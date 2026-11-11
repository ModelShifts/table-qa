"""Run model-written pandas in a subprocess.

The original file is only ever read. A copy is placed in a temporary directory
and marked read-only, and that directory is the child's working directory.
The child has a timeout, no network, and a write jail. See ``sandbox_runner``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .profile import Profile, profile_file


class SandboxError(RuntimeError):
    pass


class SandboxTimeout(SandboxError):
    pass


@dataclass
class SandboxResult:
    ok: bool
    answer: object = None
    chart_type: str = "none"
    chart_rows: list[dict] | None = None
    chart_x: str | None = None
    chart_y: str | None = None
    chart_title: str | None = None
    error: str | None = None
    network: str = ""
    data_unchanged: bool = True
    stdout: str = ""
    stderr: str = ""


def run_in_sandbox(
    code: str,
    source: str | Path,
    timeout: float,
    profile: Profile | None = None,
) -> SandboxResult:
    source = Path(source)
    profile = profile or profile_file(source)
    digest, mode, mtime = _fingerprint(source)
    work = Path(tempfile.mkdtemp(prefix="tableqa-"))
    try:
        filename = "data" + source.suffix.lower()
        copy_path = work / filename
        copy_path.write_bytes(source.read_bytes())
        copy_path.chmod(0o444)
        (work / "meta.json").write_text(json.dumps(profile.meta(filename)))
        (work / "user_code.py").write_text(code, encoding="utf-8")
        result = _execute(work, timeout)
        if not result.data_unchanged:
            result.ok = False
            result.error = "the read-only data copy changed during the run"
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _assert_original(source, digest, mode, mtime)


def _execute(work: Path, timeout: float) -> SandboxResult:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin"),
        "HOME": str(work),
        "TMPDIR": str(work),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "MPLBACKEND": "Agg",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "table_qa.sandbox_runner"],
        cwd=work,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(proc)
        return SandboxResult(ok=False, error=f"Timed out after {timeout:g}s")
    payload_path = work / "result.json"
    if not payload_path.exists():
        detail = (stderr or stdout or "sandbox process produced no result").strip()
        return SandboxResult(ok=False, error=detail[-2000:], stdout=stdout[-2000:], stderr=stderr[-2000:])
    payload = json.loads(payload_path.read_text())
    return SandboxResult(
        ok=bool(payload.get("ok")),
        answer=payload.get("answer"),
        chart_type=payload.get("chart_type") or "none",
        chart_rows=payload.get("chart_rows"),
        chart_x=payload.get("chart_x"),
        chart_y=payload.get("chart_y"),
        chart_title=payload.get("chart_title"),
        error=payload.get("error"),
        network=payload.get("network") or "",
        data_unchanged=bool(payload.get("data_unchanged", True)),
        stdout=(stdout or "")[-2000:],
        stderr=(stderr or "")[-2000:],
    )


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest, stat.st_mode, stat.st_mtime_ns


def _assert_original(path: Path, digest: str, mode: int, mtime: int) -> None:
    now = path.stat()
    if now.st_mode != mode or now.st_mtime_ns != mtime or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise SandboxError(f"the original file was modified: {path}")
