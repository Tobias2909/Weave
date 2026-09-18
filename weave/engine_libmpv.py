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

import locale

from PySide6.QtCore import QObject, Signal

from . import trace

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
    # Hand a frame over at its display time rather than fifty milliseconds
    # early. By default the render call blocks for the difference, and it is
    # made on the thread that paints the whole window, so every frame of
    # video parked the interface for up to that long. mpv's own header says
    # this is the setting that stops the render call limiting the caller's
    # frame rate. The surface asks not to wait as well, so the two agree.
    "video_timing_offset": 0,
}

# How many rows of a playlist are worth taking off the front before giving up.
# It holds two entries by design, so anything past a handful means something
# else is wrong and a loop is not the place to find out about it.
PLAYLIST_TIDY_LIMIT = 16


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
    # The address and what was said, for a picture the player would not take.
    # Its own report because the likeliest cause is an address that has aged
    # out, and whoever holds that address is the only one who can find a fresh
    # one.
    videoRefused = Signal(str, str)

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
        self._clock = trace.Clock()
        self._paused = True
        # The picture attached to the entry that is playing, so that opening
        # the page twice in one song switches the track back on rather than
        # attaching the same file again.
        self._attached = ""

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
        # Qt reads the numeric locale out of the environment when the
        # application is built, and mpv ABORTS on one whose decimal point is
        # not a point. An abort and not an exception, so there is nothing to
        # catch and it reads as a fault in whatever ran last. The binding sets
        # this as it is imported, which covers it only while that import
        # happens after the application exists, and that is an order rather
        # than a rule.
        try:
            locale.setlocale(locale.LC_NUMERIC, "C")
        except locale.Error:
            pass
        try:
            # Verbose only while tracing. The lines about frames not being
            # collected and the sound running dry are said at that level and
            # nowhere else.
            level = "v" if trace.enabled() else "error"
            self._mpv = mpv.MPV(log_handler=self._on_log, loglevel=level,
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
            # An external track belongs to the file it was added to.
            self._attached = ""
            role = self._roles.get(entry)
            if role:
                if role == NEXT:
                    # It was the one held behind the song playing and it is
                    # the song playing now, so it stops being held. Left as it
                    # was, the next tidying of the playlist would go looking
                    # for what is held behind this one and take out this one.
                    self._roles[entry] = CURRENT
                self.started.emit(role)
            else:
                # Either a report that beat the line recording what it was
                # for, which is answered the moment the role lands, or an
                # entry that should have been taken out of the playlist and
                # was not. The second is silent by nature, since nothing is
                # ever emitted about it, so it is written down here.
                trace.mark("entry_unclaimed", entry=entry)
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
        trace.player_said(level, prefix, text)
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
        self._attached = ""
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
                self._drop_entry(entry)

    def _drop_entry(self, entry: int) -> bool:
        """Take one entry out of the playlist, named by its id.

        The id has to be turned into a place first, and that is the whole
        point of this. `playlist-remove` is given a PLACE and never an id, and
        the two part company as soon as anything has been played: ids count up
        for the life of the player while places start again at zero. Handed an
        id, mpv refuses the command outright, and a refusal here says nothing
        at all, so the entry stayed in the playlist and was played after the
        one it was supposed to have replaced. Its role had already been
        forgotten, so it began with no report of its own, which is a song
        being heard that the window knows nothing about.
        """
        where = self._place_of(entry)
        if where is None:
            return False
        return self._command("playlist-remove", str(where))

    def _place_of(self, entry: int) -> int | None:
        """Where an entry sits in the playlist as it stands, or None."""
        if self._mpv is None:
            return None
        try:
            rows = list(self._mpv.playlist or [])
        except Exception:
            return None
        for place, row in enumerate(rows):
            try:
                if int(row.get("id", -1)) == entry:
                    return place
            except (TypeError, ValueError):
                continue
        return None

    def remove_before(self) -> None:
        """Drop what has already played, so the playlist stays two long.

        Everything ahead of what is being played rather than one row, because
        a playlist that has grown by more than one cannot be brought back by
        taking a single row off the front of it.
        """
        if self._mpv is None:
            return
        for _ in range(PLAYLIST_TIDY_LIMIT):
            try:
                place = self._mpv.playlist_pos
            except Exception:
                return
            if place is None or int(place) <= 0:
                return
            if not self._command("playlist-remove", "0"):
                return

    def duration(self) -> float:
        """How long what is playing is, asked rather than waited for.

        An observed property reports a change and nothing else. A track that
        follows one of the same length, which is what a queue of one repeating
        always is, changes nothing, so the report never comes and anything
        waiting for it waits for ever.
        """
        if self._mpv is None:
            return 0.0
        try:
            return float(self._mpv.duration or 0.0)
        except Exception:
            # A property read can be refused between files, which is an
            # unknown length rather than a fault.
            return 0.0

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
        trace.mark("set_video", wanted=wanted, can_render=self._can_render)
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
        trace.mark("add_video", can_render=self._can_render,
                   again=url == self._attached)
        if url == self._attached and self._want_video:
            # Already attached and already on. Setting the track again, even
            # to the same value, makes mpv reselect it and lose the frame,
            # which showed as the artwork flashing over a running picture.
            return
        if url != self._attached:
            self._attach(url)
        self._want_video = True
        if self._can_render:
            self._set("vid", "auto")

    def _attach(self, url: str) -> None:
        """Hand the picture to the song playing, without waiting for it.

        `video-add` opens the stream inside the call, and the call is made on
        the thread that paints the whole window. MEASURED on mpv 0.41: an
        address that answers holds that thread for 0.21 s, and one that does
        not answer holds it for 29.2 s, which is a frozen window with nothing
        said about why. Asked for asynchronously it returns in under a
        millisecond and mpv answers when it has an answer.
        """
        self._attached = url
        ask = getattr(self._mpv, "command_async", None)
        if ask is None:
            # A binding too old to ask this way. Rare enough to be worth the
            # wait rather than a second way of doing the same thing.
            if not self._command("video-add", url, "select"):
                self._refused(url)
            return
        try:
            ask("video-add", url, "select",
                callback=lambda error, _result, at=url: self._answered(at, error))
        except Exception:
            self._refused(url)

    def _answered(self, url: str, error) -> None:
        """What mpv made of it. Raised from the player's own thread, where the
        only thing that may be done is to say so."""
        if error is not None:
            self._refused(url)

    def _refused(self, url: str) -> None:
        """A picture the player would not take.

        What was attached is forgotten, so asking again is not read as already
        having it, and whoever found the address is told, because the likeliest
        reason by far is that it has aged out and a fresh one would work.
        """
        if self._attached == url:
            self._attached = ""
        said = "the picture could not be opened"
        trace.mark("video_refused")
        self._complaints.append(said)
        del self._complaints[:-8]
        self.videoRefused.emit(url, said)

    def drop_video(self) -> None:
        """Switch the picture off, leaving the sound and leaving the track
        attached, so it can be switched back on within the same song."""
        if self._mpv is None:
            return
        self._want_video = False
        trace.mark("drop_video")
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
        trace.mark("render_ready", ready=self._can_render, want_video=self._want_video)
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
            self._clock.report(float(value), self._paused)
            self.positionChanged.emit(float(value))

    def _on_duration(self, _name, value) -> None:
        self.durationChanged.emit(float(value or 0.0))

    def _on_paused(self, _name, value) -> None:
        self._paused = bool(value)
        self._clock.reset()
        self.pausedChanged.emit(bool(value))

    def _on_idle(self, _name, value) -> None:
        self.idleChanged.emit(bool(value))

    def _on_buffering(self, _name, value) -> None:
        self.bufferingChanged.emit(bool(value))

    def _on_frame(self, _name, value) -> None:
        has = value is not None
        if has == self._had_frame:
            return
        trace.mark("frame_exists", has=has)
        self._had_frame = has
        self.videoChanged.emit(has)

    # ---- talking to it ----------------------------------------------------

    def _command(self, *args: str) -> bool:
        """Whether it was taken. A refusal used to be swallowed whole, which
        is how a playlist entry that was never removed went unnoticed."""
        if self._mpv is None:
            return False
        try:
            self._mpv.command(*args)
        except Exception:
            # A command against a player that has gone is not worth a sentence
            # of its own; the shutdown that took it already said so.
            return False
        return True

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

