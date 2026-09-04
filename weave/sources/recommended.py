"""What YouTube suggests, kept in one place away from the feed.

This is deliberately not part of the feed. The feed is the channels you chose,
and the point of the whole application is that those two things stay apart.
Recommendations live in their own view, their own table, and are replaced
wholesale rather than accumulated, because yesterday's suggestion is not worth
keeping.

Two things about the list, both measured. It mixes in radio playlist rows whose
id is thirteen characters and whose every other field is NA, so rows are
filtered to real video ids. And the videos are often from channels that are not
tracked here, which is the point of a recommendation, so nothing here is
written into the videos table where it would look like something you follow.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..config import Config
from ..cookies import args as cookie_args
from ..ids import CHANNEL_ID, is_video_id
from ..net import Throttle
from ..process import Timeout, run as run_process

RECOMMENDED = ":ytrec"

# Tab separated, because a title can contain very nearly anything else.
FIELDS = "%(id)s\t%(title)s\t%(channel)s\t%(channel_id)s\t%(duration)s\t%(thumbnails.-1.url)s"


class RecommendedError(RuntimeError):
    pass


@dataclass(frozen=True)
class Recommendation:
    ext_id: str
    title: str
    channel_name: str | None
    channel_ext_id: str | None
    duration_s: int | None
    thumbnail_url: str | None


def _optional(text: str) -> str | None:
    text = (text or "").strip()
    return None if not text or text == "NA" else text


def _seconds(text: str) -> int | None:
    value = _optional(text)
    try:
        return int(float(value)) if value else None
    except ValueError:
        return None


def parse_lines(text: str) -> list[Recommendation]:
    out: list[Recommendation] = []
    seen: set[str] = set()
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        ext_id = parts[0].strip()
        # A radio row is thirteen characters and carries nothing else.
        if not is_video_id(ext_id) or ext_id in seen:
            continue
        title = (parts[1] or "").strip()
        if not title or title == "NA":
            continue
        seen.add(ext_id)
        channel_id = _optional(parts[3]) if len(parts) > 3 else None
        out.append(Recommendation(
            ext_id=ext_id,
            title=title,
            channel_name=_optional(parts[2]) if len(parts) > 2 else None,
            channel_ext_id=channel_id if channel_id and CHANNEL_ID.match(channel_id) else None,
            duration_s=_seconds(parts[4]) if len(parts) > 4 else None,
            thumbnail_url=_optional(parts[5]) if len(parts) > 5 else None,
        ))
    return out


def fetch(cfg: Config, limit: int = 48, throttle: Throttle | None = None,
          timeout: float = 180.0,
          cancel: threading.Event | None = None) -> list[Recommendation]:
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg),
        "--playlist-end", str(max(1, limit)),
        "--print", FIELDS,
        RECOMMENDED,
    ]
    try:
        if throttle is not None:
            with throttle.slot():
                result = run_process(command, cancel=cancel, timeout=timeout)
        else:
            result = run_process(command, cancel=cancel, timeout=timeout)
    except FileNotFoundError as exc:
        raise RecommendedError("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise RecommendedError("the recommendations timed out") from exc

    found = parse_lines(result.stdout)
    if found:
        return found
    tail = (result.stderr or "").strip().splitlines()
    detail = tail[-1] if tail else "nothing came back"
    if "cookies" in detail.lower() or "sign in" in detail.lower():
        raise RecommendedError("could not read the login cookies, check browser_profile in the config")
    raise RecommendedError(detail[:200])
