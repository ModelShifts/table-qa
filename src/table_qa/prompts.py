"""Prompts and the parser for the code model's reply.

The model is asked for a STEPS block and a CODE block. A JSON object with
``steps`` and ``code`` is accepted too, in case the model answers that way.
"""

from __future__ import annotations

import re

from .llm import parse_json_object
from .profile import Profile

SYSTEM_CODE = """You write a short Python script that answers a question about spreadsheet data.

Rules:
- A dict named tables is already loaded. pandas is pd and numpy is np.
- Do not import anything. Do not call read_excel, read_csv, open, or value_counts.
- Assign answer to a string, a number, or a date like 2026-09-15. Not a sentence.
- For a comparison, also set chart_df to a small DataFrame, chart_type to "bar" or "line", and chart_x, chart_y, chart_title. Otherwise set chart_type to "none".
- Start your reply with a line STEPS: and list the operations. Then a line CODE: and the Python. Then a line END.
- Do not answer with a description of the format. Write the real statements.

When the question uses these words:
- "Last quarter" is the latest calendar quarter in the date column. The profile names it and the previous quarter.
- "Grew fastest" is (revenue in the latest quarter - revenue in the previous quarter) / revenue in the previous quarter. On a returns sheet the measure is units. Use to_period("Q").
- "Highest" and "most" use the whole sheet. Sum the measure with groupby, then take idxmax. Do not filter to one quarter unless the question says last quarter.
- "Total" is one sum of the whole column. Do not group.
- "Latest date" is the maximum of the date column, formatted YYYY-MM-DD. No chart.
"""

SYSTEM_ANSWER = """You write the final sentence for a spreadsheet question.
You are given the question, the value computed from the file, and the steps that produced it.
Write one or two plain sentences. Repeat the computed value exactly.
Do not add any number, name, or date that is not in the computed value. No heading and no code.
"""


def code_messages(question: str, profile: Profile, error: str | None = None) -> list[dict[str, str]]:
    names = ", ".join(repr(sheet.name) for sheet in profile.sheets)
    parts = [
        profile.prompt_text(),
        "",
        f"Loaded sheets, already in tables: {names}.",
        "",
        f"Question: {question.strip()}",
        "",
        "Reply with STEPS, CODE and END. Do not read a file.",
    ]
    if error:
        clipped = error.strip()
        if len(clipped) > 1500:
            clipped = clipped[:1500] + "..."
        parts.extend(["", "The previous attempt failed:", clipped, "", "Reply again. Answer the same question."])
    return [{"role": "system", "content": SYSTEM_CODE}, {"role": "user", "content": "\n".join(parts)}]


def answer_messages(question: str, value_text: str, steps: list[str]) -> list[dict[str, str]]:
    step_lines = "\n".join(f"- {step}" for step in steps) or "- (none)"
    user = (
        f"Question: {question.strip()}\n"
        f"Computed value: {value_text}\n"
        f"Steps:\n{step_lines}\n"
    )
    return [{"role": "system", "content": SYSTEM_ANSWER}, {"role": "user", "content": user}]


def code_problem(code: str, question: str = "") -> str | None:
    """Return a short reason to reject code before it runs, or None if it may run.

    The checks use the wording of the question. They do not know the true answer.
    """
    lowered = code.lower()
    q = question.lower()
    if any(token in lowered for token in ("read_excel", "read_csv", "to_excel", "to_csv", "open(")):
        return (
            "Do not read or write files. `tables` is already loaded. "
            "Use tables['sheet name'] and the real column names. No read_excel and no read_csv."
        )
    if "value_counts" in lowered:
        return "Do not use value_counts. Sum the measure with groupby, then take idxmax."
    if re.search(r"\b(SHEET|CATEGORY|MEASURE|DATE)\b", code):
        return "Replace the placeholder names with the real sheet and column names from the profile."
    asks_total = "what is the total" in q or "what is the sum" in q
    asks_which = "which " in q or q.startswith("which")
    asks_growth = "grew" in q or "growth" in q or "fastest" in q
    asks_date = "date" in q and ("latest" in q or "earliest" in q or "most recent" in q)
    if asks_total and ("groupby" in lowered or "idxmax" in lowered):
        return "The question asks for one total. Sum the column. Do not group and do not pick a category."
    if asks_date and ".max(" not in lowered:
        return "Take the maximum of the date column and format it as YYYY-MM-DD. Set chart_type to \"none\"."
    if "return" in q and "returns" not in lowered:
        return "This question is about returns. Use the returns sheet in tables."
    if asks_which and not asks_growth:
        category = "product" if "product" in q else "region"
        if not re.search(rf"groupby\(\s*['\"]{category}['\"]", code):
            return "The question asks for a name.\n" + which_shape(question)
    if asks_growth and ("groupby" not in lowered or "chart_df" not in lowered):
        sheet = "returns" if "return" in q else "sales"
        date_col = "return_date" if sheet == "returns" else "order_date"
        category = "product" if "product" in q else "region"
        measure = "units" if "return" in q else "revenue"
        return (
            "Compute percentage growth with to_period('Q'). Use this shape, "
            f"with the {sheet} sheet, and set answer to the {category} name:\n"
            f"frame = tables[{sheet!r}].copy()\n"
            f"frame['quarter'] = frame[{date_col!r}].dt.to_period('Q')\n"
            "last_q = frame['quarter'].max()\n"
            f"current = frame[frame['quarter'] == last_q].groupby({category!r})[{measure!r}].sum()\n"
            f"prior = frame[frame['quarter'] == (last_q - 1)].groupby({category!r})[{measure!r}].sum()\n"
            "growth = ((current - prior) / prior)\n"
            "answer = growth.idxmax()\n"
            "chart_df = growth.rename('growth').reset_index()\n"
            "chart_type = 'bar'\n"
            f"chart_x = {category!r}\n"
            "chart_y = 'growth'\n"
            f"chart_title = 'Growth by {category}'"
        )
    return None


def which_shape(question: str) -> str:
    """A groupby shape for a "which name" question. Column choice follows the wording."""
    q = question.lower()
    sheet = "returns" if "return" in q else "sales"
    category = "product" if "product" in q else "region"
    measure = "units" if "return" in q or ("unit" in q and "revenue" not in q) else "revenue"
    return (
        f"Group tables[{sheet!r}] by {category} , sum {measure}, and set answer to the name (idxmax, not max):\n"
        f"grouped = tables[{sheet!r}].groupby({category!r}, as_index=False)[{measure!r}].sum()\n"
        f"answer = grouped.loc[grouped[{measure!r}].idxmax(), {category!r}]\n"
        "chart_df = grouped\n"
        "chart_type = 'bar'\n"
        f"chart_x = {category!r}\n"
        f"chart_y = {measure!r}\n"
        f"chart_title = '{measure} by {category}'"
    )


def wants_chart(question: str) -> bool:
    """True when the question is a comparison or a trend, so a chart is useful."""
    q = question.lower()
    keys = ("which", "compare", "grew", "growth", "fastest", "trend", "by region", "by product", "per ")
    return any(key in q for key in keys)


def _strip_fence(code: str) -> str:
    code = code.strip()
    code = re.sub(r"^```(?:python)?[^\n]*\n?", "", code)
    code = re.sub(r"\n?```$", "", code)
    # A language tag left on its own line is not Python.
    code = re.sub(r"^python\s*\n", "", code.strip(), count=1)
    return code.strip()


def prefer_idxmax(code: str, question: str) -> str:
    """A "which name" question needs the label from ``idxmax``, not the total from ``max``."""
    q = question.lower()
    if "which " not in q and not q.startswith("which"):
        return code
    if ".idxmax(" in code or ".max(" not in code:
        return code
    return code.replace(".max(", ".idxmax(")


def ensure_answer(code: str) -> str:
    """If the model assigned a result under another name, also assign ``answer``.

    The computation is unchanged. The added line is part of the code that runs
    and part of the script shown to the user.
    """
    if re.search(r"\banswer\s*=", code):
        return code
    names = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", code, re.M)
    skip = {"chart_df", "chart_type", "chart_x", "chart_y", "chart_title", "pd", "np"}
    names = [name for name in names if name not in skip]
    if not names:
        return code
    return code.rstrip() + f"\nanswer = {names[-1]}\n"


def _parse_sections(text: str) -> tuple[list[str], str] | None:
    match_steps = re.search(r"(?im)^STEPS:\s*$", text)
    match_code = re.search(r"(?im)^CODE:\s*$", text)
    if not match_steps or not match_code or match_code.start() < match_steps.start():
        return None
    steps_blob = text[match_steps.end() : match_code.start()]
    code_blob = text[match_code.end() :]
    match_end = re.search(r"(?im)^END\s*$", code_blob)
    if match_end:
        code_blob = code_blob[: match_end.start()]
    code = _strip_fence(code_blob)
    if code.strip() in {"python statements", "python", "<python>"} or len(code.strip()) < 8:
        return None
    steps: list[str] = []
    for line in steps_blob.splitlines():
        line = line.strip()
        line = re.sub(r"^([-*]|\d+[.)])\s+", "", line)
        if line:
            steps.append(line)
    if not code:
        return None
    return steps, code


def _parse_json_code(text: str) -> tuple[list[str], str] | None:
    if "{" not in text or "code" not in text.lower():
        return None
    try:
        obj = parse_json_object(text)
    except (ValueError, TypeError):
        return None
    code = obj.get("code")
    if not isinstance(code, str) or not code.strip():
        return None
    raw_steps = obj.get("steps") or []
    steps = [str(step).strip() for step in raw_steps if str(step).strip()] if isinstance(raw_steps, list) else []
    return steps, _strip_fence(code)


def _parse_fence(text: str) -> tuple[list[str], str] | None:
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    if not match:
        return None
    code = _strip_fence(match.group(1))
    if len(code) < 8:
        return None
    return ["Run the analysis."], code


def parse_reply(text: str) -> tuple[list[str], str] | None:
    """Return ``(steps, code)`` from a model reply, or ``None`` if it cannot be read."""
    if not text or not text.strip():
        return None
    text = text.replace("\r\n", "\n")
    return _parse_sections(text) or _parse_json_code(text) or _parse_fence(text)
