"""Importing the subscription list.

The subscriptions feed and the subscription list are different things. The feed
is videos, and deriving channels from it would miss every channel that has not
posted recently. The channel list at the address below is the real thing, and it
returns every subscription in one call together with the channel name and its
avatar.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..config import Config
from ..cookies import args as cookie_args
from ..ids import CHANNEL_ID, channel_key
from ..net import Throttle
from . import ytdlp

FEED_CHANNELS = "https://www.youtube.com/feed/channels"


class ImportError_(RuntimeError):
    """Named with a trailing underscore so it cannot shadow the builtin."""


@dataclass(frozen=True)
class SubChannel:
    ext_id: str
    title: str | None
    avatar_url: str | None

    @property
    def key(self) -> str:
        return channel_key(self.ext_id)


def _fix_scheme(url: str) -> str | None:
    """Avatar URLs come back protocol relative, which no image loader accepts."""
    url = (url or "").strip()
    if not url or url == "NA":
        return None
    if url.startswith("//"):
        return "https:" + url
    return url if url.startswith("http") else None


def parse_lines(text: str) -> list[SubChannel]:
    """Read the printed `id|title|avatar` lines.

    Split from the right, because a channel name is free text and can contain
    the separator, while the id and the avatar URL cannot.
    """
    channels: list[SubChannel] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        ext_id, _, rest = line.partition("|")
        title, _, avatar = rest.rpartition("|")
        ext_id = ext_id.strip()
        if not CHANNEL_ID.match(ext_id) or ext_id in seen:
            continue
        seen.add(ext_id)
        title = title.strip()
        channels.append(SubChannel(
            ext_id=ext_id,
            title=title if title and title != "NA" else None,
            avatar_url=_fix_scheme(avatar),
        ))
    return channels


def fetch(cfg: Config, throttle: Throttle | None = None,
          timeout: float = 300.0,
          cancel: threading.Event | None = None) -> list[SubChannel]:
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg),
        "--print", "%(id)s|%(channel)s|%(thumbnails.-1.url)s",
        FEED_CHANNELS,
    ]
    result = ytdlp.run(command, ImportError_, "the import", throttle, cancel, timeout)
    channels = parse_lines(result.stdout)
    if channels:
        return channels
    raise ytdlp.blame(result, ImportError_, "the import")
