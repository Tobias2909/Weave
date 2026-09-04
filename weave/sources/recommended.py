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

from ..config import Config
from ..cookies import args as cookie_args
from ..net import Throttle
from ..process import Timeout, run as run_process
from .flatlist import FIELDS, FlatVideo, parse

RECOMMENDED = ":ytrec"

# The same thing a playlist entry and a search result are, so it is read by the
# same parser. Kept under this name because that is what the rest calls it.
Recommendation = FlatVideo
parse_lines = parse


class RecommendedError(RuntimeError):
    pass


def fetch(cfg: Config, limit: int = 48, throttle: Throttle | None = None,
          timeout: float = 180.0, cancel: threading.Event | None = None,
          start: int = 1) -> list[Recommendation]:
    first = max(1, start)
    last = max(first, first + max(1, limit) - 1)
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg),
        # The feed pages, verified: items 25 to 36 share nothing with items 1
        # to 12. So asking for a later slice is how more of it is reached.
        "--playlist-items", f"{first}-{last}",
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

    found = parse(result.stdout)
    if found:
        return found
    tail = (result.stderr or "").strip().splitlines()
    detail = tail[-1] if tail else "nothing came back"
    if "cookies" in detail.lower() or "sign in" in detail.lower():
        raise RecommendedError("could not read the login cookies, check browser_profile in the config")
    raise RecommendedError(detail[:200])
