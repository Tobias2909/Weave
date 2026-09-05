"""Walking back and forward through the views.

The record is plain Python and is tested as such. What it is worth testing at
all is the rules a browser has taught everybody to expect: landing on the same
place twice is one place, walking back is not itself a step, and going
somewhere new from halfway back throws the rest away.

The bridge half is driven through the one method every view change goes
through, so what is asserted is the real path rather than a rehearsal of it.
The bridge is built with __new__ and given only the attributes that path
touches, which is the pattern the worker tests already use, because a real one
would want a database, a window and mpv for a question about a list.
"""

import unittest

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from weave.ui.navigation import (
    TRACK_LISTS,
    History,
    MouseNavigation,
    MusicList,
    TrackCache,
)

_app = QCoreApplication.instance() or QCoreApplication([])

ALL = ("all", -1, "", "", None)
GROUP = ("group", 3, "", "", None)
CHANNEL = ("channel", -1, "yt:UC1", "", None)
MUSIC = ("music", -1, "", "", None)
SEARCH = ("search", -1, "", "", None)

# The two things the music view can be showing besides its shelves.
MIX = MusicList("playlist", "PL1", "A mix")
STATION = MusicList("radio", "vid1", "A song")
FOUND = MusicList("search", "otters", "Search results")


def in_music(what: MusicList) -> tuple:
    return ("music", -1, "", "", what)


def track(name: str) -> dict:
    return {"key": f"yt:{name}", "videoId": name, "title": name, "artist": "",
            "album": "", "duration": 0, "thumbnail": ""}


class Recorder:
    """A signal that only counts, so a bridge built with __new__ can emit."""

    def __init__(self):
        self.count = 0

    def emit(self, *_a):
        self.count += 1


def make_bridge():
    """A bridge with exactly what _set_view and the walking touch."""
    from weave.ui.bridge import Bridge

    bridge = Bridge.__new__(Bridge)
    bridge._view_kind, bridge._view_id = "all", -1
    bridge._view_channel, bridge._view_playlist = "", ""
    bridge._search_text = ""
    bridge._search_scope = "stored"
    bridge._shelves = [1]                    # so entering music fetches nothing
    bridge._checks = [1]
    bridge._exhausted = False
    bridge._nav = History(ALL)
    bridge._nav_replaying = False
    bridge._music_list = None
    bridge._music_cache = TrackCache()
    bridge._music_autoplay = None
    bridge._results = []
    bridge._results_label = ""
    bridge._searching = False
    bridge.viewChanged = Recorder()
    bridge.searchEnded = Recorder()
    bridge.navChanged = Recorder()
    bridge.musicChanged = Recorder()
    bridge.reload = lambda: None
    bridge._fetch_recommended = lambda *a, **k: None
    bridge._fetch_history = lambda *a, **k: None
    bridge._fetch_playlist_items = lambda *a, **k: None
    # Every list the bridge asked YouTube Music for, so a restore from memory
    # can be told apart from a fetch. The real one builds a worker.
    bridge.fetched = []
    bridge._fetch_music_list = bridge.fetched.append
    bridge.played = []
    bridge.playResult = bridge.played.append
    return bridge


def view_of(bridge):
    return (bridge._view_kind, bridge._view_id, bridge._view_channel, bridge._view_playlist,
            bridge._music_list if bridge._view_kind == "music" else None)


class TheRecord(unittest.TestCase):
    def test_it_starts_on_the_view_it_was_given(self):
        record = History(ALL)
        self.assertEqual(record.current().view, ALL)
        self.assertFalse(record.can_go_back())
        self.assertFalse(record.can_go_forward())

    def test_landing_somewhere_new_is_a_step(self):
        record = History(ALL)
        self.assertTrue(record.record(MUSIC))
        self.assertEqual([e.view for e in record.entries], [ALL, MUSIC])
        self.assertTrue(record.can_go_back())

    def test_the_same_view_twice_is_one_entry(self):
        record = History(ALL)
        record.record(MUSIC)
        self.assertFalse(record.record(MUSIC))
        self.assertEqual([e.view for e in record.entries], [ALL, MUSIC])

    def test_back_and_forward_walk_the_whole_way(self):
        record = History(ALL)
        for view in (GROUP, CHANNEL, MUSIC):
            record.record(view)
        self.assertEqual(record.back().view, CHANNEL)
        self.assertEqual(record.back().view, GROUP)
        self.assertEqual(record.forward().view, CHANNEL)
        self.assertEqual(record.forward().view, MUSIC)
        self.assertFalse(record.can_go_forward())

    def test_walking_back_adds_nothing(self):
        record = History(ALL)
        record.record(MUSIC)
        record.back()
        self.assertEqual([e.view for e in record.entries], [ALL, MUSIC])

    def test_the_far_ends_hand_back_nothing(self):
        record = History(ALL)
        self.assertIsNone(record.back())
        record.record(MUSIC)
        self.assertIsNone(record.forward())

    def test_going_somewhere_new_drops_the_forward_branch(self):
        record = History(ALL)
        record.record(GROUP)
        record.record(CHANNEL)
        record.back()
        record.record(MUSIC)
        self.assertEqual([e.view for e in record.entries], [ALL, GROUP, MUSIC])
        self.assertFalse(record.can_go_forward())

    def test_the_oldest_entries_go_once_it_is_full(self):
        record = History(ALL, limit=3)
        for index in range(4):
            record.record(("group", index, "", ""))
        self.assertEqual([e.view[1] for e in record.entries], [1, 2, 3])
        self.assertEqual(record.index, 2)
        self.assertEqual(record.back().view[1], 2)

    def test_a_search_keeps_its_words(self):
        record = History(ALL)
        record.record(SEARCH, "otters")
        record.note_search("otters swimming")
        record.record(ALL)
        self.assertEqual(record.back().search_text, "otters swimming")


class TheBridgeWalk(unittest.TestCase):
    def test_a_walk_then_back_back_forward_forward(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge._set_view(bridge, "group", 3)
        Bridge._set_view(bridge, "channel", -1, "yt:UC1")
        Bridge._set_view(bridge, "music", -1)

        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), CHANNEL)
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), GROUP)
        Bridge.goForward(bridge)
        self.assertEqual(view_of(bridge), CHANNEL)
        Bridge.goForward(bridge)
        self.assertEqual(view_of(bridge), MUSIC)

    def test_setting_the_same_view_twice_records_one_entry(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge._set_view(bridge, "music", -1)
        Bridge._set_view(bridge, "music", -1)
        self.assertEqual([e.view for e in bridge._nav.entries], [ALL, MUSIC])
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), ALL)

    def test_going_back_does_not_push(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge._set_view(bridge, "group", 3)
        Bridge._set_view(bridge, "music", -1)
        Bridge.goBack(bridge)
        Bridge.goBack(bridge)
        self.assertEqual([e.view for e in bridge._nav.entries], [ALL, GROUP, MUSIC])
        self.assertEqual(view_of(bridge), ALL)
        self.assertFalse(Bridge._get_can_go_back(bridge))
        self.assertTrue(Bridge._get_can_go_forward(bridge))

    def test_a_new_view_after_going_back_drops_the_forward_branch(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge._set_view(bridge, "group", 3)
        Bridge._set_view(bridge, "channel", -1, "yt:UC1")
        Bridge.goBack(bridge)
        Bridge._set_view(bridge, "music", -1)
        self.assertFalse(Bridge._get_can_go_forward(bridge))
        Bridge.goForward(bridge)
        self.assertEqual(view_of(bridge), MUSIC)
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), GROUP)

    def test_the_stack_cap_holds(self):
        from weave.ui.bridge import Bridge
        from weave.ui import navigation

        bridge = make_bridge()
        for index in range(navigation.LIMIT + 20):
            Bridge._set_view(bridge, "group", index)
        self.assertEqual(len(bridge._nav.entries), navigation.LIMIT)
        for _ in range(navigation.LIMIT * 2):
            Bridge.goBack(bridge)
        # The oldest that survived, and no further, whatever was asked for.
        self.assertEqual(view_of(bridge), ("group", 20, "", "", None))

    def test_a_search_walked_back_to_brings_its_words(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        bridge._search_text = "otters"
        Bridge._set_view(bridge, "search", -1)
        Bridge._set_view(bridge, "music", -1)
        self.assertEqual(bridge._search_text, "")      # leaving a search ends it
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), SEARCH)
        self.assertEqual(bridge._search_text, "otters")
        self.assertEqual(bridge._search_scope, "stored")

    def test_the_notify_signal_fires_when_the_record_changes(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge._set_view(bridge, "music", -1)
        self.assertEqual(bridge.navChanged.count, 1)
        Bridge._set_view(bridge, "music", -1)
        self.assertEqual(bridge.navChanged.count, 1, "a view already showing said something changed")
        Bridge.goBack(bridge)
        self.assertEqual(bridge.navChanged.count, 2)


class TheTrackCache(unittest.TestCase):
    """What is held of the music lists that were visited."""

    def test_it_hands_back_the_rows_and_the_heading(self):
        cache = TrackCache()
        cache.put(MIX, [track("a")], "A mix, 1 of 2 still playable")
        rows, label = cache.get(MIX)
        self.assertEqual([row["title"] for row in rows], ["a"])
        self.assertEqual(label, "A mix, 1 of 2 still playable")

    def test_a_list_never_visited_is_not_held(self):
        cache = TrackCache()
        self.assertIsNone(cache.get(MIX))
        self.assertNotIn(MIX, cache)

    def test_it_holds_only_so_many(self):
        cache = TrackCache()
        lists = [MusicList("playlist", f"PL{i}", f"Mix {i}") for i in range(TRACK_LISTS + 2)]
        for one in lists:
            cache.put(one, [track("a")], one.label)
        self.assertEqual(len(cache), TRACK_LISTS)
        self.assertNotIn(lists[0], cache)
        self.assertNotIn(lists[1], cache)
        self.assertIn(lists[-1], cache)

    def test_reading_a_list_keeps_it_from_being_dropped(self):
        cache = TrackCache(limit=2)
        first = MusicList("playlist", "PL1", "One")
        second = MusicList("playlist", "PL2", "Two")
        third = MusicList("playlist", "PL3", "Three")
        cache.put(first, [], "One")
        cache.put(second, [], "Two")
        cache.get(first)                     # walked back onto, so still wanted
        cache.put(third, [], "Three")
        self.assertIn(first, cache)
        self.assertNotIn(second, cache)


class TheMusicPlaces(unittest.TestCase):
    """A track list inside the music view is a place like any other.

    The bridge is driven through the methods the interface calls, and the rows
    are handed to the same method the worker's signal reaches, so nothing here
    asks YouTube Music for anything.
    """

    def open_mix(self, bridge):
        """Into music, onto a list, with its rows arrived."""
        from weave.ui.bridge import Bridge

        Bridge.showMusic(bridge)
        Bridge._open_music_list(bridge, MIX)
        Bridge._on_tracks(bridge, [track("a"), track("b")], "A mix", MIX)

    def test_opening_a_list_is_a_step_of_its_own(self):
        bridge = make_bridge()
        self.open_mix(bridge)
        self.assertEqual(view_of(bridge), in_music(MIX))
        self.assertEqual([e.view for e in bridge._nav.entries], [ALL, MUSIC, in_music(MIX)])
        self.assertEqual(bridge.fetched, [MIX])
        self.assertEqual(bridge._results_label, "A mix")

    def test_back_returns_to_the_shelves_and_forward_opens_the_list(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        self.open_mix(bridge)
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), MUSIC)
        # The shelves are what the view shows when there are no results.
        self.assertEqual(bridge._results, [])
        self.assertEqual(bridge._results_label, "")
        Bridge.goForward(bridge)
        self.assertEqual(view_of(bridge), in_music(MIX))
        self.assertEqual([row["title"] for row in bridge._results], ["a", "b"])
        self.assertEqual(bridge._results_label, "A mix")

    def test_a_list_walked_back_onto_comes_from_memory(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        self.open_mix(bridge)
        Bridge.goBack(bridge)
        Bridge.goForward(bridge)
        self.assertEqual(bridge.fetched, [MIX], "the list was asked for a second time")

    def test_a_list_no_longer_held_is_asked_for_again(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        bridge._music_cache = TrackCache(limit=1)
        self.open_mix(bridge)
        other = MusicList("playlist", "PL2", "Another mix")
        Bridge._open_music_list(bridge, other)
        Bridge._on_tracks(bridge, [track("c")], "Another mix", other)
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), in_music(MIX))
        self.assertEqual(bridge.fetched, [MIX, other, MIX])

    def test_a_search_is_a_step_and_back_returns_to_the_shelves(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge.showMusic(bridge)
        Bridge.musicSearch(bridge, "otters")
        self.assertEqual(bridge.fetched, [FOUND])
        Bridge._on_results(bridge, [track("a")], FOUND)
        self.assertEqual(view_of(bridge), in_music(FOUND))
        self.assertEqual(bridge._results_label, "Search results")
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), MUSIC)
        self.assertEqual(bridge._results, [])
        Bridge.goForward(bridge)
        self.assertEqual([row["title"] for row in bridge._results], ["a"])

    def test_an_empty_search_is_not_a_place(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge.showMusic(bridge)
        Bridge.musicSearch(bridge, "   ")
        self.assertEqual([e.view for e in bridge._nav.entries], [ALL, MUSIC])
        self.assertEqual(bridge.fetched, [])

    def test_a_search_that_replaces_another_is_its_own_step(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge.showMusic(bridge)
        Bridge.musicSearch(bridge, "otters")
        Bridge._on_results(bridge, [track("a")], FOUND)
        again = MusicList("search", "seals", "Search results")
        Bridge.musicSearch(bridge, "seals")
        Bridge._on_results(bridge, [track("b")], again)
        self.assertEqual([e.view for e in bridge._nav.entries],
                         [ALL, MUSIC, in_music(FOUND), in_music(again)])
        Bridge.goBack(bridge)
        self.assertEqual([row["title"] for row in bridge._results], ["a"])
        self.assertEqual(bridge.fetched, [FOUND, again], "the first search ran twice")

    def test_the_way_back_to_the_shelves_is_a_step(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        self.open_mix(bridge)
        Bridge.clearResults(bridge)
        self.assertEqual(view_of(bridge), MUSIC)
        self.assertEqual(bridge._results, [])
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), in_music(MIX))
        self.assertEqual([row["title"] for row in bridge._results], ["a", "b"])

    def test_leaving_music_and_coming_back_lands_on_the_list_again(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        self.open_mix(bridge)
        Bridge._set_view(bridge, "all", -1)
        self.assertEqual(view_of(bridge), ALL)
        Bridge.showMusic(bridge)
        self.assertEqual(view_of(bridge), in_music(MIX))
        self.assertEqual([row["title"] for row in bridge._results], ["a", "b"])
        self.assertEqual(bridge.fetched, [MIX], "coming back asked for the list again")
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), ALL)

    def test_the_same_list_pressed_twice_is_one_place(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        self.open_mix(bridge)
        Bridge._open_music_list(bridge, MIX)
        self.assertEqual([e.view for e in bridge._nav.entries], [ALL, MUSIC, in_music(MIX)])
        self.assertEqual(bridge.fetched, [MIX])

    def test_playing_a_track_is_not_a_step(self):
        from weave.ui.bridge import Bridge

        class Audio:
            def __init__(self):
                self.queued = []

            def play_items(self, items, start=0):
                self.queued.append((len(items), start))

        bridge = make_bridge()
        self.open_mix(bridge)
        del bridge.playResult                # the real one, since that is the question
        bridge._audio = Audio()
        before = [e.view for e in bridge._nav.entries]
        Bridge.playResult(bridge, 1)
        self.assertEqual(bridge._audio.queued, [(2, 1)])
        self.assertEqual([e.view for e in bridge._nav.entries], before)

    def test_a_station_starts_when_pressed_and_not_when_walked_onto(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge.showMusic(bridge)
        Bridge._open_music_list(bridge, STATION, autoplay=True)
        Bridge._on_tracks(bridge, [track("a"), track("b")], "A song", STATION)
        self.assertEqual(bridge.played, [0], "a station did not start on its own")
        Bridge.clearResults(bridge)
        Bridge.goBack(bridge)
        self.assertEqual(view_of(bridge), in_music(STATION))
        self.assertEqual(bridge.played, [0], "walking onto a station started it playing")

    def test_a_list_that_arrives_after_walking_away_is_held_not_shown(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge()
        Bridge.showMusic(bridge)
        Bridge._open_music_list(bridge, MIX)
        Bridge.goBack(bridge)                # away before the rows land
        Bridge._on_tracks(bridge, [track("a")], "A mix", MIX)
        self.assertEqual(bridge._results, [])
        self.assertEqual(view_of(bridge), MUSIC)
        Bridge.goForward(bridge)
        self.assertEqual([row["title"] for row in bridge._results], ["a"])
        self.assertEqual(bridge.fetched, [MIX], "the rows were dropped rather than held")


class TheMouseButtons(unittest.TestCase):
    """The event filter itself, fed the events Qt would feed it."""

    class Bridge:
        def __init__(self):
            self.calls = []

        def goBack(self):
            self.calls.append("back")

        def goForward(self):
            self.calls.append("forward")

    def press(self, button):
        where = QPointF(1, 1)
        return QMouseEvent(QEvent.Type.MouseButtonPress, where, where, button, button,
                           Qt.KeyboardModifier.NoModifier)

    def test_the_back_button_goes_back_and_is_eaten(self):
        bridge = self.Bridge()
        nav = MouseNavigation(bridge)
        eaten = nav.eventFilter(nav, self.press(Qt.MouseButton.BackButton))
        self.assertEqual(bridge.calls, ["back"])
        self.assertTrue(eaten, "the press was passed on as well as acted on")

    def test_the_forward_button_goes_forward(self):
        bridge = self.Bridge()
        nav = MouseNavigation(bridge)
        self.assertTrue(nav.eventFilter(nav, self.press(Qt.MouseButton.ForwardButton)))
        self.assertEqual(bridge.calls, ["forward"])

    def test_an_ordinary_click_is_left_alone(self):
        bridge = self.Bridge()
        nav = MouseNavigation(bridge)
        self.assertFalse(nav.eventFilter(nav, self.press(Qt.MouseButton.LeftButton)))
        self.assertEqual(bridge.calls, [])

    def test_a_press_after_the_window_goes_reaches_nothing(self):
        bridge = self.Bridge()
        nav = MouseNavigation(bridge)
        nav.stop()
        self.assertFalse(nav.eventFilter(nav, self.press(Qt.MouseButton.BackButton)))
        self.assertEqual(bridge.calls, [])


if __name__ == "__main__":
    unittest.main()
