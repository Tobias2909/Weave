"""Which Firefox family profiles on this machine hold cookies.

yt-dlp can find a browser by itself, but only the standard Mozilla
directories, so a fork such as Zen, Floorp or LibreWolf is invisible to it and
the one profile it does find may be a browser nobody has opened in a year.
This module looks in the places the forks actually use and reports what it
found, so the window can offer a list and the checks can say what is there.

Firefox family only, deliberately. Everything past the plain feed reads the
jar as an unencrypted `moz_cookies` table, directly here and through yt-dlp's
firefox backend in the music code. A Chromium jar is encrypted with a key from
the desktop keyring, which is a different mechanism rather than another path,
so the family travels with the choice and adding one later stays an addition.

A profile is described by its directory, never by a browser name handed to
yt-dlp, because the name is what loses the forks in the first place.
"""

from __future__ import annotations

import configparser
import contextlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from . import paths

# What a signed in YouTube session looks like in the jar. The long lived
# cookies say an account is there at all, the rotating pair say the browser
# has refreshed the session recently enough for the site to accept it. The
# doctor grades on the same two sets, from this one reading.
SESSION_COOKIES = frozenset({"SID", "__Secure-1PSID", "__Secure-3PSID"})
ROTATING_COOKIES = frozenset({"__Secure-1PSIDTS", "__Secure-3PSIDTS"})
_NAMED = SESSION_COOKIES | ROTATING_COOKIES

# Where each browser keeps its profile root. The name is what a person calls
# the browser, since the directory name is not always recognisable. A root
# that is not installed simply does not exist and costs one stat.
_ROOTS: tuple[tuple[str, str], ...] = (
    ("Firefox", "~/.mozilla/firefox"),
    ("Zen", "~/.zen"),
    ("Zen", "~/.config/zen"),
    ("Floorp", "~/.floorp"),
    ("LibreWolf", "~/.librewolf"),
    ("LibreWolf", "~/.config/librewolf"),
    ("Waterfox", "~/.waterfox"),
    ("Mullvad Browser", "~/.mullvad-browser"),
)

# The same browsers packaged as a flatpak or a snap, where the home directory
# is the sandbox's own. Globbed rather than listed by application id, so a
# fork nobody here has heard of is found as long as it stores its profiles the
# way the family does.
_SANDBOXED: tuple[str, ...] = (
    "~/.var/app/*/.mozilla/firefox",
    "~/.var/app/*/.zen",
    "~/.var/app/*/.floorp",
    "~/.var/app/*/.librewolf",
    "~/.var/app/*/.waterfox",
    "~/snap/firefox/common/.mozilla/firefox",
)

# Firefox writes a second profile of its own next to the real one for the
# remote debugger. It carries a cookies.sqlite with nothing in it, and it is
# not listed in profiles.ini, so it only turns up when the fallback has to
# look at directories.
_NOT_A_PROFILE = frozenset({"chrome_debugger_profile"})

JAR = "cookies.sqlite"


@dataclass(frozen=True)
class Profile:
    """One browser profile directory that has a cookie jar."""

    family: str
    name: str
    path: Path
    written_at: int
    # Which YouTube cookies are in the jar. Empty when the jar could not be
    # read, which is not the same as a jar holding no login, so `readable`
    # says which of the two happened.
    cookies: frozenset[str] = frozenset()
    # How many YouTube cookies the jar holds in total. Not a signal about the
    # login, deliberately: a fully signed in profile can hold sixty of them
    # and another three hundred, the difference being third party leftovers.
    # It is here because the checks print it and a number is worth more than
    # nothing when the named ones are missing.
    count: int = 0
    # When the browser last sent YouTube its session cookies. Zero when the
    # jar could not say. This, and not the file's timestamp, is what tells a
    # profile somebody browses in from one that merely exists: a browser
    # writes to its jar for any site at all.
    used_at: int = 0
    readable: bool = True
    # Whether this is the profile the browser itself opens. Read from
    # installs.ini, which is the only file that knows: profiles.ini can carry
    # a Default=1 on a profile the browser has not opened in years.
    launched: bool = False

    @property
    def signed_in(self) -> bool:
        return bool(self.cookies & SESSION_COOKIES)

    @property
    def fresh(self) -> bool:
        """Whether the session tokens are the ones the site keeps rotating.
        A profile signed in long ago and never opened since has the account
        cookies and not these, and YouTube stops accepting it."""
        return bool(self.cookies & ROTATING_COOKIES)

    @property
    def label(self) -> str:
        """What the window shows. The profile name is included even when
        there is only one, because a person picking between two Firefoxes
        needs to see which is which."""
        return f"{self.family}, {self.name}"

    @property
    def idle_days(self) -> int | None:
        """How long since this browser last spoke to YouTube, or None when
        the jar would not say."""
        if not self.used_at:
            return None
        return max(0, int((time.time() - self.used_at) // 86400))

    @property
    def state(self) -> str:
        """The rest of the line in the window: whether it can be used, and
        how long since it was last used on YouTube."""
        if not self.readable:
            return "the jar could not be read"
        if not self.signed_in:
            return "not signed in to YouTube"
        idle = self.idle_days
        if idle is None:
            days = max(0, int((time.time() - self.written_at) // 86400))
            when = "written today" if days < 1 else f"written {days} days ago"
        elif idle < 1:
            when = "YouTube open today"
        else:
            when = f"YouTube last open {idle} days ago"
        return when if self.fresh else f"signed in but stale, {when}"


class _Jar(NamedTuple):
    names: frozenset[str]
    count: int
    readable: bool
    used_at: int = 0


def _read_jar(path: Path) -> _Jar:
    """The YouTube cookie names in one jar, and whether it could be read.

    The file is copied first because a running browser holds a write ahead
    lock on it, and a copy of a locked jar still carries everything committed
    before it was taken, which is every cookie that matters here.
    """
    copy = paths.CACHE_DIR / f"probe-{abs(hash(str(path)))}.sqlite"
    try:
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(path.read_bytes())
        try:
            with contextlib.closing(sqlite3.connect(copy)) as jar:
                rows = jar.execute(
                    "SELECT name, lastAccessed FROM moz_cookies "
                    "WHERE host LIKE '%youtube.com'").fetchall()
                names = {row[0] for row in rows}
                # When the browser last sent the session cookies, which is
                # when it last spoke to YouTube. MEASURED across three real
                # profiles: the file's own timestamp said all three had been
                # written today or lately, while this said 0.5 days, 9 days
                # and 119 days, and only the first one could still resolve a
                # video. A profile signed in months ago and never opened
                # since holds every cookie and no working session, and the
                # player endpoint answers it with "The page needs to be
                # reloaded" while a browse call still works.
                used = max((row[1] or 0) for row in rows
                           if row[0] in _NAMED) if names & _NAMED else 0
                return _Jar(frozenset(names & _NAMED), len(names), True,
                            int(used / 1_000_000))
        finally:
            copy.unlink(missing_ok=True)
    except (OSError, sqlite3.Error):
        return _Jar(frozenset(), 0, False, 0)


def _ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, UnicodeDecodeError, configparser.Error):
        pass
    return parser


def _launched_paths(root: Path) -> set[str]:
    """The profile directories the installed browsers actually open.

    installs.ini carries one section per installation with the profile it
    starts in. This is not the same as profiles.ini's own Default flag, and
    when the two disagree the browser follows this one. Measured on a real
    Zen install where profiles.ini flagged a profile that had never been
    used.
    """
    found = set()
    for section in _ini(root / "installs.ini").values():
        default = section.get("default")
        if default:
            found.add(default.strip())
    return found


def _from_ini(family: str, root: Path) -> list[Profile]:
    parser = _ini(root / "profiles.ini")
    launched = _launched_paths(root)
    out = []
    for name, section in parser.items():
        if not name.lower().startswith("profile"):
            continue
        raw = section.get("path")
        if not raw:
            continue
        relative = section.get("isrelative", "1").strip() not in ("0", "false", "False")
        path = (root / raw) if relative else Path(raw)
        jar = path / JAR
        if not jar.exists():
            continue
        read = _read_jar(jar)
        out.append(Profile(
            family=family,
            name=section.get("name") or path.name,
            path=path,
            written_at=int(jar.stat().st_mtime),
            cookies=read.names,
            count=read.count,
            used_at=read.used_at,
            readable=read.readable,
            launched=raw.strip() in launched,
        ))
    return out


def _from_directories(family: str, root: Path) -> list[Profile]:
    """What is there when profiles.ini is missing or unreadable. Only one
    level down, since the debugger profile the browser writes for itself sits
    inside a real profile and is not one."""
    out = []
    for jar in sorted(root.glob(f"*/{JAR}")):
        if jar.parent.name in _NOT_A_PROFILE:
            continue
        read = _read_jar(jar)
        out.append(Profile(family=family, name=jar.parent.name, path=jar.parent,
                           written_at=int(jar.stat().st_mtime), cookies=read.names,
                           count=read.count, used_at=read.used_at,
                           readable=read.readable))
    return out


def describe(path: Path, family: str = "") -> Profile:
    """One named directory, read the same way a discovered one is. This is
    how a profile that was written into the config or picked by hand is
    graded by the same reading as the ones found here."""
    jar = path / JAR
    read = _read_jar(jar) if jar.exists() else _Jar(frozenset(), 0, False)
    written = int(jar.stat().st_mtime) if jar.exists() else 0
    return Profile(family=family or "Firefox family", name=path.name, path=path,
                   written_at=written, cookies=read.names, count=read.count,
                   used_at=read.used_at, readable=read.readable and jar.exists())


def roots() -> list[tuple[str, Path]]:
    """Every profile root that exists on this machine, named."""
    home = Path.home()
    out: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for family, raw in _ROOTS:
        path = Path(raw).expanduser()
        if path.is_dir() and path not in seen:
            seen.add(path)
            out.append((family, path))
    for pattern in _SANDBOXED:
        relative = pattern.replace("~/", "", 1)
        for path in sorted(home.glob(relative)):
            if path.is_dir() and path not in seen:
                seen.add(path)
                # The sandbox directory is named after the application id,
                # which is the only name there is for it here.
                out.append((_sandbox_name(path), path))
    return out


def _sandbox_name(path: Path) -> str:
    for part in path.parts:
        if part.startswith(("org.", "io.", "one.", "app.", "com.", "net.")):
            return part.rsplit(".", 1)[-1].title() + " (flatpak)"
    if "snap" in path.parts:
        return "Firefox (snap)"
    return path.name


def found(where: list[tuple[str, Path]] | None = None) -> list[Profile]:
    """Every profile with a cookie jar, best first.

    Signed in beats signed out, because a profile without a login answers
    nothing this program asks. Then whichever spoke to YouTube most recently,
    since a session only stays valid in a browser somebody is using, and only
    then the one the browser itself opens.
    """
    out: list[Profile] = []
    for family, root in (roots() if where is None else where):
        profiles = _from_ini(family, root) or _from_directories(family, root)
        out.extend(profiles)
    out.sort(key=lambda p: (p.signed_in, p.fresh, p.used_at or p.written_at,
                            p.launched, p.written_at), reverse=True)
    return out


def best(where: list[tuple[str, Path]] | None = None) -> Profile | None:
    """The profile to use when nobody has said which. None when this machine
    has no Firefox family jar at all, in which case yt-dlp's own search is
    still worth a try."""
    for profile in found(where):
        if profile.signed_in:
            return profile
    return None
