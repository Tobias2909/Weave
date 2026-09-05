"""Running yt-dlp for a source, the same way every time.

Every source that shells out to yt-dlp used to carry its own copy of the same
dozen lines: hold a throttle slot if there is one, turn a missing binary and a
timeout into that source's own error, and when nothing came back, read the
last line of stderr and decide whether it was the login. Eight copies drifted
in small ways and each was one more place for the next mistake. This is the one
copy.

A source keeps its own error type, since the caller catches by type and the
message says which source it was.
"""

from __future__ import annotations

import threading

from ..net import Throttle
from ..process import Cancelled, Result, Timeout
from ..process import run as run_process

LOGIN_TROUBLE = "could not read the login cookies, check browser_profile in the config"


def run(command: list[str], error: type[Exception], what: str,
        throttle: Throttle | None = None, cancel: threading.Event | None = None,
        timeout: float = 180.0) -> Result:
    """Run yt-dlp to completion.

    A cancel is passed through untouched, since a shutdown is not a failure of
    the source. A missing binary and a timeout become the source's own error,
    worded with `what` so the message says which call it was.
    """
    try:
        if throttle is not None:
            with throttle.slot():
                return run_process(command, cancel=cancel, timeout=timeout)
        return run_process(command, cancel=cancel, timeout=timeout)
    except Cancelled:
        raise
    except FileNotFoundError as exc:
        raise error("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise error(f"{what} timed out") from exc


def blame(result: Result, error: type[Exception], what: str) -> Exception:
    """The error to raise when a run produced nothing usable.

    yt-dlp says why on its last line of stderr. A login problem is called out
    by name, because it is the one cause the person can fix themselves and it
    otherwise reads as a cryptic extractor message.
    """
    tail = (result.stderr or "").strip().splitlines()
    detail = tail[-1] if tail else f"{what} came back empty"
    if "cookies" in detail.lower() or "sign in" in detail.lower():
        return error(LOGIN_TROUBLE)
    return error(detail[:200])


def complained(result: Result) -> bool:
    """Whether yt-dlp wrote anything to stderr. An empty answer with nothing
    said is an empty list, which some sources treat as an answer."""
    return bool((result.stderr or "").strip())
