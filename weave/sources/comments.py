"""Comments, fetched on demand.

They are not part of a refresh. One video's comments cost several seconds, so
they are only fetched when a video is actually being looked at.

The knob that controls how many arrive is easy to get wrong twice over. It is a
list rather than a single number, and the field that decides how many threads
come back is the second one. Setting only the first counts replies towards the
total, so asking for five yields one thread and four replies to it. And
extraction has to be asked for explicitly, since writing the metadata file on
its own produces no comments at all.

Measured: five threads take about seven seconds, fifteen about twelve.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..cookies import args as cookie_args
from ..net import Throttle
from ..process import Cancelled, Timeout, run as run_process

# total, threads, replies, replies per thread
REPLIES_PER_THREAD = 2


class CommentsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Comment:
    author: str
    avatar_url: str
    text: str
    likes: int
    when: str
    pinned: bool = False
    by_uploader: bool = False
    verified: bool = False
    replies: list["Comment"] = field(default_factory=list)


def _one(raw: dict) -> Comment:
    return Comment(
        author=str(raw.get("author") or ""),
        avatar_url=str(raw.get("author_thumbnail") or ""),
        text=str(raw.get("text") or ""),
        likes=int(raw.get("like_count") or 0),
        when=str(raw.get("_time_text") or ""),
        pinned=bool(raw.get("is_pinned")),
        by_uploader=bool(raw.get("author_is_uploader")),
        verified=bool(raw.get("author_is_verified")),
    )


@dataclass(frozen=True)
class Details:
    """What the metadata file says about the video itself.

    It is written by the same call that fetches the comments, so this costs
    nothing on top. It is the only place the like count and the publish date
    are available for a video that is not in the feed, since the cheap listing
    modes carry neither, measured.
    """

    views: int | None = None
    likes: int | None = None
    published_at: int | None = None
    duration_s: int | None = None


def _whole(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_details(info: dict) -> Details:
    published = _whole(info.get("timestamp")) or _whole(info.get("release_timestamp"))
    if published is None and info.get("upload_date"):
        # A date with no time is better than nothing, and it is what the
        # metadata carries when the exact moment is missing.
        try:
            from datetime import datetime, timezone
            published = int(datetime.strptime(str(info["upload_date"]), "%Y%m%d")
                            .replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            published = None
    return Details(
        views=_whole(info.get("view_count")),
        likes=_whole(info.get("like_count")),
        published_at=published,
        duration_s=_whole(info.get("duration")),
    )


def parse(info: dict) -> list[Comment]:
    """Group the flat list into threads, keeping the order it arrived in, which
    is the order the sort asked for."""
    raw = info.get("comments") or []
    threads: list[Comment] = []
    by_id: dict[str, list[Comment]] = {}

    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("parent") == "root":
            comment = _one(item)
            by_id[str(item.get("id") or "")] = comment.replies
            threads.append(comment)

    for item in raw:
        if not isinstance(item, dict) or item.get("parent") == "root":
            continue
        parent = by_id.get(str(item.get("parent") or ""))
        if parent is not None:
            parent.append(_one(item))
    return threads


def fetch(cfg: Config, url: str, threads: int = 5,
          throttle: Throttle | None = None,
          cancel: threading.Event | None = None,
          timeout: float = 180.0) -> tuple[list[Comment], Details]:
    total = threads * (REPLIES_PER_THREAD + 1) + threads
    spec = f"{total},{threads},{threads * REPLIES_PER_THREAD},{REPLIES_PER_THREAD}"
    workspace = Path(tempfile.mkdtemp(prefix="weave-comments-"))
    command = [
        "yt-dlp", "--no-warnings", "--skip-download",
        # Both are needed. The metadata file alone contains no comments.
        "--write-comments", "--write-info-json",
        *cookie_args(cfg),
        "--extractor-args", f"youtube:comment_sort=top;max_comments={spec}",
        "-o", str(workspace / "%(id)s"), url,
    ]
    try:
        if throttle is not None:
            with throttle.slot():
                result = run_process(command, cancel=cancel, timeout=timeout)
        else:
            result = run_process(command, cancel=cancel, timeout=timeout)

        found = list(workspace.glob("*.info.json"))
        if not found:
            tail = (result.stderr or "").strip().splitlines()
            raise CommentsError((tail[-1] if tail else "no comments came back")[:200])
        info = json.loads(found[0].read_text())
        return parse(info), parse_details(info)
    except Cancelled:
        raise
    except FileNotFoundError as exc:
        raise CommentsError("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise CommentsError("fetching the comments timed out") from exc
    except ValueError as exc:
        raise CommentsError("the comment file could not be read") from exc
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
