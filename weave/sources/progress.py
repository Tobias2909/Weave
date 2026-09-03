"""Reading resume positions out of mpv's own state.

mpv already records where playback stopped, so Weave does not need to track
partial progress itself. Each resume file is named after the uppercase MD5 of
the exact URL string mpv was handed, which is why Weave hands out canonical
URLs with no extra parameters. Verified against a real state directory, where
every one of the 662 files that records its own URL hashes to its own name.

A file that played to the end leaves no resume file at all, so the presence of
one means partially watched. That pairs with the watched table rather than
competing with it.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

START_LINE = re.compile(r"^start=([0-9.]+)", re.M)


def default_dir() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(state) / "mpv" / "watch_later"


def filename_for(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest().upper()


def position_for(url: str, directory: Path | None = None) -> float | None:
    """Seconds into the given URL, or None when there is no resume file."""
    target = (directory or default_dir()) / filename_for(url)
    try:
        text = target.read_text(errors="replace")
    except OSError:
        return None
    match = START_LINE.search(text)
    if not match:
        return None
    try:
        seconds = float(match.group(1))
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def positions_for(urls: list[str], directory: Path | None = None) -> dict[str, float]:
    """Look up many at once. One stat and one small read per URL, which is
    cheaper than listing a directory holding a couple of thousand files."""
    root = directory or default_dir()
    found: dict[str, float] = {}
    for url in urls:
        seconds = position_for(url, root)
        if seconds is not None:
            found[url] = seconds
    return found
