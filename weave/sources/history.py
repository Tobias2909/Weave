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
from . import ytdlp
from .flatlist import APPROXIMATE_DATES, FIELDS, FlatVideo, parse

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
        *cookie_args(cfg), *APPROXIMATE_DATES,
        "--playlist-items", f"{first}-{last}",
        "--print", FIELDS,
        HISTORY,
    ]
    result = ytdlp.run(command, HistoryError, "reading the history", throttle, cancel, timeout)
    found = parse(result.stdout)
    if found or not ytdlp.complained(result):
        return found        # the end of the history is not a failure
    raise ytdlp.blame(result, HistoryError, "reading the history")
