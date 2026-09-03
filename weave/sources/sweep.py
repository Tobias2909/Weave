"""The subscriptions sweep, which fills in what RSS cannot carry.

RSS gives an exact publish time but no duration and no live flag. The
subscriptions feed gives duration and the live flag but no publish time at all.
Neither is sufficient alone, so the feed is built from RSS and this sweep joins
the missing columns in by video id.

It paginates cheaply, roughly 77 ids a second, so one sweep per refresh cycle
covers far more than the fifteen entries RSS publishes per channel.

Rows that are not videos have to be dropped. The feed mixes in radio playlist
ids, which arrive with every field empty and are eleven characters longer than
a video id.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..config import Config
from ..cookies import args as cookie_args
from ..ids import is_video_id, video_key
from ..net import Throttle
from ..process import Result, Timeout, run as run_process

SUBSCRIPTIONS = ":ytsubs"


class SweepError(RuntimeError):
    pass


@dataclass(frozen=True)
class SweptVideo:
    ext_id: str
    duration_s: int | None
    live_status: str | None

    @property
    def key(self) -> str:
        return video_key(self.ext_id)


def _optional_int(text: str) -> int | None:
    text = text.strip()
    if not text or text == "NA":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _optional_text(text: str) -> str | None:
    text = text.strip()
    # Ordinary videos report NA rather than not_live, so an equality check
    # against not_live would never match anything.
    return None if not text or text == "NA" else text


def parse_lines(text: str) -> list[SweptVideo]:
    out: list[SweptVideo] = []
    seen: set[str] = set()
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 3:
            continue
        ext_id = parts[0].strip()
        if not is_video_id(ext_id) or ext_id in seen:
            continue
        seen.add(ext_id)
        out.append(SweptVideo(ext_id, _optional_int(parts[1]), _optional_text(parts[2])))
    return out


def fetch(cfg: Config, limit: int = 400, throttle: Throttle | None = None,
          timeout: float = 300.0,
          cancel: threading.Event | None = None) -> list[SweptVideo]:
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg),
        "--playlist-end", str(max(1, limit)),
        "--print", "%(id)s|%(duration)s|%(live_status)s",
        SUBSCRIPTIONS,
    ]
    try:
        if throttle is not None:
            with throttle.slot():
                result = run_process(command, cancel=cancel, timeout=timeout)
        else:
            result = run_process(command, cancel=cancel, timeout=timeout)
    except FileNotFoundError as exc:
        raise SweepError("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise SweepError("the sweep timed out") from exc

    videos = parse_lines(result.stdout)
    if videos:
        return videos
    tail = (result.stderr or "").strip().splitlines()
    raise SweepError((tail[-1] if tail else "the sweep returned nothing")[:200])
