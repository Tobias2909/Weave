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
from weave.budget import Budget
from weave.config import Config
from weave.db import VideoRow
from weave.net import HttpError
from weave.sources import rss

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
