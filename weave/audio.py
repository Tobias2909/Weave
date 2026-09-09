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
from .engine import CURRENT, NEXT, MusicEngine
from .imagecache import plain_source
from .process import Cancelled, Timeout
from .process import run as run_process

# A live stream is only offered as picture and sound together, and the sound
# gets better as the picture does. This variant is the sensible middle.
LIVE_FORMAT = "93"
MUSIC_FORMAT = "bestaudio"

# Long enough to hear as a fade rather than a cut, short enough not to be a
# wait before the video starts.
FADE_MS = 500

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

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2


@dataclass(frozen=True)
class Resolved:
    """What one resolve came back with. The address is the point of it; the
    chapters ride along in the same call and cost nothing."""

    address: str
    chapters: tuple[dict, ...] = ()


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


def resolve_address(cfg: Config, url: str, live: bool,
                    cancel: threading.Event | None = None) -> Resolved:
    """One entry to one playable address, blocking. Takes a few seconds.

    The chapters come back in the same call, which is the whole reason they
    are worth having: a video that is really an album has its tracks marked in
    them, and asking separately would be another few seconds per song.
    """
    command = ["yt-dlp", "--no-warnings", *cookie_args(cfg),
               "-f", LIVE_FORMAT if live else MUSIC_FORMAT,
               "--get-url", "--print", "%(chapters)j", url]
    result = run_process(command, cancel=cancel, timeout=180)
    for line in result.stdout.splitlines():
        if line.startswith("http"):
            return Resolved(line, parse_chapters(result.stdout))
    tail = (result.stderr or "").strip().splitlines()
    raise _NoAddress((tail[-1] if tail else "no stream came back")[:200])


def address_expiry(address: str) -> float | None:
    """When a signed googlevideo address stops working, as a unix time, or
    None when the address does not say."""
    stamp = parse_qs(urlparse(address).query).get("expire", [""])[0]
    return float(stamp) if stamp.isdigit() else None


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

    resolved = Signal(str, str, list)
    failed = Signal(str, str)

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
            self.failed.emit(self.key, str(exc) or "could not resolve the track")
            return
        self.resolved.emit(self.key, found.address, list(found.chapters))


class AudioPlayer(QObject):
    trackChanged = Signal()
    # The queue as a list changes far less often than the track does. Bound to
    # trackChanged, a twenty six row popup was rebuilt every time playback
    # moved, which resets the view and throws away delegates it was still
    # building. What is playing is a number now, read beside the list.
    queueChanged = Signal()
    stateChanged = Signal()
    progressChanged = Signal()
    failed = Signal(str)

    def __init__(self, cfg: Config, db=None, parent: QObject | None = None,
                 engine: MusicEngine | None = None) -> None:
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
        # Which queue index mpv holds as its next entry, if any.
        self._appended: int | None = None

        self._engine = engine if engine is not None else MusicEngine(self)
        self._engine.positionChanged.connect(self._on_position)
        self._engine.durationChanged.connect(self._on_duration)
        self._engine.pausedChanged.connect(self._on_paused)
        self._engine.idleChanged.connect(self._on_idle)
        self._engine.bufferingChanged.connect(self._on_buffering)
        self._engine.started.connect(self._on_started)
        self._engine.ended.connect(self._on_ended)
        self._engine.gone.connect(self._on_gone)
        self._pos = 0.0
        self._dur = 0.0
        self._paused = True
        self._idle = True
        self._buffering = False

        stored = db.get_int("music_volume", 70) if db else 70
        self._level = max(0.0, min(1.0, stored / 100))
        self._output = self._level          # what mpv has been told, fades included
        self._engine.set_volume(self._level * 100)

        self._recovering = False
        self._resume_at = 0.0
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

    def play_items(self, items: list[dict], start: int = 0) -> None:
        """Queue a list and begin. Each entry needs a key, a title and a url,
        and may say that it is live."""
        self._queue = [dict(item) for item in items if item.get("url")]
        if not self._queue:
            return
        self._rebuild_order()
        self._at = max(0, min(start, len(self._queue) - 1))
        if self._shuffle:
            # Whatever was picked stays first, the rest are shuffled behind it.
            self._order = [self._at] + [i for i in self._order if i != self._at]
        self._forget_recovery()
        self.queueChanged.emit()
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
            entry.get("duration_s"))

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
            self._resume_at = 0.0
        self._pos = 0.0
        self._dur = 0.0
        self._remember(entry)
        self.trackChanged.emit()
        self.progressChanged.emit()
        if self._resolver is not None and self._resolver.isRunning():
            self._resolver.cancel()
        address = None if entry.get("live") else self._addresses.get(entry["key"])
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
        self._resolver.start()

    def _on_resolved(self, key: str, address: str, chapters: list | None = None) -> None:
        # Kept whoever it was for. A resolve that arrives after the choice has
        # moved on still learned where that track's songs are, and it will be
        # wanted the moment anybody goes back to it.
        if chapters:
            self._chapters[key] = tuple(chapters)
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

    # ---- the track after this one ----------------------------------------

    def _prepare_next(self) -> None:
        """Make sure mpv holds the right next entry, and nothing else.

        Resolving is the only wait in the whole chain, so it is done now,
        while there are minutes to spare, rather than when the track ends.
        """
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
        address = None if entry.get("live") else self._addresses.get(entry["key"])
        if address:
            self._engine.append(address)
            self._appended = wanted
            return
        if any(r.key == entry["key"] and r.isRunning() for r in self._next_resolvers):
            return
        resolver = self._make_resolver(entry)
        resolver.resolved.connect(self._on_next_resolved)
        resolver.finished.connect(self._sweep_resolvers)
        self._next_resolvers.append(resolver)
        resolver.start()

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

    def _sweep_resolvers(self) -> None:
        self._next_resolvers = [r for r in self._next_resolvers if r.isRunning()]

    # ---- what mpv reports ------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        before = int(self._pos * 10)
        self._pos = seconds
        if int(seconds * 10) != before:
            self.progressChanged.emit()

    def _on_duration(self, seconds: float) -> None:
        self._dur = seconds
        self.progressChanged.emit()

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
            self._dur = 0.0
            self._engine.remove_before()
            self.trackChanged.emit()
            self.progressChanged.emit()
            self._prepare_next()
        elif role == CURRENT:
            self._stall_timer.stop()
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
            self._fade_to(0.0, pause_after=True)
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
                self._fade_to(self._level, pause_after=False)
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
        # What mpv holds as the next file was decided before this arrived.
        if play_next and not self._idle:
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
        self._queue.pop(index)
        self._order = [i - 1 if i > index else i
                       for i in self._order if i != index]
        if was_current:
            if following is None:
                self.stop()
                return
            self._at = following - 1 if following > index else following
            self._forget_recovery()
            self._start_current()
        elif index < self._at:
            self._at -= 1
        elif not self._idle:
            # It was one still to come, so what mpv holds as next may have
            # been the one that just went.
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

    def _fade_to(self, level: float, pause_after: bool) -> None:
        self._fade.stop()
        self._pause_after_fade = pause_after
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
        for resolver in [self._resolver, *self._next_resolvers]:
            if resolver is not None and resolver.isRunning():
                resolver.cancel()
        for resolver in [self._resolver, *self._next_resolvers]:
            if resolver is not None and resolver.isRunning():
                resolver.wait(5000)
        self._engine.quit()
