"""Write the synthetic spreadsheets in ``samples/`` and their ground truth.

Every name and figure is fictional. The expected answers are computed from the
files after they are written, using the same loader the app uses, so the truth
file matches what a question actually sees.

    python scripts/make_samples.py
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from table_qa.profile import load_tables, profile_file

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

PRICES = {"Ash": 10, "Birch": 20, "Cedar": 5}
BASE = {
    "North": {"Ash": 40, "Birch": 10, "Cedar": 20},
    "East": {"Ash": 10, "Birch": 12, "Cedar": 8},
    "South": {"Ash": 16, "Birch": 14, "Cedar": 20},
    "West": {"Ash": 14, "Birch": 8, "Cedar": 10},
}
# 2026 Q3 only. East's jump is the point of the "grew fastest" question.
Q3_2026 = {
    "North": {"Ash": 44, "Birch": 11, "Cedar": 22},
    "East": {"Ash": 25, "Birch": 30, "Cedar": 20},
    "South": {"Ash": 18, "Birch": 15, "Cedar": 21},
    "West": {"Ash": 12, "Birch": 7, "Cedar": 9},
}
RETURNS = [
    (date(2026, 3, 2), "South", "Ash", 5),
    (date(2026, 4, 11), "South", "Birch", 6),
    (date(2026, 5, 20), "South", "Cedar", 4),
    (date(2026, 7, 8), "South", "Ash", 7),
    (date(2026, 8, 19), "South", "Birch", 8),
    (date(2026, 2, 14), "East", "Ash", 3),
    (date(2026, 6, 3), "East", "Cedar", 2),
    (date(2026, 1, 22), "North", "Birch", 4),
    (date(2026, 5, 5), "West", "Ash", 3),
    (date(2026, 9, 1), "West", "Cedar", 3),
]


def months() -> list[date]:
    found = []
    year, month = 2025, 1
    while (year, month) <= (2026, 9):
        found.append(date(year, month, 15))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return found


def sales_frame() -> pd.DataFrame:
    rows = []
    for day in months():
        table = Q3_2026 if (day.year, day.month) >= (2026, 7) else BASE
        for region in ("North", "East", "South", "West"):
            for product in ("Ash", "Birch", "Cedar"):
                units = table[region][product]
                price = PRICES[product]
                rows.append((day, region, product, units, price, units * price))
    frame = pd.DataFrame(rows, columns=["order_date", "region", "product", "units", "unit_price", "revenue"])
    return frame.sort_values(["order_date", "region", "product"]).reset_index(drop=True)


def returns_frame() -> pd.DataFrame:
    frame = pd.DataFrame(RETURNS, columns=["return_date", "region", "product", "units"])
    return frame.sort_values(["return_date", "region", "product"]).reset_index(drop=True)


def write_xlsx(path: Path, sales: pd.DataFrame, returns: pd.DataFrame) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "sales"
    sheet["A1"] = "Synthetic sales (fictional)"
    _write_frame(sheet, sales, header_row=3)
    other = book.create_sheet("returns")
    _write_frame(other, returns, header_row=1)
    book.properties.creator = "table-qa"
    book.properties.lastModifiedBy = "table-qa"
    book.properties.title = "Synthetic sales"
    book.properties.subject = "Fictional spreadsheet for the table-qa demo"
    book.properties.description = "Synthetic sales data. No real customers or companies."
    book.properties.created = datetime(2026, 1, 1)
    book.properties.modified = datetime(2026, 1, 1)
    book.properties.keywords = "synthetic"
    book.save(path)
    _freeze_zip(path)


def _write_frame(sheet, frame: pd.DataFrame, header_row: int) -> None:
    for col, name in enumerate(frame.columns, start=1):
        sheet.cell(header_row, col, str(name))
    for offset, record in enumerate(frame.itertuples(index=False), start=1):
        for col, value in enumerate(record, start=1):
            cell = sheet.cell(header_row + offset, col, value if not hasattr(value, "item") else value.item())
            if isinstance(value, date) and not isinstance(value, datetime):
                cell.number_format = "YYYY-MM-DD"


def write_csv(path: Path, sales: pd.DataFrame) -> None:
    copy = sales.copy()
    copy["order_date"] = copy["order_date"].map(lambda day: day.strftime("%Y-%m-%d"))
    body = copy.to_csv(index=False, lineterminator="\n")
    # A title line, then the header. (The workbook also has a blank row; CSV readers
    # drop blank lines, so the csv title sits directly above the header.)
    path.write_text("Synthetic sales (fictional)\n" + body, encoding="utf-8")


def _freeze_zip(path: Path) -> None:
    """Rewrite the xlsx so timestamps and the library version do not depend on the machine."""
    import io
    import re
    import zipfile

    fixed = (2026, 1, 1, 0, 0, 0)
    buffer = io.BytesIO()
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for info in sorted(source.infolist(), key=lambda item: item.filename):
            data = source.read(info.filename)
            if info.filename.endswith(".xml"):
                text = data.decode("utf-8")
                text = re.sub(r"openpyxl/[0-9.]+", "openpyxl", text)
                if info.filename == "docProps/core.xml":
                    text = re.sub(
                        r"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                        r"\g<1>2026-01-01T00:00:00Z\g<2>",
                        text,
                    )
                data = text.encode("utf-8")
            new = zipfile.ZipInfo(filename=info.filename, date_time=fixed)
            new.compress_type = zipfile.ZIP_DEFLATED
            new.external_attr = info.external_attr
            out.writestr(new, data)
    path.write_bytes(buffer.getvalue())


def _loaded(path: Path) -> dict[str, pd.DataFrame]:
    profile = profile_file(path)
    return load_tables(path, profile.meta(path.name))


def compute(sales: pd.DataFrame, returns: pd.DataFrame) -> dict:
    latest = pd.to_datetime(sales["order_date"]).max().strftime("%Y-%m-%d")
    total = int(sales["revenue"].sum())
    top_region = sales.groupby("region")["revenue"].sum().idxmax()
    top_product = sales.groupby("product")["units"].sum().idxmax()
    dated = sales.copy()
    dated["order_date"] = pd.to_datetime(dated["order_date"])
    dated["quarter"] = dated["order_date"].dt.to_period("Q")
    last_q = dated["quarter"].max()
    previous = last_q - 1
    current = dated[dated["quarter"] == last_q].groupby("region")["revenue"].sum()
    prior = dated[dated["quarter"] == previous].groupby("region")["revenue"].sum()
    fastest = ((current - prior) / prior).idxmax()
    most_returns = returns.groupby("region")["units"].sum().idxmax()
    if not (fastest == "East" and top_region == "North" and top_product == "Ash" and most_returns == "South"):
        raise SystemExit(
            f"sample no longer has the intended distinct answers: growth={fastest}, "
            f"region={top_region}, product={top_product}, returns={most_returns}"
        )
    if fastest == top_region or fastest == most_returns or top_region == most_returns:
        raise SystemExit("the three 'which region' answers should be different")
    return {
        "latest_order_date": latest,
        "total_revenue": total,
        "top_region": str(top_region),
        "top_product": str(top_product),
        "fastest_growth": str(fastest),
        "most_returns": str(most_returns),
        "last_quarter": str(last_q),
        "previous_quarter": str(previous),
    }


def questions(facts: dict) -> dict:
    def row(qid, file, question, type_, answer, chart):
        return {
            "id": qid,
            "file": file,
            "question": question,
            "type": type_,
            "answer": answer,
            "expect_chart": chart,
        }

    total = facts["total_revenue"]
    return {
        "note": "Synthetic data generated by scripts/make_samples.py. Names and figures are fictional.",
        "definitions": {
            "last_quarter": "the calendar quarter of the maximum order_date",
            "grew_fastest": "(revenue in the latest quarter - revenue in the previous quarter) / revenue in the previous quarter",
            "last_quarter_in_sample": facts["last_quarter"],
            "previous_quarter_in_sample": facts["previous_quarter"],
        },
        "questions": [
            row("latest_order_date", "sales.xlsx", "What is the latest order date?", "date", facts["latest_order_date"], False),
            row("total_revenue", "sales.xlsx", "What is the total revenue?", "number", total, False),
            row("top_region", "sales.xlsx", "Which region has the highest total revenue?", "string", facts["top_region"], True),
            row("top_product", "sales.xlsx", "Which product sold the most units?", "string", facts["top_product"], True),
            row("fastest_growth", "sales.xlsx", "Which region grew fastest last quarter?", "string", facts["fastest_growth"], True),
            row("most_returns", "sales.xlsx", "Which region has the most returned units?", "string", facts["most_returns"], True),
            row("csv_total_revenue", "sales.csv", "What is the total revenue?", "number", total, False),
        ],
    }


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    sales, returns = sales_frame(), returns_frame()
    write_xlsx(SAMPLES / "sales.xlsx", sales, returns)
    write_csv(SAMPLES / "sales.csv", sales)
    xlsx_tables = _loaded(SAMPLES / "sales.xlsx")
    csv_tables = _loaded(SAMPLES / "sales.csv")
    facts = compute(xlsx_tables["sales"], xlsx_tables["returns"])
    csv_total = int(csv_tables["sales"]["revenue"].sum())
    if csv_total != facts["total_revenue"]:
        raise SystemExit(f"csv total {csv_total} does not match xlsx total {facts['total_revenue']}")
    if profile_file(SAMPLES / "sales.xlsx").sheets[0].header_row != 2:
        raise SystemExit("sales sheet header was not detected on row 3")
    if profile_file(SAMPLES / "sales.csv").sheets[0].header_row != 1:
        raise SystemExit("csv header was not detected on row 2")
    payload = questions(facts)
    (SAMPLES / "questions.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {SAMPLES} ({facts['total_revenue']} revenue, fastest {facts['fastest_growth']})")


if __name__ == "__main__":
    main()
