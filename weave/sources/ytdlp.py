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
from pathlib import Path

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


@functools.cache
def solver() -> tuple[bool | None, str]:
    """Whether yt-dlp has the script that answers YouTube's challenge.

    A runtime with nothing to run is the same as no runtime. The solver is
    the separate `yt-dlp-ejs` package, which Arch makes a hard dependency of
    yt-dlp and other places do not, and without it an authenticated request
    comes back as "The page needs to be reloaded" while the same request
    without cookies is fine. MEASURED by hiding the package on a machine
    where everything worked: that exact error, and the address again the
    moment it was back.

    Asked of the interpreter in yt-dlp's own shebang rather than this one.
    They are the same only by accident: yt-dlp can be a distribution package
    while Weave runs from a virtual environment of its own. None when the
    question does not apply, which is a frozen build carrying its own copy.
    """
    found = shutil.which("yt-dlp")
    if not found:
        return None, "yt-dlp is not installed"
    try:
        first = Path(found).read_text(errors="replace").splitlines()[0]
    except (OSError, IndexError, UnicodeDecodeError):
        return None, "not a script, so it carries its own"
    if not first.startswith("#!") or "python" not in first:
        return None, "not a script, so it carries its own"
    interpreter = _interpreter(first)
    try:
        done = subprocess.run(
            [interpreter, "-c",
             "import yt_dlp_ejs as e; print(getattr(e, '__version__', 'installed'))"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        # It is a python script and its python could not be run, so whether
        # the solver is there is unknown. Unknown is reported as missing on
        # purpose. Naming a package that turns out to be present costs one
        # line that can be ignored, and staying quiet costs a machine where
        # nothing signed in works and nothing anywhere says why.
        return False, "whether yt-dlp-ejs is installed could not be read"
    if done.returncode == 0:
        return True, f"yt-dlp-ejs {(done.stdout or '').strip() or 'installed'}"
    return False, "yt-dlp-ejs is not installed"


def _interpreter(shebang: str) -> str:
    """The program named by a shebang line.

    The FIRST word after the marker, not the last. A shebang carries flags,
    Fedora writing its scripts `#!/usr/bin/python3 -sP`, so the last word can
    be `-sP`. Running a flag as a program raises OSError, which this module
    reads as not knowing whether the solver is there, so the wrong end of
    this line turns a plain answer into no answer at all.
    """
    words = shebang[2:].strip().split()
    if not words:
        return ""
    # `#!/usr/bin/env python3` names the program in the second word.
    if Path(words[0]).name == "env" and len(words) > 1:
        return next((word for word in words[1:] if not word.startswith("-")), words[1])
    return words[0]


def prepare(command: list[str]) -> list[str]:
    """One yt-dlp command line with the JavaScript runtime named on it, for
    the callers that run yt-dlp without going through `run`.

    The machine's yt-dlp is the one that runs, always. Weave does not carry
    a second copy to stand in for one without a solver, since a second copy
    goes stale unless somebody upgrades it and a sentence naming the missing
    package does the same job.
    """
    if not command:
        return command
    return [command[0], *js_runtime_args(), *command[1:]]


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
    command = prepare(command)
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
    return error(explain(detail, result.stderr or ""))


# What to type. The package is on PyPI and in some distributions, and it has
# to land in the same environment as the yt-dlp that reads it, which is what
# the pip line does by installing into yt-dlp's own python, per account.
INSTALL_SOLVER = ("run python3 -m pip install --user yt-dlp-ejs, or take it from your "
                  "distribution if it packages one")
INSTALL_RUNTIME = "install deno, or node"


# What yt-dlp says when the challenge could not be solved. The warnings are
# where the reason lives; the error that follows them names none of it. All
# MEASURED against 2026.08.19 with the solver hidden and an empty cache:
#
#   WARNING: [youtube] [jsc] Remote components challenge solver script (deno)
#            and NPM package (deno) were skipped
#   WARNING: [youtube] <id>: Signature solving failed: Some formats may be
#            missing. Ensure you have a supported JavaScript runtime and
#            challenge solver script distribution installed
#   WARNING: [youtube] <id>: n challenge solving failed: ...
#   ERROR:   [youtube] <id>: Requested format is not available
#
# and with cookies and a warm cache the error instead reads "The page needs
# to be reloaded". Two different errors, one cause, so the warnings are what
# this looks for and the errors are only the last resort.
CHALLENGE_MARKS = ("challenge solving failed", "signature solving failed",
                   "challenge solver", "js challenge", "needs to be reloaded",
                   "requested format is not available")


def challenge_trouble(stderr: str) -> str:
    """The line in yt-dlp's own words that says the challenge went unsolved,
    or empty when it said no such thing."""
    for line in (stderr or "").splitlines():
        low = line.lower()
        if any(mark in low for mark in CHALLENGE_MARKS):
            return line.strip().removeprefix("WARNING:").removeprefix("ERROR:").strip()
    return ""


def challenge_advice() -> str:
    """Why the challenge went unanswered, and what to do about it.

    Both halves have to be there and neither is named by the error YouTube
    sends, which is why this exists. "The page needs to be reloaded" on its
    own reads as a cookie problem and is not one.
    """
    have, _ = solver()
    if have is not True:
        # Not proven present is enough. yt-dlp has already said the
        # challenge went unanswered, and the solver is the usual reason,
        # so naming it beats staying quiet because a probe was unsure.
        return f"YouTube's challenge went unanswered, {INSTALL_SOLVER}"
    if not js_runtime_args() and not shutil.which("deno"):
        return f"YouTube's challenge went unanswered with no JavaScript runtime, {INSTALL_RUNTIME}"
    return "YouTube's challenge went unanswered"


# How much of yt-dlp's own line is quoted after the advice. The advice is
# never what gives way: a banner elides the end, so the half a person acts on
# goes in front and the quote is what gets shortened.
QUOTED = 160


def explain(said: str, stderr: str) -> str:
    """One sentence for a yt-dlp run that produced nothing.

    The last line of stderr is what yt-dlp finished with, and on its own it
    can be the least useful line of the lot, so where the challenge is what
    went wrong the thing to install goes in front of it. Both callers compose
    it here, because the same sentence written twice was capped at two
    different lengths and one of them cut the quote mid word.
    """
    said = said.strip().removeprefix("ERROR:").removeprefix("WARNING:").strip()
    if not challenge_trouble(stderr):
        return said[:200]
    return f"{challenge_advice()}. yt-dlp said {said[:QUOTED]}"


def challenge_missing() -> str:
    """What a signed in request is missing, or empty when it is missing
    nothing.

    YouTube answers an authenticated request with a challenge, and the two
    things that answer it are a JavaScript runtime and the solver script.
    Missing either, the feed still fills from RSS and everything past it
    fails, which reads as an account problem and is not one. Said on the way
    in rather than waiting for a press, since a press may never come.
    """
    have, said = solver()
    if have is False:
        return f"{said}, so anything signed in fails. To fix it, {INSTALL_SOLVER}"
    if not js_runtime_args() and not shutil.which("deno"):
        return ("no JavaScript runtime was found, so anything signed in fails. "
                f"To fix it, {INSTALL_RUNTIME}")
    return ""


def complained(result: Result) -> bool:
    """Whether yt-dlp wrote anything to stderr. An empty answer with nothing
    said is an empty list, which some sources treat as an answer."""
    return bool((result.stderr or "").strip())
