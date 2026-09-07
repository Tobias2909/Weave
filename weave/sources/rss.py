"""Channel RSS, the feed's spine.

Why RSS carries the feed rather than a scraped browse call. It needs no
cookies, it is a documented endpoint, and it is the only cheap source that
gives an exact publish time. It also hands over exact view and like counts,
which yt-dlp does not, since yt-dlp rounds like_count to figures like 310000.

A channel has one feed per tab, not just the one address. Rewriting the UC
prefix of the channel id gives the playlist behind a tab, and that playlist has
its own feed:

  UULF   long form videos          UUSH   Shorts          UULV   streams

Those are disjoint. Asking for UULF is therefore the whole Shorts filter, for
free and in advance, which is why nothing here has to classify anything after
the fact. It matters more than it sounds: the mixed channel feed of a channel
that posts Shorts can be entirely Shorts, so the fifteen entries it publishes
can contain no ordinary video at all.

What it does not give, and where that comes from instead.

  duration     absent, filled in by the subscriptions sweep
  live flag    absent, taken from the subscriptions sweep

Only the newest 15 entries per feed are published, so a very busy channel can
drop an entry between polls. That is what the sweep also covers.

Two shapes, two traps, both measured against the live endpoint:

  the playlist feed's <title> is the name of the tab, "Videos", not the name
  of the channel, and the channel feed's root yt:channelId has the UC prefix
  stripped off. The author block is correct in both, so identity is read from
  there and never from either of those.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from ..db import VideoRow
from ..ids import channel_key, is_video_id
from ..net import Fetcher

_BASE = "https://www.youtube.com/feeds/videos.xml"

# The tab a feed covers, and the playlist prefix that addresses it. CHANNEL is
# the mixed feed, kept as the fallback for a channel that has no videos tab.
VIDEOS = "videos"
SHORTS = "shorts"
LIVE = "live"
CHANNEL = "channel"

_PREFIX = {VIDEOS: "UULF", SHORTS: "UUSH", LIVE: "UULV"}

# What a feed says about the kind of what it carries. The mixed feed says
# nothing, which is the whole reason for preferring the others.
_IS_SHORT = {VIDEOS: False, SHORTS: True, LIVE: False, CHANNEL: None}


def playlist_id(channel_id: str, kind: str) -> str:
    """The uploads playlist behind one of a channel's tabs."""
    prefix = _PREFIX[kind]
    return prefix + channel_id[2:] if channel_id.startswith("UC") else prefix + channel_id


def feed_url(channel_id: str, kind: str = VIDEOS) -> str:
    if kind == CHANNEL:
        return f"{_BASE}?channel_id={channel_id}"
    return f"{_BASE}?playlist_id={playlist_id(channel_id, kind)}"

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
    kind: str = VIDEOS


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


def _author_channel_id(root: ET.Element) -> str:
    """The channel a feed belongs to, taken from the author link.

    Not from the root yt:channelId, which the channel feed publishes without
    its UC prefix, and not from the title, which on a playlist feed names the
    tab instead of the channel.
    """
    uri = root.findtext("atom:author/atom:uri", namespaces=_NS) or ""
    _, sep, tail = uri.partition("/channel/")
    if sep and tail:
        return tail.strip("/")
    raw = (root.findtext("yt:channelId", namespaces=_NS) or "").strip()
    return raw if raw.startswith("UC") else (f"UC{raw}" if raw else "")


def parse(xml: bytes, kind: str = VIDEOS) -> FeedResult:
    """Parse a feed. Tolerates missing fields rather than raising, because a
    single odd entry must not cost the whole channel."""
    root = ET.fromstring(xml)
    feed_channel = _author_channel_id(root)
    feed_title = root.findtext("atom:author/atom:name", namespaces=_NS)
    is_short = _IS_SHORT.get(kind)

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
        # An entry does not have to belong to the channel whose feed this is.
        # An artist channel's auto playlists carry the linked label channel's
        # uploads and streams, so the owner is read per entry and its name is
        # carried with it, since that channel can be a stranger to us.
        owner_name = (entry.findtext("atom:author/atom:name", namespaces=_NS) or "").strip()

        # starRating and statistics sit inside media:group/media:community, so
        # search by descendant rather than by exact path.
        thumbnail = entry.find(".//media:thumbnail", _NS)
        rating = entry.find(".//media:starRating", _NS)
        statistics = entry.find(".//media:statistics", _NS)

        videos.append(VideoRow(
            platform="youtube",
            ext_id=ext_id,
            channel_key=channel_key(owner),
            channel_title=owner_name or (feed_title if owner == feed_channel else None),
            title=title,
            published_at=_epoch(entry.findtext("atom:published", namespaces=_NS)),
            thumbnail_url=thumbnail.get("url") if thumbnail is not None else None,
            views=_int_attr(statistics, "views"),
            # average is a hardcoded 5.00 and useless. count is the like count.
            likes=_int_attr(rating, "count"),
            is_short=is_short,
        ))

    return FeedResult(channel_id=feed_channel, channel_title=feed_title,
                      videos=videos, kind=kind)


def fetch(fetcher: Fetcher, channel_id: str, kind: str = VIDEOS) -> FeedResult:
    return parse(fetcher.get_bytes(feed_url(channel_id, kind)), kind)
