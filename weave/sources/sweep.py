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
from . import ytdlp

SUBSCRIPTIONS = ":ytsubs"


class SweepError(RuntimeError):
    pass


@dataclass(frozen=True)
class SweptVideo:
    ext_id: str
    duration_s: int | None
    live_status: str | None
    # Which channel posted it. This is what makes the sweep a detector as well
    # as a filler: one call names every channel that has something new, so the
    # feeds of the rest do not have to be asked to find out.
    channel_id: str | None = None
    # When an announced stream or premiere is due to start. Only meaningful
    # while live_status is is_upcoming; yt-dlp reports NA once the wait is
    # over, so a video that has since gone live or ended carries none.
    scheduled_at: int | None = None
    # Rounded by the listing, so only ever applied upwards.
    views: int | None = None

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
        # Older output had three fields, and four before the start time was
        # added. Tolerated so a partial line is still worth its duration
        # rather than being dropped.
        channel = _optional_text(parts[3]) if len(parts) > 3 else None
        scheduled = _optional_int(parts[4]) if len(parts) > 4 else None
        views = _optional_int(parts[5]) if len(parts) > 5 else None
        out.append(SweptVideo(ext_id, _optional_int(parts[1]), _optional_text(parts[2]),
                              channel, scheduled, views))
    return out


def fetch(cfg: Config, limit: int = 400, throttle: Throttle | None = None,
          timeout: float = 300.0,
          cancel: threading.Event | None = None) -> list[SweptVideo]:
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg),
        "--playlist-end", str(max(1, limit)),
        "--print",
        "%(id)s|%(duration)s|%(live_status)s|%(channel_id)s|%(release_timestamp)s|%(view_count)s",
        SUBSCRIPTIONS,
    ]
    result = ytdlp.run(command, SweepError, "the sweep", throttle, cancel, timeout)
    videos = parse_lines(result.stdout)
    if videos:
        return videos
    raise ytdlp.blame(result, SweepError, "the sweep")
