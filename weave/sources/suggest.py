"""What YouTube and YouTube Music suggest for words being typed.

The same request the search box on youtube.com sends with every keystroke, a
few hundred bytes answered in about sixty milliseconds, measured 2026-10-01.
It needs no cookies, and without them it says nothing about anybody.

With them it can say what this account would be offered, but only when it is
also told which of the account's YouTube identities is asking, the same page
id the music requests carry. Measured against twelve searches made here: the
cookies alone changed nothing, while the cookies with the page id added one to
five suggestions on ten of them, none of which an anonymous request ever got.
Which of the two is asked for is a setting, anonymous unless somebody chooses.
"""

from __future__ import annotations

import json
import threading
import time
from urllib.parse import quote

from ..net import Fetcher

YOUTUBE_URL = ("https://suggestqueries-clients6.youtube.com/complete/search"
               "?client=youtube&ds=yt&q={words}")
# How many suggestions are shown. YouTube sends up to fourteen, more than a
# list under a box can hold without covering the page it is about.
SHOWN = 8
# How long the cookies read out of the browser are kept before they are read
# again. Reading them opens the browser's cookie store, which is too slow to
# do for every key pressed, and the session they carry lasts far longer.
COOKIES_KEPT_S = 600

_signed_in: tuple[float, dict[str, str]] | None = None
# The music clients, kept for the same reason. The signed in one carries an
# authorization stamped with the time it was made, so it is made again on the
# same clock as the cookies.
_music_signed_in: tuple[float, object] | None = None
_music_anonymous: object | None = None
_lock = threading.Lock()


class SuggestError(RuntimeError):
    pass


def parse(body: str) -> list[str]:
    """The suggestions in an answer, which arrives wrapped in a call to a
    script function: `window.google.ac.h([...])`."""
    try:
        data = json.loads(body[body.index("(") + 1: body.rindex(")")])
        found = [str(entry[0]) for entry in data[1] if entry and entry[0]]
    except (ValueError, IndexError, TypeError) as exc:
        raise SuggestError(f"an answer that could not be read, {exc}") from exc
    return found[:SHOWN]


def signed_in_headers(profile_path: str | None) -> dict[str, str]:
    """The cookies and the identity the account's own suggestions need, read
    once and kept for a while."""
    global _signed_in
    from . import ytmusic

    with _lock:
        if _signed_in is not None and time.monotonic() - _signed_in[0] < COOKIES_KEPT_S:
            return dict(_signed_in[1])
    try:
        headers = {"Cookie": ytmusic.cookie_header(profile_path)}
    except ytmusic.MusicError as exc:
        raise SuggestError(str(exc)) from exc
    identity = ytmusic.page_id(profile_path)
    if identity:
        headers["X-Goog-PageId"] = identity
    with _lock:
        _signed_in = (time.monotonic(), headers)
    return dict(headers)


def youtube(fetcher: Fetcher, words: str, headers: dict[str, str] | None = None) -> list[str]:
    """What YouTube suggests for these words."""
    words = (words or "").strip()
    if not words:
        return []
    body = fetcher.get_bytes(YOUTUBE_URL.format(words=quote(words)), headers=headers)
    return parse(body.decode("utf-8", "replace"))


def _music_client(profile_path: str | None, signed_in: bool):
    global _music_signed_in, _music_anonymous
    from ytmusicapi import YTMusic

    from . import ytmusic

    with _lock:
        if not signed_in:
            if _music_anonymous is None:
                _music_anonymous = YTMusic()
            return _music_anonymous
        if (_music_signed_in is not None
                and time.monotonic() - _music_signed_in[0] < COOKIES_KEPT_S):
            return _music_signed_in[1]
    made = ytmusic.client(profile_path)
    with _lock:
        _music_signed_in = (time.monotonic(), made)
    return made


def music(profile_path: str | None, words: str, signed_in: bool) -> list[str]:
    """What YouTube Music suggests for these words, signed in or not."""
    words = (words or "").strip()
    if not words:
        return []
    try:
        found = _music_client(profile_path, signed_in).get_search_suggestions(words)
    except Exception as exc:                        # a music client raises anything
        raise SuggestError(f"{type(exc).__name__}: {exc}") from exc
    return [str(text) for text in found if text][:SHOWN]
