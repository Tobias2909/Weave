"""A bundle somebody can send when nothing is arriving.

The checks in doctor.py say what is wrong on the machine they run on. This
packs the same answers, plus the numbers behind them, into one file that can be
attached to a message, so a problem can be looked at by somebody who is not
sitting at that machine.

What it must never contain is the collection itself. A channel list is a
personal thing and a video title says what somebody watched, so nothing here
carries either: errors are grouped by their message, channels appear as ids
only where an id is the thing being asked about, and the counts are counts.
Cookies, tokens and the Twitch client id are left out entirely rather than
shortened, because a shortened secret is still a secret.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from . import __version__, doctor, paths
from .config import Config
from .db import SCHEMA_VERSION, Database

# Kept out of the bundle whatever section they are in. Matched against the key
# rather than the value, since a value is exactly what must not be read.
SECRET_KEYS = ("client_id", "client_secret", "token", "secret", "password", "key")


def _versions() -> str:
    lines = [f"weave {__version__}",
             f"python {sys.version.split()[0]}",
             f"platform {platform.platform()}"]
    try:
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qVersion
        lines.append(f"PySide6 {pyside_version} on Qt {qVersion()}")
    except Exception as exc:
        lines.append(f"PySide6 could not be asked, {type(exc).__name__}")
    for name, args in (("yt-dlp", ["--version"]), ("mpv", ["--version"])):
        found = shutil.which(name)
        if not found:
            lines.append(f"{name} is not on PATH")
            continue
        try:
            said = subprocess.run([found, *args], capture_output=True, text=True,
                                  timeout=15).stdout.strip().splitlines()
            lines.append(f"{name} {said[0] if said else 'said nothing'}")
        except Exception as exc:
            lines.append(f"{name} could not be asked, {type(exc).__name__}")
    return "\n".join(lines) + "\n"


def _checks(report: doctor.Report) -> str:
    lines = []
    for check in report.checks:
        lines.append(f"[{check.state}] {check.name}: {check.detail}")
        if check.fix:
            lines.append(f"        {check.fix}")
    counts = report.counts()
    lines.append("")
    lines.append(f"{counts.get(doctor.OK, 0)} ok, {counts.get(doctor.WARN, 0)} warn, "
                 f"{counts.get(doctor.FAIL, 0)} fail")
    return "\n".join(lines) + "\n"


def _settings(cfg: Config) -> str:
    """The configuration as it is being used, secrets left out.

    What is being used rather than what is in the file: most of it is a
    default nobody wrote down, and a default that has been changed upstream is
    exactly the kind of thing this is for.
    """
    lines = []
    for section in sorted(cfg.raw) if isinstance(cfg.raw, dict) else []:
        values = cfg.raw.get(section)
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for key in sorted(values):
            if any(word in key.lower() for word in SECRET_KEYS):
                lines.append(f"{key} = <left out>")
            else:
                lines.append(f"{key} = {values[key]!r}")
        lines.append("")
    return "\n".join(lines) if lines else "nothing set, every value is a default\n"


def _requests(db: Database, hours: int = 24) -> str:
    """Every minute an endpoint was asked anything, for the last day.

    A refusal is the whole story of a throttled endpoint, and when it started
    is most of what says why.
    """
    first = (int(time.time()) - hours * 3600) // 60
    rows = db.conn.execute(
        "SELECT minute, endpoint, count, refused FROM request_budget "
        "WHERE minute >= ? ORDER BY minute", (first,)).fetchall()
    lines = ["minute\tendpoint\tsent\trefused"]
    for row in rows:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["minute"] * 60))
        lines.append(f"{stamp}\t{row['endpoint']}\t{row['count']}\t{row['refused']}")
    return "\n".join(lines) + "\n"


def _failures(db: Database) -> str:
    """What the channels that failed said, grouped.

    Grouped because a burst refusal is one thing said a few hundred times, and
    because a list of channel names is a list of what somebody watches. The
    ids of the first few are kept, since whether a feed answers is a question
    about a particular id.
    """
    rows = db.conn.execute(
        "SELECT last_error, COUNT(*) AS held, "
        "  GROUP_CONCAT(ext_id) AS ids "
        "FROM channels WHERE last_error IS NOT NULL AND last_error <> '' "
        "GROUP BY last_error ORDER BY held DESC LIMIT 40").fetchall()
    if not rows:
        return "no channel is holding an error\n"
    lines = []
    for row in rows:
        ids = (row["ids"] or "").split(",")[:3]
        lines.append(f"{row['held']:5}  {row['last_error']}")
        lines.append(f"       for instance {', '.join(ids)}")
    return "\n".join(lines) + "\n"


def _numbers(db: Database, cfg: Config) -> str:
    """Counts, and nothing that says what any of them are."""
    def one(sql: str) -> int:
        try:
            return int(db.conn.execute(sql).fetchone()[0])
        except Exception:
            return -1

    files = pictures = 0
    if paths.IMAGE_CACHE.exists():
        for path in paths.IMAGE_CACHE.rglob("*"):
            if path.is_file():
                files += 1
                pictures += path.stat().st_size

    held = db.conn.execute(
        "SELECT value FROM meta WHERE key='schema_version'").fetchone()
    lines = [
        f"schema {held['value'] if held else 'not written'}, "
        f"this build wants {SCHEMA_VERSION}",
        f"database {db.path.stat().st_size // 1024} KB"
        if Path(db.path).exists() else "database missing",
        f"channels {one('SELECT COUNT(*) FROM channels')}"
        f", followed {one('SELECT COUNT(*) FROM channels WHERE tracked=1')}"
        f", in All {one('SELECT COUNT(*) FROM channels WHERE in_all=1')}",
        f"videos {one('SELECT COUNT(*) FROM videos')}"
        f", streams {one('SELECT COUNT(*) FROM videos WHERE live_status IS NOT NULL')}",
        f"groups {one('SELECT COUNT(*) FROM groups')}"
        f", boxes {one('SELECT COUNT(*) FROM boxes')}"
        f", playlists {one('SELECT COUNT(*) FROM playlists')}",
        f"watched {one('SELECT COUNT(*) FROM watched')}",
        f"pictures {files} files, {pictures // (1024 * 1024)} MB",
        f"cookies from {'a browser profile' if cfg.browser_profile != 'auto' else 'auto'}",
        f"player {cfg.player_command}",
    ]
    return "\n".join(lines) + "\n"


def default_path() -> Path:
    """Where the bundle goes when nobody says. The downloads folder if there is
    one, since that is where a file to attach to a message is looked for."""
    downloads = Path.home() / "Downloads"
    root = downloads if downloads.is_dir() else Path.home()
    return root / time.strftime("weave-report-%Y%m%d-%H%M.zip")


def write(db: Database, cfg: Config, target: Path | None = None,
          network: bool = True, problems: list[str] | None = None) -> Path:
    """Write the bundle and answer where it went."""
    path = Path(target) if target else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    report = doctor.run(cfg, db, network=network)
    parts = {
        "checks.txt": _checks(report),
        "versions.txt": _versions(),
        "settings.txt": _settings(cfg),
        "numbers.txt": _numbers(db, cfg),
        "requests.tsv": _requests(db),
        "failures.txt": _failures(db),
        "problems.txt": ("\n".join(problems) + "\n") if problems else "nothing reported\n",
        "README.txt": (
            "A report from Weave, written by the button on the How things are page.\n\n"
            "It holds the checks that page shows, the versions in use, the settings\n"
            "with anything secret left out, counts of what is stored, every request\n"
            "made in the last day and what the failing channels said.\n\n"
            "It holds no channel names, no video titles, no cookies and no tokens.\n"),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, text in parts.items():
            bundle.writestr(name, text)
    return path
