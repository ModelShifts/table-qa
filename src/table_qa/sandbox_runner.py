"""Child process for one sandboxed analysis.

Launched by ``table_qa.sandbox`` with the working directory set to a temporary
folder that holds ``meta.json``, ``user_code.py`` and a read-only copy of the
spreadsheet. The process:

- loads the tables with the same loader the rerunnable script uses
- denies new sockets with a seccomp filter (Linux x86_64)
- refuses writes to the data copy and writes outside the work directory
- executes the model code and writes ``result.json``

Run as ``python -m table_qa.sandbox_runner`` from the work directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import traceback
from pathlib import Path


def main() -> int:
    root = Path.cwd().resolve()
    meta = json.loads((root / "meta.json").read_text())
    data_path = (root / meta["filename"]).resolve()
    write_text = _install_guards(root, data_path)

    # Imports happen after the write jail is in place. Bytecode writes are off
    # so importing a stdlib module cannot touch site-packages.
    sys.dont_write_bytecode = True
    import numpy as np
    import pandas as pd

    from table_qa.profile import load_tables

    before = _sha256(data_path)
    try:
        tables = load_tables(data_path, meta)
    except Exception:
        _write_result(
            root, write_text, ok=False, error=traceback.format_exc(limit=8), network="", data_unchanged=True
        )
        return 1

    # Network is closed after the file has loaded, so importing pandas cannot
    # trip the filter, and the model code cannot open a socket afterwards.
    network = _install_network_block()
    namespace: dict = {"tables": tables, "pd": pd, "np": np, "answer": None}
    code = (root / "user_code.py").read_text(encoding="utf-8")
    error = None
    try:
        exec(compile(code, "analysis.py", "exec"), namespace)
        ok = True
    except Exception:
        ok = False
        error = traceback.format_exc(limit=8)
    after = _sha256(data_path)
    answer = namespace.get("answer", None)
    if ok and answer is None:
        ok = False
        error = "code finished without setting `answer`"
    chart_rows, chart_type, chart_x, chart_y, chart_title = _chart_payload(namespace, pd)
    _write_result(
        root,
        write_text,
        ok=ok,
        error=error,
        network=network,
        data_unchanged=before == after,
        answer=_jsonable(answer),
        chart_rows=chart_rows,
        chart_type=chart_type,
        chart_x=chart_x,
        chart_y=chart_y,
        chart_title=chart_title,
    )
    return 0 if ok else 1


def _chart_payload(namespace: dict, pd):
    chart_df = namespace.get("chart_df", None)
    chart_type = namespace.get("chart_type", None)
    if isinstance(chart_df, pd.Series):
        chart_df = chart_df.rename_axis(chart_df.index.name or "index").reset_index(name=chart_df.name or "value")
    rows = None
    if isinstance(chart_df, pd.DataFrame) and not chart_df.empty:
        view = chart_df.head(24).copy()
        for column in view.columns:
            if pd.api.types.is_datetime64_any_dtype(view[column]):
                view[column] = view[column].dt.strftime("%Y-%m-%d")
        rows = json.loads(view.to_json(orient="records", date_format="iso"))
        rows = _jsonable(rows)
    if isinstance(chart_type, str):
        chart_type = chart_type.strip().lower()
    if chart_type in {None, ""} and rows:
        chart_type = "bar"
    if chart_type in {"column", "barh"}:
        chart_type = "bar"
    if chart_type not in {"bar", "line", "none"}:
        chart_type = "bar" if rows else "none"
    if chart_type == "none":
        rows = None
    return (
        rows,
        chart_type,
        _as_str(namespace.get("chart_x")),
        _as_str(namespace.get("chart_y")),
        _as_str(namespace.get("chart_title")),
    )


def _as_str(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _jsonable(value):
    import datetime
    import math

    import numpy as np
    import pandas as pd

    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        if value.is_integer():
            return int(value)
        return value
    if isinstance(value, (pd.Timestamp, datetime.datetime)):
        stamp = pd.Timestamp(value)
        if stamp.normalize() == stamp:
            return stamp.strftime("%Y-%m-%d")
        return stamp.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, pd.DataFrame):
        return _jsonable(json.loads(value.head(30).to_json(orient="records", date_format="iso")))
    if isinstance(value, pd.Series):
        return _jsonable(value.head(30).to_dict())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in list(value)[:40]]
    return str(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_result(root: Path, write_text, **payload) -> None:
    write_text(root / "result.json", json.dumps(payload))


def _install_guards(root: Path, data_path: Path):
    import io
    import subprocess

    real_io_open = io.open
    real_os_open = os.open

    def allowed_write(path) -> bool:
        try:
            target = Path(path).resolve()
        except (OSError, ValueError):
            return False
        if target == data_path:
            return False
        return target == root or root in target.parents

    def check_write(path):
        if not allowed_write(path):
            raise PermissionError("sandbox blocks this write")

    def guarded_open(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, os.PathLike)):
            text_mode = mode if isinstance(mode, str) else "r"
            if any(ch in text_mode for ch in "wax+"):
                check_write(file)
        return real_io_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, mode=0o777, *args, **kwargs):
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
        if flags & write_flags:
            check_write(path)
        return real_os_open(path, flags, mode, *args, **kwargs)

    def blocked(*_args, **_kwargs):
        raise PermissionError("sandbox blocks this operation")

    def guarded_remove(path, *args, **kwargs):
        check_write(path)
        return os_remove(path, *args, **kwargs)

    def guarded_rename(src, dst, *args, **kwargs):
        check_write(src)
        check_write(dst)
        return os_rename(src, dst, *args, **kwargs)

    os_remove = os.remove
    os_rename = os.rename
    io.open = guarded_open
    import builtins

    builtins.open = guarded_open
    os.open = guarded_os_open
    os.remove = os.unlink = guarded_remove
    os.rename = os.replace = guarded_rename

    def guarded_chmod(path, *_args, **_kwargs):
        check_write(path)
        raise PermissionError("sandbox blocks changing file mode")

    os.chmod = guarded_chmod
    for name in (
        "system",
        "popen",
        "fork",
        "forkpty",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "chown",
        "truncate",
    ):
        if hasattr(os, name):
            setattr(os, name, blocked)
    try:
        import posix

        for name in ("system", "popen", "fork", "execv", "execve"):
            if hasattr(posix, name):
                setattr(posix, name, blocked)
    except ImportError:
        pass
    subprocess.Popen = blocked
    subprocess.run = blocked
    subprocess.call = blocked
    subprocess.check_call = blocked
    subprocess.check_output = blocked

    def write_text(path: Path, text: str) -> None:
        real_io_open(path, "w", encoding="utf-8").write(text)

    return write_text


def _install_network_block() -> str:
    """Deny new sockets. Returns ``seccomp`` or ``python`` to say which layer is active."""
    import socket

    class _BlockedSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            raise PermissionError("sandbox blocks network")

    def _blocked_connect(*_args, **_kwargs):
        raise PermissionError("sandbox blocks network")

    socket.socket = _BlockedSocket
    socket.create_connection = _blocked_connect
    socket.create_server = _blocked_connect
    if sys.platform != "linux" or platform.machine() != "x86_64":
        return "python"
    if _install_seccomp():
        return "seccomp"
    raise RuntimeError("could not install the seccomp network filter")


def _install_seccomp() -> bool:
    """Install a BPF filter that returns EPERM for socket-creating syscalls.

    The filter allows every other syscall, including read and write, so the
    process can still load the file and write ``result.json``.
    """
    import ctypes
    import errno

    seccomp_ret_allow = 0x7FFF0000
    seccomp_ret_errno = 0x00050000
    seccomp_ret_data = 0x0000FFFF
    seccomp_ret_kill = 0x80000000
    seccomp_mode_filter = 2
    pr_set_no_new_privs = 38
    pr_set_seccomp = 22
    audit_arch_x86_64 = 0xC000003E
    bpf_ld, bpf_w, bpf_abs = 0x00, 0x00, 0x20
    bpf_jmp, bpf_jeq, bpf_k = 0x05, 0x10, 0x00
    bpf_ret = 0x06
    # socket, connect, accept, sendto, recvfrom, sendmsg, recvmsg, shutdown,
    # bind, listen, socketpair, accept4
    denied = (41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 53, 288)

    class SockFilter(ctypes.Structure):
        _fields_ = [
            ("code", ctypes.c_uint16),
            ("jt", ctypes.c_uint8),
            ("jf", ctypes.c_uint8),
            ("k", ctypes.c_uint32),
        ]

    class SockFprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(SockFilter))]

    def stmt(code, k):
        return SockFilter(code, 0, 0, k)

    def jump(code, k, jt, jf):
        return SockFilter(code, jt, jf, k)

    filters = [
        stmt(bpf_ld | bpf_w | bpf_abs, 4),
        jump(bpf_jmp | bpf_jeq | bpf_k, audit_arch_x86_64, 1, 0),
        stmt(bpf_ret | bpf_k, seccomp_ret_kill),
        stmt(bpf_ld | bpf_w | bpf_abs, 0),
    ]
    errno_ret = seccomp_ret_errno | (errno.EPERM & seccomp_ret_data)
    for number in denied:
        filters.append(jump(bpf_jmp | bpf_jeq | bpf_k, number, 0, 1))
        filters.append(stmt(bpf_ret | bpf_k, errno_ret))
    filters.append(stmt(bpf_ret | bpf_k, seccomp_ret_allow))
    array = (SockFilter * len(filters))(*filters)
    program = SockFprog(len(filters), array)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(pr_set_no_new_privs, 1, 0, 0, 0) != 0:
        return False
    if libc.prctl(pr_set_seccomp, seccomp_mode_filter, ctypes.byref(program)) != 0:
        return False
    return True


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
