"""Display formatting. Pure functions, so they are cheap to test and contain
every rounding decision in one place."""

from __future__ import annotations

import re
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


# What counts as an address inside a description. Two shapes, because people
# write both: one with a scheme, and one that begins at www and leaves the
# scheme to be assumed. The run stops at whitespace and at the three
# characters that cannot appear in markup without being escaped first, so a
# link can never swallow the tag built around it.
_ADDRESS = re.compile(r"""(?xi)
    \b
    (?:
        https?://[^\s<>"']+
      | www\.[^\s<>"']+
    )
""")

# What a sentence puts after an address rather than inside it. A closing
# bracket is only trimmed when nothing opened it inside the address, since
# plenty of real addresses carry a matched pair.
_TRAILING = ".,;:!?'\""
_CLOSERS = {")": "(", "]": "["}


def _tidy(address: str) -> tuple[str, str]:
    """Split an address from the punctuation a sentence left on its end."""
    after = ""
    while address:
        last = address[-1]
        unopened = (last in _CLOSERS
                    and address.count(_CLOSERS[last]) < address.count(last))
        if last not in _TRAILING and not unopened:
            break
        after = last + after
        address = address[:-1]
    return address, after


def _escaped(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def linked(text: str) -> str:
    """A description as markup, with its addresses made pressable.

    Qt draws this as StyledText, which is the only format that gives a Label
    an `<a href>` to report when it is pressed. Two consequences follow and
    both are handled here rather than left to the caller.

    Everything that is not an address is escaped, because an ampersand or an
    angle bracket in somebody's description would otherwise be read as markup
    and disappear. And every newline becomes a break, because StyledText
    collapses runs of whitespace, so a description written in paragraphs would
    arrive as one long line.

    Always returns markup, even for a description with no address in it, so
    the Label can be told once what format it is reading instead of switching
    between two and re-laying itself out on every song.
    """
    if not text:
        return ""
    out: list[str] = []
    at = 0
    for found in _ADDRESS.finditer(text):
        address, after = _tidy(found.group(0))
        if not address:
            continue
        out.append(_escaped(text[at:found.start()]))
        # An address written from www alone is still an address. The scheme is
        # assumed for the browser and left out of what is drawn, which is what
        # was written.
        target = address if address.lower().startswith("http") else "https://" + address
        out.append(f'<a href="{_escaped(target)}">{_escaped(address)}</a>')
        out.append(_escaped(after))
        at = found.end()
    out.append(_escaped(text[at:]))
    return "".join(out).replace("\n", "<br>")
