"""What YouTube puts beside a video on its watch page, for the companion page.

The same call the watch page makes, youtubei's next, made signed in with the
browser's cookies, because the side of a watch page is made for whoever is
looking. Measured 2026-10-02 for one song: a signed in answer shared one video
in twenty six with an anonymous one.

One call with the video's mix named alongside it answers three things at once:
the mix YouTube builds from the video, the chips across the top of the side
(All, From the artist, a genre, Related and the like), and the videos under
All. A chip other than those two is one more call, with the token the chip
carries. Shorts shelves and playlists in the side are left out, since what is
picked here goes into mpv one video at a time.

Everything about the answer's shape is read in this file and nowhere else, so
when YouTube moves it there is one place to follow it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..net import Fetcher

ORIGIN = "https://www.youtube.com"
ENDPOINT = ORIGIN + "/youtubei/v1/next?prettyPrint=false"
# The mix is no chip of YouTube's own. It is the playlist the watch page plays
# on its own after a song, and is offered here as the first chip.
MIX = "Mix"
ALL = "All"
# Asked when no version can be read from yt-dlp. Close enough to be answered.
FALLBACK_VERSION = "2.20260708.00.00"


class WatchNextError(RuntimeError):
    pass


@dataclass(frozen=True)
class Card:
    video_id: str
    title: str
    channel: str = ""
    channel_id: str = ""
    # As YouTube writes them: 3:25, LIVE, 1.3M views, 2 years ago.
    duration: str = ""
    views: str = ""
    age: str = ""
    picture: str = ""


@dataclass(frozen=True)
class Chip:
    label: str
    token: str = ""


@dataclass(frozen=True)
class Answer:
    chips: list[Chip]
    # What each chip shows, for the chips one call answered.
    cards: dict[str, list[Card]]


def client_version() -> str:
    """The web client's version, from yt-dlp, which keeps it current."""
    try:
        from yt_dlp.extractor.youtube._base import INNERTUBE_CLIENTS

        return str(INNERTUBE_CLIENTS["web"]["INNERTUBE_CONTEXT"]["client"]["clientVersion"])
    except (ImportError, KeyError, TypeError):
        return FALLBACK_VERSION


def headers(profile_path: str | None) -> dict[str, str]:
    """The cookies, the identity and an authorization stamped now.

    The cookies and the identity are the ones the suggestions read and keep.
    The authorization is a hash of the session cookie, the origin and the
    time, so it is made afresh for every call.
    """
    from ytmusicapi.helpers import get_authorization, sapisid_from_cookie

    from . import suggest

    try:
        found = suggest.signed_in_headers(profile_path)
    except suggest.SuggestError as exc:
        raise WatchNextError(str(exc)) from exc
    try:
        sapisid = sapisid_from_cookie(found["Cookie"])
    except KeyError as exc:
        raise WatchNextError("the browser profile holds no YouTube login") from exc
    found.update({
        "Authorization": get_authorization(f"{sapisid} {ORIGIN}"),
        "X-Goog-AuthUser": "0",
        "Origin": ORIGIN,
        "X-Origin": ORIGIN,
    })
    return found


def _ask(fetcher: Fetcher, body: dict, sent_headers: dict[str, str] | None) -> dict:
    body = dict(body, context={"client": {"clientName": "WEB",
                                          "clientVersion": client_version(),
                                          "hl": "en", "gl": "US"}})
    return fetcher.post_json(ENDPOINT, body, sent_headers)


def beside(fetcher: Fetcher, video_id: str,
           sent_headers: dict[str, str] | None = None) -> Answer:
    """The mix, the chips and All, for one video, in one call."""
    return parse_beside(_ask(fetcher, {"videoId": video_id, "playlistId": "RD" + video_id},
                             sent_headers), video_id)


def chip(fetcher: Fetcher, token: str, sent_headers: dict[str, str] | None = None) -> list[Card]:
    """What one of YouTube's chips shows."""
    return parse_chip(_ask(fetcher, {"continuation": token}, sent_headers))


# ---- reading the answers ------------------------------------------------------

def _get(found, *path):
    for step in path:
        if isinstance(step, int):
            if not isinstance(found, list) or not -len(found) <= step < len(found):
                return None
        elif not isinstance(found, dict):
            return None
        found = found[step] if isinstance(step, int) else found.get(step)
    return found


def _text(found) -> str:
    """A piece of text in any of the three ways YouTube writes one."""
    if isinstance(found, str):
        return found
    if not isinstance(found, dict):
        return ""
    if "content" in found:
        return str(found["content"] or "")
    if "simpleText" in found:
        return str(found["simpleText"] or "")
    return "".join(str(run.get("text") or "") for run in found.get("runs") or []
                   if isinstance(run, dict))


def _lockups(found, out: list) -> list:
    """Every video lockup inside a part of an answer, in order. A shelf of
    Shorts is passed over whole."""
    if isinstance(found, dict):
        if "reelShelfRenderer" in found:
            return out
        if "lockupViewModel" in found:
            out.append(found["lockupViewModel"])
            return out
        for value in found.values():
            _lockups(value, out)
    elif isinstance(found, list):
        for value in found:
            _lockups(value, out)
    return out


def card_of_lockup(lockup: dict) -> Card | None:
    if not isinstance(lockup, dict) or lockup.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
        return None
    video_id = str(lockup.get("contentId") or "")
    meta = _get(lockup, "metadata", "lockupMetadataViewModel") or {}
    title = _text(meta.get("title"))
    if not video_id or not title:
        return None
    rows = _get(meta, "metadata", "contentMetadataViewModel", "metadataRows") or []
    lines = [[_text(part.get("text")) for part in (row.get("metadataParts") or [])
              if isinstance(part, dict)]
             for row in rows if isinstance(row, dict)]
    channel = (lines[0][0] if lines and lines[0] else "").strip()
    facts = lines[1] if len(lines) > 1 else []
    sources = _get(lockup, "contentImage", "thumbnailViewModel", "image", "sources") or []
    picture = str(_get(sources, -1, "url") or "")
    duration = ""
    for overlay in _get(lockup, "contentImage", "thumbnailViewModel", "overlays") or []:
        for badge in _get(overlay, "thumbnailBottomOverlayViewModel", "badges") or []:
            words = str(_get(badge, "thumbnailBadgeViewModel", "text") or "")
            if words:
                duration = words
    channel_id = str(_get(meta, "image", "decoratedAvatarViewModel", "rendererContext",
                          "commandContext", "onTap", "innertubeCommand", "browseEndpoint",
                          "browseId") or "")
    return Card(video_id=video_id, title=title, channel=channel,
                channel_id=channel_id if channel_id.startswith("UC") else "",
                duration=duration, views=facts[0] if facts else "",
                age=facts[1] if len(facts) > 1 else "", picture=picture)


def card_of_mix_row(row: dict) -> Card | None:
    found = _get(row, "playlistPanelVideoRenderer")
    if not isinstance(found, dict):
        return None
    video_id = str(found.get("videoId") or "")
    title = _text(found.get("title"))
    if not video_id or not title:
        return None
    thumbnails = _get(found, "thumbnail", "thumbnails") or []
    channel_id = str(_get(found, "longBylineText", "runs", 0, "navigationEndpoint",
                          "browseEndpoint", "browseId") or "")
    return Card(video_id=video_id, title=title,
                channel=_text(found.get("longBylineText") or found.get("shortBylineText")),
                channel_id=channel_id if channel_id.startswith("UC") else "",
                duration=_text(found.get("lengthText")),
                picture=str(_get(thumbnails, -1, "url") or ""))


def _cards(lockups: list, leave_out: str = "") -> list[Card]:
    out, seen = [], {leave_out}
    for lockup in lockups:
        card = card_of_lockup(lockup)
        if card is not None and card.video_id not in seen:
            seen.add(card.video_id)
            out.append(card)
    return out


def parse_beside(answer: dict, video_id: str = "") -> Answer:
    """The answer to the first call: mix, chips and All. The video itself is
    left out of every list, since it is the one already playing."""
    results = _get(answer, "contents", "twoColumnWatchNextResults")
    if not isinstance(results, dict):
        raise WatchNextError("an answer with no watch page in it")
    side = _get(results, "secondaryResults", "secondaryResults", "results") or []
    chips = [Chip(MIX)]
    for entry in side:
        for found in _get(entry, "relatedChipCloudRenderer", "content", "chipCloudRenderer",
                          "chips") or []:
            label = _text(_get(found, "chipCloudChipRenderer", "text"))
            token = str(_get(found, "chipCloudChipRenderer", "navigationEndpoint",
                             "continuationCommand", "token") or "")
            # All is answered by this very call. Any other chip without a
            # token is one nothing could be asked about.
            if label and label != MIX and (token or label == ALL):
                chips.append(Chip(label, token))
    if len(chips) == 1:
        # Signed out, or a video with nothing to narrow, has no chips at all,
        # and what is under it is All by any other name.
        chips.append(Chip(ALL))
    mix = []
    seen = {video_id}
    for row in _get(results, "playlist", "playlist", "contents") or []:
        card = card_of_mix_row(row)
        if card is not None and card.video_id not in seen:
            seen.add(card.video_id)
            mix.append(card)
    cards = {MIX: mix, ALL: _cards(_lockups(side, []), video_id)}
    return Answer(chips=chips, cards=cards)


def parse_chip(answer: dict) -> list[Card]:
    """The answer to a chip pressed."""
    actions = answer.get("onResponseReceivedEndpoints")
    if not isinstance(actions, list):
        raise WatchNextError("an answer with nothing for the chip in it")
    found = []
    for action in actions:
        for key in ("reloadContinuationItemsCommand", "appendContinuationItemsAction"):
            _lockups(_get(action, key, "continuationItems") or [], found)
    return _cards(found)
