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


def find_wrapper() -> str | None:
    """The single instance wrapper, whether or not PATH mentions it.

    PATH is not the same everywhere Weave is started from. A shell has read a
    profile and has ~/.local/bin on it; a desktop entry is started from the
    session, whose PATH is the bare system one, so the wrapper is invisible
    there. Weave then fell back to plain mpv without a word, and every video
    opened a window of its own instead of being handed to the one already
    playing, with nothing on its IPC socket to watch, so nothing was ever
    marked watched either.

    So the usual place is looked in by name as well.
    """
    found = shutil.which(WRAPPER_NAME)
    if found:
        return found
    candidate = paths.bin_home() / WRAPPER_NAME
    if candidate.is_file():
        return str(candidate)
    return None


def resolve_command(cfg: Config) -> list[str]:
    """Prefer the wrapper, fall back to plain mpv.

    The fallback is what lets Weave work on a machine that has never seen the
    mpv config repository. Playback there loses the wrapper's extras, which
    includes reusing one window, so it is the second choice and not a quiet
    equal of the first.
    """
    configured = cfg.player_command
    if configured and configured != "auto":
        parts = shlex.split(configured)
        if parts and (shutil.which(parts[0]) or Path(parts[0]).expanduser().exists()):
            return [str(Path(parts[0]).expanduser()), *parts[1:]]
        raise PlayerNotFound(f"configured player not found: {configured}")

    wrapper = find_wrapper()
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
    duration for one, but it is the window that can be seeked rather than the
    length of the stream, and the position starts at the live edge, so a few
    seconds of watching already looks like all of the video. Three independent
    guards catch it. Weave says so when it starts one itself; mpv reports a
    stream with no rewind at all as not seekable; and a live stream's duration
    grows while it plays, which a recording's never does.

    The third is the one that matters in practice. YouTube gives a live stream
    a rewind window, so it is seekable, and a stream that went live since the
    last poll is pressed as an ordinary video, so neither of the first two
    fires. Growth takes a few seconds to show, which is why nothing is marked
    in the first seconds of a file at all.
    """

    # Nothing is marked before this much of a file has played. A live stream's
    # duration grows by a second a second, so a few seconds is enough to tell
    # it from a recording, and no ordinary video is decided in that time
    # either: reaching the end is a separate path and is not held back.
    GRACE_S = 20.0
    # Duration wobbles by a frame or two on some containers, so growth means
    # growth rather than any change at all.
    GROWTH_S = 3.0

    nowPlaying = Signal(str, str)     # key, media title
    watched = Signal(str, float)      # key, progress
    connectionChanged = Signal(bool)
    stopped = Signal()                # mpv went away

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
        # The first duration this file reported and whether it has grown since.
        # A recording's is fixed; a live stream's climbs as it is broadcast.
        self._first_duration: float | None = None
        self._duration_grew = False
        # The first position seen in this file, so the grace below is time
        # played rather than time since mpv started.
        self._first_pos: float | None = None
        self._had_session = False

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
        """Reconnects for as long as it is wanted.

        A player that has gone away is noticed by the reconnect being refused,
        not by the socket file disappearing. mpv leaves that file behind when
        it exits, so its presence proves nothing, while connecting to it raises
        a connection refused straight away.
        """
        backoff = 0.5
        while not self._stop.is_set():
            if not self._socket_path.exists():
                self._announce_gone()
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 5.0)
                continue
            try:
                self._session()
                # A session that simply ended may be a hiccup, so the next
                # connection attempt is what decides.
                backoff = 0.5
            except OSError:
                self._announce_gone()
                self._stop.wait(backoff)
                backoff = min(backoff * 1.5, 5.0)

    def _announce_gone(self) -> None:
        if not self._had_session:
            return
        self._had_session = False
        self._key = None
        self.stopped.emit()

    def _session(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(str(self._socket_path))
        self._sock = sock
        self._had_session = True
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
            except TimeoutError:
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
        elif event == "shutdown":
            # A clean exit says so. A killed one does not, which is what the
            # refused reconnect covers.
            self._flush(reached_end=False)
            self._announce_gone()
        elif event == "idle":
            self._flush(reached_end=False)

    def _on_property(self, name: str | None, data) -> None:
        if name == "path":
            self._on_new_path(data)
        elif name == "duration":
            self._duration = float(data) if isinstance(data, (int, float)) and data > 0 else None
            if self._duration is None:
                return
            if self._first_duration is None:
                self._first_duration = self._duration
            elif self._duration > self._first_duration + self.GROWTH_S:
                self._duration_grew = True
        elif name == "seekable":
            self._seekable = data if isinstance(data, bool) else None
        elif name == "time-pos":
            if not isinstance(data, (int, float)):
                return
            # time-pos arrives around 24 times a second. Only act when the
            # whole second changes, so a two hour video costs a few thousand
            # cheap comparisons instead of a few hundred thousand.
            if self._first_pos is None:
                self._first_pos = float(data)
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
        self._first_duration = None
        self._duration_grew = False
        self._first_pos = None
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
        """Any one guard is enough. Weave knows what it started, mpv knows that
        a stream with no rewind cannot be seeked, and a duration that grows
        while the file plays belongs to something still being broadcast."""
        with self._hint_lock:
            hinted = self._live_current or self._pending_live
        return hinted or self._seekable is False or self._duration_grew

    def _too_soon(self) -> bool:
        """Whether this file has played long enough to be judged.

        A live stream reads as finished within a second or two, and the guard
        that catches it needs a few seconds of duration to compare. Nothing is
        marked before then.
        """
        if self._first_pos is None:
            return True
        return (self._max_pos - self._first_pos) < self.GRACE_S

    def _check_threshold(self) -> None:
        if self._is_live() or self._too_soon():
            return
        progress = self._progress()
        if self._key and progress is not None and progress >= self._threshold:
            self._report(progress)

    def _flush(self, reached_end: bool) -> None:
        if not self._key:
            return
        progress = self._progress()
        if reached_end and (not self._is_live() or self._key.startswith("yt:")):
            # Not held back by the grace, and for a stream not by the live
            # guard either. A file short enough to end inside the grace was
            # watched from beginning to end, and a live stream that reaches
            # its end while somebody is watching was left at the end, which is
            # what decides a stream: where you stopped, not when you joined.
            #
            # A Twitch entry is a channel rather than a video, so it is left
            # alone. Marking one would answer for every broadcast that channel
            # ever makes.
            self._report(progress if progress is not None else 1.0)
            return
        if reached_end:
            return
        if self._is_live() or self._too_soon():
            # Where it stopped is remembered by mpv either way, in the resume
            # file that draws the bar under the card. A stream is judged
            # against a real length once it has ended, not against the rewind
            # window while it is running.
            return
        if progress is not None and progress >= self._threshold:
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
    stopped = Signal()
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

        # Every mpv this handed a video to and has not yet seen exit. mpv is
        # started detached and is meant to outlive this window, so nothing
        # waits on it, but a child nobody ever polls stays a zombie in the
        # process table once it does exit. Polled on the next handoff.
        self._children: list[subprocess.Popen] = []
        self._watcher = _IpcWatcher(resolve_socket(cfg), cfg.watched_threshold, self)
        self._watcher.nowPlaying.connect(self.nowPlaying)
        self._watcher.watched.connect(self.watched)
        self._watcher.connectionChanged.connect(self.connectionChanged)
        self._watcher.stopped.connect(self.stopped)

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
        self._sweep_children()

    def _sweep_children(self) -> None:
        """Collect the players that have exited since the last look."""
        self._children = [child for child in self._children if child.poll() is None]

    def play(self, url: str, twitch_login: str | None = None, live: bool = False) -> bool:
        if not self._command:
            self.failed.emit(self._error or "no player configured")
            return False
        self._watcher.set_twitch_hint(twitch_login)
        self._watcher.set_live_hint(live)
        self._sweep_children()
        try:
            self._children.append(subprocess.Popen(
                [*self._command, url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            ))
            return True
        except OSError as exc:
            self.failed.emit(f"could not start the player: {exc}")
            return False
