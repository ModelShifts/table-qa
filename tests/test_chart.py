from table_qa.chart import render_chart


def test_bar_chart_is_png():
    png = render_chart(
        [{"region": "East", "revenue": 3000}, {"region": "North", "revenue": 3600}],
        "bar",
        "region",
        "revenue",
        "Revenue by region",
    )
    assert png is not None and png.startswith(b"\x89PNG")
    assert len(png) > 1000


def test_no_chart_when_declined_or_empty():
    assert render_chart([{"region": "East", "revenue": 1}], "none", "region", "revenue", "t") is None
    assert render_chart([], "bar", "region", "revenue", "t") is None
    assert render_chart(None, "bar", None, None, None) is None


def test_line_chart_defaults_axes():
    png = render_chart(
        [{"quarter": "2026Q2", "revenue": 10}, {"quarter": "2026Q3", "revenue": 12}],
        "line",
        None,
        None,
        None,
    )
    assert png.startswith(b"\x89PNG")
