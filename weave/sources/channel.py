"""Channel details for the channel page.

Fetched lazily, when a channel page is first opened, rather than for all of
them during an import. On a subscription list of several hundred channels that
would be several hundred calls for pages that may never be looked at, and one
call costs about six tenths of a second.

Picking the right image out of the response matters. A channel returns its
banner at six crop widths plus its avatar, and the banner entries are the ones
carrying a crop parameter. The reliable discriminator is the aspect ratio, since
an avatar is square and a banner is not.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass

from ..net import Throttle
from ..process import Cancelled, Timeout, run as run_process

_COMMAND = [
    "yt-dlp", "--no-warnings", "--flat-playlist", "--playlist-items", "0",
    "--print", "playlist:%(channel)s|%(channel_follower_count)s",
    "--print", "playlist:%(thumbnails)#j",
]

AVATAR_ID = "avatar_uncropped"
BANNER_ID = "banner_uncropped"


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

    The uncropped entries are preferred when present because they carry no crop
    parameters. Otherwise the largest square image is the avatar and the widest
    non square one is the banner.
    """
    avatar = banner = None
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
        if name == BANNER_ID and not banner:
            banner = url
            continue
        width, height = entry.get("width"), entry.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or not height:
            continue
        if width == height:
            squares.append((width, url))
        elif width > height:
            wides.append((width, url))

    if not avatar and squares:
        avatar = max(squares)[1]
    if not banner and wides:
        banner = max(wides)[1]
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
    try:
        if throttle is not None:
            with throttle.slot():
                result = run_process([*_COMMAND, url], cancel=cancel, timeout=timeout)
        else:
            result = run_process([*_COMMAND, url], cancel=cancel, timeout=timeout)
    except Cancelled:
        raise
    except FileNotFoundError as exc:
        raise DetailsError("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise DetailsError("the channel lookup timed out") from exc

    if result.returncode != 0 and not result.stdout.strip():
        tail = (result.stderr or "").strip().splitlines()
        raise DetailsError((tail[-1] if tail else "the channel lookup failed")[:200])
    return parse_output(result.stdout)
