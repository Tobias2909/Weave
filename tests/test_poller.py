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
from weave.config import Config
from weave.db import Database, VideoRow
from weave.ids import ChannelRef
from weave.sources.livecheck import LiveState

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


if __name__ == "__main__":
    unittest.main()
