import hashlib
import platform
import sys
import time
from pathlib import Path

import pytest

from table_qa.sandbox import SandboxError, run_in_sandbox


def _csv(tmp_path: Path) -> Path:
    path = tmp_path / "sales.csv"
    path.write_text("region,revenue\nEast,10\nNorth,30\n")
    return path


def _fingerprint(path: Path):
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mode, stat.st_mtime_ns


def test_runs_code_and_leaves_original_untouched(tmp_path):
    path = _csv(tmp_path)
    before = _fingerprint(path)
    result = run_in_sandbox(
        'answer = float(tables["sales"]["revenue"].sum())\n',
        path,
        timeout=30,
    )
    assert result.ok, result.error
    assert result.answer == 40
    assert result.data_unchanged
    assert result.network == "seccomp"
    assert _fingerprint(path) == before


def test_original_file_cannot_be_written(tmp_path):
    path = _csv(tmp_path)
    before = path.read_bytes()
    fingerprint = _fingerprint(path)
    code = f"""
answer = "blocked"
target = {str(path)!r}
try:
    open(target, "w").write("hacked")
    answer = "open"
except Exception as exc:
    answer = type(exc).__name__
"""
    result = run_in_sandbox(code, path, timeout=30)
    assert result.ok, result.error
    assert result.answer == "PermissionError"
    assert path.read_bytes() == before
    assert _fingerprint(path) == fingerprint

    pathlib_code = f"""
from pathlib import Path
answer = "blocked"
try:
    Path({str(path)!r}).write_text("hacked")
    answer = "pathlib"
except Exception as exc:
    answer = type(exc).__name__
"""
    result = run_in_sandbox(pathlib_code, path, timeout=30)
    assert result.answer == "PermissionError"
    assert path.read_bytes() == before

    os_code = f"""
import os
answer = "blocked"
try:
    os.open({str(path)!r}, os.O_WRONLY | os.O_CREAT, 0o644)
    answer = "os-open"
except Exception as exc:
    answer = type(exc).__name__
"""
    result = run_in_sandbox(os_code, path, timeout=30)
    assert result.answer == "PermissionError"
    assert path.read_bytes() == before
    assert _fingerprint(path) == fingerprint


def test_read_only_copy_and_outside_writes(tmp_path):
    path = _csv(tmp_path)
    escape = Path("/tmp/tableqa-escape-test")
    if escape.exists():
        escape.unlink()
    code = r"""
from pathlib import Path
notes = []
for item in sorted(Path('.').iterdir()):
    try:
        item.write_text('hacked')
        notes.append('wrote:' + item.name)
    except Exception as exc:
        notes.append(type(exc).__name__ + ':' + item.name)
try:
    open('/tmp/tableqa-escape-test', 'w').write('x')
    notes.append('escaped')
except Exception as exc:
    notes.append(type(exc).__name__ + ':escape')
answer = '|'.join(notes)
"""
    result = run_in_sandbox(code, path, timeout=30)
    assert result.ok, result.error
    assert result.data_unchanged
    assert "wrote:data.csv" not in result.answer
    assert "PermissionError:data.csv" in result.answer
    assert "PermissionError:escape" in result.answer
    assert not escape.exists()


def test_network_and_process_are_blocked(tmp_path):
    path = _csv(tmp_path)
    code = """
import socket
try:
    socket.create_connection(("example.com", 80), 2)
    answer = "connected"
except Exception as exc:
    answer = type(exc).__name__
"""
    result = run_in_sandbox(code, path, timeout=30)
    assert result.ok, result.error
    assert result.answer == "PermissionError"

    system = """
import os
try:
    os.system("echo hacked")
    answer = "ran"
except Exception as exc:
    answer = type(exc).__name__
"""
    result = run_in_sandbox(system, path, timeout=30)
    assert result.answer == "PermissionError"


@pytest.mark.skipif(sys.platform != "linux" or platform.machine() != "x86_64", reason="seccomp numbers are for Linux x86_64")
def test_seccomp_blocks_the_socket_syscall(tmp_path):
    path = _csv(tmp_path)
    code = """
import ctypes
libc = ctypes.CDLL(None, use_errno=True)
fd = libc.socket(2, 1, 0)
answer = str(fd) + ":" + str(ctypes.get_errno())
"""
    result = run_in_sandbox(code, path, timeout=30)
    assert result.ok, result.error
    assert result.network == "seccomp"
    assert result.answer.startswith("-1:1"), result.answer


def test_timeout(tmp_path):
    path = _csv(tmp_path)
    before = _fingerprint(path)
    started = time.time()
    result = run_in_sandbox("while True:\n    pass\n", path, timeout=4)
    elapsed = time.time() - started
    assert not result.ok
    assert "Timed out" in (result.error or "")
    assert elapsed < 20
    assert _fingerprint(path) == before


def test_parent_refuses_a_modified_original(tmp_path):
    from table_qa import sandbox as sandbox_mod

    path = _csv(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    mode, mtime = path.stat().st_mode, path.stat().st_mtime_ns
    path.write_text("changed\n")
    with pytest.raises(SandboxError):
        sandbox_mod._assert_original(path, digest, mode, mtime)
