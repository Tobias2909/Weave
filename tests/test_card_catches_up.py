"""A card drawn from a listing catches up with what the panel learns.

A suggestion, a history entry and a playlist entry come from listings that
carry almost nothing. Opening one fetches its metadata anyway, for the panel,
so keeping that costs no request and stops the card being the poorer view of
the same video.
"""

import tempfile
import unittest
from pathlib import Path

from weave.db import Database


def listing_row(ext_id="aaaaaaaaaaa", **over):
    row = {"ext_id": ext_id, "title": "A video", "channel_name": "Someone",
           "channel_ext_id": None, "duration_s": None, "thumbnail_url": None,
           "views": None, "published_at": None}
    row.update(over)
    return row


class KeepingWhatWasLearned(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "weave.db")

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

        db = Database(Path(tempfile.mkdtemp()) / "weave.db")
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

        db = Database(Path(tempfile.mkdtemp()) / "weave.db")
        bridge = Bridge.__new__(Bridge)
        bridge._db = db
        bridge._view_kind = "all"
        Bridge._keep_details(bridge, "twitch:someone", {"views": 1})

    def test_the_open_view_is_drawn_again_so_the_card_changes(self) -> None:
        from weave.ui.bridge import Bridge

        db = Database(Path(tempfile.mkdtemp()) / "weave.db")
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
