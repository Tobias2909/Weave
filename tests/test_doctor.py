"""The checkup.

What matters here is that it answers rather than raises, and that its verdict
is honest, since the whole reason it exists is that a scraper failing looks
exactly like a scraper with nothing to say.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

from weave import doctor
from weave.config import Config
from weave.db import Database, VideoRow

from . import support


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


class WhichMpv(unittest.TestCase):
    """The report says which mpv is in front of it, and which shape of command
    it is being asked in. The two behave differently on exactly one thing, and
    a report that does not say which is in front of it cannot explain a
    difference between two machines."""

    def line(self, said):
        report = doctor.Report()
        doctor._mpv_age(said, report)
        return [check for check in report.checks if check.name == "mpv"][0]

    def test_a_current_one_is_reported_as_it_says_itself(self):
        found = self.line("mpv v0.41.0 Copyright")
        self.assertEqual(found.state, doctor.OK)
        self.assertIn("0.41.0", found.detail)

    def test_an_older_one_says_which_shape_it_is_asked_in(self):
        found = self.line("mpv 0.37.0 Copyright")
        self.assertIn("older loadfile shape", found.detail)

    def test_and_is_not_a_warning_since_nothing_is_worse_off(self):
        # Weave asks each player the way it understands, so an older one
        # resumes a track exactly as well. Warning about it would be crying
        # wolf at somebody whose distribution chose the version for them.
        self.assertEqual(self.line("mpv 0.37.0 Copyright").state, doctor.OK)

    def test_one_that_will_not_say_is_taken_at_face_value(self):
        self.assertEqual(self.line("some other player").state, doctor.OK)

    def test_the_cut_is_the_one_the_engine_uses(self):
        # Read from the engine rather than written down twice, or this line
        # and the code that shapes the command could disagree about the same
        # player.
        from weave.engine import _INDEX_ARG_SINCE

        self.assertEqual(_INDEX_ARG_SINCE, (0, 38))
        self.assertIn("0.38", self.line("mpv 0.37.0 Copyright").detail)


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
        # A plain mpv of this test's own, rather than whatever the machine
        # happens to have on /usr/bin. The warning being tested is about the
        # wrapper being absent, not about mpv being installed, and reaching
        # for the real one meant the line read FAIL rather than WARN on a
        # machine without it.
        self._path_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._path_dir.cleanup)
        plain = Path(self._path_dir.name) / "mpv"
        plain.write_text("#!/bin/sh\nexit 0\n")
        plain.chmod(0o755)
        os.environ["PATH"] = self._path_dir.name
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


class WhatTheSweepHoldsBack(unittest.TestCase):
    """The schedule has to answer the way the poller does.

    It used to ask for the tiered intervals only, so a channel that posts often
    read as due every quarter of an hour while the poller was really leaving it
    six hours. On a real subscription list that was 146 of 466 channels.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        # Posted yesterday, so it is in the hottest tier on its own.
        self.db.upsert_videos([VideoRow(platform="youtube", ext_id="aaaaaaaaaaa",
                                        channel_key="yt:UC1", title="A video",
                                        published_at=int(time.time()) - 86400)])
        self.db.mark_polled("yt:UC1")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def cover(self):
        """Name the channel in the sweep, and say the sweep answered now."""
        self.db.mark_sweep_seen(["yt:UC1"])
        self.db.set_state("sweep_at", str(int(time.time())))

    def only(self):
        return doctor.schedule(self.db, self.cfg)[0]

    def test_uncovered_it_is_on_its_own_tier(self):
        row = self.only()
        self.assertEqual(row["tier"], "posts often")
        self.assertEqual(row["interval_s"], self.cfg.feed_tiers.hot_s)
        self.assertFalse(row["covered"])

    def test_covered_it_is_asked_every_few_hours_instead(self):
        self.cover()
        row = self.only()
        self.assertEqual(row["interval_s"], self.cfg.feed_tiers.covered_s)
        self.assertTrue(row["covered"])

    def test_and_it_is_still_called_a_channel_that_posts_often(self):
        # THE TRAP. covered_s and cold_s are both 21600, so reading the name
        # off the interval would call every busy channel the sweep covers
        # quiet. The name comes from the tier, the waiting from the interval.
        self.cover()
        row = self.only()
        self.assertEqual(row["tier"], "posts often")
        self.assertEqual(row["tier_s"], self.cfg.feed_tiers.hot_s)

    def test_the_wait_is_measured_against_the_interval_it_is_really_on(self):
        self.cover()
        row = self.only()
        self.assertGreater(row["due_in_s"], self.cfg.feed_tiers.hot_s)

    def test_a_stale_sweep_puts_it_back_on_its_tier(self):
        # What happens when yt-dlp breaks or the cookies die. The feed keeps
        # moving and the schedule says so rather than describing the old plan.
        self.cover()
        self.db.set_state("sweep_at",
                          str(int(time.time()) - self.cfg.sweep_stale_s - 60))
        row = self.only()
        self.assertEqual(row["interval_s"], self.cfg.feed_tiers.hot_s)
        self.assertFalse(row["covered"])


class IsTheSweepFresh(unittest.TestCase):
    """One rule, because the poller and the schedule both act on it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_never_swept_is_not_fresh(self):
        self.assertFalse(doctor.sweep_fresh(self.db, self.cfg))

    def test_just_swept_is_fresh(self):
        self.db.set_state("sweep_at", str(int(time.time())))
        self.assertTrue(doctor.sweep_fresh(self.db, self.cfg))

    def test_swept_too_long_ago_is_not(self):
        self.db.set_state("sweep_at", str(int(time.time()) - self.cfg.sweep_stale_s - 1))
        self.assertFalse(doctor.sweep_fresh(self.db, self.cfg))

    def test_the_sweep_turned_off_is_not(self):
        self.db.set_state("sweep_at", str(int(time.time())))
        off = Config(raw={"poll": {"sweep_limit": 0}})
        self.assertFalse(doctor.sweep_fresh(self.db, off))

    def test_the_poller_asks_the_same_question(self):
        # Two copies of this rule had already grown. A third would have been
        # the one that drifted.
        from weave.poller import FeedPoller
        self.db.set_state("sweep_at", str(int(time.time())))
        worker = FeedPoller.__new__(FeedPoller)
        worker._db = self.db
        worker._cfg = self.cfg
        self.assertEqual(worker._sweep_fresh(), doctor.sweep_fresh(self.db, self.cfg))


if __name__ == "__main__":
    unittest.main()


class WhereTheRequestsGo(unittest.TestCase):
    """The small table on How things are. A ceiling on its own does not say
    whether a number is alarming, so the usual figure is beside it.

    MEASURED on a real library: the feeds endpoint read a median of 164 per
    quarter hour on one day, peaking at 284 of a 300 ceiling, and 28 two days
    later. The page showed nothing but the live figure against the ceiling, so
    neither day looked any different from the other."""

    def setUp(self):
        self.db = support.scratch_db(self)
        self.cfg = Config(raw={})

    def spend(self, endpoint, minutes_ago, count, refused=0):
        minute = int(time.time()) // 60 - minutes_ago
        with self.db.conn as conn:
            conn.execute(
                "INSERT INTO request_budget(endpoint, minute, count, refused) VALUES(?,?,?,?) "
                "ON CONFLICT(endpoint, minute) DO UPDATE SET count=count+excluded.count, "
                "refused=refused+excluded.refused", (endpoint, minute, count, refused))

    def spell(self, endpoint, from_minutes_ago, minutes, count):
        """An unbroken spell of asking, which is what a window is measured
        over. Anything shorter than a window is not one at all."""
        for back in range(from_minutes_ago, from_minutes_ago - minutes, -1):
            self.spend(endpoint, back, count)

    def row(self, endpoint, days=1):
        found = [row for row in doctor.traffic(self.db, self.cfg, days=days)
                 if row["endpoint"] == endpoint]
        return found[0]

    def test_every_endpoint_with_a_ceiling_is_listed_even_when_idle(self):
        listed = {row["endpoint"] for row in doctor.traffic(self.db, self.cfg)}
        self.assertEqual(listed, set(self.cfg.budget_limits))

    def test_it_says_what_this_window_has_cost(self):
        self.spend("feeds", 2, 20)
        self.spend("feeds", 40, 500)          # outside the window
        self.assertEqual(self.row("feeds")["sent"], 20)

    def test_a_window_is_a_spell_of_asking_and_not_a_slice_of_the_clock(self):
        # The bug this replaced. Slicing the clock counted the stubs that every
        # start and stop leaves as if they were whole windows: measured on a
        # real log, 12 of 49 slices in a day were covered end to end and the
        # median slice held 8 of its 15 minutes, so the figure read about a
        # third low and the page said he was over it everywhere.
        self.spell("feeds", 300, 40, 10)
        row = self.row("feeds")
        self.assertEqual(row["usual"], 160)          # 16 minutes at 10 each
        self.assertEqual(row["most"], 160)

    def test_a_spell_too_short_to_fill_a_window_says_nothing(self):
        # Reporting it would be the old bug again, in miniature.
        self.spell("feeds", 300, 8, 10)
        row = self.row("feeds")
        self.assertEqual(row["usual"], 0)
        self.assertEqual(row["windows"], 0)

    def test_knowing_it_is_nothing_is_not_the_same_as_not_knowing(self):
        # An endpoint that fires once an hour honestly usually costs zero in a
        # quarter of an hour, and the page must not call that missing history.
        self.spell("browse", 300, 60, 0)
        self.spend("browse", 299, 3)
        row = self.row("browse")
        self.assertEqual(row["usual"], 0)
        self.assertGreater(row["windows"], 0)

    def test_the_usual_figure_is_the_median_of_those_windows(self):
        self.spell("feeds", 500, 40, 10)             # windows of 160
        self.spell("feeds", 300, 40, 40)             # windows of 640
        self.spell("feeds", 100, 40, 20)             # windows of 320
        self.assertEqual(self.row("feeds")["usual"], 320)
        self.assertEqual(self.row("feeds")["most"], 640)

    def test_a_window_never_straddles_a_pause(self):
        # Two busy spells with a gap between them must not be joined into one
        # window that never happened. Letting them stitch put the feeds peak
        # at 315 against a ceiling of 300 on a real log.
        self.spell("feeds", 300, 10, 100)
        self.spell("feeds", 200, 10, 100)
        self.assertEqual(self.row("feeds")["usual"], 0)
        self.assertEqual(self.row("feeds")["most"], 0)

    def test_idle_time_cannot_drag_the_figure_down(self):
        # A minute the app was not running writes no row, so it is not a zero.
        self.spell("feeds", 1000, 40, 10)
        self.assertEqual(self.row("feeds")["usual"], 160)

    def test_at_the_ceiling_is_a_failure(self):
        self.spend("browse", 1, self.cfg.budget_limits["browse"])
        self.assertEqual(self.row("browse")["state"], doctor.FAIL)

    def test_well_past_the_usual_figure_is_worth_a_look(self):
        self.spell("feeds", 300, 40, 1)              # usually 16 a window
        self.spend("feeds", 1, 100)
        row = self.row("feeds")
        self.assertEqual(row["state"], doctor.WARN)
        self.assertLess(row["sent"], row["limit"])

    def test_a_quiet_endpoint_doubling_says_nothing(self):
        # Two to four is not a story, and warning about it would teach anybody
        # reading this page to ignore it.
        self.spell("dislikes", 300, 40, 1)
        self.spend("dislikes", 1, 4)
        self.assertEqual(self.row("dislikes")["state"], doctor.OK)

    def test_refusals_are_worth_a_look(self):
        self.spend("feeds", 1, 10, refused=5)
        self.assertEqual(self.row("feeds")["state"], doctor.WARN)

    def test_the_busiest_endpoint_is_first(self):
        self.spend("player", 1, 5)
        self.spend("feeds", 1, 50)
        listed = [row["endpoint"] for row in doctor.traffic(self.db, self.cfg)]
        self.assertEqual(listed[:2], ["feeds", "player"])
