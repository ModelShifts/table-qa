import json

from table_qa import cli
from table_qa.config import Settings

from test_pipeline import CODE, _patch


def test_version(capsys):
    try:
        cli.main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "table-qa" in capsys.readouterr().out


def test_profile_command(samples, capsys):
    assert cli.main(["profile", str(samples / "sales.xlsx")]) == 0
    out = capsys.readouterr().out
    assert "sales:" in out and "header on row 3" in out
    assert "returns:" in out and "header on row 1" in out


def test_ask_command_writes_outputs(samples, monkeypatch, tmp_path, capsys):
    _patch(monkeypatch, [CODE])
    monkeypatch.setenv("MS_BACKEND", "api")
    monkeypatch.setenv("MS_API_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("MS_MODEL", "fake")
    out = tmp_path / "run"
    assert cli.main(["ask", str(samples / "sales.xlsx"), "Which region has the highest total revenue?", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "North" in printed and "Steps" in printed and "def load_tables" in printed
    assert (out / "chart.png").read_bytes().startswith(b"\x89PNG")
    payload = json.loads((out / "result.json").read_text())
    assert payload["value"] == "North"
    assert "print(answer)" in (out / "analysis.py").read_text()


def test_ask_json_and_bad_backend(samples, monkeypatch, capsys):
    _patch(monkeypatch, [CODE])
    monkeypatch.setenv("MS_BACKEND", "api")
    monkeypatch.setenv("MS_API_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("MS_MODEL", "fake")
    assert cli.main(["ask", str(samples / "sales.csv"), "Which region has the highest total revenue?", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["value"] == "North"

    monkeypatch.setenv("MS_BACKEND", "nope")
    assert cli.main(["ask", str(samples / "sales.csv"), "What is the total revenue?"]) == 2
    assert "MS_BACKEND" in capsys.readouterr().err


def test_missing_api_settings(monkeypatch, capsys, samples):
    monkeypatch.setenv("MS_BACKEND", "api")
    monkeypatch.delenv("MS_API_BASE", raising=False)
    monkeypatch.delenv("MS_MODEL", raising=False)
    monkeypatch.delenv("MS_API_KEY", raising=False)
    assert cli.main(["ask", str(samples / "sales.csv"), "What is the total revenue?"]) == 2
    assert "MS_API_BASE" in capsys.readouterr().err


def test_small_model_switch(monkeypatch):
    monkeypatch.setenv("MS_SMALL", "1")
    monkeypatch.setenv("MS_BACKEND", "hf")
    monkeypatch.delenv("MS_HF_CODE_MODEL", raising=False)
    monkeypatch.delenv("MS_HF_ANSWER_MODEL", raising=False)
    settings = Settings.from_env()
    assert settings.hf_code_model == "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    assert settings.hf_answer_model == "Qwen/Qwen2.5-1.5B-Instruct"
    assert "1.5B" in settings.model_name
