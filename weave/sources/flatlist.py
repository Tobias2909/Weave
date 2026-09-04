"""One parser for the flat video lists.

Recommendations, a playlist's contents and a search all come back from yt-dlp
in the same shape, so they are read in one place rather than three. Fields are
tab separated, because a title can contain very nearly anything else.

Two things worth keeping in mind about these lists. They mix in rows that are
not videos at all, radio playlists whose id is thirteen characters and whose
every other field is NA, and they carry rows for videos that have been deleted,
which come back with no title. Both are dropped here rather than in each
caller.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ids import CHANNEL_ID, is_video_id

FIELDS = ("%(id)s\t%(title)s\t%(channel)s\t%(channel_id)s\t%(duration)s"
          "\t%(thumbnails.-1.url)s\t%(view_count)s")


@dataclass(frozen=True)
class FlatVideo:
    ext_id: str
    title: str
    channel_name: str | None = None
    channel_ext_id: str | None = None
    duration_s: int | None = None
    thumbnail_url: str | None = None
    views: int | None = None


def optional(text: str) -> str | None:
    text = (text or "").strip()
    return None if not text or text == "NA" else text


def _number(text: str) -> int | None:
    value = optional(text)
    try:
        return int(float(value)) if value else None
    except ValueError:
        return None


def _field(parts: list[str], index: int) -> str | None:
    return optional(parts[index]) if len(parts) > index else None


def parse(text: str) -> list[FlatVideo]:
    out: list[FlatVideo] = []
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
        channel_id = _field(parts, 3)
        out.append(FlatVideo(
            ext_id=ext_id,
            title=title,
            channel_name=_field(parts, 2),
            channel_ext_id=channel_id if channel_id and CHANNEL_ID.match(channel_id) else None,
            duration_s=_number(parts[4]) if len(parts) > 4 else None,
            thumbnail_url=_field(parts, 5),
            views=_number(parts[6]) if len(parts) > 6 else None,
        ))
    return out


def as_row(item: FlatVideo) -> dict:
    """The shape the database and the grid both expect."""
    return {
        "ext_id": item.ext_id, "title": item.title,
        "channel_name": item.channel_name, "channel_ext_id": item.channel_ext_id,
        "duration_s": item.duration_s, "thumbnail_url": item.thumbnail_url,
        "views": item.views,
    }
