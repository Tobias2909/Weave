"""Background workers. No network, the sources are stubbed.

These exist because a missing attribute inside a worker is invisible until it
runs, and a worker only runs against the network. One such mistake stopped the
whole live check and took the results that had already been gathered with it.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from weave import poller
from weave.budget import Budget
from weave.config import Config
from weave.db import Database, FeedTiers, VideoRow
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

    def test_a_channel_nobody_has_looked_at_gets_both_feeds(self):
        # Streams live in their own tab, so a channel not asked for it shows a
        # stream only once it has ended. Nothing else reveals that a channel
        # streams unless it is subscribed, so the first round asks and the
        # answer is remembered.
        jobs = self.poller._feed_jobs(self.rows())
        self.assertEqual({kind for _, _, kind in jobs}, {rss.VIDEOS, rss.LIVE})
        self.assertIn(("yt:UC1", "UC1", rss.LIVE), jobs)

    def test_one_without_a_streams_tab_gets_only_its_videos(self):
        self.db.set_channel_streams("yt:UC1", False)
        self.db.set_channel_streams("yt:UC2", True)
        jobs = self.poller._feed_jobs(self.rows())
        self.assertIn(("yt:UC2", "UC2", rss.LIVE), jobs)
        self.assertNotIn(("yt:UC1", "UC1", rss.LIVE), jobs)
        self.assertEqual(len(jobs), 3)

    def test_the_ones_nobody_has_looked_at_are_asked_a_few_at_a_time(self):
        # Asking all of them at once would double a round and press against
        # the request ceiling, and the answer is kept for good, so there is no
        # hurry. Known streamers are not part of that limit.
        for index in range(3, 9):
            self.db.add_channel(f"yt:UC{index}", "youtube", f"UC{index}", f"C{index}")
        self.db.set_channel_streams("yt:UC1", True)
        jobs = self.poller._feed_jobs(self.rows())
        live = [key for key, _, kind in jobs if kind == rss.LIVE]
        self.assertIn("yt:UC1", live)
        self.assertEqual(len(live), 1 + poller.LIVE_PROBES_PER_TICK)

    def test_a_channel_seen_streaming_keeps_its_live_feed(self):
        self.db.set_channel_streams("yt:UC2", False)
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", "yt:UC2", "Stream",
                                        live_status="was_live")])
        jobs = self.poller._feed_jobs(self.rows())
        self.assertIn(("yt:UC2", "UC2", rss.LIVE), jobs)

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

    def test_a_missing_streams_tab_answers_with_nothing_rather_than_raising(self):
        # There is nothing to fall back to for this one. A channel that has
        # never streamed genuinely has no streams tab, so the caller is handed
        # no result and decides what it meant by whether the videos feed of
        # the same channel answered in the same round.
        self.answer({rss.LIVE: HttpError(404, "u")})
        result, cost, variant = self.poller._fetch_one(None, "UC1", rss.LIVE)
        self.assertIsNone(result)
        self.assertEqual((cost, variant), (1, None))

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


class LearningWhenAnAnnouncedStreamIsDue(unittest.TestCase):
    """The sweep reports the time as NA for every one of them, so the card
    could say a stream was announced and never when."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.upsert_videos([
            VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "Announced",
                     live_status="is_upcoming"),
        ])
        self.watcher = poller.LiveWatcher(self.db, self.cfg)
        self._real = poller.livecheck.check
        self.addCleanup(setattr, poller.livecheck, "check", self._real)
        self.asked = []

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def answer(self, state):
        def fake(cfg, ext_id, *a, **k):
            self.asked.append(ext_id)
            return state
        poller.livecheck.check = fake
        budget = Budget(self.db, self.cfg.budget_limits, self.cfg.budget_window_s)
        self.watcher._check_upcoming(budget)

    def row(self):
        return self.db.conn.execute(
            "SELECT live_status, scheduled_at FROM videos WHERE key='yt:aaaaaaaaaaa'").fetchone()

    def test_the_time_is_stored(self):
        self.answer(LiveState("aaaaaaaaaaa", None, False, 1788825600, True))
        self.assertEqual(self.row()["scheduled_at"], 1788825600)

    def test_and_it_is_not_asked_about_again(self):
        self.answer(LiveState("aaaaaaaaaaa", None, False, 1788825600, True))
        self.assertEqual(self.db.upcoming_without_start(), [])

    def test_one_that_has_begun_stops_being_an_announcement(self):
        # Otherwise it would be asked about on every check for ever, since it
        # never gains a start time.
        self.answer(LiveState("aaaaaaaaaaa", 12, True, None, False))
        self.assertEqual(self.row()["live_status"], "is_live")

    def test_one_that_was_called_off_becomes_an_ordinary_video(self):
        self.answer(LiveState("aaaaaaaaaaa", None, False, None, False))
        self.assertEqual(self.row()["live_status"], "was_live")

    def test_an_announcement_with_no_time_yet_is_left_alone(self):
        self.answer(LiveState("aaaaaaaaaaa", None, False, None, True))
        self.assertEqual(self.row()["live_status"], "is_upcoming")
        self.assertIsNone(self.row()["scheduled_at"])

    def test_only_a_few_are_asked_in_one_round(self):
        self.db.upsert_videos([
            VideoRow("youtube", f"bbbbbbbbb{n:02d}", "yt:UC1", f"Also {n}",
                     live_status="is_upcoming")
            for n in range(6)
        ])
        self.answer(LiveState("x", None, False, None, True))
        self.assertEqual(len(self.asked), poller.UPCOMING_PER_CHECK)


class AFeedThatNamesAStranger(unittest.TestCase):
    """A feed entry can belong to a channel Weave has never heard of.

    An artist channel's own live streams playlist carries the linked label
    channel's streams, and a video cannot be stored without its channel, so
    the write was refused by the foreign key. That exception escaped the
    thread, which left the interface waiting for a poll that was already dead
    and stopped every later refresh for the rest of the session.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.poller = poller.FeedPoller(self.db, self.cfg)
        self._real = poller.rss.fetch
        self.addCleanup(setattr, poller.rss, "fetch", self._real)
        borrowed = VideoRow("youtube", "eeeeeeeeeee", "yt:UCstranger", "A label stream",
                            channel_title="OneVEVO")
        mine = VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "My own video")
        poller.rss.fetch = lambda fetcher, ext_id, kind=rss.VIDEOS: (
            rss.FeedResult("UC1", "One", [mine], rss.VIDEOS) if kind != rss.LIVE
            else rss.FeedResult("UC1", "One", [borrowed], rss.LIVE))
        budget = Budget(self.db, self.cfg.budget_limits, self.cfg.budget_window_s)
        self.polled, self.touched, self.failures = self.poller._phase_rss(None, budget)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_the_round_finishes(self):
        self.assertEqual(self.failures, 0)
        self.assertEqual(self.polled, 1)

    def test_both_videos_are_stored(self):
        keys = {row["key"] for row in self.db.feed(limit=50)}
        self.assertIn("yt:aaaaaaaaaaa", keys)
        stored = self.db.conn.execute(
            "SELECT channel_key FROM videos WHERE key='yt:eeeeeeeeeee'").fetchone()
        self.assertEqual(stored["channel_key"], "yt:UCstranger")

    def test_the_stranger_is_kept_but_not_followed(self):
        row = self.db.channel("yt:UCstranger")
        self.assertEqual(row["title"], "OneVEVO")
        self.assertEqual((row["tracked"], row["in_all"]), (0, 0))
        self.assertNotIn("yt:UCstranger", {c["key"] for c in self.db.channels()})

    def test_the_stranger_is_never_polled(self):
        due = {row["key"] for row in self.db.channels_due(FeedTiers(), force=True)}
        self.assertNotIn("yt:UCstranger", due)


class APollThatDiesStillReportsItself(unittest.TestCase):
    """finished_poll has to be emitted whatever happens.

    The interface raises a flag while a poll is in flight and lowers it there.
    An exception that escapes run leaves that flag raised, and then nothing
    refreshes again until the app is restarted, which is far worse than the
    fault that caused it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "t.db"
        self.db = Database(self.path)
        self.cfg = Config(raw={})
        self.worker = poller.FeedPoller(self.db, self.cfg)
        self.worker._phase_sweep = lambda budget: 0
        def boom(fetcher, budget):
            raise RuntimeError("FOREIGN KEY constraint failed")
        self.worker._phase_rss = boom
        self.finished = []
        self.failures = []
        self.worker.finished_poll.connect(lambda *a: self.finished.append(a))
        self.worker.failure.connect(lambda *a: self.failures.append(a))
        # The traceback is printed on purpose, so a real fault is still
        # readable in the terminal. Swallowed here to keep the run tidy.
        with contextlib.redirect_stderr(io.StringIO()):
            self.worker.run()

    def tearDown(self):
        self._tmp.cleanup()

    def test_it_finishes(self):
        self.assertEqual(len(self.finished), 1)

    def test_it_says_what_went_wrong(self):
        self.assertEqual(len(self.failures), 1)
        self.assertIn("RuntimeError", self.failures[0][1])
        self.assertIn("FOREIGN KEY", self.failures[0][1])

    def test_the_failure_is_counted(self):
        self.assertEqual(self.finished[0][2], 1)


class TheSweepsFlagReachesAVideoStoredAfterIt(unittest.TestCase):
    """A stream that starts between two sweeps.

    The sweep runs before the feeds and is the only thing that knows a video
    is live, but it can only update rows that already exist. A stream the
    feeds store in the same round was not there when the sweep spoke, so
    without a second pass its live flag waited for the next sweep a quarter of
    an hour later, and the badge and the live bar waited with it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "t.db"
        self.db = Database(self.path)
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.worker = poller.FeedPoller(self.db, self.cfg)
        self._real_sweep, self._real_rss = poller.sweep.fetch, poller.rss.fetch
        self.addCleanup(setattr, poller.sweep, "fetch", self._real_sweep)
        self.addCleanup(setattr, poller.rss, "fetch", self._real_rss)
        poller.sweep.fetch = lambda *a, **k: [
            SweptVideo("aaaaaaaaaaa", None, "is_live", "UC1")]
        fresh = VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "Starting now")
        poller.rss.fetch = lambda fetcher, ext_id, kind=rss.VIDEOS: rss.FeedResult(
            "UC1", "One", [fresh], kind)
        self.worker.run()
        self.after = Database(self.path)
        self.addCleanup(self.after.close)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_video_is_live(self):
        row = self.after.conn.execute(
            "SELECT live_status FROM videos WHERE key='yt:aaaaaaaaaaa'").fetchone()
        self.assertEqual(row["live_status"], "is_live")

    def test_it_reaches_the_live_bar(self):
        self.assertEqual([row["ext_id"] for row in self.after.live_youtube()],
                         ["aaaaaaaaaaa"])


class DecidingWhetherAChannelStreams(unittest.TestCase):
    """What a 404 on the streams tab is taken to mean.

    The endpoint answers a burst of requests with a 404 as well, so a round in
    which a channel answered nothing at all is not allowed to decide that the
    channel has no streams tab. Getting that wrong would quietly stop asking
    for the streams of every channel the first time the endpoint pushed back.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.poller = poller.FeedPoller(self.db, self.cfg)
        self._real = poller.rss.fetch
        self.addCleanup(setattr, poller.rss, "fetch", self._real)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def answer(self, table):
        def fake(fetcher, ext_id, kind=rss.VIDEOS):
            found = table[kind]
            if isinstance(found, Exception):
                raise found
            return found
        poller.rss.fetch = fake

    def run_round(self):
        budget = Budget(self.db, self.cfg.budget_limits, self.cfg.budget_window_s)
        return self.poller._phase_rss(None, budget)

    def streams_column(self):
        return self.db.channels()[0]["streams"]

    def test_a_missing_streams_tab_is_remembered_and_not_asked_again(self):
        self.answer({rss.VIDEOS: rss.FeedResult("UC1", "One", [], rss.VIDEOS),
                     rss.LIVE: HttpError(404, "u")})
        _, _, failures = self.run_round()
        # Not an error either. A channel that has never streamed answering
        # that way is the ordinary case, not a fault to report.
        self.assertEqual(failures, 0)
        self.assertEqual(self.streams_column(), 0)
        self.assertNotIn("yt:UC1", self.db.channels_that_stream())

    def test_a_refusal_leaves_the_question_open(self):
        self.answer({rss.VIDEOS: HttpError(404, "u"), rss.CHANNEL: HttpError(404, "u"),
                     rss.LIVE: HttpError(404, "u")})
        self.run_round()
        self.assertIsNone(self.streams_column())
        self.assertIn("yt:UC1", self.db.channels_not_asked_for_streams())

    def test_a_streams_tab_that_answers_is_remembered_too(self):
        self.answer({rss.VIDEOS: rss.FeedResult("UC1", "One", [], rss.VIDEOS),
                     rss.LIVE: rss.FeedResult("UC1", "One", [], rss.LIVE)})
        self.run_round()
        self.assertEqual(self.streams_column(), 1)
        self.assertIn("yt:UC1", self.db.channels_that_stream())
