"""Channel RSS, the feed's spine.

Why RSS carries the feed rather than a scraped browse call. It needs no
cookies, it is a documented endpoint, and it is the only cheap source that
gives an exact publish time. It also hands over exact view and like counts,
which yt-dlp does not, since yt-dlp rounds like_count to figures like 310000.

What it does not give, and where that comes from instead.

  duration     absent, filled in by the subscriptions sweep
  Shorts flag  absent, decided by the /shorts/<id> redirect test
  live flag    absent, taken from the subscriptions sweep

Only the newest 15 entries per channel are published, so a very busy channel
can drop an entry between polls. That is what the sweep also covers.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from ..db import VideoRow
from ..ids import channel_key, is_video_id
from ..net import Fetcher

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


@dataclass(frozen=True)
class FeedResult:
    channel_id: str
    channel_title: str | None
    videos: list[VideoRow]


def _epoch(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None


def _int_attr(element: ET.Element | None, name: str) -> int | None:
    if element is None:
        return None
    raw = element.get(name)
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def parse(xml: bytes) -> FeedResult:
    """Parse a channel feed. Tolerates missing fields rather than raising,
    because a single odd entry must not cost the whole channel."""
    root = ET.fromstring(xml)
    feed_channel = root.findtext("yt:channelId", namespaces=_NS) or ""
    feed_title = root.findtext("atom:title", namespaces=_NS)

    videos: list[VideoRow] = []
    for entry in root.findall("atom:entry", _NS):
        ext_id = (entry.findtext("yt:videoId", namespaces=_NS) or "").strip()
        if not is_video_id(ext_id):
            continue
        title = (entry.findtext("atom:title", namespaces=_NS) or "").strip()
        if not title:
            continue
        owner = (entry.findtext("yt:channelId", namespaces=_NS) or feed_channel).strip()
        if not owner:
            continue

        # starRating and statistics sit inside media:group/media:community, so
        # search by descendant rather than by exact path.
        thumbnail = entry.find(".//media:thumbnail", _NS)
        rating = entry.find(".//media:starRating", _NS)
        statistics = entry.find(".//media:statistics", _NS)

        videos.append(VideoRow(
            platform="youtube",
            ext_id=ext_id,
            channel_key=channel_key(owner),
            title=title,
            published_at=_epoch(entry.findtext("atom:published", namespaces=_NS)),
            thumbnail_url=thumbnail.get("url") if thumbnail is not None else None,
            views=_int_attr(statistics, "views"),
            # average is a hardcoded 5.00 and useless. count is the like count.
            likes=_int_attr(rating, "count"),
        ))

    return FeedResult(channel_id=feed_channel, channel_title=feed_title, videos=videos)


def fetch(fetcher: Fetcher, channel_id: str) -> FeedResult:
    return parse(fetcher.get_bytes(FEED_URL.format(channel_id=channel_id)))
