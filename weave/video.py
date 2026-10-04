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

import threading
from dataclasses import dataclass

from PySide6.QtCore import Property, QObject, QThread, QTimer, Signal, Slot

from . import format as fmt
from . import trace
from .audio import (FACT_SPEC, VIDEO_HEIGHT_STEPS, AddressCache, _why, nothing_to_play,
                    parse_chapters, parse_facts, reads_as_gone)
from .config import Config
from .cookies import args as cookie_args
from .engine_libmpv import CURRENT, LibmpvEngine
from .process import Cancelled, Timeout
from .process import run as run_process
from .sources.ytdlp import prepare

# On top of the music's. A name of its own at the sound server, so the two can
# be told apart there and in a trace. The last frame is kept when a video ends,
# which is what is left on screen when the queue has run out, and what the next
# one replaces without the page going black between them.
OPTIONS = {
    "audio_client_name": "weave-video",
    "keep_open": "yes",
    "prefetch_playlist": False,
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

# When no ceiling has been picked, the screen decides, and before the window has
# said which screen it is on, this does.
FALLBACK_HEIGHT = 1080


def ceiling_for(screen_height: int) -> int:
    """The largest offered height that fits the screen, so a picture is never
    fetched bigger than anything can show it."""
    fitting = [step for step in VIDEO_HEIGHT_STEPS if step <= int(screen_height)]
    return fitting[-1] if fitting else VIDEO_HEIGHT_STEPS[0]


def watch_format(height: int, live: bool) -> str:
    """What to ask yt-dlp for, capped at a height.

    A video is offered as a picture and a sound apart at every useful size, and
    joined only at the small ones, so the pair is asked for first, vp9 first
    because it is a third of the bytes of avc1 at the same height. A broadcast
    is only ever offered joined.
    """
    height = int(height)
    if live:
        return f"best[height<={height}]/best"
    return (f"bestvideo[height<={height}][vcodec^=vp9]+bestaudio/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]/best")


@dataclass(frozen=True)
class Found:
    """What one resolve came back with: the picture, the sound when it is a
    stream of its own, and what rides along in the same call for free."""

    picture: str
    sound: str = ""
    chapters: tuple[dict, ...] = ()
    facts: dict | None = None


class NoAddress(RuntimeError):
    pass


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
                       "--get-url", "--print", "%(chapters)j",
                       "--print", FACT_SPEC, url])
    result = run_process(command, cancel=cancel, timeout=180)
    addresses = [line for line in result.stdout.splitlines() if line.startswith("http")]
    if not addresses:
        raise NoAddress(_why(result.stderr or ""))
    # The picture is asked for first, so it comes first. A joined stream is one
    # address carrying both.
    return Found(addresses[0], addresses[1] if len(addresses) > 1 else "",
                 parse_chapters(result.stdout), parse_facts(result.stdout))


class _Finder(QThread):
    """Turns one video into what the player needs."""

    found = Signal(str, str, str, list, "QVariantMap")
    failed = Signal(str, str)
    gone = Signal(str)

    def __init__(self, cfg: Config, key: str, url: str, height: int, live: bool,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self.key = key
        self._url = url
        self._height = height
        self._live = live
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
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
        self.found.emit(self.key, found.picture, found.sound, list(found.chapters),
                        dict(found.facts or {}))


class VideoPlayer(QObject):
    """The videos played in the window, and their queue."""

    trackChanged = Signal()
    queueChanged = Signal()
    stateChanged = Signal()
    progressChanged = Signal()
    factsChanged = Signal()
    videoChanged = Signal()
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
        # The level before a mute, for the same key to give back.
        self._unmuted = 0
        stored = db.get_int("video_volume", VOLUME_DEFAULT) if db else VOLUME_DEFAULT
        self._volume = max(0, min(100, int(stored)))
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

    track = Property("QVariantMap", _get_track, notify=trackChanged)
    playing = Property(bool, _get_playing, notify=stateChanged)
    loading = Property(bool, _get_loading, notify=stateChanged)
    hasQueue = Property(bool, _get_has_queue, notify=queueChanged)
    isLive = Property(bool, _get_is_live, notify=trackChanged)
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
        self.queueChanged.emit()
        self.trackChanged.emit()
        self.stateChanged.emit()
        self.progressChanged.emit()
        if had:
            self.stopped.emit()

    # ---- playing ---------------------------------------------------------

    def _height(self) -> int:
        return ceiling_for(self._screen_height) if self._screen_height else FALLBACK_HEIGHT

    @Slot(int)
    def setScreenHeight(self, pixels: int) -> None:
        """How tall the screen the window is on is, in its real pixels. The
        picture is never fetched taller than that."""
        pixels = int(pixels)
        if pixels > 0 and pixels != self._screen_height:
            self._screen_height = pixels
            self.stateChanged.emit()

    def _start_current(self) -> None:
        entry = self._current()
        if not entry:
            return
        self._stop_finder()
        self._ended = False
        self._pos = 0.0
        self._dur = 0.0
        self._counted = ""
        self._saved_at = 0.0
        self._finding = True
        self.trackChanged.emit()
        self.stateChanged.emit()
        self.progressChanged.emit()
        key = entry.get("key", "")
        height = self._height()
        cached = self._addresses.get(f"{key}@{height}")
        if cached:
            picture, _, sound = cached.partition(" ")
            self._hand_over(entry, picture, sound)
            return
        finder = _Finder(self._cfg, key, entry.get("url", ""), height,
                         bool(entry.get("live")), self)
        finder.found.connect(self._on_found)
        finder.failed.connect(self._on_failed)
        finder.gone.connect(self._on_gone)
        finder.finished.connect(self._sweep_finders)
        self._finder = finder
        self._finders.append(finder)
        trace.mark("video_finding", key=key, height=height)
        finder.start()

    def _on_found(self, key: str, picture: str, sound: str, chapters: list,
                  facts: dict) -> None:
        if chapters:
            self._chapters[key] = tuple(chapters)
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
        if start is None and not entry.get("live"):
            start = self._resume_point(entry.get("key", ""))
        self._paused = False
        self._engine.set_video(True)
        if sound:
            self._engine.load(sound, start, video=picture)
        else:
            self._engine.load(picture, start)
        self._engine.set_pause(False)
        self._engine.set_speed(self._speed)
        self.stateChanged.emit()

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
        entry = self._current()
        if entry:
            trace.mark("video_started", key=entry.get("key", ""))
            self.started.emit(entry.get("key", ""))

    def _on_position(self, seconds: float) -> None:
        self._pos = float(seconds)
        self._count_watched()
        self.progressChanged.emit()

    def _on_duration(self, seconds: float) -> None:
        self._dur = float(seconds or 0.0)
        self.progressChanged.emit()

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

    @Slot(bool)
    def setPaused(self, paused: bool) -> None:
        if not self._current():
            return
        self._paused = bool(paused)
        self._engine.set_pause(self._paused)
        if self._paused:
            self._keep_position()
        self.stateChanged.emit()

    @Slot()
    def replay(self) -> None:
        if not self._current():
            return
        self._ended = False
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

    def shutdown(self) -> None:
        self._keep_position()
        self._keeper.stop()
        for finder in list(self._finders):
            if finder.isRunning():
                finder.cancel()
        for finder in list(self._finders):
            if finder.isRunning():
                finder.wait(5000)
        self._engine.quit()
