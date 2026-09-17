"""Taking a video out of sight, and getting it back.

A card can spoil something, or simply be unpleasant to keep meeting, and the
answer to that is to stop drawing it. Hidden is not deleted: the video keeps
its place in a box that was built by hand, keeps its watched mark, and the
settings page offers every one of them back.

Which lists it leaves is the whole of what this pins down. A box is the one
that keeps it, deliberately, since a box was picked video by video and quietly
dropping one out of a hand built list is a different act from tidying a feed.
"""

import unittest

from tests.support import scratch_db
from weave.db import VideoRow


class LeavingTheLists(unittest.TestCase):
    def setUp(self):
        self.db = scratch_db(self)
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.upsert_videos([
            VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "A spoiler",
                     published_at=1_700_000_002, duration_s=300),
            VideoRow("youtube", "bbbbbbbbbbb", "yt:UC1", "Something else",
                     published_at=1_700_000_001, duration_s=300),
        ])

    def keys(self, **kwargs):
        return [row["key"] for row in self.db.feed(**kwargs)]

    def test_it_leaves_the_feed(self):
        self.assertIn("yt:aaaaaaaaaaa", self.keys())
        self.db.hide_video("yt:aaaaaaaaaaa", "A spoiler")
        self.assertEqual(self.keys(), ["yt:bbbbbbbbbbb"])

    def test_and_comes_back(self):
        self.db.hide_video("yt:aaaaaaaaaaa", "A spoiler")
        self.assertTrue(self.db.unhide_video("yt:aaaaaaaaaaa"))
        self.assertIn("yt:aaaaaaaaaaa", self.keys())

    def test_bringing_back_one_that_is_not_hidden_says_so(self):
        self.assertFalse(self.db.unhide_video("yt:aaaaaaaaaaa"))

    def test_it_leaves_a_group(self):
        group = self.db.create_group("Some group")
        self.db.add_to_group(group, "yt:UC1")
        self.db.hide_video("yt:aaaaaaaaaaa", "A spoiler")
        self.assertEqual(self.keys(group_id=group), ["yt:bbbbbbbbbbb"])

    def test_it_leaves_a_channel_page(self):
        self.db.hide_video("yt:aaaaaaaaaaa", "A spoiler")
        self.assertEqual(self.keys(channel_key="yt:UC1"), ["yt:bbbbbbbbbbb"])

    def test_but_a_box_keeps_it(self):
        """A box was picked video by video, so what is in one stays in it."""
        box = self.db.create_box("Later")
        self.db.add_to_box(box, "yt:aaaaaaaaaaa")
        self.db.hide_video("yt:aaaaaaaaaaa", "A spoiler")
        self.assertEqual(self.keys(box_id=box), ["yt:aaaaaaaaaaa"])

    def test_and_the_watched_mark_survives(self):
        self.db.mark_watched_many(["yt:aaaaaaaaaaa"], "manual")
        self.db.hide_video("yt:aaaaaaaaaaa", "A spoiler")
        self.db.unhide_video("yt:aaaaaaaaaaa")
        self.assertEqual([row["watched"] for row in self.db.feed(hide_watched=False)
                          if row["key"] == "yt:aaaaaaaaaaa"], [1])

    def test_it_stops_being_counted(self):
        before = self.db.unwatched_total()
        self.db.hide_video("yt:aaaaaaaaaaa", "A spoiler")
        self.assertEqual(self.db.unwatched_total(), before - 1)

    def test_a_group_stops_counting_it_too(self):
        group = self.db.create_group("Some group")
        self.db.add_to_group(group, "yt:UC1")
        before = next(row["unwatched"] for row in self.db.groups() if row["id"] == group)
        self.db.hide_video("yt:aaaaaaaaaaa", "A spoiler")
        after = next(row["unwatched"] for row in self.db.groups() if row["id"] == group)
        self.assertEqual(after, before - 1)

    def test_the_channel_stops_counting_it(self):
        before = self.db.channel("yt:UC1")["video_count"]
        self.db.hide_video("yt:aaaaaaaaaaa", "A spoiler")
        self.assertEqual(self.db.channel("yt:UC1")["video_count"], before - 1)


class SuggestionsAndSearches(unittest.TestCase):
    """A suggestion or a search result is not a video this database holds.

    It belongs to a channel nobody follows, so there is no row in videos to
    mark and nothing there to name it by. That is why what is hidden is kept
    with its own title and picture.
    """

    def setUp(self):
        self.db = scratch_db(self)
        self.db.replace_cached(self.db.RECOMMENDED, [
            {"ext_id": "ccccccccccc", "title": "A suggestion",
             "channel_name": "Somebody", "channel_ext_id": "UC" + "s" * 22},
            {"ext_id": "ddddddddddd", "title": "Another",
             "channel_name": "Somebody", "channel_ext_id": "UC" + "s" * 22},
        ])

    def test_a_suggestion_can_be_hidden(self):
        self.db.hide_video("yt:ccccccccccc", "A suggestion", "https://i/x.jpg")
        self.assertEqual([row["key"] for row in self.db.cached(self.db.RECOMMENDED)],
                         ["yt:ddddddddddd"])

    def test_a_search_result_is_left_out_of_what_is_drawn(self):
        rows = [{"ext_id": "ccccccccccc", "title": "A suggestion"},
                {"ext_id": "ddddddddddd", "title": "Another"}]
        self.db.hide_video("yt:ccccccccccc", "A suggestion")
        self.assertEqual([row["key"] for row in self.db.decorate(rows)],
                         ["yt:ddddddddddd"])

    def test_what_it_was_is_remembered_for_the_page_that_offers_it_back(self):
        self.db.hide_video("yt:ccccccccccc", "A suggestion", "https://i/x.jpg")
        held = self.db.hidden_videos()
        self.assertEqual([(row["key"], row["title"], row["thumbnail_url"]) for row in held],
                         [("yt:ccccccccccc", "A suggestion", "https://i/x.jpg")])

    def test_a_video_that_is_stored_is_named_from_the_row_that_is_kept_fresh(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.upsert_videos([VideoRow("youtube", "eeeeeeeeeee", "yt:UC1", "The real title")])
        self.db.hide_video("yt:eeeeeeeeeee", "A title from a listing")
        held = self.db.hidden_videos()[0]
        self.assertEqual((held["title"], held["channel_title"]), ("The real title", "One"))

    def test_the_newest_hidden_is_first(self):
        self.db.hide_video("yt:ccccccccccc", "A suggestion")
        self.db.hide_video("yt:ddddddddddd", "Another")
        keys = [row["key"] for row in self.db.hidden_videos()]
        self.assertEqual(keys[0], "yt:ddddddddddd")

    def test_all_of_them_at_once(self):
        self.db.hide_video("yt:ccccccccccc", "A suggestion")
        self.db.hide_video("yt:ddddddddddd", "Another")
        self.assertEqual(self.db.hidden_count(), 2)
        self.assertEqual(self.db.unhide_all(), 2)
        self.assertEqual(self.db.hidden_count(), 0)


if __name__ == "__main__":
    unittest.main()
