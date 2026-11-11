"""Ask one question: profile the file, generate code, run it, draw a chart, write the sentence."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .chart import render_chart
from .config import Settings
from .llm import get_llm, release_models
from .profile import Profile, profile_file
from .prompts import (
    answer_messages,
    code_messages,
    code_problem,
    ensure_answer,
    parse_reply,
    prefer_idxmax,
    wants_chart,
    which_shape,
)
from .sandbox import SandboxResult, run_in_sandbox

# Bump when the prompt or the result shape changes, so the demo cache does not
# replay a result from an older prompt.
PROMPT_VERSION = "4"


@dataclass
class QueryResult:
    ok: bool
    question: str
    source: str
    value: object = None
    answer: str = ""
    steps: list[str] = field(default_factory=list)
    code: str = ""
    script: str = ""
    chart_png: bytes | None = None
    chart_title: str | None = None
    model: str = ""
    backend: str = ""
    error: str | None = None
    elapsed: float = 0.0
    answer_source: str = ""
    cached: bool = False

    def to_json_dict(self) -> dict:
        import base64

        return {
            "ok": self.ok,
            "question": self.question,
            "source": self.source,
            "value": self.value,
            "answer": self.answer,
            "steps": self.steps,
            "code": self.code,
            "script": self.script,
            "chart_png_b64": base64.b64encode(self.chart_png).decode("ascii") if self.chart_png else None,
            "chart_title": self.chart_title,
            "model": self.model,
            "backend": self.backend,
            "error": self.error,
            "elapsed": round(self.elapsed, 3),
            "answer_source": self.answer_source,
        }

    @classmethod
    def from_json_dict(cls, data: dict) -> "QueryResult":
        import base64

        raw = data.get("chart_png_b64")
        return cls(
            ok=bool(data.get("ok")),
            question=data.get("question", ""),
            source=data.get("source", ""),
            value=data.get("value"),
            answer=data.get("answer", ""),
            steps=list(data.get("steps") or []),
            code=data.get("code", ""),
            script=data.get("script", ""),
            chart_png=base64.b64decode(raw) if raw else None,
            chart_title=data.get("chart_title"),
            model=data.get("model", ""),
            backend=data.get("backend", ""),
            error=data.get("error"),
            elapsed=float(data.get("elapsed") or 0),
            answer_source=data.get("answer_source", ""),
            cached=True,
        )


def file_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def format_value(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    if isinstance(value, float):
        if abs(value - round(value)) < 1e-9:
            return f"{int(round(value)):,}"
        return f"{value:,.2f}"
    if isinstance(value, list) and value and isinstance(value[0], dict):
        columns = list(value[0].keys())
        header = "| " + " | ".join(str(col) for col in columns) + " |"
        rule = "| " + " | ".join("---" for _ in columns) + " |"
        body = ["| " + " | ".join("" if row.get(col) is None else str(row.get(col)) for col in columns) + " |" for row in value[:12]]
        return "\n".join([header, rule, *body])
    if value is None:
        return ""
    return str(value)


def run_question(path: str | Path, question: str, settings: Settings) -> QueryResult:
    settings.validate()
    if not question or not question.strip():
        raise ValueError("question is empty")
    started = time.time()
    profile = profile_file(path)
    code_llm = get_llm(settings, "code")
    parsed_steps: list[str] = []
    parsed_code = ""
    sandbox: SandboxResult | None = None
    saved: SandboxResult | None = None
    saved_steps: list[str] = []
    saved_code = ""
    error: str | None = None
    chart_nudge = False
    for _attempt in range(3):
        raw = code_llm.complete(
            code_messages(question, profile, error),
            max_new_tokens=settings.max_new_tokens,
            stop=["\nEND"],
        )
        parsed = parse_reply(raw)
        if parsed is None:
            error = "Could not find a STEPS block and a CODE block. Reply in the requested shape and set answer."
            continue
        parsed_steps, parsed_code = parsed
        problem = code_problem(parsed_code, question)
        if problem:
            error = problem
            continue
        parsed_code = ensure_answer(prefer_idxmax(parsed_code, question))
        sandbox = run_in_sandbox(parsed_code, path, settings.sandbox_timeout, profile)
        if not sandbox.ok:
            if sandbox.error and sandbox.error.startswith("Timed out"):
                break
            error = sandbox.error or "the code failed"
            continue
        if _asks_which(question) and isinstance(sandbox.answer, (int, float)) and not isinstance(sandbox.answer, bool):
            error = "The question asks for a name. Use idxmax, not max().\n" + which_shape(question)
            continue
        if wants_chart(question) and not sandbox.chart_rows and not chart_nudge:
            saved, saved_steps, saved_code = sandbox, parsed_steps, parsed_code
            chart_nudge = True
            error = (
                "The value was computed, but this comparison needs a chart. "
                "Keep the same answer. Also set chart_df to the grouped table, "
                "chart_type to \"bar\", chart_x to the category column, chart_y to the numeric column, "
                "and chart_title to a short title. Do not set chart_type to \"none\"."
            )
            continue
        break
    if (sandbox is None or not sandbox.ok) and saved is not None and saved.ok:
        sandbox, parsed_steps, parsed_code = saved, saved_steps, saved_code
    script = _script(profile, parsed_code, Path(path).name)
    if sandbox is None or not sandbox.ok:
        return QueryResult(
            ok=False,
            question=question.strip(),
            source=str(path),
            steps=parsed_steps,
            code=parsed_code,
            script=script,
            model=settings.model_name,
            backend=settings.backend,
            error=(sandbox.error if sandbox else error) or "the analysis did not run",
            elapsed=time.time() - started,
        )
    chart = _safe_chart(sandbox)
    prose, answer_source = _write_answer(settings, question, sandbox.answer, parsed_steps)
    return QueryResult(
        ok=True,
        question=question.strip(),
        source=str(path),
        value=sandbox.answer,
        answer=prose,
        steps=parsed_steps or ["Run the analysis code."],
        code=parsed_code,
        script=script,
        chart_png=chart,
        chart_title=sandbox.chart_title,
        model=settings.model_name,
        backend=settings.backend,
        elapsed=time.time() - started,
        answer_source=answer_source,
    )


def _asks_which(question: str) -> bool:
    q = question.lower()
    return "which " in q or q.startswith("which")


def _script(profile: Profile, code: str, display_name: str) -> str:
    body = code.rstrip() + "\n\nprint(answer)\n"
    return profile.load_preamble(display_name) + body


def _safe_chart(sandbox: SandboxResult) -> bytes | None:
    try:
        return render_chart(sandbox.chart_rows, sandbox.chart_type, sandbox.chart_x, sandbox.chart_y, sandbox.chart_title)
    except Exception:
        return None


def _write_answer(settings: Settings, question: str, value: object, steps: list[str]) -> tuple[str, str]:
    text = format_value(value)
    if settings.backend == "hf" and settings.code_model_name != settings.answer_model_name:
        release_models()
    try:
        reply = get_llm(settings, "answer").complete(
            answer_messages(question, text, steps),
            max_new_tokens=min(200, settings.max_new_tokens),
        )
    except Exception:
        return f"The result is {text}.", "fallback"
    cleaned = _clean_prose(reply)
    if not cleaned:
        return f"The result is {text}.", "fallback"
    # A name or other non-numeric value should not pick up amounts the code did not compute.
    if isinstance(value, str) and not any(ch.isdigit() for ch in value) and re.search(r"\d", cleaned):
        return f"The result is {text}.", "fallback"
    return cleaned, "model"


def _clean_prose(reply: str) -> str:
    text = reply.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
    # Drop a label the model sometimes adds.
    for prefix in ("Answer:", "Final answer:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix) :].strip()
    return text.strip().strip('"')


class ResultCache:
    """Small JSON cache keyed by file content, question and model. Used by the web demo."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, path: str | Path, question: str, settings: Settings) -> Path:
        tag = hashlib.sha256(
            f"ask|{question.strip()}|{settings.backend}|{settings.model_name}|{PROMPT_VERSION}".encode()
        ).hexdigest()[:16]
        return self.root / f"{file_digest(path)}-ask-{tag}.json"

    def get(self, path, question: str, settings: Settings) -> QueryResult | None:
        file = self._path(path, question, settings)
        if not file.exists():
            return None
        result = QueryResult.from_json_dict(json.loads(file.read_text()))
        result.cached = True
        return result

    def put(self, path, question: str, settings: Settings, result: QueryResult) -> None:
        file = self._path(path, question, settings)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(result.to_json_dict(), indent=2))
