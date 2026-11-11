import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


def truth() -> dict:
    return json.loads((SAMPLES / "questions.json").read_text())


class FakeLLM:
    """Stands in for a chat model. Returns canned replies and records prompts."""

    name = "fake-llm"

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def complete(self, messages, max_new_tokens=None, stop=None):
        self.prompts.append(messages)
        if callable(self.reply):
            return self.reply(messages)
        return self.reply


@pytest.fixture
def samples() -> Path:
    return SAMPLES


@pytest.fixture
def fake_llm():
    return FakeLLM
