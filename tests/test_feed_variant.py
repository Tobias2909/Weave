"""Which feed address answers for a channel, and what a 404 is allowed to mean.

A channel is read from its long form tab, which carries no Shorts at all, and
that is the whole Shorts filter. A channel with no such tab falls back to the
mixed feed, which carries everything.

The endpoint answers a burst of requests with a 404 rather than with a busy
signal, and a missing tab answers 404 as well. Measured on the live endpoint:
a burst refuses the per tab playlist feeds while the mixed channel feed keeps
answering, so asking the mixed feed cannot tell the two apart. Getting that
wrong moved a hundred healthy channels onto the mixed feed for good, and their
Shorts poured into the feed for days.
"""

import unittest
from dataclasses import replace

from PySide6.QtCore import QCoreApplication

from weave import poller
from weave.budget import FEEDS, SHORTS, Budget
from weave.config import Config
from weave.db import VideoRow
from weave.net import HttpError
from weave.sources import kind, rss

from . import support

_app = QCoreApplication.instance() or QCoreApplication([])


def _feed(kind, videos=()):
    # rss.parse stamps every row it reads with what its feed carries, and that
    # stamp is the Shorts filter. These fakes stand in for parse, so they do
    # the same thing rather than handing over rows of unknown kind.
    rows = [replace(video, is_short=rss.is_short_kind(kind)) for video in videos]
    return rss.FeedResult("UC1", "One", rows, kind)


def _video(ext_id, title="A video"):
    return VideoRow("youtube", ext_id, "yt:UC1", title)


class _Wire:
    """Stands in for the Fetcher where only its request count is read."""

    sent = 0


class ARoundOfRefusals(unittest.TestCase):
    """One round of 404s must move nothing. This is the bug that shipped."""

    def setUp(self):
        self.db = support.scratch_db(self)
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.poller = poller.FeedPoller(self.db, self.cfg)
        self._real = poller.rss.fetch
        self.addCleanup(setattr, poller.rss, "fetch", self._real)

    def answer(self, table):
        def fake(fetcher, ext_id, kind=rss.VIDEOS):
            found = table[kind]
            if isinstance(found, Exception):
                raise found
            return found
        poller.rss.fetch = fake

    def run_round(self):
        # Forced, since a round only asks about channels that are due and the
        # point here is what several rounds in a row do.
        self.poller._force_all = True
        budget = Budget(self.db, self.cfg.budget_limits, self.cfg.budget_window_s)
        return self.poller._phase_rss(None, budget)

    def variant(self):
        return self.db.channels()[0]["feed_variant"]

    def test_one_404_does_not_move_the_channel(self):
        self.answer({rss.VIDEOS: HttpError(404, "u"),
                     rss.CHANNEL: _feed(rss.CHANNEL),
                     rss.LIVE: HttpError(404, "u")})
        self.run_round()
        self.assertIsNone(self.variant())

    def test_and_it_costs_nothing_extra_while_it_is_undecided(self):
        # The mixed feed used to be fetched there and then, so a burst cost
        # two requests per channel at exactly the moment the endpoint was
        # asking for fewer.
        asked = []

        def fake(fetcher, ext_id, kind=rss.VIDEOS):
            asked.append(kind)
            raise HttpError(404, "u")
        poller.rss.fetch = fake
        self.run_round()
        self.assertNotIn(rss.CHANNEL, asked)

    def test_the_tab_answering_again_wipes_the_slate(self):
        self.answer({rss.VIDEOS: HttpError(404, "u"),
                     rss.CHANNEL: _feed(rss.CHANNEL),
                     rss.LIVE: HttpError(404, "u")})
        self.run_round()
        self.answer({rss.VIDEOS: _feed(rss.VIDEOS), rss.LIVE: HttpError(404, "u")})
        self.run_round()
        self.assertEqual(self.db.channels()[0]["long_form_404s"], 0)
        self.answer({rss.VIDEOS: HttpError(404, "u"),
                     rss.CHANNEL: _feed(rss.CHANNEL),
                     rss.LIVE: HttpError(404, "u")})
        self.run_round()
        self.assertIsNone(self.variant())

    def test_a_tab_that_is_really_missing_is_believed_in_the_end(self):
        self.answer({rss.VIDEOS: HttpError(404, "u"),
                     rss.CHANNEL: _feed(rss.CHANNEL),
                     rss.LIVE: HttpError(404, "u")})
        for _ in range(poller.LONG_FORM_STRIKES):
            self.run_round()
        self.assertEqual(self.variant(), rss.CHANNEL)

    def test_a_round_that_stored_nothing_settles_no_streams_verdict(self):
        # The videos feed answering is what says the endpoint is healthy, and
        # a channel that only collected a strike answered nothing.
        self.answer({rss.VIDEOS: HttpError(404, "u"),
                     rss.CHANNEL: _feed(rss.CHANNEL),
                     rss.LIVE: HttpError(404, "u")})
        self.run_round()
        self.assertIsNone(self.db.channels()[0]["streams"])


class TheShortsThatSlippedIn(unittest.TestCase):
    """A channel on the mixed feed has its Shorts tab read, which is what
    tells the rows that feed stored apart."""

    def setUp(self):
        self.db = support.scratch_db(self)
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.poller = poller.FeedPoller(self.db, self.cfg)
        self._real = poller.rss.fetch
        self.addCleanup(setattr, poller.rss, "fetch", self._real)

    def answer(self, table):
        def fake(fetcher, ext_id, kind=rss.VIDEOS):
            found = table[kind]
            if isinstance(found, Exception):
                raise found
            return found
        poller.rss.fetch = fake

    def run_round(self):
        self.poller._force_all = True
        budget = Budget(self.db, self.cfg.budget_limits, self.cfg.budget_window_s)
        return self.poller._phase_rss(None, budget)

    def kinds(self):
        return {row["key"]: row["is_short"] for row in self.db.conn.execute(
            "SELECT key, is_short FROM videos")}

    def test_a_row_of_unknown_kind_is_named_by_the_shorts_tab(self):
        # It arrived from the mixed feed, which says nothing about kind, so it
        # was in the feed looking like an ordinary video.
        self.db.upsert_videos([_video("aaaaaaaaaaa", "A Short")])
        self.assertIsNone(self.kinds()["yt:aaaaaaaaaaa"])
        self.answer({rss.CHANNEL: _feed(rss.CHANNEL),
                     rss.SHORTS: _feed(rss.SHORTS, [_video("aaaaaaaaaaa", "A Short")])})
        self.run_round()
        self.assertEqual(self.kinds()["yt:aaaaaaaaaaa"], 1)

    def test_what_the_shorts_tab_does_not_carry_is_left_alone(self):
        self.db.upsert_videos([_video("bbbbbbbbbbb", "An ordinary video")])
        self.answer({rss.CHANNEL: _feed(rss.CHANNEL),
                     rss.SHORTS: _feed(rss.SHORTS, [_video("aaaaaaaaaaa", "A Short")])})
        self.run_round()
        self.assertIsNone(self.kinds()["yt:bbbbbbbbbbb"])

    def test_a_channel_with_no_shorts_tab_is_not_asked_for_ever(self):
        # A row of unknown kind is what makes the Shorts tab worth reading at
        # all: with nothing to sort out, the round offers the long form tab
        # instead, which is the way off the mixed feed.
        self.db.upsert_videos([_video("bbbbbbbbbbb", "An ordinary video")])
        self.answer({rss.CHANNEL: _feed(rss.CHANNEL), rss.SHORTS: HttpError(404, "u")})
        self.run_round()
        self.assertTrue(self.db.channels()[0]["shorts_sweep_at"])


class TheWayBack(unittest.TestCase):
    """A fallback is re-tested rather than believed for ever."""

    def setUp(self):
        self.db = support.scratch_db(self)
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.db.stamp_shorts_sweep("yt:UC1")
        self.poller = poller.FeedPoller(self.db, self.cfg)
        self._real = poller.rss.fetch
        self.addCleanup(setattr, poller.rss, "fetch", self._real)

    def answer(self, table):
        def fake(fetcher, ext_id, kind=rss.VIDEOS):
            found = table[kind]
            if isinstance(found, Exception):
                raise found
            return found
        poller.rss.fetch = fake

    def run_round(self):
        self.poller._force_all = True
        budget = Budget(self.db, self.cfg.budget_limits, self.cfg.budget_window_s)
        return self.poller._phase_rss(None, budget)

    def test_a_tab_that_answers_again_takes_the_channel_back(self):
        self.answer({rss.VIDEOS: _feed(rss.VIDEOS, [_video("aaaaaaaaaaa")]),
                     rss.LIVE: HttpError(404, "u")})
        self.run_round()
        row = self.db.channels()[0]
        self.assertIsNone(row["feed_variant"])
        self.assertEqual(row["long_form_404s"], 0)
        self.assertTrue(row["variant_checked_at"])

    def test_a_tab_that_is_still_missing_keeps_the_channel_where_it_is(self):
        self.answer({rss.VIDEOS: HttpError(404, "u"),
                     rss.CHANNEL: _feed(rss.CHANNEL),
                     rss.LIVE: HttpError(404, "u")})
        self.run_round()
        row = self.db.channels()[0]
        self.assertEqual(row["feed_variant"], rss.CHANNEL)
        # Stamped, or it would be asked again every single round.
        self.assertTrue(row["variant_checked_at"])

    def test_what_the_long_form_tab_carries_is_stored_as_long_form(self):
        self.answer({rss.VIDEOS: _feed(rss.VIDEOS, [_video("aaaaaaaaaaa")]),
                     rss.LIVE: HttpError(404, "u")})
        self.run_round()
        kind = self.db.conn.execute(
            "SELECT is_short FROM videos WHERE key='yt:aaaaaaaaaaa'").fetchone()[0]
        self.assertEqual(kind, 0)


class OpeningAStrangersPage(unittest.TestCase):
    """The channel page fetches one feed as well, and it must not decide this
    question on the strength of a single call."""

    def setUp(self):
        self.db = support.scratch_db(self)
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self._real = poller.rss.fetch
        self.addCleanup(setattr, poller.rss, "fetch", self._real)

    def test_a_404_there_remembers_nothing(self):
        def fake(fetcher, ext_id, kind=rss.VIDEOS):
            if kind == rss.VIDEOS:
                raise HttpError(404, "u")
            return _feed(kind)
        poller.rss.fetch = fake
        worker = poller.ChannelFeedFetcher(self.db, self.cfg, "yt:UC1", "UC1")
        worker.work()
        self.assertIsNone(self.db.channels()[0]["feed_variant"])


if __name__ == "__main__":
    unittest.main()


class TheRowsHeldBack(unittest.TestCase):
    """What a list does with a row whose kind nothing has said yet.

    MEASURED on a real library: eleven of the top hundred rows in All were of
    unknown kind, every one from a channel on the mixed feed, and of the four
    newest two were Shorts and two were ordinary videos. So showing them all
    puts Shorts in the feed and hiding them all loses real videos. They are
    held back until the kind test answers, which takes a tick.
    """

    def setUp(self):
        self.db = support.scratch_db(self)
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.add_channel("yt:UC2", "youtube", "UC2", "Two")

    def store(self, channel, ext_id, **fields):
        self.db.upsert_videos([VideoRow("youtube", ext_id, channel, "A row", **fields)])

    def titles(self):
        return {row["ext_id"] for row in self.db.feed()}

    def test_a_row_of_unknown_kind_from_the_mixed_feed_is_held_back(self):
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.store("yt:UC1", "aaaaaaaaaaa")
        self.assertNotIn("aaaaaaaaaaa", self.titles())
        self.assertEqual(self.db.unwatched_total(), 0)

    def test_a_row_of_unknown_kind_from_a_tab_feed_still_shows(self):
        # Every per tab feed carries one kind, so NULL from one of those is a
        # video RSS never described rather than a question. A video saved out
        # of the suggestions or the history is the same case.
        self.store("yt:UC2", "bbbbbbbbbbb")
        self.assertIn("bbbbbbbbbbb", self.titles())

    def test_the_held_row_shows_as_soon_as_the_test_says_it_is_a_video(self):
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.store("yt:UC1", "aaaaaaaaaaa")
        self.db.set_video_kind("yt:aaaaaaaaaaa", False)
        self.assertIn("aaaaaaaaaaa", self.titles())

    def test_a_short_stays_out(self):
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.store("yt:UC1", "aaaaaaaaaaa")
        self.db.set_video_kind("yt:aaaaaaaaaaa", True)
        self.assertNotIn("aaaaaaaaaaa", self.titles())

    def test_only_the_held_rows_are_asked_about(self):
        # A row of unknown kind on a channel read per tab shows anyway, so
        # nothing is waiting on it and a request there would buy nothing.
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.store("yt:UC1", "aaaaaaaaaaa")
        self.store("yt:UC2", "bbbbbbbbbbb")
        owed = {row["ext_id"] for row in self.db.videos_owed_a_kind(limit=10)}
        self.assertEqual(owed, {"aaaaaaaaaaa"})

    def test_a_length_past_the_ceiling_settles_it_for_nothing(self):
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.store("yt:UC1", "aaaaaaaaaaa", duration_s=600)
        self.assertEqual(self.db.settle_kinds_by_length(), 1)
        self.assertIn("aaaaaaaaaaa", self.titles())
        self.assertEqual(self.db.videos_owed_a_kind(limit=10), [])

    def test_a_short_length_settles_nothing(self):
        # Length is not the signal and never was. The clip this was first
        # tested on runs 88 seconds and is an ordinary video.
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.store("yt:UC1", "aaaaaaaaaaa", duration_s=88)
        self.db.settle_kinds_by_length()
        self.assertEqual(len(self.db.videos_owed_a_kind(limit=10)), 1)

    def test_an_unanswered_row_is_not_asked_again_every_tick(self):
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.store("yt:UC1", "aaaaaaaaaaa")
        self.db.stamp_kind_tried(["yt:aaaaaaaaaaa"])
        self.assertEqual(self.db.videos_owed_a_kind(limit=10), [])
        # An hour later it is worth another try.
        self.assertEqual(len(self.db.videos_owed_a_kind(limit=10, retest_s=0)), 1)


class TheKindTest(unittest.TestCase):
    """`/shorts/<id>` answers 200 for a Short and sends a 303 to `/watch` for
    anything else. MEASURED against the live site 2026-09-09 on rows of known
    kind: three Shorts answered 200 and three long videos answered 303."""

    class _Fetcher:
        def __init__(self, answer):
            self.answer = answer
            self.asked = []
            self.cookies = None

        def head_status(self, url, cookies=None):
            self.asked.append(url)
            self.cookies = cookies
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer, ""

    def test_two_hundred_is_a_short(self):
        self.assertIs(kind.is_short(self._Fetcher(200), "aaaaaaaaaaa"), True)

    def test_a_redirect_to_watch_is_an_ordinary_video(self):
        self.assertIs(kind.is_short(self._Fetcher(303), "aaaaaaaaaaa"), False)

    def test_the_consent_page_settles_nothing(self):
        # Without the consent cookie both kinds answer 302, measured, which
        # would mark every ordinary video a Short if 302 were read as one.
        self.assertIsNone(kind.is_short(self._Fetcher(302), "aaaaaaaaaaa"))

    def test_a_refusal_settles_nothing(self):
        for status in (404, 429, 500, 503):
            self.assertIsNone(kind.is_short(self._Fetcher(status), "aaaaaaaaaaa"), status)

    def test_the_consent_cookie_is_sent(self):
        fetcher = self._Fetcher(200)
        kind.is_short(fetcher, "aaaaaaaaaaa")
        self.assertEqual(fetcher.cookies, {"SOCS": "CAI"})
        self.assertEqual(fetcher.asked, ["https://www.youtube.com/shorts/aaaaaaaaaaa"])


class TheKindPhase(unittest.TestCase):
    """The round that settles what the feed is holding back."""

    def setUp(self):
        self.db = support.scratch_db(self)
        self.cfg = Config(raw={})
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.set_feed_variant("yt:UC1", rss.CHANNEL)
        self.poller = poller.FeedPoller(self.db, self.cfg)
        self._real = poller.kind_source.is_short
        self.addCleanup(setattr, poller.kind_source, "is_short", self._real)

    def answer(self, table):
        def fake(fetcher, video_id):
            found = table[video_id]
            if isinstance(found, Exception):
                raise found
            return found
        poller.kind_source.is_short = fake

    def run_phase(self):
        budget = Budget(self.db, self.cfg.budget_limits, self.cfg.budget_window_s)
        return self.poller._phase_kinds(_Wire(), budget)

    def kinds(self):
        return {row["ext_id"]: row["is_short"] for row in self.db.conn.execute(
            "SELECT ext_id, is_short FROM videos")}

    def test_it_settles_both_answers(self):
        self.db.upsert_videos([_video("aaaaaaaaaaa"), _video("bbbbbbbbbbb")])
        self.answer({"aaaaaaaaaaa": True, "bbbbbbbbbbb": False})
        self.assertEqual(self.run_phase(), 2)
        self.assertEqual(self.kinds(), {"aaaaaaaaaaa": 1, "bbbbbbbbbbb": 0})

    def test_an_unclear_answer_marks_nothing(self):
        # The row keeps waiting, which is invisible. Marking it wrongly would
        # either put a Short in the feed for good or lose a real video.
        self.db.upsert_videos([_video("aaaaaaaaaaa")])
        self.answer({"aaaaaaaaaaa": None})
        self.assertEqual(self.run_phase(), 0)
        self.assertIsNone(self.kinds()["aaaaaaaaaaa"])
        self.assertEqual(self.db.videos_owed_a_kind(limit=10), [])

    def test_a_raised_error_marks_nothing_and_does_not_escape(self):
        self.db.upsert_videos([_video("aaaaaaaaaaa")])
        self.answer({"aaaaaaaaaaa": HttpError(500, "u")})
        self.assertEqual(self.run_phase(), 0)
        self.assertIsNone(self.kinds()["aaaaaaaaaaa"])

    def test_it_is_paced(self):
        self.db.upsert_videos([_video(chr(97 + n) * 11) for n in range(9)])
        self.answer({chr(97 + n) * 11: False for n in range(9)})
        self.assertEqual(self.run_phase(), poller.KIND_TESTS_PER_TICK)

    def test_it_spends_its_own_endpoint_and_not_the_feed_ceiling(self):
        self.db.upsert_videos([_video("aaaaaaaaaaa")])
        self.answer({"aaaaaaaaaaa": True})
        self.run_phase()
        self.assertEqual(self.db.requests_in_window(SHORTS, 900)[0], 1)
        self.assertEqual(self.db.requests_in_window(FEEDS, 900)[0], 0)

    def test_nothing_held_back_costs_nothing(self):
        self.answer({})
        self.assertEqual(self.run_phase(), 0)
        self.assertEqual(self.db.requests_in_window(SHORTS, 900)[0], 0)
