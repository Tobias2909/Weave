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

import functools
import shutil
import subprocess
import threading

from ..net import Throttle
from ..process import Cancelled, Result, Timeout
from ..process import run as run_process

LOGIN_TROUBLE = "could not read the login cookies, check browser_profile in the config"

# The JavaScript runtimes yt-dlp knows, by the name of the binary that is one.
# Only deno is enabled by default, so any of the others has to be named on the
# command line or it might as well not be installed.
_RUNTIMES = (("deno", "deno"), ("node", "node"), ("nodejs", "node"), ("bun", "bun"))


@functools.cache
def js_runtime_args() -> list[str]:
    """What to add so yt-dlp uses the JavaScript runtime this machine has.

    YouTube's player answers an authenticated request with a challenge, and
    solving it needs a JavaScript runtime. **yt-dlp enables deno and nothing
    else by default**, so a machine with only node fails, and it fails in a
    way that names neither node nor deno: MEASURED 2026-09-10, the same call
    that works here answers `ERROR: [youtube] <id>: The page needs to be
    reloaded.` with the runtimes cleared. Without cookies it succeeds either
    way, which is what made it look like a cookie problem.

    Empty when deno is there, since that is the default and saying it again
    buys nothing, and empty when the yt-dlp in front of us predates the
    option, since an unknown option is a run that does not happen at all.
    """
    if shutil.which("deno"):
        return []
    for binary, runtime in _RUNTIMES:
        found = shutil.which(binary)
        if found and _takes_js_runtimes():
            # The path goes with it. A runtime found by name is on this PATH
            # and not necessarily on the one yt-dlp is looking down.
            return ["--js-runtimes", f"{runtime}:{found}"]
    return []


def with_js_runtime(command: list[str]) -> list[str]:
    """One yt-dlp command line, with the runtime argument in it. For the two
    callers that run yt-dlp without going through `run`."""
    extra = js_runtime_args()
    if not extra or not command:
        return command
    return [command[0], *extra, *command[1:]]


@functools.cache
def _takes_js_runtimes() -> bool:
    try:
        done = subprocess.run(["yt-dlp", "--help"], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return "--js-runtimes" in (done.stdout or "")


def run(command: list[str], error: type[Exception], what: str,
        throttle: Throttle | None = None, cancel: threading.Event | None = None,
        timeout: float = 180.0) -> Result:
    """Run yt-dlp to completion.

    A cancel is passed through untouched, since a shutdown is not a failure of
    the source. A missing binary and a timeout become the source's own error,
    worded with `what` so the message says which call it was.

    The JavaScript runtime is added here rather than by each caller, since
    every one of them needs it and one of them forgetting is a machine where
    half the program works.
    """
    command = with_js_runtime(command)
    try:
        if throttle is not None:
            with throttle.slot():
                return run_process(command, cancel=cancel, timeout=timeout)
        return run_process(command, cancel=cancel, timeout=timeout)
    except Cancelled:
        raise
    except FileNotFoundError as exc:
        raise error("yt-dlp is not installed") from exc
    except OSError as exc:
        # Present but not runnable, which a permission or a broken shim can
        # manage. Named apart from missing, since the fix is different.
        raise error(f"yt-dlp could not be started, {exc}") from exc
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
