"""The lengths RSS cannot carry, and the second pass that fills them in.

Why any of this exists. The feed is built from each channel's RSS and RSS
carries no duration whatsoever, so the length of a video is filled in
afterwards by the subscriptions sweep. That sweep reaches roughly the newest
thousand videos across every subscription, which is a few weeks. Every other
door into the videos table hands over older rows: a channel feed publishes
fifteen entries the first time it is read, and opening a channel page reads the
same window. Those were already past the sweep's reach when they arrived, and
nothing asked a second time.

So the durations stopped partway down a feed, and it looked exactly like stored
data going missing. It was not. Both writers COALESCE, which is asserted here,
so a length once stored cannot be lost. There was simply no second pass.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave.db import Database, VideoRow
from weave.sources import lengths

CHANNEL = "UCaaaaaaaaaaaaaaaaaaaaaa"
CHANNEL_KEY = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"


def video(ext_id, **fields):
    fields.setdefault("is_short", False)
    return VideoRow(platform="youtube", ext_id=ext_id, channel_key=CHANNEL_KEY,
                    title=f"Video {ext_id}", published_at=1600000000, **fields)


class ReadingATabListing(unittest.TestCase):
    """The listing as yt-dlp prints it. Measured against real tabs, so the
    shapes here are the shapes that actually come back."""

    def test_a_length_and_a_live_state_are_both_read(self):
        found = lengths.parse("aaaaaaaaaaa\t1516\tNA\nbbbbbbbbbbb\t3930\twas_live\n")
        self.assertEqual([(f.ext_id, f.duration_s, f.live_status) for f in found],
                         [("aaaaaaaaaaa", 1516, None), ("bbbbbbbbbbb", 3930, "was_live")])

    def test_a_streams_tab_says_the_state_rather_than_it_being_guessed(self):
        # Measured on a real streams tab: every entry that has happened says
        # was_live outright. Guessing it would be wrong for the one that has
        # not happened yet, which is the newest entry there.
        found = lengths.parse("bbbbbbbbbbb\t3930\twas_live\n")
        self.assertEqual(found[0].live_status, "was_live")

    def test_an_announcement_that_has_not_happened_is_left_alone(self):
        # NA to both. It has no length because there is nothing to measure,
        # and saying it is over would be worse than saying nothing.
        self.assertEqual(lengths.parse("ccccccccccc\tNA\tNA\n"), [])

    def test_a_radio_row_is_dropped(self):
        # Thirteen characters and NA to everything, the same junk the other
        # flat listings mix in.
        self.assertEqual(lengths.parse("RDaaaaaaaaaaaa\tNA\tNA\n"), [])

    def test_blank_lines_and_short_output_answer_nothing(self):
        self.assertEqual(lengths.parse(""), [])
        self.assertEqual(lengths.parse("\n\n"), [])
        self.assertEqual(lengths.parse("aaaaaaaaaaa\n"), [])

    def test_only_the_two_tabs_that_have_lengths_can_be_asked(self):
        with self.assertRaises(lengths.LengthsError):
            lengths.fetch(CHANNEL, "shorts")

    def test_a_missing_tab_is_told_from_a_refusal(self):
        # Both measured against the live endpoint. The first is an answer and
        # settles the channel; anything else has to leave it to come round
        # again, and treating the first as the second asked the same channel
        # every poll for ever.
        self.assertTrue(lengths.is_missing_tab(
            "ERROR: [youtube:tab] UULVxx: YouTube said: The playlist does not exist."))
        self.assertTrue(lengths.is_missing_tab(
            "ERROR: [youtube:tab] UCxx: This channel does not have a streams tab"))
        self.assertFalse(lengths.is_missing_tab("ERROR: unable to download webpage: 500"))
        self.assertFalse(lengths.is_missing_tab(""))


class WhatTheDatabaseDoes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.db.add_channel(CHANNEL_KEY, "youtube", CHANNEL, "Someone")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_a_length_once_stored_is_never_lost(self):
        """The whole answer to how the gap happened. Nothing overwrites a
        length, so it was never there rather than gone."""
        self.db.upsert_videos([video("aaaaaaaaaaa", duration_s=300)])
        # A later feed read of the same video, carrying no duration at all,
        # which is every RSS read there has ever been.
        self.db.upsert_videos([video("aaaaaaaaaaa")])
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["duration_s"], 300)
        # And the second pass cannot overwrite one either.
        self.db.fill_lengths([("yt:aaaaaaaaaaa", 999, None)])
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["duration_s"], 300)

    def test_a_missing_length_is_filled(self):
        self.db.upsert_videos([video("aaaaaaaaaaa")])
        self.assertEqual(self.db.fill_lengths([("yt:aaaaaaaaaaa", 1516, None)]), 1)
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["duration_s"], 1516)

    def test_a_stream_read_out_of_the_streams_tab_stops_being_a_video(self):
        self.db.upsert_videos([video("aaaaaaaaaaa")])
        self.db.fill_lengths([("yt:aaaaaaaaaaa", 3930, "was_live")])
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["live_status"], "was_live")
        # Which is what puts it in the streams half of a group rather than the
        # videos half, where a stream that came in through RSS used to sit.
        videos = [row["ext_id"] for row in self.db.feed(channel_key=CHANNEL_KEY, streams=False)]
        streams = [row["ext_id"] for row in self.db.feed(channel_key=CHANNEL_KEY, streams=True)]
        self.assertEqual((videos, streams), ([], ["aaaaaaaaaaa"]))

    def test_a_live_state_already_known_is_kept(self):
        self.db.upsert_videos([video("aaaaaaaaaaa", live_status="is_live")])
        self.db.fill_lengths([("yt:aaaaaaaaaaa", 3930, "was_live")])
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["live_status"], "is_live")

    def test_nothing_to_say_writes_nothing(self):
        self.db.upsert_videos([video("aaaaaaaaaaa")])
        self.assertEqual(self.db.fill_lengths([("yt:aaaaaaaaaaa", None, None)]), 0)
        self.assertEqual(self.db.fill_lengths([]), 0)

    def test_a_long_one_settles_the_shorts_question_too(self):
        self.db.upsert_videos([VideoRow(platform="youtube", ext_id="aaaaaaaaaaa",
                                        channel_key=CHANNEL_KEY, title="A")])
        self.db.fill_lengths([("yt:aaaaaaaaaaa", 1516, None)])
        self.assertEqual(self.db.video("yt:aaaaaaaaaaa")["is_short"], 0)

    def test_only_rows_owed_a_length_are_asked_about(self):
        self.db.upsert_videos([video("aaaaaaaaaaa"), video("bbbbbbbbbbb", duration_s=60),
                               video("ccccccccccc", is_short=True)])
        self.assertEqual(self.db.videos_without_a_length(CHANNEL_KEY), {"aaaaaaaaaaa"})

    def test_the_worst_channel_comes_first(self):
        other = "yt:UCbbbbbbbbbbbbbbbbbbbbbb"
        self.db.add_channel(other, "youtube", "UCbbbbbbbbbbbbbbbbbbbbbb", "Another")
        self.db.upsert_videos([video("aaaaaaaaaaa")])
        self.db.upsert_videos([
            VideoRow(platform="youtube", ext_id=f"other{i:06d}", channel_key=other,
                     title="B", is_short=False) for i in range(3)])
        found = self.db.channels_missing_lengths(2)
        self.assertEqual([row["key"] for row in found], [other, CHANNEL_KEY])
        self.assertEqual([row["missing"] for row in found], [3, 1])

    def test_a_channel_already_read_waits_for_the_recheck(self):
        import time

        self.db.upsert_videos([video("aaaaaaaaaaa")])
        self.db.mark_lengths_read(CHANNEL_KEY)
        # No recheck window asked for means channels never read, not every
        # channel. A cutoff of now is one every stamp is already older than,
        # which would ask the same channel every poll for ever.
        self.assertEqual(self.db.channels_missing_lengths(2), [])
        self.assertEqual(self.db.channels_missing_lengths(2, older_than_s=604800), [])

        # Read a fortnight ago, so a week's recheck reaches it again, in case
        # something that was private has come back.
        self.db.mark_lengths_read(CHANNEL_KEY, now=int(time.time()) - 14 * 86400)
        later = self.db.channels_missing_lengths(2, older_than_s=604800)
        self.assertEqual([row["key"] for row in later], [CHANNEL_KEY])

    def test_a_channel_nobody_follows_is_not_worth_a_request(self):
        loose = "yt:UCcccccccccccccccccccccc"
        self.db.remember_channel(loose, "youtube", "UCccccccccccccccccccccccc", "A stranger")
        self.db.upsert_videos([VideoRow(platform="youtube", ext_id="loosevideo1",
                                        channel_key=loose, title="L", is_short=False)])
        self.assertEqual([row["key"] for row in self.db.channels_missing_lengths(5)], [])

    def test_the_gap_can_be_counted_for_the_page_and_the_doctor(self):
        self.db.upsert_videos([video("aaaaaaaaaaa"), video("bbbbbbbbbbb"),
                               video("ccccccccccc", duration_s=60)])
        self.assertEqual(self.db.lengths_gap(), (2, 1))
        self.db.fill_lengths([("yt:aaaaaaaaaaa", 100, None), ("yt:bbbbbbbbbbb", 200, None)])
        self.assertEqual(self.db.lengths_gap(), (0, 0))


if __name__ == "__main__":
    unittest.main()
