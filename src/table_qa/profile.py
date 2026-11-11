"""Read a CSV or Excel file, find the header row, and describe the sheets.

The description is what the model sees. It lists columns, types, a few sample
rows and the latest quarter. It does not include totals, so the model still
has to compute the answer.
"""

from __future__ import annotations

import csv
import math
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

SUPPORTED = {".csv", ".xlsx", ".xlsm"}
_MAX_SAMPLE = 3
_MAX_LEVELS = 12


@dataclass
class SheetProfile:
    name: str
    header_row: int
    rows: int
    columns: list[dict]
    date_columns: list[str]
    sample: list[dict] = field(default_factory=list)

    def prompt_block(self) -> str:
        human_row = self.header_row + 1
        lines = [f"Sheet `{self.name}` (header on row {human_row}, {self.rows} data rows):"]
        for col in self.columns:
            lines.append(f"- {col['name']}: {col['summary']}")
        if self.sample:
            lines.append("Sample rows: " + _compact(self.sample))
        return "\n".join(lines)


@dataclass
class Profile:
    source: Path
    kind: str
    sep: str
    sheets: list[SheetProfile]

    def meta(self, filename: str) -> dict:
        return {
            "filename": filename,
            "kind": self.kind,
            "sep": self.sep,
            "sheets": [
                {"name": sheet.name, "header_row": sheet.header_row, "date_columns": sheet.date_columns}
                for sheet in self.sheets
            ],
        }

    def prompt_text(self) -> str:
        body = "\n\n".join(sheet.prompt_block() for sheet in self.sheets)
        return f"File kind: {self.kind}\n\n{body}"

    def load_preamble(self, display_name: str) -> str:
        """Python that rebuilds ``tables`` from the file. This is the rerunnable script header."""
        lines = ["import pandas as pd", "import numpy as np", "", "def load_tables(path):", "    tables = {}"]
        for sheet in self.sheets:
            if self.kind == "csv":
                lines.append(
                    f"    tables[{sheet.name!r}] = pd.read_csv(path, header={sheet.header_row}, sep={self.sep!r})"
                )
            else:
                lines.append(
                    "    tables[{name!r}] = pd.read_excel(path, sheet_name={name!r}, header={header})".format(
                        name=sheet.name, header=sheet.header_row
                    )
                )
            for col in sheet.date_columns:
                lines.append(
                    f"    tables[{sheet.name!r}][{col!r}] = pd.to_datetime(tables[{sheet.name!r}][{col!r}])"
                )
        lines += ["    return tables", "", f"tables = load_tables({display_name!r})", ""]
        return "\n".join(lines)


def profile_file(path: str | Path) -> Profile:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"no such file: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"unsupported file type {suffix or '(none)'}; use .xlsx or .csv")
    if suffix == ".csv":
        sep = detect_separator(source)
        raw = _read_raw_csv(source, sep)
        header_row = detect_header_row(raw)
        date_columns = _date_columns_csv(source, sep, header_row)
        sheet = _describe_frame(source.stem, header_row, load_tables(source, _single_meta(source.stem, "csv", sep, header_row, date_columns))[source.stem], date_columns)
        return Profile(source=source, kind="csv", sep=sep, sheets=[sheet])
    frames = pd.read_excel(source, header=None, sheet_name=None, engine="openpyxl")
    if not frames:
        raise ValueError(f"{source.name} has no sheets")
    sheets: list[SheetProfile] = []
    meta_sheets = []
    for name, raw in frames.items():
        header_row = detect_header_row(raw)
        meta_sheets.append({"name": str(name), "header_row": header_row, "date_columns": []})
    # First pass loads with no date list, then we detect dates on the loaded frames
    # and reload so datetime columns are real timestamps. Excel often parses them already.
    loaded = load_tables(source, {"filename": source.name, "kind": "xlsx", "sep": ",", "sheets": meta_sheets})
    for spec in meta_sheets:
        frame = loaded[spec["name"]]
        spec["date_columns"] = _date_columns_frame(frame)
    loaded = load_tables(source, {"filename": source.name, "kind": "xlsx", "sep": ",", "sheets": meta_sheets})
    for spec in meta_sheets:
        sheets.append(_describe_frame(spec["name"], spec["header_row"], loaded[spec["name"]], spec["date_columns"]))
    return Profile(source=source, kind="xlsx", sep=",", sheets=sheets)


def load_tables(path: str | Path, meta: dict) -> dict[str, pd.DataFrame]:
    """Load every sheet the way the rerunnable script does."""
    path = Path(path)
    tables: dict[str, pd.DataFrame] = {}
    for spec in meta["sheets"]:
        if meta["kind"] == "csv":
            frame = pd.read_csv(path, header=spec["header_row"], sep=meta.get("sep") or ",")
        else:
            frame = pd.read_excel(path, sheet_name=spec["name"], header=spec["header_row"], engine="openpyxl")
        frame = frame.dropna(axis=0, how="all").dropna(axis=1, how="all")
        frame.columns = _clean_headers(list(frame.columns))
        for col in spec.get("date_columns") or []:
            if col in frame.columns:
                frame[col] = pd.to_datetime(frame[col])
        tables[spec["name"]] = frame.reset_index(drop=True)
    return tables


def detect_separator(path: Path) -> str:
    sample = path.read_text(encoding="utf-8", errors="replace")[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        sep = dialect.delimiter
    except csv.Error:
        sep = ","
    if sep not in ",;\t|":
        sep = ","
    # A title line can confuse the sniffer. Keep the separator only if some row has several cells.
    counts = [line.count(sep) for line in sample.splitlines() if line.strip()]
    if max(counts, default=0) < 1:
        return ","
    return sep


def _read_raw_csv(path: Path, sep: str) -> pd.DataFrame:
    """Read a CSV without assuming a rectangular header, so a title line is kept."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle, delimiter=sep))
    width = max((len(row) for row in rows), default=0)
    padded = [row + [None] * (width - len(row)) for row in rows]
    return pd.DataFrame(padded)


def detect_header_row(raw: pd.DataFrame) -> int:
    """Return the 0-based row index of the header.

    Title rows (a single cell) and blank rows are skipped. A header row has at
    least two text cells and is mostly text rather than numbers or dates.
    """
    limit = min(10, len(raw))
    for i in range(limit):
        row = raw.iloc[i].tolist()
        nonempty = [value for value in row if not _is_empty(value)]
        if len(nonempty) < 2:
            continue
        headers = [value for value in nonempty if _is_header_cell(value)]
        if len(headers) >= 2 and len(headers) / len(nonempty) >= 0.6:
            return i
    return 0


def _single_meta(name: str, kind: str, sep: str, header_row: int, date_columns: list[str]) -> dict:
    return {
        "filename": name,
        "kind": kind,
        "sep": sep,
        "sheets": [{"name": name, "header_row": header_row, "date_columns": date_columns}],
    }


def _date_columns_csv(path: Path, sep: str, header_row: int) -> list[str]:
    frame = pd.read_csv(path, header=header_row, sep=sep)
    frame.columns = _clean_headers(list(frame.columns))
    return _date_columns_frame(frame)


def _date_columns_frame(frame: pd.DataFrame) -> list[str]:
    found = []
    for name in frame.columns:
        series = frame[name]
        if pd.api.types.is_datetime64_any_dtype(series):
            found.append(str(name))
            continue
        if series.dtype != object and not pd.api.types.is_string_dtype(series):
            continue
        parsed = _parse_dates(series)
        seen = series.map(_is_empty) if series.dtype == object else series.isna()
        usable = int((~seen).sum())
        if usable and parsed.notna().sum() / usable >= 0.8:
            found.append(str(name))
    return found


def _parse_dates(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", format="%Y-%m-%d")
    if int(parsed.notna().sum()) == 0:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            parsed = pd.to_datetime(series, errors="coerce")
    return parsed


def _describe_frame(name: str, header_row: int, frame: pd.DataFrame, date_columns: list[str]) -> SheetProfile:
    columns = []
    for col in frame.columns:
        columns.append({"name": str(col), "summary": _summarise(frame[col], str(col) in date_columns)})
    sample = _sample_records(frame)
    return SheetProfile(
        name=name,
        header_row=header_row,
        rows=int(len(frame)),
        columns=columns,
        date_columns=list(date_columns),
        sample=sample,
    )


def _summarise(series: pd.Series, is_date: bool) -> str:
    if is_date:
        parsed = pd.to_datetime(series, errors="coerce")
        if parsed.notna().any():
            latest = parsed.max()
            quarter = latest.to_period("Q")
            previous = quarter - 1
            return (
                f"datetime, {parsed.min():%Y-%m-%d} to {parsed.max():%Y-%m-%d}. "
                f"Latest quarter {quarter}, previous quarter {previous}."
            )
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="coerce")
        kind = "integer" if _is_integral(numeric) else "number"
        levels = _levels(numeric.dropna().tolist())
        if levels is not None:
            return f"{kind}, values: {', '.join(levels)}"
        return f"{kind}, min {_num(numeric.min())}, max {_num(numeric.max())}"
    texts = [str(value).strip() for value in series.tolist() if not _is_empty(value)]
    levels = _levels(texts)
    if levels is not None:
        return "text, values: " + ", ".join(levels)
    return f"text, {series.nunique(dropna=True)} distinct values"


def _sample_records(frame: pd.DataFrame) -> list[dict]:
    records = []
    for row in frame.head(_MAX_SAMPLE).to_dict(orient="records"):
        item = {}
        for key, value in row.items():
            item[str(key)] = _plain(value)
        records.append(item)
    return records


def _plain(value):
    if _is_empty(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if value.normalize() == value else value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _compact(records: list[dict]) -> str:
    bits = []
    for record in records:
        inner = ", ".join(f"{key}={value!r}" for key, value in record.items())
        bits.append("{" + inner + "}")
    return "; ".join(bits)


def _clean_headers(headers: list) -> list[str]:
    cleaned, seen = [], {}
    for index, value in enumerate(headers):
        if _is_empty(value):
            name = f"column_{index + 1}"
        else:
            name = re.sub(r"\s+", " ", str(value).strip())
        count = seen.get(name, 0) + 1
        seen[name] = count
        cleaned.append(name if count == 1 else f"{name}_{count}")
    return cleaned


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and not value.strip()


def _is_header_cell(value) -> bool:
    if _is_empty(value) or not isinstance(value, str):
        return False
    text = value.strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) or re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text):
        return False
    return True


def _is_integral(series: pd.Series) -> bool:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return False
    return bool(((numeric - numeric.round()).abs() < 1e-9).all())


def _levels(values: list) -> list[str] | None:
    unique = []
    for value in values:
        text = _num(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
        if text not in unique:
            unique.append(text)
        if len(unique) > _MAX_LEVELS:
            return None
    return sorted(unique, key=str)


def _num(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
