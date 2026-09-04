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

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_a_longer_list_that_starts_the_same_is_an_addition(self):
        self.model.show([row("aaaaaaaaaaa"), row("bbbbbbbbbbb")])
        self.events.clear()
        self.model.show([row("aaaaaaaaaaa"), row("bbbbbbbbbbb"), row("ccccccccccc")])
        self.assertEqual(self.events, ["inserted"])
        self.assertEqual(self.model.rowCount(), 3)

    def test_a_different_list_is_a_reset(self):
        self.model.show([row("aaaaaaaaaaa")])
        self.events.clear()
        self.model.show([row("zzzzzzzzzzz"), row("aaaaaaaaaaa")])
        self.assertEqual(self.events, ["reset"])

    def test_a_shorter_list_is_a_reset(self):
        self.model.show([row("aaaaaaaaaaa"), row("bbbbbbbbbbb")])
        self.events.clear()
        self.model.show([row("aaaaaaaaaaa")])
        self.assertEqual(self.events, ["reset"])

    def test_the_same_list_again_is_a_reset_rather_than_nothing(self):
        # Titles and counts change under the same keys, so the rows are
        # rebuilt. It costs a position only when nothing was added.
        self.model.show([row("aaaaaaaaaaa")])
        self.events.clear()
        self.model.show([row("aaaaaaaaaaa", title="Renamed")])
        self.assertEqual(self.events, ["reset"])

    def test_the_first_list_of_all_is_a_reset(self):
        self.model.show([row("aaaaaaaaaaa")])
        self.assertEqual(self.events, ["reset"])

    def test_added_rows_keep_the_order_they_came_in(self):
        self.model.show([row("aaaaaaaaaaa")])
        self.model.show([row("aaaaaaaaaaa"), row("bbbbbbbbbbb"), row("ccccccccccc")])
        self.assertEqual([self.model.key_at(i) for i in range(3)],
                         ["yt:aaaaaaaaaaa", "yt:bbbbbbbbbbb", "yt:ccccccccccc"])


if __name__ == "__main__":
    unittest.main()
