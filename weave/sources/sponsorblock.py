"""The parts of a video other viewers have marked, from SponsorBlock.

SponsorBlock (sponsor.ajay.app) is a database its users fill: where a sponsor
read starts and ends, an intro, a reminder to subscribe. Its API and data are
shared under CC BY-NC-SA 4.0, which a program that calls it and ships none of
its data may do, saying where they come from. The settings page and the README
say so.

Asked the private way its own documentation recommends and yt-dlp uses: only
the first four characters of a hash of the video's id go out, the answer holds
every video whose hash starts with them, about a hundred and twenty measured,
and the one wanted is picked out here. SponsorBlock never learns which video it
was.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlencode

from ..net import Fetcher, HttpError

API = "https://sponsor.ajay.app/api/skipSegments/"


@dataclass(frozen=True)
class Category:
    key: str
    # As the settings list it, and as a notice or a button names it.
    label: str
    short: str
    # SponsorBlock's own colours, so a span on the bar is the one its users
    # know from everywhere else they meet it.
    colour: str
    # What it does until the person says otherwise: a sponsor is skipped, and
    # everything else is only marked, with a button to skip it.
    default: str


CATEGORIES: tuple[Category, ...] = (
    Category("sponsor", "Sponsor", "sponsor", "#00d400", "skip"),
    Category("selfpromo", "Self promotion", "self promotion", "#ffff00", "button"),
    Category("interaction", "Interaction reminder", "interaction reminder", "#cc00ff", "button"),
    Category("intro", "Intro", "intro", "#00ffff", "button"),
    Category("outro", "Outro, end cards", "outro", "#0202ed", "button"),
    Category("preview", "Preview, recap", "preview", "#008fd6", "button"),
    Category("filler", "Filler", "filler", "#7300ff", "button"),
)
BY_KEY = {one.key: one for one in CATEGORIES}

# What a category can be set to.
SKIP, BUTTON, IGNORE = "skip", "button", "ignore"
ACTIONS = (SKIP, BUTTON, IGNORE)


@dataclass(frozen=True)
class Segment:
    category: str
    start: float
    end: float
    uuid: str
    # How long SponsorBlock thought the video was when it was marked, or 0.
    length: float = 0.0


def prefix(video_id: str) -> str:
    return hashlib.sha256(video_id.encode("ascii")).hexdigest()[:4]


def address(video_id: str) -> str:
    return API + prefix(video_id) + "?" + urlencode({
        "service": "YouTube",
        "categories": json.dumps([one.key for one in CATEGORIES]),
        "actionTypes": json.dumps(["skip"]),
    })


def parse(answer, video_id: str) -> tuple[Segment, ...]:
    """The segments of this one video out of an answer about many."""
    if not isinstance(answer, list):
        return ()
    for entry in answer:
        if not isinstance(entry, dict) or entry.get("videoID") != video_id:
            continue
        found = []
        for one in entry.get("segments") or []:
            if not isinstance(one, dict) or one.get("category") not in BY_KEY:
                continue
            span = one.get("segment")
            if (not isinstance(span, list) or len(span) != 2
                    or not all(isinstance(at, (int, float)) for at in span)):
                continue
            start, end = float(span[0]), float(span[1])
            # A whole video marked as one thing is [0, 0], and nothing to skip.
            if end <= start:
                continue
            length = one.get("videoDuration")
            found.append(Segment(one["category"], start, end, str(one.get("UUID") or ""),
                                 float(length) if isinstance(length, (int, float)) else 0.0))
        return tuple(sorted(found, key=lambda segment: segment.start))
    return ()


def fits(segment: Segment, length: float) -> bool:
    """Whether a segment was marked on the video as it is now. A video cut
    after it was marked moves everything, so one marked on a length that
    differs is dropped, by yt-dlp's own rule: under a second off, or under five
    seconds and a twentieth of the segment."""
    if not segment.length or length <= 0:
        return True
    off = abs(length - segment.length)
    return off < 1 or (off < 5 and off / (segment.end - segment.start) < 0.05)


def fetch(fetcher: Fetcher, video_id: str) -> tuple[Segment, ...]:
    """One request. A hash nobody has marked anything under answers 404,
    which is an answer of none rather than a failure."""
    try:
        raw = fetcher.get_bytes(address(video_id))
    except HttpError as exc:
        if exc.status == 404:
            return ()
        raise
    try:
        answer = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError("SponsorBlock returned something unreadable") from exc
    return parse(answer, video_id)
