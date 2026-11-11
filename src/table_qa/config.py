"""Settings read from environment variables (and a local ``.env`` file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HF_CODE_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"
DEFAULT_HF_ANSWER_MODEL = "Qwen/Qwen2.5-7B-Instruct"
SMALL_HF_CODE_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
SMALL_HF_ANSWER_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def load_dotenv_if_present(path: str | os.PathLike | None = None) -> None:
    """Load ``.env`` from the working directory without overriding real env vars."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a core dependency
        return
    load_dotenv(dotenv_path=path or Path.cwd() / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _flag(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    backend: str = "hf"
    # api backend
    api_base: str = ""
    api_key: str = ""
    model: str = ""
    answer_model: str = ""
    # hf backend
    hf_code_model: str = DEFAULT_HF_CODE_MODEL
    hf_answer_model: str = DEFAULT_HF_ANSWER_MODEL
    # shared
    max_new_tokens: int = 512
    sandbox_timeout: float = 30.0
    cache_dir: str = ".cache/results"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv_if_present()
        small = _flag("MS_SMALL")
        code_default = SMALL_HF_CODE_MODEL if small else DEFAULT_HF_CODE_MODEL
        answer_default = SMALL_HF_ANSWER_MODEL if small else DEFAULT_HF_ANSWER_MODEL
        return cls(
            backend=_env("MS_BACKEND", "hf").lower(),
            api_base=_env("MS_API_BASE"),
            api_key=_env("MS_API_KEY"),
            model=_env("MS_MODEL"),
            answer_model=_env("MS_ANSWER_MODEL"),
            hf_code_model=_env("MS_HF_CODE_MODEL", code_default),
            hf_answer_model=_env("MS_HF_ANSWER_MODEL", answer_default),
            max_new_tokens=int(_env("MS_MAX_NEW_TOKENS", "512") or 512),
            sandbox_timeout=float(_env("MS_SANDBOX_TIMEOUT", "30") or 30),
            cache_dir=_env("MS_CACHE_DIR", ".cache/results"),
        )

    @property
    def code_model_name(self) -> str:
        return self.model if self.backend == "api" else self.hf_code_model

    @property
    def answer_model_name(self) -> str:
        if self.backend == "api":
            return self.answer_model or self.model
        return self.hf_answer_model

    @property
    def model_name(self) -> str:
        code, answer = self.code_model_name, self.answer_model_name
        if code == answer:
            return code
        return f"{code} + {answer}"

    def validate(self) -> None:
        if self.backend not in {"api", "hf"}:
            raise ValueError(f"MS_BACKEND must be 'api' or 'hf', got {self.backend!r}")
        if self.backend == "api":
            missing = [n for n, v in (("MS_API_BASE", self.api_base), ("MS_MODEL", self.model)) if not v]
            if missing:
                raise ValueError(f"MS_BACKEND=api needs {', '.join(missing)} (see .env.example)")
        if self.sandbox_timeout <= 0:
            raise ValueError("MS_SANDBOX_TIMEOUT must be a positive number of seconds")
        if self.max_new_tokens <= 0:
            raise ValueError("MS_MAX_NEW_TOKENS must be a positive integer")
