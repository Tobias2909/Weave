"""The player's own logic. No network, nothing is resolved or played."""

import unittest

from PySide6.QtCore import QCoreApplication
from PySide6.QtMultimedia import QMediaPlayer

from weave.audio import (RECOVER_COOLDOWN_S, RECOVER_LIMIT, RECOVER_WINDOW_S,
                         AudioPlayer)
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


class TheQueue(unittest.TestCase):
    """Starting a playlist puts the playlist in the player.

    A track that has been played stays in the list with everything else rather
    than disappearing behind you, which is how every other music player
    behaves and is what this pins down.
    """

    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player.setShuffle(False)
        self.player.setRepeat(0)
        # Queued without starting, since starting would resolve an address.
        self.player._queue = [track(name) for name in ("aaa", "bbb", "ccc", "ddd")]
        self.player._rebuild_order()
        self.player._at = 0

    def test_the_whole_list_is_in_it(self):
        self.assertEqual([t["title"] for t in self.player.queue],
                         ["aaa", "bbb", "ccc", "ddd"])

    def test_moving_on_leaves_the_last_one_behind_rather_than_dropping_it(self):
        self.player._at = 2
        self.assertEqual([t["title"] for t in self.player.queue],
                         ["aaa", "bbb", "ccc", "ddd"])

    def test_the_one_playing_is_marked(self):
        self.player._at = 2
        self.assertEqual([t["title"] for t in self.player.queue if t["current"]], ["ccc"])

    def test_even_at_the_very_end(self):
        self.player._at = 3
        self.assertEqual(len(self.player.queue), 4)
        self.assertEqual([t["title"] for t in self.player.queue if t["current"]], ["ddd"])

    def test_it_follows_the_play_order_not_the_order_it_was_given(self):
        # With shuffle on, the queue order is not what will be heard.
        self.player.setShuffle(True)
        self.player._order = [2, 0, 3, 1]
        self.player._at = 2
        self.assertEqual([t["title"] for t in self.player.queue],
                         ["ccc", "aaa", "ddd", "bbb"])

    def test_an_empty_queue_is_an_empty_list(self):
        self.player._queue = []
        self.player._order = []
        self.player._at = -1
        self.assertEqual(self.player.queue, [])

    def test_how_many_are_still_to_come(self):
        # What the button that opens the list is enabled by.
        self.assertEqual(self.player.stillToCome, 3)
        self.player._at = 3
        self.assertEqual(self.player.stillToCome, 0)

    def test_repeating_the_whole_queue_means_there_is_always_more(self):
        self.player._at = 3
        self.player.setRepeat(1)
        self.assertEqual(self.player.stillToCome, 3)


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

    def test_the_queue_says_where_each_one_sits(self):
        # So a row in the queue view can be jumped to directly rather than by
        # pressing next until it arrives.
        self.assertEqual([t["at"] for t in self.player.queue], [0, 1, 2, 3])

    def test_jumping_out_of_range_does_nothing(self):
        self.player.jumpTo(99)
        self.assertEqual(self.player._at, 0)
        self.player.jumpTo(-1)
        self.assertEqual(self.player._at, 0)


class Recovery(unittest.TestCase):
    """What reaches the person listening, as opposed to what is handled."""

    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player._queue = [track("aaa")]
        self.player._rebuild_order()
        self.player._at = 0
        self.started = []
        self.player._start_current = lambda: self.started.append(True)

    def test_a_dropped_address_is_retried_quietly(self):
        reported = []
        self.player.failed.connect(reported.append)
        self.player._on_error(None, "Demuxing failed")
        self.assertEqual(len(self.started), 1)
        self.assertEqual(reported, [])

    def test_the_same_complaint_again_is_not_a_second_problem(self):
        # The demuxer reports a dead connection over and over. One recovery
        # answers all of it, and none of it is worth telling anybody about.
        reported = []
        self.player.failed.connect(reported.append)
        for _ in range(5):
            self.player._on_error(None, "Demuxing failed")
        self.assertEqual(len(self.started), 1)
        self.assertEqual(reported, [])

    def test_something_that_cannot_be_recovered_from_is_reported(self):
        reported = []
        self.player.failed.connect(reported.append)
        for _ in range(RECOVER_LIMIT):
            self.player._recover()
            self.player._recover_at -= RECOVER_COOLDOWN_S + 1
        self.player._on_error(None, "Demuxing failed")
        self.assertEqual(len(reported), 1)

    def test_nothing_playing_is_not_recovered(self):
        self.player._at = -1
        self.assertFalse(self.player._recover())


class Recovering(unittest.TestCase):
    """A signed address is dropped part way through a track now and then, which
    over a long listen is ordinary rather than exceptional.

    The bug this pins down: the flag that says a restart is under way was also
    what limited the retries, and it was only cleared when a track reached its
    end. So the first recovery of a session used it up, and the next dropped
    address stopped the music instead of being recovered from.
    """

    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player._queue = [track(name) for name in ("aaa", "bbb")]
        self.player._rebuild_order()
        self.player._at = 0
        self.started = []
        self.player._start_current = lambda: self.started.append(self.player._at)

    def test_a_dropped_address_is_recovered_from(self):
        self.assertTrue(self.player._recover())
        self.assertEqual(self.started, [0])

    def test_a_burst_of_the_same_complaint_starts_one_recovery(self):
        # The demuxer reports it over and over while the connection is down.
        self.assertTrue(self.player._recover())
        self.assertTrue(self.player._recover())
        self.assertTrue(self.player._recover())
        self.assertEqual(len(self.started), 1)

    def test_a_later_drop_is_recovered_from_too(self):
        # The one that was broken. A second failure, minutes later, has to be
        # handled rather than reported.
        self.player._recover()
        self.player._recover_at -= RECOVER_COOLDOWN_S + 1
        self.assertTrue(self.player._recover())
        self.assertEqual(len(self.started), 2)

    def test_it_gives_up_rather_than_looping_for_ever(self):
        for _ in range(RECOVER_LIMIT):
            self.player._recover()
            self.player._recover_at -= RECOVER_COOLDOWN_S + 1
        self.assertFalse(self.player._recover())

    def test_a_track_playing_happily_for_a_while_gets_its_goes_back(self):
        for _ in range(RECOVER_LIMIT):
            self.player._recover()
            self.player._recover_at -= RECOVER_COOLDOWN_S + 1
        self.player._recover_at -= RECOVER_WINDOW_S
        self.assertTrue(self.player._recover())

    def test_a_different_track_is_a_clean_slate(self):
        for _ in range(RECOVER_LIMIT):
            self.player._recover()
            self.player._recover_at -= RECOVER_COOLDOWN_S + 1
        self.player.next()
        self.assertTrue(self.player._recover())

    def test_the_position_is_kept_so_it_picks_up_where_it_stopped(self):
        self.player._player.position = lambda: 65000
        self.player._recover()
        self.assertEqual(self.player._resume_at, 65000)

    def test_with_nothing_playing_there_is_nothing_to_recover(self):
        self.player._queue = []
        self.player._at = -1
        self.assertFalse(self.player._recover())


class PickingUpWhereItStopped(unittest.TestCase):
    """What a recovery is for.

    He watched a track restart from the beginning after a dropped connection.
    The recovery was working; the seek was not. A position set before the new
    source has loaded is discarded, so it has to wait for the source to say it
    is ready.
    """

    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player._queue = [track("aaa")]
        self.player._rebuild_order()
        self.player._at = 0
        self.seeks = []
        self.played = []
        self.player._player.setPosition = self.seeks.append
        self.player._player.play = lambda: self.played.append(True)
        self.player._player.setSource = lambda _url: None

    def resolve(self, resume_at):
        self.player._resume_at = resume_at
        self.player._on_resolved("yt:aaa", "https://x")

    def test_nothing_is_seeked_while_the_source_is_still_loading(self):
        self.resolve(65000)
        self.assertEqual(self.seeks, [])

    def test_and_nothing_is_played_yet_either(self):
        # Otherwise the first thing heard is the start of the track, which is
        # the very thing being avoided.
        self.resolve(65000)
        self.assertEqual(self.played, [])

    def test_the_position_is_taken_up_once_the_source_has_loaded(self):
        self.resolve(65000)
        self.player._on_status(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual(self.seeks, [65000])
        self.assertEqual(self.played, [True])

    def test_it_is_only_taken_up_once(self):
        self.resolve(65000)
        self.player._on_status(QMediaPlayer.MediaStatus.LoadedMedia)
        self.player._on_status(QMediaPlayer.MediaStatus.BufferedMedia)
        self.assertEqual(self.seeks, [65000])

    def test_an_ordinary_track_starts_at_once_and_from_the_beginning(self):
        self.resolve(0)
        self.assertEqual(self.seeks, [])
        self.assertEqual(self.played, [True])

    def test_loading_an_ordinary_track_seeks_nowhere(self):
        self.resolve(0)
        self.player._on_status(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual(self.seeks, [])


class Stalling(unittest.TestCase):
    """A reset connection does not always arrive as an error.

    The layers underneath report it as a read error and a session that has been
    invalidated, and the player can simply stall and sit there. Without this the
    music stops with a full console and a quiet application.
    """

    def setUp(self):
        self.player = AudioPlayer(Config(raw={}))
        self.player._queue = [track("aaa")]
        self.player._rebuild_order()
        self.player._at = 0
        self.started = []
        self.player._start_current = lambda: self.started.append(True)
        self.position = 5000
        self.player._player.position = lambda: self.position

    def stall(self):
        self.player._on_status(QMediaPlayer.MediaStatus.StalledMedia)

    def test_a_stall_is_given_a_moment_before_anything_is_done(self):
        self.stall()
        self.assertTrue(self.player._stall_timer.isActive())
        self.assertEqual(self.started, [])

    def test_buffering_that_comes_back_is_left_alone(self):
        # Ordinary buffering stalls too, and recovering from that would
        # interrupt something that was about to carry on by itself.
        self.stall()
        self.player._on_status(QMediaPlayer.MediaStatus.BufferedMedia)
        self.assertFalse(self.player._stall_timer.isActive())
        self.assertEqual(self.started, [])

    def test_a_stall_that_never_moves_is_recovered_from(self):
        self.stall()
        self.player._on_stalled_too_long()
        self.assertEqual(self.started, [True])

    def test_one_that_did_move_is_not(self):
        self.stall()
        self.position += 1000
        self.player._on_stalled_too_long()
        self.assertEqual(self.started, [])

    def test_a_stall_that_cannot_be_recovered_from_is_said_out_loud(self):
        reported = []
        self.player.failed.connect(reported.append)
        for _ in range(RECOVER_LIMIT):
            self.player._recover()
            self.player._recover_at -= RECOVER_COOLDOWN_S + 1
        self.stall()
        self.player._on_stalled_too_long()
        self.assertEqual(len(reported), 1)

    def test_the_end_of_a_track_cancels_the_watch(self):
        self.stall()
        self.player._on_status(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertFalse(self.player._stall_timer.isActive())

    def test_and_so_does_starting_something_else(self):
        self.player._start_current = AudioPlayer._start_current.__get__(self.player)
        self.stall()
        self.player._player.stop = lambda: None
        self.player._start_current()
        self.assertFalse(self.player._stall_timer.isActive())


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

    def test_the_volume_stays_down_once_the_fade_has_paused_it(self):
        """The blip at the end of a fade.

        Pausing is asynchronous, so putting the level back the moment it is
        asked for plays whatever is still in the buffer at full volume. It is
        raised again by whatever starts playing next instead.
        """
        paused = []
        self.player._player.pause = lambda: paused.append(True)
        self.player._pause_after_fade = True
        self.player._output.setVolume(0.0)
        self.player._on_fade_done()
        self.assertEqual(paused, [True])
        self.assertEqual(self.player._output.volume(), 0.0)
        # And what was asked for is not forgotten, only not applied yet.
        self.assertEqual(self.player.volume, 60)

    def test_starting_again_puts_the_level_back(self):
        played = []
        self.player._player.play = lambda: played.append(True)
        self.player._output.setVolume(0.0)
        self.player._start_playing()
        self.assertEqual(played, [True])
        self.assertAlmostEqual(self.player._output.volume(), 0.6, places=5)
