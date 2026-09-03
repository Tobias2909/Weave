"""Viewer counts for YouTube streams, and whether they are still on air.

The subscriptions sweep says a video is live but never how many are watching,
measured as NA on every live row. Without a number those streams cannot be
ordered against Twitch, which does report one, so they would always sit at the
end of the bar however busy they are.

One small call per stream fixes both halves of that. It costs about two and a
half seconds, and it also reports whether the stream is still running, so one
that has ended leaves the bar at once instead of waiting up to a full feed
refresh to disappear.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..config import Config
from ..cookies import args as cookie_args
from ..net import Throttle
from ..process import Cancelled, Timeout, run as run_process

WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


class LiveCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveState:
    ext_id: str
    viewers: int | None
    still_live: bool


def parse_line(ext_id: str, text: str) -> LiveState:
    line = next((l for l in text.splitlines() if l.strip()), "")
    viewers, _, status = line.partition("|")
    viewers = viewers.strip()
    try:
        count = int(viewers)
    except ValueError:
        count = None
    return LiveState(ext_id, count, status.strip() == "is_live")


def check(cfg: Config, ext_id: str, throttle: Throttle | None = None,
          cancel: threading.Event | None = None, timeout: float = 90.0) -> LiveState:
    command = ["yt-dlp", "--no-warnings", "--simulate", *cookie_args(cfg),
               "--print", "%(concurrent_view_count)s|%(live_status)s",
               WATCH_URL.format(video_id=ext_id)]
    try:
        if throttle is not None:
            with throttle.slot():
                result = run_process(command, cancel=cancel, timeout=timeout)
        else:
            result = run_process(command, cancel=cancel, timeout=timeout)
    except Cancelled:
        raise
    except FileNotFoundError as exc:
        raise LiveCheckError("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise LiveCheckError("the live check timed out") from exc

    if result.returncode != 0 and not result.stdout.strip():
        tail = (result.stderr or "").strip().splitlines()
        raise LiveCheckError((tail[-1] if tail else "the live check failed")[:200])
    return parse_line(ext_id, result.stdout)
