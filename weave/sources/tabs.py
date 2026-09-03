"""Asking a channel which of its videos are Shorts.

Duration is the wrong signal for this. Most stored videos never get a duration,
because the subscriptions sweep only reaches the newest entries, so a rule built
on duration leaves almost everything undecided.

A channel's two listing tabs answer it directly instead. The Shorts tab lists
its Shorts and the videos tab lists its long form uploads, and the two are
disjoint, verified on a channel that posts both where the newest thirty of each
had no id in common. One listing costs about six tenths of a second and settles
every stored video of that channel at once, rather than one request per video.

Nothing is inferred from absence. A video in neither listing stays undecided and
keeps showing, which is what a premiere or a stream that has not settled into a
tab yet should do.
"""

from __future__ import annotations

import threading

from ..ids import is_video_id
from ..net import Throttle
from ..process import Cancelled, Timeout, run as run_process

SHORTS = "shorts"
VIDEOS = "videos"

CHANNEL_TAB = "https://www.youtube.com/channel/{channel_id}/{tab}"

_COMMAND = ["yt-dlp", "--no-warnings", "--flat-playlist", "--print", "%(id)s"]

# A channel that has never posted a Short has no Shorts tab at all, and one
# that only posts Shorts or only streams has no videos tab. yt-dlp reports both
# as an error, but they are answers rather than failures. Reading them as
# failures left 181 of 424 channels permanently unclassified.
_MISSING_TAB = "does not have a"


class TabError(RuntimeError):
    pass


def parse_ids(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if is_video_id(line.strip())}


def fetch_ids(channel_id: str, tab: str, limit: int = 60,
              throttle: Throttle | None = None,
              cancel: threading.Event | None = None,
              timeout: float = 120.0) -> set[str]:
    """The newest ids in one of a channel's listing tabs.

    The limit only has to cover the window of videos actually stored, which is
    the newest fifteen a channel feed publishes, so sixty is generous.
    """
    command = [*_COMMAND, "--playlist-end", str(max(1, limit)),
               CHANNEL_TAB.format(channel_id=channel_id, tab=tab)]
    try:
        if throttle is not None:
            with throttle.slot():
                result = run_process(command, cancel=cancel, timeout=timeout)
        else:
            result = run_process(command, cancel=cancel, timeout=timeout)
    except Cancelled:
        raise
    except FileNotFoundError as exc:
        raise TabError("yt-dlp is not installed") from exc
    except Timeout as exc:
        raise TabError(f"the {tab} listing timed out") from exc

    ids = parse_ids(result.stdout)
    if ids or result.returncode == 0:
        # An empty listing with a clean exit is a real answer too.
        return ids
    stderr = result.stderr or ""
    if _MISSING_TAB in stderr and f"{tab} tab" in stderr:
        return set()
    tail = stderr.strip().splitlines()
    raise TabError((tail[-1] if tail else f"the {tab} listing returned nothing")[:200])
