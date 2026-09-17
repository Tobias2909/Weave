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


# The oldest ytmusicapi whose watch parser survives a station.  Everything
# before it reads ["tabRenderer"]["endpoint"]["browseEndpoint"] straight out
# of the payload, and YouTube stopped putting an endpoint on that tab, so
# pressing a song came back as a bare KeyError: 'endpoint'.  MEASURED against
# the released wheels 2026-09-10: 1.9.1, 1.10.3 and 1.11.1 all carry the bare
# reading, 1.12.2 asks for it with nav(..., none_if_absent) and gets None.
NEEDED = (1, 12, 2)


def installed() -> tuple[int, ...]:
    """The ytmusicapi version, as numbers. Empty when it is not installed at
    all, which is a different thing and says so where it is asked."""
    try:
        from ytmusicapi import __version__ as version
    except Exception:
        return ()
    out = []
    for part in str(version).split("."):
        # Leading digits only, and stop at the first piece that has none.
        # A pre release is 1.13.0rc1 and a development build 1.13.0.dev3, and
        # both have to compare as the release they are working towards rather
        # than as some larger number made of the letters' digits.
        digits = ""
        for char in part:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def too_old() -> str:
    """What is wrong with the installed ytmusicapi, in a sentence, or empty
    when there is nothing wrong with it."""
    have = installed()
    if not have or have >= NEEDED:
        return ""
    return (f"ytmusicapi {'.'.join(str(n) for n in have)} is installed and "
            f"{'.'.join(str(n) for n in NEEDED)} or newer is needed")


def _blame(what: str, exc: Exception) -> MusicError:
    """One sentence naming the call that failed, since every music failure
    reaches a person as one line in the window and "KeyError: 'endpoint'" on
    its own says nothing about which of them broke or why. An old library is
    named as such, because that answer is a version and not a bug here."""
    said = f"{what} said {type(exc).__name__}: {exc}"
    stale = too_old()
    return MusicError(f"{said}. {stale}" if stale else said)


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
    # The first named artist's own page, empty when the entry names nobody
    # reachable, which is the case for a compilation.
    artist_id: str = ""

    @property
    def key(self) -> str:
        return f"yt:{self.video_id}"


class _Quiet:
    def debug(self, *args, **kwargs) -> None:
        pass

    info = warning = error = debug


def cookie_header(profile_path: str | None) -> str:
    """The few cookies the music requests need, out of the browser jar.

    A profile path that is not there is a sentence rather than a traceback:
    yt-dlp raises FileNotFoundError for a missing profile directory, and this
    is called from a worker whose only way of saying anything is a MusicError.
    None means nothing here knows where the profile is, which is yt-dlp's cue
    to look for one itself.
    """
    from yt_dlp.cookies import extract_cookies_from_browser

    where = os.path.expanduser(profile_path) if profile_path else None
    try:
        jar = extract_cookies_from_browser("firefox", where, _Quiet())
    except (OSError, ValueError) as exc:
        raise MusicError(f"the browser profile could not be read, {exc}") from exc
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


def page_id(profile_path: str | None, force: bool = False) -> str | None:
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


def client(profile_path: str | None):
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
    """The largest picture an entry carries.

    Two spellings, because the library's own parsers do not agree. A song from
    a search, a playlist or a home shelf carries `thumbnails`, while a song
    from a station carries the same list under `thumbnail`. Reading only the
    first spelling is what left a station with no pictures at all, in the list,
    in the queue and beside what was playing.
    """
    thumbs = item.get("thumbnails") or item.get("thumbnail") or []
    if not isinstance(thumbs, list) or not thumbs:
        return ""
    largest = thumbs[-1]
    if not isinstance(largest, dict):
        return ""
    return bigger(str(largest.get("url") or ""))


# Large enough for the picture beside what is playing, which is the biggest
# any of these is ever drawn. Asking for no size at all is what the channel
# avatars did once, and an unresized upload came back at 8334 square and was
# refused by the image reader for being over its decode allowance.
THUMB_PX = 544
_SIZED = re.compile(r"=w\d+-h\d+")


def bigger(url: str) -> str:
    """The same picture at a size worth looking at.

    What a listing hands back is sized for the listing it came from, and what
    comes back beside a related song is small enough to see the pixels in when
    it is drawn as artwork. The picture service takes the size in the address,
    so a larger one is asked for rather than the small one being scaled up.

    Addresses that do not carry a size are left exactly as they are, which is
    every ordinary video thumbnail.
    """
    return _SIZED.sub(f"=w{THUMB_PX}-h{THUMB_PX}", url, count=1)


def _artist(item: dict) -> str:
    return ", ".join(a["name"] for a in artists_of(item))


def artists_of(item: dict) -> list[dict]:
    """Who made this, each with the address of their own page where there is
    one. The id is what makes a name worth pressing, and it is the only way to
    reach the music of a channel whose songs are uploaded by another one."""
    out = []
    for artist in item.get("artists") or []:
        if not isinstance(artist, dict) or not artist.get("name"):
            continue
        out.append({"name": str(artist["name"]), "id": str(artist.get("id") or "")})
    return out


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
        # A station spells the length differently as well.
        duration=str(item.get("duration") or item.get("length") or ""),
        thumbnail_url=_thumb(item),
        artist_id=next((a["id"] for a in artists_of(item) if a["id"]), ""),
    )


def to_tracks(items: list) -> list[Track]:
    out = []
    for item in items or []:
        if isinstance(item, dict):
            track = to_track(item)
            if track is not None:
                out.append(track)
    return out


def search(profile_path: str | None, query: str, limit: int = 25) -> list[Track]:
    if not query.strip():
        return []
    try:
        return to_tracks(client(profile_path).search(query, filter="songs", limit=limit))
    except MusicError:
        raise
    except Exception as exc:
        raise _blame("search", exc) from exc


def playlists(profile_path: str | None, limit: int = 40) -> list[dict]:
    try:
        found = client(profile_path).get_library_playlists(limit=limit)
    except MusicError:
        raise
    except Exception as exc:
        raise _blame("the playlist list", exc) from exc
    return [{"id": str(p.get("playlistId") or ""), "title": str(p.get("title") or ""),
             "count": p.get("count"), "thumbnail": _thumb(p)}
            for p in found or [] if p.get("playlistId")]


def playlist_tracks(profile_path: str | None, playlist_id: str,
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
        raise _blame("the playlist", exc) from exc
    offered = (found or {}).get("tracks") or []
    return to_tracks(offered), len(offered)


def history(profile_path: str | None, limit: int = 200) -> list[dict]:
    """What the music service remembers having played.

    Measured against a real account, this answers with a couple of hundred
    songs, each carrying an id, a title, artists, a length and a picture. What
    it does not carry is a time. Every row says only a phrase such as today or
    last week, so that phrase is passed on as it stands rather than being
    turned into a timestamp it cannot support.
    """
    try:
        found = client(profile_path).get_history()
    except MusicError:
        raise
    except Exception as exc:
        raise _blame("the listening history", exc) from exc
    out: list[dict] = []
    for item in (found or [])[:limit]:
        video_id = str(item.get("videoId") or "").strip()
        if not video_id:
            continue
        out.append({
            "ext_id": video_id,
            "title": str(item.get("title") or ""),
            "artist": _artist(item),
            "thumbnail_url": _thumb(item),
            "duration_s": item.get("duration_seconds"),
            "played_text": str(item.get("played") or "") or None,
        })
    return out


def watch(profile_path: str | None, video_id: str, limit: int = 40) -> dict:
    """The station built from one track, and the two addresses that come with
    it for free.

    The same answer carries the tracks, the address of the words for this song
    and the address of what is like it. Asking again for either of those would
    be a second request for something already in hand, so all three are kept
    and the caller takes what it needs.
    """
    try:
        found = client(profile_path).get_watch_playlist(videoId=video_id, limit=limit)
    except MusicError:
        raise
    except Exception as exc:
        raise _blame("the station", exc) from exc
    found = found or {}
    return {
        "tracks": to_tracks(found.get("tracks") or []),
        "lyrics_id": str(found.get("lyrics") or "") or None,
        "related_id": str(found.get("related") or "") or None,
    }


def radio(profile_path: str | None, video_id: str, limit: int = 40) -> list[Track]:
    """A station built from one track, which is where most listening starts
    when there is no library to speak of."""
    return watch(profile_path, video_id, limit)["tracks"]


def lyrics(profile_path: str | None, browse_id: str) -> dict:
    """The words for a song, at the address the station answer gave.

    Not every song has any, and a song with none is a normal answer rather than
    a failure, so an empty result is returned as such and nothing is said to
    the person about it beyond the page being empty.
    """
    if not browse_id:
        return {"text": "", "source": ""}
    try:
        found = client(profile_path).get_lyrics(browse_id)
    except MusicError:
        raise
    except Exception as exc:
        raise _blame("the words", exc) from exc
    if not found:
        return {"text": "", "source": ""}
    # A newer library answers with an object rather than a plain mapping, and
    # both shapes are in the wild depending on which one a distribution ships.
    text = getattr(found, "lyrics", None)
    source = getattr(found, "source", None)
    if text is None and isinstance(found, dict):
        text = found.get("lyrics")
        source = found.get("source")
    if not isinstance(text, str):
        # Timed words arrive as a list of lines, which is a shape this page
        # does not draw yet. Nothing is invented from it here.
        return {"text": "", "source": str(source or "")}
    return {"text": text, "source": str(source or "")}


def related(profile_path: str | None, browse_id: str) -> list[Track]:
    """What YouTube Music puts next to this song, at the address the station
    answer gave. The shelves it returns are flattened, since the page shows one
    list and the headings say nothing a person here would act on."""
    if not browse_id:
        return []
    try:
        found = client(profile_path).get_song_related(browse_id)
    except MusicError:
        raise
    except Exception as exc:
        raise _blame("what is like it", exc) from exc
    items: list = []
    for shelf in found or []:
        if isinstance(shelf, dict):
            items.extend(shelf.get("contents") or [])
    return to_tracks(items)


def home(profile_path: str | None, limit: int = 6) -> list[dict]:
    """The shelves YouTube Music opens on.

    Most of them are playlists rather than songs, so an entry says which it is
    and the caller expands a playlist only when it is chosen.
    """
    try:
        shelves = client(profile_path).get_home(limit=limit)
    except MusicError:
        raise
    except Exception as exc:
        raise _blame("the shelves", exc) from exc

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
                # So the name under a tile can be pressed here as well. A
                # shelf entry that names nobody reachable carries nothing.
                "artistId": next((a["id"] for a in artists_of(item) if a["id"]), ""),
            })
        if items:
            out.append({"title": str(shelf.get("title") or ""), "items": items})
    return out


def artist_of(profile_path: str | None, video_id: str) -> list[dict]:
    """Who the music service says made this video.

    The way to find the music belonging to an ordinary channel. Much of what an
    artist releases is uploaded by a separate generated channel, so there is no
    reliable walk from one channel to the other. There is a reliable walk from a
    video to its artist, and every channel here already has videos.
    """
    if not video_id:
        return []
    try:
        found = client(profile_path).get_watch_playlist(videoId=video_id, limit=1)
    except MusicError:
        raise
    except Exception as exc:
        raise _blame("who made it", exc) from exc
    tracks = (found or {}).get("tracks") or []
    return artists_of(tracks[0]) if tracks and isinstance(tracks[0], dict) else []


def _releases(page: dict) -> list[dict]:
    """The albums and singles an artist page names.

    These ride along with the page that was read for the songs, so listing
    them costs nothing at all. What is ON one is a call of its own, which is
    why the two are separate questions here.

    Singles are kept apart from albums because a single is a release of one or
    two songs and a shelf of them reads as a pile of one song albums. The
    window puts them together into a group of their own.
    """
    out: list[dict] = []
    for name in ("albums", "singles"):
        shelf = page.get(name)
        shelf = shelf if isinstance(shelf, dict) else {}
        for item in shelf.get("results") or []:
            if not isinstance(item, dict):
                continue
            # Either way in will do. An album carries both; a single, measured
            # on a real account, carries only the browse id.
            playlist_id = str(item.get("audioPlaylistId") or "")
            browse_id = str(item.get("browseId") or "")
            if not playlist_id and not browse_id:
                continue
            out.append({
                "kind": "single" if name == "singles" else "album",
                "title": str(item.get("title") or ""),
                "year": str(item.get("year") or ""),
                "playlist_id": playlist_id,
                "browse_id": browse_id,
                "thumbnail": _thumb(item),
            })
    return out


def release_tracks(profile_path: str | None, playlist_id: str = "",
                   browse_id: str = "", limit: int = 100) -> list[Track]:
    """What is on one album or single. One request, whichever way in is used.

    Measured against a real account, fifteen of these in a row answered in
    0.11 to 0.24 s each with no refusal and no slowdown, all to the same
    music browse endpoint the artist page itself is read from.
    """
    try:
        if playlist_id:
            found = client(profile_path).get_playlist(playlist_id, limit=limit)
        elif browse_id:
            found = client(profile_path).get_album(browse_id)
        else:
            return []
    except MusicError:
        raise
    except Exception as exc:
        raise _blame("the album", exc) from exc
    return to_tracks((found or {}).get("tracks") or [])


def _no_artist() -> dict:
    """Not an artist, said freshly every time.

    Built rather than shared, because a copy of a shared one is shallow and the
    list inside it stays the same list, so a caller adding to what it was given
    would change what every later call answered.
    """
    return {"name": "", "songs": [], "channel_id": "", "releases": []}


def artist(profile_path: str | None, channel_id: str, limit: int = 200) -> dict:
    """An artist's own page, flattened to the songs on it.

    The page itself shows only a handful of songs, five of them, with the rest
    behind an address for the full list. Reading the shelf alone is what made
    this look like an artist with five songs to their name, so the address is
    followed where there is one and the shelf is only the fallback.

    The albums and singles named on the page come back with it, since they are
    already in the answer. What is on each one is asked for separately, by
    `release_tracks`, because that is a call each.
    """
    if not channel_id:
        return _no_artist()
    try:
        page = client(profile_path).get_artist(channel_id)
    except MusicError:
        raise
    except (KeyError, TypeError):
        # An artist page is read through a header that an ordinary channel does
        # not have, and the library reaches for it without looking. So this is
        # how "not an artist" arrives, and it is an answer rather than a fault.
        # Raised as one, it reached the window as a KeyError about a renderer.
        return _no_artist()
    except Exception as exc:
        raise _blame("the artist", exc) from exc
    page = page or {}
    # The channel you would subscribe to, which is not the one asked about. An
    # artist is reached through a browse id that is often a generated channel
    # carrying nothing but the songs, while this is the channel with the
    # videos, the pictures and everything else on it.
    real = str(page.get("channelId") or "")
    shelf = page.get("songs")
    shelf = shelf if isinstance(shelf, dict) else {}
    full = str(shelf.get("browseId") or "")
    releases = _releases(page)
    if full:
        songs, _offered = playlist_tracks(profile_path, full, limit=limit)
        if songs:
            return {"name": str(page.get("name") or ""), "songs": songs,
                    "channel_id": real, "releases": releases}
    return {"name": str(page.get("name") or ""),
            "songs": to_tracks(shelf.get("results") or []), "channel_id": real,
            "releases": releases}
