"""Who made a video, for the videos nothing else here knows.

A history row carries an id, a title, a duration and a picture and says nothing
whatsoever about the channel, measured against a real account. Most of that is
answered by joining to what is already stored, since a video from a channel
that is followed is here already. The rest are videos from channels nobody
here follows, and this is the cheapest thing that answers for one.

YouTube's oembed endpoint takes a watch address and gives back the title, the
channel's name and the channel's page. 868 bytes and a thirtieth of a second,
measured, with no cookies and no yt-dlp, against a request for the video
itself which costs a player call. It gives no channel id: the page it names is
a handle, which is enough to show a name and to find the channel by if
somebody asks for it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..net import Fetcher

OEMBED_URL = ("https://www.youtube.com/oembed"
              "?url=https://www.youtube.com/watch%3Fv%3D{video_id}&format=json")

# What the channel's page looks like in the answer. A handle these days, and
# an old style /channel/UC... address for some, which is worth keeping apart
# because that one is an id.
HANDLE = re.compile(r"youtube\.com/@([A-Za-z0-9._-]{1,64})")
CHANNEL_ID = re.compile(r"youtube\.com/channel/(UC[A-Za-z0-9_-]{22})")


@dataclass(frozen=True)
class Owner:
    channel_name: str
    handle: str = ""
    channel_ext_id: str = ""


def parse(payload: bytes) -> Owner | None:
    try:
        answer = json.loads(payload)
    except ValueError:
        return None
    name = (answer.get("author_name") or "").strip()
    if not name:
        return None
    address = answer.get("author_url") or ""
    found = CHANNEL_ID.search(address)
    if found:
        return Owner(name, "", found.group(1))
    handle = HANDLE.search(address)
    return Owner(name, handle.group(1) if handle else "")


def fetch(fetcher: Fetcher, video_id: str) -> Owner | None:
    """The owner of one video, or nothing when the answer says nothing.

    A private or removed video answers with an error rather than a name, which
    is not a failure worth raising: it is one card that keeps the blank it
    already had.
    """
    return parse(fetcher.get_bytes(OEMBED_URL.format(video_id=video_id)))
