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



# What a real playlist entry looks like once YouTube itself will not resolve
# it, measured against a real account rather than assumed: a valid id, the
# placeholder text as the whole title, and every other field NA.
PRIVATE = "j9ziXYpFs1I\t[Private video]\tNA\tNA\tNA\thttps://i.ytimg.com/img/no_thumbnail.jpg\tNA\tNA"
DELETED = "Yb8eYa_pHaA\t[Deleted video]\tNA\tNA\tNA\thttps://i.ytimg.com/img/no_thumbnail.jpg\tNA\tNA"


class ParseItems(unittest.TestCase):
    def test_a_full_item(self):
        items, skipped = playlists.parse_items(ITEM)
        item = items[0]
        self.assertEqual(
            (item.ext_id, item.title, item.channel_name, item.channel_ext_id,
             item.duration_s, item.thumbnail_url),
            ("aaaaaaaaaaa", "First", "Some channel", "UCabcdefghijklmnopqrstuv",
             182, "https://i/x.jpg"))
        self.assertEqual(skipped, 0)

    def test_a_row_with_no_title_is_dropped(self):
        # Distinct from a private or a deleted entry, which do carry a title,
        # just not a usable one. A row can still come back with nothing at
        # all in that field, and this is not counted as skipped, since there
        # is no id-with-a-real-video behind it to have skipped.
        items, skipped = playlists.parse_items("aaaaaaaaaaa\tNA\tNA\tNA\tNA\tNA")
        self.assertEqual(items, [])
        self.assertEqual(skipped, 0)

    def test_the_order_is_kept(self):
        text = "bbbbbbbbbbb\tSecond\tx\tNA\tNA\tNA\n" + ITEM
        items, _ = playlists.parse_items(text)
        self.assertEqual([i.ext_id for i in items], ["bbbbbbbbbbb", "aaaaaaaaaaa"])

    def test_a_title_with_a_pipe_survives(self):
        items, _ = playlists.parse_items("aaaaaaaaaaa\tA | B\tx\tNA\tNA\tNA")
        self.assertEqual(items[0].title, "A | B")

    def test_a_private_entry_is_dropped_and_counted(self):
        items, skipped = playlists.parse_items(PRIVATE)
        self.assertEqual(items, [])
        self.assertEqual(skipped, 1)

    def test_a_deleted_entry_is_dropped_and_counted(self):
        items, skipped = playlists.parse_items(DELETED)
        self.assertEqual(items, [])
        self.assertEqual(skipped, 1)

    def test_real_entries_survive_alongside_unavailable_ones(self):
        # This is the case that matters: a mixed playlist keeps every video it
        # can actually show, and only counts the rest.
        text = "\n".join([ITEM, PRIVATE, DELETED])
        items, skipped = playlists.parse_items(text)
        self.assertEqual([i.ext_id for i in items], ["aaaaaaaaaaa"])
        self.assertEqual(skipped, 2)

    def test_a_playlist_with_nothing_unavailable_reports_no_skips(self):
        _, skipped = playlists.parse_items(ITEM)
        self.assertEqual(skipped, 0)


if __name__ == "__main__":
    unittest.main()
