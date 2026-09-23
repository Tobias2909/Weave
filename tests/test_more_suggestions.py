"""Reaching the foot of the suggestions.

Three faults met there, and only the first was visible. An empty slice was
raised as a failure, so the status line said "the recommendations came back
empty", which reads as a fault and is not one. The failure left the loading
flag up, so the foot of the page never asked for anything again for the rest
of the session. And the next slice was worked out from how many rows are
STORED rather than from how many positions have been asked for, so a slice
that yielded nothing asked for the same positions again.

Measured against the endpoint: YouTube builds this list afresh for every
request, a slice with nothing in it can be followed by a full one, and yt-dlp
says nothing on stderr for any of it.
"""

import unittest

from weave.sources import ytdlp


class Result:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class AnEmptySliceIsAnAnswer(unittest.TestCase):
    def fetch(self, result):
        from weave import config
        from weave.sources import recommended

        original = recommended.ytdlp.run
        recommended.ytdlp.run = lambda *a, **k: result
        try:
            return recommended.fetch(config.Config(raw={}), limit=48, start=97)
        finally:
            recommended.ytdlp.run = original

    def test_nothing_at_all_is_not_a_failure(self):
        self.assertEqual(self.fetch(Result()), [])

    def test_but_a_run_that_complained_still_is(self):
        from weave.sources.recommended import RecommendedError

        said = "ERROR: [youtube] Sign in to confirm you are not a bot"
        with self.assertRaises(RecommendedError):
            self.fetch(Result(stderr=said, returncode=1))

    def test_the_guard_is_the_one_the_others_carry(self):
        # The same rule a search and the history use, so the three cannot
        # drift into disagreeing about what an empty answer means.
        self.assertFalse(ytdlp.complained(Result()))
        self.assertTrue(ytdlp.complained(Result(stderr="ERROR: nope", returncode=1)))


class Bridge:
    """Enough of one to drive the paging by hand."""

    PAGE = 24

    def __init__(self, held=0):
        from weave.ui.bridge import Bridge as Real

        self.real = Real
        self.held = held
        self.asked = []
        self.statuses = []
        self.notices = []
        self._loading_more = False
        self._exhausted = False
        self._recommended_next = 1
        self._empty_slices = 0
        self._view_kind = "recommended"
        self._search_scope = ""
        self._web_results = []

    # What the real one reaches for.
    def _set_status(self, text):
        self.statuses.append(text)

    def _set_notice(self, *_a, **_k):
        self.notices.append(True)

    def _set_page_reading(self, *_a, **_k):
        self.notices.append(True)

    def _stop_page_reading(self, *_a, **_k):
        pass

    def _fetch_recommended(self, force=False, start=1, append=False):
        self.asked.append(start)
        self._recommended_next = start + self.PAGE * 2

    def reload(self):
        pass

    def _fetch_loose_avatars(self):
        pass

    @property
    def recommendedChanged(self):
        class Signal:
            @staticmethod
            def emit():
                pass
        return Signal

    @property
    def _db(self):
        held = self.held

        class Db:
            @staticmethod
            def recommended_count():
                return held
        return Db

    def answered(self, count):
        # The real one defers asking for the next slice through a timer, since
        # the worker that just answered has not finished yet. Here it is run
        # straight away, so the test sees what it asked for and no timer is
        # left holding a callback after the interpreter has gone.
        from weave.ui import bridge as module

        class Now:
            @staticmethod
            def singleShot(_ms, call):
                call()

        was = module.QTimer
        module.QTimer = Now
        try:
            self.real._on_recommended(self, count)
        finally:
            module.QTimer = was

    def failed(self, message):
        self.real._on_recommended_failed(self, message)


class WhatTheFootOfThePageDoes(unittest.TestCase):
    def test_a_full_slice_says_how_many_there_are(self):
        bridge = Bridge(held=90)
        bridge.answered(45)
        self.assertFalse(bridge._exhausted)
        self.assertFalse(bridge._loading_more)
        self.assertEqual(bridge._empty_slices, 0)
        self.assertIn("90 suggestions", bridge.statuses[-1])

    def test_one_empty_slice_asks_for_the_next_one_rather_than_stopping(self):
        # Nothing was added, so the grid did not grow and the foot of it cannot
        # ask again by itself. It is asked for here instead.
        bridge = Bridge(held=90)
        bridge._recommended_next = 97
        bridge.answered(0)
        self.assertFalse(bridge._exhausted)
        self.assertEqual(bridge._empty_slices, 1)
        self.assertEqual(bridge.asked, [97])

    def test_two_in_a_row_is_the_end_and_says_so_plainly(self):
        bridge = Bridge(held=90)
        bridge._empty_slices = 1
        bridge.answered(0)
        self.assertTrue(bridge._exhausted)
        self.assertIn("every one YouTube has", bridge.statuses[-1])
        self.assertNotIn("empty", bridge.statuses[-1])

    def test_a_full_slice_after_an_empty_one_starts_the_count_over(self):
        bridge = Bridge(held=90)
        bridge._empty_slices = 1
        bridge.answered(45)
        self.assertEqual(bridge._empty_slices, 0)
        self.assertFalse(bridge._exhausted)

    def test_nothing_at_all_is_not_called_the_end_of_anything(self):
        bridge = Bridge(held=0)
        bridge.answered(0)
        self.assertFalse(bridge._exhausted)
        self.assertIn("nothing", bridge.statuses[-1])

    def test_a_real_failure_puts_the_flag_down(self):
        """Left up, the foot of the page never asks for anything again."""
        bridge = Bridge(held=90)
        bridge._loading_more = True
        bridge.failed("yt-dlp said: no")
        self.assertFalse(bridge._loading_more)
        self.assertIn("yt-dlp said: no", bridge.statuses[-1])

    def test_the_next_slice_follows_the_positions_asked_for(self):
        """Not the rows that survived. A slice is filtered on the way in, so a
        cursor built from the stored count stands still whenever one yields
        none and asks for the same positions for ever."""
        bridge = Bridge(held=90)
        bridge._fetch_recommended(start=1, append=True)
        self.assertEqual(bridge._recommended_next, 49)
        bridge._fetch_recommended(start=bridge._recommended_next, append=True)
        self.assertEqual(bridge._recommended_next, 97)
        # Even though nothing at all was stored in between.
        self.assertEqual(bridge.asked, [1, 49])


if __name__ == "__main__":
    unittest.main()
