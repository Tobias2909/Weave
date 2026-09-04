"""Reading the watch history.

The list is thinner than it looks. Measured, a history row carries an id and a
duration and no channel at all, so nothing here can place a video the database
has never seen.
"""

import unittest

from weave.sources import history


class ParseLines(unittest.TestCase):
    def test_ids_become_keys_in_the_order_watched(self):
        self.assertEqual(history.parse_lines("aaaaaaaaaaa\nbbbbbbbbbbb\n"),
                         ["yt:aaaaaaaaaaa", "yt:bbbbbbbbbbb"])

    def test_duplicates_are_collapsed(self):
        # Watching something twice is one entry here, not two.
        self.assertEqual(history.parse_lines("aaaaaaaaaaa\naaaaaaaaaaa\n"),
                         ["yt:aaaaaaaaaaa"])

    def test_rows_that_are_not_videos_are_dropped(self):
        self.assertEqual(history.parse_lines("RDor6VC0FkOOw\naaaaaaaaaaa\n"),
                         ["yt:aaaaaaaaaaa"])

    def test_a_wider_row_still_yields_its_id(self):
        self.assertEqual(history.parse_lines("aaaaaaaaaaa|4948"), ["yt:aaaaaaaaaaa"])

    def test_nothing_at_all(self):
        self.assertEqual(history.parse_lines(""), [])


if __name__ == "__main__":
    unittest.main()
