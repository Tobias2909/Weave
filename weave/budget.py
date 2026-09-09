"""A persistent ceiling on how much each endpoint is asked.

The problem this solves is specific. The channel feed endpoint answers a burst
by refusing, with a 404 or a 500 rather than a busy signal, and it never sends
Retry-After. So there is nothing to react to. The only defence is to know how
much has been asked recently and stop before the endpoint does it for us.

Freshness stamps alone cannot do this. With more channels than one round
covers, the ones a round did not reach are still legitimately due a second
later, so relaunching the app six times sends six full rounds and every single
request passes its own freshness check. Counting requests per endpoint is what
closes that.

Counts live in the database, so they survive a restart, which is the case that
matters most. They are kept as one row per endpoint per minute rather than one
row per request, which is sixty rows an hour per endpoint and makes a rolling
window a single SUM.
"""

from __future__ import annotations

from dataclasses import dataclass

from .db import Database

# Endpoints are named rather than derived from a URL, because what shares a
# limit is a matter of how the far side counts, not of how the address looks.
# yt-dlp calls are counted as one each even though a paginated call is several
# requests underneath, so a limit here is in calls, not in packets.
FEEDS = "feeds"        # youtube.com/feeds/videos.xml
BROWSE = "browse"      # youtubei browse, through yt-dlp: sweep, channel details
PLAYER = "player"      # youtubei player, through yt-dlp: live checks, comments
# YouTube Music is not counted yet. Every call to it is one deliberate click
# and there is no path that can burst, so there is nothing to protect against
# until the music area starts refreshing on its own.
SHORTS = "shorts"      # youtube.com/shorts/<id>, whether a video is one
OEMBED = "oembed"      # youtube.com/oembed, a name for a video nothing else knows
DISLIKES = "dislikes"  # returnyoutubedislikeapi.com
TWITCH = "twitch"      # api.twitch.tv


# What a ceiling leaves to the work nobody is waiting for. The rest is kept
# for the calls a person is sitting in front of. Refreshing feeds is minutes
# early or minutes late and nobody can tell; a channel page that says it has
# asked as much as it should for now is the whole answer to a press. Without
# this the poller runs at the ceiling all day and whatever is pressed loses.
BACKGROUND_SHARE = 0.8


@dataclass(frozen=True)
class Allowance:
    """How much of a request may proceed right now."""

    granted: int
    wanted: int
    frees_at: int      # unix time when the window has room again

    @property
    def full(self) -> bool:
        return self.granted < self.wanted

    @property
    def empty(self) -> bool:
        return self.granted <= 0


class Budget:
    """Reads and writes the counters. One per worker, sharing the database."""

    def __init__(self, db: Database, limits: dict[str, int], window_s: int = 900) -> None:
        self._db = db
        self._limits = limits
        self._window_s = max(60, window_s)

    @property
    def window_s(self) -> int:
        return self._window_s

    def limit(self, endpoint: str) -> int:
        return int(self._limits.get(endpoint, 0))

    def allowance(self, endpoint: str, wanted: int = 1,
                  background: bool = False) -> Allowance:
        """How many of `wanted` requests fit under the ceiling.

        A round is trimmed rather than skipped. Asking about eight channels
        when there was room for eight is better than asking about none, and
        the ones left out stay at the front of the queue for the next tick.

        Work nobody is waiting for stops short of the ceiling, at
        BACKGROUND_SHARE of it, so there is always room left for a press.
        What is spent is counted the same either way, since the far side
        counts every request whoever asked for it.
        """
        limit = self.limit(endpoint)
        if limit <= 0:                      # unlimited, no counting either
            return Allowance(wanted, wanted, 0)
        if background:
            limit = max(1, int(limit * BACKGROUND_SHARE))
        used, _ = self._db.requests_in_window(endpoint, self._window_s)
        room = max(0, limit - used)
        granted = min(wanted, room)
        frees_at = 0 if granted >= wanted else self._db.budget_frees_at(endpoint, self._window_s)
        return Allowance(granted, wanted, frees_at)

    def spend(self, endpoint: str, count: int = 1, refused: int = 0) -> None:
        if self.limit(endpoint) <= 0 and refused == 0:
            return
        if count or refused:
            self._db.record_requests(endpoint, count=count, refused=refused)

    def report(self) -> list[tuple[str, int, int, int]]:
        """Endpoint, sent, refused, limit, over the current window."""
        rows = self._db.request_totals(self._window_s)
        return [(row["endpoint"], int(row["count"] or 0), int(row["refused"] or 0),
                 self.limit(row["endpoint"])) for row in rows]
