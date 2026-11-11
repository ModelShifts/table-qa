"""Compare answers with the ground truth in ``samples/questions.json``.

    python scripts/evaluate.py
    python scripts/evaluate.py --out eval.json

A value counts as correct when it matches the truth. Strings are compared with
the truth as a whole word, case-insensitively. Numbers within 0.05. Dates by
their ``YYYY-MM-DD`` prefix. "Prose" counts when the sentence also states that
value. "Chart" counts when a chart was drawn for a comparison question, and
when a single-number question correctly drew none.

The script always exits 0 after printing the table. A wrong answer is a result,
not a crash.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from table_qa.config import Settings
from table_qa.pipeline import run_question

ROOT = Path(__file__).resolve().parent.parent


def same_text(pred, truth: str) -> bool:
    def norm(value) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()

    got, want = norm(pred), norm(truth)
    if not want:
        return got == want
    return got == want or f" {want} " in f" {got} "


def same(pred, truth, kind: str) -> bool:
    if kind == "number":
        try:
            return abs(float(pred) - float(truth)) <= 0.05
        except (TypeError, ValueError):
            return False
    if kind == "date":
        return str(pred)[:10] == str(truth)[:10]
    return same_text(pred, str(truth))


def prose_mentions(prose: str, truth, kind: str) -> bool:
    if kind == "number":
        try:
            number = float(truth)
        except (TypeError, ValueError):
            return False
        compact = str(int(number)) if number.is_integer() else str(number)
        return compact in str(prose).replace(",", "")
    if kind == "date":
        return str(truth)[:10] in str(prose)
    return same_text(prose, str(truth))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", default=str(ROOT / "samples"))
    parser.add_argument("--out")
    parser.add_argument("--only", help="run one question id")
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.validate()
    spec = json.loads((Path(args.samples) / "questions.json").read_text())
    questions = spec["questions"]
    if args.only:
        questions = [item for item in questions if item["id"] == args.only]
        if not questions:
            print(f"no question with id {args.only}", file=sys.stderr)
            return 2
    rows, raw = [], []
    totals = {"value": 0, "prose": 0, "chart": 0, "n": 0}
    for item in questions:
        path = Path(args.samples) / item["file"]
        started = time.time()
        try:
            result = run_question(path, item["question"], settings)
        except Exception as exc:  # report and keep going
            rows.append((item["id"], "error", "no", "no", time.time() - started, str(exc)))
            totals["n"] += 1
            raw.append({"id": item["id"], "error": str(exc)})
            print(f"{item['id']}: error: {exc}", file=sys.stderr)
            continue
        value_ok = bool(result.ok) and same(result.value, item["answer"], item["type"])
        prose_ok = bool(result.ok) and prose_mentions(result.answer, item["answer"], item["type"])
        chart_ok = bool(result.chart_png) == bool(item["expect_chart"])
        totals["value"] += int(value_ok)
        totals["prose"] += int(prose_ok)
        totals["chart"] += int(chart_ok)
        totals["n"] += 1
        detail = "" if value_ok else f"got {result.value!r}, want {item['answer']!r}"
        if result.error and not result.ok:
            detail = result.error.splitlines()[-1][:180]
        rows.append(
            (
                item["id"],
                "yes" if value_ok else "no",
                "yes" if prose_ok else "no",
                "yes" if chart_ok else "no",
                time.time() - started,
                detail,
            )
        )
        raw.append(
            {
                "id": item["id"],
                "file": item["file"],
                "question": item["question"],
                "expected": item["answer"],
                "value": result.value,
                "answer": result.answer,
                "value_ok": value_ok,
                "prose_ok": prose_ok,
                "chart": bool(result.chart_png),
                "chart_ok": chart_ok,
                "steps": result.steps,
                "code": result.code,
                "error": result.error,
                "elapsed": round(result.elapsed, 3),
                "model": result.model,
                "backend": result.backend,
                "answer_source": result.answer_source,
            }
        )
        print(
            f"{item['id']}: value={'yes' if value_ok else 'no'} prose={'yes' if prose_ok else 'no'} "
            f"chart={'yes' if chart_ok else 'no'} {time.time() - started:.1f}s",
            file=sys.stderr,
        )

    print(f"\nBackend: {settings.backend}, model: {settings.model_name}\n")
    print("| Question | Value | Prose | Chart | Time (s) | Detail |")
    print("|---|---|---|---|---|---|")
    for qid, value, prose, chart, elapsed, detail in rows:
        print(f"| {qid} | {value} | {prose} | {chart} | {elapsed:.1f} | {detail or '-'} |")
    n = max(totals["n"], 1)
    print(
        f"| **All** | **{totals['value']}/{totals['n']}** | {totals['prose']}/{totals['n']} | "
        f"{totals['chart']}/{totals['n']} | | |"
    )
    if args.out:
        Path(args.out).write_text(json.dumps({"model": settings.model_name, "backend": settings.backend, "results": raw}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
