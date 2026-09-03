"""Display formatting. Pure functions, so they are cheap to test and contain
every rounding decision in one place."""

from __future__ import annotations

import time

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
