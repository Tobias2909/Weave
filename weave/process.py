"""Running a subprocess that can be cancelled.

Qt treats destroying a running QThread as a fatal error and aborts the process,
so every background thread has to be able to stop when the window closes. A
plain subprocess.run cannot be interrupted, which is enough to make quitting
during a refresh crash. This wraps Popen in a poll loop instead, so a waiting
thread can be told to give up.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass

POLL_INTERVAL_S = 0.1
# How long a terminated child gets to exit before it is killed outright.
GRACE_S = 2.0


class Cancelled(RuntimeError):
    pass


class Timeout(RuntimeError):
    """Own type on purpose. subprocess.TimeoutExpired does not inherit from
    the builtin TimeoutError, so catching that would silently never fire."""


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str


def run(command: list[str], cancel: threading.Event | None = None,
        timeout: float = 300.0) -> Result:
    """Run to completion, or raise Cancelled if asked to stop first."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    waited = 0.0
    while True:
        try:
            stdout, stderr = process.communicate(timeout=POLL_INTERVAL_S)
        except subprocess.TimeoutExpired:
            waited += POLL_INTERVAL_S
            if cancel is not None and cancel.is_set():
                _stop(process)
                raise Cancelled("cancelled")
            if waited >= timeout:
                _stop(process)
                raise Timeout(f"timed out after {timeout:.0f} seconds")
            continue
        return Result(process.returncode, stdout or "", stderr or "")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.communicate(timeout=GRACE_S)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.communicate(timeout=GRACE_S)
        except subprocess.TimeoutExpired:
            pass
