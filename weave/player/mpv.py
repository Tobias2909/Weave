"""Handoff to mpv, and watched detection by observing its IPC socket.

Two decisions worth knowing before changing anything here.

Weave calls the existing mpv-ff2mpv-single.sh wrapper rather than building its
own mpv command line. The wrapper already canonicalizes URLs, strips the &t=
parameter that otherwise breaks mpv's resume, resolves Twitch through
streamlink, hands the channel login to the chat overlay, expands playlists,
caps mixes and reuses one instance. Duplicating that here would mean two
implementations of the same logic drifting apart.

Weave detects what was watched by connecting to the wrapper's IPC socket as a
second client, not by shipping an mpv Lua script. The wrapper builds its own
argument list and does not forward extra arguments, so a script cannot be
injected through it, and adding one to the mpv config repository would couple
two projects that are better left independent. Observing the socket needs
neither. mpv accepts several concurrent IPC clients.
"""

from __future__ import annotations

import json
import shlex
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .. import ids, paths
from ..config import Config

WRAPPER_NAME = "mpv-ff2mpv-single.sh"
DEFAULT_SOCKET = "mpv-ff2mpv.sock"

# Property ids used with observe_property. Any stable integers would do.
_OBS_PATH = 1
_OBS_DURATION = 2
_OBS_TIME_POS = 3
_OBS_SEEKABLE = 4


class PlayerNotFound(RuntimeError):
    pass


def resolve_command(cfg: Config) -> list[str]:
    """Prefer the wrapper, fall back to plain mpv.

    The fallback is what lets Weave work on a machine that has never seen the
    mpv config repository. Playback there loses the wrapper's extras but works.
    """
    configured = cfg.player_command
    if configured and configured != "auto":
        parts = shlex.split(configured)
        if parts and (shutil.which(parts[0]) or Path(parts[0]).expanduser().exists()):
            return [str(Path(parts[0]).expanduser()), *parts[1:]]
        raise PlayerNotFound(f"configured player not found: {configured}")

    wrapper = shutil.which(WRAPPER_NAME)
    if wrapper:
        return [wrapper]
    mpv = shutil.which("mpv")
    if mpv:
        return [mpv]
    raise PlayerNotFound("neither " + WRAPPER_NAME + " nor mpv is on PATH")


def resolve_socket(cfg: Config) -> Path:
    configured = cfg.ipc_socket
    if configured and configured != "auto":
        return paths.expand(configured)
    return paths.runtime_dir() / DEFAULT_SOCKET


class _IpcWatcher(QThread):
    """Reads mpv's JSON IPC and reports what finished.

    Watched is decided here rather than by mpv, so the rule is Weave's own.
    Reaching the end always counts. Otherwise the highest playback position
    seen, divided by the duration, has to reach the configured threshold.

    A live stream is never marked, and guarding that needs care. mpv reports a
    duration for one, but it is the length of the sliding window rather than of
    the stream, measured at about fifteen seconds, so a few seconds of watching
    already looks like most of the video and the stream is marked watched
    almost at once. Two independent guards catch it. Weave says so when it
    starts one itself, and mpv reports a live stream as not seekable, which
    covers a stream started from somewhere else.
    """

    nowPlaying = Signal(str, str)     # key, media title
    watched = Signal(str, float)      # key, progress
    connectionChanged = Signal(bool)

    def __init__(self, socket_path: Path, threshold: float, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._socket_path = socket_path
        self._threshold = threshold
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._hint_lock = threading.Lock()
        self._twitch_hint: str | None = None

        self._key: str | None = None
        self._title = ""
        self._duration: float | None = None
        self._seekable: bool | None = None
        # Set before a handoff and consumed by the file that follows, so it
        # applies to what Weave started and not to whatever mpv moves on to by
        # itself. Clearing it on a path change instead would clear it before
        # the file it was meant for had even loaded.
        self._pending_live = False
        self._live_current = False
        self._max_pos = 0.0
        self._reported: set[str] = set()
        self._last_whole_second = -1

    def set_live_hint(self, live: bool) -> None:
        """Told by Weave when it hands over something it knows is live."""
        with self._hint_lock:
            self._pending_live = live

    def set_twitch_hint(self, login: str | None) -> None:
        """A resolved Twitch playlist names the channel nowhere, so the login
        Weave handed to mpv is the only way to identify it."""
        with self._hint_lock:
            self._twitch_hint = login

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    # ---- main loop -------------------------------------------------------

    def run(self) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            if not self._socket_path.exists():
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 5.0)
                continue
            try:
                self._session()
                backoff = 0.5
            except OSError:
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 5.0)

    def _session(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(str(self._socket_path))
        self._sock = sock
        self.connectionChanged.emit(True)
        try:
            self._send(sock, {"command": ["observe_property", _OBS_PATH, "path"]})
            self._send(sock, {"command": ["observe_property", _OBS_DURATION, "duration"]})
            self._send(sock, {"command": ["observe_property", _OBS_TIME_POS, "time-pos"]})
            self._send(sock, {"command": ["observe_property", _OBS_SEEKABLE, "seekable"]})
            self._read_forever(sock)
        finally:
            self.connectionChanged.emit(False)
            self._sock = None
            try:
                sock.close()
            except OSError:
                pass

    @staticmethod
    def _send(sock: socket.socket, payload: dict) -> None:
        sock.sendall(json.dumps(payload).encode() + b"\n")

    def _read_forever(self, sock: socket.socket) -> None:
        buffer = b""
        while not self._stop.is_set():
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line.strip():
                    try:
                        self._handle(json.loads(line))
                    except (ValueError, KeyError):
                        continue

    # ---- event handling --------------------------------------------------

    def _handle(self, message: dict) -> None:
        event = message.get("event")
        if event == "property-change":
            self._on_property(message.get("name"), message.get("data"))
        elif event == "end-file":
            self._flush(reached_end=message.get("reason") == "eof")
        elif event in ("shutdown", "idle"):
            self._flush(reached_end=False)

    def _on_property(self, name: str | None, data) -> None:
        if name == "path":
            self._on_new_path(data)
        elif name == "duration":
            self._duration = float(data) if isinstance(data, (int, float)) and data > 0 else None
        elif name == "seekable":
            self._seekable = data if isinstance(data, bool) else None
        elif name == "time-pos":
            if not isinstance(data, (int, float)):
                return
            # time-pos arrives around 24 times a second. Only act when the
            # whole second changes, so a two hour video costs a few thousand
            # cheap comparisons instead of a few hundred thousand.
            self._max_pos = max(self._max_pos, float(data))
            whole = int(data)
            if whole == self._last_whole_second:
                return
            self._last_whole_second = whole
            self._check_threshold()

    def _on_new_path(self, path) -> None:
        self._flush(reached_end=False)
        self._duration = None
        self._seekable = None
        self._max_pos = 0.0
        self._last_whole_second = -1
        if not isinstance(path, str):
            self._key = None
            return
        with self._hint_lock:
            hint = self._twitch_hint
            self._live_current = self._pending_live
            self._pending_live = False
        self._key = ids.key_for_media_path(path, twitch_hint=hint)
        if self._key:
            self.nowPlaying.emit(self._key, self._title or "")

    def _progress(self) -> float | None:
        if not self._duration:
            return None
        return min(1.0, self._max_pos / self._duration)

    def _is_live(self) -> bool:
        """Either guard is enough. Weave knows what it started, and mpv knows
        that a live stream cannot be seeked."""
        with self._hint_lock:
            hinted = self._live_current or self._pending_live
        return hinted or self._seekable is False

    def _check_threshold(self) -> None:
        if self._is_live():
            return
        progress = self._progress()
        if self._key and progress is not None and progress >= self._threshold:
            self._report(progress)

    def _flush(self, reached_end: bool) -> None:
        # Reaching the end of a live stream means the broadcast stopped, not
        # that it was watched.
        if not self._key or self._is_live():
            return
        progress = self._progress()
        if reached_end:
            self._report(progress if progress is not None else 1.0)
        elif progress is not None and progress >= self._threshold:
            self._report(progress)

    def _report(self, progress: float) -> None:
        if self._key in self._reported:
            return
        self._reported.add(self._key)
        self.watched.emit(self._key, progress)


class Player(QObject):
    """Public playback surface. Owns the handoff and the watcher."""

    nowPlaying = Signal(str, str)
    watched = Signal(str, float)
    connectionChanged = Signal(bool)
    failed = Signal(str)

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._command: list[str] | None = None
        self._error: str | None = None
        try:
            self._command = resolve_command(cfg)
        except PlayerNotFound as exc:
            self._error = str(exc)

        self._watcher = _IpcWatcher(resolve_socket(cfg), cfg.watched_threshold, self)
        self._watcher.nowPlaying.connect(self.nowPlaying)
        self._watcher.watched.connect(self.watched)
        self._watcher.connectionChanged.connect(self.connectionChanged)

    @property
    def command(self) -> list[str] | None:
        return self._command

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> None:
        self._watcher.start()

    def stop(self) -> None:
        self._watcher.stop()
        self._watcher.wait(3000)

    def play(self, url: str, twitch_login: str | None = None, live: bool = False) -> bool:
        if not self._command:
            self.failed.emit(self._error or "no player configured")
            return False
        self._watcher.set_twitch_hint(twitch_login)
        self._watcher.set_live_hint(live)
        try:
            subprocess.Popen(
                [*self._command, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError as exc:
            self.failed.emit(f"could not start the player: {exc}")
            return False
