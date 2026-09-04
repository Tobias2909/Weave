"""Reading the watch history.

The history YouTube keeps is the whole of it, since mpv tells YouTube when it
plays something, so there is nothing to be gained from keeping a second and
poorer list here.

What a row carries is thinner than it looks. Measured against the live
endpoint, it has an id, a title, a duration and a thumbnail, and says nothing
at all about the channel.
"""

import unittest

from weave.sources import history

# A real row's shape. The two empty looking fields are the channel name and the
# channel id, which the history never fills in.
ROW = "aaaaaaaaaaa\tA video\tNA\tNA\t186\thttps://i/x.jpg\tNA"


class ParseLines(unittest.TestCase):
    def test_an_entry_keeps_what_the_history_does_carry(self):
        item = history.parse_lines(ROW)[0]
        self.assertEqual((item.ext_id, item.title, item.duration_s, item.thumbnail_url),
                         ("aaaaaaaaaaa", "A video", 186, "https://i/x.jpg"))

    def test_and_has_no_channel_to_carry(self):
        item = history.parse_lines(ROW)[0]
        self.assertEqual((item.channel_name, item.channel_ext_id), (None, None))

    def test_the_order_watched_is_kept(self):
        text = f"{ROW}\nbbbbbbbbbbb\tAnother\tNA\tNA\tNA\tNA\tNA"
        self.assertEqual([i.ext_id for i in history.parse_lines(text)],
                         ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_watching_something_twice_is_one_entry(self):
        self.assertEqual(len(history.parse_lines(f"{ROW}\n{ROW}")), 1)

    def test_rows_that_are_not_videos_are_dropped(self):
        text = "RDabcdefghijk\tNA\tNA\tNA\tNA\tNA\tNA\n" + ROW
        self.assertEqual([i.ext_id for i in history.parse_lines(text)], ["aaaaaaaaaaa"])

    def test_keys_for_marking_what_is_stored(self):
        self.assertEqual(history.keys_of(history.parse_lines(ROW)), ["yt:aaaaaaaaaaa"])

    def test_nothing_at_all(self):
        self.assertEqual(history.parse_lines(""), [])


if __name__ == "__main__":
    unittest.main()
