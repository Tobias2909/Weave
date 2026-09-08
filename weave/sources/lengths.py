"""The lengths RSS cannot carry, read off a channel's own tab listings.

Why this exists at all. The feed is built from each channel's RSS, and RSS
carries no duration whatsoever. The only thing that fills one in is the
subscriptions sweep, and that reaches roughly the newest thousand videos across
every subscription, which is a few weeks. Every other door into the videos
table hands over older rows: a channel feed publishes fifteen entries the first
time it is read, and opening a channel page reads the same window. Those were
already past the sweep's reach when they arrived, and nothing asked a second
time, so they kept the empty length they came with for ever. Measured on a real
library of 9468 videos: 90 percent of anything older than a month had no
length, against 90 percent of the last month having one.

Nothing was lost. Both writers COALESCE, so a length once stored is never
overwritten. There was simply no second pass, and this is it.

What it reads. A tab listing through yt-dlp, which is the same call the
subscriptions sweep makes and carries the same fields, so one request answers a
whole channel however many rows it is owed. Measured: a 254 entry long form tab
in 1.6 s. Two tabs at most per channel, the long form one and, for a channel
known to stream, the streams one.

The streams tab matters as much as the length. A stream that arrived through
RSS carries no live state, so it sits in the videos half of a group being a
stream. The listing says `was_live` outright, measured, so the state is read
rather than guessed, and an entry that has not happened yet answers NA to both
and is left exactly as it was.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..net import Throttle
from . import ytdlp
from .rss import LIVE, VIDEOS, playlist_id

# A channel with more stored rows than this is answered as far as this reaches
# and looked at again later. It is well past any real channel's tab: the
# deepest in a 455 subscription library was 254 entries.
MAX_ITEMS = 600

FIELDS = "%(id)s\t%(duration)s\t%(live_status)s"


class LengthsError(RuntimeError):
    pass


class NoSuchTab(LengthsError):
    """The channel has no tab of this kind. An answer, not a failure.

    It matters that these are told apart. A channel with nothing in its
    streams tab is settled for good and must be stamped as read, while a
    refusal has to leave the channel alone so it comes round again. Treating
    the first as the second asked the same channel every poll for ever.
    """


@dataclass(frozen=True)
class Length:
    ext_id: str
    duration_s: int | None
    live_status: str | None


def _optional(text: str) -> str | None:
    text = (text or "").strip()
    return None if not text or text == "NA" else text


def _number(text: str) -> int | None:
    value = _optional(text)
    try:
        return int(float(value)) if value else None
    except ValueError:
        return None


def parse(text: str) -> list[Length]:
    """Read the printed lines. Separated out so it can be tested without a
    network call, and tab separated because a title is not printed here but
    the other fields are still safer apart."""
    found: list[Length] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        ext_id = (parts[0] if parts else "").strip()
        if len(ext_id) != 11:
            # A radio row is thirteen characters and answers NA to everything.
            continue
        duration = _number(parts[1]) if len(parts) > 1 else None
        live = _optional(parts[2]) if len(parts) > 2 else None
        if duration is None and live is None:
            # An announcement that has not happened yet. Nothing to say about
            # it, and saying it is over would be worse than saying nothing.
            continue
        found.append(Length(ext_id, duration, live))
    return found


def fetch(channel_id: str, kind: str = VIDEOS, limit: int = MAX_ITEMS,
          throttle: Throttle | None = None, timeout: float = 180.0,
          cancel: threading.Event | None = None) -> list[Length]:
    """One tab of one channel, as a list of lengths.

    No cookies, and so no Config either. A tab listing is public, and asking
    anonymously keeps this away from the account entirely.
    """
    if kind not in (VIDEOS, LIVE):
        raise LengthsError(f"there is no {kind} tab to read lengths from")
    command = [
        "yt-dlp", "--no-warnings", "--flat-playlist",
        "--playlist-items", f"1-{max(1, min(limit, MAX_ITEMS))}",
        "--print", FIELDS,
        f"https://www.youtube.com/playlist?list={playlist_id(channel_id, kind)}",
    ]
    result = ytdlp.run(command, LengthsError, f"the {kind} tab", throttle, cancel, timeout)
    found = parse(result.stdout)
    if found or result.returncode == 0:
        # An empty answer with a clean exit is a channel with nothing in that
        # tab, which is ordinary and not worth reporting.
        return found
    if is_missing_tab(result.stderr):
        raise NoSuchTab(f"no {kind} tab")
    raise ytdlp.blame(result, LengthsError, f"the {kind} tab")


# What YouTube says when the uploads playlist behind a tab is not there at all.
# Measured: a channel with no streams tab answers "YouTube said: The playlist
# does not exist." through this address, and the tab address itself says "This
# channel does not have a streams tab". Both mean settled.
_MISSING = ("the playlist does not exist", "does not have a")


def is_missing_tab(stderr: str) -> bool:
    """Whether this refusal means there is no such tab, rather than a refusal
    worth trying again. Separated out so it can be tested off a real message."""
    said = (stderr or "").lower()
    return any(phrase in said for phrase in _MISSING)
