"""Background workers. No network, the sources are stubbed.

These exist because a missing attribute inside a worker is invisible until it
runs, and a worker only runs against the network. One such mistake stopped the
whole live check and took the results that had already been gathered with it.
"""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from weave import poller
from weave.budget import Budget
from weave.config import Config
from weave.db import Database, VideoRow
from weave.ids import ChannelRef
from weave.net import HttpError
from weave.sources import rss
from weave.sources.livecheck import LiveState
from weave.sources.sweep import SweptVideo

_app = QCoreApplication.instance() or QCoreApplication([])


class WorkerConstruction(unittest.TestCase):
    """Every worker has to survive being built and cancelled, which is what
    the shutdown path does to all of them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_each_worker_builds_and_cancels(self):
        workers = [
            poller.FeedPoller(self.db, self.cfg),
            poller.ChannelAdder(ChannelRef("youtube", "id", "UCabcdefghijklmnopqrstuv"), self.cfg),
            poller.SubsImporter(self.db, self.cfg),
            poller.ChannelDetailsFetcher(self.db, self.cfg, "yt:UC1", "UC1"),
            poller.LiveWatcher(self.db, self.cfg),
            poller.TwitchLogin(self.db, self.cfg),
            poller.DetailFetcher(self.db, self.cfg, "yt:aaaaaaaaaaa", "aaaaaaaaaaa",
                                 "https://www.youtube.com/watch?v=aaaaaaaaaaa"),
        ]
        for worker in workers:
            with self.subTest(worker=type(worker).__name__):
                worker.cancel()
                self.assertFalse(worker.isRunning())


class YoutubeLiveCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.upsert_videos([
            VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "Still going", live_status="is_live"),
            VideoRow("youtube", "bbbbbbbbbbb", "yt:UC1", "Finished", live_status="is_live"),
        ])
        self.watcher = poller.LiveWatcher(self.db, self.cfg)
        self._real = poller.livecheck.check
        answers = {
            "aaaaaaaaaaa": LiveState("aaaaaaaaaaa", 3707, True),
            "bbbbbbbbbbb": LiveState("bbbbbbbbbbb", None, False),
        }
        poller.livecheck.check = lambda cfg, ext_id, *a, **k: answers[ext_id]

    def tearDown(self):
        poller.livecheck.check = self._real
        self.db.close()
        self._tmp.cleanup()

    def test_a_running_stream_gets_its_viewer_count(self):
        self.watcher._check_youtube()
        row = self.db.video("yt:aaaaaaaaaaa")
        self.assertEqual((row["live_viewers"], row["live_status"]), (3707, "is_live"))

    def test_a_finished_stream_leaves_the_bar_but_stays_in_the_feed(self):
        self.watcher._check_youtube()
        row = self.db.video("yt:bbbbbbbbbbb")
        self.assertEqual((row["live_viewers"], row["live_status"]), (None, "was_live"))
        self.assertIn("bbbbbbbbbbb", [r["ext_id"] for r in self.db.feed(hide_watched=False)])

    def test_it_reports_how_many_are_still_live(self):
        self.assertEqual(self.watcher._check_youtube(), 1)

    def test_a_counted_stream_orders_against_twitch(self):
        self.db.add_channel("twitch:alpha", "twitch", "alpha", "Alpha")
        self.db.replace_live("twitch", [{"channel_key": "twitch:alpha", "login": "alpha",
                                         "display_name": "Alpha", "viewers": 100}])
        self.watcher._check_youtube()
        # The whole point. Before it had a count, the busy YouTube stream was
        # always sorted behind every Twitch one.
        self.assertEqual([r["platform"] for r in self.db.live_now()][0], "youtube")


class FeedJobs(unittest.TestCase):
    """Which feeds a round asks for."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.add_channel("yt:UC2", "youtube", "UC2", "Two")
        self.poller = poller.FeedPoller(self.db, self.cfg)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def rows(self):
        return self.db.channels_due(self.cfg.feed_tiers)

    def test_only_the_videos_feed_by_default(self):
        jobs = self.poller._feed_jobs(self.rows())
        self.assertEqual({kind for _, _, kind in jobs}, {rss.VIDEOS})
        self.assertEqual(len(jobs), 2)

    def test_a_channel_that_streams_also_gets_its_live_feed(self):
        # Streams live in their own tab, so without this a stream would only
        # appear once it had ended. Only channels seen streaming are asked,
        # because asking every channel would double the round for nothing.
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", "yt:UC2", "Stream",
                                        live_status="was_live")])
        jobs = self.poller._feed_jobs(self.rows())
        self.assertIn(("yt:UC2", "UC2", rss.LIVE), jobs)
        self.assertNotIn(("yt:UC1", "UC1", rss.LIVE), jobs)

    def test_a_remembered_variant_is_used(self):
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        jobs = dict(((key, kind) for key, _, kind in self.poller._feed_jobs(self.rows())))
        self.assertEqual(jobs["yt:UC1"], rss.CHANNEL)


class FeedFallback(unittest.TestCase):
    """A 404 on a tab feed is ambiguous, and getting that wrong would rewrite
    every channel to the mixed feed the first time the endpoint pushed back."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})
        self.poller = poller.FeedPoller(self.db, self.cfg)
        self._real = poller.rss.fetch

    def tearDown(self):
        poller.rss.fetch = self._real
        self.db.close()
        self._tmp.cleanup()

    def answer(self, mapping):
        def fake(fetcher, ext_id, kind=rss.VIDEOS):
            outcome = mapping[kind]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        poller.rss.fetch = fake

    def test_a_tab_that_answers_costs_one_request(self):
        self.answer({rss.VIDEOS: rss.FeedResult("UC1", "One", [], rss.VIDEOS)})
        result, cost, variant = self.poller._fetch_one(None, "UC1", rss.VIDEOS)
        self.assertEqual((cost, variant), (1, None))
        self.assertEqual(result.kind, rss.VIDEOS)

    def test_a_missing_tab_falls_back_and_is_remembered(self):
        self.answer({rss.VIDEOS: HttpError(404, "u"),
                     rss.CHANNEL: rss.FeedResult("UC1", "One", [], rss.CHANNEL)})
        _, cost, variant = self.poller._fetch_one(None, "UC1", rss.VIDEOS)
        self.assertEqual((cost, variant), (2, rss.CHANNEL))

    def test_a_refusal_is_not_mistaken_for_a_missing_tab(self):
        # The endpoint answers a burst with a 404 too. The mixed feed is the
        # discriminator: it answers when the tab is genuinely absent and
        # refuses when we are the problem, so the fallback only sticks when
        # that second call succeeds.
        self.answer({rss.VIDEOS: HttpError(404, "u"), rss.CHANNEL: HttpError(404, "u")})
        with self.assertRaises(HttpError):
            self.poller._fetch_one(None, "UC1", rss.VIDEOS)


class SweepDetector(unittest.TestCase):
    """One call over every subscription, turned into a list of the channels
    worth asking. This is what makes a new video arrive in one sweep interval
    instead of in a full lap of several hundred feeds."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UCabcdefghijklmnopqrstuv", "youtube",
                            "UCabcdefghijklmnopqrstuv", "One")
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa",
                                        "yt:UCabcdefghijklmnopqrstuv", "Known")])
        self.db.mark_polled("yt:UCabcdefghijklmnopqrstuv")
        self.poller = poller.FeedPoller(self.db, self.cfg)
        self._real = poller.sweep.fetch
        self.budget = Budget(self.db, self.cfg.budget_limits, self.cfg.budget_window_s)

    def tearDown(self):
        poller.sweep.fetch = self._real
        self.db.close()
        self._tmp.cleanup()

    def answer(self, videos):
        poller.sweep.fetch = lambda *a, **k: videos

    def test_a_new_video_promotes_its_channel(self):
        self.assertEqual(self.db.channels_due(self.cfg.feed_tiers), [])
        self.answer([SweptVideo("zzzzzzzzzzz", 300, None, "UCabcdefghijklmnopqrstuv")])
        self.poller._phase_sweep(self.budget)
        self.assertEqual([r["key"] for r in self.db.channels_due(self.cfg.feed_tiers)],
                         ["yt:UCabcdefghijklmnopqrstuv"])

    def test_nothing_new_promotes_nothing(self):
        self.answer([SweptVideo("aaaaaaaaaaa", 300, None, "UCabcdefghijklmnopqrstuv")])
        self.poller._phase_sweep(self.budget)
        self.assertEqual(self.db.channels_due(self.cfg.feed_tiers), [])

    def test_a_recent_sweep_is_not_repeated(self):
        calls = []
        poller.sweep.fetch = lambda *a, **k: calls.append(1) or []
        self.poller._phase_sweep(self.budget)
        self.poller._phase_sweep(self.budget)
        self.assertEqual(len(calls), 1)

    def test_a_failed_sweep_is_retried_rather_than_waiting_out_the_interval(self):
        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise poller.sweep.SweepError("nope")

        poller.sweep.fetch = boom
        self.poller._phase_sweep(self.budget)
        self.poller._phase_sweep(self.budget)
        self.assertEqual(len(calls), 2)


class BudgetedRound(unittest.TestCase):
    """A round is trimmed to what the endpoint budget allows, and says so
    rather than quietly doing nothing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={"budget": {"feeds": 2}})
        for n in range(5):
            self.db.add_channel(f"yt:UC{n}", "youtube", f"UC{n}", f"Channel {n}")
        self.poller = poller.FeedPoller(self.db, self.cfg)
        self._real = poller.rss.fetch
        self.asked = []

        def fake(fetcher, ext_id, kind=rss.VIDEOS):
            self.asked.append(ext_id)
            return rss.FeedResult(ext_id, None, [], kind)

        poller.rss.fetch = fake

    def tearDown(self):
        poller.rss.fetch = self._real
        self.db.close()
        self._tmp.cleanup()

    def budget(self):
        return Budget(self.db, self.cfg.budget_limits, self.cfg.budget_window_s)

    def test_the_round_shrinks_to_what_is_left(self):
        self.poller._phase_rss(None, self.budget())
        self.assertEqual(len(self.asked), 2)

    def test_a_spent_budget_stops_the_round_and_reports_it(self):
        said = []
        self.poller.failure.connect(lambda source, message: said.append(source))
        self.poller._phase_rss(None, self.budget())
        self.asked.clear()
        self.poller._phase_rss(None, self.budget())
        self.assertEqual(self.asked, [])
        self.assertIn("feeds", said)

    def test_what_was_left_out_is_still_due(self):
        self.poller._phase_rss(None, self.budget())
        self.assertEqual(len(self.db.channels_due(self.cfg.feed_tiers)), 3)


if __name__ == "__main__":
    unittest.main()
