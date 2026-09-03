"""Stable keys for videos and channels.

The key scheme is deliberately the same one mpv's volume_per_file.lua already
uses, so a video opened from Weave, from a playlist or from the browser handoff
all resolve to one identity.

  video   yt:<11 char id>      twitch:<login>
  channel yt:<UC channel id>   twitch:<login>

A YouTube video id is 11 characters of [A-Za-z0-9_-]. Anything else is not an
id, which is what keeps the recommendation feed's RD... radio playlist rows out
of the video table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
TWITCH_LOGIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{2,24}$")

# Path prefixes that carry a bare video id as the next segment.
_ID_IN_PATH = ("live", "embed", "shorts", "v")

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com",
                  "music.youtube.com", "youtube-nocookie.com",
                  "www.youtube-nocookie.com"}
_YOUTU_BE_HOSTS = {"youtu.be", "www.youtu.be"}
_TWITCH_HOSTS = {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}


def is_video_id(value: str) -> bool:
    return bool(VIDEO_ID.match(value))


def video_key(ext_id: str, platform: str = "youtube") -> str:
    return f"{'yt' if platform == 'youtube' else 'twitch'}:{ext_id}"


def channel_key(ext_id: str, platform: str = "youtube") -> str:
    return f"{'yt' if platform == 'youtube' else 'twitch'}:{ext_id}"


def youtube_video_id(text: str) -> str | None:
    """Pull a video id out of any YouTube URL form, or accept a bare id.

    Handles watch?v=, youtu.be/, /live/, /embed/, /shorts/ and /v/, and ignores
    every extra query parameter. Dropping those parameters matters more than it
    looks, because mpv names its resume file after the exact URL string, so
    watch?v=X and watch?v=X&t=90s are two different videos to it.
    """
    text = (text or "").strip()
    if not text:
        return None
    if is_video_id(text):
        return text

    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    segments = [s for s in parsed.path.split("/") if s]

    if host in _YOUTU_BE_HOSTS:
        return segments[0] if segments and is_video_id(segments[0]) else None

    if host in _YOUTUBE_HOSTS:
        values = parse_qs(parsed.query).get("v")
        if values and is_video_id(values[0]):
            return values[0]
        if len(segments) >= 2 and segments[0] in _ID_IN_PATH and is_video_id(segments[1]):
            return segments[1]
    return None


def twitch_login(text: str) -> str | None:
    """Pull a channel login out of a twitch.tv URL, or accept a bare login."""
    text = (text or "").strip().lstrip("@")
    if not text:
        return None
    if "/" not in text and ":" not in text and TWITCH_LOGIN.match(text):
        return text.lower()
    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in _TWITCH_HOSTS:
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if not segments or not TWITCH_LOGIN.match(segments[0]):
        return None
    return segments[0].lower()


@dataclass(frozen=True)
class ChannelRef:
    """A requested channel.

    `kind` is "id" when it can be stored right away, or "handle" when it still
    needs one lookup. For a handle, `value` holds the URL path rather than the
    bare name, so `@name`, `c/name` and `user/name` stay distinguishable. They
    are not interchangeable and can point at different channels.
    """

    platform: str
    kind: str
    value: str

    @property
    def url(self) -> str:
        if self.platform == "twitch":
            return f"https://www.twitch.tv/{self.value}"
        if self.kind == "id":
            return f"https://www.youtube.com/channel/{self.value}"
        return f"https://www.youtube.com/{self.value}"


def parse_channel_ref(text: str) -> ChannelRef | None:
    """Understand what was pasted into the add channel box.

    Accepts a UC id, a /channel/UC... URL, an @handle, a legacy /c/ or /user/
    URL, and any twitch.tv channel URL or bare login.
    """
    text = (text or "").strip()
    if not text:
        return None
    if CHANNEL_ID.match(text):
        return ChannelRef("youtube", "id", text)
    if text.startswith("@") and len(text) > 1 and "/" not in text:
        return ChannelRef("youtube", "handle", text)

    probe = text if "://" in text else "https://" + text
    try:
        parsed = urlparse(probe)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    segments = [s for s in parsed.path.split("/") if s]

    if host in _TWITCH_HOSTS:
        login = twitch_login(probe)
        return ChannelRef("twitch", "id", login) if login else None

    if host in _YOUTUBE_HOSTS and segments:
        head = segments[0]
        if head == "channel" and len(segments) >= 2 and CHANNEL_ID.match(segments[1]):
            return ChannelRef("youtube", "id", segments[1])
        if head.startswith("@"):
            return ChannelRef("youtube", "handle", head)
        if head in ("c", "user") and len(segments) >= 2:
            # Keep the prefix. youtube.com/user/x and youtube.com/@x are
            # different addresses and can resolve to different channels.
            return ChannelRef("youtube", "handle", f"{head}/{segments[1]}")

    # A bare word is deliberately rejected. It could be a Twitch login or a
    # YouTube name, and guessing turns a typo into a tracked channel. Finding a
    # channel by name is the search flow's job, not this function's.
    return None


def key_for_media_path(path: str, twitch_hint: str | None = None) -> str | None:
    """Turn whatever mpv reports in its `path` property into a key.

    A resolved Twitch stream is an m3u8 on *.ttvnw.net that names the channel
    nowhere, which is why the caller passes the login it handed to mpv itself.
    """
    if not path:
        return None
    video = youtube_video_id(path)
    if video:
        return video_key(video)
    if ".ttvnw.net" in path or "m3u8" in path:
        return video_key(twitch_hint, "twitch") if twitch_hint else None
    login = twitch_login(path)
    if login:
        return video_key(login, "twitch")
    return None


def watch_url(platform: str, ext_id: str) -> str:
    """The canonical URL to hand to mpv.

    Deliberately minimal, with no extra query parameters. mpv names its resume
    file after the exact URL string, so a stray &t= or &list= would give the
    same video a second identity and lose its position.
    """
    if platform == "twitch":
        return f"https://www.twitch.tv/{ext_id}"
    return f"https://www.youtube.com/watch?v={ext_id}"
