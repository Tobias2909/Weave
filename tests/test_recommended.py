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


class AStreamInASuggestionThatHasEnded(unittest.TestCase):
    """A suggestion says live from the moment it was read, and goes on saying
    it until the whole list is read again.

    A suggestion is usually a channel nobody follows, so the video is not in
    `videos` at all and there is nothing there to correct. Where both do have a
    word for it the listing's own wins, since it came from the same reading as
    the rest of the row. So finding out that a broadcast has ended has to be
    said on the cached row as well, or the card goes on saying live however
    many times the answer comes back.
    """

    def setUp(self):
        from tests.support import scratch_db

        self.db = scratch_db(self)
        self.db.replace_cached(self.db.RECOMMENDED, [
            {"ext_id": "bbbbbbbbbbb", "title": "On air now",
             "channel_name": "Some channel", "channel_ext_id": "UCabcdefghijklmnopqrstuv",
             "live_status": "is_live"},
            {"ext_id": "ccccccccccc", "title": "Starting later",
             "channel_name": "Some channel", "channel_ext_id": "UCabcdefghijklmnopqrstuv",
             "live_status": "is_upcoming", "scheduled_at": 1_800_000_000},
            {"ext_id": "ddddddddddd", "title": "An ordinary video",
             "channel_name": "Some channel", "channel_ext_id": "UCabcdefghijklmnopqrstuv"},
        ])

    def states(self):
        return {row["ext_id"]: row["live_status"]
                for row in self.db.cached(self.db.RECOMMENDED)}

    def test_the_suggestion_stops_saying_live(self):
        self.assertEqual(self.states()["bbbbbbbbbbb"], "is_live")
        self.db.set_live_state("yt:bbbbbbbbbbb", None, False)
        self.assertEqual(self.states()["bbbbbbbbbbb"], "was_live")

    def test_one_that_has_not_begun_is_left_alone(self):
        """A different question, and this is not the answer to it."""
        self.db.set_live_state("yt:ccccccccccc", None, False)
        self.assertEqual(self.states()["ccccccccccc"], "is_upcoming")

    def test_an_ordinary_video_is_not_given_a_state_it_never_had(self):
        self.db.set_live_state("yt:ddddddddddd", None, False)
        self.assertIsNone(self.states()["ddddddddddd"])

    def test_a_stream_that_is_still_on_changes_nothing(self):
        self.db.set_live_state("yt:bbbbbbbbbbb", 51, True)
        self.assertEqual(self.states()["bbbbbbbbbbb"], "is_live")
