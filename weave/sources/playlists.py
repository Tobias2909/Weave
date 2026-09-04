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
from ..ids import CHANNEL_ID, is_video_id
from ..net import Throttle
from ..process import Timeout, run as run_process

FEED_PLAYLISTS = "https://www.youtube.com/feed/playlists"
PLAYLIST_URL = "https://www.youtube.com/playlist?list={playlist_id}"

# Liked videos and the uploads playlists are addressed the same way, so the id
# is checked rather than assumed. LL is the liked list, which is a real
# playlist and is kept.
PLAYLIST_ID = re.compile(r"^(?:PL|LL|FL|UU|OL|RD)[A-Za-z0-9_-]{0,40}$")

ITEM_FIELDS = "%(id)s\t%(title)s\t%(channel)s\t%(channel_id)s\t%(duration)s\t%(thumbnails.-1.url)s"


class PlaylistError(RuntimeError):
    pass


@dataclass(frozen=True)
class Playlist:
    ext_id: str
    title: str


@dataclass(frozen=True)
class PlaylistItem:
    ext_id: str
    title: str
    channel_name: str | None
    channel_ext_id: str | None
    duration_s: int | None
    thumbnail_url: str | None


def _optional(text: str) -> str | None:
    text = (text or "").strip()
    return None if not text or text == "NA" else text


def _seconds(text: str) -> int | None:
    value = _optional(text)
    try:
        return int(float(value)) if value else None
    except ValueError:
        return None


def parse_list(text: str) -> list[Playlist]:
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


def parse_items(text: str) -> list[PlaylistItem]:
    out: list[PlaylistItem] = []
    seen: set[str] = set()
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        ext_id = parts[0].strip()
        title = (parts[1] or "").strip()
        if not is_video_id(ext_id) or ext_id in seen or not title or title == "NA":
            continue
        seen.add(ext_id)
        channel_id = _optional(parts[3]) if len(parts) > 3 else None
        out.append(PlaylistItem(
            ext_id=ext_id,
            title=title,
            channel_name=_optional(parts[2]) if len(parts) > 2 else None,
            channel_ext_id=channel_id if channel_id and CHANNEL_ID.match(channel_id) else None,
            duration_s=_seconds(parts[4]) if len(parts) > 4 else None,
            thumbnail_url=_optional(parts[5]) if len(parts) > 5 else None,
        ))
    return out


def _run(command: list[str], throttle: Throttle | None, timeout: float,
         cancel: threading.Event | None, what: str):
    try:
        if throttle is not None:
            with throttle.slot():
                return run_process(command, cancel=cancel, timeout=timeout)
        return run_process(command, cancel=cancel, timeout=timeout)
    except FileNotFoundError as exc:
        raise PlaylistError("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise PlaylistError(f"{what} timed out") from exc


def _blame(result, what: str) -> PlaylistError:
    tail = (result.stderr or "").strip().splitlines()
    detail = tail[-1] if tail else f"{what} came back empty"
    if "cookies" in detail.lower() or "sign in" in detail.lower():
        return PlaylistError("could not read the login cookies, check browser_profile in the config")
    return PlaylistError(detail[:200])


def fetch_list(cfg: Config, limit: int = 100, throttle: Throttle | None = None,
               timeout: float = 180.0,
               cancel: threading.Event | None = None) -> list[Playlist]:
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg),
        "--playlist-end", str(max(1, limit)),
        "--print", "%(id)s\t%(title)s",
        FEED_PLAYLISTS,
    ]
    result = _run(command, throttle, timeout, cancel, "the playlist list")
    found = parse_list(result.stdout)
    if found:
        return found
    raise _blame(result, "the playlist list")


def fetch_items(cfg: Config, playlist_id: str, limit: int = 300,
                throttle: Throttle | None = None, timeout: float = 300.0,
                cancel: threading.Event | None = None) -> list[PlaylistItem]:
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg),
        "--playlist-end", str(max(1, limit)),
        "--print", ITEM_FIELDS,
        PLAYLIST_URL.format(playlist_id=playlist_id),
    ]
    result = _run(command, throttle, timeout, cancel, "the playlist")
    found = parse_items(result.stdout)
    if found:
        return found
    # An empty playlist is a real thing and not a failure, so a clean run that
    # simply had nothing in it is reported as nothing rather than as a problem.
    if not (result.stderr or "").strip():
        return []
    raise _blame(result, "the playlist")
