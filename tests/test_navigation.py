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

from weave.ui.navigation import History, MouseNavigation

_app = QCoreApplication.instance() or QCoreApplication([])

ALL = ("all", -1, "", "")
GROUP = ("group", 3, "", "")
CHANNEL = ("channel", -1, "yt:UC1", "")
MUSIC = ("music", -1, "", "")
SEARCH = ("search", -1, "", "")


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
    bridge.viewChanged = Recorder()
    bridge.searchEnded = Recorder()
    bridge.navChanged = Recorder()
    bridge.reload = lambda: None
    bridge._fetch_recommended = lambda *a, **k: None
    bridge._fetch_history = lambda *a, **k: None
    bridge._fetch_playlist_items = lambda *a, **k: None
    return bridge


def view_of(bridge):
    return (bridge._view_kind, bridge._view_id, bridge._view_channel, bridge._view_playlist)


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
        self.assertEqual(view_of(bridge), ("group", 20, "", ""))

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
