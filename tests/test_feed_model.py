"""The list model behind the grid.

The one behaviour worth pinning down here is what happens when more rows
arrive. Resetting a model sends the view back to the top, and being thrown to
the top is exactly what loading more at the bottom of a long list must not do.
"""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from weave.db import Database
from weave.ui.feed_model import FeedModel

_app = QCoreApplication.instance() or QCoreApplication([])


def row(ext_id, title="A video"):
    return {
        "key": f"yt:{ext_id}", "platform": "youtube", "ext_id": ext_id,
        "channel_key": "yt:UC1", "title": title, "published_at": None,
        "thumbnail_url": None, "duration_s": 60, "views": 10, "likes": None,
        "live_status": None, "channel_title": "One", "avatar_url": None,
        "watched": False,
    }


class Showing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.model = FeedModel(self.db)
        self.events = []
        self.model.modelReset.connect(lambda: self.events.append("reset"))
        self.model.rowsInserted.connect(lambda *_a: self.events.append("inserted"))
        self.changes = []
        self.model.dataChanged.connect(
            lambda first, last, *_a: self.changes.append((first.row(), last.row())))

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_a_longer_list_that_starts_the_same_is_an_addition(self):
        self.model.show([row("aaaaaaaaaaa"), row("bbbbbbbbbbb")])
        self.events.clear()
        self.model.show([row("aaaaaaaaaaa"), row("bbbbbbbbbbb"), row("ccccccccccc")])
        self.assertEqual(self.events, ["inserted"])
        self.assertEqual(self.model.rowCount(), 3)

    def test_a_new_video_at_the_front_is_an_addition_too(self):
        # Where a feed puts what is new. This was a reset until a refresh
        # landing mid scroll was noticed throwing the reader to the top.
        self.model.show([row("aaaaaaaaaaa")])
        self.events.clear()
        self.model.show([row("zzzzzzzzzzz"), row("aaaaaaaaaaa")])
        self.assertEqual(self.events, ["inserted"])
        self.assertEqual([self.model.key_at(i) for i in range(2)],
                         ["yt:zzzzzzzzzzz", "yt:aaaaaaaaaaa"])

    def test_a_list_in_another_order_is_a_reset(self):
        # Nothing to keep a place against, so the honest answer is a reset.
        self.model.show([row("aaaaaaaaaaa"), row("bbbbbbbbbbb")])
        self.events.clear()
        self.model.show([row("bbbbbbbbbbb"), row("aaaaaaaaaaa")])
        self.assertEqual(self.events, ["reset"])

    def test_a_shorter_list_is_a_reset(self):
        self.model.show([row("aaaaaaaaaaa"), row("bbbbbbbbbbb")])
        self.events.clear()
        self.model.show([row("aaaaaaaaaaa")])
        self.assertEqual(self.events, ["reset"])

    def test_the_same_list_again_changes_rows_rather_than_resetting(self):
        # What a poll comes back with nearly every time: the same videos with
        # fresher numbers. A reset for that is what sent the grid to the top
        # once a minute, which is the whole reason for the check.
        self.model.show([row("aaaaaaaaaaa")])
        self.events.clear()
        self.model.show([row("aaaaaaaaaaa", title="Renamed")])
        self.assertEqual(self.events, [])
        self.assertEqual(self.changes, [(0, 0)])
        self.assertEqual(self.model.row_at(0)["title"], "Renamed")

    def test_only_the_rows_that_changed_are_announced(self):
        # Three hundred delegates rebinding once a minute for nothing is the
        # other way to get this wrong.
        first = [row(name * 11, title=name) for name in "abcde"]
        self.model.show(first)
        self.events.clear()
        second = [dict(one) for one in first]
        second[3]["title"] = "Renamed"
        self.model.show(second)
        self.assertEqual(self.events, [])
        self.assertEqual(self.changes, [(3, 3)])

    def test_neighbouring_changes_are_announced_as_one_stretch(self):
        first = [row(name * 11, title=name) for name in "abcde"]
        self.model.show(first)
        self.events.clear()
        second = [dict(one) for one in first]
        second[1]["title"] = "Renamed"
        second[2]["title"] = "Renamed too"
        self.model.show(second)
        self.assertEqual(self.changes, [(1, 2)])

    def test_the_same_list_with_nothing_changed_says_nothing(self):
        self.model.show([row("aaaaaaaaaaa")])
        self.events.clear()
        self.model.show([row("aaaaaaaaaaa")])
        self.assertEqual((self.events, self.changes), ([], []))

    def test_the_first_list_of_all_is_a_reset(self):
        self.model.show([row("aaaaaaaaaaa")])
        self.assertEqual(self.events, ["reset"])

    def test_added_rows_keep_the_order_they_came_in(self):
        self.model.show([row("aaaaaaaaaaa")])
        self.model.show([row("aaaaaaaaaaa"), row("bbbbbbbbbbb"), row("ccccccccccc")])
        self.assertEqual([self.model.key_at(i) for i in range(3)],
                         ["yt:aaaaaaaaaaa", "yt:bbbbbbbbbbb", "yt:ccccccccccc"])

    def test_a_row_shaped_with_no_scheduled_at_column_is_never_upcoming(self):
        # Recommendations and playlist items never select scheduled_at at
        # all, so the row dict simply has no such key.
        self.model.show([row("aaaaaaaaaaa")])
        built = self.model.row_at(0)
        self.assertFalse(built["isUpcoming"])
        self.assertEqual(built["scheduledText"], "")

    def test_an_announced_video_is_marked_upcoming_with_its_start_time(self):
        one = row("aaaaaaaaaaa")
        one["live_status"] = "is_upcoming"
        one["scheduled_at"] = 1_900_000_000
        self.model.show([one])
        built = self.model.row_at(0)
        self.assertTrue(built["isUpcoming"])
        self.assertNotEqual(built["scheduledText"], "")
        # The card puts this where the age of an ordinary video goes, so an
        # announced stream that carries no clock time would leave a gap.
        self.assertIn(" at ", built["startsText"])


if __name__ == "__main__":
    unittest.main()
