"""Draw the chart the analysis code asked for.

Bar and line charts only, in the showcase colours. The chart is rendered in
the parent process from the rows the sandbox returned, so the model code does
not need a display.
"""

from __future__ import annotations

from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

PAPER = "#faf7f0"
INK = "#1c1a17"
RUST = "#8a3a24"
GRID = "#e4dccb"


def render_chart(
    rows: list[dict] | None,
    chart_type: str | None,
    x: str | None,
    y: str | None,
    title: str | None,
) -> bytes | None:
    if not rows or chart_type in {None, "", "none"}:
        return None
    frame = pd.DataFrame(rows)
    if frame.empty:
        return None
    x_name = x if x in frame.columns else str(frame.columns[0])
    numeric = [col for col in frame.columns if col != x_name and pd.api.types.is_numeric_dtype(frame[col])]
    y_name = y if y in frame.columns and pd.api.types.is_numeric_dtype(frame[y]) else (numeric[0] if numeric else None)
    if y_name is None:
        return None
    kind = "line" if chart_type == "line" else "bar"
    fig, ax = plt.subplots(figsize=(7.2, 4.15), dpi=120)
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    labels = ["" if value is None else str(value) for value in frame[x_name].tolist()]
    values = pd.to_numeric(frame[y_name], errors="coerce").tolist()
    if kind == "line":
        ax.plot(labels, values, color=RUST, marker="o", linewidth=2.2)
    else:
        ax.bar(labels, values, color=RUST, width=0.72)
    ax.set_title(title or f"{y_name} by {x_name}", color=INK, fontsize=14, pad=12, fontname="DejaVu Serif")
    ax.set_xlabel(x_name, color=INK)
    ax.set_ylabel(y_name, color=INK)
    ax.tick_params(colors=INK, labelsize=9)
    for label in ax.get_xticklabels():
        label.set_fontname("DejaVu Sans")
        if len(labels) > 6:
            label.set_rotation(30)
            label.set_ha("right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(INK)
    ax.spines["bottom"].set_color(INK)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    buffer = BytesIO()
    fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buffer.getvalue()
