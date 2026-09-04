"""What YouTube says you have watched.

This is the whole history, not a reflection of what Weave saw. mpv already
tells YouTube when it plays something, so YouTube's copy is the complete one
and there is nothing to be gained from keeping a second, poorer list here.

One measured limitation. A history row carries an id, a title, a duration and
a thumbnail, and says nothing whatsoever about the channel. So an entry from a
channel that is tracked here picks up its name by being joined to it, and one
from anywhere else simply has no channel name. Asking per video would cost a
request each, which is not worth it for a name.

It pages like the other lists, verified, so more of it is reached by asking for
a later slice.
"""

from __future__ import annotations

import threading

from ..config import Config
from ..cookies import args as cookie_args
from ..ids import video_key
from ..net import Throttle
from ..process import Timeout, run as run_process
from .flatlist import FIELDS, FlatVideo, parse

HISTORY = ":ythistory"


class HistoryError(RuntimeError):
    pass


def parse_lines(text: str) -> list[FlatVideo]:
    return parse(text)


def keys_of(items: list[FlatVideo]) -> list[str]:
    """The video keys, for marking the stored ones as watched."""
    return [video_key(item.ext_id) for item in items]


def fetch(cfg: Config, limit: int = 200, throttle: Throttle | None = None,
          timeout: float = 600.0, cancel: threading.Event | None = None,
          start: int = 1) -> list[FlatVideo]:
    first = max(1, start)
    last = max(first, first + max(1, limit) - 1)
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg),
        "--playlist-items", f"{first}-{last}",
        "--print", FIELDS,
        HISTORY,
    ]
    try:
        if throttle is not None:
            with throttle.slot():
                result = run_process(command, cancel=cancel, timeout=timeout)
        else:
            result = run_process(command, cancel=cancel, timeout=timeout)
    except FileNotFoundError as exc:
        raise HistoryError("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise HistoryError("reading the history timed out") from exc

    found = parse(result.stdout)
    if found:
        return found
    tail = (result.stderr or "").strip().splitlines()
    if not tail:
        return []           # the end of the history is not a failure
    detail = tail[-1]
    if "cookies" in detail.lower() or "sign in" in detail.lower():
        raise HistoryError("could not read the login cookies, check browser_profile in the config")
    raise HistoryError(detail[:200])
