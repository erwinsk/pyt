# -*- coding: utf-8 -*-
"""Menjalankan proses eksternal dengan streaming log + pembatalan bersih."""
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional


class Cancelled(Exception):
    """Dilempar saat pengguna membatalkan proses."""


class ProcessTimeout(Exception):
    pass


@dataclass
class ProcResult:
    returncode: int
    tail: List[str]


def kill_tree(proc: subprocess.Popen):
    """Hentikan proses beserta seluruh anaknya (lintas OS)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":  # pragma: no cover
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       creationflags=subprocess.CREATE_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    t0 = time.monotonic()
    while proc.poll() is None and time.monotonic() - t0 < 2.0:
        time.sleep(0.05)
    if proc.poll() is None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def run_process(cmd: List[str], *, env: Optional[dict] = None, cwd: Optional[str] = None,
                on_line: Optional[Callable[[str], None]] = None,
                is_cancelled: Optional[Callable[[], bool]] = None,
                timeout: Optional[float] = None, tail: int = 80) -> ProcResult:
    kwargs = {}
    if os.name == "nt":  # pragma: no cover
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, cwd=cwd, env=env, text=True, encoding="utf-8",
        errors="replace", bufsize=1, **kwargs)
    lines: Deque[str] = deque(maxlen=tail)

    def reader():
        try:
            for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.rstrip("\r\n")
                lines.append(line)
                if on_line:
                    try:
                        on_line(line)
                    except Exception:
                        pass
        except ValueError:
            pass

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    start = time.monotonic()
    cancelled = False
    timed_out = False
    while True:
        try:
            proc.wait(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            pass
        if is_cancelled and is_cancelled():
            cancelled = True
            kill_tree(proc)
            break
        if timeout and time.monotonic() - start > timeout:
            timed_out = True
            kill_tree(proc)
            break
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()
    th.join(timeout=3)
    if cancelled:
        raise Cancelled()
    if timed_out:
        raise ProcessTimeout(f"Proses melebihi batas waktu {timeout}s")
    return ProcResult(proc.returncode, list(lines))
