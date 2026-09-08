"""The checkup.

What matters here is that it answers rather than raises, and that its verdict
is honest, since the whole reason it exists is that a scraper failing looks
exactly like a scraper with nothing to say.
"""

import os
import tempfile
import unittest
from pathlib import Path

from weave import doctor
from weave.config import Config
from weave.db import Database, VideoRow


class Verdict(unittest.TestCase):
    def report(self, *states):
        report = doctor.Report()
        for index, state in enumerate(states):
            report.add(f"check {index}", state)
        return report

    def test_all_well(self):
        self.assertEqual(self.report(doctor.OK, doctor.OK).worst, doctor.OK)

    def test_one_worth_a_look(self):
        self.assertEqual(self.report(doctor.OK, doctor.WARN).worst, doctor.WARN)

    def test_anything_broken_wins(self):
        # A failure has to survive being outnumbered.
        self.assertEqual(self.report(doctor.OK, doctor.WARN, doctor.FAIL).worst, doctor.FAIL)

    def test_nothing_checked_is_not_a_failure(self):
        self.assertEqual(doctor.Report().worst, doctor.OK)

    def test_counting(self):
        counts = self.report(doctor.OK, doctor.OK, doctor.FAIL).counts()
        self.assertEqual((counts[doctor.OK], counts[doctor.FAIL]), (2, 1))


class Offline(unittest.TestCase):
    """The whole run, with nothing to reach for."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_it_answers_rather_than_raising(self):
        report = doctor.run(self.cfg, self.db, network=False)
        self.assertTrue(report.checks)
        self.assertTrue(all(c.state in (doctor.OK, doctor.WARN, doctor.FAIL)
                            for c in report.checks))

    def test_an_empty_database_is_reported_as_such(self):
        report = doctor.run(self.cfg, self.db, network=False)
        channels = next(c for c in report.checks if c.name == "channels")
        self.assertEqual(channels.state, doctor.FAIL)
        self.assertTrue(channels.fix)

    def test_a_filled_one_is_not(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "A")])
        report = doctor.run(self.cfg, self.db, network=False)
        channels = next(c for c in report.checks if c.name == "channels")
        self.assertEqual(channels.state, doctor.OK)

    def test_nothing_makes_a_request_when_asked_not_to(self):
        doctor.run(self.cfg, self.db, network=False)
        self.assertEqual(self.db.requests_in_window("feeds", 900), (0, 0))


class ToolVersions(unittest.TestCase):
    def test_a_tool_that_says_nothing_is_still_installed(self):
        # A wrapper that exits cleanly and prints nothing used to be an
        # IndexError out of the middle of the report.
        import subprocess
        from unittest import mock

        done = subprocess.CompletedProcess(["x"], 0, stdout="", stderr="")
        with mock.patch.object(doctor.subprocess, "run", return_value=done):
            self.assertEqual(doctor._version(["x", "--version"]), "installed")

    def test_the_first_line_is_the_version(self):
        import subprocess
        from unittest import mock

        done = subprocess.CompletedProcess(["x"], 0, stdout="2026.09.01\nmore\n", stderr="")
        with mock.patch.object(doctor.subprocess, "run", return_value=done):
            self.assertEqual(doctor._version(["x", "--version"]), "2026.09.01")

    def test_a_failing_tool_is_not_installed(self):
        import subprocess
        from unittest import mock

        done = subprocess.CompletedProcess(["x"], 1, stdout="", stderr="broken")
        with mock.patch.object(doctor.subprocess, "run", return_value=done):
            self.assertIsNone(doctor._version(["x", "--version"]))


class WhichPlayer(unittest.TestCase):
    """The report says which mpv a video is handed to, resolved rather than as
    configured. Started from the start menu, Weave used to fall back to plain
    mpv without a word, and a window per video was the only sign of it."""

    def setUp(self):
        self.cfg = Config(raw={})
        self._path = os.environ.get("PATH", "")
        self._bin = os.environ.get("XDG_BIN_HOME")
        self.addCleanup(self._restore)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["PATH"] = "/usr/bin:/bin"
        os.environ["XDG_BIN_HOME"] = self._tmp.name

    def _restore(self):
        os.environ["PATH"] = self._path
        if self._bin is None:
            os.environ.pop("XDG_BIN_HOME", None)
        else:
            os.environ["XDG_BIN_HOME"] = self._bin

    def line(self):
        report = doctor.Report()
        doctor._player(self.cfg, report)
        return [check for check in report.checks if check.name == "player"][0]

    def install_wrapper(self):
        from weave.player.mpv import WRAPPER_NAME

        wrapper = Path(self._tmp.name) / WRAPPER_NAME
        wrapper.write_text("#!/bin/sh\nexit 0\n")
        wrapper.chmod(0o755)
        return wrapper

    def test_the_wrapper_is_the_good_answer(self):
        wrapper = self.install_wrapper()
        found = self.line()
        self.assertEqual(found.state, doctor.OK)
        self.assertIn(str(wrapper), found.detail)

    def test_plain_mpv_is_worth_a_warning(self):
        found = self.line()
        self.assertEqual(found.state, doctor.WARN)
        self.assertIn("window per video", found.detail)


class Schedule(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_it_says_when_each_channel_is_next_due(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        rows = doctor.schedule(self.db, self.cfg)
        self.assertEqual(rows[0]["title"], "One")
        self.assertEqual(rows[0]["last_polled_at"], None)
        self.assertEqual(rows[0]["due_in_s"], 0)          # never asked, so now

    def test_a_channel_just_asked_is_not_due_yet(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.mark_polled("yt:UC1")
        self.assertGreater(doctor.schedule(self.db, self.cfg)[0]["due_in_s"], 0)

    def test_how_often_it_is_asked_is_named(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.assertEqual(doctor.schedule(self.db, self.cfg)[0]["tier"], "dormant")

    def test_an_error_is_carried_through(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.mark_polled("yt:UC1", "HTTPError: 404")
        self.assertEqual(doctor.schedule(self.db, self.cfg)[0]["error"], "HTTPError: 404")


if __name__ == "__main__":
    unittest.main()
