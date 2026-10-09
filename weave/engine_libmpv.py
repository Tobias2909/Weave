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

  That holds for a picture never added. One added and then switched off went on
  being fetched, measured later, so a picture nobody is looking at is taken off
  the song rather than switched off (`drop_video`).
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
    # Pictures decoded on the graphics card where that is known to work, for
    # the music's and the window's videos alike. MEASURED in a real window
    # through the render API, the whole application with a 1080p60 VP9 music
    # video showing: 21 % of one core in software, 10 % on the card; the
    # window's 1440p VP9 at 25 fps: 11.1 % against 3.5 %, no frame dropped
    # either way. auto-safe only takes a decoder mpv vouches for and falls
    # back to software otherwise. Forcing vaapi through an NVIDIA card's
    # translation layer froze the drawing for 5.6 s, and auto-safe never
    # chose it there.
    "hwdec": "auto-safe",
}

# A picture added this far into a song is moved to where the song is. mpv
# starts a picture added to a playing song at its very beginning and catches it
# up by reading and decoding everything before, MEASURED at 106 MiB and 11.3 s
# before a frame for one 3.5 minutes in, which for a long mix is never. Before
# this the beginning is close enough to be cheaper than moving.
FROM_HERE_S = 5.0

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
    # The player has taken a picture's address. Said from the player's own
    # thread and answered on this one, which is where the track is chosen.
    _videoTaken = Signal(str)
    # What the player says `vid` is, asked about that address without waiting.
    # Said from the player's own thread, empty when it gave no answer.
    _videoKnown = Signal(str, str)
    # The picture's decoder has its first frame's shape, which means its file
    # has been read from. Said from the player's own thread.
    _decoding = Signal()
    # There is something the surface could draw and nowhere yet to draw it.
    # The surface builds its render context only when it paints, and it has
    # no reason of its own to paint, so it is told.
    surfaceWanted = Signal()
    # A picture has been taken off and the player's output for it closed.
    # Said from the player's own thread. What the surface held for drawing it
    # is given back on its next paint, so it is told to paint once now.
    outputClosed = Signal()
    # The end of what is playing has been reached and the player is holding its
    # last frame there. Only ever true for a player told to keep files open at
    # their end, which the music is not.
    eofChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None,
                 options: dict | None = None) -> None:
        super().__init__(parent)
        self._videoTaken.connect(self._on_video_taken)
        self._videoKnown.connect(self._on_video_known)
        self._decoding.connect(self._from_here)
        # Whatever this player is started with on top of OPTIONS. The music
        # takes none; the videos played in the window are another player with a
        # name of its own at the sound server.
        self._options = dict(options or {})
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
        # Where the song is, as last reported. Read here rather than asked of
        # the player, which answers only once it is free.
        self._pos = 0.0
        # The picture wanted on the entry that is playing. A picture arriving
        # from any other address is one nobody wants any more, and goes.
        self._attached = ""
        # A picture asked for and not yet answered. Choosing a track before
        # the answer found none, read that as a picture gone missing and
        # attached it a second time, so every picture was opened twice.
        self._attaching = ""
        # A picture added partway into the song, still to be moved to where
        # the song is once its decoder has started (`_from_here`).
        self._move_up = ""

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
                                **{**OPTIONS, **self._options})
        except Exception as exc:
            self._mpv = None
            self.gone.emit(f"the player would not start, {exc}")
            return False
        self._observe()
        self.set_volume(self._volume)
        # A page opened before the first song gave the surface its one paint
        # while there was no player, and it gave up. Measured in a trace: the
        # page open at 4.8 s, the picture ready at 8.1 s, and no render context
        # at all until the page was closed two minutes later.
        self.surfaceWanted.emit()
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
        player.observe_property("eof-reached", self._on_eof)
        # Which decoder a picture got, for the trace of one that stutters.
        player.observe_property("hwdec-current", self._on_decoder)
        player.observe_property("video-dec-params", self._on_dec_params)

        @player.event_callback("start-file")
        def _started(event):
            self._new_file()
            entry = _entry_id(event)
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

    def _new_file(self) -> None:
        """What belonged to the file before goes with it.

        An external track belongs to the file it was added to, and so does a
        frame. mpv keeps its output, and the last frame in it, from one file
        to the next whenever the next one has a picture by the time its sound
        has opened, which a picture already found and a stream slow to open
        make likely. The report then goes from the old frame straight to the
        new ones without ever saying there was none, and a frame already
        counted was never counted again. MEASURED: the page said "Opening the
        video" over a picture that was playing underneath it, at frame 254.
        Forgotten here, the first frame of this file is news again.
        """
        self._attached = ""
        self._attaching = ""
        self._move_up = ""
        # The last report was about the file before, and a picture for this
        # one would otherwise be moved to where that one had got to.
        self._pos = 0.0
        if self._had_frame:
            self._had_frame = False
            self.videoChanged.emit(False)

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
             video: str | None = None, subtitle: str = "") -> None:
        """Play this now, dropping whatever was held as next.

        A video address is a separate stream, handed to the entry as its own
        file, which is how one track can carry both without either being
        re-fetched when the picture is turned on or off. A caption handed over
        here is opened with the file and shown from its first frame.
        """
        if not self.ensure():
            return
        self._roles.clear()
        self._attached = ""
        entry = self._play(url, "replace", start, video, subtitle)
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
              video: str | None, subtitle: str = "") -> int | None:
        options: dict[str, str] = {}
        if start:
            options["start"] = f"{start:.3f}"
        if subtitle:
            # One caption given with the file is shown by default, measured.
            options["sub-file"] = subtitle
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

    def holds_next(self) -> int | None:
        """The entry held behind the one playing, or None.

        Read from the roles rather than asked of the player. A role goes the
        moment its entry ends, starts or is taken out, on whichever thread
        hears of it first, so this is never older than a report still on its
        way to the window, and checking such a report is what it is for.
        """
        for entry, role in list(self._roles.items()):
            if role == NEXT:
                return entry
        return None

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

    def set_speed(self, speed: float) -> None:
        self._set("speed", max(0.25, min(4.0, float(speed))))

    def set_subtitle_place(self, percent: int) -> None:
        """How far down the picture a caption sits, 100 being its foot."""
        self._set("sub-pos", max(0, min(100, int(percent))))

    def show_subtitle(self, url: str, title: str = "", lang: str = "") -> None:
        """Show this caption on the file playing, or none with no address.

        One added before is chosen again rather than fetched again: mpv's own
        `cached` flag was MEASURED to add a second copy all the same. A new
        one is asked for without waiting, since mpv fetches it inside the
        call, on the thread that paints the window, as it does a picture.
        """
        if self._mpv is None:
            return
        if not url:
            self._set("sid", "no")
            return
        try:
            tracks = list(self._mpv.track_list or [])
        except Exception:
            tracks = []
        for track in tracks:
            if track.get("type") == "sub" and track.get("external-filename") == url:
                self._set("sid", track.get("id"))
                return
        ask = getattr(self._mpv, "command_async", None)
        if ask is None:
            self._command("sub-add", url, "select", title, lang)
            return
        try:
            ask("sub-add", url, "select", title, lang, callback=_subtitle_answered)
        except Exception:
            pass

    def cached_ranges(self) -> list[tuple[float, float]]:
        """What of the file playing is fetched and can be played at once, as
        spans in seconds of it.

        The player's own account covers its main file alone, and a video is
        loaded with the picture as that file and its sound riding along, so
        these are the picture's spans, the larger of the two and the one that
        runs out first. A broadcast's last span ends at the newest moment the
        player holds of it.
        """
        if self._mpv is None:
            return []
        try:
            state = self._mpv.demuxer_cache_state or {}
            spans = [(float(one["start"]), float(one["end"]))
                     for one in state.get("seekable-ranges") or []]
        except Exception:
            # Asked between files, or of a file that has none yet.
            return []
        return [(start, end) for start, end in spans if end > start]

    def position(self) -> float:
        """Where the player is, asked rather than waited for."""
        if self._mpv is None:
            return 0.0
        try:
            return float(self._mpv.time_pos or 0.0)
        except Exception:
            return 0.0

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
                   again=url == self._attached, on=self._video_on())
        if url == self._attached and self._want_video and self._video_on():
            # Already attached and already on. Setting the track again, even
            # to the same value, makes mpv reselect it and lose the frame,
            # which showed as the artwork flashing over a running picture.
            #
            # Whether it is ON is the question, not whether it was asked for.
            # Asked for and not on is a picture that never came, and reading
            # that as already done left the artwork up for the whole song
            # however often the page was closed and opened again.
            return
        if url == self._attaching:
            # Asked for before the page closed and still on its way. Its
            # answer turns it on now rather than taking it off again, and
            # asking a second time would put the same picture on the song twice.
            self._attached = url
        elif url != self._attached:
            self._attach(url)
        self._want_video = True
        self._choose_video()
        if not self._can_render:
            self.surfaceWanted.emit()

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
        self._move_up = url if self._pos > FROM_HERE_S else ""
        # `select` is what turns the picture on, and it does that whether or
        # not there is anywhere to draw it yet. With nowhere, the player says
        # `No render context set`, fails to open its output, and LEAVES THE
        # TRACK DEAD for the rest of the song. Nothing recovers it, because
        # the context arriving afterwards only sets `vid`, and by then the
        # output has already given up.
        #
        # It is a race only a picture handed over at once can lose. One that
        # spends seconds finding an address arrives after the surface has long
        # since painted and built the context; one handed over at once, as a
        # song once kept on disk was, beat the first paint by 105 ms, measured.
        #
        # So the track is added and left alone until there is somewhere for
        # it to go, and `render_ready` turns it on.
        flag = "select" if self._can_render else "auto"
        ask = getattr(self._mpv, "command_async", None)
        self._attaching = url if ask is not None else ""
        if ask is None:
            # A binding too old to ask this way. Rare enough to be worth the
            # wait rather than a second way of doing the same thing.
            if not self._command("video-add", url, flag):
                self._refused(url)
            return
        try:
            ask("video-add", url, flag,
                callback=lambda error, _result, at=url: self._answered(at, error))
        except Exception:
            self._refused(url)

    def _from_here(self) -> None:
        """Move a picture added partway into the song to where the song is.

        mpv moves a picture to the song's place only when it is chosen again
        after its file has been read from, and never one just added (demux.c,
        refresh_track). Its decoder having started says the file has been
        read from, so it is let go and chosen again then, before a frame of
        the beginning could be shown, and without waiting either time.
        """
        url, self._move_up = self._move_up, ""
        if not url or url != self._attached or not self._want_video or self._had_frame:
            return
        chosen = [track for track in self._video_tracks()
                  if track.get("external-filename") == url and track.get("selected")]
        if not chosen:
            return
        number = str(chosen[-1]["id"])
        trace.mark("picture_moved_up", track=number, at=f"{self._pos:.1f}")
        self._ask("set", "vid", "no")
        self._ask("set", "vid", number)

    def _video_on(self) -> bool:
        """Whether a video track is selected in the player right now.

        Asked rather than remembered, because what was asked for and what the
        player is doing came apart exactly once and that was the fault.
        """
        if self._mpv is None:
            return False
        try:
            return bool(self._mpv.vid)
        except Exception:
            return False

    def _answered(self, url: str, error) -> None:
        """What mpv made of it. Raised from the player's own thread, where the
        only thing that may be done is to say so."""
        if error is not None:
            self._refused(url)
        else:
            self._videoTaken.emit(url)

    def _on_video_taken(self, url: str) -> None:
        if url == self._attaching:
            self._attaching = ""
        if url == self._attached:
            self._ask_whether_on(url)
        else:
            # Asked for by a page that has closed since, or for a song that
            # has ended since. Left on the song, it would be fetched and
            # decoded for nobody, so it goes as soon as it has arrived.
            self._take_off(url)

    def _ask_whether_on(self, url: str) -> None:
        """Whether a picture just taken is on, asked without waiting.

        Read, the question waits for the player to be free, and straight after
        taking a picture it is starting its decoder. On the graphics card that
        is 35 ms, MEASURED, and the window stood still for all of it as the
        page slid in. The binding hands back answers to commands only, so it
        is asked as one: the raw `vid`, which says `no` or a number.
        """
        ask = getattr(self._mpv, "command_async", None)
        if ask is None:
            self._choose_video()
            return
        try:
            ask("expand-text", "${=vid}",
                callback=lambda error, said, at=url: self._videoKnown.emit(
                    at, "" if error is not None or said is None else str(said)))
        except Exception:
            self._choose_video()

    def _on_video_known(self, url: str, said: str) -> None:
        if url != self._attached:
            # Taken off or replaced while the question was out, and that has
            # dealt with it.
            return
        # No answer, and it is read the way every other choosing reads it.
        self._choose_video(on=said != "no" if said else None)

    def _choose_video(self, on: bool | None = None) -> None:
        """Turn the picture on, if it is wanted and there is somewhere to draw it.

        By the number of the track rather than by `vid=auto`. MEASURED on mpv
        0.41: `auto` chooses a track only at the moment it is set, so set
        while the picture was still on its way it chose nothing, the picture
        then arrived unchosen, and setting `auto` again changed nothing, since
        it already said `auto`. That is a picture stuck on its way for the rest
        of the song, which opening the page again could not mend. Naming the
        track chooses it whatever `vid` says.

        Never for a track already chosen, since choosing it again makes the
        player lose the frame it is showing. `on` is the player's own answer
        to that, when it has already been asked without waiting.
        """
        if self._mpv is None or not (self._can_render and self._want_video):
            return
        if self._attaching:
            # On its way. Its answer chooses it, or `select` already has.
            return
        if self._video_on() if on is None else on:
            return
        tracks = self._video_tracks()
        if tracks:
            number = max(int(track["id"]) for track in tracks)
            trace.mark("choose_video", track=number)
            self._set("vid", number)
        elif self._attached:
            # Asked for and not on the song. Seen once in a trace, cause not
            # found: asked again, chosen this time, since there is now
            # somewhere to draw it.
            trace.mark("choose_video", track="asked again")
            url, self._attached = self._attached, ""
            self._attach(url)
        else:
            # Nothing has been asked for yet. The track is chosen when it is.
            trace.mark("choose_video", track="none yet")
            self._set("vid", "auto")

    def _refused(self, url: str) -> None:
        """A picture the player would not take.

        What was attached is forgotten, so asking again is not read as already
        having it, and whoever found the address is told, because the likeliest
        reason by far is that it has aged out and a fresh one would work.
        """
        if self._attaching == url:
            self._attaching = ""
        if self._attached == url:
            self._attached = ""
        said = "the picture could not be opened"
        trace.mark("video_refused")
        self._complaints.append(said)
        del self._complaints[:-8]
        self.videoRefused.emit(url, said)

    def drop_video(self) -> None:
        """Take the picture off the song, track and stream, leaving the sound.

        MEASURED on a 1080p60 picture, page closed for 13 s at a time: left
        running it cost 22 to 26 % of a core and 400 KiB/s, the same as with
        the page open; switched off with `vid=no` it cost 6 % and went on
        fetching at 7 to 10 MB/s; taken off it costs 3 %, as a page never
        opened does, and fetches nothing. Opening the page again puts it back
        from the address already known, a frame in 0.2 to 1 s.

        Asked without waiting. The same call made the other way held the
        thread that paints the window for 192 ms, measured, and mpv said its
        frames were not being collected for exactly that long. A picture still
        on its way is left to its answer, which takes it off as it arrives.
        """
        if self._mpv is None:
            return
        self._want_video = False
        self._attached = ""
        trace.mark("drop_video")
        for track in self._video_tracks():
            if track.get("external"):
                self._remove_track(track)
        if self._had_frame:
            self._had_frame = False
            self.videoChanged.emit(False)

    def _take_off(self, url: str) -> None:
        """Remove every picture on the song opened from this address."""
        for track in self._video_tracks():
            if track.get("external-filename") == url:
                self._remove_track(track)

    def _remove_track(self, track: dict) -> None:
        trace.mark("remove_video", track=track.get("id"))
        # The surface told once it has gone. On the graphics card, giving back
        # what was held for drawing it is 17-25 ms of the render thread,
        # MEASURED, and left for the next paint that was the page opening
        # again, with the window waiting on it as the page slid in.
        self._ask("video-remove", str(track.get("id")), then=self.outputClosed.emit)

    def _ask(self, *args: str, then=None) -> None:
        """A command about the picture, without waiting for it. `then` runs
        once the player has done it, on the player's own thread.

        Waited for, a change of picture track held the thread that paints the
        window until mpv had done it, and mpv was waiting for that thread to
        collect a frame: 200 ms each time, MEASURED, three closes in eight,
        twice with the sound running dry.
        """
        ask = getattr(self._mpv, "command_async", None)
        if ask is None:
            if self._command(*args) and then is not None:
                then()
            return

        def answered(error, result) -> None:
            _asked(error, result)
            if error is None and then is not None:
                try:
                    then()
                except RuntimeError:
                    # Whoever was to be told has gone, the application
                    # closing while the player was still answering.
                    pass

        try:
            ask(*args, callback=answered)
        except Exception:
            pass

    def _video_tracks(self) -> list[dict]:
        if self._mpv is None:
            return []
        try:
            return [track for track in (self._mpv.track_list or [])
                    if track.get("type") == "video"]
        except Exception:
            # Asked between files, which have no tracks to speak of.
            return []

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
            self._choose_video()
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

    def picture_state(self) -> dict:
        """What the player says about the picture right now, for the report
        written when one never came. Each answer is asked on its own, since
        a report that fails over one question says nothing at all."""
        def short(address) -> str:
            text = str(address or "")
            return text[:60] + ("..." if len(text) > 60 else "")

        state = {"can_render": self._can_render, "want_video": self._want_video,
                 "had_frame": self._had_frame, "attached": short(self._attached),
                 "attaching": short(self._attaching),
                 "roles": dict(self._roles)}
        if self._mpv is None:
            state["player"] = "none"
            return state
        # Read as properties. `player[name]` reads the OPTION of that name,
        # which said `vid=auto` over a chosen track and could not answer the
        # rest at all, so the first report caught said nothing about them.
        for name in ("vid", "video-frame-info", "estimated-frame-number",
                     "playlist-pos", "idle-active"):
            try:
                value = getattr(self._mpv, name.replace("-", "_"))
                state[name] = "set" if name == "video-frame-info" and value else value
            except Exception as exc:
                state[name] = f"unanswered {type(exc).__name__}"
        try:
            state["video_tracks"] = [
                f"{track.get('id')}{'*' if track.get('selected') else ''}"
                f":{short(track.get('external-filename'))}"
                for track in (self._mpv.track_list or []) if track.get("type") == "video"]
        except Exception as exc:
            state["video_tracks"] = f"unanswered {type(exc).__name__}"
        try:
            state["playlist"] = [
                f"{entry.get('id')}{'>' if entry.get('playing') else ''}"
                for entry in (self._mpv.playlist or [])]
        except Exception as exc:
            state["playlist"] = f"unanswered {type(exc).__name__}"
        return state

    # ---- what mpv reports -------------------------------------------------

    def _on_position(self, _name, value) -> None:
        if value is not None:
            self._pos = float(value)
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

    def _on_decoder(self, _name, value) -> None:
        if value:
            trace.mark("decoder", player=self._options.get("audio_client_name", "weave"),
                       current=value)

    def _on_dec_params(self, _name, value) -> None:
        if value and self._move_up:
            self._decoding.emit()

    def _on_eof(self, _name, value) -> None:
        self.eofChanged.emit(bool(value))

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


def _asked(error, _result) -> None:
    """Raised from the player's own thread. A track already gone with its
    file is the usual reason, and there is nothing left to do about it."""
    if error is not None:
        trace.mark("picture_command_refused", why=str(error))


def _subtitle_answered(error, _result) -> None:
    """Raised from the player's own thread. A caption that would not open
    leaves the video playing without one, so a line in the trace is all."""
    if error is not None:
        trace.mark("subtitle_refused", why=str(error))


def _entry_id(event) -> int:
    data = getattr(event, "data", None)
    return int(getattr(data, "playlist_entry_id", 0) or 0)

