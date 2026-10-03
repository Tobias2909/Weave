"""A music video that never appears writes down what led up to it.

The fault is rare and has never been caught in a trace, because tracing has to
be switched on before it happens. So the marks are kept in memory always, and
a step line that waits far past anything merely slow writes them to a file.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_audio import FakeEngine, FakeResolver, signed  # noqa: E402

from weave import trace  # noqa: E402


class TheMarksAreKeptWithoutALog(unittest.TestCase):
    def test_a_mark_reaches_the_memory_with_no_log_open(self):
        self.assertIsNone(trace._file)
        trace.mark("kept_without_a_log", n=1)
        self.assertIn("kept_without_a_log n=1", trace._ring[-1])

    def test_they_are_written_under_a_line_saying_why(self):
        trace.mark("before_the_report")
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / "stuck.log"
            self.assertEqual(trace.dump("testing", path, stage="x"), path)
            written = path.read_text()
        self.assertIn(" testing stage=x\n", written)
        self.assertIn("before_the_report", written)


class AStepLineThatWaitsTooLong(unittest.TestCase):
    def setUp(self):
        from weave.audio import AudioPlayer
        from weave.config import Config

        self._home = tempfile.TemporaryDirectory()
        self.path = Path(self._home.name) / "stuck.log"
        self._real = trace.STUCK
        trace.STUCK = self.path
        self.addCleanup(setattr, trace, "STUCK", self._real)
        self.player = AudioPlayer(Config(raw={}), engine=FakeEngine())
        self.player._make_resolver = lambda entry: FakeResolver(entry["key"])
        items = [{"key": "yt:a", "title": "a", "url": "ua"}]
        self.player._addresses.put("yt:a", signed("yt:a"))
        self.player.play_items(items, 0)

    def tearDown(self):
        self._home.cleanup()

    def opening(self):
        from weave import audio

        self.player._video_wanted = True
        self.player._video_stage = audio.STAGE_OPENING
        self.player.videoChanged.emit()

    def test_waiting_starts_the_clock(self):
        self.opening()
        self.assertTrue(self.player._stuck_timer.isActive())

    def test_the_picture_arriving_stops_it(self):
        self.opening()
        self.player._on_video_frame(True)
        self.assertFalse(self.player._stuck_timer.isActive())

    def test_running_out_writes_the_report(self):
        self.opening()
        self.player._picture_stuck()
        written = self.path.read_text()
        self.assertIn("the picture never came stage=Opening_the_video key=yt:a", written)
        self.assertIn("stage stage=Opening_the_video key=yt:a", written)

    def test_nothing_is_written_once_the_picture_is_there(self):
        self.opening()
        self.player._video_showing = True
        self.player._picture_stuck()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
