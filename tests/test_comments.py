"""Comment grouping and dislike parsing. No network."""

import unittest

from weave.sources import comments, dislikes

RAW = {"comments": [
    {"id": "a", "parent": "root", "author": "Alpha", "text": "first",
     "like_count": 500, "_time_text": "1 day ago", "is_pinned": True,
     "author_thumbnail": "https://x/a.jpg", "author_is_verified": True},
    {"id": "b", "parent": "a", "author": "Beta", "text": "a reply", "like_count": 3},
    {"id": "c", "parent": "a", "author": "Gamma", "text": "another reply"},
    {"id": "d", "parent": "root", "author": "Delta", "text": "second"},
    {"id": "e", "parent": "gone", "author": "Epsilon", "text": "orphan"},
    "not a dictionary",
]}


class Grouping(unittest.TestCase):
    def setUp(self):
        self.threads = comments.parse(RAW)

    def test_only_top_level_comments_are_threads(self):
        self.assertEqual([t.author for t in self.threads], ["Alpha", "Delta"])

    def test_replies_hang_off_their_parent(self):
        self.assertEqual([r.author for r in self.threads[0].replies], ["Beta", "Gamma"])
        self.assertEqual(self.threads[1].replies, [])

    def test_a_reply_to_something_missing_is_dropped(self):
        # Rather than raising or becoming a thread of its own.
        everyone = [t.author for t in self.threads]
        everyone += [r.author for t in self.threads for r in t.replies]
        self.assertNotIn("Epsilon", everyone)

    def test_rubbish_in_the_list_is_skipped(self):
        self.assertEqual(len(self.threads), 2)

    def test_the_order_it_arrived_in_is_kept(self):
        # It is YouTube's own top comment order, which puts a pinned comment
        # first and is not a sort by likes, so it must not be reordered here.
        self.assertEqual(self.threads[0].author, "Alpha")

    def test_fields(self):
        first = self.threads[0]
        self.assertEqual((first.likes, first.when, first.pinned, first.verified),
                         (500, "1 day ago", True, True))
        self.assertEqual(first.avatar_url, "https://x/a.jpg")

    def test_missing_fields_become_empty_rather_than_missing(self):
        second = self.threads[1]
        self.assertEqual((second.likes, second.when, second.pinned), (0, "", False))

    def test_an_empty_response(self):
        self.assertEqual(comments.parse({}), [])
        self.assertEqual(comments.parse({"comments": []}), [])


class Votes(unittest.TestCase):
    def test_reads_the_counts(self):
        got = dislikes.parse({"likes": 19369750, "dislikes": 518289, "viewCount": 1811113398})
        self.assertEqual((got.likes, got.dislikes, got.views), (19369750, 518289, 1811113398))

    def test_missing_numbers_stay_missing(self):
        # None rather than zero, so the panel can leave the field out instead
        # of claiming a video has no dislikes.
        got = dislikes.parse({})
        self.assertEqual((got.likes, got.dislikes, got.views), (None, None, None))

    def test_rubbish_values_are_ignored(self):
        got = dislikes.parse({"likes": "many", "dislikes": None})
        self.assertIsNone(got.likes)
        self.assertIsNone(got.dislikes)


class VideoDetails(unittest.TestCase):
    """The metadata the same call writes.

    The cheap listing modes carry no like count and no publish date at all,
    measured, so this file is the only place they come from for a video that is
    not in the feed, and it costs no extra request.
    """

    def test_the_numbers_come_across(self):
        found = comments.parse_details({"view_count": 7600516, "like_count": 1234,
                                        "timestamp": 1600000000, "duration": 662})
        self.assertEqual((found.views, found.likes, found.published_at, found.duration_s),
                         (7600516, 1234, 1600000000, 662))

    def test_a_date_with_no_time_is_better_than_nothing(self):
        # What the metadata carries when the exact moment is missing.
        found = comments.parse_details({"upload_date": "20200102"})
        self.assertIsNotNone(found.published_at)

    def test_a_release_time_stands_in_for_a_publish_time(self):
        found = comments.parse_details({"release_timestamp": 1600000000})
        self.assertEqual(found.published_at, 1600000000)

    def test_nothing_at_all_is_not_an_error(self):
        found = comments.parse_details({})
        self.assertEqual((found.views, found.likes, found.published_at), (None, None, None))

    def test_a_number_that_is_not_one_is_dropped(self):
        self.assertIsNone(comments.parse_details({"like_count": "lots"}).likes)


if __name__ == "__main__":
    unittest.main()
