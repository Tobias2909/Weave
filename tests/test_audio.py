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
        self.player.setRepeat(0)
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
        self.player.setRepeat(1)
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


class Jumping(unittest.TestCase):
    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player.setShuffle(False)
        self.player._queue = [track(name) for name in ("aaa", "bbb", "ccc", "ddd")]
        self.player._rebuild_order()
        self.player._at = 0

    def test_upcoming_says_where_each_one_sits(self):
        # So a row in the queue view can be jumped to directly rather than by
        # pressing next until it arrives.
        self.assertEqual([t["at"] for t in self.player.upcoming], [1, 2, 3])

    def test_jumping_out_of_range_does_nothing(self):
        self.player.jumpTo(99)
        self.assertEqual(self.player._at, 0)
        self.player.jumpTo(-1)
        self.assertEqual(self.player._at, 0)


class Recovery(unittest.TestCase):
    """A stream address is signed and can be dropped part way through."""

    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player._queue = [track("aaa")]
        self.player._rebuild_order()
        self.player._at = 0
        self.started = []
        self.player._start_current = lambda: self.started.append(True)

    def test_the_first_failure_is_retried_quietly(self):
        reported = []
        self.player.failed.connect(reported.append)
        self.player._on_error(None, "Demuxing failed")
        self.assertEqual(len(self.started), 1)
        self.assertEqual(reported, [])

    def test_a_second_failure_is_reported_rather_than_looping(self):
        reported = []
        self.player.failed.connect(reported.append)
        self.player._on_error(None, "Demuxing failed")
        self.player._on_error(None, "Demuxing failed")
        self.assertEqual(len(self.started), 1)
        self.assertEqual(len(reported), 1)

    def test_nothing_playing_is_not_recovered(self):
        self.player._at = -1
        self.assertFalse(self.player._recover())


class Repeat(unittest.TestCase):
    """Three states, because repeating a queue and repeating a track are
    different wants and one switch cannot say which."""

    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player.setRepeat(0)
        self.player._queue = [track(name) for name in ("aaa", "bbb")]
        self.player._rebuild_order()
        self.player._at = 0

    def test_it_cycles(self):
        self.assertEqual(self.player.repeat, 0)
        self.player.cycleRepeat()
        self.assertEqual(self.player.repeat, 1)
        self.player.cycleRepeat()
        self.assertEqual(self.player.repeat, 2)
        self.player.cycleRepeat()
        self.assertEqual(self.player.repeat, 0)

    def test_each_state_is_named(self):
        names = []
        for _ in range(3):
            names.append(self.player.repeatLabel)
            self.player.cycleRepeat()
        self.assertEqual(names, ["Repeat", "Repeat all", "Repeat one"])

    def test_out_of_range_is_clamped(self):
        self.player.setRepeat(9)
        self.assertEqual(self.player.repeat, 2)
        self.player.setRepeat(-4)
        self.assertEqual(self.player.repeat, 0)

    def test_repeating_one_does_not_advance_at_the_end(self):
        from PySide6.QtMultimedia import QMediaPlayer

        moved = []
        self.player.next = lambda: moved.append(True)
        self.player.setRepeat(2)
        self.player._on_status(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertEqual(moved, [])
        self.assertEqual(self.player._at, 0)

    def test_repeating_the_queue_does_advance(self):
        from PySide6.QtMultimedia import QMediaPlayer

        moved = []
        self.player.next = lambda: moved.append(True)
        self.player.setRepeat(1)
        self.player._on_status(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertEqual(moved, [True])

    def test_only_the_whole_queue_setting_wraps_what_is_coming(self):
        self.player._at = 1
        self.player.setRepeat(2)
        self.assertEqual(self.player.upcoming, [])
        self.player.setRepeat(1)
        self.assertEqual([t["title"] for t in self.player.upcoming], ["aaa"])


class Fading(unittest.TestCase):
    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player.setVolume(60)

    def test_the_reported_volume_is_what_was_asked_for(self):
        # Not whatever level a fade happens to be passing through.
        self.player._output.setVolume(0.02)
        self.assertEqual(self.player.volume, 60)

    def test_pausing_for_a_video_fades_rather_than_cuts(self):
        self.player._queue = [track("aaa")]
        self.player._rebuild_order()
        self.player._at = 0
        self.player._get_playing = lambda: True
        self.player.pause_for_video()
        self.assertTrue(self.player._fade.state() != self.player._fade.State.Stopped
                        or self.player._pause_after_fade)

    def test_setting_the_volume_stops_a_fade(self):
        self.player._fade_to(0.0, pause_after=True)
        self.player.setVolume(30)
        self.assertFalse(self.player._pause_after_fade)
        self.assertEqual(self.player.volume, 30)
