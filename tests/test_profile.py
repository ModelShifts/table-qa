import hashlib

import pandas as pd

from table_qa.profile import detect_header_row, detect_separator, profile_file


def _digest(path):
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mode, stat.st_mtime_ns


def test_header_row_skips_title_and_blank():
    raw = pd.DataFrame(
        [
            ["Synthetic sales (fictional)", None, None],
            [None, None, None],
            ["order_date", "region", "revenue"],
            ["2025-01-15", "North", 10],
        ]
    )
    assert detect_header_row(raw) == 2


def test_sample_workbook_profile(samples):
    path = samples / "sales.xlsx"
    before = _digest(path)
    profile = profile_file(path)
    assert _digest(path) == before
    by_name = {sheet.name: sheet for sheet in profile.sheets}
    assert by_name["sales"].header_row == 2
    assert by_name["returns"].header_row == 0
    assert "order_date" in by_name["sales"].date_columns
    assert "return_date" in by_name["returns"].date_columns
    assert by_name["sales"].rows == 252
    assert "Latest quarter" in by_name["sales"].prompt_block()
    assert "header=2" in profile.load_preamble("sales.xlsx")
    assert "sheet_name='returns'" in profile.load_preamble("sales.xlsx")


def test_sample_csv_matches_sheet(samples):
    path = samples / "sales.csv"
    before = _digest(path)
    profile = profile_file(path)
    assert _digest(path) == before
    assert profile.kind == "csv" and profile.sep == ","
    sheet = profile.sheets[0]
    assert sheet.name == "sales" and sheet.header_row == 1 and sheet.rows == 252
    assert "order_date" in sheet.date_columns


def test_semicolon_csv(tmp_path):
    path = tmp_path / "units.csv"
    path.write_text("region;units\nEast;2\nNorth;5\n")
    assert detect_separator(path) == ";"
    profile = profile_file(path)
    assert profile.sep == ";"
    assert profile.sheets[0].rows == 2
    assert [column["name"] for column in profile.sheets[0].columns] == ["region", "units"]


def test_rejects_unknown_type(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    try:
        profile_file(path)
    except ValueError as exc:
        assert ".txt" in str(exc)
    else:
        raise AssertionError("expected ValueError")
