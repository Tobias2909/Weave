"""Display formatting. Pure functions, so they are cheap to test and contain
every rounding decision in one place."""

from __future__ import annotations

import time
from datetime import date

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")

_AGE_STEPS = (
    (60, 1, "second"),
    (3600, 60, "minute"),
    (86400, 3600, "hour"),
    (604800, 86400, "day"),
    (2629800, 604800, "week"),
    (31557600, 2629800, "month"),
)


def age_text(published_at: int | None, now: int | None = None) -> str:
    """Relative age, in the shape YouTube uses. Empty when unknown."""
    if not published_at:
        return ""
    now = int(time.time()) if now is None else now
    delta = now - int(published_at)
    if delta < 0:
        return "just now"          # clock skew, or a premiere dated ahead
    if delta < 60:
        return "just now"
    for limit, divisor, unit in _AGE_STEPS:
        if delta < limit:
            value = delta // divisor
            return f"{value} {unit}{'s' if value != 1 else ''} ago"
    years = delta // 31557600
    return f"{years} year{'s' if years != 1 else ''} ago"


def upcoming_text(scheduled_at: int | None, now: int | None = None) -> str:
    """When an announced stream is due, for the card badge. A missing time
    still lets the card say "Upcoming" on its own rather than nothing."""
    if not scheduled_at:
        return "Upcoming"
    now = int(time.time()) if now is None else now
    delta = int(scheduled_at) - now
    if delta <= 0:
        return "Starting soon"
    if delta < 60:
        return "Starts in seconds"
    for limit, divisor, unit in _AGE_STEPS:
        if delta < limit:
            value = delta // divisor
            return f"Starts in {value} {unit}{'s' if value != 1 else ''}"
    return "Starts later"


def start_time_text(scheduled_at: int | None, now: int | None = None) -> str:
    """When an announced stream begins, on the clock this machine is set to.

    The badge already says how long there is to wait, which answers a different
    question from the one somebody deciding whether to be there asks. So this
    is the wall clock rather than another relative phrase, and it is local
    because a time in anybody else's zone is a puzzle rather than an answer.
    """
    if not scheduled_at:
        return ""
    when = time.localtime(int(scheduled_at))
    today = time.localtime(int(time.time()) if now is None else int(now))
    clock = f"{when.tm_hour:02d}:{when.tm_min:02d}"
    # Calendar days apart, not chunks of 24 hours. A stream at nine tomorrow
    # morning is tomorrow whether it is now noon or midnight.
    days = (date(when.tm_year, when.tm_mon, when.tm_mday)
            - date(today.tm_year, today.tm_mon, today.tm_mday)).days
    if days == 0:
        return f"today at {clock}"
    if days == 1:
        return f"tomorrow at {clock}"
    if 1 < days < 7:
        return f"{_WEEKDAYS[when.tm_wday]} at {clock}"
    month = _MONTHS[when.tm_mon - 1]
    if when.tm_year != today.tm_year:
        return f"{when.tm_mday} {month} {when.tm_year} at {clock}"
    return f"{when.tm_mday} {month} at {clock}"


def count_text(value: int | None) -> str:
    """Compact counts. None becomes an empty string rather than a zero, so the
    UI can tell "no data yet" from "genuinely nothing"."""
    if value is None:
        return ""
    if value < 1000:
        return str(value)
    if value < 1_000_000:
        return f"{value / 1000:.1f}K".replace(".0K", "K")
    if value < 1_000_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    return f"{value / 1_000_000_000:.1f}B".replace(".0B", "B")


def every_text(seconds: int | None) -> str:
    """A polling interval as a person would say it. Clock form is for a video,
    not for how often something is asked, where 0:15:00 reads as a length."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return ""
    if seconds % 86400 == 0:
        days = seconds // 86400
        return "every day" if days == 1 else f"every {days} days"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "every hour" if hours == 1 else f"every {hours} h"
    if seconds % 60 == 0:
        return f"every {seconds // 60} min"
    return f"every {seconds} s"


def duration_text(seconds: int | None) -> str:
    """Clock form. Empty when the duration is not known yet, which is the
    normal state for a video that RSS found but no sweep has reached."""
    if not seconds or seconds < 0:
        return ""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
