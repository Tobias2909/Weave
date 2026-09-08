"""Videos behind a channel's membership.

Nothing cheap says a video is members only. It is absent from the channel
feeds entirely, and the subscriptions feed reports availability as NA for
every entry, measured over a thousand of them. The one place the word arrives
is the live check, which is already made for the viewer count, so learning it
costs no request of its own.

Once it is known, three things follow: the card says so on the picture, a
press is refused rather than handing mpv an address that answers with a
sentence about joining the channel, and nothing asks about that video again,
because without a membership the answer cannot change.
"""

import tempfile
import unittest
from pathlib import Path

from weave.db import Database, VideoRow
from weave.sources import livecheck
from weave.ui.feed_model import FeedModel

CHANNEL = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"


class ReadingTheAnswer(unittest.TestCase):
    def test_the_call_asks_for_it(self):
        from weave.config import Config

        printed = _command(Config(raw={}))
        self.assertTrue(printed, "the live check printed no template at all")
        self.assertIn("%(availability)s", printed[0])

    def test_a_members_only_video_says_so(self):
        state = livecheck.parse_line("aaaaaaaaaaa", "NA|NA|NA|subscriber_only")
        self.assertTrue(state.members_only)

    def test_an_ordinary_one_does_not(self):
        state = livecheck.parse_line("aaaaaaaaaaa", "12|is_live|NA|public")
        self.assertFalse(state.members_only)
        self.assertTrue(state.still_live)
        self.assertEqual(state.viewers, 12)

    def test_an_answer_from_before_this_was_asked_for_still_reads(self):
        # Three fields, which is what the older command printed. It must yield
        # the viewer count rather than being thrown away for being short.
        state = livecheck.parse_line("aaaaaaaaaaa", "31|is_live|NA")
        self.assertEqual(state.viewers, 31)
        self.assertFalse(state.members_only)


def _command(cfg):
    """The print template the live check sends, without making the call."""
    seen = {}

    def fake_run(command, *_a, **_k):
        seen["command"] = command
        raise livecheck.LiveCheckError("not run")

    real = livecheck.ytdlp.run
    livecheck.ytdlp.run = fake_run
    try:
        livecheck.check(cfg, "aaaaaaaaaaa")
    except livecheck.LiveCheckError:
        pass
    finally:
        livecheck.ytdlp.run = real
    command = seen["command"]
    return [one for one in command if one.startswith("%(")]


class StoringIt(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.addCleanup(self.db.close)
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", CHANNEL, "Theirs",
                                        published_at=1_700_000_000)])

    def test_a_video_is_not_members_only_to_begin_with(self):
        self.assertEqual(self.db.feed()[0]["members_only"], 0)

    def test_marking_it_sticks(self):
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.assertEqual(self.db.feed()[0]["members_only"], 1)

    def test_and_can_be_taken_back(self):
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.db.set_members_only("yt:aaaaaaaaaaa", False)
        self.assertEqual(self.db.feed()[0]["members_only"], 0)

    def test_a_marked_stream_is_never_settled_again(self):
        self.db.mark_streams_pending(["yt:aaaaaaaaaaa"])
        self.assertEqual([row["key"] for row in self.db.streams_to_settle()],
                         ["yt:aaaaaaaaaaa"])
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.assertEqual(self.db.streams_to_settle(), [],
                         "a members only stream was asked about again")

    def test_and_is_never_asked_when_it_starts(self):
        self.db.set_upcoming("yt:aaaaaaaaaaa", None)
        self.assertEqual([row["key"] for row in self.db.upcoming_without_start()],
                         ["yt:aaaaaaaaaaa"])
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.assertEqual(self.db.upcoming_without_start(), [],
                         "a members only announcement was asked about again")


class OnTheCard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.addCleanup(self.db.close)
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", CHANNEL, "Theirs",
                                        published_at=1_700_000_000)])

    def row(self):
        return FeedModel._build(self.db.feed()[0])

    def test_the_card_is_told_it_is_not_one(self):
        self.assertFalse(self.row()["isMembers"])

    def test_and_told_when_it_is(self):
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.assertTrue(self.row()["isMembers"])

    def test_a_listing_with_no_such_column_is_not_a_crash(self):
        # A search result and a playlist entry are built from a listing that
        # has no column for this, the way they have none for a start time.
        plain = {"key": "yt:bbbbbbbbbbb", "title": "From a listing", "channel_key": CHANNEL,
                 "channel_title": "One", "avatar_url": None, "thumbnail_url": None,
                 "published_at": 1, "duration_s": 60, "views": None, "likes": None,
                 "watched": 0, "platform": "youtube", "ext_id": "bbbbbbbbbbb",
                 "live_status": None}
        self.assertFalse(FeedModel._build(plain)["isMembers"])


class TheWatcherRecordsIt(unittest.TestCase):
    """Each of the three questions the watcher asks can come back this way,
    and each one has somewhere different to go afterwards."""

    def setUp(self):
        import tempfile as tmpmod

        from weave import poller
        from weave.config import Config

        self._tmp = tmpmod.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.addCleanup(self.db.close)
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")
        self.poller = poller
        self.watcher = poller.LiveWatcher(self.db, Config(raw={}))
        self._real = poller.livecheck.check
        self.addCleanup(lambda: setattr(poller.livecheck, "check", self._real))
        poller.livecheck.check = lambda cfg, ext_id, *a, **k: livecheck.LiveState(
            ext_id, None, False, None, False, True)

    def video(self, live_status=None):
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", CHANNEL, "Theirs",
                                        published_at=1_700_000_000,
                                        live_status=live_status)])
        return "yt:aaaaaaaaaaa"

    def test_a_freshly_published_one_is_marked_and_settled(self):
        key = self.video()
        self.db.mark_streams_pending([key])
        self.watcher._settle_streams(self.poller.Budget(self.db, {}, 900))
        self.assertEqual(self.db.video(key)["members_only"], 1)
        self.assertEqual(self.db.streams_to_settle(), [])

    def test_and_is_not_called_finished(self):
        # It was never seen running, so saying it has ended would be inventing
        # a state nothing here can see.
        key = self.video()
        self.db.mark_streams_pending([key])
        self.watcher._settle_streams(self.poller.Budget(self.db, {}, 900))
        self.assertIsNone(self.db.video(key)["live_status"])

    def test_an_announced_one_stops_being_asked_when_it_starts(self):
        key = self.video()
        self.db.set_upcoming(key, None)
        self.watcher._check_upcoming(self.poller.Budget(self.db, {}, 900))
        self.assertEqual(self.db.video(key)["members_only"], 1)
        self.assertEqual(self.db.upcoming_without_start(), [])

    def test_one_already_in_the_bar_leaves_it(self):
        key = self.video(live_status="is_live")
        self.watcher._check_youtube()
        row = self.db.video(key)
        self.assertEqual(row["members_only"], 1)
        self.assertEqual((row["live_status"], row["live_viewers"]), ("was_live", None))


class PressingIt(unittest.TestCase):
    """The press is refused in both places that reach the same address."""

    def bridge(self, members: bool):
        from tests.test_play import make_bridge

        row = {"key": "yt:aaaaaaaaaaa", "title": "Theirs",
               "url": "https://example/watch", "isLive": False, "isUpcoming": False,
               "scheduledText": "", "isMembers": members}
        made = make_bridge([row])
        made.said = []
        made._set_notice = lambda text, *_a, **_k: made.said.append(text)
        return made

    def test_a_members_only_video_never_reaches_mpv(self):
        from weave.ui.bridge import Bridge

        made = self.bridge(True)
        Bridge.play(made, "yt:aaaaaaaaaaa")
        self.assertEqual(made._player.calls, [])

    def test_and_the_window_says_why(self):
        from weave.ui.bridge import Bridge

        made = self.bridge(True)
        Bridge.play(made, "yt:aaaaaaaaaaa")
        self.assertEqual(made.said, ["that one is for members of the channel"])

    def test_an_ordinary_one_still_plays(self):
        from weave.ui.bridge import Bridge

        made = self.bridge(False)
        Bridge.play(made, "yt:aaaaaaaaaaa")
        self.assertEqual(len(made._player.calls), 1)


if __name__ == "__main__":
    unittest.main()
