"""Dislike counts, from the archive that kept them.

YouTube stopped publishing the number, so it comes from returnyoutubedislike,
which estimates it from what its own users report. It is an estimate rather
than a fact and is labelled as such in the interface.

The address matters. The obvious one on the project's own domain answers with a
404 for both spellings of the path. The working host is a separate one.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..net import Fetcher

VOTES_URL = "https://returnyoutubedislikeapi.com/votes?videoId={video_id}"


@dataclass(frozen=True)
class Votes:
    likes: int | None
    dislikes: int | None
    views: int | None


def parse(payload: dict) -> Votes:
    def number(name: str) -> int | None:
        value = payload.get(name)
        return int(value) if isinstance(value, (int, float)) else None

    return Votes(likes=number("likes"), dislikes=number("dislikes"), views=number("viewCount"))


def fetch(fetcher: Fetcher, video_id: str) -> Votes:
    import json

    raw = fetcher.get_bytes(VOTES_URL.format(video_id=video_id))
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError("the dislike service returned something unreadable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("the dislike service returned something unreadable")
    return parse(payload)
