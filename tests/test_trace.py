"""The evidence path for the page catching.

What is pinned is that it costs nothing when off, that it writes what it is
told when on, and that the sound server's report is read at the right column.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from weave import trace

PW_TOP = """S   ID  QUANT   RATE    WAIT    BUSY   W/Q   B/Q  ERR FORMAT           NAME
S   31      0      0   0.0us   0.0us  0.00  0.00    0                  Dummy-Driver
R   45   1024  48000  71.3us  22.4us  0.01  0.00    0    S32LE 2 48000 alsa_output.usb
 +  88   1024  48000  40.1us  13.9us  0.00  0.00    3    F32LE 2 48000 weave
 +  91   1024  48000  12.0us   3.9us  0.00  0.00    0    F32LE 2 48000 Firefox
"""


class WhenOff(unittest.TestCase):
    def test_a_mark_is_a_no_op(self) -> None:
        trace.close_log()
        trace.mark("anything", a=1)                    # must not raise or write

    def test_start_answers_none_without_the_flag(self) -> None:
        with mock.patch.dict(os.environ, {trace.ENV: ""}):
            self.assertIsNone(trace.start(app=None))


class WhenOn(unittest.TestCase):
    def test_a_mark_is_one_line_with_a_clock_and_a_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = trace.open_log(Path(tmp) / "trace.log")
            trace.mark("page", wanted=True)
            trace.close_log()
            lines = path.read_text().splitlines()
        self.assertEqual(lines[0].split()[2], "start")
        fields = lines[1].split()
        float(fields[0])                               # milliseconds since start
        self.assertIn("page", fields)
        self.assertIn("wanted=True", fields)

    def test_only_a_slow_render_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = trace.open_log(Path(tmp) / "trace.log")
            with trace.Timed():
                pass
            trace.close_log()
            self.assertNotIn("render_slow", path.read_text())

    def test_the_player_is_quoted_only_for_the_words_that_matter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = trace.open_log(Path(tmp) / "trace.log")
            trace.player_said("v", "vo/libmpv",
                              "mpv_render_context_render() not being called or stuck.")
            trace.player_said("v", "cplayer", "playback position 12.3")
            trace.player_said("warn", "ao/pipewire", "anything at warn level")
            trace.close_log()
            text = path.read_text()
        self.assertIn("not being called", text)
        self.assertIn("anything at warn level", text)
        self.assertNotIn("playback position", text)


class TheSoundServersReport(unittest.TestCase):
    def test_the_count_is_read_for_this_application(self) -> None:
        self.assertEqual(trace.parse_xruns(PW_TOP), 3)

    def test_another_application_is_not_ours(self) -> None:
        self.assertEqual(trace.parse_xruns(PW_TOP, node="Firefox"), 0)

    def test_absent_is_none(self) -> None:
        self.assertIsNone(trace.parse_xruns(PW_TOP, node="nothing"))
        self.assertIsNone(trace.parse_xruns(""))


class TheClock(unittest.TestCase):
    def test_a_position_behind_the_wall_is_a_slip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = trace.open_log(Path(tmp) / "trace.log")
            clock = trace.Clock()
            with mock.patch("weave.trace.time.monotonic", side_effect=[100.0, 100.5, 100.5]):
                clock.report(10.0, paused=False)
                clock.report(10.1, paused=False)      # 0.1 s moved in 0.5 s of wall
            trace.close_log()
            self.assertIn("clock_slip", path.read_text())

    def test_a_position_keeping_up_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = trace.open_log(Path(tmp) / "trace.log")
            clock = trace.Clock()
            with mock.patch("weave.trace.time.monotonic", side_effect=[100.0, 100.5, 100.5]):
                clock.report(10.0, paused=False)
                clock.report(10.5, paused=False)
            trace.close_log()
            self.assertNotIn("clock_slip", path.read_text())


if __name__ == "__main__":
    unittest.main()
