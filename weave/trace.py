"""Evidence for the one fault that keeps coming back: the window catching when
the Now playing page opens or closes with a picture in it.

Off unless the environment says otherwise, and then it costs nothing: every
mark is one attribute read. On, it writes one line per event to a file in the
cache directory, with a clock in milliseconds since start and the thread that
wrote it, so that what the window's thread was doing can be laid beside what
the render thread and the player were doing at the same moment.

Four things are watched, because the fault has four possible homes and every
round so far has guessed at which:

  the window's own thread, through a timer that notices when it was not run
  on time (a stall in the interface);

  the render thread, through the time spent inside the player's render call
  (the video holding the scene up);

  the player, through its own verbose log lines about frames not being
  collected, frames dropped and the sound running dry, and through its clock
  falling behind the wall clock (the music actually catching);

  the sound server, through the number of times it ran out of data for this
  application, which is the one measure that cannot be argued with.

Run with WEAVE_TRACE=1, do the thing, then read trace.log next to the images.

The marks are also kept in memory whether or not a log is open, the last few
hundred of them, because a fault that comes rarely cannot wait for somebody to
have switched tracing on before it happened. Where the window can tell that
something is stuck, it writes them out on its own (`dump`).
"""

from __future__ import annotations

import faulthandler
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from . import paths

ENV = "WEAVE_TRACE"
LOG = paths.CACHE_DIR / "trace.log"
FAULTS = paths.CACHE_DIR / "trace-faults.log"
# Where the marks kept in memory are written when something is seen stuck.
STUCK = paths.CACHE_DIR / "stuck-picture.log"
# Past this the file is moved aside to one older copy, so a fault that keeps
# happening cannot fill the disk.
STUCK_LIMIT = 512 * 1024
# How many marks are kept in memory. Every mark there is is rare, a few for each
# song and each opening of the page, so this reaches back over several songs.
RING = 400

# A tick this far past due on the window's thread is worth a line. One frame
# at 60 Hz is 16.7 ms, so anything over this was seen.
STALL_MS = 20.0
# A render call longer than this is the video holding the scene up rather
# than drawing a frame, which takes one or two milliseconds.
SLOW_RENDER_MS = 4.0
# How far the player's clock may fall behind the wall clock between two
# position reports before it is called a catch.
CLOCK_SLIP_S = 0.06

_file = None
_lock = threading.Lock()
_t0 = time.monotonic()
_ring: deque[str] = deque(maxlen=RING)


def enabled() -> bool:
    return bool(os.environ.get(ENV))


def mark(event: str, **fields) -> None:
    """One line, kept in memory always and written while a log is open."""
    stamp = (time.monotonic() - _t0) * 1000.0
    thread = threading.current_thread().name[:14]
    tail = "".join(f" {name}={value}" for name, value in fields.items())
    line = f"{stamp:10.1f} {thread:<14} {event}{tail}\n"
    _ring.append(line)
    if _file is None:
        return
    with _lock:
        try:
            _file.write(line)
            _file.flush()
        except OSError:
            pass


def open_log(path: Path = LOG) -> Path:
    """Start writing. Appends, and every run begins with a start line, so a
    run before a change and one after it sit in the same file."""
    global _file, _t0
    path.parent.mkdir(parents=True, exist_ok=True)
    _file = open(path, "a", encoding="utf-8")                  # noqa: SIM115
    _t0 = time.monotonic()
    mark("start", pid=os.getpid(), python=sys.version.split()[0])
    return path


def close_log() -> None:
    global _file
    handle, _file = _file, None
    if handle is not None:
        try:
            handle.close()
        except OSError:
            pass


def start(app) -> Path | None:
    """Arm everything, given the application. None when tracing is off."""
    if not enabled():
        return None
    path = open_log()
    # A crash leaves a stack this way, where a plain core dump of a Python
    # process names only the interpreter.
    try:
        faults = open(FAULTS, "a", encoding="utf-8")            # noqa: SIM115
        faulthandler.enable(file=faults, all_threads=True)
        mark("faulthandler", file=str(FAULTS))
    except OSError:
        pass
    mark("gui_thread", ident=threading.get_ident())
    _watch_gui_thread(app)
    _watch_sound_server()
    return path


# ---- the window's thread ---------------------------------------------------

def _watch_gui_thread(app) -> None:
    from PySide6.QtCore import Qt, QTimer

    timer = QTimer(app)
    timer.setInterval(4)
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    last = [time.monotonic()]

    def tick() -> None:
        now = time.monotonic()
        gap = (now - last[0]) * 1000.0
        last[0] = now
        if gap > STALL_MS:
            mark("gui_stall", ms=f"{gap:.1f}")

    timer.timeout.connect(tick)
    timer.start()
    # Kept alive by its parent, the application.


# ---- the render thread -----------------------------------------------------

class Timed:
    """Times one render call and writes a line when it was slow."""

    __slots__ = ("_began",)

    def __enter__(self) -> Timed:
        self._began = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        spent = (time.perf_counter() - self._began) * 1000.0
        # Only into a log. A frame is drawn many times a second, and kept in
        # memory these would push out the marks a report is wanted for.
        if spent > SLOW_RENDER_MS and _file is not None:
            mark("render_slow", ms=f"{spent:.1f}")


# ---- the player's clock ----------------------------------------------------

class Clock:
    """Notices the player's position falling behind the wall clock."""

    def __init__(self) -> None:
        self._wall = 0.0
        self._pos = 0.0

    def report(self, position: float, paused: bool) -> None:
        # Only into a log, for the reason the render times are.
        if _file is None:
            return
        now = time.monotonic()
        if self._wall and not paused and position > self._pos:
            expected = now - self._wall
            moved = position - self._pos
            if expected - moved > CLOCK_SLIP_S:
                mark("clock_slip", wall_ms=f"{expected * 1000:.0f}",
                     moved_ms=f"{moved * 1000:.0f}")
        self._wall, self._pos = now, position

    def reset(self) -> None:
        self._wall = 0.0


# What the player says that is worth keeping. Its verbose log is a flood, and
# these are the lines that speak to frames not collected, frames dropped and
# the sound running dry.
PLAYER_WORDS = ("underrun", "not being called", "stuck", "drop", "VO: ",
                "reconfig", "hwdec", "Audio device", "late")


def player_said(level: str, prefix: str, text: str) -> None:
    # Kept whether or not a log is open, like every mark. Without tracing the
    # player is asked for its errors alone, so this is a line or two a song.
    if level in ("warn", "error", "fatal") or any(w in text for w in PLAYER_WORDS):
        mark("mpv", level=level, who=prefix, said=text.strip())


def dump(why: str, path: Path | None = None, **fields) -> Path | None:
    """Write the marks kept in memory to a file of their own, under a line
    saying when and why. None when it could not be written."""
    path = path or STUCK
    head = "".join(f" {name}={value}" for name, value in fields.items())
    lines = list(_ring)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > STUCK_LIMIT:
            path.replace(path.with_name(path.name + ".1"))
        with open(path, "a", encoding="utf-8") as out:
            out.write(f"==== {time.strftime('%Y-%m-%d %H:%M:%S')} {why}{head}\n")
            out.writelines(lines)
            out.write("\n")
    except OSError:
        return None
    return path


# ---- the sound server ------------------------------------------------------

def parse_xruns(report: str, node: str = "weave") -> int | None:
    """The ERR count for one node from pw-top's batch output, or None.

    The columns are S ID QUANT RATE WAIT BUSY W/Q B/Q ERR FORMAT NAME, and
    FORMAT carries spaces, so the count is the ninth field from the left and
    the name is the last.
    """
    for line in report.splitlines():
        fields = line.split()
        if len(fields) >= 10 and fields[-1] == node:
            try:
                return int(fields[8])
            except ValueError:
                return None
    return None


def _watch_sound_server() -> None:
    def loop() -> None:
        seen = None
        while _file is not None:
            try:
                done = subprocess.run(["pw-top", "-b", "-n", "1"],
                                      capture_output=True, text=True, timeout=3)
                count = parse_xruns(done.stdout)
            except (OSError, subprocess.TimeoutExpired):
                return
            if count is not None and count != seen:
                mark("pw_xruns", total=count)
                seen = count
            time.sleep(1.0)

    threading.Thread(target=loop, name="trace-pw", daemon=True).start()
