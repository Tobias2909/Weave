"""YouTube Music, through ytmusicapi.

Signing in costs nothing extra. The library is reached with the same browser
cookies everything else here already uses, turned into the headers ytmusicapi
expects. It decides that a login is a browser login by the presence of an
authorization header carrying a SAPISIDHASH, which it can compute itself from
the cookie, so nothing has to be copied out of a developer console.

Only a handful of cookies matter. Handing over the whole jar produces a header
of well over a hundred kilobytes, which no server will accept.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

ORIGIN = "https://music.youtube.com"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

# What a signed in request actually needs.
ESSENTIAL_COOKIES = {
    "SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO", "PREF", "SIDCC",
    "__Secure-1PAPISID", "__Secure-3PAPISID", "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
}


class MusicError(RuntimeError):
    pass


@dataclass(frozen=True)
class Track:
    video_id: str
    title: str
    artist: str
    album: str
    duration: str
    thumbnail_url: str

    @property
    def key(self) -> str:
        return f"yt:{self.video_id}"


class _Quiet:
    def debug(self, *args, **kwargs) -> None:
        pass

    info = warning = error = debug


def cookie_header(profile_path: str) -> str:
    from yt_dlp.cookies import extract_cookies_from_browser

    jar = extract_cookies_from_browser("firefox", os.path.expanduser(profile_path), _Quiet())
    pairs = {c.name: c.value for c in jar
             if "youtube.com" in (c.domain or "") and c.name in ESSENTIAL_COOKIES}
    if "__Secure-3PAPISID" not in pairs:
        raise MusicError("the browser profile holds no YouTube login")
    return "; ".join(f"{name}={value}" for name, value in pairs.items())


# Which identity the request speaks as. A Google account can carry more than
# one YouTube identity, and cookies alone do not say which is in use. The
# account index does not select it, and neither does the channel id, which is
# answered with a server error. The web client sends a numeric page id that it
# reads out of the page it was served, and that is what picks the right one.
#
# Without it, an account whose music lives on a second identity looks like a
# brand new listener. Measured on one such account, sending it turned one
# playlist into seventy four and no liked songs into two thousand.
_page_id: str | None = None
_page_id_looked_for = False
_configured_identity: str | None = None


def configure(identity: str | None) -> None:
    """Pin which identity to speak as, rather than reading it off the page.

    Discovery follows whichever identity the browser is currently using, which
    is the right one almost always, since it is whichever was last used there.
    This is for the case where somebody keeps two and wants the other."""
    global _configured_identity, _page_id_looked_for, _page_id
    value = (identity or "").strip()
    _configured_identity = value if value and value != "auto" else None
    _page_id_looked_for = False
    _page_id = None

PAGE_ID_PATTERN = re.compile(r'"DELEGATED_SESSION_ID"\s*:\s*"(\d{5,40})"')


def page_id(profile_path: str, force: bool = False) -> str | None:
    """Read the identity out of the music page, once per run."""
    global _page_id, _page_id_looked_for
    if _configured_identity:
        return _configured_identity
    if _page_id_looked_for and not force:
        return _page_id

    _page_id_looked_for = True
    try:
        import requests

        response = requests.get(ORIGIN + "/", timeout=30, headers={
            "User-Agent": USER_AGENT,
            "Cookie": cookie_header(profile_path),
            "Accept-Language": "en-US,en;q=0.9",
        })
        found = PAGE_ID_PATTERN.search(response.text)
        _page_id = found.group(1) if found else None
    except Exception:
        # An account with only one identity has none, and that is fine.
        _page_id = None
    return _page_id


def client(profile_path: str):
    """A signed in client. Built fresh rather than kept, because the
    authorization header is stamped with the time it was made."""
    from ytmusicapi import YTMusic
    from ytmusicapi.helpers import get_authorization, sapisid_from_cookie

    cookie = cookie_header(profile_path)
    try:
        sapisid = sapisid_from_cookie(cookie)
    except KeyError as exc:
        raise MusicError("the browser profile holds no YouTube login") from exc
    headers = {
        "cookie": cookie,
        "authorization": get_authorization(f"{sapisid} {ORIGIN}"),
        "x-goog-authuser": "0",
        "user-agent": USER_AGENT,
        "origin": ORIGIN,
        "accept-language": "en-US,en;q=0.9",
    }
    identity = page_id(profile_path)
    if identity:
        headers["x-goog-pageid"] = identity
    return YTMusic(headers)


def _thumb(item: dict) -> str:
    thumbs = item.get("thumbnails") or []
    return str(thumbs[-1].get("url") or "") if thumbs else ""


def _artist(item: dict) -> str:
    artists = item.get("artists") or []
    names = [str(a.get("name")) for a in artists if isinstance(a, dict) and a.get("name")]
    return ", ".join(names)


def to_track(item: dict) -> Track | None:
    video_id = item.get("videoId")
    if not isinstance(video_id, str) or not video_id:
        return None
    album = item.get("album")
    return Track(
        video_id=video_id,
        title=str(item.get("title") or ""),
        artist=_artist(item),
        album=str(album.get("name")) if isinstance(album, dict) else "",
        duration=str(item.get("duration") or ""),
        thumbnail_url=_thumb(item),
    )


def to_tracks(items: list) -> list[Track]:
    out = []
    for item in items or []:
        if isinstance(item, dict):
            track = to_track(item)
            if track is not None:
                out.append(track)
    return out


def search(profile_path: str, query: str, limit: int = 25) -> list[Track]:
    if not query.strip():
        return []
    try:
        return to_tracks(client(profile_path).search(query, filter="songs", limit=limit))
    except MusicError:
        raise
    except Exception as exc:
        raise MusicError(f"{type(exc).__name__}: {exc}") from exc


def playlists(profile_path: str, limit: int = 40) -> list[dict]:
    try:
        found = client(profile_path).get_library_playlists(limit=limit)
    except MusicError:
        raise
    except Exception as exc:
        raise MusicError(f"{type(exc).__name__}: {exc}") from exc
    return [{"id": str(p.get("playlistId") or ""), "title": str(p.get("title") or ""),
             "count": p.get("count"), "thumbnail": _thumb(p)}
            for p in found or [] if p.get("playlistId")]


def playlist_tracks(profile_path: str, playlist_id: str,
                    limit: int = 200) -> tuple[list[Track], int]:
    """The playable tracks, and how many were offered.

    A playlist can be mostly dead. One here lists three and a half thousand
    entries of which fewer than a dozen still exist, and an entry that has gone
    carries no video id at all, so the two numbers are worth reporting rather
    than leaving it looking as though the fetch failed.
    """
    try:
        if playlist_id == "LIKED":
            found = client(profile_path).get_liked_songs(limit=limit)
        else:
            found = client(profile_path).get_playlist(playlist_id, limit=limit)
    except MusicError:
        raise
    except Exception as exc:
        raise MusicError(f"{type(exc).__name__}: {exc}") from exc
    offered = (found or {}).get("tracks") or []
    return to_tracks(offered), len(offered)


def radio(profile_path: str, video_id: str, limit: int = 40) -> list[Track]:
    """A station built from one track, which is where most listening starts
    when there is no library to speak of."""
    try:
        found = client(profile_path).get_watch_playlist(videoId=video_id, limit=limit)
    except MusicError:
        raise
    except Exception as exc:
        raise MusicError(f"{type(exc).__name__}: {exc}") from exc
    return to_tracks((found or {}).get("tracks") or [])


def home(profile_path: str, limit: int = 6) -> list[dict]:
    """The shelves YouTube Music opens on.

    Most of them are playlists rather than songs, so an entry says which it is
    and the caller expands a playlist only when it is chosen.
    """
    try:
        shelves = client(profile_path).get_home(limit=limit)
    except MusicError:
        raise
    except Exception as exc:
        raise MusicError(f"{type(exc).__name__}: {exc}") from exc

    out = []
    for shelf in shelves or []:
        items = []
        for item in shelf.get("contents") or []:
            if not isinstance(item, dict):
                continue
            video_id = item.get("videoId")
            playlist_id = item.get("playlistId")
            if not video_id and not playlist_id:
                continue
            items.append({
                "title": str(item.get("title") or ""),
                "subtitle": _artist(item) or str(item.get("description") or ""),
                "videoId": str(video_id or ""),
                "playlistId": str(playlist_id or ""),
                "thumbnail": _thumb(item),
            })
        if items:
            out.append({"title": str(shelf.get("title") or ""), "items": items})
    return out
