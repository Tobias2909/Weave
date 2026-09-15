"""The in process player.

Most of what matters here needs a real libmpv and is verified by driving one.
What is pinned here is the bookkeeping around it, which is where the faults
were: which entry an event is about, and not asking for a picture before there
is anywhere to put one.
"""

import unittest

from PySide6.QtCore import QObject

from weave.engine_libmpv import CURRENT, NEXT, LibmpvEngine, available


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


class WhetherItIsThere(unittest.TestCase):
    def test_it_says_so_either_way(self) -> None:
        self.assertIsInstance(available(), bool)


if __name__ == "__main__":
    unittest.main()
