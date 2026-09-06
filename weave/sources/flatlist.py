"""One parser for the flat video lists.

Recommendations, a playlist's contents and a search all come back from yt-dlp
in the same shape, so they are read in one place rather than three. Fields are
tab separated, because a title can contain very nearly anything else.

Two things worth keeping in mind about these lists. They mix in rows that are
not videos at all, radio playlists whose id is thirteen characters and whose
every other field is NA, and dropped here rather than in each caller.

A playlist adds a third case a search or a recommendation never produces: a
video the owner made private, or one that no longer exists. Both keep a real
id and every other field goes NA, but the title is not blank, it is YouTube's
own placeholder text. That is a real row, not junk, so it is named here
rather than dropped, and left to the caller that knows what a playlist is
supposed to do with it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ids import CHANNEL_ID, is_video_id

FIELDS = ("%(id)s\t%(title)s\t%(channel)s\t%(channel_id)s\t%(duration)s"
          "\t%(thumbnails.-1.url)s\t%(view_count)s\t%(timestamp)s")

# What turns "3 weeks ago" in the listing into a date. YouTube sends the age of
# a video in every listing as a relative phrase, and yt-dlp parses it only when
# asked to, so without this the publish time comes back empty for everything
# that is not the feed. It is approximate by nature, since that phrase is all
# there is, which is the same thing other clients show.
APPROXIMATE_DATES = ["--extractor-args", "youtubetab:approximate_date"]


@dataclass(frozen=True)
class FlatVideo:
    ext_id: str
    title: str
    channel_name: str | None = None
    channel_ext_id: str | None = None
    duration_s: int | None = None
    thumbnail_url: str | None = None
    views: int | None = None
    published_at: int | None = None


# The exact titles YouTube substitutes for a playlist entry it will not
# resolve. Measured against a real playlist rather than assumed: both come
# back with a valid video id, no channel, no thumbnail, and this text as the
# whole title.
UNAVAILABLE_TITLES = frozenset({"[Private video]", "[Deleted video]"})


def is_unavailable(item: FlatVideo) -> bool:
    return item.title in UNAVAILABLE_TITLES


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
            published_at=_number(parts[7]) if len(parts) > 7 else None,
        ))
    return out


def as_row(item: FlatVideo) -> dict:
    """The shape the database and the grid both expect."""
    return {
        "ext_id": item.ext_id, "title": item.title,
        "channel_name": item.channel_name, "channel_ext_id": item.channel_ext_id,
        "duration_s": item.duration_s, "thumbnail_url": item.thumbnail_url,
        "views": item.views, "published_at": item.published_at,
    }
