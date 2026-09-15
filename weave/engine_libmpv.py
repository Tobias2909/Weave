"""The music player as a library rather than as another process.

Weave has played music through a second mpv started as a subprocess and driven
over its IPC socket. That is still the right shape for sound alone, and it is
what shipped, but a picture cannot come out of it: video frames live inside the
player's own process and there is no way to lift them into this window. Wayland
has no protocol for embedding a foreign window either, so the only route to a
picture in the page is libmpv rendering into the same scene Qt draws.

So this is the same player, in this process, behind the same interface the
subprocess one has. Anything already written against `MusicEngine` works against
this without knowing which it is holding.

Two things measured before any of it was written, because the design turned on
them:

  A video track can be switched on and off in the middle of a song without the
  sound breaking. Sampled over the change, the audio advanced 9.97 s in 9.97 s
  of wall time, with no stall over 50 ms.

  With the video track off, nothing is fetched and nothing is decoded: 0 KiB in
  12.1 s against 2411 kbit/s with it on, and 0.2 % of a core against 9.2 %. So a
  page nobody has opened costs exactly nothing, and turning it on costs about
  2.7 s before a frame exists, which the artwork covers.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

# The same two roles the subprocess engine uses. Every entry handed to mpv is
# one of them, and an event about an entry that has since been replaced has no
# role and is dropped.
CURRENT, NEXT = "current", "next"

# What the player is started with. Deliberately close to the subprocess
# command, since the two have to behave identically for everything but the
# picture.
#
# `vo=libmpv` is the one real difference: it renders on demand into whatever
# asks it to, rather than opening a window of its own. With nothing asking,
# nothing is drawn.
OPTIONS = {
    "config": False,
    "load_scripts": False,
    "ytdl": False,
    "idle": True,
    "vo": "libmpv",
    # Off until a page asks for it. This is what makes a listener who never
    # opens the page pay nothing at all for the ability to.
    "vid": "no",
    "audio_display": "no",
    "prefetch_playlist": True,
    "gapless_audio": True,
    "audio_client_name": "weave",
    "terminal": False,
}


class LibmpvMissing(RuntimeError):
    """python-mpv or libmpv itself is not here."""


def available() -> bool:
    try:
        import mpv                                                  # noqa: F401
    except (ImportError, OSError):
        # OSError is libmpv itself being absent, which is a different fault
        # from the binding being absent and reads the same to a caller.
        return False
    return True


class LibmpvEngine(QObject):
    """One mpv, in this process, holding [current, next] exactly as the other
    one does."""

    positionChanged = Signal(float)      # seconds into the current track
    durationChanged = Signal(float)      # seconds, 0 while unknown or live
    pausedChanged = Signal(bool)
    idleChanged = Signal(bool)           # True when nothing is loaded at all
    bufferingChanged = Signal(bool)      # mpv paused itself waiting for data
    started = Signal(str)                # CURRENT or NEXT began playing
    ended = Signal(str)                  # the current entry ended: eof, error, stop
    gone = Signal(str)                   # the player went away or would not start
    # A frame exists, or none does any more. The page draws the artwork until
    # the first of these arrives, so a picture never appears as a black box.
    videoChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mpv = None
        self._roles: dict[int, str] = {}
        # An entry mpv began playing before the load that made it had
        # finished saying what it was for. The player starts a file at
        # once and reports it from its own thread, which can beat the
        # line that records the role, so the report is held rather than
        # dropped and is answered as soon as the role is known.
        self._unclaimed: int | None = None
        self._volume = 100.0
        self._complaints: list[str] = []
        self._want_video = False
        self._had_frame = False
        # Whether anything is able to draw yet. With vo=libmpv there is no
        # picture until something has attached itself to render one, and
        # asking for the video track before then fails outright with "No
        # render context set" and leaves the track switched on and dead.
        self._can_render = False

    # ---- the player itself ------------------------------------------------

    def running(self) -> bool:
        return self._mpv is not None

    def ensure(self) -> bool:
        """Start it if it is not already up. True when there is a player."""
        if self._mpv is not None:
            return True
        try:
            import mpv
        except (ImportError, OSError) as exc:
            self.gone.emit(f"the player library could not be loaded, {exc}")
            return False
        try:
            self._mpv = mpv.MPV(log_handler=self._on_log, loglevel="error",
                                **OPTIONS)
        except Exception as exc:
            self._mpv = None
            self.gone.emit(f"the player would not start, {exc}")
            return False
        self._observe()
        self.set_volume(self._volume)
        return True

    def _observe(self) -> None:
        player = self._mpv
        player.observe_property("time-pos", self._on_position)
        player.observe_property("duration", self._on_duration)
        player.observe_property("pause", self._on_paused)
        player.observe_property("idle-active", self._on_idle)
        player.observe_property("paused-for-cache", self._on_buffering)
        # What says a picture exists. Width alone is set the moment a track is
        # configured, which is about two seconds before anything can be drawn,
        # and drawing from that point shows a black box.
        player.observe_property("video-frame-info", self._on_frame)

        @player.event_callback("start-file")
        def _started(event):
            entry = _entry_id(event)
            role = self._roles.get(entry)
            if role:
                self.started.emit(role)
            else:
                self._unclaimed = entry

        @player.event_callback("end-file")
        def _ended(event):
            data = getattr(event, "data", None)
            reason = str(getattr(data, "reason", "") or "eof")
            self._roles.pop(_entry_id(event), None)
            self.ended.emit(reason)

    def complaint(self, lines: int = 2) -> str:
        """What the player said about the last thing that would not play.

        The subprocess engine has to lift these out of a log file, because an
        mpv with no terminal throws its own words away. In here they arrive as
        they happen and are simply kept.
        """
        return "; ".join(self._complaints[-lines:])

    def _on_log(self, level: str, prefix: str, text: str) -> None:
        if level in ("error", "fatal"):
            said = f"{prefix}: {text.strip()}"
            self._complaints.append(said)
            del self._complaints[:-8]

    def quit(self) -> None:
        player, self._mpv = self._mpv, None
        self._roles.clear()
        if player is None:
            return
        try:
            player.terminate()
        except Exception:
            pass

    # ---- what is playing --------------------------------------------------

    def load(self, url: str, start: float | None = None,
             video: str | None = None) -> None:
        """Play this now, dropping whatever was held as next.

        A video address is a separate stream, handed to the entry as its own
        file, which is how one track can carry both without either being
        re-fetched when the picture is turned on or off.
        """
        if not self.ensure():
            return
        self._roles.clear()
        entry = self._play(url, "replace", start, video)
        if entry is not None:
            self._claim(entry, CURRENT)

    def append(self, url: str, video: str | None = None) -> None:
        if not self.ensure():
            return
        entry = self._play(url, "append", None, video)
        if entry is not None:
            self._claim(entry, NEXT)

    def _claim(self, entry: int, role: str) -> None:
        """Say what an entry is for, and answer a report that got here first."""
        self._roles[entry] = role
        if self._unclaimed == entry:
            self._unclaimed = None
            self.started.emit(role)

    def _play(self, url: str, mode: str, start: float | None,
              video: str | None) -> int | None:
        options: dict[str, str] = {}
        if start:
            options["start"] = f"{start:.3f}"
        if video:
            # The picture is the file and the sound rides along with it, rather
            # than the other way round, because mpv times a playlist entry by
            # its own stream and the picture is the one that must not drift.
            url, options["audio-file"] = video, url
        try:
            self._mpv.loadfile(url, mode, **options)
            # The call itself answers nothing, so the entry it just made is
            # read back off the playlist. Which entry an event is about is the
            # whole basis for telling the track playing from the one queued
            # behind it, and without an id here every event was anonymous and
            # dropped, so nothing ever advanced.
            entries = list(self._mpv.playlist or [])
            return int(entries[-1]["id"]) if entries else None
        except Exception as exc:
            self.gone.emit(f"the player would not take the track, {exc}")
            return None

    def clear_after(self) -> None:
        """Drop whatever is held as next, keeping what is playing."""
        if self._mpv is None:
            return
        for entry, role in list(self._roles.items()):
            if role == NEXT:
                self._roles.pop(entry, None)
                self._command("playlist-remove", str(entry))

    def remove_before(self) -> None:
        """Drop what has already played, so the playlist stays two long."""
        if self._mpv is None:
            return
        self._command("playlist-remove", "0")

    def next(self) -> None:
        self._command("playlist-next", "force")

    def stop(self) -> None:
        self._roles.clear()
        self._command("stop")

    def set_pause(self, paused: bool) -> None:
        self._set("pause", bool(paused))

    def seek(self, seconds: float) -> None:
        self._command("seek", f"{max(0.0, seconds):.3f}", "absolute")

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(100.0, float(volume)))
        self._set("volume", self._volume)

    def set_loop(self, loop: bool) -> None:
        self._set("loop-file", "inf" if loop else "no")

    # ---- the picture ------------------------------------------------------

    def set_video(self, wanted: bool) -> None:
        """Turn the picture on or off, without touching the sound.

        Measured gapless in both directions. Off, mpv fetches none of the video
        stream and decodes none of it, so this is what a page nobody has opened
        costs rather than a saving to be made later.
        """
        wanted = bool(wanted)
        if wanted == self._want_video:
            return
        self._want_video = wanted
        if not self._had_frame or not wanted:
            self._had_frame = False
            self.videoChanged.emit(False)
        # Remembered either way, and only acted on once there is somewhere for
        # the frames to go.
        if self._can_render or not wanted:
            self._set("vid", "auto" if wanted else "no")

    def add_video(self, url: str) -> None:
        """Attach a picture to the song already playing.

        Measured gapless: the sound does not break, and a frame exists about
        four and a half seconds later. The alternative is loading the track
        again with the picture in it, which restarts the song.
        """
        if self._mpv is None or not url:
            return
        self._command("video-add", url, "select")
        self._want_video = True
        if self._can_render:
            self._set("vid", "auto")

    def drop_video(self) -> None:
        """Take the picture away and stop fetching it, leaving the sound."""
        if self._mpv is None:
            return
        self._want_video = False
        self._set("vid", "no")
        if self._had_frame:
            self._had_frame = False
            self.videoChanged.emit(False)

    def render_failed(self, why: str) -> None:
        """The surface could not be built. Kept with the player's own
        complaints, so the page can say why there is no picture rather than
        simply never showing one."""
        self._complaints.append(f"the picture could not be set up, {why}")
        del self._complaints[:-8]

    def render_ready(self, ready: bool) -> None:
        """Something has attached itself to draw the frames, or let go again.

        Called by whatever holds the render context. A wish made before this
        was held rather than refused, so opening the page and the picture
        arriving are not a race.
        """
        self._can_render = bool(ready)
        if self._can_render and self._want_video:
            self._set("vid", "auto")
        elif not self._can_render:
            self._set("vid", "no")
            if self._had_frame:
                self._had_frame = False
                self.videoChanged.emit(False)

    @property
    def raw(self):
        """The player itself, for the one thing that needs it: building a
        render context, which has to be made against this exact handle."""
        return self._mpv

    @property
    def wants_video(self) -> bool:
        return self._want_video

    # ---- what mpv reports -------------------------------------------------

    def _on_position(self, _name, value) -> None:
        if value is not None:
            self.positionChanged.emit(float(value))

    def _on_duration(self, _name, value) -> None:
        self.durationChanged.emit(float(value or 0.0))

    def _on_paused(self, _name, value) -> None:
        self.pausedChanged.emit(bool(value))

    def _on_idle(self, _name, value) -> None:
        self.idleChanged.emit(bool(value))

    def _on_buffering(self, _name, value) -> None:
        self.bufferingChanged.emit(bool(value))

    def _on_frame(self, _name, value) -> None:
        has = value is not None
        if has == self._had_frame:
            return
        self._had_frame = has
        self.videoChanged.emit(has)

    # ---- talking to it ----------------------------------------------------

    def _command(self, *args: str) -> None:
        if self._mpv is None:
            return
        try:
            self._mpv.command(*args)
        except Exception:
            # A command against a player that has gone is not worth a sentence
            # of its own; the shutdown that took it already said so.
            pass

    def _set(self, name: str, value) -> None:
        if self._mpv is None:
            return
        try:
            self._mpv[name] = value
        except Exception:
            pass


def _entry_id(event) -> int:
    data = getattr(event, "data", None)
    return int(getattr(data, "playlist_entry_id", 0) or 0)

