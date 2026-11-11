"""Local web demo (Gradio): pick or upload a spreadsheet, ask a question, see the answer, chart and steps."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import __version__
from .config import Settings
from .pipeline import QueryResult, ResultCache, format_value, run_question
from .profile import profile_file

EXAMPLES = [
    "Which region grew fastest last quarter?",
    "Which region has the highest total revenue?",
    "What is the total revenue?",
    "Which product sold the most units?",
    "Which region has the most returned units?",
]


def display_model(name: str) -> str:
    text = name.replace("\\", "/").split("/")[-1]
    if text.endswith(".gguf"):
        text = text[: -len(".gguf")]
    return text


def samples_dir() -> Path:
    for folder in (Path.cwd() / "samples", Path(__file__).resolve().parents[2] / "samples"):
        if folder.is_dir():
            return folder
    return Path.cwd() / "samples"


def list_samples() -> list[str]:
    folder = samples_dir()
    names = [p.name for p in folder.iterdir() if p.suffix.lower() in {".xlsx", ".csv"}] if folder.is_dir() else []
    return sorted(names)


def profile_markdown(path: str | Path | None) -> str:
    if not path:
        return "Pick a synthetic sample or upload a .xlsx or .csv file."
    try:
        profile = profile_file(path)
    except (OSError, ValueError) as exc:
        return f"Could not read the file. {exc}"
    blocks = []
    for sheet in profile.sheets:
        columns = ", ".join(column["name"] for column in sheet.columns)
        blocks.append(
            f"**{sheet.name}** — header on row {sheet.header_row + 1}, {sheet.rows} rows. {columns}"
        )
    return "\n\n".join(blocks)


def steps_markdown(steps: list[str]) -> str:
    if not steps:
        return ""
    return "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))


def answer_markdown(result: QueryResult) -> str:
    if not result.ok:
        return ""
    lines = [f"**{format_value(result.value)}**", ""]
    if result.answer:
        lines.append(result.answer)
        lines.append("")
    wording = result.answer_source or "model"
    lines.append(f"<span class='ms-muted'>Model: {result.model} · Wording: {wording}</span>")
    return "\n".join(lines)


def status_markdown(result: QueryResult, settings: Settings) -> str:
    if result.cached:
        return (
            f"Loaded a saved result for this file and question, computed earlier by `{display_model(result.model)}`."
        )
    if not result.ok:
        return f"The analysis did not finish. {result.error}"
    return f"Computed with `{display_model(result.model)}` ({settings.backend} backend) in {result.elapsed:.1f}s."


def write_chart(result: QueryResult, folder: Path) -> str | None:
    if not result.chart_png:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "chart.png"
    path.write_bytes(result.chart_png)
    return str(path)


CSS = """
:root, .gradio-container { --ms-ink:#1c1a17; --ms-rust:#8a3a24; --ms-paper:#f3efe6; --ms-cream:#faf7f0; }
.gradio-container { background: var(--ms-cream) !important; font-family: Georgia, 'Times New Roman', serif !important; max-width: 1240px !important; }
.ms-header { border-bottom: 1px solid var(--ms-ink); padding: 8px 4px 10px; margin-bottom: 4px; }
.ms-brand { letter-spacing: .22em; font-size: 12px; color: var(--ms-rust); font-weight: 700; }
.ms-header h1 { font-family: Georgia, serif; font-weight: 400; font-size: 30px; margin: 2px 0 2px; color: var(--ms-ink); }
.ms-header p { margin: 0; color: #4a463f; font-style: italic; }
.ms-meta { margin-top: 6px; font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #6b665e; }
.ms-muted { color: #6b665e; font-size: 12px; }
.ms-card { background: #fff !important; border: 1px solid #ddd5c6 !important; border-radius: 10px !important; }
.ms-section-title { font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--ms-rust); margin: 2px 0; }
.ms-left { max-height: calc(100vh - 130px); min-height: 520px; overflow-y: auto !important; padding-right: 8px; scroll-behavior: smooth; flex-wrap: nowrap !important; }
.ms-left > * { flex-shrink: 0 !important; }
.ms-status, .ms-answer { font-size: 14px; }
.ms-answer strong { color: var(--ms-ink); font-size: 22px; }
.ms-secondary, button.ms-secondary { background: #fff !important; color: var(--ms-rust) !important; border: 1px solid var(--ms-rust) !important; }
button.primary, .ms-primary button { background: var(--ms-rust) !important; border-color: var(--ms-rust) !important; color: #fff !important; }
footer { display: none !important; }
"""


def build_app(settings: Settings | None = None):
    import gradio as gr

    settings = settings or Settings.from_env()
    cache = ResultCache(settings.cache_dir)
    samples = list_samples()
    chart_dir = Path(tempfile.mkdtemp(prefix="tableqa-chart-"))

    def pick_sample(name):
        if not name:
            return gr.update()
        return str(samples_dir() / name)

    def pick_upload(file):
        return (file if isinstance(file, str) else getattr(file, "name", None)), gr.update(value=None)

    def preview(path):
        if not path:
            return profile_markdown(None), "", "", "", None, ""
        return profile_markdown(path), "Type a question and press **Ask**.", "", "", None, ""

    def use_example(example):
        return example or gr.update()

    def do_ask(path, question):
        question = (question or "").strip()
        if not path or not question:
            return "Pick a spreadsheet and type a question first.", "", "", "", None, ""
        cached = cache.get(path, question, settings)
        if cached and cached.ok:
            result = cached
        else:
            try:
                result = run_question(path, question, settings)
            except Exception as exc:
                return f"The analysis did not finish. {exc}", "", "", "", None, ""
            if result.ok:
                cache.put(path, question, settings, result)
        chart = write_chart(result, chart_dir)
        code = result.script or result.code
        return (
            status_markdown(result, settings),
            answer_markdown(result),
            steps_markdown(result.steps),
            code,
            chart,
            result.chart_title or "",
        )

    with gr.Blocks(title="table-qa · Modelshifts") as demo:
        gr.HTML(
            "<div class='ms-header'><div class='ms-brand'>MODELSHIFTS</div><h1>table-qa</h1>"
            "<p>Ask a spreadsheet a question in plain language and get the answer, a chart and the steps.</p>"
            f"<div class='ms-meta'>backend: {settings.backend} · model: {display_model(settings.model_name)} · "
            f"v{__version__}</div></div>"
        )
        current = gr.State(None)
        with gr.Row(equal_height=False):
            with gr.Column(scale=5, min_width=420, elem_classes="ms-left", elem_id="ms-left"):
                gr.HTML("<div class='ms-section-title'>1 · Spreadsheet</div>")
                with gr.Row(equal_height=True):
                    sample = gr.Dropdown(
                        samples, value=None, label="Synthetic sample", interactive=True, scale=3, elem_id="ms-sample"
                    )
                    upload = gr.UploadButton(
                        "Upload .xlsx or .csv",
                        file_types=[".xlsx", ".xlsm", ".csv"],
                        type="filepath",
                        scale=1,
                        elem_classes="ms-secondary",
                    )
                profile = gr.Markdown("Pick a synthetic sample or upload a .xlsx or .csv file.")
                gr.HTML("<div class='ms-section-title'>2 · Question</div>")
                example = gr.Dropdown(EXAMPLES, value=None, label="Example question", elem_id="ms-example")
                with gr.Row(equal_height=True):
                    question = gr.Textbox(
                        placeholder="e.g. Which region grew fastest last quarter?",
                        show_label=False,
                        scale=4,
                        container=False,
                        elem_id="ms-question",
                    )
                    ask_btn = gr.Button("Ask", scale=1, variant="primary", elem_classes="ms-primary", elem_id="ms-ask")
                status = gr.Markdown("", elem_classes="ms-status")
                gr.HTML("<div class='ms-section-title'>3 · Answer</div>")
                answer = gr.Markdown("", elem_classes="ms-answer", elem_id="ms-answer")
                gr.HTML("<div class='ms-section-title'>4 · Steps</div>")
                steps = gr.Markdown("", elem_id="ms-steps")
            with gr.Column(scale=6, min_width=460):
                gr.HTML("<div class='ms-section-title'>Chart</div>")
                chart = gr.Image(
                    type="filepath",
                    show_label=False,
                    height=460,
                    interactive=False,
                    elem_classes="ms-card",
                    elem_id="ms-chart",
                    buttons=["fullscreen", "download"],
                )
                chart_caption = gr.Markdown("", elem_classes="ms-muted")
                gr.HTML("<div class='ms-section-title'>Code you can rerun</div>")
                code = gr.Code(language="python", interactive=False, lines=14, elem_id="ms-code")
        gr.HTML(
            "<p class='ms-muted'>Sample files are synthetic. Uploaded files stay on the machine running this demo. "
            "Generated code runs in a subprocess with a timeout, no network, and a read-only copy of the file.</p>"
        )

        outs = [profile, status, answer, steps, chart, code]
        sample.change(pick_sample, [sample], [current]).then(preview, [current], outs)
        upload.upload(pick_upload, [upload], [current, sample]).then(preview, [current], outs)
        example.change(use_example, [example], [question])
        ask_btn.click(do_ask, [current, question], [status, answer, steps, code, chart, chart_caption])
        question.submit(do_ask, [current, question], [status, answer, steps, code, chart, chart_caption])
    return demo


def theme():
    import gradio as gr

    return gr.themes.Base(
        primary_hue=gr.themes.colors.orange,
        neutral_hue=gr.themes.colors.stone,
        font=[gr.themes.Font("Georgia"), gr.themes.Font("Times New Roman"), gr.themes.Font("serif")],
        font_mono=[gr.themes.Font("ui-monospace"), gr.themes.Font("Menlo"), gr.themes.Font("monospace")],
        radius_size=gr.themes.sizes.radius_md,
    )


def launch(host: str = "127.0.0.1", port: int = 7860, share: bool = False) -> None:
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "0")
    demo = build_app()
    demo.queue().launch(server_name=host, server_port=port, share=share, theme=theme(), css=CSS)
