"""Music played inside Weave rather than in a window of its own.

Video goes to mpv because that is the whole point of the application. Audio
goes to mpv too, but to a second one with no window that Weave starts, controls
over its socket and closes with itself (`engine.py`). Nothing is downloaded:
yt-dlp resolves a stream address, which reaches the same Premium quality the
rest of the setup gets, and mpv reads it. A live stream has no audio only form
at all, so one of its muxed variants is played with no video output and the
picture is simply never decoded.

This module owns what mpv does not: the queue and its order, shuffle and
repeat, the fades, the volume that is remembered, and the addresses. The
address for the track after this one is resolved as soon as this one starts,
because resolving takes a few seconds and is the only wait there is. mpv is
handed that track before it is needed, opens it while the current one is still
playing, and moves on with no gap.
"""

from __future__ import annotations

import calendar
import json
import random
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QObject,
    QThread,
    QTimer,
    QVariantAnimation,
    Signal,
    Slot,
)

from .config import Config
from .cookies import args as cookie_args
from .sources.ytdlp import challenge_trouble, explain, prepare
from .engine_libmpv import CURRENT, NEXT, LibmpvEngine
from . import trace
from .imagecache import plain_source
from .process import Cancelled, Timeout
from .process import run as run_process

# A live stream is only offered as picture and sound together, and the sound
# gets better as the picture does. This variant is the sensible middle.
LIVE_FORMAT = "93"
MUSIC_FORMAT = "bestaudio"

# The picture, when one is asked for. Capped rather than best: a music video at
# its largest is several times the bytes for a pane a few hundred pixels wide,
# and vp9 at this height measured 29 MiB against 77 for the same thing in avc1.
VIDEO_HEIGHT = 1080

# What the settings page offers as that cap. A ceiling and not a demand: the
# best shape at or under it is taken, so a video offered only smaller is shown
# at whatever it has rather than refused.
VIDEO_HEIGHT_STEPS: tuple[int, ...] = (360, 480, 720, 1080, 1440, 2160)


def video_format(height: int = VIDEO_HEIGHT) -> str:
    """What to ask yt-dlp for, capped at a height.

    The fallbacks are there because not every video is offered in every shape:
    vp9 at the ceiling, then anything at the ceiling, then whatever there is.
    """
    height = int(height)
    return (f"bestvideo[height<={height}][vcodec^=vp9]/"
            f"bestvideo[height<={height}]/bestvideo")


def height_label(height: int) -> str:
    """A ceiling as it is offered on the settings page and reported back."""
    return f"{int(height)}p"

# Past this a video is not worth fetching. A long mix or a talk played as music
# is an hour of pictures nobody looks at, and the artwork says as much.
VIDEO_MAX_S = 15 * 60

# Long enough to hear as a fade rather than a cut, short enough not to be a
# wait before the video starts.
FADE_MS = 500

# How long a song has to be heard before it counts as listened to, which is
# what is said to the music service when that is switched on. Close to how
# YouTube itself counts a play, and long enough that a song skipped past after
# a few seconds is never counted, since a skip is not a listen.
HEARD_S = 30.0

# The most one report of the position can move while it counts as listening.
# mpv reports it several times a second, so a longer step is a seek, and a
# seek forwards is not the song being heard.
HEARD_STEP_S = 2.0

# Pausing and carrying on, pressed by hand. Half the fade above, because here
# the press itself is the thing waited on, and at 500 ms the music was heard
# answering late. Still a fade and never a cut, which is what a stop in the
# middle of a note sounds like.
TOGGLE_FADE_MS = 250

# A signed address can stop being accepted, which is ordinary rather than
# exceptional over a long listen, so it is recovered from rather than
# reported. These bound that: a few goes at one track, not in a tight loop,
# and the count starts over once a track has been playing happily for a
# while, so an evening of occasional drops never runs out of goes.
RECOVER_LIMIT = 3
RECOVER_COOLDOWN_S = 2.0
RECOVER_WINDOW_S = 120.0

# mpv pauses itself when it runs out of data. Ordinary buffering comes back
# within a moment; a connection that has quietly died does not, and is treated
# as a dropped address.
STALL_GRACE_MS = 8000

# A signed address carries the moment it expires. One that is about to is not
# worth handing to the player.
ADDRESS_MARGIN_S = 600.0

# How far one turn of the wheel over the bar moves. Five seconds is what a
# player usually gives a wheel, far enough to be worth the gesture and short
# enough that a handful of turns lands where it was aimed.
SEEK_NOTCH_S = 5.0

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2

# What is being done about the picture, said plainly, for the line under the
# picture. These are the real steps and not a guess at them: an address has to
# be found, which is a full extraction and takes seconds, the player then has
# to open that stream, and only a couple of seconds after that does a frame
# exist to draw. Nothing is said while there is nothing to say, so a song with
# no picture coming carries no line at all.
STAGE_LOOKING = "Looking for the video"
STAGE_OPENING = "Opening the video"
STAGE_KEPT = "Opening the video kept on disk"
STAGE_SHOWING = "Showing the video"


@dataclass(frozen=True)
class Resolved:
    """What one resolve came back with. The address is the point of it; the
    chapters and the facts ride along in the same call and cost nothing."""

    address: str
    chapters: tuple[dict, ...] = ()
    facts: dict | None = None


# What is known about a song by the time it can be played, asked for in the
# same call as the address. Measured against the live endpoint: the resolve is
# a full extraction whatever is printed, so every one of these is free, and a
# listing cannot answer for any of them. A flat listing carries no like count
# at all and no date without an extractor argument.
FACT_FIELDS = ("view_count", "like_count", "comment_count", "channel",
               "channel_id", "channel_follower_count", "timestamp",
               "upload_date", "track", "artists", "album", "release_year",
               "categories", "description")
FACT_SPEC = "%(.{" + ",".join(FACT_FIELDS) + "})j"


def parse_facts(text: str) -> dict:
    """What yt-dlp said about the song, in the shape the page draws.

    Printed as one JSON object among the other lines of the same output, so
    the whole of it is looked at rather than a line counted off. Anything the
    extractor did not answer for is left out entirely rather than carried as a
    None the window would have to test for.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if not isinstance(found, dict):
            continue
        return _facts_from(found)
    return {}


def _facts_from(found: dict) -> dict:
    """One extraction turned into plain numbers and words."""
    out: dict = {}

    def number(name: str, into: str) -> None:
        value = found.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[into] = int(value)

    def words(name: str, into: str) -> None:
        value = found.get(name)
        if isinstance(value, str) and value.strip():
            out[into] = value.strip()

    number("view_count", "views")
    number("like_count", "likes")
    number("comment_count", "comments")
    number("channel_follower_count", "followers")
    number("release_year", "year")
    words("channel", "channel")
    # Not to show. It is how the picture of whoever made this is found among
    # the channels already known, which is where a song that is only a song
    # gets a face at all.
    words("channel_id", "channel_id")
    words("track", "track")
    words("album", "album")
    words("description", "description")

    # The moment it went up. An extraction carries the exact time; the date on
    # its own is the fallback, read as UTC because a date with no hour in it is
    # not a moment anywhere in particular.
    stamp = found.get("timestamp")
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        out["published_at"] = int(stamp)
    else:
        day = found.get("upload_date")
        if isinstance(day, str) and len(day) == 8 and day.isdigit():
            try:
                out["published_at"] = calendar.timegm(
                    time.strptime(day, "%Y%m%d"))
            except ValueError:
                pass

    # Several names for one song, and the first is the one it is filed under.
    artists = found.get("artists")
    if isinstance(artists, list):
        named = [str(one).strip() for one in artists if str(one).strip()]
        if named:
            out["artist"] = ", ".join(named)
    categories = found.get("categories")
    if isinstance(categories, list) and categories:
        first = str(categories[0]).strip()
        if first:
            out["category"] = first
    return out


def parse_chapters(text: str) -> tuple[dict, ...]:
    """The chapters yt-dlp printed, if the video has any.

    A video with none prints NA, and the address is another line of the same
    output, so the whole of it is looked at rather than a line counted off.
    Anything without a title or a start is dropped: a mark on the bar that
    cannot be named is worse than no mark.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if not isinstance(found, list):
            continue
        out = []
        for one in found:
            if not isinstance(one, dict):
                continue
            title = str(one.get("title") or "").strip()
            start = one.get("start_time")
            end = one.get("end_time")
            if not title or not isinstance(start, (int, float)):
                continue
            out.append({"title": title, "start": float(start),
                        "end": float(end) if isinstance(end, (int, float)) else 0.0})
        return tuple(out)
    return ()


def resolve_video(cfg: Config, url: str,
                  cancel: threading.Event | None = None,
                  height: int = VIDEO_HEIGHT) -> str:
    """The picture for one song, as its own stream.

    Asked for separately and only when a page is open to show it. Asking for
    both at once costs about twice as long, measured, and that wait would be
    paid by every press whether or not anybody was looking.
    """
    command = prepare(["yt-dlp", *cookie_args(cfg),
                       "-f", video_format(height), "--get-url", url])
    result = run_process(command, cancel=cancel, timeout=180)
    for line in result.stdout.splitlines():
        if line.startswith("http"):
            return line
    return ""


def nothing_to_play(cfg: Config, url: str,
                   cancel: threading.Event | None = None) -> bool:
    """Whether YouTube will not serve this video at all, ever.

    Asked only after a resolve has already failed, and worth the two and a
    half seconds it takes, because the answer decides whether the song is
    taken out of the lists holding it.

    It exists because the sentence a failed resolve comes back with is not
    enough to decide on. MEASURED against two real ones: asking for an address
    answers "Video unavailable" and nothing else, no reason and no second line,
    and a video blocked in this country opens with those same two words. Asking
    for the extraction instead answers in full, and both of those came back
    rc 0, availability "unlisted", a title, a channel, a length, an
    upload date, and ZERO formats. So they are not deleted at all. They exist,
    and YouTube offers nothing to play, which from here is the same thing and
    is the state worth acting on.

    Every way of being wrong about this is guarded, because being wrong means
    throwing away something that is still there:

    A run that did not finish answers no. Not being able to ask is not
    evidence. This is the one that matters most: a broken solver or a stale
    cookie makes every video in the library fail to resolve, and a rule that
    read that as every video being gone would empty a whole playlist.

    A run yt-dlp complained about the challenge on answers no, for the same
    reason: that is this machine's own trouble and not the video's.

    Behind a membership, upcoming, or on the air answers no. Each of those is
    a video that exists and has nothing to hand us right now.
    """
    command = prepare(["yt-dlp", "--no-warnings", "--simulate",
                       # Without this, no formats is itself an error and
                       # nothing is printed, which is the state being asked
                       # about.
                       "--ignore-no-formats-error",
                       *cookie_args(cfg),
                       "--print", "%(availability)s|%(live_status)s|%(format_id)s",
                       url])
    try:
        result = run_process(command, cancel=cancel, timeout=120)
    except (OSError, Timeout):
        return False
    line = next((row for row in result.stdout.splitlines() if row.strip()), "")
    if result.returncode != 0 or not line:
        return False
    if challenge_trouble(result.stderr or ""):
        return False
    parts = [part.strip() for part in line.split("|")]
    availability = parts[0] if parts else ""
    live_status = parts[1] if len(parts) > 1 else ""
    format_id = parts[2] if len(parts) > 2 else ""
    if availability == "subscriber_only":
        return False
    if live_status in ("is_upcoming", "is_live", "post_live"):
        return False
    return format_id in ("", "NA")


def resolve_address(cfg: Config, url: str, live: bool,
                    cancel: threading.Event | None = None) -> Resolved:
    """One entry to one playable address, blocking. Takes a few seconds.

    The chapters and the facts come back in the same call, which is the whole
    reason they are worth having: a video that is really an album has its
    tracks marked in the chapters, the views and the likes and the date are
    what the page says under the picture, and asking for any of it separately
    would be another few seconds per song. Measured: printing them costs
    nothing, because a resolve is a full extraction either way.
    """
    # Warnings are NOT suppressed here, deliberately. When YouTube's
    # challenge goes unsolved, yt-dlp says why in warnings and then fails
    # with an error that says nothing, "Requested format is not available",
    # so suppressing them on this command throws away the only account of
    # the cause there is. A test fails if the flag comes back.
    command = prepare(["yt-dlp", *cookie_args(cfg),
                       "-f", LIVE_FORMAT if live else MUSIC_FORMAT,
                       "--get-url", "--print", "%(chapters)j",
                       "--print", FACT_SPEC, url])
    result = run_process(command, cancel=cancel, timeout=180)
    for line in result.stdout.splitlines():
        if line.startswith("http"):
            return Resolved(line, parse_chapters(result.stdout),
                            parse_facts(result.stdout))
    raise _NoAddress(_why(result.stderr or ""))


def _why(stderr: str) -> str:
    """One sentence for a resolve that produced no address, composed from the
    last line yt-dlp wrote."""
    lines = stderr.strip().splitlines()
    return explain(lines[-1] if lines else "no stream came back", stderr)


def address_expiry(address: str) -> float | None:
    """When a signed googlevideo address stops working, as a unix time, or
    None when the address does not say."""
    stamp = parse_qs(urlparse(address).query).get("expire", [""])[0]
    return float(stamp) if stamp.isdigit() else None


# What yt-dlp says when the video itself is gone rather than when something
# went wrong on the way to it. Measured against two real ones:
# "Video unavailable. This video is not available". A private entry and one the
# uploader removed each say so in their own words.
GONE_MARKS = (
    "this video is not available",
    "private video",
    "removed by the uploader",
    "video has been removed",
    "video is no longer available",
    "account associated with this video has been terminated",
)

# And the one thing that vetoes all of it. A video Weave cannot play HERE is
# not a video that has gone: a country lock, a membership, an age gate and a
# login problem are about this copy of the application and not about the video,
# and taking one of those out of a playlist would throw away something that is
# still there. Only the country lock needs saying, because YouTube opens that
# sentence with the same two words as a deletion. The rest carry none of the
# marks above and are left out by simply not matching.
#
# "sign in" deliberately does NOT veto, and that was nearly the bug: read from
# yt-dlp's own source, a private video answers with the reason AND the
# subreason joined, so its sentence carries "Private video" and an invitation
# to sign in together, and vetoing on the second would have thrown away exactly
# the case this exists for.
STILL_THERE_MARKS = ("in your country",)


def reads_as_gone(message: str) -> bool:
    """Whether a failure says the video itself is no longer there."""
    said = (message or "").lower()
    if any(mark in said for mark in STILL_THERE_MARKS):
        return False
    return any(mark in said for mark in GONE_MARKS)


class _NoAddress(RuntimeError):
    pass


class AddressCache:
    """Resolved addresses, kept until shortly before they expire.

    Going back a track, restarting one, or playing the same song twice in an
    evening would otherwise cost the few seconds of resolving again each time.
    An address is tied to this machine's connection, so it lives in memory and
    dies with the process.
    """

    def __init__(self, now=time.time) -> None:
        self._now = now
        self._held: dict[str, tuple[str, float | None]] = {}

    def get(self, key: str) -> str | None:
        found = self._held.get(key)
        if found is None:
            return None
        address, expires = found
        if expires is not None and self._now() > expires - ADDRESS_MARGIN_S:
            del self._held[key]
            return None
        return address

    def put(self, key: str, address: str) -> None:
        self._held[key] = (address, address_expiry(address))

    def drop(self, key: str) -> None:
        self._held.pop(key, None)


class _Resolver(QThread):
    """Turns one entry into a playable address."""

    resolved = Signal(str, str, list, "QVariantMap")
    failed = Signal(str, str)
    # Established, rather than guessed from the sentence: this one has nothing
    # to play and never will.
    gone = Signal(str)

    def __init__(self, cfg: Config, key: str, url: str, live: bool,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.key = key
        self._url = url
        self._live = live
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            found = resolve_address(self._cfg, self._url, self._live, self._cancel)
        except Cancelled:
            return
        except (FileNotFoundError, Timeout, _NoAddress) as exc:
            said = str(exc) or "could not resolve the track"
            # The sentence first, since a private or a removed one says so
            # outright and there is nothing left to ask. Otherwise ask, because
            # what a failed resolve says about an unplayable video is only the
            # two words "Video unavailable", which a video blocked in this
            # country opens with as well.
            if reads_as_gone(said) or (not self._live and not self._cancel.is_set()
                                       and nothing_to_play(self._cfg, self._url,
                                                           self._cancel)):
                self.gone.emit(self.key)
                return
            self.failed.emit(self.key, said)
            return
        self.resolved.emit(self.key, found.address, list(found.chapters),
                           dict(found.facts or {}))


class _VideoResolver(QThread):
    """Turns one entry into a picture, when something is open to show it."""

    resolved = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, cfg: Config, key: str, url: str,
                 parent: QObject | None = None,
                 height: int = VIDEO_HEIGHT) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.key = key
        self._url = url
        self._height = height
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            found = resolve_video(self._cfg, self._url, self._cancel,
                                  self._height)
        except Cancelled:
            return
        except (FileNotFoundError, Timeout) as exc:
            self.failed.emit(self.key, str(exc) or "could not find the picture")
            return
        if found:
            self.resolved.emit(self.key, found)
        else:
            self.failed.emit(self.key, "this one has no picture")


class AudioPlayer(QObject):
    trackChanged = Signal()
    # The queue as a list changes far less often than the track does. Bound to
    # trackChanged, a twenty six row popup was rebuilt every time playback
    # moved, which resets the view and throws away delegates it was still
    # building. What is playing is a number now, read beside the list.
    queueChanged = Signal()
    queueReplaced = Signal()
    videoChanged = Signal()
    # What the resolve learned about the song. Its own signal on purpose: the
    # page asks for words and comments again on trackChanged, and those cost
    # requests, so facts arriving must not read as a different song.
    factsChanged = Signal()
    stateChanged = Signal()
    progressChanged = Signal()
    failed = Signal(str)
    # A song that is no longer on YouTube, by key. Its own report rather than
    # a failure, because nothing went wrong here and there is nothing to try
    # again: what is wanted is for the lists holding it to stop holding it.
    gone = Signal(str)
    # A song has been heard for long enough to count as listened to. Once per
    # play, with the queue entry it was.
    heard = Signal("QVariantMap")

    def __init__(self, cfg: Config, db=None, parent: QObject | None = None,
                 engine: LibmpvEngine | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._db = db
        self._queue: list[dict] = []
        self._order: list[int] = []
        self._at = -1
        self._loading = False
        self._resolver: _Resolver | None = None
        self._next_resolvers: list[_Resolver] = []
        self._addresses = AddressCache()
        # What each track's chapters are, by track key. A video that is really
        # an album marks its songs in them, and they came free with the address
        # that was resolved to play it. Kept for the life of the process rather
        # than expiring with the address, since where a song starts is not
        # something that goes stale.
        self._chapters: dict[str, tuple[dict, ...]] = {}
        # What is known about each track, by track key, from the same resolve
        # that found its address. Kept for the same reason the chapters are:
        # it cost nothing, and how many people have watched a song is not
        # something that goes stale over an evening.
        self._facts: dict[str, dict] = {}
        # Which queue index mpv holds as its next entry, if any.
        self._appended: int | None = None

        # The player lives in this process now. A picture cannot come out
        # of a second one, and there is no fallback on purpose: two
        # players would mean faults on the path nobody here ever walks.
        self._engine = engine if engine is not None else LibmpvEngine(self)
        self._engine.positionChanged.connect(self._on_position)
        self._engine.durationChanged.connect(self._on_duration)
        self._engine.pausedChanged.connect(self._on_paused)
        self._engine.idleChanged.connect(self._on_idle)
        self._engine.bufferingChanged.connect(self._on_buffering)
        self._engine.started.connect(self._on_started)
        self._engine.ended.connect(self._on_ended)
        self._engine.gone.connect(self._on_gone)
        # Whether a frame exists yet. The page keeps the artwork up
        # until it does, so the pane is never a black box waiting.
        self._engine.videoChanged.connect(self._on_video_frame)
        # A picture the player would not open. Almost always an address that
        # has aged out, and this is the only place that holds those.
        self._engine.videoRefused.connect(self._on_video_refused)
        self._pos = 0.0
        self._dur = 0.0
        self._paused = True
        self._idle = True
        self._first_at = 0.0
        # How much of the song playing has really been heard, counted from
        # the position as it moves rather than read off it, so a seek forwards
        # adds nothing. Said once per play, when it reaches HEARD_S.
        self._heard_entry: dict | None = None
        self._heard_s = 0.0
        self._heard_last: float | None = None
        self._heard_said = False
        self._buffering = False

        stored = db.get_int("music_volume", 70) if db else 70
        self._level = max(0.0, min(1.0, stored / 100))
        self._output = self._level          # what mpv has been told, fades included
        self._engine.set_volume(self._level * 100)

        self._recovering = False
        self._resume_at = 0.0
        # The picture. Nothing is fetched and nothing decoded until something
        # is open to show it, measured at 0 KiB and 0.2 % of a core, so a
        # listener who never opens the page pays nothing for the ability to.
        self._video_wanted = False
        # Sound alone, whatever is open. Remembered, because it is a way of
        # listening rather than something done to one song.
        self._audio_only = (db.get_state("music_audio_only", "0") == "1") if db else False
        self._video_resolver: _VideoResolver | None = None
        # The picture for the song AFTER this one, found while there is time,
        # so a song change shows it at once instead of two and a half seconds
        # later. A list rather than one, the way the sound's own look ahead is
        # kept, since a queue can be walked faster than a resolve finishes.
        self._next_video_resolvers: list = []
        # Asked whether a song's picture is already on disk, and answering
        # with the file when it is. Installed from outside, since which songs
        # are worth keeping is not something the player knows.
        self.local_video = None
        # And the same for the sound. Asked before any address is looked for,
        # which is the only wait in the whole chain.
        self.local_audio = None
        # Where each song's picture is, kept the way the sound's addresses
        # are and not in a plain map. A signed address stops being accepted
        # after a few hours, and a map that never forgets one hands a dead
        # address to the player, which refuses it without a word and leaves
        # the artwork up for the rest of the evening.
        self._video_addresses = AddressCache()
        self._video_note = ""
        # What is being done about the picture, in words, for the line under
        # the button that fills the screen with it. Finding an address takes
        # seconds and opening the stream takes a couple more, and an artwork
        # sitting there says nothing about which of them is being waited on.
        self._video_stage = ""
        self._video_showing = False
        # Whether the picture for this song came off the disk rather than off
        # the wire, which decides whether the artwork over it is faded away or
        # simply goes.
        self._video_instant = False
        self._recover_at = 0.0
        self._recover_count = 0
        self._stall_timer = QTimer(self)
        self._stall_timer.setSingleShot(True)
        self._stall_timer.timeout.connect(self._on_stalled_too_long)
        self._stall_at = -1.0

        self._shuffle = (db.get_state("music_shuffle", "0") == "1") if db else False
        # Off, the whole queue, or the one track. A queue that repeats and a
        # track that repeats are different wants, and one switch cannot say
        # which, so it cycles through all three.
        self._repeat_mode = max(0, min(2, db.get_int("music_repeat", 0) if db else 0))

        # Volume is faded rather than cut, so a video starting does not chop
        # the music off mid note.
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade.valueChanged.connect(self._on_fade_step)
        self._fade.finished.connect(self._on_fade_done)
        self._pause_after_fade = False
        self._auto_pause = (db.get_state("music_autopause", "1") != "0") if db else True

    # ---- what QML reads --------------------------------------------------

    def _current(self) -> dict:
        if 0 <= self._at < len(self._queue):
            return self._queue[self._at]
        return {}

    def _get_track(self) -> dict:
        return dict(self._current())

    def _get_playing(self) -> bool:
        return not self._idle and not self._paused

    def _get_loading(self) -> bool:
        return self._loading

    def _get_has_queue(self) -> bool:
        return bool(self._queue)

    def _get_position(self) -> float:
        return (self._pos / self._dur) if self._dur > 0 else 0.0

    def _get_elapsed(self) -> int:
        return int(self._pos)

    def _get_is_live(self) -> bool:
        """Whether what is playing is a broadcast rather than a recording.

        Read from the entry, which knew before anything was resolved, and
        never from what mpv reports. mpv answers a live stream's duration with
        the length of the HLS window it is holding, about fourteen seconds,
        which is a real number about the wrong thing.
        """
        return bool(self._current().get("live"))

    def _get_length(self) -> int:
        """How long this is, and nothing for a broadcast.

        A live stream has no length. mpv says fourteen seconds because that is
        the window it is buffering, and taken at face value the bar filled and
        reset every fourteen seconds, the clock counted to 0:14, and the word
        live went out the moment the sound came in. Answering with nothing is
        what every one of those already reads as live.
        """
        return 0 if self._get_is_live() else int(self._dur)

    def _get_chapters(self) -> list:
        """Where this track's songs begin, for the marks on the bar.

        Handed over with each start already a fraction of the whole, because
        the bar is drawn in fractions and a length of zero is a real state
        here, right up until mpv reports one.
        """
        found = self._chapters.get(self._current().get("key") or "")
        if not found or self._dur <= 0:
            return []
        return [{"title": one["title"], "start": one["start"],
                 "at": max(0.0, min(1.0, one["start"] / self._dur))}
                for one in found if one["start"] < self._dur]

    def _song_at(self, seconds: float) -> str:
        """Which song of this track is the one at that moment.

        The last one that has begun, so a track whose first chapter starts
        part way in says nothing over the beginning rather than naming the one
        that comes after. One rule, used by the line under the title and by
        what the pointer says over the bar, so the two can never disagree
        about the same second.
        """
        found = self._chapters.get(self._current().get("key") or "")
        if not found:
            return ""
        name = ""
        for one in found:
            if one["start"] <= seconds:
                name = one["title"]
            else:
                break
        return name

    def _get_current_chapter(self) -> str:
        # Half a second of slack, because a position arrives a moment after the
        # song it belongs to has started and naming the one before it for that
        # moment reads as the line lagging.
        return self._song_at(self._pos + 0.5)

    @Slot(float, result=str)
    def songAt(self, along: float) -> str:
        """The song at that fraction of the track, for the pointer over the
        bar. A fraction rather than a time, because the bar is drawn in
        fractions and the length lives here."""
        if self._dur <= 0:
            return ""
        return self._song_at(max(0.0, min(1.0, along)) * self._dur)

    def _get_volume(self) -> int:
        # What was asked for, not what a fade happens to be passing through.
        return round(self._level * 100)

    def _get_shuffle(self) -> bool:
        return self._shuffle

    def _get_repeat(self) -> int:
        return self._repeat_mode

    def _get_repeat_label(self) -> str:
        return ("Repeat", "Repeat all", "Repeat one")[self._repeat_mode]

    def _get_auto_pause(self) -> bool:
        return self._auto_pause

    def _get_queue_length(self) -> int:
        return len(self._queue)

    def _get_queue(self) -> list:
        """The whole queue, in the order it will actually be played, which is
        not the order it was given once shuffle is on.

        All of it, not only what is still to come. Starting a playlist puts the
        playlist in the player, and a track that has been played stays in the
        list with everything else rather than disappearing behind you, which is
        how every other music player behaves. The one playing is marked so it
        can be found again.
        """
        if not self._queue or self._at not in self._order:
            return []
        return [{
            "title": self._queue[i].get("title", ""),
            "artist": self._queue[i].get("artist", ""),
            "thumbnail": self._queue[i].get("thumbnail", ""),
            # The address of whoever made it, so the name on a row can be
            # pressed. Built here from a fixed set of fields, and a field left
            # out of that set can never reach the window however faithfully
            # everything upstream carries it, which is exactly what kept every
            # name in the queue dead.
            "artistId": self._queue[i].get("artistId", ""),
            # Where it sits in the queue, so it can be jumped to directly.
            "at": i,
        } for i in self._order]

    def _get_still_to_come(self) -> int:
        """How many have not been played yet, for the button that opens the
        list. Zero means there is nothing after this one."""
        if not self._queue or self._at not in self._order:
            return 0
        place = self._order.index(self._at)
        if self._repeat_mode == REPEAT_ALL:
            return max(0, len(self._order) - 1)
        return len(self._order) - place - 1

    track = Property("QVariantMap", _get_track, notify=trackChanged)
    playing = Property(bool, _get_playing, notify=stateChanged)
    loading = Property(bool, _get_loading, notify=stateChanged)
    hasQueue = Property(bool, _get_has_queue, notify=trackChanged)
    position = Property(float, _get_position, notify=progressChanged)
    elapsed = Property(int, _get_elapsed, notify=progressChanged)
    length = Property(int, _get_length, notify=progressChanged)
    isLive = Property(bool, _get_is_live, notify=trackChanged)
    # Bound to progress rather than to the track, because the length arrives
    # from mpv after the track does and the marks cannot be placed without it.
    chapters = Property("QVariantList", _get_chapters, notify=progressChanged)
    currentChapter = Property(str, _get_current_chapter, notify=progressChanged)
    volume = Property(int, _get_volume, notify=stateChanged)
    shuffle = Property(bool, _get_shuffle, notify=stateChanged)
    repeat = Property(int, _get_repeat, notify=stateChanged)
    repeatLabel = Property(str, _get_repeat_label, notify=stateChanged)
    autoPause = Property(bool, _get_auto_pause, notify=stateChanged)
    queueLength = Property(int, _get_queue_length, notify=trackChanged)
    queue = Property("QVariantList", _get_queue, notify=queueChanged)

    def _get_queue_index(self) -> int:
        """Where in the queue the track being played sits, or -1."""
        return self._order.index(self._at) if self._at in self._order else -1

    queueIndex = Property(int, _get_queue_index, notify=trackChanged)
    stillToCome = Property(int, _get_still_to_come, notify=trackChanged)

    # ---- the queue -------------------------------------------------------

    def play_items(self, items: list[dict], start: int = 0,
                   shuffle_rest: bool = False, at_s: float = 0.0) -> None:
        """Queue a list and begin. Each entry needs a key, a title and a url,
        and may say that it is live.

        `shuffle_rest` is for a list that is a bag rather than a running order,
        a shelf of singles being the one that asked for it. It shuffles this
        list only and leaves the player's own shuffle setting alone, so a
        person who plays their singles does not find every later list shuffled
        too.
        """
        self._queue = [dict(item) for item in items if item.get("url")]
        if not self._queue:
            return
        # Where in the first song to begin, which a link with a time in it
        # asks for. Only the first; everything after starts at its top.
        self._first_at = max(0.0, float(at_s or 0.0))
        self._rebuild_order()
        self._at = max(0, min(start, len(self._queue) - 1))
        if self._shuffle or shuffle_rest:
            # Whatever was picked stays first, the rest are shuffled behind it.
            behind = [i for i in self._order if i != self._at]
            if shuffle_rest and not self._shuffle:
                # _rebuild_order only shuffles for the setting, so a list that
                # asked for it on its own is shuffled here.
                random.shuffle(behind)
            self._order = [self._at, *behind]
        self._forget_recovery()
        self.queueChanged.emit()
        # A list replaced outright is not the same event as a song ending into
        # the next one, and the window has to be able to tell them apart. The
        # queue signal cannot say it, since adding one song raises that too.
        self.queueReplaced.emit()
        self._start_current()

    def _rebuild_order(self) -> None:
        self._order = list(range(len(self._queue)))
        if self._shuffle:
            random.shuffle(self._order)

    def _next_index(self) -> int | None:
        """What follows the current track, or None when nothing does. Repeat
        one is not a next track, it is the same one again, and mpv loops it."""
        if not self._queue or self._at not in self._order or self._repeat_mode == REPEAT_ONE:
            return None
        place = self._order.index(self._at)
        if place + 1 < len(self._order):
            return self._order[place + 1]
        if self._repeat_mode == REPEAT_ALL:
            return self._order[0]
        return None

    # ---- starting a track ------------------------------------------------

    def _remember(self, entry: dict) -> None:
        """Note a song in the listening history as it starts.

        A stream is left out, since it is a place rather than a song and has
        no end to come back to. Anything without a YouTube id is left out too,
        because the history is addressed by that id.
        """
        if self._db is None or entry.get("live"):
            return
        key = str(entry.get("key") or "")
        if not key.startswith("yt:"):
            return
        # The picture is stored plain. A queue entry carries it already
        # wrapped for the cache, and wrapping it twice leaves nothing.
        self._db.remember_played(
            key.split(":", 1)[1], str(entry.get("title") or ""),
            entry.get("artist") or None,
            plain_source(entry.get("thumbnail")) or None,
            entry.get("duration_s"), entry.get("artistId") or None)

    def _start_current(self) -> None:
        """Play the current track from the top, or from where a recovery left
        off. Whatever mpv held as next is dropped with the load and queued
        again once this one is under way."""
        entry = self._current()
        if not entry:
            return
        self._stall_timer.stop()
        self._appended = None
        if not self._recovering:
            self._resume_at = self._first_at
        self._first_at = 0.0
        self._pos = 0.0
        self._dur = 0.0
        self._remember(entry)
        # A recovery loads the same song again from where it broke off, which
        # is the same listening, so it keeps what was already heard.
        if not self._recovering:
            self._begin_hearing(entry)
        # A different song needs its own picture, so whatever was on screen
        # stops being shown and the artwork comes back at once. Asking for the
        # new one waits for mpv to say it has started this file: a picture is
        # added to the file that is PLAYING, and this one has not been handed
        # over yet, so asking here attached it to the song being left and the
        # load that followed threw it away. That is why pressing another song
        # in the queue showed no picture until the window was minimised and
        # opened again, which asked a second time with the right file playing.
        self._video_showing = False
        self._video_stage = ""
        self.trackChanged.emit()
        self.progressChanged.emit()
        if self._resolver is not None and self._resolver.isRunning():
            self._resolver.cancel()
        # Kept on disk, for a song he keeps. No address to find and nothing to
        # pull, so the sound starts at once rather than after the few seconds
        # a resolve takes. Never for a broadcast, which has no file and no end.
        kept = (self.local_audio(entry["key"])
                if self.local_audio and not entry.get("live") else "")
        address = kept or (None if entry.get("live")
                           else self._addresses.get(entry["key"]))
        if address:
            self._loading = False
            self.stateChanged.emit()
            self._hand_over(entry, address)
            return
        self._loading = True
        self.stateChanged.emit()
        self._resolver = self._make_resolver(entry)
        self._resolver.resolved.connect(self._on_resolved)
        self._resolver.failed.connect(self._on_resolve_failed)
        self._resolver.gone.connect(self._on_resolve_gone)
        self._resolver.start()

    def _on_resolved(self, key: str, address: str, chapters: list | None = None,
                     facts: dict | None = None) -> None:
        # Kept whoever it was for. A resolve that arrives after the choice has
        # moved on still learned where that track's songs are, and it will be
        # wanted the moment anybody goes back to it.
        if chapters:
            self._chapters[key] = tuple(chapters)
        if facts:
            self._facts[key] = dict(facts)
            self.factsChanged.emit()
        entry = self._current()
        if entry.get("key") != key:
            return                       # a later choice overtook this one
        if not entry.get("live"):
            self._addresses.put(key, address)
        self._loading = False
        self._hand_over(entry, address)

    def _hand_over(self, entry: dict, address: str) -> None:
        """Give mpv the address. A position left by a recovery goes with the
        load, so it is applied to the file it was meant for and never to one
        that has not loaded yet."""
        start = self._resume_at if self._resume_at > 0 else None
        self._resume_at = 0.0
        self._recovering = False
        self._raise_volume()
        self._engine.load(address, start=start)
        self._engine.set_pause(False)
        self._paused = False
        self._idle = False
        self.stateChanged.emit()
        self._prepare_next()

    def _make_resolver(self, entry: dict) -> _Resolver:
        """Its own method so a test can put something there that never
        reaches for a subprocess."""
        return _Resolver(self._cfg, entry["key"], entry["url"], bool(entry.get("live")), self)

    def _on_resolve_failed(self, key: str, message: str) -> None:
        if self._current().get("key") != key:
            return
        self._loading = False
        self.stateChanged.emit()
        self.failed.emit(message)

    def _on_resolve_gone(self, key: str) -> None:
        """Nothing to play, and there never will be. A different thing from a
        track that would not play, so it leaves the queue rather than being
        tried again, and what is said about it is said by whoever holds the
        lists it was in."""
        if self._current().get("key") != key:
            return
        self._loading = False
        self.stateChanged.emit()
        self.gone.emit(key)
        self.removeFromQueue(self._queue.index(self._current()))

    # ---- the track after this one ----------------------------------------

    def _prepare_next(self) -> None:
        """Get everything the song after this one needs, while there is time.

        Resolving is the only wait in the whole chain, so it is done now,
        while there are minutes to spare, rather than when the track ends.
        Both halves of it: the sound, which mpv is handed in advance so it can
        open it and move on with no gap, and the picture, which is found in
        advance for the same reason and only while the page that draws it is
        open.
        """
        self._arrange_next()
        self._prepare_next_picture()

    def _arrange_next(self) -> None:
        """Make sure mpv holds the right next entry, and nothing else."""
        self._engine.set_loop(self._repeat_mode == REPEAT_ONE)
        wanted = self._next_index()
        if wanted is None:
            if self._appended is not None:
                self._engine.clear_after()
                self._appended = None
            return
        if wanted == self._appended:
            return
        if self._appended is not None:
            self._engine.clear_after()
            self._appended = None
        entry = self._queue[wanted]
        kept = (self.local_audio(entry["key"])
                if self.local_audio and not entry.get("live") else "")
        address = kept or (None if entry.get("live")
                           else self._addresses.get(entry["key"]))
        if address:
            self._engine.append(address)
            self._appended = wanted
            return
        if any(r.key == entry["key"] and r.isRunning() for r in self._next_resolvers):
            return
        resolver = self._make_resolver(entry)
        resolver.resolved.connect(self._on_next_resolved)
        resolver.gone.connect(self._on_next_gone)
        resolver.finished.connect(self._sweep_resolvers)
        self._next_resolvers.append(resolver)
        resolver.start()

    def _prepare_next_picture(self) -> None:
        """Find the next song's picture while this one is still playing.

        The sound is already done this way, because resolving is the only wait
        in the chain. The picture was not, so every song change showed the
        artwork for the two and a half seconds an address takes to find and
        a frame to arrive, however long there had been to do it in.

        Only while the page is open, which is the rule the whole picture side
        follows: somebody who never opens it pays nothing for the ability to.
        One extraction per song, and only for a song that would be given a
        picture at all.
        """
        if not self._video_wanted or self._audio_only:
            return
        wanted = self._next_index()
        if wanted is None:
            return
        entry = self._queue[wanted]
        key = entry.get("key", "")
        if (not key or self._video_addresses.get(key)
                or self._refuse_video(entry)):
            return
        if self.local_video and self.local_video(key):
            # Already on disk, so there is nothing to look ahead for.
            return
        if any(r.key == key and r.isRunning() for r in self._next_video_resolvers):
            return
        resolver = self._make_video_resolver(entry)
        # The same handler the current song's picture uses. It writes the
        # address down and only hands it to the player when it belongs to the
        # song playing, which this one does not yet.
        resolver.resolved.connect(self._on_video_resolved)
        resolver.finished.connect(self._sweep_video_resolvers)
        self._next_video_resolvers.append(resolver)
        resolver.start()

    def _sweep_video_resolvers(self) -> None:
        self._next_video_resolvers = [r for r in self._next_video_resolvers
                                      if r.isRunning()]

    def _stop_next_video_resolvers(self) -> None:
        """Closing the page stops looking ahead. What was already found is
        kept, since it costs nothing to keep and saves the whole wait if the
        page is opened again before that song comes round."""
        for resolver in self._next_video_resolvers:
            if resolver.isRunning():
                resolver.cancel()
        self._next_video_resolvers = []

    def _on_next_resolved(self, key: str, address: str,
                          chapters: list | None = None) -> None:
        """Whatever the queue looks like by now, the address is worth keeping.
        It is only handed to mpv if that track is still the one coming up.

        The songs inside it are worth keeping for the same reason, and they
        would otherwise be thrown away here: PySide hands a slot only as many
        arguments as it takes, so a shorter one drops them without a word.
        """
        if chapters:
            self._chapters[key] = tuple(chapters)
        wanted = self._next_index()
        entry = self._queue[wanted] if wanted is not None else {}
        if not entry.get("live"):
            self._addresses.put(key, address)
        if entry.get("key") == key and self._appended is None and not self._idle:
            self._engine.append(address)
            self._appended = wanted

    def _on_next_gone(self, key: str) -> None:
        """A song with nothing to play, met while looking ahead.

        This is how nearly all of them are met. A song is seldom pressed; it
        comes round in the queue, and by then the question has already been
        asked and answered, because looking ahead resolves it minutes early.
        Nobody was listening to the answer, so nothing was handed to mpv for
        it and the listening ended on the song before it with no word about
        why, leaving the dead one in the queue and in the list it came from.

        It leaves both exactly as a pressed one does. Every copy of it goes,
        since a song that is gone is gone wherever it sits in the queue, and
        removing one re-arranges what follows on its own.
        """
        self.gone.emit(key)
        while True:
            here = next((i for i, entry in enumerate(self._queue)
                         if entry.get("key") == key), None)
            if here is None:
                return
            self.removeFromQueue(here)

    def _sweep_resolvers(self) -> None:
        self._next_resolvers = [r for r in self._next_resolvers if r.isRunning()]

    # ---- what mpv reports ------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        before = int(self._pos * 10)
        self._pos = seconds
        self._count_heard(seconds)
        if int(seconds * 10) != before:
            self.progressChanged.emit()

    # ---- what has been heard ---------------------------------------------

    def _begin_hearing(self, entry: dict) -> None:
        self._heard_entry = dict(entry) if str(entry.get("key") or "").startswith("yt:") else None
        self._heard_s = 0.0
        self._heard_last = None
        self._heard_said = False

    def _count_heard(self, seconds: float) -> None:
        """Add what the position moved by, if it moved the way listening does.

        A short song is heard once most of it has been, since it can never
        reach the full HEARD_S.
        """
        if self._heard_entry is None or self._heard_said:
            return
        last, self._heard_last = self._heard_last, seconds
        if last is None or self._paused:
            return
        step = seconds - last
        if 0 < step <= HEARD_STEP_S:
            self._heard_s += step
        needed = HEARD_S if self._dur <= 0 else min(HEARD_S, self._dur * 0.9)
        if self._heard_s >= needed:
            self._heard_said = True
            self.heard.emit(dict(self._heard_entry))

    def _on_duration(self, seconds: float) -> None:
        self._dur = seconds
        self.progressChanged.emit()

    def _read_duration(self) -> float:
        """What the player says its length is right now.

        An engine written before this was needed answers nothing, which is the
        old behaviour of starting from zero and waiting for a report.
        """
        ask = getattr(self._engine, "duration", None)
        if ask is None:
            return 0.0
        try:
            return max(0.0, float(ask() or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _on_paused(self, paused: bool) -> None:
        self._paused = paused
        self.stateChanged.emit()

    def _on_idle(self, idle: bool) -> None:
        self._idle = idle
        if idle:
            self._stall_timer.stop()
            self._appended = None
            self._pos = 0.0
            self.progressChanged.emit()
        self.stateChanged.emit()

    def _on_buffering(self, buffering: bool) -> None:
        """mpv paused itself for want of data. Ordinary buffering comes back
        within a moment. One that does not, with the position where it was,
        is a connection that has died without saying so."""
        self._buffering = buffering
        if buffering and self._current():
            self._stall_at = self._pos
            self._stall_timer.start(STALL_GRACE_MS)
        else:
            self._stall_timer.stop()

    def _on_started(self, role: str) -> None:
        if role == NEXT and self._appended is not None:
            # mpv moved on by itself, as planned. Weave's pointer follows.
            self._at = self._appended
            self._appended = None
            self._forget_recovery()
            self._pos = 0.0
            # Asked for rather than zeroed and waited for. The length arrives
            # as a change to a property mpv observes, and a track that follows
            # one of the same length changes nothing, so no report comes. A
            # queue of one repeating is always that case, and the bar, which
            # is drawn only where there is a length, went and stayed away.
            self._dur = self._read_duration()
            self._engine.remove_before()
            # Played as surely as a song pressed by hand, and most of a queue
            # arrives this way. Only a press used to be noted, so a queue
            # listened to from start to end left one song in the history.
            entry = self._current()
            if entry:
                self._remember(entry)
                self._begin_hearing(entry)
            # mpv moved on by itself, so the song changed without going through
            # the path that starts one. The picture has to follow here as well
            # or a gapless changeover leaves the page showing nothing.
            self._video_showing = False
            self._video_stage = ""
            if self._video_wanted:
                self._start_video()
            self.trackChanged.emit()
            self.progressChanged.emit()
            self._prepare_next()
        elif role == CURRENT:
            self._stall_timer.stop()
            # The file mpv is playing is this one now, so a picture added goes
            # to the right place. See _start_current for why it is not asked
            # for any earlier.
            if self._video_wanted:
                self._start_video()
        self.stateChanged.emit()

    def _on_ended(self, reason: str) -> None:
        self._stall_timer.stop()
        if reason == "eof":
            # mpv either moves on to what it was handed or goes idle, and
            # both arrive as their own events.
            self._forget_recovery()
        elif reason == "error":
            if not self._recover():
                self.failed.emit("the track could not be played")

    def _on_stalled_too_long(self) -> None:
        if not self._current() or not self._buffering or self._pos != self._stall_at:
            return
        if not self._recover():
            self.failed.emit("the connection was lost and could not be picked up again")

    def _on_gone(self, why: str) -> None:
        self._idle = True
        self._paused = True
        self._appended = None
        self._stall_timer.stop()
        self.stateChanged.emit()
        if self._queue:
            self.failed.emit(why)

    def _recover(self) -> bool:
        """Fetch a fresh address and carry on from the same place.

        Returns whether it is being handled, so a failure that is being dealt
        with stays quiet and one that cannot be is reported.
        """
        if not self._current():
            return False
        now = time.monotonic()
        # A dropped connection can arrive as a burst of the same complaint.
        # The first one starts a recovery and the rest are already answered.
        if now - self._recover_at < RECOVER_COOLDOWN_S:
            return True
        # A track that has been playing happily for a while starts over with a
        # full set of goes, so a long listen cannot run out.
        if now - self._recover_at > RECOVER_WINDOW_S:
            self._recover_count = 0
        if self._recover_count >= RECOVER_LIMIT:
            return False
        self._recover_at = now
        self._recover_count += 1
        self._recovering = True
        self._resume_at = self._pos
        # The address is the likeliest thing to have gone bad.
        self._addresses.drop(self._current().get("key", ""))
        self._start_current()
        return True

    def _forget_recovery(self) -> None:
        """A different track is a clean slate."""
        self._recovering = False
        self._recover_count = 0
        self._recover_at = 0.0

    # ---- controls --------------------------------------------------------

    @Slot()
    def toggle(self) -> None:
        if self._get_playing():
            self._fade_to(0.0, pause_after=True, duration_ms=TOGGLE_FADE_MS)
            return
        if self._queue:
            if self._idle:
                self._start_current()
            else:
                # Comes back up rather than arriving at full volume.
                self._fade.stop()
                self._pause_after_fade = False
                self._set_output(0.0)
                self._engine.set_pause(False)
                self._paused = False
                self._fade_to(self._level, pause_after=False,
                              duration_ms=TOGGLE_FADE_MS)
        self.stateChanged.emit()

    @Slot(int)
    def jumpTo(self, index: int) -> None:
        """Skip straight to something further down the queue."""
        if 0 <= index < len(self._queue) and index != self._at:
            self._forget_recovery()
            self._at = index
            self._start_current()

    def add_item(self, item: dict, play_next: bool = False) -> bool:
        """Put one song in the queue, at the end or straight after this one.

        Nothing starts playing because of this. A queue with nothing in it is
        the one exception, since adding to an empty queue and hearing silence
        would be a strange thing to have asked for.
        """
        if not item.get("url"):
            return False
        if not self._queue:
            self.play_items([item])
            return True
        self._queue.append(dict(item))
        index = len(self._queue) - 1
        if play_next and self._at in self._order:
            self._order.insert(self._order.index(self._at) + 1, index)
        else:
            self._order.append(index)
        # What mpv holds as the next file was decided before this arrived, and
        # a song put on the end is the next one whenever what is playing is the
        # last. Without asking again there, the player is holding nothing, and
        # the listening stops on a song that has a successor.
        if not self._idle:
            self._prepare_next()
        self.queueChanged.emit()
        self.trackChanged.emit()
        return True

    def extend(self, items: list[dict]) -> bool:
        """Put several songs on the end at once.

        One signal rather than one per song, and nothing restarts. A station
        arrives as fifty tracks after the first of them is already playing, and
        handing them over one at a time rebuilt the window fifty times.
        """
        fresh = [dict(item) for item in items if item.get("url")]
        if not fresh:
            return False
        if not self._queue:
            self.play_items(fresh)
            return True
        first = len(self._queue)
        self._queue.extend(fresh)
        self._order.extend(range(first, len(self._queue)))
        if not self._idle:
            self._prepare_next()
        self.queueChanged.emit()
        self.trackChanged.emit()
        return True

    @Slot(int, int)
    def moveInQueue(self, from_place: int, to_place: int) -> None:
        """Move a song to another place in the play order.

        Places are places in the list as it is shown, which is the play order
        and not the order the songs were handed over, so this holds under
        shuffle as well. A song already heard can be moved ahead of what is
        still to come, and it is then heard again when it is reached, which is
        the point of being allowed to move it at all.
        """
        if from_place == to_place:
            return
        if not (0 <= from_place < len(self._order)) or not (0 <= to_place < len(self._order)):
            return
        self._order.insert(to_place, self._order.pop(from_place))
        # What mpv holds as the next file was chosen before the move, so it is
        # chosen again. Without this the old next is still what plays.
        if not self._idle:
            self._prepare_next()
        self.queueChanged.emit()
        self.trackChanged.emit()

    @Slot(int)
    def removeFromQueue(self, index: int) -> None:
        """Take a song out of the queue, and out of nothing else.

        The list it came from is untouched. Taking out the one playing moves
        on to what follows it, since the alternative is a player still playing
        something it was told to forget.
        """
        if not (0 <= index < len(self._queue)):
            return
        was_current = index == self._at
        following = self._next_index() if was_current else None
        held = self._appended
        self._queue.pop(index)
        self._order = [i - 1 if i > index else i
                       for i in self._order if i != index]
        # What the player is holding as next is a place in this queue, and
        # every place after the one taken out has just moved. Left as it was
        # it names a different song, or no song at all, and the window then
        # announces whatever it names while the player plays what it was
        # really given.
        if held is not None:
            if held == index:
                # It is holding the very song being taken out, so it has to be
                # told. Nothing else would: the arrangement below finds the
                # same place still wanted and leaves the player alone.
                self._engine.clear_after()
                self._appended = None
            elif held > index:
                self._appended = held - 1
        if was_current:
            if following is None:
                self.stop()
                return
            self._at = following - 1 if following > index else following
            self._forget_recovery()
            self._start_current()
        else:
            if index < self._at:
                self._at -= 1
            if not self._idle:
                # What mpv holds as next may have been the one that just went,
                # and under shuffle or a queue that repeats it may have been
                # one of the places that moved.
                self._prepare_next()
        self.queueChanged.emit()
        self.trackChanged.emit()

    @Slot()
    def next(self) -> None:
        if not self._queue:
            return
        self._forget_recovery()
        if self._repeat_mode == REPEAT_ONE:
            # Asking for the next one means the next one, whatever repeat says.
            place = self._order.index(self._at) if self._at in self._order else -1
            target = self._order[(place + 1) % len(self._order)] if self._order else None
        else:
            target = self._next_index()
        if target is None:
            self._engine.stop()
            self.stateChanged.emit()
            return
        if target == self._appended and not self._idle:
            # Already open in mpv, so this is instant. The pointer moves when
            # mpv says it has started.
            self._engine.next()
            return
        self._at = target
        self._start_current()

    @Slot()
    def previous(self) -> None:
        if not self._queue:
            return
        # Within the first few seconds this goes back a track, later it
        # restarts the current one, which is what every music player does.
        if self._pos > 4.0 and not self._idle:
            self._engine.seek(0.0)
            return
        self._forget_recovery()
        place = self._order.index(self._at) if self._at in self._order else 0
        self._at = self._order[max(0, place - 1)]
        self._start_current()

    @Slot(float)
    def seek(self, fraction: float) -> None:
        if self._dur > 0 and not self._idle:
            self._engine.seek(max(0.0, min(1.0, fraction)) * self._dur)

    @Slot(int)
    def seekTo(self, seconds: int) -> None:
        """Go to a time in the track, the way a time written in a description
        does. Past the end is the end, and a broadcast has nowhere to go."""
        if self._dur <= 0 or self._idle:
            return
        self._engine.seek(max(0.0, min(self._dur, float(seconds))))

    @Slot(int)
    def nudgeSeek(self, notches: int) -> None:
        """Move along the track by turns of the wheel over the bar.

        In seconds rather than in a fraction of the whole, because the wheel
        is the same gesture whatever is playing and a tenth of a track is a
        different distance in every song. A broadcast has no length and no
        place to move to, so it stays where it is.
        """
        if self._dur <= 0 or self._idle or not notches:
            return
        wanted = self._pos + notches * SEEK_NOTCH_S
        self._engine.seek(max(0.0, min(self._dur, wanted)))

    @Slot(float)
    def seekToTick(self, along: float) -> None:
        """Seek, but land on the start of a song rather than between two.

        The marks on the bar say where each one begins, and hitting one of them
        by hand on a bar a few hundred pixels wide is luck. This goes to the
        nearest one, forwards or back, so a press that falls just past the
        start of a song goes to the start of that song rather than skipping the
        whole of it.

        A track with no songs in it is seeked to plainly rather than doing
        nothing, since a press that answers with nothing reads as one that did
        not work. Two marks the same distance away is the beginning of the
        earlier one, which is the half that has not been heard.
        """
        if self._dur <= 0 or self._idle:
            return
        along = max(0.0, min(1.0, along))
        found = self._chapters.get(self._current().get("key") or "")
        starts = [one["start"] for one in found or () if one["start"] < self._dur]
        if not starts:
            self.seek(along)
            return
        wanted = along * self._dur
        self._engine.seek(min(starts, key=lambda start: abs(start - wanted)))

    @Slot(int)
    def nudgeVolume(self, steps: int) -> None:
        """One wheel notch is five, which is small enough to tune with and big
        enough to be worth a notch."""
        self.setVolume(self._get_volume() + steps * 5)

    # ---- volume and fades ------------------------------------------------

    def _set_output(self, level: float) -> None:
        self._output = max(0.0, min(1.0, level))
        self._engine.set_volume(self._output * 100)

    def _raise_volume(self) -> None:
        """Play at the level that was asked for.

        A pause leaves the volume down on purpose, since restoring it while
        the player is still stopping is heard as a blip, so anything that
        starts playing has to raise it again.
        """
        self._fade.stop()
        self._pause_after_fade = False
        self._set_output(self._level)

    def _fade_to(self, level: float, pause_after: bool,
                 duration_ms: int = FADE_MS) -> None:
        self._fade.stop()
        self._pause_after_fade = pause_after
        self._fade.setDuration(duration_ms)
        self._fade.setStartValue(float(self._output))
        self._fade.setEndValue(float(max(0.0, min(1.0, level))))
        self._fade.start()

    def _on_fade_step(self, value) -> None:
        self._set_output(float(value))

    def _on_fade_done(self) -> None:
        if self._pause_after_fade:
            self._pause_after_fade = False
            self._engine.set_pause(True)
            self._paused = True
            # The volume stays down. Pausing takes a moment, so putting the
            # level back here plays whatever is still in the buffer at full
            # volume, which is heard as a blip right at the end of the fade.
            # Every path that starts playing raises it instead.
            self.stateChanged.emit()

    @Slot(int)
    def setVolume(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self._fade.stop()
        self._pause_after_fade = False
        self._level = value / 100
        self._set_output(self._level)
        if self._db is not None:
            self._db.set_state("music_volume", str(value))
        self.stateChanged.emit()

    # ---- modes -----------------------------------------------------------

    @Slot(bool)
    def setShuffle(self, value: bool) -> None:
        self._shuffle = bool(value)
        if self._db is not None:
            self._db.set_state("music_shuffle", "1" if value else "0")
        current = self._at
        self._rebuild_order()
        if current in self._order and self._shuffle:
            self._order = [current] + [i for i in self._order if i != current]
        if not self._idle:
            self._prepare_next()
        self.stateChanged.emit()
        self.queueChanged.emit()
        self.trackChanged.emit()

    @Slot()
    def cycleRepeat(self) -> None:
        self.setRepeat((self._repeat_mode + 1) % 3)

    @Slot(int)
    def setRepeat(self, mode: int) -> None:
        self._repeat_mode = max(0, min(2, int(mode)))
        if self._db is not None:
            self._db.set_state("music_repeat", str(self._repeat_mode))
        if not self._idle:
            self._prepare_next()
        self.stateChanged.emit()
        self.trackChanged.emit()

    @Slot(bool)
    def setAutoPause(self, value: bool) -> None:
        self._auto_pause = bool(value)
        if self._db is not None:
            self._db.set_state("music_autopause", "1" if value else "0")
        self.stateChanged.emit()

    # ---- the picture ------------------------------------------------------

    @property
    def engine(self):
        """The player itself. The surface needs it to build a render context,
        which can only be made against this exact handle."""
        return self._engine

    @Slot(bool)
    def setVideoWanted(self, wanted: bool) -> None:
        """Whether anything is open to show a picture."""
        wanted = bool(wanted)
        if wanted == self._video_wanted:
            return
        self._video_wanted = wanted
        trace.mark("page", wanted=wanted)
        if not wanted:
            # Nothing is said to the player. The picture keeps running behind
            # the closed page for the rest of this song, so opening it again
            # shows the video at once rather than the artwork for the seconds
            # a frame takes to exist again. It lapses at the next song, which
            # gets no picture unless the page is open, and that bounds the
            # cost to the remainder of one song.
            self._stop_video_resolver()
            self._stop_next_video_resolvers()
            self._video_note = ""
            self._video_stage = ""
            self.videoChanged.emit()
            return
        self._start_video()
        # And the one after it, since opening the page is exactly the moment
        # the next song becomes worth finding a picture for.
        self._prepare_next_picture()

    def _start_video(self) -> None:
        """Find the picture for what is playing, if it deserves one."""
        entry = self._current()
        self._video_note = ""
        if not entry or not self._video_wanted or self._audio_only:
            self._video_stage = ""
            return
        note = self._refuse_video(entry)
        if note:
            # The note says why there will never be one, which is a better
            # thing to read than a step that is not being taken.
            self._video_stage = ""
            self._video_note = note
            self.videoChanged.emit()
            return
        key = entry.get("key", "")
        # A song that is kept may have its picture on disk already, in which
        # case there is no address to find and nothing to pull. Asked through
        # a hook rather than reached for, because what counts as kept is the
        # window's business and not the player's.
        kept = self.local_video(key) if self.local_video else ""
        if kept:
            # A file on disk has its first frame in a moment rather than in the
            # seconds an address and a stream take, so the artwork over it is
            # not faded away, it simply goes. A fade is there to cover a wait.
            self._video_instant = True
            self._video_stage = STAGE_KEPT
            self._engine.add_video(kept)
            self.videoChanged.emit()
            return
        self._video_instant = False
        known = self._video_addresses.get(key)
        if known:
            self._video_stage = STAGE_OPENING
            self._engine.add_video(known)
            self.videoChanged.emit()
            return
        self._video_stage = STAGE_LOOKING
        self._stop_video_resolver()
        self._video_resolver = self._make_video_resolver(entry)
        self._video_resolver.resolved.connect(self._on_video_resolved)
        self._video_resolver.failed.connect(self._on_video_failed)
        self._video_resolver.start()
        self.videoChanged.emit()

    def _refuse_video(self, entry: dict) -> str:
        """Why this one gets no picture, or nothing at all.

        A broadcast is exempt from the length rule: it reports no length worth
        comparing, and its picture is already being fetched whatever happens,
        since a livestream is offered in no sound only shape at all.
        """
        if entry.get("live"):
            return ""
        # The song's own length first, and the player's only where there is
        # none. Across a gapless change the player is asked before it has
        # reconfigured, so what it answers can still be the length of the song
        # before, and a long one before a short one refused the short one a
        # picture it should have had.
        length = float(entry.get("duration_s") or 0) or self._dur
        if length and length > VIDEO_MAX_S:
            return f"no video over {VIDEO_MAX_S // 60} minutes"
        return ""

    def _on_video_resolved(self, key: str, url: str) -> None:
        self._video_addresses.put(key, url)
        if (self._current().get("key") != key or not self._video_wanted
                or self._audio_only):
            return
        self._video_stage = STAGE_OPENING
        self._engine.add_video(url)
        self.videoChanged.emit()

    def _on_video_failed(self, key: str, why: str) -> None:
        if self._current().get("key") != key:
            return
        self._video_stage = ""
        self._video_note = why
        self.videoChanged.emit()

    def _on_video_refused(self, url: str, said: str) -> None:
        """The player would not open the picture it was given.

        The address is forgotten rather than kept, because the likeliest cause
        by a long way is one that has aged out, and holding it means every
        later go at that song is refused in the same silence.
        """
        key = self._current().get("key", "")
        if key and self._video_addresses.get(key) == url:
            self._video_addresses.drop(key)
        self._video_stage = ""
        self._video_note = said
        self.videoChanged.emit()

    def _make_video_resolver(self, entry: dict):
        """Its own method so a test can put something there that never reaches
        for a subprocess, the same way the address resolver is replaced."""
        return _VideoResolver(self._cfg, entry["key"], entry["url"], self,
                              self.video_height())

    def video_height(self) -> int:
        """The ceiling in force for the picture.

        The config carries the default and a choice made on the settings page
        overrides it, exactly as the image cache ceiling works. Read at the
        moment a picture is asked for, so a change takes hold on the next song
        without anything having to be told about it.
        """
        wanted = getattr(self._cfg, "music_video_height", VIDEO_HEIGHT)
        if self._db is None:
            return int(wanted)
        return self._db.video_height(int(wanted))

    @Slot(bool)
    def setAudioOnly(self, value: bool) -> None:
        """Sound alone, whatever page is open.

        Turning it on says so to the player at once rather than at the next
        song: the picture is already being decoded, and waiting would be
        ignoring what was asked for. Turning it off starts one if there is
        something open to show it.
        """
        value = bool(value)
        if value == self._audio_only:
            return
        self._audio_only = value
        if self._db is not None:
            self._db.set_state("music_audio_only", "1" if value else "0")
        if value:
            self._stop_video_resolver()
            self._video_note = ""
            self._video_stage = ""
            self._engine.drop_video()
        else:
            self._start_video()
        self.stateChanged.emit()
        self.videoChanged.emit()

    def _stop_video_resolver(self) -> None:
        if self._video_resolver is not None and self._video_resolver.isRunning():
            self._video_resolver.cancel()
        self._video_resolver = None

    def _on_video_frame(self, showing: bool) -> None:
        self._video_showing = bool(showing)
        if showing:
            self._video_stage = STAGE_SHOWING
        elif self._video_stage == STAGE_SHOWING:
            # A picture that was being shown and is not any more. What comes
            # next decides what is said, so nothing is said until it does.
            self._video_stage = ""
        self.videoChanged.emit()

    def _get_track_facts(self) -> dict:
        """What the resolve learned about the song playing, or nothing yet.

        Empty until its address has been found, which is a few seconds after
        the press, and empty for good for a track that would not resolve.
        """
        return dict(self._facts.get(self._current().get("key", ""), {}))

    def _get_audio_only(self) -> bool:
        return self._audio_only

    def _get_video_wanted(self) -> bool:
        return self._video_wanted

    def _get_video_note(self) -> str:
        return self._video_note

    def _get_video_showing(self) -> bool:
        return self._video_showing

    def _get_video_stage(self) -> str:
        return self._video_stage

    # Views, likes and the date, from the resolve that found the address.
    trackFacts = Property("QVariantMap", _get_track_facts, notify=factsChanged)
    audioOnly = Property(bool, _get_audio_only, notify=stateChanged)
    videoWanted = Property(bool, _get_video_wanted, notify=videoChanged)
    # Why there is no picture, when there is a reason worth saying.
    videoNote = Property(str, _get_video_note, notify=videoChanged)
    # A frame exists. Until it does the artwork stays up, so the pane is never
    # a black box waiting.
    videoShowing = Property(bool, _get_video_showing, notify=videoChanged)
    # Which step of getting a picture up is being waited on, in words. Empty
    # whenever there is nothing being waited on, including for a song that is
    # never going to have one, whose reason the note above carries instead.
    videoStage = Property(str, _get_video_stage, notify=videoChanged)

    def _get_video_instant(self) -> bool:
        return self._video_instant

    # Whether this song's picture came off the disk. The page uses it to drop
    # the fade, which is there to cover the wait for a stream's first frame and
    # has nothing to cover when there was no wait.
    videoInstant = Property(bool, _get_video_instant, notify=videoChanged)

    @Slot()
    def stop(self) -> None:
        self._engine.stop()
        self._queue = []
        self._order = []
        self._at = -1
        self._appended = None
        self.queueChanged.emit()
        self.trackChanged.emit()
        self.stateChanged.emit()

    def pause_for_video(self) -> None:
        """Called when mpv starts something. Two things playing at once is
        never what anyone wanted, but neither is being cut off mid note."""
        if self._auto_pause and self._get_playing():
            self._fade_to(0.0, pause_after=True)

    def shutdown(self) -> None:
        # The picture resolver goes with the rest. Qt treats destroying
        # a thread that is still running as fatal, and this one outlives
        # a short session easily: it spends seconds asking for an
        # address nobody is waiting for any more.
        self._stop_video_resolver()
        held = [self._resolver, *self._next_resolvers, *self._next_video_resolvers]
        for resolver in held:
            if resolver is not None and resolver.isRunning():
                resolver.cancel()
        for resolver in held:
            if resolver is not None and resolver.isRunning():
                resolver.wait(5000)
        self._engine.quit()
