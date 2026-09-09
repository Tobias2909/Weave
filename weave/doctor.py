"""Why nothing is arriving.

Every scraper failure in this application looks the same from the outside: an
exit code of zero, no items, and no error. That is what makes this the most
valuable file in the project for its size. It asks each part whether it is
working and says so plainly, so a quiet failure has somewhere to show up.

The checks are the same list whether they are read in a terminal or in the
Debug page, so the two cannot drift. Each one is cheap. Only two of them touch
the network, and they can be left out.
"""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, backoff, paths
from .budget import FEEDS
from .config import Config
from .cookies import browser_spec
from .db import Database
from .sources import release as release_source

OK = "ok"
WARN = "warn"
FAIL = "fail"

# A channel that exists and is not anyone's in particular, for the one request
# that has to name a channel.
PROBE_CHANNEL = "UCBR8-60-B28hp2BmDPdntcQ"


@dataclass
class Check:
    name: str
    state: str
    detail: str = ""
    fix: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, state: str, detail: str = "", fix: str = "") -> None:
        self.checks.append(Check(name, state, detail, fix))

    @property
    def worst(self) -> str:
        states = {check.state for check in self.checks}
        return FAIL if FAIL in states else (WARN if WARN in states else OK)

    def counts(self) -> dict[str, int]:
        return {state: sum(1 for c in self.checks if c.state == state)
                for state in (OK, WARN, FAIL)}


def _version(command: list[str]) -> str | None:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = (done.stdout or done.stderr).strip().splitlines()
    # A tool that exits cleanly and says nothing is still installed.
    return (lines[0] if lines else "installed") if done.returncode == 0 else None


def _weave(db: Database, report: Report) -> None:
    """Which copy this is, and whether a newer one has been published.

    The versions of everything else are already here, so leaving this one out
    meant a report from this page could not say what produced it. Never a
    warning: being a version behind is not a fault, and the foot of the panel
    already says so where it can be acted on.
    """
    tag = db.get_state("update_tag") or ""
    newest = release_source.numbers_text(tag)
    if not newest:
        report.add("Weave", OK, f"{__version__}, newest not asked yet")
    elif release_source.is_newer(tag, __version__):
        report.add("Weave", OK, f"{__version__}, newest {newest}",
                   "A newer release is out, see the foot of the panel or the settings page")
    else:
        report.add("Weave", OK, f"{__version__}, the newest there is")


def _tools(report: Report) -> None:
    for name, command, needed, why in (
        ("yt-dlp", ["yt-dlp", "--version"], True,
         "Everything past the plain feed goes through it"),
        ("a JavaScript runtime", ["deno", "--version"], True,
         "yt-dlp solves YouTube's challenges with deno or node"),
        ("mpv", ["mpv", "--version"], False,
         "Videos are handed to it, and music plays through a second one with no window"),
        ("streamlink", ["streamlink", "--version"], False, "Only Twitch playback needs it"),
    ):
        if shutil.which(command[0]) is None and name == "a JavaScript runtime":
            if shutil.which("node") is not None:
                report.add(name, OK, "node")
                continue
        found = _version(command)
        if found and name == "mpv":
            _mpv_age(found, report)
        elif found:
            report.add(name, OK, found[:60])
        elif needed:
            report.add(name, FAIL, "not installed", f"{why}. Install {command[0]}")
        else:
            report.add(name, WARN, "not installed", why)


def _mpv_age(said: str, report: Report) -> None:
    """Which mpv this is, and which shape of command it is being asked in.

    Where loadfile's options go moved in mpv 0.38, and handing a player the
    wrong shape does not lose a start position, it makes the whole load fail,
    so a resumed track would not play at all. Weave asks each player the way it
    understands, so neither is worse off and this is not a warning.

    It is said out loud because Debian and Ubuntu still package 0.37, the two
    behave differently on the one thing, and a report that does not say which
    is in front of it cannot explain a difference between two machines. Reading
    it here rather than deciding it again keeps this line and the code that
    shapes the command from ever disagreeing about the same player.
    """
    from .engine import _INDEX_ARG_SINCE, mpv_numbers

    numbers = mpv_numbers(said)
    if numbers is None or numbers >= _INDEX_ARG_SINCE:
        report.add("mpv", OK, said[:60])
        return
    wanted = ".".join(str(part) for part in _INDEX_ARG_SINCE)
    report.add("mpv", OK, f"{said[:44]}, before {wanted}, older loadfile shape")


def _player(cfg: Config, report: Report) -> None:
    """Which mpv a video is handed to, resolved rather than as configured.

    Worth a line of its own because the answer depends on where Weave was
    started from. The wrapper lives in ~/.local/bin, which a shell has on PATH
    and a desktop session has not, and without it every video opens a window of
    its own and nothing reports what was watched.
    """
    from .player.mpv import PlayerNotFound, WRAPPER_NAME, resolve_command

    try:
        command = resolve_command(cfg)
    except PlayerNotFound as exc:
        report.add("player", FAIL, str(exc), "Install mpv, or set player.command")
        return
    if Path(command[0]).name == WRAPPER_NAME:
        report.add("player", OK, f"{command[0]}, one window reused")
    else:
        report.add("player", WARN, f"{command[0]}, a window per video",
                   f"{WRAPPER_NAME} was not found. Without it mpv is started "
                   f"again for every video and nothing is marked watched")


def _config(cfg: Config, report: Report) -> None:
    """Whether the config file was actually read. A file with a typo in it
    yields the defaults and nothing else says so."""
    if cfg.problem:
        report.add("config file", FAIL, cfg.problem, "Fix the file, the defaults apply until then")
    elif cfg.warnings:
        # The file was read and most of it applies. What did not is listed,
        # because a misspelt key is a setting somebody believes is in force.
        shown = "; ".join(cfg.warnings[:3])
        more = f", and {len(cfg.warnings) - 3} more" if len(cfg.warnings) > 3 else ""
        report.add("config file", WARN, f"{shown}{more}",
                   "Those lines are ignored, the rest of the file applies")
    elif cfg.raw:
        report.add("config file", OK, str(paths.CONFIG_FILE))
    else:
        report.add("config file", OK, "not written yet, the defaults apply")


def _cookies(cfg: Config, report: Report) -> None:
    spec = browser_spec(cfg)
    report.add("cookie source", OK, spec)
    _, _, profile = spec.partition(":")
    if not profile:
        report.add("browser profile", WARN, "yt-dlp will look for one itself",
                   "Set browser_profile in the config if it picks the wrong one")
        return
    path = Path(profile)
    jar = path / "cookies.sqlite"
    if not jar.exists():
        report.add("browser profile", FAIL, f"no cookies.sqlite under {path}",
                   "Point browser_profile at the profile directory you actually browse in")
        return
    age_days = (time.time() - jar.stat().st_mtime) / 86400
    # The rotating tokens are only refreshed in the browser that is being used,
    # so a profile nobody browses in rots without ever looking broken.
    state = OK if age_days < 14 else WARN
    report.add("browser profile", state, f"{path.name}, cookies written "
               f"{age_days:.0f} days ago",
               "" if state == OK else "Nothing has written to that profile lately. If you "
                                      "switched browsers, point browser_profile at the new one")
    try:
        copy = paths.CACHE_DIR / "doctor-cookies.sqlite"
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(jar.read_bytes())
        try:
            # Closed before the copy is removed, or the connection lingers on
            # a file that is gone and says so on the console at shutdown.
            with contextlib.closing(sqlite3.connect(copy)) as jar_copy:
                names = {row[0] for row in jar_copy.execute(
                    "SELECT name FROM moz_cookies WHERE host LIKE '%youtube.com'")}
        finally:
            copy.unlink(missing_ok=True)
    except Exception as exc:
        report.add("YouTube login", WARN, f"could not read the jar, {exc}")
        return
    wanted = {"SID", "__Secure-1PSID", "__Secure-3PSID"}
    rotating = {"__Secure-1PSIDTS", "__Secure-3PSIDTS"}
    if not names & wanted:
        report.add("YouTube login", FAIL, "no session cookies in that profile",
                   "Sign in to YouTube in that browser")
    elif not names & rotating:
        report.add("YouTube login", WARN, "signed in, but the rotating tokens are missing",
                   "Open YouTube in that browser once")
    else:
        report.add("YouTube login", OK, f"{len(names)} YouTube cookies")


def _database(db: Database, report: Report) -> None:
    size = paths.DB_FILE.stat().st_size / 1_048_576 if paths.DB_FILE.exists() else 0
    counts = db.counts()
    # The loose ones are the channels a saved video brought along. They are
    # not followed and are not counted as channels anywhere else, so the line
    # says so rather than leaving the table looking bigger than the count.
    loose = f", {counts['loose']} kept only for saved videos" if counts["loose"] else ""
    # Followed, polled, and shown in their own group rather than in All. They
    # are part of the channel count, so the line says how many of it they are
    # instead of the feed looking short of them.
    grouped = (f", {counts['group_only']} of them in groups only"
               if counts.get("group_only") else "")
    report.add("database", OK, f"{size:.1f} MB, {counts['channels']} channels{grouped}, "
                               f"{counts['videos']} videos{loose}")
    if not counts["channels"]:
        report.add("channels", FAIL, "nothing is tracked",
                   "Add a channel, or run weave import")
    else:
        report.add("channels", OK, f"{counts['channels']} tracked")

    # RSS carries no duration, so a length is filled in afterwards, and a
    # library that had a backlog when it was first read has a long tail of
    # rows still owed one. Said out loud, because the only way it shows
    # otherwise is the lengths stopping partway down a feed.
    owed, channels = db.lengths_gap()
    if owed:
        report.add("lengths", WARN, f"{owed} videos have no length, "
                                    f"{channels} channels left to read",
                   "Filled in the background, a channel a poll")
    else:
        report.add("lengths", OK, "every video has one")


def _schedule(db: Database, cfg: Config, report: Report) -> None:
    tiers = cfg.feed_tiers
    swept_at = db.get_int("sweep_at", 0)
    age = int(time.time()) - swept_at
    fresh = bool(cfg.sweep_limit and swept_at and age < cfg.sweep_stale_s)
    due = len(db.channels_due(tiers, limit=100000, sweep_fresh=fresh))
    total = len(db.channels(platform="youtube"))
    per_hour = cfg.channels_per_tick * (3600 / max(1, cfg.tick_interval_s))
    detail = f"{due} of {total} channels due, {cfg.channels_per_tick} asked a tick"
    if due and per_hour:
        detail += f", about {due / per_hour * 60:.0f} min to come round"
    report.add("polling", OK if due <= total else WARN, detail)

    # Which channels the sweep covers, and whether it is fresh enough to be
    # leaned on. A covered channel is asked on its own only every few hours,
    # so this is most of the difference between a quiet endpoint and a busy
    # one, and the one thing that changes when the sweep breaks.
    covered, followed = db.sweep_coverage(tiers.coverage_days)
    if not cfg.sweep_limit:
        report.add("the sweep", WARN, "off, every channel is asked on its own interval")
    elif not swept_at:
        report.add("the sweep", WARN, "has not answered yet, every channel is asked on "
                                      "its own interval until it does")
    elif age >= cfg.sweep_stale_s:
        report.add("the sweep", WARN,
                   f"last answered {age // 60} min ago, so every channel is asked on its "
                   f"own interval until it does",
                   "Check yt-dlp and the cookies below")
    else:
        report.add("the sweep", OK,
                   f"{covered} of {followed} channels covered, last swept {age // 60} min "
                   f"ago. A covered channel is asked on its own every "
                   f"{tiers.covered_s // 3600} h and at once when the sweep names it")

    # When the next round actually asks anything, which is not the tick when
    # the endpoint is being left alone.
    resting = db.resting_until(FEEDS) - int(time.time())
    if resting > 0:
        report.add("next refresh", WARN,
                   f"at {time.strftime('%H:%M', time.localtime(time.time() + resting))}"
                   f", in {(resting + 59) // 60} min, when the rest ends",
                   "Refreshing by hand goes anyway")
    else:
        report.add("next refresh", OK,
                   f"within {cfg.tick_interval_s} s, {cfg.channels_per_tick} channels a tick")


def _budget(db: Database, cfg: Config, report: Report) -> None:
    window = cfg.budget_window_s // 60
    limits = cfg.budget_limits
    rows = db.request_totals(cfg.budget_window_s)
    if not rows:
        report.add("requests", OK, f"nothing asked in {window} min")
        return
    parts, worst = [], OK
    for row in rows:
        endpoint, sent = row["endpoint"], int(row["count"] or 0)
        refused = int(row["refused"] or 0)
        limit = limits.get(endpoint, 0)
        parts.append(f"{endpoint} {sent}" + (f"/{limit}" if limit else "")
                     + (f" ({refused} refused)" if refused else ""))
        if limit and sent >= limit:
            worst = WARN
        if refused and sent and refused / sent > 0.2:
            worst = WARN
    report.add("requests", worst, f"in {window} min, " + ", ".join(parts),
               "" if worst == OK else "An endpoint is pushing back or is at its ceiling. "
                                      "It clears on its own")




def _rest(db: Database, report: Report) -> None:
    """Whether the feeds are being left alone, and everything somebody staring
    at a window that is not refreshing would want to know.

    Said whether or not anything has been asked lately, because a rest is
    exactly the case where nothing has been.
    """
    left = db.resting_until(FEEDS) - int(time.time())
    if left <= 0:
        return
    step = db.rest_step(FEEDS)
    ran_for = min(backoff.LONGEST_S, backoff.FIRST_S * (2 ** max(0, step - 1)))
    started = time.strftime("%H:%M", time.localtime(time.time() + left - ran_for))
    until = time.strftime("%H:%M", time.localtime(time.time() + left))
    report.add("the feed rest", WARN,
               f"resting since {started}, until {until}, {(left + 59) // 60} min from now. "
               f"Rest {step} in a row, the next one would be "
               f"{min(backoff.LONGEST_S, backoff.FIRST_S * (2 ** step)) // 60} min",
               "It refused too much of a round. Refreshing by hand goes anyway")


def _cache(report: Report) -> None:
    if not paths.IMAGE_CACHE.exists():
        report.add("image cache", OK, "empty")
        return
    files = list(paths.IMAGE_CACHE.rglob("*"))
    pictures = [f for f in files if f.is_file() and f.suffix != ".log"]
    size = sum(f.stat().st_size for f in pictures) / 1_048_576
    report.add("image cache", OK, f"{len(pictures)} files, {size:.0f} MB")
    problems = paths.IMAGE_CACHE / "failures.log"
    try:
        lines = (problems.read_text(errors="replace").strip().splitlines()
                 if problems.exists() and problems.stat().st_size else [])
    except OSError as exc:
        report.add("pictures that failed", WARN, f"the log could not be read, {exc}")
        return
    if lines:
        report.add("pictures that failed", WARN, f"{len(lines)} recorded",
                   "Run weave cache --problems to see them")


def _twitch(cfg: Config, report: Report, network: bool) -> None:
    from . import tokens
    from .sources import twitch

    if not cfg.twitch_client_id:
        report.add("Twitch", WARN, "the client id is empty",
                   "Unset it to use the one Weave ships, or put your own there")
        return
    stored = tokens.load()
    if stored is None:
        report.add("Twitch", WARN, "not connected", "Run weave twitch login")
        return
    if not network:
        report.add("Twitch", OK, "a login is stored")
        return
    try:
        who = twitch.validate(stored.access_token)
        report.add("Twitch", OK, f"connected as {who.get('login', 'someone')}")
    except twitch.NeedsLogin:
        # The access token lasts hours and is refreshed in normal use, so this
        # only means a login when the refresh is refused too.
        try:
            fresh = twitch.refresh(cfg.twitch_client_id, stored.refresh_token)
            tokens.save(fresh)
            report.add("Twitch", OK, "the login was renewed")
        except twitch.TwitchError as exc:
            report.add("Twitch", FAIL, str(exc), "Run weave twitch login")
    except Exception as exc:
        report.add("Twitch", WARN, f"{type(exc).__name__}: {exc}")


def probe_channel(db: Database) -> str:
    """Which channel to ask the feed endpoint about.

    One of the followed ones, because that is the exact question the poller
    asks all day and the only one whose answer says anything about whether the
    poller will work. The constant is the fallback for a fresh install with
    nothing followed yet, and it is only that: a channel can stop having a
    feed, and a probe that always fails says nothing at all.
    """
    row = db.conn.execute(
        "SELECT ext_id FROM channels WHERE platform='youtube' AND tracked=1 "
        "AND last_error IS NULL ORDER BY last_polled_at DESC LIMIT 1").fetchone()
    return row["ext_id"] if row else PROBE_CHANNEL


def _endpoints(cfg: Config, db: Database, report: Report) -> None:
    from .net import Fetcher, Throttle
    from .sources import rss

    fetcher = Fetcher(Throttle(1, cfg.min_request_interval_s), timeout=15.0, attempts=1)
    try:
        try:
            found = rss.fetch(fetcher, probe_channel(db))
            db.record_requests(FEEDS, 1)
            report.add("the feed endpoint", OK, f"answered with {len(found.videos)} entries")
        except Exception as exc:
            db.record_requests(FEEDS, 1, refused=1)
            # This endpoint answers a burst with a refusal rather than a busy
            # signal, so one refusal is not a broken installation.
            report.add("the feed endpoint", WARN, f"{type(exc).__name__}: {exc}",
                       "It answers a burst by refusing. It usually clears within minutes")
    finally:
        fetcher.close()


def run(cfg: Config, db: Database, network: bool = True) -> Report:
    """Everything, in the order a person would ask it."""
    report = Report()
    _weave(db, report)
    _config(cfg, report)
    _tools(report)
    _player(cfg, report)
    _cookies(cfg, report)
    _database(db, report)
    _schedule(db, cfg, report)
    _budget(db, cfg, report)
    _rest(db, report)
    _cache(report)
    _twitch(cfg, report, network)
    if network:
        _endpoints(cfg, db, report)
    return report


# How far back the usual figure is read. One day rather than a week, and that
# is a real trade off: a week is a steadier number, and it is also the wrong
# number for days after anything changes. The question this answers is whether
# the window in front of you is unusual for how the app behaves NOW, so it
# reads the recent behaviour and says so on the page.
#
# The lag is real and worth knowing about. The day the feed volume was cut, a
# day's worth of whole windows on a real log ran 30 to 36 in the new regime and
# 107 to 241 in the old one, so the median sat at 216 while the app was in fact
# costing 35. Nothing is wrong with the figure there; the baseline is simply
# yesterday's app. It washes out within a day of running.
TRAFFIC_DAYS = 1


def traffic(db: Database, cfg: Config, days: int = TRAFFIC_DAYS) -> list[dict]:
    """Where the requests go: what each endpoint has cost this window, what it
    usually costs, and what it is allowed.

    The ceiling alone does not say whether a number is alarming. Both halves
    together do: 34 against a usual 28 is the app working, and 250 against a
    usual 28 is something to look at even though the ceiling is 300 and
    nothing has been refused yet.

    The usual figure is read over spells of asking rather than slices of the
    clock, see `Database.request_shape`, because the app is started and stopped
    and a slice of the clock is mostly the stub either side of that.
    """
    window_s = cfg.budget_window_s
    limits = cfg.budget_limits
    now = {row["endpoint"]: (int(row["count"] or 0), int(row["refused"] or 0))
           for row in db.request_totals(window_s)}
    shape = {row["endpoint"]: row for row in db.request_shape(window_s, days=days)}
    out = []
    for endpoint in sorted(set(limits) | set(now) | set(shape),
                           key=lambda name: (-now.get(name, (0, 0))[0], name)):
        sent, refused = now.get(endpoint, (0, 0))
        seen = shape.get(endpoint)
        usual = int(seen["usual"] or 0) if seen else 0
        most = int(seen["most"] or 0) if seen else 0
        # Whole windows behind the usual figure. None of them means it is not
        # known, which is a different thing from knowing it is nothing: an
        # endpoint that fires once an hour honestly usually costs zero in a
        # quarter of an hour.
        windows = int(seen["windows"] or 0) if seen else 0
        limit = int(limits.get(endpoint, 0))
        state = OK
        if limit and sent >= limit:
            state = FAIL
        elif refused and sent and refused / sent > 0.2:
            state = WARN
        elif usual and sent > 2 * usual and sent > 10:
            # Twice what it usually is, and enough of it to mean anything. A
            # quiet endpoint doubling from two to four says nothing.
            state = WARN
        out.append({
            "endpoint": endpoint,
            "sent": sent,
            "refused": refused,
            "usual": usual,
            "most": most,
            "limit": limit,
            "windows": windows,
            "state": state,
        })
    return out


def schedule(db: Database, cfg: Config, limit: int = 40) -> list[dict]:
    """When each channel was last asked and when it is next due.

    Ordered the way the poller will actually take them, so the top of this list
    is what the next few ticks will do.
    """
    tiers = cfg.feed_tiers
    now = int(time.time())
    rows = db.channels_due(tiers, limit=limit, force=True)
    out = []
    for row in rows:
        interval = int(row["interval_s"])
        last = row["last_polled_at"]
        tier = {tiers.hot_s: "posts often", tiers.warm_s: "posts sometimes",
                tiers.cold_s: "quiet", tiers.frozen_s: "dormant"}.get(interval, "")
        out.append({
            "key": row["key"],
            "title": row["title"] or row["ext_id"],
            "tier": tier,
            "interval_s": interval,
            "last_polled_at": last,
            "due_in_s": 0 if not last else max(0, last + interval - now),
            "error": row["last_error"] or "",
        })
    return out
