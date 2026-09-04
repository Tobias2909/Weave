"""Searching YouTube itself.

Weave's own search is one query over the stored database and costs nothing.
This is the other one, for finding something that was never in the feed. It
costs a request, so it happens when asked for rather than while typing.

FreeTube reaches this through youtubei.js and a continuation token. There is no
such library here, so it goes through yt-dlp, which addresses a search as a
playlist. That has one useful consequence: a slice of the results can be asked
for directly, and the slices do not overlap, so more can be loaded by asking
for a later one. Verified, items 13 to 24 of a search share nothing with items
1 to 12.
"""

from __future__ import annotations

import threading

from ..config import Config
from ..cookies import args as cookie_args
from ..net import Throttle
from ..process import Timeout, run as run_process
from .flatlist import APPROXIMATE_DATES, FIELDS, FlatVideo, parse


class SearchError(RuntimeError):
    pass


def fetch(cfg: Config, query: str, start: int = 1, count: int = 24,
          throttle: Throttle | None = None, timeout: float = 180.0,
          cancel: threading.Event | None = None) -> list[FlatVideo]:
    """One page of results. `start` is one based, like the slice yt-dlp takes."""
    query = (query or "").strip()
    if not query:
        return []
    first = max(1, start)
    last = max(first, first + max(1, count) - 1)
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        *cookie_args(cfg), *APPROXIMATE_DATES,
        "--playlist-items", f"{first}-{last}",
        "--print", FIELDS,
        # The number in the prefix is how deep the search goes, so it has to
        # reach at least as far as the slice being asked for.
        f"ytsearch{last}:{query}",
    ]
    try:
        if throttle is not None:
            with throttle.slot():
                result = run_process(command, cancel=cancel, timeout=timeout)
        else:
            result = run_process(command, cancel=cancel, timeout=timeout)
    except FileNotFoundError as exc:
        raise SearchError("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise SearchError("the search timed out") from exc

    found = parse(result.stdout)
    if found:
        return found
    # A search that genuinely matched nothing is an answer, not a failure, so
    # only a run that also complained is treated as one.
    tail = (result.stderr or "").strip().splitlines()
    if not tail:
        return []
    detail = tail[-1]
    if "cookies" in detail.lower() or "sign in" in detail.lower():
        raise SearchError("could not read the login cookies, check browser_profile in the config")
    raise SearchError(detail[:200])
