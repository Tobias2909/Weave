"""Real YouTube playlists, as opposed to boxes.

A box is this application's own and lives only in the database. A playlist is
YouTube's. They were deliberately never given the same name, and this is the
module that reads the second kind.
"""

import unittest

from weave.sources import playlists

LIST = "PLabcdef\tHolidays\nLL\tLiked videos\nnotaplaylist\tSomething\n"
ITEM = "aaaaaaaaaaa\tFirst\tSome channel\tUCabcdefghijklmnopqrstuv\t182\thttps://i/x.jpg"


class ParseList(unittest.TestCase):
    def test_playlists_come_back_with_their_names(self):
        found = playlists.parse_list(LIST)
        self.assertEqual([(p.ext_id, p.title) for p in found],
                         [("PLabcdef", "Holidays"), ("LL", "Liked videos")])

    def test_liked_videos_is_a_playlist_like_any_other(self):
        self.assertIn("LL", [p.ext_id for p in playlists.parse_list(LIST)])

    def test_a_row_that_is_not_a_playlist_id_is_dropped(self):
        self.assertNotIn("notaplaylist", [p.ext_id for p in playlists.parse_list(LIST)])

    def test_an_unnamed_row_is_dropped(self):
        self.assertEqual(playlists.parse_list("PLabcdef\tNA"), [])

    def test_duplicates_are_collapsed(self):
        self.assertEqual(len(playlists.parse_list("PLa\tOne\nPLa\tOne\n")), 1)


class ParseItems(unittest.TestCase):
    def test_a_full_item(self):
        item = playlists.parse_items(ITEM)[0]
        self.assertEqual(
            (item.ext_id, item.title, item.channel_name, item.channel_ext_id,
             item.duration_s, item.thumbnail_url),
            ("aaaaaaaaaaa", "First", "Some channel", "UCabcdefghijklmnopqrstuv",
             182, "https://i/x.jpg"))

    def test_a_deleted_entry_is_dropped(self):
        # A playlist keeps rows for videos that are gone, and those come back
        # with no title at all.
        self.assertEqual(playlists.parse_items("aaaaaaaaaaa\tNA\tNA\tNA\tNA\tNA"), [])

    def test_the_order_is_kept(self):
        text = "bbbbbbbbbbb\tSecond\tx\tNA\tNA\tNA\n" + ITEM
        self.assertEqual([i.ext_id for i in playlists.parse_items(text)],
                         ["bbbbbbbbbbb", "aaaaaaaaaaa"])

    def test_a_title_with_a_pipe_survives(self):
        item = playlists.parse_items("aaaaaaaaaaa\tA | B\tx\tNA\tNA\tNA")[0]
        self.assertEqual(item.title, "A | B")


if __name__ == "__main__":
    unittest.main()
