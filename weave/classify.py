"""Deciding which stored videos are Shorts, one channel at a time.

Shared by the background poller and the classify subcommand so there is one
implementation. See weave/sources/tabs.py for why the channel listings are the
signal rather than duration.
"""

from __future__ import annotations

import threading

from .db import Database
from .net import Throttle
from .sources import tabs


def classify_channel(db: Database, channel_key: str, ext_id: str,
                     throttle: Throttle | None = None,
                     cancel: threading.Event | None = None,
                     limit: int = 60) -> tuple[int, int]:
    """Settle a channel's undecided videos. Returns how many were marked as
    Shorts and how many as long form.

    Both listings are fetched even when the first already decided everything,
    because a video missing from the Shorts tab is not evidence of anything on
    its own. Only presence in a listing is treated as an answer.

    Each listing is handled on its own, so a network failure on one still lets
    the other one's answer be recorded. The channel is only stamped as asked
    when both were actually answered, so a partial result is retried rather
    than being treated as complete.
    """
    answered = 0
    marked_short = marked_long = 0
    first_error: tabs.TabError | None = None

    for tab, is_short in ((tabs.SHORTS, True), (tabs.VIDEOS, False)):
        try:
            found = tabs.fetch_ids(ext_id, tab, limit, throttle, cancel)
        except tabs.TabError as exc:
            first_error = first_error or exc
            continue
        answered += 1
        marked = db.set_kind(channel_key, found, is_short=is_short)
        if is_short:
            marked_short = marked
        else:
            marked_long = marked

    if answered == 2:
        db.mark_classified(channel_key)
    elif first_error is not None:
        raise first_error
    return marked_short, marked_long
