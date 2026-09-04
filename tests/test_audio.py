"""The player's own logic. No network, nothing is resolved or played."""

import unittest

from PySide6.QtCore import QCoreApplication

from weave.audio import AudioPlayer
from weave.config import Config

_app = QCoreApplication.instance() or QCoreApplication([])


def track(name):
    return {"key": f"yt:{name}", "title": name, "artist": "someone",
            "thumbnail": "", "url": f"https://www.youtube.com/watch?v={name}"}


class Volume(unittest.TestCase):
    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player.setVolume(50)

    def test_a_notch_is_five(self):
        self.player.nudgeVolume(1)
        self.assertEqual(self.player.volume, 55)
        self.player.nudgeVolume(-1)
        self.assertEqual(self.player.volume, 50)

    def test_several_notches(self):
        self.player.nudgeVolume(3)
        self.assertEqual(self.player.volume, 65)

    def test_it_cannot_go_past_the_ends(self):
        self.player.setVolume(98)
        self.player.nudgeVolume(2)
        self.assertEqual(self.player.volume, 100)
        self.player.setVolume(3)
        self.player.nudgeVolume(-2)
        self.assertEqual(self.player.volume, 0)


class Upcoming(unittest.TestCase):
    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player.setShuffle(False)
        self.player.setRepeat(False)
        # Queued without starting, since starting would resolve an address.
        self.player._queue = [track(name) for name in ("aaa", "bbb", "ccc", "ddd")]
        self.player._rebuild_order()
        self.player._at = 0

    def test_what_follows(self):
        self.assertEqual([t["title"] for t in self.player.upcoming], ["bbb", "ccc", "ddd"])

    def test_nothing_follows_the_last_one(self):
        self.player._at = 3
        self.assertEqual(self.player.upcoming, [])

    def test_repeat_wraps_round_at_the_end(self):
        self.player._at = 3
        self.player.setRepeat(True)
        self.assertEqual([t["title"] for t in self.player.upcoming], ["aaa", "bbb", "ccc"])

    def test_it_follows_the_play_order_not_the_queue(self):
        # With shuffle on, the queue order is not what will be heard.
        self.player.setShuffle(True)
        self.player._order = [2, 0, 3, 1]
        self.player._at = 2
        self.assertEqual([t["title"] for t in self.player.upcoming], ["aaa", "ddd", "bbb"])

    def test_an_empty_queue_has_nothing_coming(self):
        self.player._queue = []
        self.player._order = []
        self.player._at = -1
        self.assertEqual(self.player.upcoming, [])


class Shuffle(unittest.TestCase):
    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player._queue = [track(name) for name in ("aaa", "bbb", "ccc", "ddd")]
        self.player._rebuild_order()
        self.player._at = 2

    def test_turning_shuffle_on_keeps_the_current_track_first(self):
        # Otherwise whatever is playing would appear to be coming up again.
        self.player.setShuffle(True)
        self.assertEqual(self.player._order[0], 2)
        self.assertEqual(sorted(self.player._order), [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
