"""The thing that actually plays music: a second mpv, with no window.

Playing a stream well means a lot of machinery underneath the player. A signed
googlevideo address is dropped by the server as a matter of course, the last
piece of a file is shorter than the others, a seek lands outside what has been
read, and the next track has to be open before the current one ends or there
is a gap. Writing that machinery is writing a media player, and each piece of
it is another place to be wrong.

mpv has all of it already, measured rather than assumed. It reads a whole track
into memory within a few seconds of starting it, so a reset connection after
that costs nothing at all; before that it reconnects on its own. A seek inside
what it holds lands in a millisecond. With the next entry already in its
playlist it opens that entry while the current one is still playing, and the
changeover was measured at one millisecond with no buffering pause. So the
music goes to mpv too, a headless one that Weave owns, controls over its JSON
IPC socket, and shuts down with the window.

This module is only the socket. What to play, in which order, and what the
window shows is `audio.py`'s business.

Every command that puts something in the playlist is asked for its entry id,
and every start and end mpv reports names an entry id, so which track started
is never guessed from a playlist position that a command in flight might have
moved. That is what lets a track prefetched as "next" be told apart from a
stale event about one that was just replaced.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import signal
import socket
import subprocess
import threading

from PySide6.QtCore import QObject, QThread, Signal

from . import paths

SOCKET_NAME = "weave-music.sock"

# The two roles an entry in mpv's playlist can have. Weave keeps its own queue
# and hands mpv only what is playing and what comes next.
CURRENT, NEXT = "current", "next"

_OBSERVED = ("time-pos", "duration", "pause", "idle-active", "paused-for-cache")


def mpv_command(volume: float, socket_path: os.PathLike | str) -> list[str]:
    """The plain player, never the video wrapper, with none of the mpv
    configuration on this machine loaded. The wrapper carries shaders, overlays
    and a socket of its own, all of which would be wrong here."""
    binary = shutil.which("mpv")
    if binary is None:
        raise FileNotFoundError("mpv is not installed")
    return [
        binary, "--no-config", "--load-scripts=no", "--no-terminal",
        "--no-video", "--audio-display=no", "--force-window=no",
        "--idle=yes", "--ytdl=no",
        f"--input-ipc-server={socket_path}",
        # The next entry is opened while the current one still plays, and the
        # audio device is kept open across the change, so there is no gap.
        "--prefetch-playlist=yes", "--gapless-audio=yes",
        f"--volume={max(0, min(100, round(volume)))}",
        "--audio-client-name=weave",
    ]


try:
    _LIBC = ctypes.CDLL("libc.so.6", use_errno=True)
except OSError:                                                     # not glibc
    _LIBC = None

PR_SET_PDEATHSIG = 1


def _die_with_parent() -> None:
    """Runs in the child between fork and exec. A player with no window that
    outlived a crashed Weave would keep playing with nothing to stop it, so
    the kernel is asked to end it when its parent goes, however that happens.

    Nothing may be imported or locked in here. The child is a fork of a
    process with other threads running, and an import lock held by one of
    them at that moment would never be released on this side. The library
    handle is resolved once at import time for exactly that reason.
    """
    if _LIBC is not None:
        _LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


class MusicEngine(QObject):
    """A headless mpv, started on first use and controlled over its socket.

    The signals are emitted from the socket thread, which Qt delivers to the
    receiving thread's event loop, so anything connected to them runs where it
    was created.
    """

    positionChanged = Signal(float)      # seconds into the current track
    durationChanged = Signal(float)      # seconds, 0 while unknown or live
    pausedChanged = Signal(bool)
    idleChanged = Signal(bool)           # True when nothing is loaded at all
    bufferingChanged = Signal(bool)      # mpv paused itself waiting for data
    started = Signal(str)                # CURRENT or NEXT began playing
    ended = Signal(str)                  # the current entry ended: eof, error, stop
    gone = Signal(str)                   # the player went away or would not start

    def __init__(self, parent: QObject | None = None, socket_path=None) -> None:
        super().__init__(parent)
        self._socket_path = socket_path or (paths.runtime_dir() / SOCKET_NAME)
        self._process: subprocess.Popen | None = None
        self._ipc: _Ipc | None = None
        self._volume = 70.0

    # ---- lifecycle -------------------------------------------------------

    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def ensure(self) -> bool:
        """Start the player if it is not running. Blocks for the moment it
        takes the socket to appear, which is well under a second."""
        if self.running() and self._ipc is not None and self._ipc.connected.is_set():
            return True
        self.quit()
        try:
            command = mpv_command(self._volume, self._socket_path)
        except FileNotFoundError as exc:
            self.gone.emit(str(exc))
            return False
        try:
            os.unlink(self._socket_path)
        except OSError:
            pass
        try:
            # preexec_fn is flagged as unsafe with threads for good reason,
            # which is why the hook above imports nothing and takes no lock.
            self._process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)  # noqa: PLW1509
        except OSError as exc:
            self.gone.emit(f"could not start mpv: {exc}")
            return False
        self._ipc = _Ipc(self._socket_path, self)
        self._ipc.message.connect(self._on_message)
        self._ipc.lost.connect(self._on_lost)
        self._ipc.start()
        if not self._ipc.connected.wait(5.0):
            self.gone.emit("mpv did not open its socket")
            self.quit()
            return False
        return True

    def quit(self) -> None:
        ipc, process = self._ipc, self._process
        self._ipc, self._process = None, None
        if ipc is not None:
            ipc.send(["quit"])
            ipc.stop()
            ipc.wait(2000)
        if process is not None:
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
        try:
            os.unlink(self._socket_path)
        except OSError:
            pass

    # ---- the playlist ----------------------------------------------------

    def load(self, url: str, start: float | None = None) -> None:
        """Replace whatever is there with this, and play it. A start position
        goes with the load rather than after it, so it is never applied to a
        file that has not loaded yet and thrown away."""
        if not self.ensure():
            return
        command = ["loadfile", url, "replace"]
        if start and start > 0:
            command += [-1, f"start=+{start:.3f}"]
        self._ipc.send(command, role=CURRENT)

    def append(self, url: str) -> None:
        """Queue this behind the current entry. mpv opens it before the current
        one ends and moves on to it by itself."""
        if self._ipc is not None:
            self._ipc.send(["loadfile", url, "append"], role=NEXT)

    def clear_after(self) -> None:
        """Drop everything but the current entry."""
        if self._ipc is not None:
            self._ipc.send(["playlist-clear"])
            self._ipc.forget(NEXT)

    def remove_before(self) -> None:
        """Once mpv has moved on to the next entry, the one before it is done
        with. Weave keeps the history, not mpv."""
        if self._ipc is not None:
            self._ipc.send(["playlist-remove", 0])

    def next(self) -> None:
        if self._ipc is not None:
            self._ipc.send(["playlist-next", "force"])

    def stop(self) -> None:
        if self._ipc is not None:
            self._ipc.send(["stop"])

    # ---- playback --------------------------------------------------------

    def set_pause(self, paused: bool) -> None:
        if self._ipc is not None:
            self._ipc.send(["set_property", "pause", bool(paused)])

    def seek(self, seconds: float) -> None:
        if self._ipc is not None:
            self._ipc.send(["seek", max(0.0, float(seconds)), "absolute"])

    def set_volume(self, volume: float) -> None:
        """0 to 100. Remembered so a player started later begins there."""
        self._volume = max(0.0, min(100.0, float(volume)))
        if self._ipc is not None:
            self._ipc.send(["set_property", "volume", self._volume])

    def set_loop(self, loop: bool) -> None:
        if self._ipc is not None:
            self._ipc.send(["set_property", "loop-file", "inf" if loop else "no"])

    # ---- what mpv says ---------------------------------------------------

    def _on_message(self, message: dict) -> None:
        event = message.get("event")
        if event == "property-change":
            name, data = message.get("name"), message.get("data")
            if name == "time-pos":
                if isinstance(data, (int, float)):
                    self.positionChanged.emit(float(data))
            elif name == "duration":
                self.durationChanged.emit(float(data) if isinstance(data, (int, float)) else 0.0)
            elif name == "pause":
                self.pausedChanged.emit(bool(data))
            elif name == "idle-active":
                self.idleChanged.emit(bool(data))
            elif name == "paused-for-cache":
                self.bufferingChanged.emit(bool(data))
        elif event == "start-file":
            role = message.get("_role")
            if role:
                self.started.emit(role)
        elif event == "end-file":
            if message.get("_role") == CURRENT:
                self.ended.emit(str(message.get("reason") or ""))

    def _on_lost(self, why: str) -> None:
        if self._ipc is not None:
            self._ipc = None
            self._process = None
            self.gone.emit(why)


class _Ipc(QThread):
    """The socket, read on its own thread.

    Roles are resolved here, on the one thread that sees every reply and every
    event in the order mpv sent them, so a stale event about an entry that has
    since been replaced cannot be mistaken for a fresh one.
    """

    message = Signal(dict)
    lost = Signal(str)

    def __init__(self, socket_path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = str(socket_path)
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self.connected = threading.Event()
        self._lock = threading.Lock()
        self._next_id = 100
        self._pending: dict[int, str] = {}        # request id -> role asked for
        self._entries: dict[int, str] = {}        # mpv entry id -> role

    # ---- sending, from any thread ----------------------------------------

    def send(self, command: list, role: str | None = None) -> None:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            if role is not None:
                self._pending[request_id] = role
            sock = self._sock
        if sock is None:
            return
        payload = json.dumps({"command": command, "request_id": request_id}) + "\n"
        try:
            sock.sendall(payload.encode())
        except OSError:
            pass

    def forget(self, role: str) -> None:
        with self._lock:
            for entry, held in list(self._entries.items()):
                if held == role:
                    del self._entries[entry]

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    # ---- the thread ------------------------------------------------------

    def run(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.25)
        deadline = 5.0
        while not self._stop.is_set():
            try:
                sock.connect(self._path)
                break
            except OSError:
                deadline -= 0.05
                if deadline <= 0:
                    self.lost.emit("mpv did not open its socket")
                    return
                self._stop.wait(0.05)
        else:
            return
        with self._lock:
            self._sock = sock
        for index, name in enumerate(_OBSERVED, 1):
            self.send(["observe_property", index, name])
        self.connected.set()
        try:
            self._read(sock)
        finally:
            with self._lock:
                self._sock = None
            try:
                sock.close()
            except OSError:
                pass
        if not self._stop.is_set():
            self.lost.emit("mpv went away")

    def _read(self, sock: socket.socket) -> None:
        buffer = b""
        while not self._stop.is_set():
            try:
                chunk = sock.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    parsed = json.loads(line)
                except ValueError:
                    continue
                self._handle(parsed)

    def _handle(self, parsed: dict) -> None:
        request_id = parsed.get("request_id")
        if request_id is not None:
            with self._lock:
                role = self._pending.pop(request_id, None)
            entry = (parsed.get("data") or {}).get("playlist_entry_id") \
                if isinstance(parsed.get("data"), dict) else None
            if role is not None and entry is not None and parsed.get("error") == "success":
                with self._lock:
                    if role == CURRENT:
                        # Replacing the playlist forgets everything in it.
                        self._entries.clear()
                    self._entries[int(entry)] = role
            return
        event = parsed.get("event")
        if event in ("start-file", "end-file"):
            entry = parsed.get("playlist_entry_id")
            with self._lock:
                role = self._entries.get(entry) if entry is not None else None
                if event == "start-file" and role == NEXT:
                    # The next one is now the current one.
                    self._entries = {entry: CURRENT}
                    role = NEXT
            parsed = {**parsed, "_role": role}
        if "event" in parsed:
            self.message.emit(parsed)
