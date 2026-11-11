"""Command-line interface.

    table-qa ask FILE "Which region grew fastest last quarter?"
    table-qa profile FILE
    table-qa serve
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import Settings


def _settings() -> Settings:
    settings = Settings.from_env()
    settings.validate()
    return settings


def cmd_profile(args: argparse.Namespace) -> int:
    from .profile import profile_file

    profile = profile_file(args.file)
    print(f"{Path(args.file).name}  ({profile.kind})")
    for sheet in profile.sheets:
        print(f"\n{sheet.name}: header on row {sheet.header_row + 1}, {sheet.rows} data rows")
        for column in sheet.columns:
            print(f"  {column['name']}: {column['summary']}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from .pipeline import format_value, run_question

    result = run_question(args.file, args.question, _settings())
    if args.json:
        print(json.dumps(result.to_json_dict(), indent=2, ensure_ascii=False))
    else:
        if result.ok:
            print(format_value(result.value))
            print()
            if result.answer:
                print(result.answer)
                print()
        else:
            print(f"error: {result.error}", file=sys.stderr)
        if result.steps:
            print("Steps")
            for index, step in enumerate(result.steps, start=1):
                print(f"{index}. {step}")
            print()
        if result.script:
            print("Code")
            print(result.script.rstrip())
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(json.dumps(result.to_json_dict(), indent=2) + "\n")
        if result.script:
            (out / "analysis.py").write_text(result.script)
        if result.answer:
            (out / "answer.txt").write_text(result.answer + "\n")
        if result.chart_png:
            (out / "chart.png").write_bytes(result.chart_png)
            print(f"chart: {out / 'chart.png'}", file=sys.stderr)
        print(f"wrote {out}", file=sys.stderr)
    return 0 if result.ok else 2


def cmd_serve(args: argparse.Namespace) -> int:
    from .webapp import launch

    launch(host=args.host, port=args.port, share=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="table-qa",
        description="Ask a spreadsheet a question in plain language and get the answer, a chart and the steps.",
    )
    parser.add_argument("--version", action="version", version=f"table-qa {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="ask a question about one .xlsx or .csv file")
    ask.add_argument("file")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true", help="print the full result as JSON")
    ask.add_argument("--out", help="directory for result.json, analysis.py, answer.txt and chart.png")
    ask.set_defaults(func=cmd_ask)

    profile = sub.add_parser("profile", help="show detected sheets, header rows and columns")
    profile.add_argument("file")
    profile.set_defaults(func=cmd_profile)

    serve = sub.add_parser("serve", help="start the local web demo (Gradio)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7860)
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
