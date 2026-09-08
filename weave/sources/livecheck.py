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
from . import ytdlp

WATCH_URL = "https://www.youtube.com/watch?v={video_id}"

# What yt-dlp calls a video behind a channel's membership. Measured against a
# real one, with and without cookies: the word arrives on stdout even though
# there are no formats to play, so this call learns it for free while it is
# asking the viewer count. Nothing cheaper says so anywhere.
MEMBERS_ONLY = "subscriber_only"


class LiveCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveState:
    ext_id: str
    viewers: int | None
    still_live: bool
    # When an announced stream is due, which is the one thing the subscriptions
    # sweep never carries. Only meaningful while the state is is_upcoming.
    starts_at: int | None = None
    upcoming: bool = False
    # Behind the channel's membership. Nothing else says so: it is absent from
    # the channel feeds, and the subscriptions feed reports availability as NA
    # for every entry, measured over a thousand of them. This call is the one
    # place it shows, and it costs nothing extra because the call is already
    # being made for the viewer count.
    members_only: bool = False


def _number(text: str) -> int | None:
    text = text.strip()
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_line(ext_id: str, text: str) -> LiveState:
    line = next((row for row in text.splitlines() if row.strip()), "")
    parts = line.split("|")
    status = parts[1].strip() if len(parts) > 1 else ""
    # Older output had three fields. Tolerated, so a line from before this was
    # asked for still yields the viewer count rather than being thrown away.
    availability = parts[3].strip() if len(parts) > 3 else ""
    return LiveState(
        ext_id,
        _number(parts[0] if parts else ""),
        status == "is_live",
        _number(parts[2]) if len(parts) > 2 else None,
        status == "is_upcoming",
        availability == MEMBERS_ONLY,
    )


def check(cfg: Config, ext_id: str, throttle: Throttle | None = None,
          cancel: threading.Event | None = None, timeout: float = 90.0) -> LiveState:
    command = ["yt-dlp", "--no-warnings", "--simulate",
               # An announced stream has no formats yet, and without this
               # yt-dlp treats that as an error, prints nothing and takes the
               # start time with it. Measured against a real one: with the
               # flag it answers is_upcoming and the timestamp, without it the
               # only thing on the terminal is a sentence about how long there
               # is to wait.
               "--ignore-no-formats-error",
               *cookie_args(cfg),
               "--print",
               "%(concurrent_view_count)s|%(live_status)s|%(release_timestamp)s"
               "|%(availability)s",
               WATCH_URL.format(video_id=ext_id)]
    result = ytdlp.run(command, LiveCheckError, "the live check", throttle, cancel, timeout)
    if result.returncode != 0 and not result.stdout.strip():
        raise ytdlp.blame(result, LiveCheckError, "the live check")
    return parse_line(ext_id, result.stdout)
