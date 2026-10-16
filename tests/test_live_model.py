"""The live bar's cards, changed where they stand rather than built again.

A new list every check threw every card away and built them all again, and a
bar scrolled along to find somebody went back to its start each time. These
check that a check changes only what changed, and that a Twitch frame is asked
for again while a YouTube picture is left as it is.
"""

import random
import time
import unittest

from PySide6.QtCore import QCoreApplication, QObject

from tests.support import scratch_db
from weave import imagecache
from weave.db import VideoRow
from weave.ui.bridge import Bridge
from weave.ui.live_model import LiveModel

_app = QCoreApplication.instance() or QCoreApplication([])


def row(key: str, viewers: int = 100, picture: str = "") -> dict:
    return {"id": key, "channelKey": key, "platform": "twitch", "login": key,
            "name": key, "title": "A stream", "game": "", "viewers": viewers,
            "viewersText": str(viewers), "thumbnail": picture, "avatar": ""}


class Heard:
    """Everything the model said, in order."""

    def __init__(self, model: LiveModel) -> None:
        self.said: list[str] = []
        model.modelReset.connect(lambda: self.said.append("reset"))
        model.rowsInserted.connect(lambda _p, first, _l: self.said.append(f"insert {first}"))
        model.rowsRemoved.connect(lambda _p, first, _l: self.said.append(f"remove {first}"))
        model.rowsMoved.connect(
            lambda _p, first, _l, _d, to: self.said.append(f"move {first} {to}"))
        model.dataChanged.connect(
            lambda first, _last, _roles=None: self.said.append(f"change {first.row()}"))
        model.countChanged.connect(lambda: self.said.append("count"))


def ids(model: LiveModel) -> list[str]:
    return [entry["id"] for entry in model.rows()]


class ACheck(unittest.TestCase):
    def setUp(self):
        self.model = LiveModel()
        self.model.show([row("a", 900), row("b", 500), row("c", 100)])
        self.heard = Heard(self.model)

    def test_fresher_numbers_change_only_their_rows(self):
        self.model.show([row("a", 905), row("b", 500), row("c", 101)])
        self.assertEqual(self.heard.said, ["change 0", "change 2"])

    def test_the_same_answer_says_nothing(self):
        self.model.show([row("a", 900), row("b", 500), row("c", 100)])
        self.assertEqual(self.heard.said, [])

    def test_a_stream_that_starts_is_put_in_its_place(self):
        self.model.show([row("a", 900), row("d", 700), row("b", 500), row("c", 100)])
        self.assertEqual(self.heard.said, ["insert 1", "count"])
        self.assertEqual(ids(self.model), ["a", "d", "b", "c"])

    def test_a_stream_that_ends_is_taken_out(self):
        self.model.show([row("a", 900), row("c", 100)])
        self.assertEqual(self.heard.said, ["remove 1", "count"])
        self.assertEqual(self.model.count, 2)

    def test_one_overtaken_is_moved_rather_than_built_again(self):
        self.model.show([row("c", 1000), row("a", 900), row("b", 500)])
        self.assertEqual(self.heard.said, ["move 2 0", "change 0"])
        self.assertEqual(ids(self.model), ["c", "a", "b"])

    def test_a_new_picture_is_a_change_to_its_card(self):
        self.model.show([row("a", 900, "image://cached/x#live=2"), row("b", 500),
                         row("c", 100)])
        self.assertEqual(self.heard.said, ["change 0"])

    def test_nothing_is_ever_reset(self):
        # A reset is what threw the cards away. No check may cause one.
        chance = random.Random(7)
        pool = [row(name, chance.randint(1, 999)) for name in "abcdefghij"]
        for _ in range(200):
            wanted = chance.sample(pool, chance.randint(0, len(pool)))
            self.model.show(wanted)
            self.assertEqual(ids(self.model), [entry["id"] for entry in wanted])
        self.assertNotIn("reset", self.heard.said)

    def test_a_copy_does_not_outlive_its_list(self):
        self.model.show([row("a"), row("a"), row("b")])
        self.model.show([row("a"), row("b")])
        self.assertEqual(ids(self.model), ["a", "b"])


class TheRowsForTheBar(unittest.TestCase):
    """Only a Twitch frame is marked to be asked for again."""

    def setUp(self):
        self.db = scratch_db(self)
        self.db.add_channel("twitch:someone", "twitch", "someone", "Someone",
                            "https://pictures.invalid/face.jpg")
        self.db.replace_live("twitch", [{
            "channel_key": "twitch:someone", "login": "someone", "display_name": "Someone",
            "title": "A stream", "game": "A game", "viewers": 50, "started_at": 1,
            "thumbnail_url": "https://pictures.invalid/live_user_someone-440x248.jpg"}])
        self.db.add_channel("yt:UCsomebodyelse0000000000", "youtube",
                            "UCsomebodyelse0000000000", "Somebody", None)
        self.db.upsert_videos([VideoRow(
            "youtube", "aaaaaaaaaaa", "yt:UCsomebodyelse0000000000", "Live now",
            published_at=1, thumbnail_url="https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg",
            live_status="is_live")])
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._db = self.db
        self.bridge._live_collapsed = False
        self.bridge._live_frames_at = 0.0

    def rows(self) -> dict[str, dict]:
        return {entry["platform"]: entry for entry in Bridge._live_rows(self.bridge)}

    def test_a_twitch_frame_carries_the_five_minutes_it_belongs_to(self):
        twitch = self.rows()["twitch"]["thumbnail"]
        self.assertIn(imagecache.LIVE_MARK, twitch)
        self.assertTrue(twitch.startswith(imagecache.qml_source(
            "https://pictures.invalid/live_user_someone-440x248.jpg")))

    def test_a_youtube_picture_is_left_as_it_is(self):
        youtube = self.rows()["youtube"]["thumbnail"]
        self.assertEqual(youtube, imagecache.qml_source(
            "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"))

    def test_a_bar_rolled_up_asks_for_no_new_frame(self):
        # The five minutes stay where they were while nobody can see the bar,
        # and catch up the moment it is unrolled.
        self.bridge._live_frames_at = 3 * imagecache.LIVE_PICTURE_S + 1
        self.bridge._live_collapsed = True
        self.assertTrue(self.rows()["twitch"]["thumbnail"].endswith(
            f"{imagecache.LIVE_MARK}3"))
        self.bridge._live_collapsed = False
        now = int(time.time() // imagecache.LIVE_PICTURE_S)
        self.assertTrue(self.rows()["twitch"]["thumbnail"].endswith(
            f"{imagecache.LIVE_MARK}{now}"))

    def test_every_stream_has_an_id_of_its_own(self):
        rows = Bridge._live_rows(self.bridge)
        self.assertEqual(len({entry["id"] for entry in rows}), len(rows))


if __name__ == "__main__":
    unittest.main()
