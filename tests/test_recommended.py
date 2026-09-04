"""Parsing what YouTube suggests.

The list is not all videos. It mixes in radio playlist rows whose id is
thirteen characters and whose every other field is NA, measured, and reading
one of those as a video would put a row in the grid that cannot be played.
"""

import unittest

from weave.sources import recommended

REAL = "aaaaaaaaaaa\tA real video\tSome channel\tUCabcdefghijklmnopqrstuv\t5646\thttps://i/x.jpg"
RADIO = "RDor6VC0FkOOw\tNA\tNA\tNA\tNA\tNA"


class ParseLines(unittest.TestCase):
    def test_a_full_row(self):
        item = recommended.parse_lines(REAL)[0]
        self.assertEqual(
            (item.ext_id, item.title, item.channel_name, item.channel_ext_id,
             item.duration_s, item.thumbnail_url),
            ("aaaaaaaaaaa", "A real video", "Some channel", "UCabcdefghijklmnopqrstuv",
             5646, "https://i/x.jpg"))

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
