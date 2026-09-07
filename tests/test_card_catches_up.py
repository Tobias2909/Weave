"""A card drawn from a listing catches up with what the panel learns.

A suggestion, a history entry and a playlist entry come from listings that
carry almost nothing. Opening one fetches its metadata anyway, for the panel,
so keeping that costs no request and stops the card being the poorer view of
the same video.
"""

import unittest

from tests.support import scratch_db


def listing_row(ext_id="aaaaaaaaaaa", **over):
    row = {"ext_id": ext_id, "title": "A video", "channel_name": "Someone",
           "channel_ext_id": None, "duration_s": None, "thumbnail_url": None,
           "views": None, "published_at": None}
    row.update(over)
    return row


class KeepingWhatWasLearned(unittest.TestCase):
    def setUp(self) -> None:
        self.db = scratch_db(self)

    def test_a_suggestion_gains_its_numbers(self) -> None:
        self.db.replace_cached(self.db.RECOMMENDED, [listing_row()])
        self.db.fill_in_details("aaaaaaaaaaa", views=1234,
                                published_at=1700000000, duration_s=321)
        row = self.db.cached(self.db.RECOMMENDED)[0]
        self.assertEqual(row["views"], 1234)
        self.assertEqual(row["published_at"], 1700000000)
        self.assertEqual(row["duration_s"], 321)

    def test_a_history_entry_gains_them_too(self) -> None:
        self.db.replace_cached(self.db.HISTORY, [listing_row()])
        self.db.fill_in_details("aaaaaaaaaaa", views=7)
        self.assertEqual(self.db.cached(self.db.HISTORY)[0]["views"], 7)

    def test_a_playlist_entry_gains_them_too(self) -> None:
        self.db.replace_playlists([{"ext_id": "PL1", "title": "A list"}])
        self.db.replace_playlist_items("PL1", [listing_row()], skipped=0)
        self.db.fill_in_details("aaaaaaaaaaa", duration_s=99)
        found = [row for row in self.db.playlist_items("PL1")
                 if row["ext_id"] == "aaaaaaaaaaa"]
        self.assertEqual(found[0]["duration_s"], 99)

    def test_nothing_known_is_undone_by_a_blank_answer(self) -> None:
        """A listing that did carry a view count keeps it."""
        self.db.replace_cached(self.db.RECOMMENDED, [listing_row(views=500)])
        self.db.fill_in_details("aaaaaaaaaaa", views=None, duration_s=42)
        row = self.db.cached(self.db.RECOMMENDED)[0]
        self.assertEqual(row["views"], 500)
        self.assertEqual(row["duration_s"], 42)

    def test_a_video_nobody_has_cached_is_no_error(self) -> None:
        self.assertEqual(self.db.fill_in_details("bbbbbbbbbbb", views=1), 0)

    def test_learning_the_same_thing_twice_changes_nothing(self) -> None:
        """The second answer must not count as a change.

        A row that is already complete would otherwise have the view drawn
        again for nothing, and a redraw throws away rows the grid is still
        building, which is what Qt complains about as a cancelled delegate.
        """
        self.db.replace_cached(self.db.RECOMMENDED, [listing_row()])
        self.assertEqual(self.db.fill_in_details("aaaaaaaaaaa", views=5,
                                                 published_at=1700000000,
                                                 duration_s=60), 1)
        self.assertEqual(self.db.fill_in_details("aaaaaaaaaaa", views=5,
                                                 published_at=1700000000,
                                                 duration_s=60), 0)
        row = self.db.cached(self.db.RECOMMENDED)[0]
        self.assertEqual(row["views"], 5)


class TheBridgeKeepsThem(unittest.TestCase):
    def test_details_from_the_panel_reach_the_row(self) -> None:
        from weave.ui.bridge import Bridge

        db = scratch_db(self)
        db.replace_cached(db.RECOMMENDED, [listing_row()])

        bridge = Bridge.__new__(Bridge)
        bridge._db = db
        bridge._view_kind = "all"
        bridge.reloaded = []
        bridge.reload = lambda: bridge.reloaded.append(True)
        Bridge._keep_details(bridge, "yt:aaaaaaaaaaa", {
            "views": 42, "likes": 7, "published_at": 1700000000, "duration_s": 60})
        row = db.cached(db.RECOMMENDED)[0]
        self.assertEqual(row["views"], 42)
        self.assertEqual(row["duration_s"], 60)

    def test_a_twitch_key_is_left_alone(self) -> None:
        from weave.ui.bridge import Bridge

        db = scratch_db(self)
        bridge = Bridge.__new__(Bridge)
        bridge._db = db
        bridge._view_kind = "all"
        Bridge._keep_details(bridge, "twitch:someone", {"views": 1})

    def test_the_open_view_is_drawn_again_so_the_card_changes(self) -> None:
        from weave.ui.bridge import Bridge

        db = scratch_db(self)
        db.replace_cached(db.RECOMMENDED, [listing_row()])
        bridge = Bridge.__new__(Bridge)
        bridge._db = db
        bridge._view_kind = "recommended"
        bridge.reloaded = []
        bridge.reload = lambda: bridge.reloaded.append(True)
        Bridge._keep_details(bridge, "yt:aaaaaaaaaaa", {"views": 42})
        self.assertEqual(bridge.reloaded, [True])


if __name__ == "__main__":
    unittest.main()


class WalkingPastAViewWithNoGrid(unittest.TestCase):
    """The wheel over the sidebar steps the selection, so a fast walk lands on
    Music, How things are and Settings in quick succession. Those draw their
    own page over a hidden grid, and emptying that grid on the way past threw
    away rows it was still building, which Qt reports as a cancelled delegate.
    """

    def bridge(self, kind: str):
        from weave.ui.bridge import Bridge

        db = scratch_db(self)

        class Model:
            def __init__(self):
                self.calls = []

            def show(self, rows):
                self.calls.append(("show", len(list(rows))))

            def reload(self, **kw):
                self.calls.append(("reload", kw))

        class Quiet:
            def emit(self, *_a):
                pass

        bridge = Bridge.__new__(Bridge)
        bridge._db = db
        bridge._model = Model()
        bridge._view_kind = kind
        bridge._view_id = -1
        bridge._view_channel = ""
        bridge._view_playlist = ""
        bridge._search_text = ""
        bridge._search_scope = "stored"
        bridge._history_music = False
        bridge._hide_watched = True
        bridge._web_results = []
        for name in ("playlistSkippedChanged", "emptyHintChanged", "groupsChanged",
                     "boxesChanged", "countsChanged"):
            setattr(bridge, name, Quiet())
        return bridge

    def test_the_grid_is_left_alone_by_those_three(self) -> None:
        from weave.ui.bridge import Bridge

        for kind in ("music", "debug", "settings"):
            with self.subTest(kind=kind):
                bridge = self.bridge(kind)
                Bridge.reload(bridge)
                self.assertEqual(bridge._model.calls, [],
                                 "the hidden grid was touched anyway")

    def test_a_view_that_does_have_a_grid_still_fills_it(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge("all")
        Bridge.reload(bridge)
        self.assertEqual([call[0] for call in bridge._model.calls], ["reload"])
