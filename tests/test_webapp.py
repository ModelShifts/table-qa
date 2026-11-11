from table_qa.pipeline import QueryResult, ResultCache
from table_qa.webapp import list_samples, profile_markdown, samples_dir


def test_samples_are_listed():
    names = list_samples()
    assert "sales.xlsx" in names and "sales.csv" in names
    text = profile_markdown(samples_dir() / "sales.xlsx")
    assert "sales" in text and "header on row 3" in text
    assert "returns" in text and "header on row 1" in text


def test_result_cache_roundtrip(samples, tmp_path, monkeypatch):
    from table_qa.config import Settings

    monkeypatch.setenv("MS_BACKEND", "api")
    monkeypatch.setenv("MS_API_BASE", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("MS_MODEL", "fake-cache")
    settings = Settings.from_env()
    cache = ResultCache(tmp_path)
    result = QueryResult(
        ok=True,
        question="What is the total revenue?",
        source=str(samples / "sales.csv"),
        value=14910,
        answer="The total revenue is 14,910.",
        steps=["Sum the revenue column"],
        code="answer = 14910",
        script="print(answer)\n",
        chart_png=None,
        model=settings.model_name,
        backend="api",
        answer_source="model",
    )
    assert cache.get(samples / "sales.csv", result.question, settings) is None
    cache.put(samples / "sales.csv", result.question, settings, result)
    loaded = cache.get(samples / "sales.csv", result.question, settings)
    assert loaded is not None and loaded.cached
    assert loaded.value == 14910
    assert loaded.answer.startswith("The total")


def test_app_builds(monkeypatch):
    pytest = __import__("pytest")
    pytest.importorskip("gradio")
    monkeypatch.setenv("MS_BACKEND", "hf")
    from table_qa.webapp import build_app

    demo = build_app()
    assert demo is not None
