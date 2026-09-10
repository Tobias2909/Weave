"""What the music area says when it cannot do the thing.

Every music failure reaches a person as one line in the window, so the line
has to name which call broke. The one that started this said only
KeyError: 'endpoint', which is what ytmusicapi before 1.12.2 raises out of
its own watch parser when a station is asked for, and it looked exactly like
a broken account on a machine whose account was fine.
"""

import unittest

from weave.sources import ytmusic


class TheVersion(unittest.TestCase):
    """Read from the library itself, so the cases that matter are put in
    front of it rather than taken from whatever this machine happens to
    have. The music area is an optional extra, and the machine running the
    tests is quite likely one where it is not installed at all."""

    def use(self, said):
        self.addCleanup(setattr, ytmusic, "installed", ytmusic.installed)
        ytmusic.installed = lambda: said

    def saying(self, version):
        """Stand a library in front of it that reports this version."""
        import sys
        import types

        fake = types.ModuleType("ytmusicapi")
        fake.__version__ = version
        real = sys.modules.get("ytmusicapi")
        sys.modules["ytmusicapi"] = fake
        # Put back what was there, and nothing at all when nothing was, or
        # the next import in this process finds a None and gives up.
        if real is None:
            self.addCleanup(sys.modules.pop, "ytmusicapi", None)
        else:
            self.addCleanup(sys.modules.__setitem__, "ytmusicapi", real)

    def test_a_release_is_read_as_numbers(self):
        self.saying("1.12.2")
        self.assertEqual(ytmusic.installed(), (1, 12, 2))

    def test_a_pre_release_counts_as_the_release_it_is_becoming(self):
        # "1.13.0rc1" must not read as 1.13.01 or anything larger.
        self.saying("1.13.0rc1")
        self.assertEqual(ytmusic.installed(), (1, 13, 0))

    def test_no_library_at_all_is_no_version(self):
        # Which is what a machine without the music extra answers, the
        # build that runs these tests among them.
        import sys

        real = sys.modules.pop("ytmusicapi", None)
        if real is not None:
            self.addCleanup(sys.modules.__setitem__, "ytmusicapi", real)
        import builtins

        importer = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name == "ytmusicapi":
                raise ImportError("no ytmusicapi here")
            return importer(name, *args, **kwargs)

        builtins.__import__ = refuse
        self.addCleanup(setattr, builtins, "__import__", importer)
        self.assertEqual(ytmusic.installed(), ())

    def test_an_old_one_is_complained_about(self):
        self.use((1, 11, 1))
        self.assertIn("1.11.1 is installed", ytmusic.too_old())
        self.assertIn("1.12.2", ytmusic.too_old())

    def test_a_new_enough_one_is_not(self):
        self.use((1, 12, 2))
        self.assertEqual(ytmusic.too_old(), "")

    def test_one_that_is_not_there_is_not_called_old(self):
        # Not installed is a different sentence, said where it is noticed.
        self.use(())
        self.assertEqual(ytmusic.too_old(), "")


class TheSentence(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, ytmusic, "installed", ytmusic.installed)
        self.addCleanup(setattr, ytmusic, "client", ytmusic.client)

    def test_the_call_that_failed_is_named(self):
        ytmusic.installed = lambda: (1, 12, 2)

        def broken(_profile):
            raise KeyError("endpoint")

        ytmusic.client = broken
        with self.assertRaises(ytmusic.MusicError) as caught:
            ytmusic.radio("/nowhere", "abc")
        said = str(caught.exception)
        self.assertIn("the station", said)
        self.assertIn("KeyError", said)

    def test_an_old_library_is_named_as_the_reason(self):
        ytmusic.installed = lambda: (1, 11, 1)

        def broken(_profile):
            raise KeyError("endpoint")

        ytmusic.client = broken
        with self.assertRaises(ytmusic.MusicError) as caught:
            ytmusic.radio("/nowhere", "abc")
        self.assertIn("1.11.1 is installed", str(caught.exception))

    def test_a_login_failure_is_left_alone(self):
        # MusicError already says something useful and must not be rewritten
        # as a library problem.
        def refused(_profile):
            raise ytmusic.MusicError("the browser profile holds no YouTube login")

        ytmusic.client = refused
        with self.assertRaises(ytmusic.MusicError) as caught:
            ytmusic.radio("/nowhere", "abc")
        self.assertEqual(str(caught.exception),
                         "the browser profile holds no YouTube login")


class WhatTheWindowShows(unittest.TestCase):
    """A failure nobody is listening to is the same as no failure.

    AudioPlayer.failed was connected to nothing, so a track that would not
    play said the same thing for a dead login, a missing solver and a broken
    sound card: nothing at all, anywhere in the window.
    """

    def setUp(self):
        from PySide6.QtCore import QCoreApplication, QObject, Signal

        self.app = QCoreApplication.instance() or QCoreApplication([])

        class Player(QObject):
            failed = Signal(str)
            trackChanged = Signal()

            def pause_for_video(self):
                pass

        from weave.ui.bridge import Bridge

        self.Bridge = Bridge
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._problems = []
        self.bridge._status = ""
        self.player = Player()

        class Video(QObject):
            nowPlaying = Signal(str)

        self.bridge._player = Video()

    def test_a_track_that_will_not_play_reaches_the_banner(self):
        self.Bridge.attach_audio(self.bridge, self.player)
        self.player.failed.emit("the track could not be played, install something")
        self.assertEqual(self.bridge._problems,
                         ["the track could not be played, install something"])

    def test_and_the_status_line_as_well(self):
        self.Bridge.attach_audio(self.bridge, self.player)
        self.player.failed.emit("no")
        self.assertEqual(self.bridge._status, "no")


class WhatTheWindowSaysUnprompted(unittest.TestCase):
    """The challenge needs two things and names neither when it fails, so
    the window says which is missing without waiting to be pressed."""

    def setUp(self):
        from PySide6.QtCore import QCoreApplication, QObject

        self.app = QCoreApplication.instance() or QCoreApplication([])
        from weave.sources import ytdlp
        from weave.ui.bridge import Bridge

        self.ytdlp, self.Bridge = ytdlp, Bridge
        self.addCleanup(setattr, ytdlp, "solver", ytdlp.solver)
        self.addCleanup(setattr, ytdlp, "js_runtime_args", ytdlp.js_runtime_args)
        self.addCleanup(setattr, ytdlp, "challenge_missing", ytdlp.challenge_missing)
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._problems = []

    def note(self):
        # Both halves: the sentence the probe composes off the thread, and
        # the bridge putting it on the banner once.
        self.Bridge._on_challenge_answered(                       # noqa: SLF001
            self.bridge, self.ytdlp.challenge_missing())
        return self.bridge._problems

    def test_a_missing_solver_is_on_the_banner_before_anything_is_pressed(self):
        self.ytdlp.solver = lambda: (False, "yt-dlp-ejs is not installed")
        said = self.note()
        self.assertEqual(len(said), 1)
        self.assertIn("pip install --user yt-dlp-ejs", said[0])

    def test_it_is_said_once_and_not_on_every_look(self):
        self.ytdlp.solver = lambda: (False, "yt-dlp-ejs is not installed")
        self.note()
        self.assertEqual(len(self.note()), 1)

    def test_a_machine_with_both_is_left_in_peace(self):
        self.ytdlp.solver = lambda: (True, "yt-dlp-ejs 0.8.0")
        self.ytdlp.js_runtime_args = lambda: ["--js-runtimes", "node:/usr/bin/node"]
        self.assertEqual(self.note(), [])

    def test_the_asking_happens_off_the_interface_thread(self):
        """Finding out runs a small program, and on the interface thread that
        is a window that stops answering for as long as it takes."""
        from PySide6.QtCore import QRunnable

        from weave.ui.bridge import _ChallengeProbe                # noqa: SLF001

        self.assertTrue(issubclass(_ChallengeProbe, QRunnable))
        probe = _ChallengeProbe()
        self.ytdlp.solver = lambda: (False, "yt-dlp-ejs is not installed")
        said = []
        probe.answered.connect(said.append)
        probe.run()
        self.assertEqual(len(said), 1)
        self.assertIn("pip install --user yt-dlp-ejs", said[0])

    def test_a_probe_that_cannot_answer_says_nothing_and_does_not_take_the_app(self):
        from weave.ui.bridge import _ChallengeProbe                # noqa: SLF001

        def boom():
            raise OSError("no")

        self.ytdlp.challenge_missing = boom
        probe = _ChallengeProbe()
        said = []
        probe.answered.connect(said.append)
        probe.run()
        self.assertEqual(said, [""])


class EveryRouteToTheBanner(unittest.TestCase):
    """A song can be pressed by several routes and any of them can come back
    with something to install. The station and the shelves used to reach the
    status line only, which is gone in seconds."""

    def setUp(self):
        from PySide6.QtCore import QCoreApplication, QObject

        self.app = QCoreApplication.instance() or QCoreApplication([])
        from weave.ui.bridge import Bridge

        self.Bridge = Bridge
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._problems = []
        self.bridge._status = ""
        self.bridge._searching = True

    def fail(self, message):
        self.Bridge._on_search_failed(self.bridge, message)
        return self.bridge._problems

    def test_something_to_install_is_kept_on_the_banner(self):
        said = self.fail("run python3 -m pip install --user yt-dlp-ejs")
        self.assertEqual(len(said), 1)
        self.assertIn("yt-dlp-ejs", said[0])

    def test_a_missing_runtime_too(self):
        self.assertEqual(len(self.fail("no JavaScript runtime was found")), 1)

    def test_an_ordinary_miss_stays_on_the_status_line(self):
        self.assertEqual(self.fail("nothing matched"), [])
        self.assertIn("nothing matched", self.bridge._status)

    def test_the_same_thing_twice_is_one_line_not_two(self):
        self.fail("run python3 -m pip install --user yt-dlp-ejs")
        self.assertEqual(len(self.fail("run python3 -m pip install --user yt-dlp-ejs")), 1)
