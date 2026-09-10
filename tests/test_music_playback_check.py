"""The check that walks the whole music chain.

Pressing a song either plays or does nothing, and the window has one line for
four different failures behind that. This is the thing that says which, so
what it has to get right is naming the step rather than the symptom.
"""

import unittest

from PySide6.QtCore import QCoreApplication

from weave import doctor
from weave.config import Config

_app = QCoreApplication.instance() or QCoreApplication([])


class Hook:
    """A signal that only has to be connected to and fired."""

    def __init__(self):
        self.handlers = []

    def connect(self, handler):
        self.handlers.append(handler)

    def fire(self, *args):
        for handler in self.handlers:
            handler(*args)


class FakePlayer:
    def __init__(self, starts=True, position=None, trouble=""):
        self.gone = Hook()
        self.ended = Hook()
        self.positionChanged = Hook()
        self.loaded = []
        self.quit_called = False
        self._starts = starts
        self._position = position
        self._trouble = trouble

    def ensure(self):
        if not self._starts:
            self.gone.fire(self._trouble or "mpv would not start")
        return self._starts

    def load(self, address, start=None):
        self.loaded.append(address)
        if self._position is not None:
            self.positionChanged.fire(self._position)
        if self._trouble:
            self.ended.fire("error")

    def set_pause(self, paused):
        pass

    def quit(self):
        self.quit_called = True


class TheChain(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(raw={})
        from weave import audio, engine

        self.addCleanup(setattr, doctor.shutil, "which", doctor.shutil.which)
        self.addCleanup(setattr, audio, "resolve_address", audio.resolve_address)
        self.addCleanup(setattr, engine, "MusicEngine", engine.MusicEngine)
        self.audio, self.engine = audio, engine
        doctor.shutil.which = lambda _name: "/usr/bin/mpv"
        self.address("https://rr1.googlevideo.com/videoplayback?expire=1")

    def address(self, said):
        self.audio.resolve_address = lambda *_a, **_k: self.audio.Resolved(said, ())

    def use(self, player):
        self.engine.MusicEngine = lambda *a, **k: player
        return player

    def run_check(self, seconds=1.0):
        report = doctor.Report()
        doctor.playback(self.cfg, report, "https://example.invalid/watch", seconds)
        return {check.name: check for check in report.checks}

    def test_a_player_that_plays_is_the_whole_chain_answering(self):
        player = self.use(FakePlayer(position=1.4))
        found = self.run_check()
        self.assertEqual(found["the address"].state, doctor.OK)
        self.assertEqual(found["the player"].state, doctor.OK)
        self.assertEqual(found["playing"].state, doctor.OK)
        self.assertIn("1.4 s", found["playing"].detail)
        self.assertTrue(player.quit_called)

    def test_no_mpv_stops_before_anything_is_asked_of_the_network(self):
        doctor.shutil.which = lambda _name: None
        asked = []
        self.audio.resolve_address = lambda *a, **k: asked.append(1)
        found = self.run_check()
        self.assertEqual(found["mpv"].state, doctor.FAIL)
        self.assertEqual(asked, [])
        self.assertNotIn("the address", found)

    def test_an_address_that_never_comes_is_named_as_such(self):
        def refused(*_a, **_k):
            raise RuntimeError("Sign in to confirm you are not a bot")

        self.audio.resolve_address = refused
        found = self.run_check()
        self.assertEqual(found["the address"].state, doctor.FAIL)
        self.assertIn("not a bot", found["the address"].detail)
        # And nothing further is claimed about a chain that stopped here.
        self.assertNotIn("the player", found)

    def test_a_player_that_will_not_start_says_why(self):
        self.use(FakePlayer(starts=False, trouble="mpv did not open its socket"))
        found = self.run_check()
        self.assertEqual(found["the player"].state, doctor.FAIL)
        self.assertIn("socket", found["the player"].detail)
        self.assertNotIn("playing", found)

    def test_a_player_that_takes_the_address_and_plays_nothing(self):
        # The case a machine with no working sound output lands in.
        self.use(FakePlayer(position=None, trouble="broken"))
        found = self.run_check()
        self.assertEqual(found["playing"].state, doctor.FAIL)
        self.assertIn("ended the track", found["playing"].detail)

    def test_silence_with_no_complaint_is_still_a_failure(self):
        self.use(FakePlayer(position=None))
        found = self.run_check(seconds=0.3)
        self.assertEqual(found["playing"].state, doctor.FAIL)
        self.assertIn("nothing played", found["playing"].detail)

    def test_a_position_that_never_leaves_the_start_is_not_sound(self):
        # mpv reports 0.0 the moment a file is opened, and an opened file
        # that never advances is exactly the failure being looked for.
        self.use(FakePlayer(position=0.0))
        found = self.run_check(seconds=0.3)
        self.assertEqual(found["playing"].state, doctor.FAIL)
