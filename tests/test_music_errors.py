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
