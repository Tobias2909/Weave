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

from PySide6.QtCore import Property, QObject, QThread, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .config import Config
from .cookies import args as cookie_args
from .process import Cancelled, Timeout, run as run_process

# A live stream is only offered as picture and sound together, and the sound
# gets better as the picture does. This variant is the sensible middle.
LIVE_FORMAT = "93"
MUSIC_FORMAT = "bestaudio"


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
        self._player.errorOccurred.connect(
            lambda _e, message: self.failed.emit(message or "playback failed"))

        self._shuffle = (db.get_state("music_shuffle", "0") == "1") if db else False
        self._repeat = (db.get_state("music_repeat", "0") == "1") if db else False
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
        return int(round(self._output.volume() * 100))

    def _get_shuffle(self) -> bool:
        return self._shuffle

    def _get_repeat(self) -> bool:
        return self._repeat

    def _get_auto_pause(self) -> bool:
        return self._auto_pause

    def _get_queue_length(self) -> int:
        return len(self._queue)

    def _get_upcoming(self) -> list:
        """What follows, in the order it will actually be played, which is not
        the order of the queue once shuffle is on."""
        if not self._queue or self._at not in self._order:
            return []
        place = self._order.index(self._at)
        following = self._order[place + 1:]
        if self._repeat and not following:
            following = self._order[:place]
        return [{
            "title": self._queue[i].get("title", ""),
            "artist": self._queue[i].get("artist", ""),
            "thumbnail": self._queue[i].get("thumbnail", ""),
        } for i in following[:40]]

    track = Property("QVariantMap", _get_track, notify=trackChanged)
    playing = Property(bool, _get_playing, notify=stateChanged)
    loading = Property(bool, _get_loading, notify=stateChanged)
    hasQueue = Property(bool, _get_has_queue, notify=trackChanged)
    position = Property(float, _get_position, notify=progressChanged)
    elapsed = Property(int, _get_elapsed, notify=progressChanged)
    length = Property(int, _get_length, notify=progressChanged)
    volume = Property(int, _get_volume, notify=stateChanged)
    shuffle = Property(bool, _get_shuffle, notify=stateChanged)
    repeat = Property(bool, _get_repeat, notify=stateChanged)
    autoPause = Property(bool, _get_auto_pause, notify=stateChanged)
    queueLength = Property(int, _get_queue_length, notify=trackChanged)
    upcoming = Property("QVariantList", _get_upcoming, notify=trackChanged)

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
        self._player.play()
        self.stateChanged.emit()

    def _on_resolve_failed(self, key: str, message: str) -> None:
        self._loading = False
        self.stateChanged.emit()
        self.failed.emit(message)

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next()

    @Slot()
    def toggle(self) -> None:
        if self._get_playing():
            self._player.pause()
        elif self._queue:
            if self._player.source().isEmpty():
                self._start_current()
            else:
                self._player.play()
        self.stateChanged.emit()

    @Slot()
    def next(self) -> None:
        if not self._queue:
            return
        place = self._order.index(self._at) if self._at in self._order else -1
        if place + 1 < len(self._order):
            self._at = self._order[place + 1]
        elif self._repeat:
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

    @Slot(int)
    def setVolume(self, value: int) -> None:
        value = max(0, min(100, int(value)))
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

    @Slot(bool)
    def setRepeat(self, value: bool) -> None:
        self._repeat = bool(value)
        if self._db is not None:
            self._db.set_state("music_repeat", "1" if value else "0")
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
        never what anyone wanted."""
        if self._auto_pause and self._get_playing():
            self._player.pause()
            self.stateChanged.emit()

    def shutdown(self) -> None:
        if self._resolver is not None and self._resolver.isRunning():
            self._resolver.cancel()
            self._resolver.wait(5000)
        self._player.stop()
