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
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from weave import poller
from weave.config import Config
from weave.db import Database, VideoRow
from weave.ids import ChannelRef
from weave.sources import resolve as resolve_source
from weave.sources.channel import ChannelDetails
from weave.sources.livecheck import LiveState
from weave.sources.resolve import ResolvedChannel

_app = QCoreApplication.instance() or QCoreApplication([])

# Words that only appear when the code itself is wrong, as opposed to the
# network being unhappy, which is an ordinary thing for these to report.
MISTAKES = ("AttributeError", "NameError", "TypeError", "KeyError", "ImportError")


def live_checking(bridge) -> bool:
    """What the live bar reads, through the getter the property is built on.

    Not the property itself. On a bridge built with __new__ an unbound
    Property reads back as the Property object rather than the value, and that
    object is always truthy, so asserting on it would pass either way.
    """
    from weave.ui.bridge import Bridge

    return Bridge._get_live_checking(bridge)


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
        # crashed is the base's own report of an exception nobody expected,
        # which is exactly the kind of mistake this file exists to catch.
        for signal in ("failed", "failure", "crashed"):
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

    def test_channel_feed_fetcher(self):
        # Opening a channel's page asks that one channel for its videos, since
        # the poller asks after the channels somebody follows in an order of
        # its own and a stranger is in no such order at all.
        self.db.remember_channel("yt:UC3", "youtube", "UC3", "A stranger")
        self.patch(poller.rss, "fetch", lambda fetcher, ext_id, kind=poller.rss.VIDEOS:
                   poller.rss.FeedResult(ext_id, "A stranger", [
                       VideoRow("youtube", "ccccccccccc", "yt:UC3", "Theirs")], kind))
        said = self.run_worker(poller.ChannelFeedFetcher(self.db, self.cfg, "yt:UC3", "UC3"))
        self.assertFalse([word for word in MISTAKES if word in said])
        self.assertTrue(self.db.channel_has_videos("yt:UC3"))
        # And it does not start following them. Opening a stranger's page is
        # not the same as asking for their videos in the feed.
        self.assertNotIn("yt:UC3", [row["key"] for row in self.db.channels()])

    def test_channel_playlists_fetcher(self):
        from weave.sources.playlists import Playlist

        self.db.add_channel("yt:UC4", "youtube", "UC4", "One")
        self.patch(poller.playlist_source, "fetch_channel_lists",
                   lambda *a, **k: [Playlist("PL" + "a" * 22, "Theirs")])
        said = self.run_worker(poller.ChannelPlaylistsFetcher(self.db, self.cfg, "yt:UC4", "UC4"))
        self.assertFalse([word for word in MISTAKES if word in said])
        self.assertEqual([row["title"] for row in self.db.channel_playlists("yt:UC4")], ["Theirs"])

    def test_channel_avatars_fetcher(self):
        self.db.remember_channel("yt:UC2", "youtube", "UC2", "A stranger")
        self.patch(poller.channel_source, "fetch",
                   lambda ext_id, *a, **k: ChannelDetails(None, f"{ext_id}.jpg", None, None))
        said = self.run_worker(
            poller.ChannelAvatarsFetcher(self.db, self.cfg, ["yt:UC2"]))
        self.assertEqual(self.db.channel("yt:UC2")["avatar_url"], "UC2.jpg")
        self.assertFalse(said)

    def test_history_importer(self):
        self.patch(poller.history_source, "fetch",
                   lambda *a, **k: [poller.flatlist.FlatVideo("aaaaaaaaaaa", "Watched"),
                                    poller.flatlist.FlatVideo("zzzzzzzzzzz", "Also watched")])
        self.run_worker(poller.HistoryImporter(self.db, self.cfg))
        # The whole history is kept, and the ones that are stored here are
        # marked watched as well, since that is what hide watched reads.
        self.assertEqual([r["title"] for r in self.db.cached(self.db.HISTORY)],
                         ["Watched", "Also watched"])
        self.assertTrue(self.db.is_watched("yt:aaaaaaaaaaa"))

    def test_recommendations_fetcher(self):
        self.patch(poller.recommended_source, "fetch",
                   lambda *a, **k: [poller.recommended_source.Recommendation(
                       "aaaaaaaaaaa", "A suggestion", "Someone", "UC9", 100, "t")])
        self.run_worker(poller.RecommendationsFetcher(self.db, self.cfg))
        self.assertEqual([r["title"] for r in self.db.recommended()], ["A suggestion"])

    def test_playlists_fetcher(self):
        self.patch(poller.playlist_source, "fetch_list",
                   lambda *a, **k: [poller.playlist_source.Playlist("PL1", "One")])
        self.run_worker(poller.PlaylistsFetcher(self.db, self.cfg))
        self.assertEqual([p["title"] for p in self.db.playlists()], ["One"])

    def test_playlist_items_fetcher(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.patch(poller.playlist_source, "fetch_items",
                   lambda *a, **k: ([poller.playlist_source.PlaylistItem(
                       "aaaaaaaaaaa", "In a playlist", "Someone", "UC9", 60, "t")], 0))
        self.run_worker(poller.PlaylistItemsFetcher(self.db, self.cfg, "PL1"))
        self.assertEqual([i["title"] for i in self.db.playlist_items("PL1")],
                         ["In a playlist"])

    def test_playlist_items_fetcher_stores_the_skipped_count(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.patch(poller.playlist_source, "fetch_items", lambda *a, **k: ([], 2))
        self.run_worker(poller.PlaylistItemsFetcher(self.db, self.cfg, "PL1"))
        self.assertEqual(self.db.playlist("PL1")["skipped"], 2)

    def test_search_fetcher(self):
        got = []
        self.patch(poller.search_source, "fetch",
                   lambda *a, **k: [poller.flatlist.FlatVideo(
                       "aaaaaaaaaaa", "A result", "Someone", "UC9", 60, "t", 10)])
        worker = poller.SearchFetcher(self.db, self.cfg, "anything")
        worker.results.connect(lambda q, start, rows: got.append((q, start, rows)))
        self.run_worker(worker)
        self.assertEqual(got[0][0], "anything")
        self.assertEqual(got[0][2][0]["title"], "A result")

    def test_checkup(self):
        got = []
        worker = poller.Checkup(self.db, self.cfg, network=False)
        worker.ready.connect(got.append)
        self.run_worker(worker)
        # Every check answers something, and none of them raises.
        self.assertTrue(got and len(got[0]) > 5)
        self.assertTrue(all(c["state"] in ("ok", "warn", "fail") for c in got[0]))

    def test_live_watcher(self):
        self.patch(poller.tokens, "load", lambda: object())
        self.patch(poller.twitch, "Client", _TwitchClient)
        self.patch(poller.livecheck, "check",
                   lambda cfg, ext_id, *a, **k: LiveState(ext_id, 5, True))
        self.run_worker(poller.LiveWatcher(self.db, self.cfg))

    def test_detail_fetcher(self):
        self.patch(poller.dislike_source, "fetch",
                   lambda *a, **k: type("V", (), {"dislikes": 3})())
        self.patch(poller.comment_source, "fetch",
                   lambda *a, **k: ([], poller.comment_source.Details(views=1, likes=2)))
        self.run_worker(poller.DetailFetcher(
            self.db, self.cfg, "yt:aaaaaaaaaaa", "aaaaaaaaaaa",
            "https://www.youtube.com/watch?v=aaaaaaaaaaa"))

    def test_source_details(self):
        self.patch(poller, "run_process",
                   lambda *a, **k: type("R", (), {"stdout": "Title\thttps://a/b.jpg"})())
        self.run_worker(poller.SourceDetails(self.db, self.cfg, "https://a/stream"))

    def test_twitch_login_without_a_client_id_is_a_message_not_a_crash(self):
        # One is shipped, so this is somebody who deliberately emptied it.
        worker = poller.TwitchLogin(self.db, Config(raw={"twitch": {"client_id": ""}}))
        said = self.run_worker(worker)
        self.assertTrue(any("client id" in line for line in said))

    def test_shutdown_cancels_a_thread_that_has_not_begun_yet(self):
        """The race behind a crash on exit.

        A thread that has been started but whose run has not begun is not
        running yet, so filtering the shutdown list on that left it alive, and
        Qt aborts the process when it destroys a live QThread. Cancelling one
        that never started costs nothing, so every thread is cancelled.
        """
        from weave.ui.bridge import Bridge

        class Idle:
            def __init__(self):
                self.cancelled = False
                self.waited = False

            def isRunning(self):
                return False        # exactly the case that used to be skipped

            def cancel(self):
                self.cancelled = True

            def wait(self, _ms):
                self.waited = True

        idle = Idle()
        bridge = Bridge.__new__(Bridge)          # no Qt object needed for this
        bridge._stopping = False
        bridge._threads = {idle}
        bridge._audio = None
        Bridge.shutdown(bridge, timeout_ms=10)
        self.assertTrue(idle.cancelled)
        self.assertTrue(idle.waited)

    def test_every_launched_worker_is_waited_for(self):
        """The shutdown list used to be found by inspecting attributes, which
        missed a worker held anywhere else. Now a worker is on the list from
        the moment it is launched until it is reaped, whatever holds it."""
        from weave.ui.bridge import Bridge

        class Launched:
            def __init__(self):
                self.cancelled = False
                self.started = False

            def start(self):
                self.started = True

            def cancel(self):
                self.cancelled = True

            def wait(self, _ms):
                pass

            class _Finished:
                def connect(self, *_a):
                    pass

            finished = _Finished()

        worker = Launched()
        bridge = Bridge.__new__(Bridge)
        bridge._stopping = False
        bridge._threads = set()
        bridge._audio = None
        self.assertTrue(Bridge._launch(bridge, worker))
        self.assertIn(worker, bridge._threads)
        Bridge.shutdown(bridge, timeout_ms=10)
        self.assertTrue(worker.cancelled)

    def test_a_finished_worker_is_let_go(self):
        """A poll a minute and a live check every ninety seconds, each kept
        for the life of the window, was a slow leak. A reaped worker leaves
        the list, the attribute that held it and, through Qt, memory."""
        from weave.ui.bridge import Bridge

        class Done:
            def __init__(self):
                self.deleted = False

            def isFinished(self):
                return True

            def deleteLater(self):
                self.deleted = True

        done = Done()
        bridge = Bridge.__new__(Bridge)
        bridge._threads = {done}
        bridge._poller = done
        bridge._source_details = [done]
        bridge.sender = lambda: None            # swept by finished state instead
        Bridge._reap(bridge)
        self.assertEqual(bridge._threads, set())
        self.assertIsNone(bridge._poller)
        self.assertEqual(bridge._source_details, [])
        self.assertTrue(done.deleted)

    def test_nothing_new_starts_once_shutdown_has_begun(self):
        """The other half of the same crash, and the half that actually caused
        it. A timer that was already due fired after shutdown had finished,
        started a fresh poll, and Qt aborted destroying the live thread.
        """
        from weave.ui.bridge import Bridge

        class Started:
            def __init__(self):
                self.started = False

            def start(self):
                self.started = True

            class _Finished:
                def connect(self, *_a):
                    pass

            finished = _Finished()

        bridge = Bridge.__new__(Bridge)
        bridge._stopping = False
        bridge._threads = set()
        first = Started()
        self.assertTrue(Bridge._launch(bridge, first))
        self.assertTrue(first.started)

        bridge._stopping = True
        second = Started()
        self.assertFalse(Bridge._launch(bridge, second))
        self.assertFalse(second.started)

    def test_no_class_defines_the_same_method_twice(self):
        """Two methods with one name leaves whichever came last, silently.

        It has happened twice on the bridge, which carries well over a hundred
        methods and a lot of underscore prefixed workers. Both times the loss
        was invisible until the thing ran, and once it meant a signal quietly
        went nowhere.
        """
        import ast
        import collections

        for path in sorted(Path("weave").rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                names = [child.name for child in node.body
                         if isinstance(child, ast.FunctionDef)]
                repeated = [n for n, count in collections.Counter(names).items() if count > 1]
                self.assertEqual(repeated, [], f"{path}, class {node.name}")

    def test_every_worker_that_counts_requests_is_run_here(self):
        """A worker that counts requests has to be run by a test, or the next
        missing attribute reaches the app the way the last one did."""
        import re

        run_here = {"FeedPoller", "SubsImporter", "ChannelDetailsFetcher",
                    "HistoryImporter", "RecommendationsFetcher", "PlaylistsFetcher",
                    "PlaylistItemsFetcher", "SearchFetcher", "LiveWatcher",
                    "ChannelFeedFetcher", "ChannelPlaylistsFetcher",
                    "DetailFetcher", "ChannelAvatarsFetcher"}
        # The checkup runs the doctor, which counts its own requests.
        run_here.add("Checkup")
        source = Path("weave/poller.py").read_text()
        spenders = {match.group(1)
                    for match in re.finditer(r"class (\w+)\(Worker\):(.*?)(?=\nclass |\Z)",
                                             source, re.S)
                    if "_spend(" in match.group(2) or "budget.spend(" in match.group(2)}
        self.assertEqual(spenders - run_here, set())
        self.assertTrue(spenders, "the pattern no longer matches the workers")

    def test_the_bar_says_it_is_working_before_the_check_even_starts(self):
        """A Twitch answer arrives in a fraction of a second, so a flag raised
        only while the request is in flight was never on screen long enough to
        read. It goes up when the check is promised instead, and a check that
        never happens must not leave it up for ever.
        """
        from weave.ui.bridge import Bridge

        class Recorder:
            def emit(self, *_a):
                pass

        bridge = Bridge.__new__(Bridge)
        bridge._live = None
        bridge._live_checking = False
        bridge._live_ready = False
        bridge.liveChanged = Recorder()

        Bridge.expectLiveCheck(bridge)
        self.assertTrue(bridge._live_checking)

        # Nothing ever ran, so the guard puts it back down.
        Bridge._live_check_gave_up(bridge)
        self.assertFalse(bridge._live_checking)

    def test_a_running_check_is_left_alone_by_the_guard(self):
        from weave.ui.bridge import Bridge

        class Recorder:
            def emit(self, *_a):
                pass

        class Running:
            def isRunning(self):
                return True

        bridge = Bridge.__new__(Bridge)
        bridge._live = Running()
        bridge._live_checking = True
        bridge.liveChanged = Recorder()
        Bridge._live_check_gave_up(bridge)
        self.assertTrue(bridge._live_checking)

    def test_the_live_check_says_it_is_working_and_stops_saying_so(self):
        """The bar sits empty until the first check comes back, so it says it
        is checking in the meantime. A check ends three ways and can also be
        cancelled, and every one of them has to put the flag back down, or the
        line stays up for the rest of the evening.
        """
        from weave.ui import bridge as bridge_module
        from weave.ui.bridge import Bridge

        class Recorder:
            def __init__(self):
                self.count = 0

            def emit(self, *_a):
                self.count += 1

        class Wire:
            """A signal that keeps its slots, so the test can fire it."""

            def __init__(self):
                self.slots = []

            def connect(self, slot, *_a):
                self.slots.append(slot)

            def emit(self, *args):
                for slot in list(self.slots):
                    slot(*args)

        class Watcher:
            def __init__(self, *_a, **_k):
                self.updated = Wire()
                self.needsLogin = Wire()
                self.failed = Wire()
                self.finished = Wire()
                self.started = False

            def isRunning(self):
                return False

            def isFinished(self):
                return self.started

            def start(self):
                self.started = True

            def deleteLater(self):
                pass

        def make():
            bridge = Bridge.__new__(Bridge)
            bridge._db = self.db
            bridge._cfg = self.cfg
            bridge._live = None
            bridge._live_checking = False
            bridge._live_ready = False
            bridge._twitch_needs_login = False
            bridge._status = ""
            bridge._stopping = False
            bridge._threads = set()
            bridge._source_details = []
            bridge.liveChanged = Recorder()
            bridge.twitchChanged = Recorder()
            bridge.statusChanged = Recorder()
            bridge.sender = lambda: None
            return bridge

        self.patch(bridge_module, "LiveWatcher", Watcher)

        # The success path. Results arrive and the line goes.
        bridge = make()
        Bridge.refreshLive(bridge)
        self.assertTrue(bridge._live.started)
        self.assertTrue(live_checking(bridge), "the bar was never told a check began")
        Bridge._on_live(bridge, 1)
        self.assertFalse(live_checking(bridge))

        # The failure path. Twitch said no, and the line still goes.
        bridge = make()
        Bridge.refreshLive(bridge)
        self.assertTrue(live_checking(bridge))
        bridge._live.failed.emit("Twitch is unhappy")
        self.assertFalse(live_checking(bridge), "a failed check left the bar checking")
        self.assertIn("Twitch is unhappy", bridge._status)

        # And the ends that carry no result at all, a login that is missing
        # and a check cancelled on the way out. Both reach finished only.
        for name in ("needsLogin", "finished"):
            bridge = make()
            Bridge.refreshLive(bridge)
            self.assertTrue(live_checking(bridge))
            worker = bridge._live
            if name == "needsLogin":
                worker.needsLogin.emit()
            worker.finished.emit()
            self.assertFalse(live_checking(bridge), f"{name} left the bar checking")

        # Nothing starts once the window is going, so nothing may claim to be
        # checking either.
        bridge = make()
        bridge._stopping = True
        Bridge.refreshLive(bridge)
        self.assertFalse(live_checking(bridge))

    def test_a_finished_check_does_not_cut_short_the_one_after_it(self):
        """finished is delivered queued, so it can arrive after the timer has
        already started the next check. The flag belongs to that next check by
        then, and the late arrival must leave it alone."""
        from weave.ui.bridge import Bridge

        class Recorder:
            def emit(self, *_a):
                pass

        bridge = Bridge.__new__(Bridge)
        bridge._live_checking = True
        bridge._live_ready = False
        bridge.liveChanged = Recorder()
        older, newer = object(), object()
        bridge._live = newer
        bridge.sender = lambda: older
        Bridge._on_live_done(bridge)
        self.assertTrue(live_checking(bridge), "the running check was cut short")

        bridge.sender = lambda: newer
        Bridge._on_live_done(bridge)
        self.assertFalse(live_checking(bridge))

    def test_every_worker_is_built_on_the_base(self):
        """A worker that is not is a worker with no cancel, which Qt turns into
        an abort on the way out."""
        import inspect

        from PySide6.QtCore import QThread

        strays = [name for name, cls in inspect.getmembers(poller, inspect.isclass)
                  if issubclass(cls, QThread) and cls not in (QThread, poller.Worker)
                  and not issubclass(cls, poller.Worker)]
        self.assertEqual(strays, [])

    def test_every_worker_does_its_work_in_work_and_leaves_run_alone(self):
        """run belongs to the base. It is the one place an exception that
        escaped the work is caught and said, and a worker that overrides it
        has stepped out from under that net without anyone noticing."""
        import inspect

        for name, cls in inspect.getmembers(poller, inspect.isclass):
            if cls is poller.Worker or not issubclass(cls, poller.Worker):
                continue
            with self.subTest(worker=name):
                self.assertIn("work", vars(cls), f"{name} defines no work")
                self.assertNotIn("run", vars(cls), f"{name} overrides run")

    def test_an_exception_nobody_expected_is_said_rather_than_swallowed(self):
        """The bug class behind two evenings of a window that said working
        and did nothing. An exception leaving run ends the thread with no
        signal at all, so the base catches it and turns it into one."""
        import io
        from contextlib import redirect_stderr

        class Closing:
            closed = False

            def close(self):
                self.closed = True

        class Dies(poller.Worker):
            def __init__(self):
                super().__init__()
                self._db = Closing()

            def work(self):
                raise RuntimeError("boom")

        worker = Dies()
        said = []
        worker.crashed.connect(said.append)
        with redirect_stderr(io.StringIO()):
            worker.run()
        self.assertEqual(said, ["RuntimeError: boom"])
        # The connection this thread opened is closed on the way out, whatever
        # the way out was.
        self.assertTrue(worker._db.closed)

    def test_a_cancel_is_not_a_crash(self):
        class Leaves(poller.Worker):
            def work(self):
                raise poller.ProcessCancelled("cancelled")

        worker = Leaves()
        said = []
        worker.crashed.connect(said.append)
        worker.run()
        self.assertEqual(said, [])

    def test_the_bridge_puts_down_the_flag_a_crashed_worker_left_up(self):
        """Every worker raises some flag in the bridge while it runs, and each
        one used to be lowered only by that worker's own success or failure
        signal. A crash emitted neither, so the flag stayed up for good."""
        from weave.ui.bridge import Bridge

        class Recorder:
            def __init__(self):
                self.count = 0

            def emit(self, *_a):
                self.count += 1

        class Timer:
            def stop(self):
                pass

            def start(self, *_a):
                pass

        holders = ("_poller", "_importer", "_adder", "_details", "_searcher", "_recommended",
                   "_history", "_search", "_tracks", "_station", "_detail", "_cache_job",
                   "_twitch", "_checkup", "_playlists", "_playlist_items")

        def make(held: str):
            bridge = Bridge.__new__(Bridge)
            for name in holders:
                setattr(bridge, name, None)
            worker = object()
            setattr(bridge, held, worker)
            bridge._problems = []
            bridge._status = ""
            bridge._notice = "Working"
            bridge._notice_timer = Timer()
            bridge._busy = True
            bridge._import_state = "working"
            bridge._import_message = ""
            bridge._add_state = "working"
            bridge._add_message = ""
            bridge._add_queue = []
            bridge._adding = 3
            bridge._details_queue = []
            bridge._loading_more = True
            bridge._searching = True
            bridge._detail_loading = True
            bridge._cache_working = True
            bridge._twitch_status = "asking Twitch for a code"
            for signal in ("problemsChanged", "statusChanged", "noticeChanged", "busyChanged",
                           "importChanged", "addChanged", "musicChanged", "detailChanged",
                           "cacheChanged", "twitchChanged"):
                setattr(bridge, signal, Recorder())
            return bridge, worker

        bridge, worker = make("_poller")
        Bridge._on_worker_crashed(bridge, worker, "RuntimeError: boom")
        self.assertFalse(bridge._busy, "a dead poll left the window busy for good")
        self.assertTrue(bridge._problems and "boom" in bridge._problems[0])
        self.assertIn("boom", bridge._status)

        bridge, worker = make("_importer")
        Bridge._on_worker_crashed(bridge, worker, "OSError: disk")
        self.assertEqual(bridge._import_state, "failed")
        self.assertIn("disk", bridge._import_message)

        bridge, worker = make("_adder")
        Bridge._on_worker_crashed(bridge, worker, "ValueError: odd")
        self.assertEqual(bridge._add_state, "failed")
        self.assertEqual(bridge._adding, -1)

        for held in ("_searcher", "_recommended", "_history"):
            bridge, worker = make(held)
            Bridge._on_worker_crashed(bridge, worker, "x")
            self.assertFalse(bridge._loading_more, held)
            self.assertEqual(bridge._notice, "", held)

        for held in ("_search", "_tracks", "_station"):
            bridge, worker = make(held)
            Bridge._on_worker_crashed(bridge, worker, "x")
            self.assertFalse(bridge._searching, held)

        bridge, worker = make("_detail")
        Bridge._on_worker_crashed(bridge, worker, "x")
        self.assertFalse(bridge._detail_loading)

        bridge, worker = make("_cache_job")
        Bridge._on_worker_crashed(bridge, worker, "x")
        self.assertFalse(bridge._cache_working)

        bridge, worker = make("_twitch")
        Bridge._on_worker_crashed(bridge, worker, "x")
        self.assertIn("failed", bridge._twitch_status)

        # A worker the bridge holds nowhere in particular is still reported.
        bridge, worker = make("_checkup")
        Bridge._on_worker_crashed(bridge, object(), "y")
        self.assertEqual(len(bridge._problems), 1)

    def test_launching_connects_the_crash_report(self):
        from weave.ui.bridge import Bridge

        class Wire:
            def __init__(self):
                self.slots = []

            def connect(self, slot, *_a):
                self.slots.append(slot)

        class Crashes:
            def __init__(self):
                self.finished = Wire()
                self.crashed = Wire()

            def start(self):
                pass

        bridge = Bridge.__new__(Bridge)
        bridge._stopping = False
        bridge._threads = set()
        worker = Crashes()
        self.assertTrue(Bridge._launch(bridge, worker))
        self.assertEqual(len(worker.crashed.slots), 1)


if __name__ == "__main__":
    unittest.main()
