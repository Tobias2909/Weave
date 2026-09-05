"""Channel details for the channel page.

Fetched lazily, when a channel page is first opened, rather than for all of
them during an import. On a subscription list of several hundred channels that
would be several hundred calls for pages that may never be looked at, and one
call costs about six tenths of a second.

Picking the right image out of the response matters, and getting it wrong does
not look like an error. A channel returns its banner at six crop widths plus its
avatar. Measured on a live channel, the six crops are the banner as it is
actually displayed, up to 2560 by 424 at an aspect ratio of about six to one,
while `banner_uncropped` is the raw 2560 by 1440 artwork the channel owner
uploaded, of which only a middle strip is ever shown.

So the crops are what a page wants. Taking the uncropped one instead fills a
wide band with a magnified slice of the middle of a mostly empty image, which
reads as the banner having failed to load rather than as the wrong picture.
The uncropped entry is kept only as the fallback for a channel that offers no
crops, and it carries no width or height, which is why it cannot simply be
sorted with the rest.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass

from ..net import Throttle
from . import ytdlp

_COMMAND = [
    "yt-dlp", "--no-warnings", "--flat-playlist", "--playlist-items", "0",
    "--print", "playlist:%(channel)s|%(channel_follower_count)s",
    "--print", "playlist:%(thumbnails)#j",
]

AVATAR_ID = "avatar_uncropped"
BANNER_ID = "banner_uncropped"
BANNER_RATIO = 3


class DetailsError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChannelDetails:
    title: str | None
    avatar_url: str | None
    banner_url: str | None
    follower_count: int | None


def _optional_int(text: str) -> int | None:
    text = (text or "").strip()
    if not text or text == "NA":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def pick_images(thumbnails: list[dict]) -> tuple[str | None, str | None]:
    """Return the avatar and the banner.

    The avatar is square, so the uncropped one is as good as any and is
    preferred. The banner is not: the widest crop is what gets shown, and the
    uncropped artwork is only the fallback when there are no crops.
    """
    avatar = uncropped_banner = None
    squares: list[tuple[int, str]] = []
    wides: list[tuple[int, str]] = []

    for entry in thumbnails:
        url = (entry or {}).get("url")
        if not url:
            continue
        name = entry.get("id")
        if name == AVATAR_ID and not avatar:
            avatar = url
            continue
        if name == BANNER_ID and not uncropped_banner:
            uncropped_banner = url
            continue
        width, height = entry.get("width"), entry.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or not height:
            continue
        if width == height:
            squares.append((width, url))
        elif width >= BANNER_RATIO * height:
            # Wide enough to be a banner rather than a landscape picture of
            # some other kind. The real crops measure about six to one, so
            # three is a generous floor.
            wides.append((width, url))

    if not avatar and squares:
        avatar = max(squares)[1]
    banner = max(wides)[1] if wides else uncropped_banner
    return avatar, banner


def parse_output(text: str) -> ChannelDetails:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise DetailsError("nothing came back")

    title, _, followers = lines[0].partition("|")
    title = title.strip()

    thumbnails: list[dict] = []
    remainder = "\n".join(lines[1:]).strip()
    if remainder:
        try:
            loaded = json.loads(remainder)
            if isinstance(loaded, list):
                thumbnails = [entry for entry in loaded if isinstance(entry, dict)]
        except ValueError:
            thumbnails = []

    avatar, banner = pick_images(thumbnails)
    return ChannelDetails(
        title=title if title and title != "NA" else None,
        avatar_url=avatar,
        banner_url=banner,
        follower_count=_optional_int(followers),
    )


def fetch(channel_id: str, throttle: Throttle | None = None,
          cancel: threading.Event | None = None,
          timeout: float = 120.0) -> ChannelDetails:
    url = f"https://www.youtube.com/channel/{channel_id}"
    result = ytdlp.run([*_COMMAND, url], DetailsError, "the channel lookup", throttle, cancel,
                       timeout)
    if result.returncode != 0 and not result.stdout.strip():
        raise ytdlp.blame(result, DetailsError, "the channel lookup")
    return parse_output(result.stdout)
