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

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, backoff, browsers, cookies, paths
from .budget import FEEDS
from .config import Config
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
        ("mpv", ["mpv", "--version"], False,
         "Videos are handed to it, and music plays through a second one with no window"),
        ("streamlink", ["streamlink", "--version"], False, "Only Twitch playback needs it"),
    ):
        found = _version(command)
        if found and name == "mpv":
            _mpv_age(found, report)
        elif found:
            report.add(name, OK, found[:60])
        elif needed:
            report.add(name, FAIL, "not installed", f"{why}. Install {command[0]}")
        else:
            report.add(name, WARN, "not installed", why)
    _js_runtime(report)
    _music_library(report)


def _js_runtime(report: Report) -> None:
    """Which JavaScript runtime YouTube's challenge will be solved with.

    Not simply whether one is installed. **yt-dlp enables deno and nothing
    else by default**, so a machine with node alone has a runtime yt-dlp will
    not touch unless it is named, and the failure that follows names neither:
    an authenticated call answers "The page needs to be reloaded" while the
    same call without cookies works. Weave names it now, and this line says
    so, because the two together are the whole of that story.
    """
    from .sources.ytdlp import js_runtime_args

    if shutil.which("deno"):
        report.add("a JavaScript runtime", OK, _version(["deno", "--version"]) or "deno")
        return
    named = js_runtime_args()
    if named:
        report.add("a JavaScript runtime", OK,
                   f"{named[-1].split(':')[0]}, named for yt-dlp because it enables "
                   f"only deno by itself")
        return
    if shutil.which("node") or shutil.which("bun"):
        report.add("a JavaScript runtime", FAIL,
                   "one is installed and this yt-dlp cannot be told to use it",
                   "Install deno, which is the one yt-dlp reaches for on its own")
        return
    report.add("a JavaScript runtime", FAIL, "not installed",
               "YouTube answers a signed in request with a challenge, and solving it "
               "needs deno or node. Without one, playback and the music area fail while "
               "the feed keeps working")


def _music_library(report: Report) -> None:
    """Which ytmusicapi is in front of us, if any.

    Said out loud for the same reason mpv's version is. The music area is one
    library away from the rest of the program, distributions ship whatever
    they froze, and an old one fails in a way that reads like a broken account
    rather than a package that is behind: pressing a song came back as
    KeyError: 'endpoint' on a laptop while the same press worked here.
    """
    from .sources import ytmusic

    have = ytmusic.installed()
    if not have:
        report.add("ytmusicapi", WARN, "not installed",
                   "Only the music area needs it. Install python-ytmusicapi")
        return
    said = ".".join(str(part) for part in have)
    stale = ytmusic.too_old()
    if stale:
        report.add("ytmusicapi", FAIL, said,
                   "A station or a playlist fails with a KeyError in its own parser. "
                   "Update it")
    else:
        report.add("ytmusicapi", OK, said)


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
    source = cookies.resolve(cfg)
    report.add("cookie source", OK, source.text)
    others = [p for p in browsers.found() if p.path != source.path]

    def alternatives() -> str:
        """What else is on this machine, for a line that has to suggest
        something. Signed in first, since that is the useful end of it."""
        if not others:
            return "No other Firefox family profile with cookies was found here"
        shown = ", ".join(f"{p.label} ({p.state})" for p in others[:3])
        return f"Also here: {shown}. Pick one in Settings"

    if source.path is None:
        report.add("browser profile", WARN, "yt-dlp will look for one itself",
                   alternatives())
        return
    profile = browsers.describe(source.path)
    if not profile.readable:
        report.add("browser profile", FAIL, f"no {browsers.JAR} under {source.path}",
                   alternatives())
        return
    # When that browser last spoke to YouTube, not when the file was last
    # touched. A browser writes to its jar for any site at all, so the file's
    # own timestamp says a profile nobody has watched anything in is fresh.
    # A session that is not kept warm is refused by the player endpoint with
    # "The page needs to be reloaded" while a browse call still answers, so
    # this is the line that explains music that will not start.
    idle = profile.idle_days
    age_days = idle if idle is not None else (time.time() - profile.written_at) / 86400
    state = OK if age_days < 14 else WARN
    said = (f"{source.path.name}, YouTube last open {age_days:.0f} days ago"
            if idle is not None else
            f"{source.path.name}, cookies written {age_days:.0f} days ago")
    report.add("browser profile", state, said,
               "" if state == OK else "A session nobody keeps warm stops being accepted. "
                                      f"Open YouTube in that browser once. {alternatives()}")
    if not profile.signed_in:
        report.add("YouTube login", FAIL, "no session cookies in that profile",
                   "Sign in to YouTube in that browser. " + alternatives())
    elif not profile.fresh:
        report.add("YouTube login", WARN, "signed in, but the rotating tokens are missing",
                   "Open YouTube in that browser once")
    else:
        report.add("YouTube login", OK, f"{profile.count} YouTube cookies")


# Something short, public and certain to exist, for a check that has to play
# a real sound. The same video the README uses.
PROBE_TRACK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def playback(cfg: Config, report: Report, url: str = PROBE_TRACK,
             seconds: float = 6.0) -> None:
    """Walk the whole music chain and say which step of it fails.

    Nothing else does. The window shows one line when a track will not play,
    and every step behind that line looks the same from there: an address
    that was never resolved, a player that would not start, a player that
    started and could not open the sound card. So this asks each of them in
    order and stops at the first that will not answer, which is the only
    thing anybody wants to know when the press does nothing.

    It plays for real, briefly. A silent output would hide exactly the case
    where the machine's sound is what is broken.
    """
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

    from . import engine as music
    from .audio import resolve_address

    binary = shutil.which("mpv")
    if binary is None:
        report.add("mpv", FAIL, "not installed", "The music plays through a second mpv")
        return
    try:
        address = resolve_address(cfg, url, live=False).address
    except Exception as exc:
        report.add("the address", FAIL, f"{type(exc).__name__}: {exc}",
                   "yt-dlp could not turn the track into a stream. Check the cookie "
                   "source above, and that yt-dlp and a JavaScript runtime are there")
        return
    report.add("the address", OK, f"{address.split('?')[0][:56]}")

    app = QCoreApplication.instance() or QCoreApplication([])
    player = music.MusicEngine()
    trouble: list[str] = []
    player.gone.connect(trouble.append)
    player.ended.connect(lambda why: trouble.append(f"mpv ended the track, {why}")
                         if why and why != "eof" else None)
    if not player.ensure():
        report.add("the player", FAIL, trouble[0] if trouble else "mpv would not start",
                   "The music player is a plain mpv with no window and no config")
        return
    report.add("the player", OK, "started and answered on its socket")

    reached: list[float] = []
    player.positionChanged.connect(reached.append)
    player.load(address)
    player.set_pause(False)

    loop = QEventLoop()
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(int(seconds * 1000))
    watch = QTimer()
    watch.setInterval(100)
    # Half a second of sound is proof enough that the whole chain works, and
    # nobody wants to sit through more of it than that.
    watch.timeout.connect(lambda: loop.quit() if (reached and reached[-1] > 0.5)
                          or trouble else None)
    watch.start()
    loop.exec()
    watch.stop()
    deadline.stop()
    del app

    played = reached[-1] if reached else 0.0
    # Whatever mpv itself called an error, which is the only account of a
    # sound card that would not open.
    said = getattr(player, "complaint", lambda: "")()
    player.quit()
    if played > 0.5:
        report.add("playing", OK, f"{played:.1f} s of sound came out of mpv")
    elif trouble:
        report.add("playing", FAIL, f"{trouble[-1]}{said}",
                   "mpv took the address and could not play it. A machine with no "
                   "working sound output fails exactly here")
    else:
        report.add("playing", FAIL, f"nothing played within {seconds:.0f} s{said}",
                   "mpv took the address and never reported a position")


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


def sweep_fresh(db: Database, cfg: Config) -> bool:
    """Whether the subscriptions sweep can be leaned on right now.

    It decides how often every covered channel is asked on its own, so three
    places wanted the answer and two of them had grown their own copy of it.
    One place, because a schedule that disagrees with the poller about this is
    worse than no schedule at all.
    """
    if not cfg.sweep_limit or not cfg.sweep_stale_s:
        return False
    swept_at = db.get_int("sweep_at", 0)
    return bool(swept_at) and int(time.time()) - swept_at < cfg.sweep_stale_s


def _schedule(db: Database, cfg: Config, report: Report) -> None:
    tiers = cfg.feed_tiers
    swept_at = db.get_int("sweep_at", 0)
    age = int(time.time()) - swept_at
    fresh = sweep_fresh(db, cfg)
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

    **The sweep is taken into account here exactly as the poller takes it into
    account**, which it was not before: this asked for the tiered intervals
    only, so a channel that posts often read as due every quarter of an hour
    while the poller was really leaving it six hours. On a real subscription
    list that was 146 of 466 channels, wrong by as much as a factor of 24.

    Two intervals travel out of here, and they are not the same thing. `tier_s`
    is how often the channel POSTS, which is what names it; `interval_s` is how
    often it is ASKED, which is what the waiting is measured against. Reading
    the name off the second one would be wrong in a way that looks right,
    because a covered channel lands on 21600 and that is also the quiet tier,
    so every busy channel the sweep covers would be labelled quiet.
    """
    tiers = cfg.feed_tiers
    now = int(time.time())
    rows = db.channels_due(tiers, limit=limit, force=True,
                           sweep_fresh=sweep_fresh(db, cfg))
    out = []
    for row in rows:
        tier_s = int(row["tier_s"])
        interval = int(row["interval_s"])
        last = row["last_polled_at"]
        tier = {tiers.hot_s: "posts often", tiers.warm_s: "posts sometimes",
                tiers.cold_s: "quiet", tiers.frozen_s: "dormant"}.get(tier_s, "")
        out.append({
            "key": row["key"],
            "title": row["title"] or row["ext_id"],
            "tier": tier,
            "tier_s": tier_s,
            "interval_s": interval,
            # Whether the sweep is what is holding this channel back, rather
            # than its own tier. Worth saying outright, since otherwise a
            # channel that posts often and is asked every six hours reads as a
            # mistake.
            "covered": interval != tier_s,
            "last_polled_at": last,
            "due_in_s": 0 if not last else max(0, last + interval - now),
            "error": row["last_error"] or "",
        })
    return out
