"""The streams half of a channel page.

A channel's videos tab and its streams tab are disjoint at the source: the
long form feed carries no stream and the streams feed carries nothing else.
Both land in one table here, so the two halves are two readings of it, and
what tells them apart has to answer for every row rather than for the rows it
was written with in mind.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave.db import Database, VideoRow

CHANNEL = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"


class TheTwoHalves(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")
        self.db.upsert_videos([
            VideoRow("youtube", "plain1", CHANNEL, "An ordinary video",
                     published_at=1_700_000_001, duration_s=600),
            VideoRow("youtube", "plain2", CHANNEL, "Another one",
                     published_at=1_700_000_002, duration_s=700),
            VideoRow("youtube", "ended1", CHANNEL, "A stream that ended",
                     published_at=1_700_000_003, live_status="was_live"),
        ])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def titles(self, **kwargs):
        return sorted(row["title"] for row
                      in self.db.feed(channel_key=CHANNEL, hide_watched=False, **kwargs))

    def test_the_videos_half_leaves_the_streams_out(self):
        self.assertEqual(self.titles(streams=False), ["An ordinary video", "Another one"])

    def test_and_the_streams_half_is_only_them(self):
        self.assertEqual(self.titles(streams=True), ["A stream that ended"])

    def test_asking_for_neither_half_answers_with_both(self):
        # What a group, a box and the feed itself ask for. A stream of a
        # channel you follow belongs in what you follow.
        self.assertEqual(len(self.titles()), 3)

    def test_the_halves_add_up(self):
        # They came apart once. An unset stream_pending made the test NULL,
        # NOT NULL is NULL, and the videos half came back empty while the
        # streams half looked perfectly right on its own.
        self.assertEqual(len(self.titles(streams=True)) + len(self.titles(streams=False)),
                         len(self.titles()))

    def test_an_announced_one_is_a_stream_before_it_has_a_status(self):
        self.db.upsert_videos([VideoRow("youtube", "soon1", CHANNEL, "Starting later",
                                        published_at=1_700_000_004)])
        self.db.set_scheduled_at("yt:soon1", 1_700_100_000)
        self.assertIn("Starting later", self.titles(streams=True))
        self.assertNotIn("Starting later", self.titles(streams=False))

    def test_and_so_is_one_still_being_asked_about(self):
        self.db.upsert_videos([VideoRow("youtube", "maybe1", CHANNEL, "Nobody watching yet",
                                        published_at=1_700_000_005)])
        self.db.mark_streams_pending(["yt:maybe1"])
        self.assertIn("Nobody watching yet", self.titles(streams=True))

    def test_the_half_is_offered_by_what_is_stored(self):
        self.assertEqual(self.db.channel_stream_count(CHANNEL), 1)

    def test_and_a_channel_that_never_streamed_offers_none(self):
        self.db.add_channel("yt:UCbbbbbbbbbbbbbbbbbbbbbb", "youtube",
                            "UCbbbbbbbbbbbbbbbbbbbbbb", "Two")
        self.assertEqual(self.db.channel_stream_count("yt:UCbbbbbbbbbbbbbbbbbbbbbb"), 0)


if __name__ == "__main__":
    unittest.main()
