"""Where yt-dlp reads cookies from.

Only the parts that go past RSS need cookies. The feed itself never does,
which is deliberate, so a rotted login degrades the extras rather than the
app.

Five things can say which profile to read, and they are tried in this order.
A choice made in the window wins, because it is the most recent thing a
person said. Then a path written into config.toml, since that is also a
person saying it, only earlier. Then the mpv setup's browser profile symlink,
which is already maintained to point at whichever browser is in use. Then
whatever is found on this machine, preferring one that is signed in, because
a machine with a single signed in Firefox fork should not have to be told.
Only when none of that answers is yt-dlp handed a bare browser name and left
to search, and that search is why the earlier steps exist: it looks in the
standard Mozilla directories only, so a fork such as Zen or Floorp is never
found by it.

The answer is cached for the run. Finding it reads every jar on the machine,
and the profiles do not move while the program is open.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from . import browsers, paths
from .config import Config

MPV_PROFILE_LINK = Path("~/.config/mpv/browser-profile")
DEFAULT_FAMILY = "firefox"

# The state row the window writes when a profile is picked there. config.toml
# stays a file a person wrote, so the choice lives in the database with the
# rest of the mutable state, the same way the picture cache ceiling does.
STATE_KEY = "browser_profile"

_lock = threading.Lock()
# None means the choice has not been looked for yet. Empty means there is no
# choice, which is a different thing and must not send it looking again.
_chosen: str | None = None
_cache: dict[tuple[str, str], Source] = {}


@dataclass(frozen=True)
class Source:
    """Which cookies are being read, and who said so."""

    spec: str
    path: Path | None
    origin: str

    @property
    def text(self) -> str:
        """One line for the window and the checks."""
        return f"{self.spec} ({self.origin})" if self.origin else self.spec


def remember(path: str) -> None:
    """Note the choice without going to the database for it. The window calls
    this after writing the row, so nothing has to be re-read and no other
    copy of the answer can go stale."""
    global _chosen
    with _lock:
        _chosen = path or ""
        _cache.clear()


def forget() -> None:
    """Drop what was worked out, so the next question looks again."""
    global _chosen
    with _lock:
        _chosen = None
        _cache.clear()


def _stored() -> str:
    """The choice, read straight out of the state database.

    Read only and by hand rather than through Database, because this is
    reached from the command line tools as well and opening the real database
    the usual way would run a migration behind the app's back.
    """
    if not paths.DB_FILE.exists():
        return ""
    try:
        with contextlib.closing(sqlite3.connect(
                f"file:{paths.DB_FILE}?mode=ro", uri=True)) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?",
                               (f"state.{STATE_KEY}",)).fetchone()
    except sqlite3.Error:
        return ""
    return str(row[0]) if row and row[0] else ""


def chosen() -> str:
    global _chosen
    with _lock:
        if _chosen is None:
            _chosen = _stored()
        return _chosen


def _look(cfg: Config) -> Source:
    picked = chosen()
    if picked:
        path = Path(picked).expanduser()
        if path.exists():
            return Source(f"{DEFAULT_FAMILY}:{path}", path, "picked here")
        # A profile that was picked and is now gone. Saying so beats falling
        # through to another browser's cookies without a word, which would
        # look like the choice never took.
        return Source(f"{DEFAULT_FAMILY}:{path}", path, "picked here, now missing")

    configured = cfg.browser_profile
    if configured and configured != "auto":
        expanded = Path(configured).expanduser()
        if expanded.exists():
            # yt-dlp calls abspath but never expanduser on this argument, so
            # it has to be resolved here.
            return Source(f"{DEFAULT_FAMILY}:{expanded}", expanded, "config.toml")
        # Anything else the file carries is handed over as written. A browser
        # name rather than a path is the one useful case, and it is how a
        # Chromium family jar can still be tried by hand.
        return Source(configured, None, "config.toml")

    link = MPV_PROFILE_LINK.expanduser()
    if link.exists():
        return Source(f"{DEFAULT_FAMILY}:{link}", link, "the mpv profile link")

    profile = browsers.best()
    if profile is not None:
        return Source(f"{DEFAULT_FAMILY}:{profile.path}", profile.path,
                      f"found, {profile.label}")
    return Source(DEFAULT_FAMILY, None, "yt-dlp's own search")


def resolve(cfg: Config) -> Source:
    key = (chosen(), cfg.browser_profile)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    found = _look(cfg)
    with _lock:
        _cache[key] = found
    return found


def browser_spec(cfg: Config) -> str:
    """The value for yt-dlp's cookies-from-browser argument."""
    return resolve(cfg).spec


def profile_path(cfg: Config) -> str | None:
    """The profile directory itself, for the code that reads the jar rather
    than passing an argument to yt-dlp. None when nothing here knows where it
    is, which yt-dlp's own reader takes as leave to go looking."""
    path = resolve(cfg).path
    return str(path) if path is not None else None


def args(cfg: Config) -> list[str]:
    return ["--cookies-from-browser", browser_spec(cfg)]
