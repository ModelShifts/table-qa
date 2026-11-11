"""Chat model backends.

``api``: any OpenAI-compatible ``/v1/chat/completions`` endpoint.
``hf``:  a local ``transformers`` causal LM.

Both expose ``complete(messages) -> str``. Decoding is greedy (temperature 0).
The code model and the answer model are loaded separately. On CPU, a model is
released before a different one is loaded so both are not resident at once.
"""

from __future__ import annotations

import gc
import json
import re
from typing import Any, Protocol

from .config import Settings

Message = dict[str, str]


class LLM(Protocol):
    name: str

    def complete(self, messages: list[Message], max_new_tokens: int | None = None, stop: list[str] | None = None) -> str: ...


class APIChat:
    def __init__(self, settings: Settings, model: str):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("MS_BACKEND=api needs the 'api' extra: pip install -e '.[api]'") from exc
        self.client = OpenAI(base_url=settings.api_base, api_key=settings.api_key or "not-needed")
        self.name = model
        self.max_new_tokens = settings.max_new_tokens

    def complete(self, messages: list[Message], max_new_tokens: int | None = None, stop: list[str] | None = None) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.name,
                messages=messages,
                temperature=0,
                max_tokens=max_new_tokens or self.max_new_tokens,
                stop=stop or None,
            )
        except Exception as exc:
            raise RuntimeError(f"the API request failed: {exc}") from exc
        return response.choices[0].message.content or ""


class HFChat:
    def __init__(self, settings: Settings, model: str):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("MS_BACKEND=hf needs the 'hf' extra: pip install -e '.[hf]'") from exc
        self._torch = torch
        self.name = model
        self.max_new_tokens = settings.max_new_tokens
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(self.name)
        self.model = AutoModelForCausalLM.from_pretrained(self.name, dtype=dtype).to(self.device).eval()

    def complete(self, messages: list[Message], max_new_tokens: int | None = None, stop: list[str] | None = None) -> str:
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        criteria = _stop_criteria(self.tokenizer, inputs["input_ids"].shape[1], stop) if stop else None
        with self._torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens or self.max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                top_k=None,
                pad_token_id=self.tokenizer.eos_token_id,
                stopping_criteria=criteria,
            )
        return self.tokenizer.decode(out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)


_CACHE: dict[tuple, Any] = {}


def release_models() -> None:
    """Drop cached models so a different checkpoint can be loaded."""
    _CACHE.clear()
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def get_llm(settings: Settings, role: str = "code") -> LLM:
    """Build (and memoise) the chat model for ``role`` (``code`` or ``answer``)."""
    settings.validate()
    if role not in {"code", "answer"}:
        raise ValueError(f"unknown model role {role!r}")
    name = settings.code_model_name if role == "code" else settings.answer_model_name
    key = ("llm", settings.backend, name, settings.api_base)
    if key not in _CACHE:
        if settings.backend == "hf" and _CACHE and not _on_cuda():
            # One local model at a time on CPU. The weights are several GB each.
            release_models()
        _CACHE[key] = APIChat(settings, name) if settings.backend == "api" else HFChat(settings, name)
    return _CACHE[key]


def _stop_criteria(tokenizer, prompt_len: int, stops: list[str]):
    from transformers import StoppingCriteria, StoppingCriteriaList

    class _Stop(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            text = tokenizer.decode(input_ids[0][prompt_len:], skip_special_tokens=True)
            return any(piece in text for piece in stops)

    return StoppingCriteriaList([_Stop()])


def _on_cuda() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def parse_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (tolerates code fences and chatter)."""
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    if start < 0:
        raise ValueError(f"model reply has no JSON object: {text[:200]!r}")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"model reply has an unterminated JSON object: {text[:200]!r}")
