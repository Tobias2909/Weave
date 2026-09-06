"""Real YouTube playlists, as opposed to boxes.

A box is Weave's own, holds whatever you put in it and lives only in your
database. A playlist is YouTube's, and this reads it. The two were deliberately
never given the same name.

Two calls, because they answer different questions. The playlists feed lists
what you have, cheaply and without their contents. A playlist address then
lists one playlist's videos, and those carry a channel id and a duration where
the history does not.

Nothing here is written into the videos table. A playlist is full of videos
from channels you may not track at all, and putting them there would make them
look like something followed.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from ..config import Config
from ..cookies import args as cookie_args
from ..net import Throttle
from . import ytdlp
from .flatlist import APPROXIMATE_DATES, FIELDS, FlatVideo, is_unavailable, parse

FEED_PLAYLISTS = "https://www.youtube.com/feed/playlists"
PLAYLIST_URL = "https://www.youtube.com/playlist?list={playlist_id}"

# Liked videos and the uploads playlists are addressed the same way, so the id
# is checked rather than assumed. LL is the liked list, which is a real
# playlist and is kept.
PLAYLIST_ID = re.compile(r"^(?:PL|LL|FL|UU|OL|RD)[A-Za-z0-9_-]{0,40}$")

ITEM_FIELDS = FIELDS

# A playlist entry is the same thing a recommendation and a search result are,
# so it is read by the same parser.
PlaylistItem = FlatVideo


def parse_items(text: str) -> tuple[list[PlaylistItem], int]:
    """A playlist's rows, with the ones YouTube itself will not resolve
    counted and left out rather than shown as a video with nothing behind it.

    There is nothing this app, or YouTube's own apps, can do about a private
    or a deleted entry, so it is not treated as an error. It is just worth
    saying somewhere that it happened, which is why the count travels with
    the list instead of being thrown away here.
    """
    found = parse(text)
    kept = [item for item in found if not is_unavailable(item)]
    return kept, len(found) - len(kept)


class PlaylistError(RuntimeError):
    pass


@dataclass(frozen=True)
class Playlist:
    ext_id: str
    title: str


def parse_list(text: str) -> list[Playlist]:
    """The playlists themselves, which are not videos and so are read here
    rather than by the shared parser."""
    out: list[Playlist] = []
    seen: set[str] = set()
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        ext_id = parts[0].strip()
        title = (parts[1] or "").strip()
        if not PLAYLIST_ID.match(ext_id) or ext_id in seen or not title or title == "NA":
            continue
        seen.add(ext_id)
        out.append(Playlist(ext_id, title))
    return out


def fetch_list(cfg: Config, limit: int = 100, throttle: Throttle | None = None,
               timeout: float = 180.0,
               cancel: threading.Event | None = None) -> list[Playlist]:
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg), *APPROXIMATE_DATES,
        "--playlist-end", str(max(1, limit)),
        "--print", "%(id)s\t%(title)s",
        FEED_PLAYLISTS,
    ]
    result = ytdlp.run(command, PlaylistError, "the playlist list", throttle, cancel, timeout)
    found = parse_list(result.stdout)
    if found:
        return found
    raise ytdlp.blame(result, PlaylistError, "the playlist list")


def fetch_items(cfg: Config, playlist_id: str, limit: int = 300,
                throttle: Throttle | None = None, timeout: float = 300.0,
                cancel: threading.Event | None = None) -> tuple[list[PlaylistItem], int]:
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg), *APPROXIMATE_DATES,
        "--playlist-end", str(max(1, limit)),
        "--print", ITEM_FIELDS,
        PLAYLIST_URL.format(playlist_id=playlist_id),
    ]
    result = ytdlp.run(command, PlaylistError, "the playlist", throttle, cancel, timeout)
    found, skipped = parse_items(result.stdout)
    # An empty playlist is a real thing and not a failure, so a clean run that
    # simply had nothing in it is reported as nothing rather than as a problem.
    # A playlist that is nothing but private or deleted entries counts as
    # having found something too, for the same reason.
    if found or skipped or not ytdlp.complained(result):
        return found, skipped
    raise ytdlp.blame(result, PlaylistError, "the playlist")
