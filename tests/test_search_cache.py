"""A search of YouTube, kept.

Searching for the same words twice used to cost a request every time, and
every page scrolled cost another. They cost one request now for most of a day,
and an older set is still drawn at once while a fresh one arrives, so the page
is never empty while it waits.

Kept as the rows the source handed over and shaped by the same call that
shapes a fresh page, or a set from here and a set from YouTube would draw
differently, which is exactly the kind of difference nobody notices until a
card is missing something.
"""

import time
import unittest

from PySide6.QtCore import QCoreApplication

from weave.ui.bridge import SEARCH_KEEP_S, SEARCH_TRUST_S, Bridge

from . import support

_app = QCoreApplication.instance() or QCoreApplication([])

STRANGER = "UCaaaaaaaaaaaaaaaaaaaaaa"


def flat(ext_id, title="A result"):
    return {"ext_id": ext_id, "title": title, "channel_name": "A stranger",
            "channel_ext_id": STRANGER, "duration_s": 300,
            "thumbnail_url": "https://i/x.jpg", "views": 12,
            "published_at": 1600000000, "live_status": None, "scheduled_at": None}


class TheKey(unittest.TestCase):
    def setUp(self):
        self.db = support.scratch_db(self)

    def test_the_same_words_are_the_same_key(self):
        self.assertEqual(self.db.search_kind("Two Words"), self.db.search_kind("two words"))

    def test_spacing_does_not_make_a_new_one(self):
        self.assertEqual(self.db.search_kind("  two   words "),
                         self.db.search_kind("two words"))

    def test_different_words_are_a_different_key(self):
        self.assertNotEqual(self.db.search_kind("cats"), self.db.search_kind("dogs"))

    def test_a_search_is_not_the_suggestions(self):
        self.assertNotIn(self.db.search_kind("cats"), (self.db.RECOMMENDED, self.db.HISTORY))


class WhatIsKept(unittest.TestCase):
    def setUp(self):
        self.db = support.scratch_db(self)
        self.kind = self.db.search_kind("cats")

    def test_the_rows_come_back_as_they_went_in(self):
        self.db.replace_cached(self.kind, [flat("aaaaaaaaaaa"), flat("bbbbbbbbbbb")])
        stored = self.db.cached_flat(self.kind)
        self.assertEqual([row["ext_id"] for row in stored], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        self.assertEqual(stored[0]["channel_ext_id"], STRANGER)

    def test_and_in_the_order_the_answer_had(self):
        self.db.replace_cached(self.kind, [flat("bbbbbbbbbbb"), flat("aaaaaaaaaaa")])
        self.assertEqual([row["ext_id"] for row in self.db.cached_flat(self.kind)],
                         ["bbbbbbbbbbb", "aaaaaaaaaaa"])

    def test_a_later_page_goes_after_the_first(self):
        self.db.replace_cached(self.kind, [flat("aaaaaaaaaaa")])
        self.db.append_cached(self.kind, [flat("bbbbbbbbbbb")])
        self.assertEqual([row["ext_id"] for row in self.db.cached_flat(self.kind)],
                         ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_its_age_comes_from_the_rows(self):
        # There is one kind per set of words, so a stamp per kind would leave
        # a row of state behind for every search ever typed.
        self.db.replace_cached(self.kind, [flat("aaaaaaaaaaa")])
        self.assertIsNone(self.db.get_state(f"{self.kind}_at"))
        self.assertLess(self.db.cached_age_s(self.kind), 5)

    def test_words_never_searched_have_no_age(self):
        self.assertIsNone(self.db.cached_age_s(self.db.search_kind("nothing")))

    def test_the_named_kinds_still_read_their_own_stamp(self):
        self.db.replace_cached(self.db.RECOMMENDED, [flat("aaaaaaaaaaa")])
        self.assertIsNotNone(self.db.get_state(f"{self.db.RECOMMENDED}_at"))
        self.assertLess(self.db.cached_age_s(self.db.RECOMMENDED), 5)

    def test_a_search_nobody_repeated_is_swept_up(self):
        self.db.replace_cached(self.kind, [flat("aaaaaaaaaaa")])
        old = int(time.time()) - SEARCH_KEEP_S - 10
        with self.db.conn as conn:
            conn.execute("UPDATE cached_videos SET seen_at=? WHERE kind=?", (old, self.kind))
        self.assertEqual(self.db.forget_old_searches(SEARCH_KEEP_S), 1)
        self.assertEqual(self.db.cached_flat(self.kind), [])

    def test_a_recent_one_is_left_alone(self):
        self.db.replace_cached(self.kind, [flat("aaaaaaaaaaa")])
        self.db.forget_old_searches(SEARCH_KEEP_S)
        self.assertEqual(len(self.db.cached_flat(self.kind)), 1)

    def test_the_sweep_never_touches_the_suggestions_or_the_history(self):
        for kind in (self.db.RECOMMENDED, self.db.HISTORY):
            self.db.replace_cached(kind, [flat("aaaaaaaaaaa")])
            with self.db.conn as conn:
                conn.execute("UPDATE cached_videos SET seen_at=1 WHERE kind=?", (kind,))
        self.db.forget_old_searches(SEARCH_KEEP_S)
        self.assertEqual(len(self.db.cached_flat(self.db.RECOMMENDED)), 1)
        self.assertEqual(len(self.db.cached_flat(self.db.HISTORY)), 1)


class WhatTheWindowDoes(unittest.TestCase):
    """searchYouTube on a stubbed bridge, since the decision is the point and
    the rest of the window is not."""

    def setUp(self):
        self.db = support.scratch_db(self)
        bridge = Bridge.__new__(Bridge)
        bridge._db = self.db
        bridge._search_text = "cats"
        bridge._search_scope = "stored"
        bridge._view_kind = "search"
        bridge._view_id = -1
        bridge._web_results = []
        bridge._exhausted = False
        bridge._set_status = lambda *_a, **_k: None
        bridge.reload = lambda: None
        bridge.viewChanged = type("Sig", (), {"emit": staticmethod(lambda: None)})()
        bridge.fetched = []
        bridge._fetch_results = lambda start: bridge.fetched.append(start)
        self.bridge = bridge

    def search(self):
        Bridge.searchYouTube(self.bridge)

    def store(self, age_s=0):
        kind = self.db.search_kind("cats")
        self.db.replace_cached(kind, [flat("aaaaaaaaaaa"), flat("bbbbbbbbbbb")])
        if age_s:
            with self.db.conn as conn:
                conn.execute("UPDATE cached_videos SET seen_at=? WHERE kind=?",
                             (int(time.time()) - age_s, kind))

    def test_words_never_searched_are_asked_about(self):
        self.search()
        self.assertEqual(self.bridge.fetched, [1])
        self.assertEqual(self.bridge._web_results, [])

    def test_the_same_words_again_cost_nothing(self):
        self.store()
        self.search()
        self.assertEqual(self.bridge.fetched, [])
        self.assertEqual([row["ext_id"] for row in self.bridge._web_results],
                         ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_and_the_rows_are_shaped_like_a_fresh_page(self):
        self.store()
        self.search()
        row = self.bridge._web_results[0]
        for field in ("key", "channel_key", "channel_title", "watched", "thumbnail_url"):
            self.assertIn(field, row)
        self.assertEqual(row["key"], "yt:aaaaaaaaaaa")

    def test_an_old_set_is_drawn_at_once_and_asked_about_anyway(self):
        self.store(age_s=SEARCH_TRUST_S + 60)
        self.search()
        self.assertEqual(self.bridge.fetched, [1])
        self.assertEqual(len(self.bridge._web_results), 2)

    def test_other_words_are_not_answered_from_this_set(self):
        self.store()
        self.bridge._search_text = "dogs"
        self.search()
        self.assertEqual(self.bridge.fetched, [1])
        self.assertEqual(self.bridge._web_results, [])

    def test_nothing_typed_asks_nothing(self):
        self.bridge._search_text = ""
        self.search()
        self.assertEqual(self.bridge.fetched, [])


class WhatComesBackIsKept(unittest.TestCase):
    def setUp(self):
        self.db = support.scratch_db(self)
        bridge = Bridge.__new__(Bridge)
        bridge._db = self.db
        bridge._search_text = "cats"
        bridge._view_kind = "search"
        bridge._web_results = []
        bridge._exhausted = False
        bridge._loading_more = False
        bridge._set_status = lambda *_a, **_k: None
        bridge._set_notice = lambda *_a, **_k: None
        bridge.reload = lambda: None
        self.bridge = bridge

    def test_the_first_page_replaces_what_was_there(self):
        Bridge._on_web_results(self.bridge, "cats", 1, [flat("aaaaaaaaaaa")])
        Bridge._on_web_results(self.bridge, "cats", 1, [flat("bbbbbbbbbbb")])
        stored = self.db.cached_flat(self.db.search_kind("cats"))
        self.assertEqual([row["ext_id"] for row in stored], ["bbbbbbbbbbb"])

    def test_a_later_page_is_added_to_it(self):
        Bridge._on_web_results(self.bridge, "cats", 1, [flat("aaaaaaaaaaa")])
        Bridge._on_web_results(self.bridge, "cats", 2, [flat("bbbbbbbbbbb")])
        stored = self.db.cached_flat(self.db.search_kind("cats"))
        self.assertEqual([row["ext_id"] for row in stored],
                         ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_an_answer_to_words_that_moved_on_is_dropped(self):
        # The words changed while the request was in flight, so this set is
        # not what is on screen and must not be stored under the new words.
        Bridge._on_web_results(self.bridge, "dogs", 1, [flat("aaaaaaaaaaa")])
        self.assertEqual(self.db.cached_flat(self.db.search_kind("dogs")), [])
        self.assertEqual(self.db.cached_flat(self.db.search_kind("cats")), [])


class WalkingBackOntoASearch(unittest.TestCase):
    """What the page shows when the mouse's back button lands on a search.

    It used to show nothing at all. The words came back but the scope did
    not, so the page searched what is stored here, and something looked for
    on YouTube is looked for there precisely because it is not in the feed.
    """

    def setUp(self):
        self.db = support.scratch_db(self)
        bridge = Bridge.__new__(Bridge)
        bridge._db = self.db
        bridge._search_text = ""
        bridge._search_scope = "stored"
        bridge._view_kind = "all"
        bridge._web_results = []
        bridge._exhausted = True
        self.statuses = []
        bridge._set_status = lambda text, *_a, **_k: self.statuses.append(text)
        self.bridge = bridge

    def store(self, words="cats", age_s=0):
        kind = self.db.search_kind(words)
        self.db.replace_cached(kind, [flat("aaaaaaaaaaa"), flat("bbbbbbbbbbb")])
        if age_s:
            with self.db.conn as conn:
                conn.execute("UPDATE cached_videos SET seen_at=? WHERE kind=?",
                             (int(time.time()) - age_s, kind))

    def restore(self, words="cats"):
        self.bridge._search_text = words
        Bridge._restore_kept_search(self.bridge)

    def test_the_kept_results_come_back(self):
        self.store()
        self.restore()
        self.assertEqual(self.bridge._search_scope, "youtube")
        self.assertEqual([row["ext_id"] for row in self.bridge._web_results],
                         ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_and_they_are_shaped_like_a_fresh_page(self):
        self.store()
        self.restore()
        row = self.bridge._web_results[0]
        for field in ("key", "channel_key", "channel_title", "watched", "thumbnail_url"):
            self.assertIn(field, row)

    def test_a_set_older_than_the_trust_window_still_comes_back(self):
        # A walk back is putting a page that was just on screen back, not
        # asking for a fresh one, so age is not a reason to draw nothing.
        self.store(age_s=SEARCH_TRUST_S + 60)
        self.restore()
        self.assertEqual(len(self.bridge._web_results), 2)

    def test_nothing_kept_leaves_the_search_against_what_is_stored(self):
        self.restore("otters")
        self.assertEqual(self.bridge._search_scope, "stored")
        self.assertEqual(self.bridge._web_results, [])

    def test_another_search_is_not_answered_from_this_one(self):
        self.store("cats")
        self.restore("dogs")
        self.assertEqual(self.bridge._search_scope, "stored")
        self.assertEqual(self.bridge._web_results, [])

    def test_no_words_at_all_restores_nothing(self):
        self.store()
        self.restore("")
        self.assertEqual(self.bridge._search_scope, "stored")
        self.assertEqual(self.bridge._web_results, [])

    def test_more_can_be_asked_for_again(self):
        self.store()
        self.bridge._exhausted = True
        self.restore()
        self.assertFalse(self.bridge._exhausted)

    def test_it_says_how_old_the_set_is(self):
        self.store()
        self.restore()
        self.assertTrue(self.statuses)
        self.assertIn("from YouTube", self.statuses[-1])


class TheBoxSayingWhatIsShowing(unittest.TestCase):
    """Refilling the search box must not throw the restored page away.

    The box is refilled from the outside on a walk back, and every change to
    it calls search(). Without the guard that call is a fresh local search
    under the same words, which replaced the kept results with nothing.
    """

    def setUp(self):
        self.db = support.scratch_db(self)
        bridge = Bridge.__new__(Bridge)
        bridge._db = self.db
        bridge._view_kind = "search"
        bridge._view_id = -1
        bridge._view_channel = ""
        bridge._view_playlist = ""
        bridge._search_text = "cats"
        bridge._search_scope = "youtube"
        bridge._web_results = [{"key": "yt:aaaaaaaaaaa"}]
        bridge._before_search = ("all", -1, "", "")
        bridge._nav = type("Nav", (), {"note_search": staticmethod(lambda _t: None)})()
        self.reloads = 0

        def reload():
            self.reloads += 1
        bridge.reload = reload
        bridge.viewChanged = type("Sig", (), {"emit": staticmethod(lambda: None)})()
        self.bridge = bridge

    def test_the_same_words_again_change_nothing(self):
        Bridge.search(self.bridge, "cats")
        self.assertEqual(self.bridge._search_scope, "youtube")
        self.assertEqual(len(self.bridge._web_results), 1)
        self.assertEqual(self.reloads, 0)

    def test_spacing_around_them_is_still_the_same_words(self):
        Bridge.search(self.bridge, "  cats ")
        self.assertEqual(self.bridge._search_scope, "youtube")

    def test_different_words_are_a_real_search_again(self):
        Bridge.search(self.bridge, "dogs")
        self.assertEqual(self.bridge._search_scope, "stored")
        self.assertEqual(self.bridge._web_results, [])
        self.assertEqual(self.reloads, 1)


if __name__ == "__main__":
    unittest.main()
