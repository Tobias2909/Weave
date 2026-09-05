"""The player's own logic. No network, nothing is resolved or played.

The engine underneath is a stand in that records what it was told and lets a
test say what mpv reported back. What mpv really does is pinned down in
`test_engine.py` against the real thing.
"""

import unittest

from PySide6.QtCore import QCoreApplication, QObject, Signal

from weave.audio import (ADDRESS_MARGIN_S, RECOVER_COOLDOWN_S, RECOVER_LIMIT,
                         RECOVER_WINDOW_S, AddressCache, AudioPlayer, address_expiry)
from weave.config import Config
from weave.engine import CURRENT, NEXT

_app = QCoreApplication.instance() or QCoreApplication([])


def track(name, live=False):
    return {"key": f"yt:{name}", "title": name, "artist": "someone", "thumbnail": "",
            "url": f"https://www.youtube.com/watch?v={name}", "live": live}


def signed(name, expire=4_000_000_000):
    return f"https://rr1.example/videoplayback?expire={expire}&id={name}&itag=774"


class FakeEngine(QObject):
    positionChanged = Signal(float)
    durationChanged = Signal(float)
    pausedChanged = Signal(bool)
    idleChanged = Signal(bool)
    bufferingChanged = Signal(bool)
    started = Signal(str)
    ended = Signal(str)
    gone = Signal(str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.volume = None

    def _note(self, *call):
        self.calls.append(call)

    def load(self, url, start=None):
        self._note("load", url, start)

    def append(self, url):
        self._note("append", url)

    def clear_after(self):
        self._note("clear_after")

    def remove_before(self):
        self._note("remove_before")

    def next(self):
        self._note("next")

    def stop(self):
        self._note("stop")

    def set_pause(self, paused):
        self._note("pause", paused)

    def seek(self, seconds):
        self._note("seek", round(seconds, 3))

    def set_volume(self, volume):
        self.volume = volume
        self._note("volume", round(volume, 3))

    def set_loop(self, loop):
        self._note("loop", loop)

    def quit(self):
        self._note("quit")

    def only(self, kind):
        return [c for c in self.calls if c[0] == kind]


class FakeResolver(QObject):
    """Never starts, so nothing here ever reaches for yt-dlp."""

    resolved = Signal(str, str)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.running = False

    def start(self):
        self.running = True

    def cancel(self):
        self.running = False

    def isRunning(self):
        return self.running

    def wait(self, _ms=0):
        return True


class _Base(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.player = AudioPlayer(Config(raw={}), engine=self.engine)
        self.player.setShuffle(False)
        self.player.setRepeat(0)
        # Resolving is a subprocess. Every test here decides what came back.
        self.player._make_resolver = lambda entry: FakeResolver(entry["key"])

    def queue(self, *names, at=0):
        self.player._queue = [track(n) for n in names]
        self.player._rebuild_order()
        self.player._at = at

    def cache(self, *names):
        for name in names:
            self.player._addresses.put(f"yt:{name}", signed(name))


class Volume(_Base):
    def test_a_notch_is_five(self):
        self.player.setVolume(50)
        self.player.nudgeVolume(1)
        self.assertEqual(self.player.volume, 55)
        self.player.nudgeVolume(-1)
        self.assertEqual(self.player.volume, 50)

    def test_it_cannot_go_past_the_ends(self):
        self.player.setVolume(98)
        self.player.nudgeVolume(2)
        self.assertEqual(self.player.volume, 100)
        self.player.setVolume(3)
        self.player.nudgeVolume(-2)
        self.assertEqual(self.player.volume, 0)

    def test_the_level_reaches_mpv_as_a_percentage(self):
        self.player.setVolume(42)
        self.assertEqual(self.engine.volume, 42.0)


class TheQueue(_Base):
    """Starting a playlist puts the playlist in the player.

    A track that has been played stays in the list with everything else rather
    than disappearing behind you, which is how every other music player
    behaves and is what this pins down.
    """

    def setUp(self):
        super().setUp()
        self.queue("aaa", "bbb", "ccc", "ddd")

    def test_the_whole_list_is_in_it(self):
        self.assertEqual([t["title"] for t in self.player.queue], ["aaa", "bbb", "ccc", "ddd"])

    def test_moving_on_leaves_the_last_one_behind_rather_than_dropping_it(self):
        self.player._at = 2
        self.assertEqual([t["title"] for t in self.player.queue], ["aaa", "bbb", "ccc", "ddd"])

    def test_the_one_playing_is_marked(self):
        self.player._at = 2
        self.assertEqual([t["title"] for t in self.player.queue if t["current"]], ["ccc"])

    def test_it_follows_the_play_order_not_the_order_it_was_given(self):
        self.player.setShuffle(True)
        self.player._order = [2, 0, 3, 1]
        self.player._at = 2
        self.assertEqual([t["title"] for t in self.player.queue], ["ccc", "aaa", "ddd", "bbb"])

    def test_an_empty_queue_is_an_empty_list(self):
        self.queue()
        self.player._at = -1
        self.assertEqual(self.player.queue, [])

    def test_how_many_are_still_to_come(self):
        self.assertEqual(self.player.stillToCome, 3)
        self.player._at = 3
        self.assertEqual(self.player.stillToCome, 0)

    def test_repeating_the_whole_queue_means_there_is_always_more(self):
        self.player._at = 3
        self.player.setRepeat(1)
        self.assertEqual(self.player.stillToCome, 3)

    def test_what_comes_next(self):
        self.assertEqual(self.player._next_index(), 1)
        self.player._at = 3
        self.assertIsNone(self.player._next_index())
        self.player.setRepeat(1)
        self.assertEqual(self.player._next_index(), 0)
        self.player.setRepeat(2)
        self.assertIsNone(self.player._next_index(), "repeat one is the same track again")


class Shuffle(_Base):
    def test_turning_shuffle_on_keeps_the_current_track_first(self):
        self.queue("aaa", "bbb", "ccc", "ddd", at=2)
        self.player.setShuffle(True)
        self.assertEqual(self.player._order[0], 2)
        self.assertEqual(sorted(self.player._order), [0, 1, 2, 3])


class Jumping(_Base):
    def test_jumping_out_of_range_does_nothing(self):
        self.queue("aaa", "bbb")
        self.player.jumpTo(7)
        self.assertEqual(self.player._at, 0)
        self.assertEqual(self.engine.only("load"), [])


class StartingATrack(_Base):
    """An address that is already known goes straight to mpv. One that is not
    is resolved first, and the window says so."""

    def test_a_known_address_is_handed_over_at_once(self):
        self.queue("aaa", "bbb")
        self.cache("aaa")
        self.player._start_current()
        self.assertEqual(self.engine.only("load"), [("load", signed("aaa"), None)])
        self.assertFalse(self.player.loading)
        self.assertTrue(self.player.playing)

    def test_an_unknown_one_is_resolved_first(self):
        self.queue("aaa", "bbb")
        self.player._start_current()
        self.assertEqual(self.engine.only("load"), [])
        self.assertTrue(self.player.loading)
        self.player._resolver.cancel()

    def test_what_comes_back_is_played_and_remembered(self):
        self.queue("aaa", "bbb")
        self.player._start_current()
        self.player._resolver.cancel()
        self.player._on_resolved("yt:aaa", signed("aaa"))
        self.assertEqual(self.engine.only("load"), [("load", signed("aaa"), None)])
        self.assertEqual(self.player._addresses.get("yt:aaa"), signed("aaa"))

    def test_an_answer_for_something_no_longer_wanted_is_ignored(self):
        self.queue("aaa", "bbb")
        self.player._start_current()
        self.player._resolver.cancel()
        self.player._on_resolved("yt:zzz", signed("zzz"))
        self.assertEqual(self.engine.only("load"), [])

    def test_a_live_address_is_not_remembered(self):
        self.player._queue = [track("live", live=True)]
        self.player._rebuild_order()
        self.player._at = 0
        self.player._start_current()
        self.player._resolver.cancel()
        self.player._on_resolved("yt:live", "https://x/playlist.m3u8")
        self.assertEqual(self.engine.only("load"), [("load", "https://x/playlist.m3u8", None)])
        self.assertIsNone(self.player._addresses.get("yt:live"))

    def test_the_volume_asked_for_is_raised_before_playing(self):
        self.queue("aaa")
        self.cache("aaa")
        self.player.setVolume(60)
        self.player._set_output(0.0)
        self.player._start_current()
        self.assertEqual(self.engine.volume, 60.0)


class TheTrackAfter(_Base):
    """The only wait in the chain is resolving, so the next address is fetched
    while the current track plays, and mpv is handed it before it is needed."""

    def setUp(self):
        super().setUp()
        self.queue("aaa", "bbb", "ccc")
        self.cache("aaa")

    def test_a_known_next_address_is_queued_with_the_current_one(self):
        self.cache("bbb")
        self.player._start_current()
        self.assertEqual(self.engine.only("append"), [("append", signed("bbb"))])
        self.assertEqual(self.player._appended, 1)

    def test_an_unknown_next_address_is_resolved_in_the_background(self):
        self.player._start_current()
        self.assertEqual(self.engine.only("append"), [])
        self.assertEqual(len(self.player._next_resolvers), 1)
        for r in self.player._next_resolvers:
            r.cancel()
        self.player._on_next_resolved("yt:bbb", signed("bbb"))
        self.assertEqual(self.engine.only("append"), [("append", signed("bbb"))])
        self.assertEqual(self.player._appended, 1)

    def test_a_late_answer_for_a_track_no_longer_next_is_only_remembered(self):
        self.player._start_current()
        for r in self.player._next_resolvers:
            r.cancel()
        self.player._at = 2
        self.player._on_next_resolved("yt:bbb", signed("bbb"))
        self.assertEqual(self.engine.only("append"), [])
        self.assertEqual(self.player._addresses.get("yt:bbb"), signed("bbb"))

    def test_the_last_track_with_repeat_off_queues_nothing(self):
        self.player._at = 2
        self.cache("ccc")
        self.player._start_current()
        self.assertEqual(self.engine.only("append"), [])
        self.assertEqual(self.player._next_resolvers, [])

    def test_repeat_all_queues_the_first_after_the_last(self):
        self.player._at = 2
        self.cache("ccc")
        self.player.setRepeat(1)
        self.player._start_current()
        self.assertEqual(self.engine.only("append"), [("append", signed("aaa"))])

    def test_repeat_one_loops_in_mpv_instead(self):
        self.player.setRepeat(2)
        self.player._start_current()
        self.assertEqual(self.engine.only("append"), [])
        self.assertEqual(self.engine.only("loop")[-1], ("loop", True))

    def test_changing_repeat_mid_track_changes_what_is_queued(self):
        self.cache("bbb")
        self.player._start_current()
        self.player.setRepeat(2)
        self.assertEqual(self.engine.only("clear_after"), [("clear_after",)])
        self.assertIsNone(self.player._appended)
        self.player.setRepeat(0)
        self.assertEqual(self.engine.only("append"), [("append", signed("bbb"))] * 2)

    def test_shuffling_mid_track_requeues_the_new_next(self):
        self.cache("bbb", "ccc")
        self.player._start_current()
        self.player.setShuffle(True)
        self.player._order = [0, 2, 1]
        self.player._prepare_next()
        self.assertEqual(self.engine.only("append")[-1], ("append", signed("ccc")))
        self.assertEqual(self.player._appended, 2)


class MpvMovingOn(_Base):
    """When mpv reaches the end and starts what it was handed, the pointer
    follows and the one after that is prepared. Nothing is loaded, because
    mpv is already playing it."""

    def setUp(self):
        super().setUp()
        self.queue("aaa", "bbb", "ccc")
        self.cache("aaa", "bbb", "ccc")
        self.player._start_current()
        self.changed = []
        self.player.trackChanged.connect(lambda: self.changed.append(self.player.track["title"]))

    def test_the_pointer_follows(self):
        self.engine.ended.emit("eof")
        self.engine.started.emit(NEXT)
        self.assertEqual(self.player._at, 1)
        self.assertEqual(self.changed, ["bbb"])
        self.assertEqual(self.engine.only("load"), [("load", signed("aaa"), None)])

    def test_the_finished_entry_is_dropped_from_mpv_and_the_next_one_queued(self):
        self.engine.started.emit(NEXT)
        self.assertEqual(self.engine.only("remove_before"), [("remove_before",)])
        self.assertEqual(self.engine.only("append")[-1], ("append", signed("ccc")))
        self.assertEqual(self.player._appended, 2)

    def test_a_start_with_nothing_queued_is_not_an_advance(self):
        self.player._appended = None
        self.engine.started.emit(NEXT)
        self.assertEqual(self.player._at, 0)

    def test_the_end_of_the_queue_goes_quiet(self):
        self.player._at = 2
        self.player._appended = None
        self.engine.ended.emit("eof")
        self.engine.idleChanged.emit(True)
        self.assertFalse(self.player.playing)
        self.assertEqual(self.player._at, 2)
        self.assertEqual(self.player.elapsed, 0)


class Skipping(_Base):
    def setUp(self):
        super().setUp()
        self.queue("aaa", "bbb", "ccc")
        self.cache("aaa", "bbb", "ccc")
        self.player._start_current()
        self.engine.calls.clear()

    def test_next_uses_what_mpv_already_holds(self):
        self.player.next()
        self.assertEqual(self.engine.only("next"), [("next",)])
        self.assertEqual(self.engine.only("load"), [])
        # The pointer moves when mpv says it has started, not before.
        self.assertEqual(self.player._at, 0)
        self.engine.started.emit(NEXT)
        self.assertEqual(self.player._at, 1)

    def test_next_when_nothing_is_held_loads(self):
        self.player._appended = None
        self.player.next()
        self.assertEqual(self.engine.only("load"), [("load", signed("bbb"), None)])
        self.assertEqual(self.player._at, 1)

    def test_next_past_the_end_stops(self):
        self.player._at = 2
        self.player._appended = None
        self.player.next()
        self.assertEqual(self.engine.only("stop"), [("stop",)])
        self.assertEqual(self.player._at, 2)

    def test_next_under_repeat_one_still_moves_on(self):
        self.player.setRepeat(2)
        self.engine.calls.clear()
        self.player.next()
        self.assertEqual(self.player._at, 1)
        self.assertEqual(self.engine.only("load"), [("load", signed("bbb"), None)])

    def test_jumping_loads_that_track(self):
        self.player.jumpTo(2)
        self.assertEqual(self.player._at, 2)
        self.assertEqual(self.engine.only("load"), [("load", signed("ccc"), None)])

    def test_previous_early_in_a_track_goes_back(self):
        self.player._at = 1
        self.player._pos = 2.0
        self.player.previous()
        self.assertEqual(self.player._at, 0)
        self.assertEqual(self.engine.only("load"), [("load", signed("aaa"), None)])

    def test_previous_later_in_a_track_restarts_it(self):
        self.player._at = 1
        self.player._pos = 30.0
        self.player.previous()
        self.assertEqual(self.player._at, 1)
        self.assertEqual(self.engine.only("seek"), [("seek", 0.0)])

    def test_seeking_is_a_fraction_of_the_duration(self):
        self.engine.durationChanged.emit(200.0)
        self.player.seek(0.25)
        self.assertEqual(self.engine.only("seek"), [("seek", 50.0)])


class Progress(_Base):
    def setUp(self):
        super().setUp()
        self.queue("aaa")
        self.cache("aaa")
        self.player._start_current()

    def test_position_and_length_come_from_mpv(self):
        self.engine.durationChanged.emit(180.0)
        self.engine.positionChanged.emit(45.0)
        self.assertEqual(self.player.length, 180)
        self.assertEqual(self.player.elapsed, 45)
        self.assertAlmostEqual(self.player.position, 0.25)

    def test_a_live_stream_has_no_length(self):
        self.engine.durationChanged.emit(0.0)
        self.engine.positionChanged.emit(45.0)
        self.assertEqual(self.player.length, 0)
        self.assertEqual(self.player.position, 0.0)

    def test_playing_means_loaded_and_not_paused(self):
        self.assertTrue(self.player.playing)
        self.engine.pausedChanged.emit(True)
        self.assertFalse(self.player.playing)
        self.engine.pausedChanged.emit(False)
        self.assertTrue(self.player.playing)
        self.engine.idleChanged.emit(True)
        self.assertFalse(self.player.playing)


class Recovery(_Base):
    """A signed address can stop being accepted. That is recovered from, a
    bounded number of times, from the same position, and the person
    listening hears about it only when it cannot be."""

    def setUp(self):
        super().setUp()
        self.queue("aaa", "bbb")
        self.cache("aaa", "bbb")
        self.player._start_current()
        self.engine.calls.clear()
        self.reported = []
        self.player.failed.connect(self.reported.append)

    def test_an_error_fetches_a_fresh_address_and_carries_on_from_the_same_place(self):
        self.engine.positionChanged.emit(65.0)
        self.engine.ended.emit("error")
        # The old address is dropped, so a new one has to be resolved.
        self.assertIsNone(self.player._addresses.get("yt:aaa"))
        self.assertTrue(self.player.loading)
        self.player._resolver.cancel()
        self.player._on_resolved("yt:aaa", signed("aaa2"))
        self.assertEqual(self.engine.only("load"), [("load", signed("aaa2"), 65.0)])
        self.assertEqual(self.reported, [])

    def test_a_burst_of_the_same_complaint_starts_one_recovery(self):
        self.engine.ended.emit("error")
        self.engine.ended.emit("error")
        self.engine.ended.emit("error")
        self.assertEqual(self.player._recover_count, 1)
        self.assertEqual(self.reported, [])
        self.player._resolver.cancel()

    def test_it_gives_up_rather_than_looping_for_ever(self):
        import time
        for n in range(RECOVER_LIMIT):
            self.player._recover_at = time.monotonic() - RECOVER_COOLDOWN_S - 1
            self.engine.ended.emit("error")
            self.player._resolver.cancel()
        self.player._recover_at = time.monotonic() - RECOVER_COOLDOWN_S - 1
        self.engine.ended.emit("error")
        self.assertEqual(len(self.reported), 1)

    def test_a_track_playing_happily_for_a_while_gets_its_goes_back(self):
        import time
        self.player._recover_count = RECOVER_LIMIT
        self.player._recover_at = time.monotonic() - RECOVER_WINDOW_S - 1
        self.engine.ended.emit("error")
        self.assertEqual(self.player._recover_count, 1)
        self.assertEqual(self.reported, [])
        self.player._resolver.cancel()

    def test_a_different_track_is_a_clean_slate(self):
        self.player._recover_count = RECOVER_LIMIT
        self.player.jumpTo(1)
        self.assertEqual(self.player._recover_count, 0)

    def test_reaching_the_end_is_not_an_error(self):
        self.engine.ended.emit("eof")
        self.assertEqual(self.engine.only("load"), [])
        self.assertEqual(self.reported, [])

    def test_a_stall_that_never_moves_is_recovered_from(self):
        self.engine.positionChanged.emit(20.0)
        self.engine.bufferingChanged.emit(True)
        self.assertTrue(self.player._stall_timer.isActive())
        self.player._stall_timer.stop()
        self.player._on_stalled_too_long()
        self.assertTrue(self.player.loading)
        self.player._resolver.cancel()

    def test_buffering_that_comes_back_is_left_alone(self):
        self.engine.bufferingChanged.emit(True)
        self.engine.bufferingChanged.emit(False)
        self.assertFalse(self.player._stall_timer.isActive())
        self.player._on_stalled_too_long()
        self.assertFalse(self.player.loading)

    def test_the_player_going_away_is_said_out_loud(self):
        self.engine.gone.emit("mpv went away")
        self.assertEqual(self.reported, ["mpv went away"])
        self.assertFalse(self.player.playing)


class Fading(_Base):
    def setUp(self):
        super().setUp()
        self.player.setVolume(60)
        self.queue("aaa")
        self.cache("aaa")
        self.player._start_current()

    def test_the_reported_volume_is_what_was_asked_for(self):
        # Not whatever level a fade happens to be passing through.
        self.player._set_output(0.02)
        self.assertEqual(self.player.volume, 60)

    def test_pausing_for_a_video_fades_rather_than_cuts(self):
        self.player.pause_for_video()
        self.assertTrue(self.player._fade.state() != self.player._fade.State.Stopped
                        or self.player._pause_after_fade)
        self.assertEqual(self.engine.only("pause")[-1], ("pause", False), "not paused yet")

    def test_setting_the_volume_stops_a_fade(self):
        self.player._fade_to(0.0, pause_after=True)
        self.player.setVolume(30)
        self.assertFalse(self.player._pause_after_fade)
        self.assertEqual(self.player.volume, 30)

    def test_the_volume_stays_down_once_the_fade_has_paused_it(self):
        """The blip at the end of a fade. Pausing takes a moment, so putting
        the level back the moment it is asked for plays whatever is still in
        the buffer at full volume. It is raised again by whatever starts
        playing next instead."""
        self.player._pause_after_fade = True
        self.player._set_output(0.0)
        self.player._on_fade_done()
        self.assertEqual(self.engine.only("pause")[-1], ("pause", True))
        self.assertEqual(self.engine.volume, 0.0)
        self.assertEqual(self.player.volume, 60)

    def test_resuming_comes_back_up_rather_than_arriving_at_full_volume(self):
        self.player._paused = True
        self.player._set_output(0.0)
        self.player.toggle()
        self.assertEqual(self.engine.only("pause")[-1], ("pause", False))
        self.assertNotEqual(self.player._fade.state(), self.player._fade.State.Stopped)

    def test_toggling_when_idle_starts_the_track(self):
        self.engine.idleChanged.emit(True)
        self.engine.calls.clear()
        self.player.toggle()
        self.assertEqual(self.engine.only("load"), [("load", signed("aaa"), None)])


class Addresses(unittest.TestCase):
    def test_the_expiry_is_read_out_of_the_address(self):
        self.assertEqual(address_expiry(signed("a", expire=1788631030)), 1788631030.0)
        self.assertIsNone(address_expiry("https://x/playlist.m3u8"))

    def test_an_address_is_kept_until_shortly_before_it_expires(self):
        clock = [1000.0]
        cache = AddressCache(now=lambda: clock[0])
        cache.put("k", signed("a", expire=int(1000 + ADDRESS_MARGIN_S + 100)))
        self.assertIsNotNone(cache.get("k"))
        clock[0] += 150
        self.assertIsNone(cache.get("k"), "too close to expiring to be worth handing over")

    def test_one_without_an_expiry_is_kept(self):
        cache = AddressCache(now=lambda: 5.0)
        cache.put("k", "https://x/thing")
        self.assertEqual(cache.get("k"), "https://x/thing")

    def test_dropping(self):
        cache = AddressCache()
        cache.put("k", signed("a"))
        cache.drop("k")
        self.assertIsNone(cache.get("k"))


if __name__ == "__main__":
    unittest.main()
