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
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["members_only"], 0)

    def test_marking_it_sticks(self):
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["members_only"], 1)

    def test_and_can_be_taken_back(self):
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.db.set_members_only("yt:aaaaaaaaaaa", False)
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["members_only"], 0)

    def test_a_marked_one_leaves_the_ordinary_lists(self):
        # For almost every channel these cannot be opened, so rows nobody can
        # act on are noise in the feed, in a group and in the videos half.
        self.assertEqual([r["key"] for r in self.db.feed()], ["yt:aaaaaaaaaaa"])
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.assertEqual(self.db.feed(), [])
        self.assertEqual(self.db.feed(channel_key=CHANNEL), [])

    def test_and_is_found_in_its_own_half(self):
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.assertEqual([r["key"] for r in self.db.feed(channel_key=CHANNEL, members=True)],
                         ["yt:aaaaaaaaaaa"])

    def test_which_is_what_decides_the_button(self):
        self.assertEqual(self.db.channel_members_count(CHANNEL), 0)
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.assertEqual(self.db.channel_members_count(CHANNEL), 1)

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

    def row(self, members=False):
        rows = self.db.feed(channel_key=CHANNEL, members=members)
        return FeedModel._build(rows[0])

    def test_the_card_is_told_it_is_not_one(self):
        self.assertFalse(self.row()["isMembers"])

    def test_and_told_when_it_is(self):
        self.db.set_members_only("yt:aaaaaaaaaaa")
        self.assertTrue(self.row(members=True)["isMembers"])

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


class TheMembersFeed(unittest.TestCase):
    """The fourth per channel tab. It is the only address that carries this at
    all, so without it a members video is simply absent, which is how Weave
    behaved until now."""

    def test_it_has_an_address_of_its_own(self):
        from weave.sources import rss

        channel_id = "UCaaaaaaaaaaaaaaaaaaaaaa"
        self.assertEqual(rss.playlist_id(channel_id, rss.MEMBERS),
                         "UUMO" + channel_id[2:])
        self.assertIn("playlist_id=UUMO", rss.feed_url(channel_id, rss.MEMBERS))
        # The four tabs address four disjoint lists, so no two may share one.
        made = {rss.playlist_id(channel_id, kind)
                for kind in (rss.VIDEOS, rss.SHORTS, rss.LIVE, rss.MEMBERS)}
        self.assertEqual(len(made), 4)

    def test_everything_in_it_is_marked_on_arrival(self):
        from weave.sources import rss

        parsed = rss.parse(_FEED, rss.MEMBERS)
        self.assertTrue(parsed.videos)
        self.assertTrue(all(row.members_only for row in parsed.videos))

    def test_and_nothing_from_any_other_tab_is(self):
        from weave.sources import rss

        for kind in (rss.VIDEOS, rss.SHORTS, rss.LIVE, rss.CHANNEL):
            parsed = rss.parse(_FEED, kind)
            self.assertFalse(any(row.members_only for row in parsed.videos), kind)


class KeepingTheMark(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.addCleanup(self.db.close)
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")

    def row(self, members_only):
        return VideoRow("youtube", "aaaaaaaaaaa", CHANNEL, "Theirs",
                        published_at=1_700_000_000, members_only=members_only)

    def test_a_row_from_the_members_tab_is_stored_marked(self):
        self.db.upsert_videos([self.row(True)])
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["members_only"], 1)

    def test_and_another_feed_mentioning_it_does_not_unmark_it(self):
        # Every other source is silent about this rather than saying no, so a
        # zero from one of them is not an answer. Getting this wrong would
        # unmark a video the moment anything else listed it.
        self.db.upsert_videos([self.row(True)])
        self.db.upsert_videos([self.row(False)])
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["members_only"], 1)


class AskingForTheMembersTab(unittest.TestCase):
    """Whether the tab is asked for at all, and what a 404 on it means."""

    def setUp(self):
        from weave import poller
        from weave.budget import Budget
        from weave.net import HttpError
        from weave.sources import rss

        self.poller_mod, self.Budget, self.rss = poller, Budget, rss
        self.HttpError = HttpError
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.addCleanup(self.db.close)
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self._real = poller.rss.fetch
        self.addCleanup(setattr, poller.rss, "fetch", self._real)

    def make(self, on: bool):
        from weave.config import Config

        self.db.set_members_wanted("yt:UC1", on)
        cfg = Config(raw={"poll": {"poll_live_feeds": False}})
        return self.poller_mod.FeedPoller(self.db, cfg), cfg

    def answer(self, table):
        def fake(fetcher, ext_id, kind=self.rss.VIDEOS):
            found = table[kind]
            if isinstance(found, Exception):
                raise found
            return found
        self.poller_mod.rss.fetch = fake

    def kinds_asked(self, on: bool):
        made, _ = self.make(on)
        rows = self.db.channels_due(made._cfg.feed_tiers, limit=5, force=True)
        return {kind for _key, _ext, kind in made._feed_jobs(rows)}

    def test_no_channel_is_asked_unless_somebody_asked_for_it(self):
        # There is deliberately no discovery. Looking for the channels that
        # sell a membership would spend a request per channel in the library
        # to be told 404 by almost all of them.
        self.assertNotIn(self.rss.MEMBERS, self.kinds_asked(False))

    def test_and_one_that_was_asked_for_is(self):
        self.assertIn(self.rss.MEMBERS, self.kinds_asked(True))

    def run_round(self, on=True):
        made, cfg = self.make(on)
        budget = self.Budget(self.db, cfg.budget_limits, cfg.budget_window_s)
        return made._phase_rss(None, budget)

    def members_column(self):
        return self.db.channels()[0]["members"]

    def test_a_channel_that_sells_nothing_is_remembered_as_such(self):
        self.answer({self.rss.VIDEOS: self.rss.FeedResult("UC1", "One", [], self.rss.VIDEOS),
                     self.rss.MEMBERS: self.HttpError(404, "u")})
        _, _, failures = self.run_round()
        self.assertEqual(failures, 0)
        self.assertEqual(self.members_column(), 0)

    def test_a_refusal_leaves_the_question_open(self):
        # The endpoint answers a burst with a 404 as well, so a round where
        # the channel answered nothing at all decides nothing.
        self.answer({self.rss.VIDEOS: self.HttpError(404, "u"),
                     self.rss.CHANNEL: self.HttpError(404, "u"),
                     self.rss.MEMBERS: self.HttpError(404, "u")})
        self.run_round()
        self.assertIsNone(self.members_column())

    def test_one_that_answers_is_remembered_and_its_rows_are_marked(self):
        made = VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "Theirs",
                        published_at=1_700_000_000, members_only=True)
        self.answer({self.rss.VIDEOS: self.rss.FeedResult("UC1", "One", [], self.rss.VIDEOS),
                     self.rss.MEMBERS: self.rss.FeedResult("UC1", "One", [made],
                                                           self.rss.MEMBERS)})
        self.run_round()
        self.assertEqual(self.members_column(), 1)
        self.assertIn("yt:UC1", self.db.channels_wanting_members())
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["members_only"], 1)

    def test_turning_it_off_stops_the_asking_and_keeps_the_rows(self):
        made = VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "Theirs",
                        published_at=1_700_000_000, members_only=True)
        self.answer({self.rss.VIDEOS: self.rss.FeedResult("UC1", "One", [], self.rss.VIDEOS),
                     self.rss.MEMBERS: self.rss.FeedResult("UC1", "One", [made],
                                                           self.rss.MEMBERS)})
        self.run_round()
        self.db.set_members_wanted("yt:UC1", False)
        self.assertNotIn(self.rss.MEMBERS, self.kinds_asked(False))
        # Paid for once. They are still what that channel published, and
        # asking for them again later would cost the same requests over.
        self.assertEqual(self.db.channel_members_count("yt:UC1"), 1)


_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
 <yt:channelId>UCaaaaaaaaaaaaaaaaaaaaaa</yt:channelId>
 <title>Members-only videos</title>
 <author><name>One</name>
  <uri>https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa</uri></author>
 <entry>
  <id>yt:video:aaaaaaaaaaa</id>
  <yt:videoId>aaaaaaaaaaa</yt:videoId>
  <yt:channelId>UCaaaaaaaaaaaaaaaaaaaaaa</yt:channelId>
  <title>Behind the membership</title>
  <author><name>One</name>
   <uri>https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa</uri></author>
  <published>2026-09-07T12:00:00+00:00</published>
  <media:group>
   <media:thumbnail url="https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"/>
   <media:community>
    <media:starRating count="200"/>
    <media:statistics views="0"/>
   </media:community>
  </media:group>
 </entry>
</feed>
"""


class PressingIt(unittest.TestCase):
    """The press is refused in both places that reach the same address."""

    def bridge(self, members: bool):
        from tests.test_play import make_bridge

        # isLocked is the one the press reads: the mark says what a video is,
        # this says whether it can go anywhere. A membership you hold is
        # marked and still plays.
        row = {"key": "yt:aaaaaaaaaaa", "title": "Theirs",
               "url": "https://example/watch", "isLive": False, "isUpcoming": False,
               "scheduledText": "", "isMembers": members, "isLocked": members}
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

    def test_and_so_does_one_whose_membership_you_hold(self):
        from weave.ui.bridge import Bridge

        made = self.bridge(True)
        made._model._rows["yt:aaaaaaaaaaa"]["isLocked"] = False
        Bridge.play(made, "yt:aaaaaaaaaaa")
        self.assertEqual(len(made._player.calls), 1,
                         "a membership that is held was refused anyway")


if __name__ == "__main__":
    unittest.main()
