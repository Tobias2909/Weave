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

YouTube's own filters travel in the address of its results page, as a small
protobuf written in base64 in the `sp` parameter, and yt-dlp reads that page
as a playlist too. Measured 2026-10-01 against the live page:

  sorting by view count works, sorting by upload date no longer does (the
  answer is the same as by relevance), so newest first is done here over what
  has been loaded;

  the upload windows work, from the last hour to this year, and so do the
  three lengths, whose short end is under four minutes (the longest of sixty
  songs under it ran 3:59);

  sorting and filtering combine, and so do two filters;

  but the first page also carries a few rows from YouTube's own shelves that
  ignore every filter, the same top rows an unfiltered search starts with.
  `Filters.keeps` takes those out by their length and their age.
"""

from __future__ import annotations

import base64
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote, quote_plus

from ..config import Config
from ..cookies import args as cookie_args
from ..net import Throttle
from . import ytdlp
from .flatlist import APPROXIMATE_DATES, FIELDS, FlatVideo, parse


class SearchError(RuntimeError):
    pass


# The numbers YouTube's filter message uses for each choice. A sort of 0 is
# relevance, the default, and is never written; 2 was upload date and is
# ignored now, which is why newest first is not in here.
_SORTS = {"relevance": 0, "views": 3}
_WHEN = {"any": 0, "hour": 1, "today": 2, "week": 3, "month": 4, "year": 5}
_LENGTH = {"any": 0, "short": 1, "long": 2, "medium": 3}

# How old a row may be and still belong to each window, in seconds. The age is
# the phrase YouTube shows ("2 days ago") turned into a time, so these are the
# first phrase that falls outside: "1 week ago" is not this week.
_WINDOW_S = {"hour": 3600, "today": 86400, "week": 7 * 86400, "month": 30 * 86400,
             "year": 365 * 86400}
# The lengths, with a few seconds either way, since all this has to catch is a
# row from a shelf that was never filtered at all.
_LENGTH_S = {"short": (0, 245), "medium": (235, 1205), "long": (1195, None)}

SORTS = ("relevance", "views", "newest")
WHENS = tuple(_WHEN)
LENGTHS = ("any", "short", "medium", "long")


@dataclass(frozen=True)
class Filters:
    """What a search is narrowed to, the way YouTube's own filters do it."""

    sort: str = "relevance"
    when: str = "any"
    length: str = "any"

    def is_default(self) -> bool:
        return self == Filters()

    def tag(self) -> str:
        """A short name for the choices, empty for none, to keep each
        filtered set of results apart from the plain one."""
        return "" if self.is_default() else f"{self.sort},{self.when},{self.length}"

    def sp(self) -> str:
        """The `sp` value of the results address, empty when YouTube is
        asked for nothing beyond the words."""
        message = b""
        sort = _SORTS.get(self.sort, 0)
        if sort:
            message += bytes([0x08, sort])
        narrow = b""
        if _WHEN.get(self.when, 0):
            narrow += bytes([0x08, _WHEN[self.when]])
        if _LENGTH.get(self.length, 0):
            narrow += bytes([0x18, _LENGTH[self.length]])
        if narrow:
            message += bytes([0x12, len(narrow)]) + narrow
        return base64.b64encode(message).decode() if message else ""

    def keeps(self, row: dict, now: float | None = None) -> bool:
        """Whether a row belongs to these filters, as far as can be told. A
        row that does not say how old or how long it is is kept."""
        published = row.get("published_at")
        if self.when in _WINDOW_S and published:
            age = (now if now is not None else time.time()) - published
            if age >= _WINDOW_S[self.when]:
                return False
        length = row.get("duration_s")
        if self.length in _LENGTH_S and length:
            low, high = _LENGTH_S[self.length]
            if length < low or (high is not None and length > high):
                return False
        return True


def address(query: str, filters: Filters) -> str:
    """YouTube's results page for these words, narrowed by these filters."""
    return (f"https://www.youtube.com/results?search_query={quote_plus(query)}"
            f"&sp={quote(filters.sp(), safe='')}")


def fetch(cfg: Config, query: str, start: int = 1, count: int = 24,
          throttle: Throttle | None = None, timeout: float = 180.0,
          cancel: threading.Event | None = None,
          filters: Filters | None = None) -> list[FlatVideo]:
    """One page of results. `start` is one based, like the slice yt-dlp takes.

    With filters that YouTube can apply, the page asked for is its results
    page narrowed by them. Newest first alone asks for nothing different,
    since it is sorted here. Rows are returned as YouTube sent them, strays
    included, so the caller can count the page it asked for.
    """
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
        address(query, filters) if filters is not None and filters.sp()
        else f"ytsearch{last}:{query}",
    ]
    result = ytdlp.run(command, SearchError, "the search", throttle, cancel, timeout)
    found = parse(result.stdout)
    # A search that genuinely matched nothing is an answer, not a failure, so
    # only a run that also complained is treated as one.
    if found or not ytdlp.complained(result):
        return found
    raise ytdlp.blame(result, SearchError, "the search")
