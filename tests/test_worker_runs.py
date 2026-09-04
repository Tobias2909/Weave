"""Every worker, actually run.

Building a worker and cancelling it proves almost nothing, which is the lesson
this module exists to hold on to. A worker that reads an attribute its
constructor never set raises nothing until the moment it runs, and it only runs
against the network, so the mistake reaches the person using the app rather
than the test suite. It has happened twice now, once with a throttle and once
with the configuration, and the second one silently stopped every channel page
from ever fetching its banner.

So each worker here is run for real with its source stubbed. What is asserted
is not the result, which belongs to the other modules, but that the run reached
its work and reported nothing that names a programming mistake.
"""

import tempfile
import threading
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from weave import poller
from weave.config import Config
from weave.db import Database, VideoRow
from weave.ids import ChannelRef
from weave.sources import resolve as resolve_source
from weave.sources.channel import ChannelDetails
from weave.sources.resolve import ResolvedChannel
from weave.sources.livecheck import LiveState

_app = QCoreApplication.instance() or QCoreApplication([])

# Words that only appear when the code itself is wrong, as opposed to the
# network being unhappy, which is an ordinary thing for these to report.
MISTAKES = ("AttributeError", "NameError", "TypeError", "KeyError", "ImportError")


class _Stream:
    key = "twitch:alpha"
    login = "alpha"
    display_name = "Alpha"
    title = "Live"
    game = "Chess"
    viewers = 10
    started_at = None
    thumbnail_url = None


class _TwitchClient:
    def __init__(self, *args, **kwargs):
        pass

    def account_id(self):
        return "1"

    def followed_streams(self, _account):
        return [_Stream()]

    def streams_for(self, _logins):
        return []

    def users(self, _logins):
        return []


class WorkerRuns(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.cfg = Config(raw={"twitch": {"client_id": "cid"}})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.add_channel("twitch:alpha", "twitch", "alpha", "Alpha")
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "A stream",
                                        live_status="is_live")])
        self._patched = []

    def tearDown(self):
        for owner, name, original in reversed(self._patched):
            setattr(owner, name, original)
        self.db.close()
        self._tmp.cleanup()

    def patch(self, owner, name, value):
        self._patched.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def run_worker(self, worker):
        """Run one worker in this thread and collect what it complained about.

        Not start(), because a run in another thread would let an exception
        escape into Qt rather than into the test.
        """
        said = []
        for signal in ("failed", "failure"):
            if hasattr(worker, signal):
                getattr(worker, signal).connect(
                    lambda *args: said.append(" ".join(str(a) for a in args)))
        worker.run()
        for line in said:
            for mistake in MISTAKES:
                self.assertNotIn(mistake, line, f"{type(worker).__name__} reported {line}")
        return said

    def test_feed_poller(self):
        self.patch(poller.rss, "fetch",
                   lambda fetcher, ext_id, kind=poller.rss.VIDEOS:
                   poller.rss.FeedResult(ext_id, "One", [], kind))
        self.patch(poller.sweep, "fetch", lambda *a, **k: [])
        self.run_worker(poller.FeedPoller(self.db, self.cfg))

    def test_channel_adder(self):
        self.patch(resolve_source, "resolve",
                   lambda *a, **k: ResolvedChannel("youtube", "UC1", "One"))
        self.run_worker(poller.ChannelAdder(ChannelRef("youtube", "UC1", "UC1"), self.cfg))

    def test_subs_importer(self):
        self.patch(poller.subs, "fetch", lambda *a, **k: [])
        self.run_worker(poller.SubsImporter(self.db, self.cfg))

    def test_channel_details_fetcher(self):
        # The one that broke. Its constructor took the configuration and threw
        # it away, so opening a channel page raised instead of fetching, and
        # the banner never arrived.
        self.patch(poller.channel_source, "fetch",
                   lambda *a, **k: ChannelDetails("One", "a.jpg", "b.jpg", 10))
        self.run_worker(poller.ChannelDetailsFetcher(self.db, self.cfg, "yt:UC1", "UC1"))
        self.assertEqual(self.db.channel("yt:UC1")["banner_url"], "b.jpg")

    def test_history_importer(self):
        self.patch(poller.history_source, "fetch",
                   lambda *a, **k: ["yt:aaaaaaaaaaa", "yt:zzzzzzzzzzz"])
        self.run_worker(poller.HistoryImporter(self.db, self.cfg))
        self.assertTrue(self.db.is_watched("yt:aaaaaaaaaaa"))

    def test_recommendations_fetcher(self):
        self.patch(poller.recommended_source, "fetch",
                   lambda *a, **k: [poller.recommended_source.Recommendation(
                       "aaaaaaaaaaa", "A suggestion", "Someone", "UC9", 100, "t")])
        self.run_worker(poller.RecommendationsFetcher(self.db, self.cfg))
        self.assertEqual([r["title"] for r in self.db.recommended()], ["A suggestion"])

    def test_live_watcher(self):
        self.patch(poller.tokens, "load", lambda: object())
        self.patch(poller.twitch, "Client", _TwitchClient)
        self.patch(poller.livecheck, "check",
                   lambda cfg, ext_id, *a, **k: LiveState(ext_id, 5, True))
        self.run_worker(poller.LiveWatcher(self.db, self.cfg))

    def test_detail_fetcher(self):
        self.patch(poller.dislike_source, "fetch",
                   lambda *a, **k: type("V", (), {"dislikes": 3})())
        self.patch(poller.comment_source, "fetch", lambda *a, **k: [])
        self.run_worker(poller.DetailFetcher(
            self.db, self.cfg, "yt:aaaaaaaaaaa", "aaaaaaaaaaa",
            "https://www.youtube.com/watch?v=aaaaaaaaaaa"))

    def test_source_details(self):
        self.patch(poller, "run_process",
                   lambda *a, **k: type("R", (), {"stdout": "Title\thttps://a/b.jpg"})())
        self.run_worker(poller.SourceDetails(self.db, self.cfg, "https://a/stream"))

    def test_twitch_login_without_a_client_id_is_a_message_not_a_crash(self):
        worker = poller.TwitchLogin(self.db, Config(raw={}))
        said = self.run_worker(worker)
        self.assertTrue(any("client id" in line for line in said))

    def test_every_worker_that_counts_requests_is_run_here(self):
        """A worker that counts requests has to be run by a test, or the next
        missing attribute reaches the app the way the last one did."""
        import re

        run_here = {"FeedPoller", "SubsImporter", "ChannelDetailsFetcher",
                    "HistoryImporter", "RecommendationsFetcher", "LiveWatcher",
                    "DetailFetcher"}
        source = Path("weave/poller.py").read_text()
        spenders = {match.group(1)
                    for match in re.finditer(r"class (\w+)\(QThread\):(.*?)(?=\nclass |\Z)",
                                             source, re.S)
                    if "_spend(" in match.group(2) or "budget.spend(" in match.group(2)}
        self.assertEqual(spenders - run_here, set())


if __name__ == "__main__":
    unittest.main()
