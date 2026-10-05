"""Videos played in the window, rather than handed to mpv.

A second player beside the music's: the same libmpv engine, its own render
context and its own surface on a page of its own. MEASURED before any of this
was written, two players drawing 1080p in one window at once dropped no frame,
held none and stalled nothing, and the music paused costs nothing at all.

It differs from the music player where a video differs from a song. The
picture is the point rather than an extra, so it is asked for with the sound
in one resolve and turned on from the start. There is no look-ahead and no
gapless changeover: a video ends on its last frame and the next one starts from
a press or from the queue. And a video is watched rather than heard, so where it
was left is kept and it starts there again, and passing the same share of its
length mpv uses marks it watched.

The queue is Weave's own, shaped like the music's so the same list can draw
it: a video played stays in it, dimmed, and the one pressed while another plays
goes in straight after it and plays.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import Property, QEvent, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QWindow

from . import format as fmt
from . import net, trace
from .audio import (FACT_SPEC, HOLD_SPEED, VIDEO_HEIGHT_STEPS, AddressCache, _why,
                    nothing_to_play, parse_chapters, parse_facts, reads_as_gone)
from .budget import SPONSORBLOCK, Budget
from .config import Config
from .cookies import args as cookie_args
from .cookies import twitch_token
from .engine_libmpv import CURRENT, LibmpvEngine
from .process import Cancelled, Timeout
from .process import run as run_process
from .sources import sponsorblock
from .sources import streamlink
from .sources.ytdlp import prepare

# On top of the music's. A name of its own at the sound server, so the two can
# be told apart there and in a trace. The last frame is kept when a video ends,
# which is what is left on screen when the queue has run out, and what the next
# one replaces without the page going black between them.
OPTIONS = {
    "audio_client_name": "weave-video",
    "keep_open": "yes",
    "prefetch_playlist": False,
    # Decoded on the graphics card where that is known to work. MEASURED in a
    # real window through the render API, 1440p VP9 at 25 fps: 11.1 % of one
    # core in software, 3.5 % on the card, no frame dropped either way.
    # auto-safe only takes a decoder mpv vouches for and falls back to software
    # otherwise. Forcing vaapi through an NVIDIA card's translation layer froze
    # the drawing for 5.6 s, and auto-safe never chose it there.
    "hwdec": "auto-safe",
}

# A video left before this far in starts again from the beginning: that much
# is a look rather than a watch, and resuming it would be a surprise.
RESUME_FROM_S = 30.0

# How often where it is gets written down while it plays, besides every pause,
# every switch and the window closing. Often enough that a crash costs little.
SAVE_EVERY_S = 15.0

# What one press of an arrow moves, and one notch of the volume.
SEEK_STEP_S = 5.0
VOLUME_STEP = 5
VOLUME_DEFAULT = 70
# How wide the picture waits in the corner of the window, until it is made
# bigger or smaller by hand, and the least it can be.
CORNER_WIDTH_DEFAULT = 384
CORNER_WIDTH_LEAST = 144

# When no ceiling has been picked, the screen decides, and before the window has
# said which screen it is on, this does.
FALLBACK_HEIGHT = 1080

# How the pictures under the ceiling are ranked for a video, ahead of yt-dlp's
# own order: the tallest, then the smoothest, then YouTube's Premium quality,
# which yt-dlp ranks as the better source of the same height and which only a
# Premium account's cookies are offered, then vp9 over any other codec, at a
# third of the bytes of avc1 for the same height. The height decides first, so
# Premium only wins against pictures as tall as itself. MEASURED 2026-10-05
# with a Premium account, four videos at three ceilings: 1080p Premium taken
# in vp9 (356) and in av01 (721) alike, and vp9 wherever there is no Premium.
WATCH_SORT = "res,fps,hdr:12,source,vcodec:vp9"

# What yt-dlp's note on a format says when it is YouTube's Premium quality, a
# higher bitrate at the same height.
PREMIUM = "Premium"

# The speeds the player's menu offers.
SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)

# Kept between runs on this machine: the height picked in the player or the
# settings ("auto" lets the screen decide), whether captions are on, and the
# language they were last picked in.
QUALITY_STATE = "video_quality"
CAPTIONS_STATE = "video_captions"
CAPTION_LANGUAGE_STATE = "video_caption_language"

# SponsorBlock, off until it is switched on, and what each kind of segment does
# once it is: skipped, offered with a button, or left alone.
SPONSOR_STATE = "sponsorblock"
SPONSOR_ACTION_STATE = "sponsorblock_{}"

# How long the word that something was skipped stays up, with its Undo.
SKIPPED_NOTICE_MS = 6000

# A segment is left this short of its end, so the last report inside it, a
# moment before the end, does not skip the few frames that are left.
SEGMENT_TAIL_S = 0.3

# How often the part of the video already fetched is looked at, for the
# lighter part of the bar ahead of the played one.
BUFFER_EVERY_MS = 500

# A broadcast says how far behind it is once paused or held up this long, and
# it is worked out this often: the wall clock since it was opened, less how much
# of it has played since, which a pause and a wait for the network both add to.
# MEASURED 2026-10-05 on YouTube and Twitch, paused 30 s and 40 s: exact to a
# tenth of a second, and the player keeps fetching while paused, so what was
# missed is held, up to its own limit of 150 MB.
BEHIND_FROM_S = 5
LIVE_EVERY_MS = 1000
# More than this between two looks a second apart, while playing, is the
# broadcast's own clock jumping, at a break stitched in, and not time lost.
LIVE_JUMP_S = 2.5
# Back to live is a seek this far short of the newest moment held. MEASURED: a
# seek past the end of what the player can seek to is ignored without a word,
# and on Twitch that end trails the newest moment fetched by about two seconds.
# When what is held does not reach the present, within this much, the
# broadcast is opened afresh instead, which is about three seconds.
LIVE_EDGE_MARGIN_S = 1.0
LIVE_REACH_SLACK_S = 2.0

# The pictures the bar shows under the pointer come as sheets of frames, in
# several sizes. Nothing wider than this is taken, which is about what the box
# under the pointer shows them at.
STORYBOARD_WIDTH = 320

# What rides along in the same call as the addresses, each on a line of its own
# behind a tag. The chapters and the facts are found by the shape of their line,
# a list and an object, and these are lists and objects too.
#
# Only the last way each caption is offered is printed, which is its WebVTT
# one, and that is what keeps the line short: every way of every language of
# YouTube's own captions came to 588 KB for one video, MEASURED, and the last
# of each to about a tenth of that.
#
# The note on the picture fetched says whether it is in Premium quality, and
# the notes in the list which heights are offered in it.
EXTRA_PRINTS = (
    "--print", "weave-height:%(height)s",
    "--print", "weave-note:%(requested_formats.0.format_note,format_note)s",
    "--print", ("weave-formats:%(formats.:.{format_id,format_note,height,vcodec,width,rows,"
                "columns,fps,fragments})j"),
    "--print", "weave-captions:%(subtitles.:.-1)j",
    "--print", "weave-auto:%(automatic_captions.:.-1)j",
)


def ceiling_for(screen_height: int) -> int:
    """The largest offered height that fits the screen, so a picture is never
    fetched bigger than anything can show it."""
    fitting = [step for step in VIDEO_HEIGHT_STEPS if step <= int(screen_height)]
    return fitting[-1] if fitting else VIDEO_HEIGHT_STEPS[0]


class ScreenWatch(QObject):
    """Tells the player how tall the screen the window is on is, counted in
    the pixels the window is really drawn in.

    The screen's own ratio cannot say. Wayland gives a screen's scale in whole
    numbers, so a 1080 line screen scaled to 125 % calls itself 864 lines at a
    ratio of 2: 1728 lines, and Auto fetched 1440p for it. The window is told
    the fraction itself. MEASURED in a nested KWin at 125 % and 150 %: the
    screen said 2.0 both times, the window 1.25 and 1.5, and 1080 each time.

    The window moving to another screen is told before its new ratio is, so
    the ratio changing is measured again on its own."""

    def __init__(self, window: QWindow, player: VideoPlayer, parent=None) -> None:
        super().__init__(parent)
        self._window = window
        self._player = player
        window.installEventFilter(self)
        window.screenChanged.connect(self.measure)
        app = QGuiApplication.instance()
        for screen in app.screens():
            screen.geometryChanged.connect(self.measure)
        app.screenAdded.connect(lambda screen: screen.geometryChanged.connect(self.measure))
        self.measure()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self.measure()
        return False

    def measure(self, *_ignored) -> None:
        screen = self._window.screen()
        if screen is None:
            return
        ratio = self._window.devicePixelRatio()
        pixels = round(screen.size().height() * ratio)
        trace.mark("screen_height", pixels=pixels, screen=screen.name(), ratio=ratio,
                   screen_ratio=screen.devicePixelRatio())
        self._player.setScreenHeight(pixels)


def watch_format(height: int, live: bool) -> str:
    """What to ask yt-dlp for, capped at a height.

    A video is offered as a picture and a sound apart at every useful size, and
    joined only at the small ones, so the pair is asked for first, and
    WATCH_SORT says which of the pictures under the cap. A broadcast is only
    ever offered joined.
    """
    height = int(height)
    if live:
        return f"best[height<={height}]/best"
    return (f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]/best")


def premium_heights(formats: list[dict]) -> tuple[int, ...]:
    """The heights the video's picture is offered at in Premium quality,
    tallest first. Only a Premium account's cookies are offered any."""
    heights = {int(one["height"]) for one in formats
               if PREMIUM in str(one.get("format_note") or "")
               and isinstance(one.get("height"), (int, float)) and one["height"] > 0
               and one.get("vcodec") != "none"}
    return tuple(sorted(heights, reverse=True))


def quality_label(height: int, premium: bool = False) -> str:
    return f"{height}p {PREMIUM}" if premium else f"{height}p"


@dataclass(frozen=True)
class Found:
    """What one resolve came back with: the picture, the sound when it is a
    stream of its own, and what rides along in the same call for free."""

    picture: str
    sound: str = ""
    chapters: tuple[dict, ...] = ()
    facts: dict | None = None
    extras: dict = field(default_factory=dict)


def _tagged_list(text: str | None) -> list[dict]:
    if not text:
        return []
    try:
        found = json.loads(text)
    except ValueError:
        return []
    return [one for one in found if isinstance(one, dict)] if isinstance(found, list) else []


def offered_heights(formats: list[dict]) -> tuple[int, ...]:
    """Every height the video's picture is offered at, tallest first. The
    sound alone and the storyboards are offered too and have none."""
    heights = set()
    for one in formats:
        height = one.get("height")
        if (isinstance(height, (int, float)) and height > 0
                and one.get("vcodec") != "none"):
            heights.add(int(height))
    return tuple(sorted(heights, reverse=True))


def storyboard_of(formats: list[dict]) -> dict | None:
    """The sheets of small frames YouTube makes of a video, in the largest
    size that is not wider than the box shows them, or None without any."""
    boards = [one for one in formats
              if str(one.get("format_id") or "").startswith("sb") and one.get("fragments")
              and all(isinstance(one.get(name), (int, float)) and one.get(name) > 0
                      for name in ("width", "height", "columns", "rows", "fps"))]
    fitting = [one for one in boards if one["width"] <= STORYBOARD_WIDTH] or boards
    if not fitting:
        return None
    best = max(fitting, key=lambda one: one["width"])
    sheets = [str(part.get("url") or "") for part in best["fragments"] if isinstance(part, dict)]
    if not sheets or not all(sheets):
        return None
    return {"sheets": sheets, "width": int(best["width"]), "height": int(best["height"]),
            "columns": int(best["columns"]), "rows": int(best["rows"]),
            "fps": float(best["fps"])}


def _query(url: str) -> dict:
    return parse_qs(urlparse(url).query)


def captions_of(uploaded: list[dict], automatic: list[dict]) -> tuple[dict, ...]:
    """Every caption a video offers, in the order the menu lists them: the
    uploader's own by name, then the one YouTube made from the sound.

    YouTube offers its own in every language there is, translated from the
    one it heard, and only that one is kept. It is the one whose address asks
    for no translation.
    """
    made = []
    for one in uploaded:
        url = str(one.get("url") or "")
        code = (_query(url).get("lang") or [""])[0]
        if one.get("ext") != "vtt" or not url or not code:
            continue
        made.append({"code": code, "name": str(one.get("name") or code), "auto": False,
                     "url": url})
    made.sort(key=lambda one: one["name"].casefold())
    heard: list[dict] = []
    for one in automatic:
        url = str(one.get("url") or "")
        asked = _query(url)
        code = (asked.get("lang") or [""])[0]
        if (one.get("ext") != "vtt" or not url or not code or "tlang" in asked
                or any(other["code"] == code for other in heard)):
            continue
        name = str(one.get("name") or code).removesuffix(" (Original)")
        heard.append({"code": code, "name": name, "auto": True, "url": url})
    return tuple(made + heard)


def parse_extras(text: str) -> dict:
    """What the tagged lines of one resolve said: the height fetched and
    whether in Premium quality, the heights offered and those in Premium, the
    storyboard and the captions. Each is an extra the video plays without, so
    anything missing is simply left out."""
    tagged: dict[str, str] = {}
    for line in text.splitlines():
        tag, sep, rest = line.strip().partition(":")
        if sep and tag.startswith("weave-") and tag not in tagged:
            tagged[tag] = rest
    out: dict = {}
    try:
        out["height"] = int(float(tagged.get("weave-height", "")))
    except ValueError:
        pass
    if PREMIUM in tagged.get("weave-note", ""):
        out["premium"] = True
    formats = _tagged_list(tagged.get("weave-formats"))
    out["heights"] = list(offered_heights(formats))
    premium = premium_heights(formats)
    if premium:
        out["premium_heights"] = list(premium)
    board = storyboard_of(formats)
    if board is not None:
        out["storyboard"] = board
    uploaded = _tagged_list(tagged.get("weave-captions"))
    out["captions"] = list(captions_of(uploaded, _tagged_list(tagged.get("weave-auto"))))
    # yt-dlp offers a past broadcast's chat as one more caption, when there is
    # a replay of it to read.
    if any(one.get("protocol") == "youtube_live_chat_replay" for one in uploaded):
        out["chat_replay"] = True
    return out


def _language(code: str) -> str:
    return code.split("-", 1)[0].casefold()


def choose_caption(tracks: list[dict], language: str) -> dict | None:
    """The caption shown when captions are on.

    The language picked last, the uploader's before YouTube's and an exact
    match before a kindred one (en-GB for en). Failing that the video's own
    language, which is the one YouTube's caption is in. Never a stranger: a
    video with only someone else's language uploaded shows none.
    """
    if not tracks:
        return None
    wanted = [language] if language else []
    heard = next((one for one in tracks if one["auto"]), None)
    if heard is not None:
        wanted.append(heard["code"])
    for code in wanted:
        for auto in (False, True):
            for same in (lambda one, c=code: one["code"] == c,
                         lambda one, c=code: _language(one["code"]) == _language(c)):
                found = next((one for one in tracks if one["auto"] == auto and same(one)), None)
                if found is not None:
                    return found
    return None


class NoAddress(RuntimeError):
    pass


# What is said when a Twitch channel turns out not to be on air, by whichever
# of the two asked.
OFF_AIR = "That stream is not on air any more"


def resolve_twitch(cfg: Config, login: str, url: str, height: int,
                   cancel: threading.Event | None = None) -> Found:
    """A Twitch channel's stream to what the player needs, blocking.

    Through streamlink where the machine has it, so its plugins and its own
    config apply, and through yt-dlp otherwise or when streamlink cannot. Both
    play signed in to the browser's Twitch account: yt-dlp finds the login in
    the jar it reads anyway, streamlink is handed it.
    """
    if streamlink.available():
        try:
            answer = streamlink.ask(login, twitch_token(cfg), cancel)
        except streamlink.Offline as exc:
            raise NoAddress(OFF_AIR) from exc
        except (streamlink.StreamlinkError, FileNotFoundError) as exc:
            trace.mark("streamlink_failed", login=login, why=str(exc)[:200])
        else:
            chosen = streamlink.pick(answer, height)
            facts = {name: value for name, value in (("title", answer.title),
                                                     ("channel", answer.author),
                                                     ("category", answer.category)) if value}
            return Found(chosen.url, "", (), facts,
                         {"height": chosen.height, "heights": list(answer.heights),
                          "captions": [], "via": "streamlink"})
    try:
        found = resolve_watch(cfg, url, height, True, cancel)
    except NoAddress as exc:
        if "not currently live" in str(exc) or "offline" in str(exc).lower():
            raise NoAddress(OFF_AIR) from exc
        raise
    return Found(found.picture, found.sound, (), found.facts,
                 dict(found.extras, via="yt-dlp"))


def resolve_watch(cfg: Config, url: str, height: int, live: bool,
                  cancel: threading.Event | None = None) -> Found:
    """One video to what the player needs, blocking. A few seconds.

    One call for everything: the two addresses, the chapters for the marks on
    the bar and the facts under the picture. Warnings are left on for the same
    reason the music's resolve leaves them on: when the challenge goes unsolved
    they are the only account of why.
    """
    command = prepare(["yt-dlp", *cookie_args(cfg),
                       "-f", watch_format(height, live),
                       *([] if live else ["-S", WATCH_SORT]),
                       "--get-url", "--print", "%(chapters)j",
                       "--print", FACT_SPEC, *EXTRA_PRINTS, url])
    result = run_process(command, cancel=cancel, timeout=180)
    addresses = [line for line in result.stdout.splitlines() if line.startswith("http")]
    if not addresses:
        raise NoAddress(_why(result.stderr or ""))
    # The picture is asked for first, so it comes first. A joined stream is one
    # address carrying both.
    return Found(addresses[0], addresses[1] if len(addresses) > 1 else "",
                 parse_chapters(result.stdout), parse_facts(result.stdout),
                 parse_extras(result.stdout))


class _Finder(QThread):
    """Turns one video into what the player needs."""

    found = Signal(str, str, str, list, "QVariantMap", "QVariantMap")
    failed = Signal(str, str)
    gone = Signal(str)

    def __init__(self, cfg: Config, key: str, url: str, height: int, live: bool,
                 parent: QObject | None = None, login: str = "") -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.key = key
        self._url = url
        self._height = height
        self._live = live
        self._login = login
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            if self._login:
                found = resolve_twitch(self._cfg, self._login, self._url, self._height,
                                       self._cancel)
            else:
                found = resolve_watch(self._cfg, self._url, self._height, self._live,
                                      self._cancel)
        except Cancelled:
            return
        except (FileNotFoundError, Timeout, NoAddress) as exc:
            said = str(exc) or "could not find the video"
            # The same care the music takes: the sentence a failed resolve
            # comes back with cannot tell a video that is gone from one blocked
            # here, so it is asked properly before anything is said about it.
            if reads_as_gone(said) or (not self._live and not self._cancel.is_set()
                                       and nothing_to_play(self._cfg, self._url,
                                                           self._cancel)):
                self.gone.emit(self.key)
                return
            self.failed.emit(self.key, said)
            return
        extras = dict(found.extras)
        # Which ceiling this was fetched under, which is what the height it
        # came back at is kept against.
        extras["asked"] = self._height
        self.found.emit(self.key, found.picture, found.sound, list(found.chapters),
                        dict(found.facts or {}), extras)


class _SegmentFinder(QThread):
    """Asks SponsorBlock about one video. A failure costs only the marks, so
    it is written down in the trace and the video plays without them."""

    found = Signal(str, list)

    def __init__(self, db, cfg: Config, key: str, video_id: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self.key = key
        self._video_id = video_id
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        if budget.allowance(SPONSORBLOCK).empty:
            trace.mark("sponsorblock_refused", key=self.key)
            return
        budget.spend(SPONSORBLOCK)
        fetcher = net.Fetcher(net.Throttle(1, self._cfg.min_request_interval_s),
                              cancel=self._cancel)
        try:
            found = sponsorblock.fetch(fetcher, self._video_id)
        except net.Cancelled:
            return
        except Exception as exc:
            budget.spend(SPONSORBLOCK, count=0, refused=1)
            trace.mark("sponsorblock_failed", key=self.key, why=f"{type(exc).__name__}: {exc}")
            return
        finally:
            fetcher.close()
        self.found.emit(self.key, list(found))


class VideoPlayer(QObject):
    """The videos played in the window, and their queue."""

    trackChanged = Signal()
    queueChanged = Signal()
    stateChanged = Signal()
    progressChanged = Signal()
    factsChanged = Signal()
    videoChanged = Signal()
    # The quality, the captions and the storyboard: what the menus on the
    # picture and the box over the bar draw.
    extrasChanged = Signal()
    # The segments on the bar, the button to skip the one playing, and the
    # word that one was skipped.
    sponsorChanged = Signal()
    # The parts of the video fetched, drawn on the bar.
    bufferChanged = Signal()
    # How far behind its present a broadcast is.
    behindChanged = Signal()
    cornerChanged = Signal()
    # A video has begun to play. The music gives way to it here.
    started = Signal(str)
    # Nothing is playing any more and nothing is about to: the queue ran out or
    # it was stopped. The music comes back here.
    stopped = Signal()
    watched = Signal(str, float)
    failed = Signal(str)
    gone = Signal(str)

    def __init__(self, cfg: Config, db=None, parent: QObject | None = None,
                 engine=None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._db = db
        self._engine = engine if engine is not None else LibmpvEngine(self, options=OPTIONS)
        self._queue: list[dict] = []
        self._at = -1
        self._pos = 0.0
        self._dur = 0.0
        self._paused = True
        self._idle = True
        self._buffering = False
        self._finding = False
        self._ended = False
        self._showing = False
        self._facts: dict[str, dict] = {}
        self._chapters: dict[str, tuple] = {}
        self._addresses = AddressCache()
        self._finder: _Finder | None = None
        self._finders: list[_Finder] = []
        self._threshold = float(getattr(cfg, "watched_threshold", 0.85) or 0.85)
        self._counted = ""
        self._saved_at = 0.0
        self._screen_height = 0
        self._speed = 1.0
        # While the picture is held down: faster, and whether it was paused
        # before, to be paused again once it is let go.
        self._held_fast = False
        self._held_from_pause = False
        # Per video, what its resolve said besides the addresses, and per
        # video and ceiling, the height it came back at and whether that was in
        # Premium quality.
        self._extras: dict[str, dict] = {}
        self._fetched: dict[str, int] = {}
        self._premium: set[str] = set()
        # The ceiling the one playing was fetched under, which a new pick is
        # weighed against.
        self._under = 0
        quality = db.get_state(QUALITY_STATE, "auto") if db else "auto"
        self._quality = int(quality) if str(quality).isdigit() else 0
        self._captions_on = bool(db) and db.get_state(CAPTIONS_STATE, "off") == "on"
        self._caption_language = (db.get_state(CAPTION_LANGUAGE_STATE, "") or "") if db else ""
        # The address of the caption on screen, or nothing, and how far up the
        # picture captions sit, in mpv's percent of its height.
        self._caption_shown = ""
        self._caption_place = 100
        # The video being fetched again at another height, whose start is not
        # news to anyone listening for a video starting.
        self._quiet = ""
        self._sponsor_on = bool(db) and db.get_state(SPONSOR_STATE, "off") == "on"
        self._sponsor_actions = {}
        for one in sponsorblock.CATEGORIES:
            said = db.get_state(SPONSOR_ACTION_STATE.format(one.key), one.default) if db else ""
            self._sponsor_actions[one.key] = said if said in sponsorblock.ACTIONS else one.default
        self._segments: dict[str, tuple] = {}
        self._segment_finders: list[_SegmentFinder] = []
        # Segments let play this time through, by an Undo; the one skipped
        # last and when, which a late report from inside it does not skip a
        # second time; the button segment the position is in; the skip the
        # word is up about.
        self._let_play: set[str] = set()
        self._skipping = ("", 0.0)
        self._here: sponsorblock.Segment | None = None
        self._skipped: sponsorblock.Segment | None = None
        self._notice = QTimer(self)
        self._notice.setSingleShot(True)
        self._notice.setInterval(SKIPPED_NOTICE_MS)
        self._notice.timeout.connect(self._drop_notice)
        # The level before a mute, for the same key to give back.
        self._unmuted = 0
        stored = db.get_int("video_volume", VOLUME_DEFAULT) if db else VOLUME_DEFAULT
        self._volume = max(0, min(100, int(stored)))
        wide = (db.get_int("video_corner_width", CORNER_WIDTH_DEFAULT) if db
                else CORNER_WIDTH_DEFAULT)
        self._corner_width = max(CORNER_WIDTH_LEAST, int(wide))
        self._engine.set_volume(self._volume)

        self._engine.positionChanged.connect(self._on_position)
        self._engine.durationChanged.connect(self._on_duration)
        self._engine.pausedChanged.connect(self._on_paused)
        self._engine.idleChanged.connect(self._on_idle)
        self._engine.bufferingChanged.connect(self._on_buffering)
        self._engine.started.connect(self._on_started)
        self._engine.eofChanged.connect(self._on_eof)
        self._engine.videoChanged.connect(self._on_video)
        self._engine.gone.connect(self._on_engine_gone)

        # Several position reports a second, and writing each would be a write
        # to the database several times a second. Kept between, written here.
        self._keeper = QTimer(self)
        self._keeper.setInterval(int(SAVE_EVERY_S * 1000))
        self._keeper.timeout.connect(self._keep_position)
        self._keeper.start()

        # The fetched spans, as shares of the video.
        self._buffered: tuple[tuple[float, float], ...] = ()
        self._buffer_watch = QTimer(self)
        self._buffer_watch.setInterval(BUFFER_EVERY_MS)
        self._buffer_watch.timeout.connect(self._look_at_buffer)
        # A broadcast's wall clock and position when it was opened or caught
        # up, and how far behind it was at the last look.
        self._live_since: tuple[float, float] | None = None
        self._behind = 0.0
        self._live_watch = QTimer(self)
        self._live_watch.setInterval(LIVE_EVERY_MS)
        self._live_watch.timeout.connect(self._look_at_live)

    # ---- what QML reads --------------------------------------------------

    @property
    def engine(self):
        return self._engine

    def _current(self) -> dict:
        if 0 <= self._at < len(self._queue):
            return self._queue[self._at]
        return {}

    def _get_track(self) -> dict:
        return dict(self._current())

    def _get_playing(self) -> bool:
        return bool(self._current()) and not self._paused and not self._idle and not self._ended

    def _get_loading(self) -> bool:
        return bool(self._current()) and (self._finding or self._buffering)

    def _get_has_queue(self) -> bool:
        return bool(self._queue)

    def _get_is_live(self) -> bool:
        return bool(self._current().get("live"))

    def _get_position(self) -> float:
        if self._get_is_live() or self._dur <= 0:
            return 0.0
        return max(0.0, min(1.0, self._pos / self._dur))

    def _get_seconds(self) -> float:
        return float(self._pos)

    def _get_length(self) -> int:
        return 0 if self._get_is_live() else int(self._dur)

    def _get_volume(self) -> int:
        return self._volume

    def _get_speed(self) -> float:
        return self._speed

    def _get_ended(self) -> bool:
        return self._ended

    def _get_showing(self) -> bool:
        return self._showing

    def _get_buffered(self) -> list:
        return [{"at": at, "to": to} for at, to in self._buffered]

    def _get_behind(self) -> int:
        return int(self._behind) if self._behind >= BEHIND_FROM_S else 0

    def has_chat_replay(self) -> bool:
        """Whether the video playing is a past broadcast whose chat was kept."""
        return bool(self._known().get("chat_replay"))

    def _get_queue(self) -> list:
        """The whole queue in the shape the music's list draws: a video played
        stays, the one playing is marked by where it sits."""
        return [{
            "key": entry.get("key", ""),
            "title": entry.get("title", ""),
            # The list calls whoever made it the artist; for a video that is
            # the channel.
            "artist": entry.get("channel", ""),
            "thumbnail": entry.get("thumbnail", ""),
            "duration": entry.get("duration") or fmt.duration_text(entry.get("duration_s")),
            "artistId": "",
            "channelId": entry.get("channelId", ""),
            "at": place,
        } for place, entry in enumerate(self._queue)]

    def _get_queue_index(self) -> int:
        return self._at if 0 <= self._at < len(self._queue) else -1

    def _get_chapters(self) -> list:
        found = self._chapters.get(self._current().get("key") or "")
        if not found or self._dur <= 0:
            return []
        return [{"title": one["title"], "start": one["start"],
                 "at": max(0.0, min(1.0, one["start"] / self._dur))}
                for one in found if one["start"] < self._dur]

    def _chapter_at(self, seconds: float) -> str:
        found = self._chapters.get(self._current().get("key") or "")
        name = ""
        for one in found or ():
            if one["start"] <= seconds:
                name = one["title"]
            else:
                break
        return name

    def _get_current_chapter(self) -> str:
        return self._chapter_at(self._pos + 0.5)

    @Slot(float, result=str)
    def chapterAt(self, along: float) -> str:
        """The chapter at that fraction of the video, for the pointer over
        the bar."""
        return self._chapter_at(max(0.0, min(1.0, along)) * self._dur)

    def _get_facts(self) -> dict:
        return dict(self._facts.get(self._current().get("key") or "", {}))

    def _get_ceiling(self) -> int:
        return self._height()

    def _known(self) -> dict:
        return self._extras.get(self._current().get("key") or "", {})

    def _auto_height(self) -> int:
        return ceiling_for(self._screen_height) if self._screen_height else FALLBACK_HEIGHT

    def _playing(self) -> tuple[int, bool]:
        """The height the one playing was fetched at, or 0 before that is
        known, and whether it is in Premium quality."""
        fetched = f"{self._current().get('key') or ''}@{self._under}"
        return int(self._fetched.get(fetched) or 0), fetched in self._premium

    def _playing_height(self) -> int:
        return self._playing()[0]

    def _get_qualities(self) -> list:
        """The menu of heights: Auto first, then every height this video is
        offered at, or the usual steps for one not fetched yet. The one picked
        is chosen, and Auto says in brackets what it plays, the way YouTube's
        own menu does. A height picked that this video does not have is listed
        anyway, to carry its tick, and the height it came back at instead is
        the one marked as playing."""
        known = self._known()
        offered = list(known.get("heights") or [
            step for step in reversed(VIDEO_HEIGHT_STEPS) if step >= 480])
        premium = set(known.get("premium_heights") or ())
        if self._quality and self._quality not in offered:
            offered = sorted([*offered, self._quality], reverse=True)
        playing, in_premium = self._playing()
        auto = "Auto"
        if not self._quality and playing:
            auto = f"Auto ({quality_label(playing, in_premium)})"
        out = [{"height": 0, "label": auto, "chosen": self._quality == 0, "playing": False}]
        out += [{"height": height, "label": quality_label(height, height in premium),
                 "chosen": self._quality == height,
                 "playing": bool(self._quality) and height == playing != self._quality}
                for height in offered]
        return out

    def _get_quality_text(self) -> str:
        """The button: what is picked, and what it plays once that is known,
        in brackets where the two differ."""
        height, premium = self._playing()
        playing = quality_label(height, premium) if height else ""
        if not self._quality:
            return f"Auto ({playing})" if playing else "Auto"
        if not height or height == self._quality:
            return playing or quality_label(self._quality)
        return f"{quality_label(self._quality)} ({playing})"

    def _tracks(self) -> list:
        return list(self._known().get("captions") or [])

    def _get_captions(self) -> list:
        return [{"label": one["name"] + (" (auto)" if one["auto"] else ""),
                 "chosen": one["url"] == self._caption_shown}
                for one in self._tracks()]

    def _get_storyboard(self) -> dict:
        return dict(self._known().get("storyboard") or {})

    def _usable(self) -> list:
        """The segments of the one playing that are acted on: ones marked on
        the video as it is now, of a kind not left alone."""
        if not self._sponsor_on:
            return []
        found = self._segments.get(self._current().get("key") or "") or ()
        return [one for one in found if sponsorblock.fits(one, self._dur)
                and self._sponsor_actions.get(one.category) != sponsorblock.IGNORE]

    def _get_segments(self) -> list:
        if self._dur <= 0:
            return []
        return [{"at": max(0.0, one.start / self._dur), "to": min(1.0, one.end / self._dur),
                 "start": max(0.0, one.start), "end": min(self._dur, one.end),
                 "colour": sponsorblock.BY_KEY[one.category].colour,
                 "label": sponsorblock.BY_KEY[one.category].label}
                for one in self._usable()]

    def _get_segment_button(self) -> str:
        if self._here is None:
            return ""
        return "Skip " + sponsorblock.BY_KEY[self._here.category].short

    def _get_skip_notice(self) -> str:
        if self._skipped is None:
            return ""
        return "Skipped " + sponsorblock.BY_KEY[self._skipped.category].short

    def _get_sponsor_categories(self) -> list:
        return [{"key": one.key, "label": one.label, "colour": one.colour,
                 "action": self._sponsor_actions[one.key]}
                for one in sponsorblock.CATEGORIES]

    track = Property("QVariantMap", _get_track, notify=trackChanged)
    playing = Property(bool, _get_playing, notify=stateChanged)
    loading = Property(bool, _get_loading, notify=stateChanged)
    hasQueue = Property(bool, _get_has_queue, notify=queueChanged)
    isLive = Property(bool, _get_is_live, notify=trackChanged)
    holdingFast = Property(bool, lambda self: self._held_fast, notify=stateChanged)
    position = Property(float, _get_position, notify=progressChanged)
    seconds = Property(float, _get_seconds, notify=progressChanged)
    length = Property(int, _get_length, notify=progressChanged)
    volume = Property(int, _get_volume, notify=stateChanged)
    speed = Property(float, _get_speed, notify=stateChanged)
    ended = Property(bool, _get_ended, notify=stateChanged)
    videoShowing = Property(bool, _get_showing, notify=videoChanged)
    queue = Property("QVariantList", _get_queue, notify=queueChanged)
    queueIndex = Property(int, _get_queue_index, notify=queueChanged)
    chapters = Property("QVariantList", _get_chapters, notify=progressChanged)
    currentChapter = Property(str, _get_current_chapter, notify=progressChanged)
    trackFacts = Property("QVariantMap", _get_facts, notify=factsChanged)
    ceiling = Property(int, _get_ceiling, notify=stateChanged)
    qualities = Property("QVariantList", _get_qualities, notify=extrasChanged)
    qualityText = Property(str, _get_quality_text, notify=extrasChanged)
    quality = Property(int, lambda self: self._quality, notify=extrasChanged)
    autoHeight = Property(int, _auto_height, notify=extrasChanged)
    captions = Property("QVariantList", _get_captions, notify=extrasChanged)
    captionShowing = Property(bool, lambda self: bool(self._caption_shown),
                              notify=extrasChanged)
    captionsOn = Property(bool, lambda self: self._captions_on, notify=extrasChanged)
    storyboard = Property("QVariantMap", _get_storyboard, notify=extrasChanged)
    speeds = Property("QVariantList", lambda _self: list(SPEEDS), constant=True)
    segments = Property("QVariantList", _get_segments, notify=sponsorChanged)
    segmentButton = Property(str, _get_segment_button, notify=sponsorChanged)
    skipNotice = Property(str, _get_skip_notice, notify=sponsorChanged)
    sponsorOn = Property(bool, lambda self: self._sponsor_on, notify=sponsorChanged)
    buffered = Property("QVariantList", _get_buffered, notify=bufferChanged)
    behindLive = Property(int, _get_behind, notify=behindChanged)
    cornerWidth = Property(int, lambda self: self._corner_width, notify=cornerChanged)
    sponsorCategories = Property("QVariantList", _get_sponsor_categories,
                                 notify=sponsorChanged)

    # ---- the queue -------------------------------------------------------

    def play_now(self, item: dict, at_s: float | None = None) -> None:
        """Play this at once. With something already playing it goes in
        straight after that and plays, and what was playing stays above it as
        played; it is not played again."""
        entry = dict(item)
        if at_s is not None:
            entry["start_s"] = float(at_s)
        if not self._queue:
            self._queue = [entry]
            self._at = 0
        else:
            self._keep_position()
            place = self._at + 1 if self._at >= 0 else len(self._queue)
            self._queue.insert(place, entry)
            self._at = place
        self.queueChanged.emit()
        self._start_current()

    def play_list(self, items: list[dict], at_s: float | None = None) -> None:
        """Play the first of these at once and queue the rest straight after
        it, the way a playlist pressed in the middle is handed over."""
        if not items:
            return
        self.play_now(items[0], at_s)
        for offset, item in enumerate(items[1:], start=1):
            self._queue.insert(self._at + offset, dict(item))
        self.queueChanged.emit()

    def add_item(self, item: dict, play_next: bool = False) -> None:
        """Into the queue, after the one playing or at the end. With nothing
        there at all it plays, which is the only sensible reading of adding the
        first one."""
        if not self._queue:
            self.play_now(item)
            return
        place = self._at + 1 if play_next and self._at >= 0 else len(self._queue)
        self._queue.insert(place, dict(item))
        self.queueChanged.emit()
        if self._ended and place == self._at + 1:
            # The last one had finished and was sitting on its last frame; what
            # was added is what comes next, so it comes now.
            self.next()

    @Slot(int)
    def jumpTo(self, index: int) -> None:
        if 0 <= index < len(self._queue) and index != self._at:
            self._keep_position()
            self._at = index
            self.queueChanged.emit()
            self._start_current()

    @Slot(int)
    def removeFromQueue(self, index: int) -> None:
        if not 0 <= index < len(self._queue):
            return
        if index == self._at:
            if index + 1 < len(self._queue):
                del self._queue[index]
                self.queueChanged.emit()
                self._start_current()
            else:
                self.stop()
            return
        del self._queue[index]
        if index < self._at:
            self._at -= 1
        self.queueChanged.emit()

    @Slot(int, int)
    def moveInQueue(self, from_place: int, to_place: int) -> None:
        if not (0 <= from_place < len(self._queue)):
            return
        to_place = max(0, min(len(self._queue), int(to_place)))
        if to_place in (from_place, from_place + 1):
            return
        entry = self._queue.pop(from_place)
        if to_place > from_place:
            to_place -= 1
        self._queue.insert(to_place, entry)
        if self._at == from_place:
            self._at = to_place
        elif from_place < self._at <= to_place:
            self._at -= 1
        elif to_place <= self._at < from_place:
            self._at += 1
        self.queueChanged.emit()

    @Slot()
    def clearQueue(self) -> None:
        """Everything but the one playing."""
        if self._at < 0 or not self._queue:
            return
        self._queue = [self._queue[self._at]]
        self._at = 0
        self.queueChanged.emit()

    @Slot()
    def next(self) -> None:
        if self._at + 1 < len(self._queue):
            self._keep_position()
            self._at += 1
            self.queueChanged.emit()
            self._start_current()

    @Slot()
    def previous(self) -> None:
        if self._at > 0:
            self._keep_position()
            self._at -= 1
            self.queueChanged.emit()
            self._start_current()

    @Slot()
    def stop(self) -> None:
        """Stop for good: where it was is kept, the queue goes."""
        self._keep_position()
        self._stop_finder()
        self._engine.stop()
        had = bool(self._queue)
        self._queue = []
        self._at = -1
        self._pos = self._dur = 0.0
        self._ended = False
        self._paused = True
        self._finding = False
        self._forget_live()
        self._look_at_buffer()
        self.queueChanged.emit()
        self.trackChanged.emit()
        self.stateChanged.emit()
        self.progressChanged.emit()
        if had:
            self.stopped.emit()

    # ---- playing ---------------------------------------------------------

    def _height(self) -> int:
        """The ceiling a video is fetched under: the height picked, or else
        what the screen can show."""
        return self._quality or self._auto_height()

    @Slot(int)
    def setScreenHeight(self, pixels: int) -> None:
        """How tall the screen the window is on is, in its real pixels, as
        ScreenWatch measures it. Auto never fetches the picture taller than
        that."""
        pixels = int(pixels)
        if pixels > 0 and pixels != self._screen_height:
            self._screen_height = pixels
            self.stateChanged.emit()
            self.extrasChanged.emit()

    def _start_current(self, again: bool = False) -> None:
        """Find the one in the queue's place and play it. Again is the same
        video fetched once more at another height: where it was, whether it
        was watched and the page about it all stay as they are."""
        entry = self._current()
        if not entry:
            return
        self._stop_finder()
        self._ended = False
        self._caption_shown = ""
        if not again:
            self._pos = 0.0
            self._dur = 0.0
            self._counted = ""
            self._saved_at = 0.0
            self._let_play.clear()
            self._skipping = ("", 0.0)
            self._here = None
            self._drop_notice()
            self._ask_segments(entry)
        key = entry.get("key", "")
        height = self._height()
        self._under = height
        self._finding = True
        if not again:
            self.trackChanged.emit()
        self.stateChanged.emit()
        self.progressChanged.emit()
        self.extrasChanged.emit()
        cached = self._addresses.get(f"{key}@{height}")
        if cached:
            picture, _, sound = cached.partition(" ")
            self._hand_over(entry, picture, sound)
            return
        finder = _Finder(self._cfg, key, entry.get("url", ""), height,
                         bool(entry.get("live")), self, login=str(entry.get("login") or ""))
        finder.found.connect(self._on_found)
        finder.failed.connect(self._on_failed)
        finder.gone.connect(self._on_gone)
        finder.finished.connect(self._sweep_finders)
        self._finder = finder
        self._finders.append(finder)
        trace.mark("video_finding", key=key, height=height)
        finder.start()

    def _on_found(self, key: str, picture: str, sound: str, chapters: list,
                  facts: dict, extras: dict | None = None) -> None:
        if chapters:
            self._chapters[key] = tuple(chapters)
        if extras:
            extras = dict(extras)
            asked = extras.pop("asked", None)
            premium = bool(extras.pop("premium", False))
            if asked and extras.get("height"):
                self._fetched[f"{key}@{asked}"] = int(extras["height"])
                if premium:
                    self._premium.add(f"{key}@{asked}")
                else:
                    self._premium.discard(f"{key}@{asked}")
            self._extras[key] = extras
        if facts:
            self._facts[key] = dict(facts)
            if key == self._current().get("key"):
                self.factsChanged.emit()
        entry = self._current()
        if entry.get("key") != key:
            return
        if not entry.get("live"):
            # A broadcast's address is a moving window and not worth keeping.
            self._addresses.put(f"{key}@{self._height()}", f"{picture} {sound}".strip())
        self._hand_over(entry, picture, sound)

    def _hand_over(self, entry: dict, picture: str, sound: str) -> None:
        self._finding = False
        start = entry.pop("start_s", None)
        if entry.pop("go_on", False):
            start = self._pos
        if start is None and not entry.get("live"):
            start = self._resume_point(entry.get("key", ""))
        # Fetched again at another height while paused, it stays paused.
        paused = bool(entry.pop("hold_pause", False))
        caption = (choose_caption(self._tracks(), self._caption_language)
                   if self._captions_on else None)
        self._caption_shown = caption["url"] if caption else ""
        self._paused = paused
        self._engine.set_video(True)
        if sound:
            self._engine.load(sound, start, video=picture, subtitle=self._caption_shown)
        else:
            self._engine.load(picture, start, subtitle=self._caption_shown)
        self._engine.set_pause(paused)
        # A broadcast plays at its own pace, whatever the last video was
        # played at: faster, it would run into its present and stall there.
        self._engine.set_speed(1.0 if entry.get("live")
                               else HOLD_SPEED if self._held_fast else self._speed)
        self._forget_live()
        if entry.get("live"):
            self._live_watch.start()
        self._buffered = ()
        self.bufferChanged.emit()
        self._buffer_watch.start()
        self.stateChanged.emit()
        self.extrasChanged.emit()

    def _resume_point(self, key: str) -> float | None:
        if self._db is None or not key:
            return None
        found = self._db.video_position(key)
        if not found:
            return None
        seconds, length = found
        if seconds < RESUME_FROM_S:
            return None
        if length > 0 and seconds / length >= self._threshold:
            return None
        return seconds

    def _on_failed(self, key: str, said: str) -> None:
        if key != self._current().get("key"):
            return
        self._finding = False
        self.stateChanged.emit()
        self.failed.emit(said)

    def _on_gone(self, key: str) -> None:
        if key != self._current().get("key"):
            return
        self._finding = False
        self.stateChanged.emit()
        self.gone.emit(key)

    def _stop_finder(self) -> None:
        if self._finder is not None:
            self._finder.cancel()
            self._finder = None

    def _sweep_finders(self) -> None:
        self._finders = [one for one in self._finders if one.isRunning()]

    # ---- what the engine reports -----------------------------------------

    def _on_started(self, role: str) -> None:
        if role != CURRENT:
            return
        # Whatever was reported before belonged to the file before.
        self._live_since = None
        entry = self._current()
        if entry and self._quiet == entry.get("key"):
            self._quiet = ""
            return
        if entry:
            trace.mark("video_started", key=entry.get("key", ""))
            self.started.emit(entry.get("key", ""))

    def _on_position(self, seconds: float) -> None:
        self._pos = float(seconds)
        if self._live_since is None and self._get_is_live():
            self._live_since = (time.monotonic(), self._pos)
        self._count_watched()
        self.progressChanged.emit()
        self._check_segments()

    def _on_duration(self, seconds: float) -> None:
        self._dur = float(seconds or 0.0)
        self.progressChanged.emit()
        # Whether a segment fits is weighed against the length.
        self.sponsorChanged.emit()

    def _on_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if self._paused:
            self._keep_position()
        self.stateChanged.emit()

    def _on_idle(self, idle: bool) -> None:
        self._idle = bool(idle)
        self.stateChanged.emit()

    def _on_buffering(self, buffering: bool) -> None:
        self._buffering = bool(buffering)
        self.stateChanged.emit()

    def _on_video(self, showing: bool) -> None:
        self._showing = bool(showing)
        self.videoChanged.emit()

    def _on_engine_gone(self, why: str) -> None:
        self._finding = False
        self.stateChanged.emit()
        self.failed.emit(why)

    def _on_eof(self, reached: bool) -> None:
        if not reached or not self._current():
            return
        entry = self._current()
        key = entry.get("key", "")
        if not entry.get("live"):
            if self._counted != key:
                self._counted = key
                self.watched.emit(key, 1.0)
            if self._db is not None:
                self._db.forget_video_position(key)
        if self._at + 1 < len(self._queue):
            self._at += 1
            self.queueChanged.emit()
            self._start_current()
            return
        # The queue has run out. The last frame stays, and nothing else plays.
        self._ended = True
        self.stateChanged.emit()
        self.stopped.emit()

    def _count_watched(self) -> None:
        """Watched once this much of it has played, the same share mpv uses,
        and only once per play. A broadcast is never watched."""
        entry = self._current()
        key = entry.get("key", "")
        if not key or entry.get("live") or self._counted == key or self._dur <= 0:
            return
        progress = self._pos / self._dur
        if progress >= self._threshold:
            self._counted = key
            self.watched.emit(key, round(progress, 3))

    def _keep_position(self) -> None:
        """Write down where the one playing is, unless that is nowhere worth
        coming back to."""
        entry = self._current()
        key = entry.get("key", "")
        if self._db is None or not key or entry.get("live") or self._dur <= 0:
            return
        if abs(self._pos - self._saved_at) < 1.0 and self._saved_at:
            return
        self._saved_at = self._pos
        if self._pos / self._dur >= self._threshold:
            self._db.forget_video_position(key)
        elif self._pos >= RESUME_FROM_S:
            self._db.set_video_position(key, self._pos, self._dur)

    # ---- the controls ----------------------------------------------------

    @Slot()
    def toggle(self) -> None:
        if not self._current():
            return
        if self._ended:
            self.replay()
            return
        if self._idle and not self._finding:
            self._start_current()
            return
        self.setPaused(not self._paused)

    @Slot(bool, result=bool)
    def holdFast(self, held: bool) -> bool:
        """Twice as fast for as long as the picture is held down, then back to
        the speed picked, and paused again if it was. A broadcast plays at its
        own pace, and a video still on its way or come to its end has nothing
        to hurry, so those are left alone. Says whether the hold took."""
        held = bool(held)
        if held == self._held_fast:
            return held
        if held:
            if not self._current() or self._get_is_live() or self._ended or self._finding:
                return False
            self._held_fast = True
            self._held_from_pause = self._paused
            self._engine.set_speed(HOLD_SPEED)
            if self._paused:
                self.setPaused(False)
        else:
            self._held_fast = False
            self._engine.set_speed(self._speed)
            if self._held_from_pause and not self._paused:
                self.setPaused(True)
        self.stateChanged.emit()
        return True

    @Slot(bool)
    def setPaused(self, paused: bool) -> None:
        if not self._current():
            return
        self._paused = bool(paused)
        self._engine.set_pause(self._paused)
        if self._paused:
            self._keep_position()
        self.stateChanged.emit()

    # ---- a broadcast's present ---------------------------------------------

    def _forget_live(self) -> None:
        self._live_since = None
        was = self._get_behind()
        self._behind = 0.0
        self._live_watch.stop()
        if was:
            self.behindChanged.emit()

    def _behind_now(self) -> float:
        """The wall clock since the mark less what has played since, which a
        jump of the broadcast's own clock can make less than nothing."""
        if self._live_since is None:
            return 0.0
        since, at = self._live_since
        return (time.monotonic() - since) - (self._pos - at)

    def _look_at_live(self) -> None:
        """How far behind its present the broadcast is now."""
        if not self._get_is_live() or self._ended:
            self._forget_live()
            return
        if self._live_since is None:
            return
        behind = self._behind_now()
        moving = not self._paused and not self._buffering and not self._idle
        if moving and abs(behind - self._behind) > LIVE_JUMP_S:
            # Playing, nothing is lost but the time passing. What jumped is the
            # broadcast's own clock, so the mark is moved with it.
            since, at = self._live_since
            self._live_since = (since, at - (behind - self._behind))
            behind = self._behind
        was = self._get_behind()
        self._behind = max(0.0, behind)
        if self._get_behind() != was:
            self.behindChanged.emit()

    def _spans(self) -> list[tuple[float, float]]:
        reader = getattr(self._engine, "cached_ranges", None)
        return list(reader()) if reader is not None else []

    @Slot()
    def goLive(self) -> None:
        """Back to the broadcast's present: a seek to the newest moment held
        when what was fetched while it was paused reaches that far, else the
        broadcast opened afresh."""
        entry = self._current()
        if not entry or not entry.get("live") or self._finding or self._ended:
            return
        behind = self._behind_now()
        spans = self._spans()
        newest = spans[-1][1] if spans else 0.0
        self._paused = False
        if (newest - LIVE_EDGE_MARGIN_S > self._pos
                and newest - self._pos >= behind - LIVE_REACH_SLACK_S):
            trace.mark("live_caught_up", by="seek", behind=round(behind, 1))
            self._engine.seek(newest - LIVE_EDGE_MARGIN_S)
            self._engine.set_pause(False)
            self._live_since = None
            self._behind = 0.0
            self.behindChanged.emit()
            self.stateChanged.emit()
            return
        trace.mark("live_caught_up", by="opening again", behind=round(behind, 1))
        self._fetch_again()

    # ---- what the bar shows fetched ----------------------------------------

    def _look_at_buffer(self) -> None:
        entry = self._current()
        spans: tuple[tuple[float, float], ...] = ()
        if entry and not entry.get("live") and self._dur > 0 and not self._idle:
            length = self._dur
            spans = tuple((round(max(0.0, start) / length, 3), round(min(length, end) / length, 3))
                          for start, end in self._spans() if end > start)
        elif not entry:
            self._buffer_watch.stop()
        if spans != self._buffered:
            self._buffered = spans
            self.bufferChanged.emit()

    @Slot()
    def replay(self) -> None:
        if not self._current():
            return
        self._ended = False
        if self._get_is_live():
            # A broadcast that ran out has nothing to go back to. Asked for
            # again, it is either on air once more or says it is not.
            self._start_current()
            return
        self._engine.seek(0.0)
        self._engine.set_pause(False)
        self._paused = False
        self.stateChanged.emit()

    @Slot(float)
    def seek(self, fraction: float) -> None:
        if self._dur > 0 and not self._get_is_live():
            self.seekTo(max(0.0, min(1.0, float(fraction))) * self._dur)

    @Slot(float)
    def seekTo(self, seconds: float) -> None:
        if not self._current() or self._get_is_live():
            return
        seconds = max(0.0, float(seconds))
        if self._dur > 0:
            seconds = min(seconds, max(0.0, self._dur - 0.5))
        if self._ended:
            self._ended = False
            self._engine.set_pause(False)
            self._paused = False
        self._engine.seek(seconds)
        self._pos = seconds
        self.progressChanged.emit()
        self.stateChanged.emit()

    @Slot(int)
    def nudgeSeek(self, steps: int) -> None:
        self.seekTo(self._pos + int(steps) * SEEK_STEP_S)

    @Slot(int)
    def setVolume(self, value: int) -> None:
        self._volume = max(0, min(100, int(value)))
        self._engine.set_volume(self._volume)
        if self._db is not None:
            self._db.set_state("video_volume", str(self._volume))
        self.stateChanged.emit()

    @Slot(int)
    def setCornerWidth(self, width: int) -> None:
        """How wide the picture in the corner of the window was made, kept
        for the next time."""
        width = max(CORNER_WIDTH_LEAST, int(width))
        if width == self._corner_width:
            return
        self._corner_width = width
        if self._db is not None:
            self._db.set_state("video_corner_width", str(width))
        self.cornerChanged.emit()

    @Slot(int)
    def nudgeVolume(self, steps: int) -> None:
        self.setVolume(self._volume + int(steps) * VOLUME_STEP)

    @Slot()
    def toggleMute(self) -> None:
        """Silence, and the level it had back again."""
        if self._volume > 0:
            self._unmuted = self._volume
            self.setVolume(0)
        else:
            self.setVolume(self._unmuted or VOLUME_DEFAULT)

    @Slot(float)
    def setSpeed(self, speed: float) -> None:
        self._speed = max(0.25, min(4.0, float(speed)))
        self._engine.set_speed(self._speed)
        self.stateChanged.emit()

    # ---- the menus on the picture ----------------------------------------

    @Slot(int)
    def setQuality(self, height: int) -> None:
        """A height to fetch every video at from now on, or 0 for Auto. It
        holds until Auto is picked again, and the one playing is fetched again
        at once if that changes what it plays at."""
        height = max(0, int(height))
        if height == self._quality:
            return
        self._quality = height
        if self._db is not None:
            self._db.set_state(QUALITY_STATE, str(height) if height else "auto")
        self.extrasChanged.emit()
        # Weighed against the ceiling the one playing was fetched under, not
        # the one in force before the pick: Auto's moves with the screen the
        # window is on, and nothing is fetched again when it does.
        if self._height() != self._under and self._would_change():
            self._fetch_again()

    def _would_change(self) -> bool:
        """Whether the ceiling now in force picks another height than the one
        playing. The same video offered no taller than either ceiling would
        only be fetched again to come back the same."""
        playing = self._playing_height()
        offered = self._known().get("heights") or []
        if not playing or not offered:
            return True
        ceiling = self._height()
        fitting = [height for height in offered if height <= ceiling]
        return (max(fitting) if fitting else min(offered)) != playing

    def _fetch_again(self) -> None:
        """The one playing, from where it is, fetched under the new ceiling."""
        entry = self._current()
        if not entry or self._ended:
            return
        if not self._finding:
            # Where it is when the new address is handed over, not now: the
            # old one plays on for the seconds the finding takes.
            entry["go_on"] = not entry.get("live")
            entry["hold_pause"] = self._paused
            self._keep_position()
            self._quiet = entry.get("key", "")
        self._start_current(again=True)

    @Slot(int)
    def setCaption(self, index: int) -> None:
        """A caption picked from the menu, or Off with any other number. The
        language picked is remembered for the next video, and on stays on
        until Off is picked."""
        tracks = self._tracks()
        track = tracks[index] if 0 <= index < len(tracks) else None
        self._captions_on = track is not None
        if track is not None:
            self._caption_language = track["code"]
        if self._db is not None:
            self._db.set_state(CAPTIONS_STATE, "on" if self._captions_on else "off")
            if track is not None:
                self._db.set_state(CAPTION_LANGUAGE_STATE, track["code"])
        self._show_caption(track)

    @Slot(bool)
    def setCaptionsOn(self, on: bool) -> None:
        """On or off from the settings, in the language picked last."""
        self._captions_on = bool(on)
        if self._db is not None:
            self._db.set_state(CAPTIONS_STATE, "on" if self._captions_on else "off")
        self._show_caption(choose_caption(self._tracks(), self._caption_language)
                           if self._captions_on else None)

    def _show_caption(self, track: dict | None) -> None:
        url = track["url"] if track else ""
        # While a video is still being found there is no file to show it on,
        # and the hand over picks it up.
        if url != self._caption_shown and not self._finding and not self._idle:
            self._caption_shown = url
            if track is not None:
                self._engine.show_subtitle(url, track["name"], track["code"])
            else:
                self._engine.show_subtitle("")
        self.extrasChanged.emit()

    # ---- SponsorBlock -------------------------------------------------------

    def _ask_segments(self, entry: dict) -> None:
        """Ask about a video as it starts, once a session, while SponsorBlock
        is on. Only a YouTube video that is not a broadcast has any."""
        key = str(entry.get("key") or "")
        if (not self._sponsor_on or entry.get("live") or not key.startswith("yt:")
                or key in self._segments or self._db is None
                or any(one.key == key and one.isRunning() for one in self._segment_finders)):
            return
        finder = _SegmentFinder(self._db, self._cfg, key, key.split(":", 1)[1], self)
        finder.found.connect(self._on_segments)
        finder.finished.connect(self._sweep_segment_finders)
        self._segment_finders.append(finder)
        finder.start()

    def _sweep_segment_finders(self) -> None:
        self._segment_finders = [one for one in self._segment_finders if one.isRunning()]

    def _on_segments(self, key: str, found: list) -> None:
        self._segments[key] = tuple(found)
        trace.mark("sponsorblock_found", key=key, segments=len(found))
        if key == self._current().get("key"):
            self.sponsorChanged.emit()
            self._check_segments()

    def _check_segments(self) -> None:
        """Skip a segment the position is in when its kind is skipped, or
        offer the button for one whose kind is offered."""
        here = None
        if not (self._finding or self._ended or self._idle):
            for one in self._usable():
                if not one.start <= self._pos < one.end - SEGMENT_TAIL_S:
                    continue
                action = self._sponsor_actions.get(one.category)
                if action == sponsorblock.SKIP and one.uuid not in self._let_play:
                    uuid, when = self._skipping
                    # The seek is under way, and a report from before it landed
                    # is still inside.
                    if uuid != one.uuid or time.monotonic() - when > 1.5:
                        self._skip(one, by_hand=False)
                    return
                if action == sponsorblock.BUTTON and here is None:
                    here = one
        if here != self._here:
            self._here = here
            self.sponsorChanged.emit()

    def _skip(self, segment: sponsorblock.Segment, by_hand: bool) -> None:
        self._skipping = (segment.uuid, time.monotonic())
        trace.mark("segment_skipped", key=self._current().get("key", ""),
                   category=segment.category, start=segment.start, end=segment.end,
                   by_hand=by_hand)
        self._here = None
        if not by_hand:
            self._skipped = segment
            self._notice.start()
        self.seekTo(segment.end)
        self.sponsorChanged.emit()

    def _drop_notice(self) -> None:
        self._notice.stop()
        if self._skipped is not None:
            self._skipped = None
            self.sponsorChanged.emit()

    @Slot()
    def skipSegment(self) -> None:
        """The button: past the segment the position is in."""
        if self._here is not None:
            self._skip(self._here, by_hand=True)

    @Slot()
    def undoSkip(self) -> None:
        """Back to the start of what was just skipped, and let it play."""
        segment = self._skipped
        if segment is None:
            return
        self._let_play.add(segment.uuid)
        self._drop_notice()
        self.seekTo(segment.start)

    @Slot(float, result=str)
    def segmentAt(self, along: float) -> str:
        """What kind of segment that fraction of the video is in, for the
        pointer over the bar."""
        at = max(0.0, min(1.0, float(along))) * self._dur
        found = next((one for one in self._usable() if one.start <= at < one.end), None)
        return sponsorblock.BY_KEY[found.category].label if found is not None else ""

    @Slot(bool)
    def setSponsorBlock(self, on: bool) -> None:
        self._sponsor_on = bool(on)
        if self._db is not None:
            self._db.set_state(SPONSOR_STATE, "on" if self._sponsor_on else "off")
        if self._sponsor_on and self._current():
            self._ask_segments(self._current())
        if not self._sponsor_on:
            self._here = None
            self._drop_notice()
        self.sponsorChanged.emit()
        self._check_segments()

    @Slot(str, str)
    def setSegmentAction(self, category: str, action: str) -> None:
        if category not in sponsorblock.BY_KEY or action not in sponsorblock.ACTIONS:
            return
        self._sponsor_actions[category] = action
        if self._db is not None:
            self._db.set_state(SPONSOR_ACTION_STATE.format(category), action)
        self.sponsorChanged.emit()
        self._check_segments()

    @Slot(float)
    def setCaptionLift(self, share: float) -> None:
        """How much of the picture's height a caption keeps clear of at its
        foot, which is the controls while they are up."""
        place = round(100 - 100 * max(0.0, min(0.5, float(share))))
        if place != self._caption_place:
            self._caption_place = place
            self._engine.set_subtitle_place(place)

    @Slot(float, result="QVariantMap")
    def previewAt(self, along: float) -> dict:
        """The frame of the storyboard at that fraction of the video: which
        sheet, and the column and row of it."""
        board = self._known().get("storyboard")
        if not board or self._dur <= 0:
            return {}
        each = board["columns"] * board["rows"]
        sheets = board["sheets"]
        frame = int(max(0.0, min(1.0, float(along))) * self._dur * board["fps"])
        frame = max(0, min(frame, len(sheets) * each - 1))
        sheet, cell = divmod(frame, each)
        return {"sheet": sheets[sheet], "column": cell % board["columns"],
                "row": cell // board["columns"]}

    def shutdown(self) -> None:
        self._keep_position()
        self._keeper.stop()
        self._notice.stop()
        running = [*self._finders, *self._segment_finders]
        for finder in running:
            if finder.isRunning():
                finder.cancel()
        for finder in running:
            if finder.isRunning():
                finder.wait(5000)
        self._engine.quit()
