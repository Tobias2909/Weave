"""Music played inside Weave rather than handed to mpv.

Video goes to mpv because that is the whole point of the application. Audio does
not, because a separate window for a song makes no sense, so it is played here.

Nothing is downloaded. yt-dlp resolves a stream address and Qt's own player
takes it from there, which reaches the same Premium quality the rest of the
setup gets, measured at 257 kb/s opus. A live stream has no audio only form at
all, so one of its muxed variants is played with no video sink attached and the
picture is simply discarded.
"""

from __future__ import annotations

import random
import threading

from PySide6.QtCore import (Property, QEasingCurve, QObject, QPropertyAnimation, QThread,
                            QUrl, Signal, Slot)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .config import Config
from .cookies import args as cookie_args
from .process import Cancelled, Timeout, run as run_process

# A live stream is only offered as picture and sound together, and the sound
# gets better as the picture does. This variant is the sensible middle.
LIVE_FORMAT = "93"
MUSIC_FORMAT = "bestaudio"

# Long enough to hear as a fade rather than a cut, short enough not to be a
# wait before the video starts.
FADE_MS = 1400

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2


class _Resolver(QThread):
    """Turns one entry into a playable address."""

    resolved = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, cfg: Config, key: str, url: str, live: bool,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._key = key
        self._url = url
        self._live = live
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        command = ["yt-dlp", "--no-warnings", *cookie_args(self._cfg),
                   "-f", LIVE_FORMAT if self._live else MUSIC_FORMAT,
                   "--get-url", self._url]
        try:
            result = run_process(command, cancel=self._cancel, timeout=180)
        except Cancelled:
            return
        except (FileNotFoundError, Timeout) as exc:
            self.failed.emit(self._key, str(exc) or "could not resolve the track")
            return
        address = next((line for line in result.stdout.splitlines() if line.startswith("http")), "")
        if not address:
            tail = (result.stderr or "").strip().splitlines()
            self.failed.emit(self._key, (tail[-1] if tail else "no stream came back")[:200])
            return
        self.resolved.emit(self._key, address)


class AudioPlayer(QObject):
    trackChanged = Signal()
    stateChanged = Signal()
    progressChanged = Signal()
    failed = Signal(str)

    def __init__(self, cfg: Config, db=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._db = db
        self._queue: list[dict] = []
        self._order: list[int] = []
        self._at = -1
        self._loading = False
        self._resolver: _Resolver | None = None

        self._output = QAudioOutput(self)
        stored = int(db.get_state("music_volume", "70") or 70) if db else 70
        self._output.setVolume(max(0.0, min(1.0, stored / 100)))
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.positionChanged.connect(self.progressChanged)
        self._player.durationChanged.connect(self.progressChanged)
        self._player.playbackStateChanged.connect(lambda _s: self.stateChanged.emit())
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)
        # A stream address is signed and can be dropped part way through, which
        # arrives as a demux failure and stops the music. One silent retry per
        # track resolves a fresh address and picks up where it left off.
        self._recovering = False
        self._resume_at = 0

        self._shuffle = (db.get_state("music_shuffle", "0") == "1") if db else False
        # Off, the whole queue, or the one track. A queue that repeats and a
        # track that repeats are different wants, and one switch cannot say
        # which, so it cycles through all three.
        stored_repeat = (db.get_state("music_repeat", "0") if db else "0") or "0"
        self._repeat_mode = int(stored_repeat) if stored_repeat.isdigit() else 0
        self._repeat_mode = max(0, min(2, self._repeat_mode))

        # Volume is faded rather than cut, so a video starting does not chop
        # the music off mid note.
        self._fade = QPropertyAnimation(self._output, b"volume", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade.finished.connect(self._on_fade_done)
        self._pause_after_fade = False
        self._level = self._output.volume()
        self._auto_pause = (db.get_state("music_autopause", "1") != "0") if db else True

    # ---- what QML reads --------------------------------------------------

    def _current(self) -> dict:
        if 0 <= self._at < len(self._queue):
            return self._queue[self._at]
        return {}

    def _get_track(self) -> dict:
        return dict(self._current())

    def _get_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def _get_loading(self) -> bool:
        return self._loading

    def _get_has_queue(self) -> bool:
        return bool(self._queue)

    def _get_position(self) -> float:
        span = self._player.duration()
        return (self._player.position() / span) if span > 0 else 0.0

    def _get_elapsed(self) -> int:
        return int(self._player.position() // 1000)

    def _get_length(self) -> int:
        return int(self._player.duration() // 1000)

    def _get_volume(self) -> int:
        # What was asked for, not what a fade happens to be passing through.
        return int(round(self._level * 100))

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
            "current": i == self._at,
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
    volume = Property(int, _get_volume, notify=stateChanged)
    shuffle = Property(bool, _get_shuffle, notify=stateChanged)
    repeat = Property(int, _get_repeat, notify=stateChanged)
    repeatLabel = Property(str, _get_repeat_label, notify=stateChanged)
    autoPause = Property(bool, _get_auto_pause, notify=stateChanged)
    queueLength = Property(int, _get_queue_length, notify=trackChanged)
    queue = Property("QVariantList", _get_queue, notify=trackChanged)
    stillToCome = Property(int, _get_still_to_come, notify=trackChanged)

    # ---- playing ---------------------------------------------------------

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
        self._start_current()

    def _rebuild_order(self) -> None:
        self._order = list(range(len(self._queue)))
        if self._shuffle:
            random.shuffle(self._order)

    def _start_current(self) -> None:
        entry = self._current()
        if not entry:
            return
        self._player.stop()
        self._loading = True
        if not self._recovering:
            self._resume_at = 0
        self.trackChanged.emit()
        self.stateChanged.emit()
        if self._resolver is not None and self._resolver.isRunning():
            self._resolver.cancel()
        self._resolver = _Resolver(self._cfg, entry["key"], entry["url"],
                                   bool(entry.get("live")), self)
        self._resolver.resolved.connect(self._on_resolved)
        self._resolver.failed.connect(self._on_resolve_failed)
        self._resolver.start()

    def _on_resolved(self, key: str, address: str) -> None:
        if self._current().get("key") != key:
            return                       # a later choice overtook this one
        self._loading = False
        self._player.setSource(QUrl(address))
        if self._resume_at > 0:
            # Set once the source has enough to seek in.
            self._player.setPosition(self._resume_at)
            self._resume_at = 0
        self._start_playing()
        self.stateChanged.emit()

    def _on_resolve_failed(self, key: str, message: str) -> None:
        self._loading = False
        self.stateChanged.emit()
        self.failed.emit(message)

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._recovering = False
            if self._repeat_mode == REPEAT_ONE:
                self._player.setPosition(0)
                self._start_playing()
                return
            self.next()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._recover()

    def _on_error(self, _error, message: str) -> None:
        if self._recover():
            return
        self.failed.emit(message or "playback failed")

    def _recover(self) -> bool:
        """Fetch a fresh address and carry on from the same place.

        Returns whether it is being handled, so a first failure is quiet and a
        second one is reported rather than looping.
        """
        if self._recovering or not self._current():
            return False
        self._recovering = True
        self._resume_at = self._player.position()
        self._start_current()
        return True

    @Slot()
    def toggle(self) -> None:
        if self._get_playing():
            self._fade_to(0.0, pause_after=True)
            return
        if self._queue:
            if self._player.source().isEmpty():
                self._start_current()
            else:
                # Comes back up rather than arriving at full volume.
                self._fade.stop()
                self._pause_after_fade = False
                self._output.setVolume(0.0)
                self._player.play()
                self._fade_to(self._level, pause_after=False)
        self.stateChanged.emit()

    @Slot(int)
    def jumpTo(self, index: int) -> None:
        """Skip straight to something further down the queue."""
        if 0 <= index < len(self._queue) and index != self._at:
            self._recovering = False
            self._at = index
            self._start_current()

    @Slot()
    def next(self) -> None:
        if not self._queue:
            return
        place = self._order.index(self._at) if self._at in self._order else -1
        if place + 1 < len(self._order):
            self._at = self._order[place + 1]
        elif self._repeat_mode == REPEAT_ALL:
            self._at = self._order[0]
        else:
            self._player.stop()
            self.stateChanged.emit()
            return
        self._start_current()

    @Slot()
    def previous(self) -> None:
        if not self._queue:
            return
        # Within the first few seconds this goes back a track, later it
        # restarts the current one, which is what every music player does.
        if self._player.position() > 4000:
            self._player.setPosition(0)
            return
        place = self._order.index(self._at) if self._at in self._order else 0
        self._at = self._order[max(0, place - 1)]
        self._start_current()

    @Slot(float)
    def seek(self, fraction: float) -> None:
        span = self._player.duration()
        if span > 0:
            self._player.setPosition(int(max(0.0, min(1.0, fraction)) * span))

    @Slot(int)
    def nudgeVolume(self, steps: int) -> None:
        """One wheel notch is five, which is small enough to tune with and big
        enough to be worth a notch."""
        self.setVolume(self._get_volume() + steps * 5)

    def _start_playing(self) -> None:
        """Play at the level that was asked for.

        A pause leaves the volume down on purpose, since restoring it while
        the player is still stopping is heard as a blip, so anything that
        starts playing has to raise it again.
        """
        self._fade.stop()
        self._pause_after_fade = False
        self._output.setVolume(self._level)
        self._player.play()

    def _fade_to(self, level: float, pause_after: bool) -> None:
        self._fade.stop()
        self._pause_after_fade = pause_after
        self._fade.setStartValue(self._output.volume())
        self._fade.setEndValue(max(0.0, min(1.0, level)))
        self._fade.start()

    def _on_fade_done(self) -> None:
        if self._pause_after_fade:
            self._pause_after_fade = False
            self._player.pause()
            # The volume stays down. Pausing is asynchronous, so putting the
            # level back here plays whatever is still in the buffer at full
            # volume for a moment, which is heard as a blip right at the end
            # of the fade. Every path that starts playing raises it instead.
            self.stateChanged.emit()

    @Slot(int)
    def setVolume(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self._fade.stop()
        self._pause_after_fade = False
        self._level = value / 100
        self._output.setVolume(value / 100)
        if self._db is not None:
            self._db.set_state("music_volume", str(value))
        self.stateChanged.emit()

    @Slot(bool)
    def setShuffle(self, value: bool) -> None:
        self._shuffle = bool(value)
        if self._db is not None:
            self._db.set_state("music_shuffle", "1" if value else "0")
        current = self._at
        self._rebuild_order()
        if current in self._order and self._shuffle:
            self._order = [current] + [i for i in self._order if i != current]
        self.stateChanged.emit()

    @Slot()
    def cycleRepeat(self) -> None:
        self._repeat_mode = (self._repeat_mode + 1) % 3
        if self._db is not None:
            self._db.set_state("music_repeat", str(self._repeat_mode))
        self.stateChanged.emit()

    @Slot(int)
    def setRepeat(self, mode: int) -> None:
        self._repeat_mode = max(0, min(2, int(mode)))
        if self._db is not None:
            self._db.set_state("music_repeat", str(self._repeat_mode))
        self.stateChanged.emit()

    @Slot(bool)
    def setAutoPause(self, value: bool) -> None:
        self._auto_pause = bool(value)
        if self._db is not None:
            self._db.set_state("music_autopause", "1" if value else "0")
        self.stateChanged.emit()

    @Slot()
    def stop(self) -> None:
        self._player.stop()
        self._queue = []
        self._order = []
        self._at = -1
        self.trackChanged.emit()
        self.stateChanged.emit()

    def pause_for_video(self) -> None:
        """Called when mpv starts something. Two things playing at once is
        never what anyone wanted, but neither is being cut off mid note."""
        if self._auto_pause and self._get_playing():
            self._fade_to(0.0, pause_after=True)

    def shutdown(self) -> None:
        if self._resolver is not None and self._resolver.isRunning():
            self._resolver.cancel()
            self._resolver.wait(5000)
        self._player.stop()
