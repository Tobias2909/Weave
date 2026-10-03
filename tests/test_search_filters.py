"""YouTube's own search filters, and what is done here where YouTube falls short.

The codes below were read off the live results page on 2026-10-01: each one
was asked for and the answer checked for the age, the length or the order it
promises. Sorting by upload date is not among them because YouTube ignores it
now, which is why newest first is sorted here over what has been loaded.
"""

import unittest

from weave.sources.search import Filters, address
from weave.ui.bridge import Bridge

from . import support

NOW = 1_800_000_000


def flat(ext_id, age_s=3600, length_s=300, views=10):
    return {"ext_id": ext_id, "title": "A result", "channel_name": "A stranger",
            "channel_ext_id": "UC" + "s" * 22, "duration_s": length_s,
            "thumbnail_url": "https://i/x.jpg", "views": views,
            "published_at": NOW - age_s, "live_status": None, "scheduled_at": None}


class WhatYouTubeIsAskedFor(unittest.TestCase):
    def test_nothing_is_nothing(self):
        self.assertEqual(Filters().sp(), "")

    def test_the_codes_that_were_measured(self):
        self.assertEqual(Filters(sort="views").sp(), "CAM=")
        self.assertEqual(Filters(when="hour").sp(), "EgIIAQ==")
        self.assertEqual(Filters(when="today").sp(), "EgIIAg==")
        self.assertEqual(Filters(when="week").sp(), "EgIIAw==")
        self.assertEqual(Filters(when="month").sp(), "EgIIBA==")
        self.assertEqual(Filters(when="year").sp(), "EgIIBQ==")
        self.assertEqual(Filters(length="short").sp(), "EgIYAQ==")
        self.assertEqual(Filters(length="medium").sp(), "EgIYAw==")
        self.assertEqual(Filters(length="long").sp(), "EgIYAg==")

    def test_and_how_they_combine(self):
        self.assertEqual(Filters(when="week", length="long").sp(), "EgQIAxgC")
        self.assertEqual(Filters(sort="views", length="long").sp(), "CAMSAhgC")
        self.assertEqual(Filters(sort="views", when="week").sp(), "CAMSAggD")

    def test_newest_first_asks_youtube_for_nothing(self):
        self.assertEqual(Filters(sort="newest").sp(), "")

    def test_the_address_carries_the_words_and_the_code(self):
        self.assertEqual(
            address("lofi & rain", Filters(sort="views")),
            "https://www.youtube.com/results?search_query=lofi+%26+rain&sp=CAM%3D")


class WhatDoesNotBelong(unittest.TestCase):
    """A filtered page also carries rows from YouTube's own shelves, which no
    filter touches. Those are told apart by their age and their length."""

    def test_a_row_too_old_for_the_window(self):
        self.assertFalse(Filters(when="week").keeps(flat("a", age_s=8 * 86400), NOW))
        self.assertTrue(Filters(when="week").keeps(flat("a", age_s=6 * 86400), NOW))

    def test_a_day_ago_is_not_today(self):
        self.assertFalse(Filters(when="today").keeps(flat("a", age_s=86400), NOW))
        self.assertTrue(Filters(when="today").keeps(flat("a", age_s=23 * 3600), NOW))

    def test_a_row_of_the_wrong_length(self):
        self.assertFalse(Filters(length="short").keeps(flat("a", length_s=7170), NOW))
        self.assertTrue(Filters(length="short").keeps(flat("a", length_s=239), NOW))
        self.assertFalse(Filters(length="long").keeps(flat("a", length_s=600), NOW))
        self.assertTrue(Filters(length="medium").keeps(flat("a", length_s=600), NOW))

    def test_a_row_that_does_not_say_is_kept(self):
        row = flat("a")
        row["published_at"] = None
        row["duration_s"] = None
        self.assertTrue(Filters(when="hour", length="long").keeps(row, NOW))


class TheWindow(unittest.TestCase):
    def setUp(self):
        self.db = support.scratch_db(self)
        bridge = Bridge.__new__(Bridge)
        bridge._db = self.db
        bridge._search_text = "cats"
        bridge._view_kind = "search"
        bridge._web_results = []
        bridge._exhausted = False
        bridge._loading_more = False
        bridge._search_filters = Filters()
        bridge._search_next = 1
        bridge._set_status = lambda *_a, **_k: None
        bridge._set_notice = lambda *_a, **_k: None
        bridge.reload = lambda: None
        self.bridge = bridge

    def keys(self):
        return [row["ext_id"] for row in self.bridge._web_results]

    def test_rows_that_do_not_belong_are_left_out(self):
        self.bridge._search_filters = Filters(length="long")
        Bridge._on_web_results(self.bridge, "cats", 1,
                               [flat("aaaaaaaaaaa", length_s=83), flat("bbbbbbbbbbb", length_s=3000)])
        self.assertEqual(self.keys(), ["bbbbbbbbbbb"])

    def test_the_next_page_starts_after_what_youtube_sent(self):
        self.bridge._search_filters = Filters(length="long")
        Bridge._on_web_results(self.bridge, "cats", 1,
                               [flat("aaaaaaaaaaa", length_s=83), flat("bbbbbbbbbbb", length_s=3000)])
        self.assertEqual(self.bridge._search_next, 3)

    def test_a_page_whose_rows_were_all_left_out_is_not_the_end(self):
        self.bridge._search_filters = Filters(length="long")
        Bridge._on_web_results(self.bridge, "cats", 1, [flat("aaaaaaaaaaa", length_s=83)])
        self.assertFalse(self.bridge._exhausted)
        Bridge._on_web_results(self.bridge, "cats", 2, [])
        self.assertTrue(self.bridge._exhausted)

    def test_newest_first_sorts_what_has_loaded(self):
        self.bridge._search_filters = Filters(sort="newest")
        Bridge._on_web_results(self.bridge, "cats", 1,
                               [flat("aaaaaaaaaaa", age_s=9000), flat("bbbbbbbbbbb", age_s=60)])
        Bridge._on_web_results(self.bridge, "cats", 3, [flat("ccccccccccc", age_s=600)])
        self.assertEqual(self.keys(), ["bbbbbbbbbbb", "ccccccccccc", "aaaaaaaaaaa"])

    def test_a_filtered_set_is_kept_apart_from_the_plain_one(self):
        Bridge._on_web_results(self.bridge, "cats", 1, [flat("aaaaaaaaaaa")])
        self.bridge._search_filters = Filters(sort="views")
        Bridge._on_web_results(self.bridge, "cats", 1, [flat("bbbbbbbbbbb")])
        plain = self.db.cached_flat(self.db.search_kind("cats"))
        narrowed = self.db.cached_flat(Bridge._search_kind(self.bridge, "cats"))
        self.assertEqual([row["ext_id"] for row in plain], ["aaaaaaaaaaa"])
        self.assertEqual([row["ext_id"] for row in narrowed], ["bbbbbbbbbbb"])


class ChoosingOne(unittest.TestCase):
    def setUp(self):
        bridge = Bridge.__new__(Bridge)
        bridge._search_filters = Filters()
        bridge._view_kind = "search"
        bridge._search_scope = "youtube"
        bridge.viewChanged = type("Sig", (), {"emit": staticmethod(lambda: None)})()
        bridge.asked = []
        bridge.searchYouTube = lambda: bridge.asked.append(bridge._search_filters)
        self.bridge = bridge

    def test_a_choice_asks_again_with_it(self):
        Bridge.setSearchFilter(self.bridge, "when", "week")
        self.assertEqual(self.bridge.asked, [Filters(when="week")])

    def test_the_others_stay_as_they_were(self):
        Bridge.setSearchFilter(self.bridge, "sort", "views")
        Bridge.setSearchFilter(self.bridge, "length", "long")
        self.assertEqual(self.bridge._search_filters, Filters(sort="views", length="long"))

    def test_something_that_is_not_a_choice_is_refused(self):
        Bridge.setSearchFilter(self.bridge, "when", "decade")
        Bridge.setSearchFilter(self.bridge, "colour", "red")
        self.assertEqual(self.bridge.asked, [])

    def test_the_same_choice_again_asks_nothing(self):
        Bridge.setSearchFilter(self.bridge, "sort", "relevance")
        self.assertEqual(self.bridge.asked, [])


if __name__ == "__main__":
    unittest.main()
