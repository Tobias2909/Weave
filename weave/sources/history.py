"""What YouTube says you have already watched.

Weave decides watched for itself by observing mpv, but that only covers what
has been played through Weave. Importing the history once gives the feed a
sensible starting point instead of several thousand unwatched rows on the first
day.

The list carries an id and a duration and nothing else. There is no channel id
on a history row, measured, so a video the database has never seen cannot be
placed and is counted as skipped rather than invented. That is fine for what
this is for, since the point is to mark the stored feed, not to grow it.
"""

from __future__ import annotations

import threading

from ..config import Config
from ..cookies import args as cookie_args
from ..ids import is_video_id, video_key
from ..net import Throttle
from ..process import Timeout, run as run_process

HISTORY = ":ythistory"


class HistoryError(RuntimeError):
    pass


def parse_lines(text: str) -> list[str]:
    """Video keys, in the order watched, newest first, without duplicates."""
    keys: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        ext_id = line.strip().split("|")[0].strip()
        if not is_video_id(ext_id) or ext_id in seen:
            continue
        seen.add(ext_id)
        keys.append(video_key(ext_id))
    return keys


def fetch(cfg: Config, limit: int = 2000, throttle: Throttle | None = None,
          timeout: float = 600.0,
          cancel: threading.Event | None = None) -> list[str]:
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg),
        "--playlist-end", str(max(1, limit)),
        "--print", "%(id)s",
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

    keys = parse_lines(result.stdout)
    if keys:
        return keys
    tail = (result.stderr or "").strip().splitlines()
    detail = tail[-1] if tail else "the history came back empty"
    if "cookies" in detail.lower() or "sign in" in detail.lower():
        raise HistoryError("could not read the login cookies, check browser_profile in the config")
    raise HistoryError(detail[:200])
