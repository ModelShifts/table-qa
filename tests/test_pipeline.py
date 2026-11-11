import hashlib
import json

from table_qa.config import Settings
from table_qa.pipeline import format_value, run_question
from table_qa.prompts import code_problem, parse_reply, wants_chart

from conftest import truth


CODE = """
STEPS:
- Sum revenue by region
- Pick the region with the largest sum
CODE:
grouped = tables["sales"].groupby("region", as_index=False)["revenue"].sum()
answer = grouped.loc[grouped["revenue"].idxmax(), "region"]
chart_df = grouped
chart_type = "bar"
chart_x = "region"
chart_y = "revenue"
chart_title = "Revenue by region"
END
"""


def _settings(monkeypatch) -> Settings:
    monkeypatch.setenv("MS_BACKEND", "api")
    monkeypatch.setenv("MS_API_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("MS_MODEL", "fake")
    return Settings.from_env()


def _patch(monkeypatch, replies):
    from table_qa import pipeline

    state = {"n": 0}

    class Model:
        def __init__(self, role):
            self.name = "fake-" + role
            self.role = role

        def complete(self, messages, max_new_tokens=None, stop=None):
            if self.role == "answer":
                return "North has the highest total revenue."
            state["n"] += 1
            reply = replies[min(state["n"] - 1, len(replies) - 1)]
            return reply

    monkeypatch.setattr(pipeline, "get_llm", lambda settings, role="code": Model(role))


def test_comment_mentioning_sales_is_allowed():
    code = "sales_df = tables['sales']\nanswer = sales_df['revenue'].sum()\n"
    assert code_problem(code, "What is the total revenue?") is None


def test_code_problem_rejects_file_access():
    assert code_problem('answer = tables["sales"]["revenue"].sum()', "What is the total revenue?") is None
    assert "read_excel" in (code_problem("sales = pd.read_excel('sales.xlsx')", "What is the total revenue?") or "")
    assert code_problem('answer = tables["SHEET"]["revenue"].sum()', "Which region?")
    assert code_problem('answer = tables["sales"]["region"].value_counts().idxmax()', "Which region has the highest total revenue?")
    assert code_problem(
        'grouped = tables["sales"].groupby("region")["revenue"].sum()\nanswer = grouped.idxmax()',
        "What is the total revenue?",
    )


def test_ensure_answer_and_language_tag():
    from table_qa.prompts import ensure_answer

    assert ensure_answer("total = tables['sales']['revenue'].sum()\n").strip().endswith("answer = total")
    assert ensure_answer("answer = 1") == "answer = 1"
    parsed = parse_reply("STEPS:\n- Sum\nCODE:\n```python\ntotal = 1\n```\nEND\n")
    assert parsed is not None and parsed[1] == "total = 1"
    tagged = parse_reply("STEPS:\n- Sum\nCODE:\npython\ntotal = 1\nEND\n")
    assert tagged is not None and tagged[1] == "total = 1"


def test_parse_sections_and_json():
    parsed = parse_reply("Sure\nSTEPS:\n- Add it\nCODE:\nanswer = 1\nEND\n")
    assert parsed == (["Add it"], "answer = 1")
    fenced = parse_reply("STEPS:\n1. Count rows\nCODE:\n```python\nanswer = 2\n```\nEND\n")
    assert fenced == (["Count rows"], "answer = 2")
    as_json = parse_reply('{"steps": ["Sum"], "code": "answer = 3"}')
    assert as_json == (["Sum"], "answer = 3")
    assert parse_reply("no code here") is None
    assert wants_chart("Which region grew fastest last quarter?")
    assert not wants_chart("What is the total revenue?")


def test_ask_returns_value_chart_steps_and_script(samples, monkeypatch):
    _patch(monkeypatch, [CODE])
    path = samples / "sales.xlsx"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = run_question(path, "Which region has the highest total revenue?", _settings(monkeypatch))
    assert result.ok, result.error
    assert result.value == truth()["questions"][2]["answer"] == "North"
    assert result.answer.startswith("North")
    assert result.answer_source == "model"
    assert result.steps[0].startswith("Sum revenue")
    assert result.chart_png and result.chart_png.startswith(b"\x89PNG")
    assert 'header=2' in result.script and "print(answer)" in result.script
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert format_value(14910) == "14,910"


def test_retries_a_file_read(samples, monkeypatch):
    bad = 'STEPS:\n- Read the file\nCODE:\nsales = pd.read_excel("sales.xlsx")\nanswer = "East"\nEND\n'
    _patch(monkeypatch, [bad, CODE])
    result = run_question(samples / "sales.xlsx", "Which region has the highest total revenue?", _settings(monkeypatch))
    assert result.ok and result.value == "North"


def test_retries_a_bad_reply(samples, monkeypatch):
    _patch(monkeypatch, ["I am not sure", CODE])
    result = run_question(samples / "sales.xlsx", "Which region has the highest total revenue?", _settings(monkeypatch))
    assert result.ok and result.value == "North"


def test_rerunnable_script(samples, monkeypatch, tmp_path):
    import subprocess
    import sys

    _patch(monkeypatch, [CODE])
    result = run_question(samples / "sales.xlsx", "Which region has the highest total revenue?", _settings(monkeypatch))
    script = tmp_path / "analysis.py"
    script.write_text(result.script)
    proc = subprocess.run([sys.executable, str(script)], cwd=samples, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "North" in proc.stdout


def test_ground_truth_matches_the_files(samples):
    from table_qa.profile import load_tables, profile_file

    spec = {item["id"]: item for item in truth()["questions"]}
    tables = load_tables(samples / "sales.xlsx", profile_file(samples / "sales.xlsx").meta("sales.xlsx"))
    sales, returns = tables["sales"], tables["returns"]
    assert spec["total_revenue"]["answer"] == int(sales["revenue"].sum())
    assert spec["top_region"]["answer"] == sales.groupby("region")["revenue"].sum().idxmax()
    assert spec["top_product"]["answer"] == sales.groupby("product")["units"].sum().idxmax()
    assert spec["most_returns"]["answer"] == returns.groupby("region")["units"].sum().idxmax()
    assert spec["latest_order_date"]["answer"] == sales["order_date"].max().strftime("%Y-%m-%d")
    dated = sales.copy()
    dated["quarter"] = dated["order_date"].dt.to_period("Q")
    last_q = dated["quarter"].max()
    growth = (
        dated[dated["quarter"] == last_q].groupby("region")["revenue"].sum()
        - dated[dated["quarter"] == last_q - 1].groupby("region")["revenue"].sum()
    ) / dated[dated["quarter"] == last_q - 1].groupby("region")["revenue"].sum()
    assert spec["fastest_growth"]["answer"] == growth.idxmax() == "East"
    assert spec["top_region"]["answer"] == "North"
    assert spec["most_returns"]["answer"] == "South"
    csv_tables = load_tables(samples / "sales.csv", profile_file(samples / "sales.csv").meta("sales.csv"))
    assert spec["csv_total_revenue"]["answer"] == int(csv_tables["sales"]["revenue"].sum())
    assert json.loads((samples / "questions.json").read_text())["definitions"]["last_quarter_in_sample"] == str(last_q)
