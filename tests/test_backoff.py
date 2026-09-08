"""Easing off an endpoint that is refusing.

Measured on a real collection: four hours of two hundred feed requests a
quarter hour with not one refusal, then a quarter hour where seventy-nine of
two hundred and thirty-two were refused. Every one of those channels answered
fine an hour earlier and answered fine again ten minutes later, so it was the
endpoint pushing back rather than anything about the channels. Nothing in the
application changed when it happened: it went on asking fifteen a minute into
an endpoint refusing every third one.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from weave import backoff, poller
from weave.config import Config
from weave.db import Database
from weave.net import HttpError


class Deciding(unittest.TestCase):
    def test_a_clean_round_rests_nothing(self):
        self.assertFalse(backoff.next_rest(sent=200, refused=0).resting)

    def test_nor_does_one_bad_channel_in_a_quiet_minute(self):
        # A 404 also means a channel with no such feed, which is a real thing
        # and must not stop the feed for everybody.
        self.assertFalse(backoff.next_rest(sent=8, refused=2).resting)

    def test_a_third_of_a_round_refused_is_the_endpoint_saying_stop(self):
        rest = backoff.next_rest(sent=232, refused=79)
        self.assertTrue(rest.resting)
        self.assertEqual(rest.seconds, backoff.FIRST_S)

    def test_and_it_doubles_while_it_keeps_refusing(self):
        steps = []
        step = 0
        for _ in range(6):
            rest = backoff.next_rest(sent=100, refused=40, step=step)
            steps.append(rest.seconds)
            step = rest.step
        self.assertEqual(steps, [120, 240, 480, 960, 1800, 1800])

    def test_it_stops_at_half_an_hour(self):
        self.assertEqual(backoff.next_rest(sent=100, refused=40, step=20).seconds,
                         backoff.LONGEST_S)

    def test_a_clean_window_puts_it_back_to_nothing(self):
        # Rather than easing back down. An endpoint that answers is an
        # endpoint that answers, and a slow return would keep a recovered feed
        # quiet for another twenty minutes for no reason.
        rest = backoff.next_rest(sent=100, refused=0, step=4)
        self.assertFalse(rest.resting)
        self.assertEqual(rest.step, 0)

    def test_nothing_asked_is_not_pushback(self):
        self.assertFalse(backoff.pushing_back(sent=0, refused=0))

    def test_what_it_says_counts_in_whole_minutes(self):
        self.assertIn("2 min", backoff.said("feed", 61))
        self.assertIn("1 min", backoff.said("feed", 1))


class Resting(unittest.TestCase):
    """A rest lives in the database, and the poller reads it before asking."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "t.db"
        self.db = Database(self.path)
        self.cfg = Config(raw={})
        for number in range(6):
            key = f"yt:UC{number}"
            self.db.add_channel(key, "youtube", f"UC{number}", f"Channel {number}")
        self._patched = []

    def tearDown(self):
        for owner, name, original in reversed(self._patched):
            setattr(owner, name, original)
        self.db.close()
        self._tmp.cleanup()

    def patch(self, owner, name, value):
        self._patched.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def asked(self):
        """Every channel the feed endpoint is asked about in one round."""
        seen = []

        def fetch(fetcher, ext_id, kind=poller.rss.VIDEOS):
            seen.append(ext_id)
            raise HttpError(404, f"https://example.invalid/{ext_id}")

        self.patch(poller.rss, "fetch", fetch)
        self.patch(poller.sweep, "fetch", lambda *a, **k: [])
        worker = poller.FeedPoller(self.db, self.cfg)
        worker.run()
        return seen

    def test_a_round_that_is_mostly_refused_rests_the_endpoint(self):
        self.assertTrue(self.asked())
        self.assertGreater(self.db.resting_until("feeds"), int(time.time()))

    def test_and_the_next_round_asks_nothing(self):
        self.asked()
        self.assertEqual(self.asked(), [])

    def test_the_rest_survives_a_restart(self):
        # The reason it is in the database at all. Starting the application
        # begins a round at once, so a rest held in the poller would be walked
        # straight past by anybody restarting to test a build.
        self.asked()
        self.db.close()
        self.db = Database(self.path)
        self.assertGreater(self.db.resting_until("feeds"), int(time.time()))

    def test_a_forced_refresh_goes_anyway(self):
        # Somebody pressing refresh in front of the window is asking. An
        # application that ignores a button is worse than one that asks too
        # often.
        self.asked()
        self.patch(poller.sweep, "fetch", lambda *a, **k: [])
        seen = []

        def fetch(fetcher, ext_id, kind=poller.rss.VIDEOS):
            seen.append(ext_id)
            raise HttpError(404, "https://example.invalid/x")

        self.patch(poller.rss, "fetch", fetch)
        worker = poller.FeedPoller(self.db, self.cfg, force_all=True)
        worker.run()
        self.assertTrue(seen)

    def test_and_a_clean_round_clears_it(self):
        self.db.rest_endpoint("feeds", int(time.time()) + 600, 3)
        self.db.record_requests("feeds", count=100, refused=0)
        self.db.rest_endpoint("feeds", 0, 0)
        self.assertEqual(self.db.resting_until("feeds"), 0)
        self.assertEqual(self.db.rest_step("feeds"), 0)


class Saying(unittest.TestCase):
    """The page has to say a rest is on, or nothing arriving looks like a
    fault. What somebody needs is when it started, how long it has left, what
    the ceiling is and when the next round will really ask anything."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def lines(self) -> dict[str, str]:
        from weave import doctor
        return {check.name: check.detail
                for check in doctor.run(self.cfg, self.db, network=False).checks}

    def test_it_says_when_the_rest_ends_and_how_long_it_has_run(self):
        self.db.rest_endpoint("feeds", int(time.time()) + 470, 3)
        said = self.lines()["the feed rest"]
        self.assertIn("resting since", said)
        self.assertIn("8 min from now", said)
        self.assertIn("Rest 3 in a row", said)
        self.assertIn("16 min", said)          # what the next one would be

    def test_it_says_when_the_next_round_asks_anything(self):
        self.db.rest_endpoint("feeds", int(time.time()) + 120, 1)
        self.assertIn("when the rest ends", self.lines()["next refresh"])

    def test_and_says_the_ordinary_cadence_when_nothing_is_resting(self):
        said = self.lines()["next refresh"]
        self.assertIn("60 s", said)
        self.assertIn("15 channels a tick", said)

    def test_the_endpoint_is_probed_with_a_channel_that_is_followed(self):
        # The constant it used is YouTube's own channel, whose feed answers
        # 404 whatever the endpoint is doing, so the check cried wolf on every
        # visit to the page. A followed channel is the question the poller
        # asks all day, which is the one worth asking.
        from weave import doctor
        self.db.add_channel("yt:UCkkkkkkkkkkkkkkkkkkkkkk", "youtube",
                            "UCkkkkkkkkkkkkkkkkkkkkkk", "Followed")
        self.db.mark_polled("yt:UCkkkkkkkkkkkkkkkkkkkkkk", None)
        self.assertEqual(doctor.probe_channel(self.db), "UCkkkkkkkkkkkkkkkkkkkkkk")

    def test_and_by_the_constant_when_nothing_is_followed_yet(self):
        from weave import doctor
        self.assertEqual(doctor.probe_channel(self.db), doctor.PROBE_CHANNEL)

    def test_a_channel_already_failing_is_not_the_one_to_ask_about(self):
        from weave import doctor
        self.db.add_channel("yt:UCkkkkkkkkkkkkkkkkkkkkkk", "youtube",
                            "UCkkkkkkkkkkkkkkkkkkkkkk", "Failed")
        self.db.mark_polled("yt:UCkkkkkkkkkkkkkkkkkkkkkk", "HttpError: HTTP 404")
        self.assertEqual(doctor.probe_channel(self.db), doctor.PROBE_CHANNEL)

    def test_the_ceiling_is_on_the_requests_line(self):
        self.db.record_requests("feeds", count=232, refused=79)
        self.assertIn("feeds 232/300 (79 refused)", self.lines()["requests"])


if __name__ == "__main__":
    unittest.main()
