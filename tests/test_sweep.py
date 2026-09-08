import unittest

from weave.sources import sweep


class ParseLines(unittest.TestCase):
    def test_full_row(self):
        got = sweep.parse_lines("aaaaaaaaaaa|487|NA")
        self.assertEqual((got[0].ext_id, got[0].duration_s, got[0].live_status),
                         ("aaaaaaaaaaa", 487, None))

    def test_live_row(self):
        got = sweep.parse_lines("aaaaaaaaaaa|NA|is_live")
        self.assertIsNone(got[0].duration_s)
        self.assertEqual(got[0].live_status, "is_live")

    def test_na_duration_is_none_not_zero(self):
        # Zero would read as a known duration and break the Shorts threshold.
        self.assertIsNone(sweep.parse_lines("aaaaaaaaaaa|NA|NA")[0].duration_s)

    def test_float_duration_is_truncated(self):
        self.assertEqual(sweep.parse_lines("aaaaaaaaaaa|487.8|NA")[0].duration_s, 487)

    def test_radio_playlist_rows_are_dropped(self):
        # The feed mixes these in with every field empty.
        text = "RDabcdefghijk|NA|NA\naaaaaaaaaaa|100|NA\n"
        self.assertEqual([v.ext_id for v in sweep.parse_lines(text)], ["aaaaaaaaaaa"])

    def test_short_lines_are_ignored(self):
        self.assertEqual(sweep.parse_lines("aaaaaaaaaaa|100\nbroken\n"), [])

    def test_duplicates_are_collapsed(self):
        self.assertEqual(len(sweep.parse_lines("aaaaaaaaaaa|1|NA\naaaaaaaaaaa|2|NA\n")), 1)

    def test_key(self):
        self.assertEqual(sweep.parse_lines("aaaaaaaaaaa|1|NA")[0].key, "yt:aaaaaaaaaaa")

    def test_the_view_count_comes_along_and_na_is_none(self):
        rows = sweep.parse_lines("aaaaaaaaaaa|300|NA|UC1|NA|4400\nbbbbbbbbbbb|NA|is_live|UC1|NA|NA")
        self.assertEqual([r.views for r in rows], [4400, None])

    def test_the_owning_channel_comes_along(self):
        # This is what makes one call over every subscription a detector as
        # well as a filler. Without it a new video says that something is new
        # but not whose feed to ask.
        got = sweep.parse_lines("aaaaaaaaaaa|100|NA|UCabcdefghijklmnopqrstuv")
        self.assertEqual(got[0].channel_id, "UCabcdefghijklmnopqrstuv")

    def test_a_row_without_a_channel_still_carries_its_duration(self):
        self.assertEqual(sweep.parse_lines("aaaaaaaaaaa|100|NA")[0].channel_id, None)
        self.assertEqual(sweep.parse_lines("aaaaaaaaaaa|100|NA|NA")[0].channel_id, None)

    def test_an_announced_stream_carries_its_start_time(self):
        # A stream that has not begun reports no duration but does report
        # when it is due, which is the only way to tell it apart from a
        # video RSS found that no sweep has reached yet.
        got = sweep.parse_lines(
            "aaaaaaaaaaa|NA|is_upcoming|UCabcdefghijklmnopqrstuv|1900000000")
        self.assertEqual(got[0].live_status, "is_upcoming")
        self.assertIsNone(got[0].duration_s)
        self.assertEqual(got[0].scheduled_at, 1900000000)

    def test_a_row_with_no_start_time_carries_none(self):
        self.assertIsNone(sweep.parse_lines("aaaaaaaaaaa|100|NA|NA|NA")[0].scheduled_at)
        self.assertIsNone(sweep.parse_lines("aaaaaaaaaaa|100|NA")[0].scheduled_at)


if __name__ == "__main__":
    unittest.main()
