"""The screen kept on while the window's video plays, and let go otherwise.

The desktop is a stand in here that records what was asked of it; the real
session bus is only asked whether it is there."""

import unittest

from PySide6.QtCore import QCoreApplication, QObject, Signal

from weave import awake

_app = QCoreApplication.instance() or QCoreApplication([])


class FakeVideo(QObject):
    stateChanged = Signal()
    videoChanged = Signal()

    def __init__(self):
        super().__init__()
        self.playing = False
        self.videoShowing = False

    def set(self, playing=None, showing=None):
        if playing is not None:
            self.playing = playing
        if showing is not None:
            self.videoShowing = showing
        self.stateChanged.emit()
        self.videoChanged.emit()


class FakeBus:
    def __init__(self, connects=True):
        self.connects = connects
        self.opened = []
        self.closed = []
        self.waiting = {}

    def open(self):
        if not self.connects:
            return ""
        name = f"hold-{len(self.opened) + 1}"
        self.opened.append(name)
        return name

    def inhibit(self, name, done):
        self.waiting[name] = done

    def answer(self, name, ok=True):
        self.waiting.pop(name)(ok)

    def close(self, name):
        self.closed.append(name)


class KeepingTheScreenOn(unittest.TestCase):
    def setUp(self):
        self.video = FakeVideo()
        self.bus = FakeBus()
        self.keeper = awake.KeepAwake(self.video, bus=self.bus)

    def test_nothing_is_held_before_a_video_plays(self):
        self.assertEqual((self.bus.opened, self.keeper.holding), ([], False))

    def test_a_video_playing_holds_it_once(self):
        self.video.set(playing=True, showing=True)
        self.video.set(playing=True, showing=True)
        self.assertEqual(self.bus.opened, ["hold-1"])
        self.bus.answer("hold-1")
        self.assertTrue(self.keeper.holding)

    def test_sound_with_no_picture_yet_holds_nothing(self):
        self.video.set(playing=True, showing=False)
        self.assertEqual(self.bus.opened, [])

    def test_pausing_lets_go_and_playing_again_holds_again(self):
        self.video.set(playing=True, showing=True)
        self.bus.answer("hold-1")
        self.video.set(playing=False)
        self.assertEqual((self.bus.closed, self.keeper.holding), (["hold-1"], False))
        self.video.set(playing=True)
        self.assertEqual(self.bus.opened, ["hold-1", "hold-2"])

    def test_let_go_of_while_the_desktop_answers_stays_let_go(self):
        self.video.set(playing=True, showing=True)
        self.video.set(playing=False)
        self.bus.answer("hold-1")
        self.assertEqual((self.bus.closed, self.keeper.holding), (["hold-1"], False),
                         "the connection that asked is gone, and the hold with it")

    def test_a_refusal_is_not_asked_again_until_the_video_stops(self):
        self.video.set(playing=True, showing=True)
        self.bus.answer("hold-1", ok=False)
        self.video.set(playing=True, showing=True)
        self.assertEqual((self.bus.opened, self.bus.closed), (["hold-1"], ["hold-1"]))
        self.video.set(playing=False)
        self.video.set(playing=True)
        self.assertEqual(self.bus.opened, ["hold-1", "hold-2"], "a new start asks again")

    def test_no_bus_to_ask_on_is_no_hold_and_no_retrying(self):
        bus = FakeBus(connects=False)
        video = FakeVideo()
        keeper = awake.KeepAwake(video, bus=bus)
        video.set(playing=True, showing=True)
        video.set(playing=True, showing=True)
        self.assertFalse(keeper.holding)

    def test_shutting_down_lets_go(self):
        self.video.set(playing=True, showing=True)
        self.bus.answer("hold-1")
        self.keeper.shutdown()
        self.assertEqual(self.bus.closed, ["hold-1"])
