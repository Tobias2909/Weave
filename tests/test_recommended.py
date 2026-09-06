"""Parsing what YouTube suggests.

The list is not all videos. It mixes in radio playlist rows whose id is
thirteen characters and whose every other field is NA, measured, and reading
one of those as a video would put a row in the grid that cannot be played.
"""

import unittest

from weave.sources import recommended

REAL = ("aaaaaaaaaaa\tA real video\tSome channel\tUCabcdefghijklmnopqrstuv\t5646"
        "\thttps://i/x.jpg\t7600516\t1600000000")
RADIO = "RDabcdefghijk\tNA\tNA\tNA\tNA\tNA"


class ParseLines(unittest.TestCase):
    def test_a_full_row(self):
        item = recommended.parse_lines(REAL)[0]
        self.assertEqual(
            (item.ext_id, item.title, item.channel_name, item.channel_ext_id,
             item.duration_s, item.thumbnail_url),
            ("aaaaaaaaaaa", "A real video", "Some channel", "UCabcdefghijklmnopqrstuv",
             5646, "https://i/x.jpg"))

    def test_the_counts_and_the_date_come_along(self):
        # The date is approximate. A listing gives the age of a video as a
        # phrase, so this is that phrase turned into a time, which is the same
        # thing other clients show.
        item = recommended.parse_lines(REAL)[0]
        self.assertEqual((item.views, item.published_at), (7600516, 1600000000))

    def test_a_row_without_them_is_still_a_row(self):
        item = recommended.parse_lines("aaaaaaaaaaa\tTitle\tName\tNA\tNA\tNA\tNA\tNA")[0]
        self.assertEqual((item.views, item.published_at), (None, None))

    def test_radio_rows_are_dropped(self):
        self.assertEqual([i.ext_id for i in recommended.parse_lines(f"{RADIO}\n{REAL}")],
                         ["aaaaaaaaaaa"])

    def test_duplicates_are_collapsed(self):
        self.assertEqual(len(recommended.parse_lines(f"{REAL}\n{REAL}")), 1)

    def test_a_row_with_no_title_is_not_shown(self):
        self.assertEqual(recommended.parse_lines("aaaaaaaaaaa\t\tx\tNA\tNA\tNA"), [])

    def test_missing_fields_become_none_rather_than_the_word(self):
        item = recommended.parse_lines("aaaaaaaaaaa\tTitle\tNA\tNA\tNA\tNA")[0]
        self.assertEqual((item.channel_name, item.channel_ext_id, item.duration_s,
                          item.thumbnail_url), (None, None, None, None))

    def test_a_channel_id_that_is_not_one_is_dropped(self):
        item = recommended.parse_lines("aaaaaaaaaaa\tTitle\tName\tnotanid\t10\tt")[0]
        self.assertIsNone(item.channel_ext_id)

    def test_a_title_containing_a_pipe_survives(self):
        # Tab separated for exactly this reason.
        item = recommended.parse_lines("aaaaaaaaaaa\tA | B\tName\tNA\tNA\tNA")[0]
        self.assertEqual(item.title, "A | B")

    def test_nothing_at_all(self):
        self.assertEqual(recommended.parse_lines(""), [])


if __name__ == "__main__":
    unittest.main()


class StreamsInTheseLists(unittest.TestCase):
    """A stream is a listing like any other here.

    A suggestion or a search result can be a channel that is live now or a
    premiere that has been announced, and the flat listing says which without
    a second request. Reading it is what lets the card badge them the way a
    feed row is badged, and what lets the play path refuse one that has not
    begun.
    """

    LIVE = ("bbbbbbbbbbb\tOn air now\tSome channel\tUCabcdefghijklmnopqrstuv\tNA"
            "\thttps://i/x.jpg\t1200\tNA\tis_live\tNA")
    SOON = ("ccccccccccc\tStarting later\tSome channel\tUCabcdefghijklmnopqrstuv\tNA"
            "\thttps://i/x.jpg\tNA\tNA\tis_upcoming\t1800000000")

    def test_a_stream_that_is_on_says_so(self):
        item = recommended.parse_lines(self.LIVE)[0]
        self.assertEqual(item.live_status, "is_live")
        self.assertIsNone(item.scheduled_at)

    def test_an_announced_stream_carries_when_it_begins(self):
        item = recommended.parse_lines(self.SOON)[0]
        self.assertEqual((item.live_status, item.scheduled_at),
                         ("is_upcoming", 1800000000))

    def test_an_ordinary_video_answers_neither(self):
        # Measured: yt-dlp says NA rather than not_live for these.
        item = recommended.parse_lines(REAL)[0]
        self.assertIsNone(item.live_status)
        self.assertIsNone(item.scheduled_at)

    def test_the_row_handed_on_carries_both(self):
        from weave.sources import flatlist

        row = flatlist.as_row(recommended.parse_lines(self.SOON)[0])
        self.assertEqual((row["live_status"], row["scheduled_at"]),
                         ("is_upcoming", 1800000000))
