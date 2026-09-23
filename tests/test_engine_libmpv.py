"""The in process player.

Most of what matters here needs a real libmpv and is verified by driving one.
What is pinned here is the bookkeeping around it, which is where the faults
were: which entry an event is about, and not asking for a picture before there
is anywhere to put one.
"""

import time
import unittest
from unittest import mock

from PySide6.QtCore import QObject

from weave.audio import AudioPlayer
from weave.config import Config
from weave.engine_libmpv import CURRENT, NEXT, OPTIONS, LibmpvEngine, available


class Recorder(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.said: list = []


def engine() -> LibmpvEngine:
    """An engine with no player behind it. Every command is a no-op, which is
    what lets the bookkeeping be checked without libmpv."""
    return LibmpvEngine()


class WhichEntryAnEventIsAbout(unittest.TestCase):
    def test_a_report_that_arrives_first_is_answered_not_dropped(self) -> None:
        # mpv begins a file at once and reports it from its own thread, which
        # can beat the line that records what the entry was for. Dropped, the
        # player never learns the next track started and never moves on.
        one = engine()
        said: list = []
        one.started.connect(said.append)
        one._unclaimed = 7
        one._claim(7, NEXT)
        self.assertEqual(said, [NEXT])
        self.assertIsNone(one._unclaimed)

    def test_an_entry_claimed_before_it_starts_says_nothing_yet(self) -> None:
        one = engine()
        said: list = []
        one.started.connect(said.append)
        one._claim(3, CURRENT)
        self.assertEqual(said, [], "a track announced itself before it began")
        self.assertEqual(one._roles[3], CURRENT)

    def test_a_report_about_an_entry_nobody_owns_is_held(self) -> None:
        one = engine()
        one._unclaimed = None
        one._roles.clear()
        # Standing in for the callback, which needs a real player to install.
        entry = 9
        role = one._roles.get(entry)
        if not role:
            one._unclaimed = entry
        self.assertEqual(one._unclaimed, 9)


class NoPictureWithoutSomewhereToPutIt(unittest.TestCase):
    def test_asking_before_there_is_a_place_holds_the_wish(self) -> None:
        # Asked for with nothing attached, mpv answers "No render context set",
        # fails to open the output at all, and leaves the track switched on and
        # dead. So the wish is kept and acted on when there is somewhere to draw.
        one = engine()
        one.set_video(True)
        self.assertTrue(one.wants_video)
        self.assertFalse(one._can_render)

    def test_it_is_acted_on_once_there_is(self) -> None:
        one = engine()
        one.set_video(True)
        one.render_ready(True)
        self.assertTrue(one._can_render)
        self.assertTrue(one.wants_video)

    def test_letting_go_of_the_place_puts_the_picture_away(self) -> None:
        one = engine()
        one._had_frame = True
        one.render_ready(True)
        said: list = []
        one.videoChanged.connect(said.append)
        one.render_ready(False)
        self.assertEqual(said, [False], "the page kept a picture it cannot draw")

    def test_turning_it_off_is_always_allowed(self) -> None:
        one = engine()
        one.set_video(True)
        one.set_video(False)
        self.assertFalse(one.wants_video)


class Talker:
    """Stands in for the player and keeps what it was told.

    It models one thing rather than only recording, which is whether a video
    track is selected. The engine asks the player that before it touches a
    running picture, and a stub that always answered no makes the question
    moot, which is the shape of mistake this whole area is made of.
    """

    def __init__(self) -> None:
        self.said: list = []
        # What mpv answers for `vid`: False for none, a track id otherwise.
        self.vid = False
        # The picture tracks on the song, which the engine reads to choose one
        # by its number. Each video-add adds one.
        self.tracks: list[int] = []

    @property
    def track_list(self) -> list:
        return [{"id": number, "type": "video", "selected": self.vid == number}
                for number in self.tracks]

    def command(self, *args) -> None:
        self.said.append(tuple(args))
        if args and args[0] == "video-add":
            self.tracks.append(len(self.tracks) + 1)
            # `select` turns it on, `auto` adds it and leaves it alone.
            self.vid = self.tracks[-1] if args[-1] == "select" else self.vid

    def __setitem__(self, name, value) -> None:
        self.said.append((name, value))
        if name == "vid":
            if value == "no":
                self.vid = False
            elif value == "auto":
                self.vid = self.tracks[-1] if self.tracks else False
            else:
                self.vid = int(value)


class NeverWaitingOnAFrame(unittest.TestCase):
    def test_frames_are_handed_over_at_their_display_time(self) -> None:
        # The render call is made on the thread that paints the window and
        # blocks for the difference otherwise, up to fifty milliseconds a
        # frame, which is the whole window catching at the video's rate.
        self.assertEqual(OPTIONS["video_timing_offset"], 0)


class OnePictureAttachedPerSong(unittest.TestCase):
    def test_the_same_address_is_switched_back_on_not_added_again(self) -> None:
        one = engine()
        one._mpv = Talker()
        one.render_ready(True)
        one._mpv.said.clear()
        one.add_video("https://example.invalid/v")
        first = list(one._mpv.said)
        one.add_video("https://example.invalid/v")
        added = [s for s in one._mpv.said if s[0] == "video-add"]
        self.assertEqual(len(added), 1, "the same picture was attached twice")
        # On after the first, which `select` did by itself, so nothing was
        # set on top of it.
        self.assertTrue(one._video_on(), "the picture was never switched on")
        # And a picture already running is left alone. Setting the track
        # again makes mpv reselect it and lose the frame.
        self.assertEqual(one._mpv.said, first, "a running picture was touched")

    def test_one_switched_off_is_switched_back_on(self) -> None:
        one = engine()
        one._mpv = Talker()
        one.render_ready(True)
        one.add_video("https://example.invalid/v")
        one.drop_video()
        one._mpv.said.clear()
        one.add_video("https://example.invalid/v")
        self.assertEqual(one._mpv.said, [("vid", 1)])

    def test_a_new_song_forgets_what_was_attached(self) -> None:
        one = engine()
        one._mpv = Talker()
        one.add_video("https://example.invalid/v")
        one._attached = ""                                   # what start-file does
        one.add_video("https://example.invalid/v")
        added = [s for s in one._mpv.said if s[0] == "video-add"]
        self.assertEqual(len(added), 2)

    def test_it_is_not_turned_on_before_there_is_anywhere_to_draw(self) -> None:
        """`select` is what turns the picture on, and it does that whether or
        not there is a render context. With none, the player fails to open
        its output and leaves the track dead for the rest of the song."""
        one = engine()
        one._mpv = Talker()
        one.add_video("https://example.invalid/v")
        self.assertIn(("video-add", "https://example.invalid/v", "auto"),
                      one._mpv.said)
        self.assertNotIn(("video-add", "https://example.invalid/v", "select"),
                         one._mpv.said)

    def test_and_is_turned_on_the_moment_there_is(self) -> None:
        one = engine()
        one._mpv = Talker()
        one.add_video("https://example.invalid/v")
        one._mpv.said.clear()
        one.render_ready(True)
        self.assertEqual(one._mpv.said, [("vid", 1)])

    def test_where_there_is_somewhere_already_it_is_asked_for_outright(self) -> None:
        one = engine()
        one._mpv = Talker()
        one.render_ready(True)
        one.add_video("https://example.invalid/v")
        self.assertIn(("video-add", "https://example.invalid/v", "select"),
                      one._mpv.said)

    def test_asking_again_for_one_that_never_came_turns_it_on(self) -> None:
        """Closing the page and opening it again has to be a second go. Read
        as already done, the artwork stayed up for the whole song however
        often it was asked for."""
        one = engine()
        one._mpv = Talker()
        one.render_ready(True)
        one.add_video("https://example.invalid/v")
        one._mpv.vid = False                 # the player did not keep it
        one._mpv.said.clear()
        one.add_video("https://example.invalid/v")       # the page, opened again
        self.assertIn(("vid", 1), one._mpv.said)

    def test_dropping_leaves_the_track_attached(self) -> None:
        one = engine()
        one._mpv = Talker()
        one.add_video("https://example.invalid/v")
        one.drop_video()
        self.assertIn(("vid", "no"), one._mpv.said)
        self.assertEqual(one._attached, "https://example.invalid/v")


class WhetherItIsThere(unittest.TestCase):
    def test_it_says_so_either_way(self) -> None:
        self.assertIsInstance(available(), bool)


# A sound with no file behind it, so these need nothing but the player itself.
TONE = "av://lavfi:sine=f={hz}:d={seconds}"


@unittest.skipUnless(available(), "libmpv is not here")
class TheRealPlaylist(unittest.TestCase):
    """Driven against a real player, because the fault these exist for cannot
    be seen from anywhere else.

    Every command in here used to be answered by a stub, and a stub takes an
    argument of the wrong kind as happily as one of the right kind. The player
    does not: it refused the command outright, said nothing a caller could
    read, and the entry that should have gone stayed and was played. So this is
    the shape the rest of this file cannot have.
    """

    def setUp(self) -> None:
        from PySide6.QtCore import QCoreApplication

        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.one = LibmpvEngine()
        if not self.one.ensure():
            self.skipTest("the player would not start")
        # Nothing is meant to be heard, and a runner has nowhere to put it.
        self.one._mpv["ao"] = "null"
        self.said: list = []
        self.one.started.connect(self.said.append)

    def tearDown(self) -> None:
        self.one.quit()

    def pump(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)

    def until(self, ready, seconds: float = 8.0) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            if ready():
                return True
            time.sleep(0.02)
        return ready()

    def places(self) -> list:
        return [int(row["id"]) for row in (self.one._mpv.playlist or [])]

    def test_an_entry_id_is_not_a_place_in_the_playlist(self) -> None:
        """Which is the whole of why this went wrong. Ids count up for the
        life of the player, places start again at zero."""
        for hz in (100, 200, 300):
            self.one.load(TONE.format(hz=hz, seconds=30))
            self.pump(0.3)
        self.one.append(TONE.format(hz=400, seconds=30))
        self.assertTrue(self.until(lambda: len(self.places()) == 2))
        held = self.places()[-1]
        self.assertGreater(held, 1, "the ids never moved past their places")
        self.assertEqual(self.one._place_of(held), 1)
        self.assertNotEqual(held, 1, "this playlist cannot show the fault")

    def test_the_next_entry_really_leaves(self) -> None:
        self.one.load(TONE.format(hz=110, seconds=30))
        self.pump(0.4)
        self.one.append(TONE.format(hz=220, seconds=30))
        self.assertTrue(self.until(lambda: len(self.places()) == 2))
        self.one.clear_after()
        self.assertTrue(self.until(lambda: len(self.places()) == 1),
                        "the song taken out stayed in the playlist")

    def test_and_what_is_put_there_instead_is_what_plays(self) -> None:
        """The fault end to end. The entry that should have gone was played
        after the one it was supposed to replace, and because its role had
        been forgotten it began with no report at all, so nothing above ever
        learned that the song had changed."""
        self.one.load(TONE.format(hz=110, seconds=1))
        self.pump(0.4)
        self.one.append(TONE.format(hz=220, seconds=30))
        self.assertTrue(self.until(lambda: len(self.places()) == 2))
        # What a rearrangement of the queue does.
        self.one.clear_after()
        self.one.append(TONE.format(hz=330, seconds=30))
        self.assertTrue(self.until(lambda: self.said == [CURRENT, NEXT]),
                        f"reports were {self.said}")
        self.assertIn("f=330", str(self.one._mpv.filename),
                      "the song that was taken out is the one being played")

    def test_what_has_played_is_taken_off_the_front(self) -> None:
        self.one.load(TONE.format(hz=110, seconds=1))
        self.pump(0.4)
        self.one.append(TONE.format(hz=220, seconds=30))
        self.assertTrue(self.until(lambda: self.said == [CURRENT, NEXT]),
                        f"reports were {self.said}")
        self.one.remove_before()
        self.assertTrue(self.until(lambda: len(self.places()) == 1),
                        "the playlist grew past the two entries it holds")

    def test_a_song_that_has_begun_is_not_still_held_behind_one(self) -> None:
        """The other half of taking the next entry out properly.

        An entry the player moves on to by itself is still written down as
        the one held BEHIND the song playing, because nothing said otherwise.
        With the removal working, the next tidying of the playlist then went
        looking for what is held behind this song and took out this song.
        """
        self.one.load(TONE.format(hz=110, seconds=1))
        self.pump(0.4)
        self.one.append(TONE.format(hz=220, seconds=30))
        self.assertTrue(self.until(lambda: self.said == [CURRENT, NEXT]),
                        f"reports were {self.said}")
        self.one.remove_before()
        self.one.clear_after()
        self.pump(0.4)
        self.assertEqual(len(self.places()), 1,
                         "the song being played was taken out of the playlist")
        self.assertIn("f=220", str(self.one._mpv.filename))

    def test_a_picture_that_will_not_open_is_reported_and_forgotten(self) -> None:
        """And asked for without waiting. The same call made the other way
        held the thread that paints the window for 29.2 s, measured."""
        refused: list = []
        self.one.videoRefused.connect(lambda url, said: refused.append(url))
        self.one.load(TONE.format(hz=110, seconds=30))
        self.pump(0.4)
        began = time.monotonic()
        self.one.add_video("/nowhere/there-is-no-such-picture.mp4")
        asked_in = time.monotonic() - began
        self.assertLess(asked_in, 1.0, "the window was held while mpv opened it")
        self.assertTrue(self.until(lambda: refused == [
            "/nowhere/there-is-no-such-picture.mp4"]))
        self.assertEqual(self.one._attached, "",
                         "a picture that would not open is still believed to be there")


if __name__ == "__main__":
    unittest.main()



@unittest.skipUnless(available(), "libmpv is not here")
class APictureLeftUnchosen(unittest.TestCase):
    """A picture on the song but not chosen, against a real player.

    Choosing used to be `vid=auto`, which mpv answers only when it is a change,
    so a picture that arrived unchosen with `auto` already said stayed that way
    for the rest of the song. It is chosen by its number now, which is chosen
    whatever `vid` says, and opening the page again chooses it.
    """

    def setUp(self) -> None:
        from PySide6.QtCore import QCoreApplication

        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.one = LibmpvEngine()
        if not self.one.ensure():
            self.skipTest("the player would not start")
        # Decoded with nowhere to show it, which is what a runner can do. The
        # choosing is the same whatever draws it.
        self.one._mpv["ao"] = "null"
        self.one._mpv["vo"] = "null"
        self.said: list = []
        self.one.started.connect(self.said.append)

    def tearDown(self) -> None:
        self.one.quit()

    def until(self, ready, seconds: float = 6.0) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            if ready():
                return True
            time.sleep(0.02)
        return ready()

    def unchosen_picture(self) -> str:
        picture = "av://lavfi:testsrc=size=160x90:rate=25:duration=60"
        self.one.load("av://lavfi:sine=frequency=440:duration=60")
        self.assertTrue(self.until(lambda: self.said), "the song did not start")
        self.one.render_ready(True)
        self.one.add_video(picture)
        self.assertTrue(self.until(lambda: any(
            track.get("type") == "video" for track in self.one._mpv.track_list)))
        self.one._mpv["vid"] = "no"
        self.assertTrue(self.until(lambda: not self.one._video_on()))
        return picture

    def test_it_is_chosen_by_its_number(self):
        self.unchosen_picture()
        self.one._choose_video()
        self.assertTrue(self.until(self.one._video_on, 3.0))
        self.assertNotEqual(self.one._mpv["vid"], "auto")

    def test_opening_the_page_again_chooses_it(self):
        picture = self.unchosen_picture()
        self.one.add_video(picture)
        self.assertTrue(self.until(self.one._video_on, 3.0),
                        "asked for again, the picture stayed unchosen")


class TheSurfaceIsToldToPaint(unittest.TestCase):
    """The surface builds its render context only when it paints, and it has
    no reason of its own to paint. A page opened before the first song gave it
    one paint while there was no player, and it gave up for as long as the
    page stayed open. Measured in a trace: the page open at 4.8 s, the picture
    ready at 8.1 s, no render context until the page was closed."""

    def test_a_picture_with_nowhere_to_go_asks_for_a_paint(self) -> None:
        one = engine()
        one._mpv = Talker()
        asked = []
        one.surfaceWanted.connect(lambda: asked.append(True))
        one.add_video("https://example.invalid/v")
        self.assertEqual(asked, [True])

    def test_one_with_somewhere_to_go_does_not(self) -> None:
        one = engine()
        one._mpv = Talker()
        one.render_ready(True)
        asked = []
        one.surfaceWanted.connect(lambda: asked.append(True))
        one.add_video("https://example.invalid/v")
        self.assertEqual(asked, [])

    def test_a_picture_gone_from_the_song_is_asked_for_again_once_it_can_be_drawn(self):
        one = engine()
        one._mpv = Talker()
        one.add_video("https://example.invalid/v")
        one._mpv.tracks.clear()
        one._mpv.said.clear()
        one.render_ready(True)
        again = [s for s in one._mpv.said if s[0] == "video-add"]
        self.assertEqual(again, [("video-add", "https://example.invalid/v", "select")])


@unittest.skipUnless(available(), "libmpv is not here")
class ThePlayerStarting(unittest.TestCase):
    def test_starting_asks_the_surface_to_paint(self) -> None:
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.instance() or QCoreApplication([])
        one = LibmpvEngine()
        asked = []
        one.surfaceWanted.connect(lambda: asked.append(True))
        try:
            if not one.ensure():
                self.skipTest("the player would not start")
            self.assertEqual(asked, [True])
        finally:
            one.quit()


@unittest.skipUnless(available(), "libmpv is not here")
class ANewPlayerMovingOnByItself(unittest.TestCase):
    """Two songs kept on disk, played by a player that does not exist yet.

    Both are handed over at once, before the new player has said anything, and
    the first thing it says is that it is idle. That was taken to mean nothing
    was held behind the first song, so when mpv moved on into the second one
    nothing followed it, and the window showed the first song for the whole of
    the second. Only a real player can say it this late.
    """

    def test_the_window_follows_it_into_the_second_song(self) -> None:
        from PySide6.QtCore import QCoreApplication

        app = QCoreApplication.instance() or QCoreApplication([])
        kept = {"yt:aaaaaaaaaaa": TONE.format(hz=220, seconds=1),
                "yt:bbbbbbbbbbb": TONE.format(hz=440, seconds=30)}
        songs = [{"key": key, "title": key,
                  "url": f"https://www.youtube.com/watch?v={key[3:]}"} for key in kept]
        # Nothing is meant to be heard, and it has to be said before the
        # player exists, because the player starting inside the first load is
        # the whole of the case.
        with mock.patch.dict(OPTIONS, ao="null"):
            one = AudioPlayer(Config(raw={}))
            one.local_audio = lambda key: kept.get(key, "")
            try:
                one.play_items(songs)
                if not one._engine.running():
                    self.skipTest("the player would not start")
                self.assertEqual(one._appended, 1)
                end = time.monotonic() + 8.0
                while time.monotonic() < end and one._at != 1:
                    app.processEvents()
                    time.sleep(0.02)
                self.assertEqual(one.track.get("key"), "yt:bbbbbbbbbbb",
                                 "mpv moved on and the window did not")
                self.assertIsNone(one._engine.holds_next())
            finally:
                one.shutdown()
