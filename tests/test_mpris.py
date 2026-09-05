"""The music player on MPRIS.

The mapping is checked here without a bus. What the desktop actually reads is
checked against the real session bus at the bottom, which is skipped where
there is none, and the player underneath is the same stand in `test_audio.py`
drives, so nothing here reaches for a subprocess either.
"""

import contextlib
import io
import os
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtDBus import QDBus, QDBusArgument, QDBusConnection, QDBusMessage, QDBusObjectPath

from tests.test_audio import FakeEngine, FakeResolver, signed, track
from weave import mpris
from weave.audio import AudioPlayer
from weave.config import Config
from weave.engine import NEXT

_app = QCoreApplication.instance() or QCoreApplication([])

PLAYER = "org.mpris.MediaPlayer2.Player"


def has_session_bus() -> bool:
    return QDBusConnection.sessionBus().isConnected()


class FakeBus:
    """Records what would have gone out, so announcing can be read back."""

    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)
        return True


def build_player(*names):
    """A player with a queue, playing, that never resolves anything."""
    engine = FakeEngine()
    player = AudioPlayer(Config(raw={}), engine=engine)
    player._make_resolver = lambda entry: FakeResolver(entry["key"])
    player.setShuffle(False)
    player.setRepeat(0)
    for name in names:
        player._addresses.put(f"yt:{name}", signed(name))
    if names:
        player.play_items([track(name) for name in names])
    return player, engine


class _Base(unittest.TestCase):
    def setUp(self):
        self.player, self.engine = build_player("aaa", "bbb", "ccc")
        self.engine.durationChanged.emit(212.0)
        self.bus = FakeBus()
        self.adapter = mpris.MprisAdapter(self.player, self.bus)
        self.root = self.adapter._root
        self.mpris = self.adapter._player


class Metadata(unittest.TestCase):
    def test_a_track_becomes_what_the_panel_draws(self):
        found = mpris.metadata(track("aaa"), 212)
        self.assertEqual(found["xesam:title"], "aaa")
        self.assertEqual(found["xesam:artist"], ["someone"])
        self.assertEqual(found["mpris:length"], 212_000_000, "microseconds, not seconds")

    def test_nothing_playing_is_an_empty_map(self):
        self.assertEqual(mpris.metadata({}, 0), {})

    def test_a_length_that_is_not_known_yet_is_left_out(self):
        # A reader draws a zero as a zero length track rather than as unknown.
        self.assertNotIn("mpris:length", mpris.metadata(track("aaa"), 0))

    def test_a_field_that_is_empty_is_left_out(self):
        bare = {"key": "yt:aaa", "title": "aaa", "artist": "", "thumbnail": ""}
        found = mpris.metadata(bare, 0)
        self.assertNotIn("xesam:artist", found)
        self.assertNotIn("mpris:artUrl", found)

    def test_a_picture_is_passed_on_as_it_is(self):
        entry = dict(track("aaa"), thumbnail="https://example/a.jpg")
        self.assertEqual(mpris.metadata(entry, 1)["mpris:artUrl"], "https://example/a.jpg")

    def test_a_queue_key_becomes_a_path_the_bus_accepts(self):
        # `yt:aaa` has a colon in it, which no object path may have.
        path = mpris.metadata(track("aaa"), 0)["mpris:trackid"]
        self.assertIsInstance(path, QDBusObjectPath)
        self.assertTrue(path.path().endswith("/yt_aaa"))
        self.assertTrue(all(c.isalnum() or c in "_/" for c in path.path()))

    def test_two_tracks_do_not_share_one_path(self):
        first = mpris.metadata(track("aaa"), 0)["mpris:trackid"].path()
        second = mpris.metadata(track("bbb"), 0)["mpris:trackid"].path()
        self.assertNotEqual(first, second)


class Controls(_Base):
    def test_playpause_pauses_what_is_playing(self):
        self.mpris.PlayPause()
        # Pausing fades first, exactly as the button in the window does.
        self.assertTrue(self.player._pause_after_fade)
        self.player._on_fade_done()
        self.assertEqual(self.engine.only("pause")[-1], ("pause", True))

    def test_play_leaves_what_is_already_playing_alone(self):
        self.engine.calls.clear()
        self.mpris.Play()
        self.assertEqual(self.engine.calls, [], "a second play must not pause it")

    def test_pause_leaves_what_is_already_paused_alone(self):
        self.mpris.PlayPause()
        self.player._on_fade_done()
        self.engine.calls.clear()
        self.mpris.Pause()
        self.assertEqual(self.engine.calls, [])

    def test_play_starts_what_is_paused(self):
        self.mpris.PlayPause()
        self.player._on_fade_done()
        self.mpris.Play()
        self.assertEqual(self.engine.only("pause")[-1], ("pause", False))

    def test_next_moves_on(self):
        self.mpris.Next()
        # The one after this is already open in mpv, so the pointer follows
        # when mpv says it has started.
        self.engine.started.emit(NEXT)
        self.assertEqual(self.player.track["title"], "bbb")

    def test_previous_goes_back(self):
        self.mpris.Next()
        self.engine.started.emit(NEXT)
        self.mpris.Previous()
        self.assertEqual(self.player.track["title"], "aaa")

    def test_stop_empties_the_queue(self):
        self.mpris.Stop()
        self.assertEqual(self.player.track, {})
        self.assertEqual(self.engine.only("stop"), [("stop",)])

    def test_the_volume_is_a_fraction_on_the_bus(self):
        self.player.setVolume(40)
        self.assertAlmostEqual(self.mpris.Volume, 0.4)

    def test_setting_the_volume_reaches_the_player(self):
        self.mpris.Volume = 0.25
        self.assertEqual(self.player.volume, 25)
        self.assertEqual(self.engine.volume, 25.0)

    def test_a_volume_outside_the_range_is_brought_back_in(self):
        self.mpris.Volume = 4.0
        self.assertEqual(self.player.volume, 100)
        self.mpris.Volume = -1.0
        self.assertEqual(self.player.volume, 0)


class WhatIsReadBack(_Base):
    def test_playing(self):
        self.assertEqual(self.mpris.PlaybackStatus, "Playing")

    def test_paused(self):
        self.mpris.PlayPause()
        self.player._on_fade_done()
        self.assertEqual(self.mpris.PlaybackStatus, "Paused")

    def test_nothing_in_the_queue_is_stopped(self):
        self.mpris.Stop()
        self.assertEqual(self.mpris.PlaybackStatus, "Stopped")

    def test_the_position_is_in_microseconds(self):
        self.engine.positionChanged.emit(12.0)
        self.assertEqual(self.mpris.Position, 12_000_000)

    def test_the_controls_are_off_with_nothing_to_control(self):
        self.mpris.Stop()
        for name in ("CanGoNext", "CanGoPrevious", "CanPlay", "CanPause"):
            self.assertFalse(getattr(self.mpris, name), name)

    def test_the_controls_are_on_with_a_queue(self):
        for name in ("CanGoNext", "CanGoPrevious", "CanPlay", "CanPause", "CanControl"):
            self.assertTrue(getattr(self.mpris, name), name)


class TheApplicationItself(_Base):
    def test_it_says_which_desktop_file_is_its_own(self):
        shipped = Path(__file__).resolve().parent.parent / f"{mpris.DESKTOP_ENTRY}.desktop"
        self.assertTrue(shipped.is_file(), "the name has to match the file that ships")

    def test_it_names_itself(self):
        self.assertEqual(self.root.Identity, "Weave")

    def test_it_has_no_track_list(self):
        self.assertFalse(self.root.HasTrackList)

    def test_raising_is_off_until_something_can_do_it(self):
        self.assertFalse(self.root.CanRaise)
        self.root.Raise()          # and does nothing rather than failing

    def test_raising_reaches_what_was_handed_over(self):
        asked = []
        adapter = mpris.MprisAdapter(self.player, self.bus, on_raise=lambda: asked.append(1))
        self.assertTrue(adapter._root.CanRaise)
        adapter._root.Raise()
        self.assertEqual(len(asked), 1)

    def test_quitting_reaches_what_was_handed_over(self):
        asked = []
        adapter = mpris.MprisAdapter(self.player, self.bus, on_quit=lambda: asked.append(1))
        adapter._root.Quit()
        self.assertEqual(len(asked), 1)


class Announcing(_Base):
    """Without this the panel keeps the first title it read, since nothing
    polls a player that can tell it instead."""

    def one(self, index=-1):
        message = self.bus.sent[index]
        interface, changed, invalidated = message.arguments()
        return interface, changed, invalidated

    def test_a_new_track_is_announced(self):
        self.bus.sent.clear()
        self.mpris.Next()
        self.engine.started.emit(NEXT)
        interface, changed, _ = self.one()
        self.assertEqual(interface, PLAYER)
        self.assertEqual(changed["Metadata"]["xesam:title"], "bbb")

    def test_pausing_is_announced(self):
        self.bus.sent.clear()
        self.mpris.PlayPause()
        self.player._on_fade_done()
        self.assertEqual(self.one()[1]["PlaybackStatus"], "Paused")

    def test_only_what_changed_goes_out(self):
        self.bus.sent.clear()
        self.player.setVolume(30)
        self.assertEqual(list(self.one()[1]), ["Volume"], "a title that did not change is noise")

    def test_nothing_is_said_when_nothing_changed(self):
        self.bus.sent.clear()
        self.player.stateChanged.emit()
        self.player.trackChanged.emit()
        self.assertEqual(self.bus.sent, [])

    def test_the_signal_is_the_one_a_reader_listens_for(self):
        self.bus.sent.clear()
        self.player.setVolume(30)
        message = self.bus.sent[-1]
        self.assertEqual(message.path(), mpris.OBJECT_PATH)
        self.assertEqual(message.interface(), "org.freedesktop.DBus.Properties")
        self.assertEqual(message.member(), "PropertiesChanged")

    def test_the_list_of_names_to_read_again_keeps_its_element_type(self):
        """An empty Python list has no element type left to marshal, so it
        goes out as an array of variants, and every glib reader checks the
        whole signature and drops the signal."""
        self.bus.sent.clear()
        self.player.setVolume(30)
        invalidated = self.one()[2]
        self.assertIsInstance(invalidated, QDBusArgument)
        self.assertEqual(invalidated.currentSignature(), "as")


@unittest.skipUnless(has_session_bus(), "no session bus to publish on")
class OnTheRealBus(unittest.TestCase):
    """The same calls the desktop makes, over the bus it makes them on.

    A name of its own, so a running Weave keeps its own and is not disturbed.
    """

    def setUp(self):
        self.name = mpris.BUS_NAME
        mpris.BUS_NAME = f"org.mpris.MediaPlayer2.weavetest{os.getpid()}"
        self.player, self.engine = build_player("aaa", "bbb")
        self.adapter = mpris.install(self.player)
        self.bus = QDBusConnection.sessionBus()

    def tearDown(self):
        self.bus.unregisterObject(mpris.OBJECT_PATH)
        self.bus.unregisterService(mpris.BUS_NAME)
        mpris.BUS_NAME = self.name
        self.player.shutdown()

    def call(self, interface, method, arguments=None):
        message = QDBusMessage.createMethodCall(mpris.BUS_NAME, mpris.OBJECT_PATH,
                                                interface, method)
        if arguments:
            message.setArguments(arguments)
        # Blocking here would otherwise wait on a reply this same process has
        # to send, so the loop keeps turning while it waits.
        return self.bus.call(message, QDBus.CallMode.BlockWithGui, 5000)

    def get(self, name):
        reply = self.call("org.freedesktop.DBus.Properties", "Get", [PLAYER, name])
        self.assertEqual(reply.type(), QDBusMessage.MessageType.ReplyMessage, reply.errorMessage())
        return reply.arguments()[0].variant()

    def test_it_takes_the_name_the_desktop_looks_for(self):
        self.assertIsNotNone(self.adapter)
        self.assertTrue(self.bus.interface().isServiceRegistered(mpris.BUS_NAME).value())

    def test_a_call_over_the_bus_reaches_the_player(self):
        self.engine.calls.clear()
        reply = self.call(PLAYER, "Next")
        self.assertEqual(reply.type(), QDBusMessage.MessageType.ReplyMessage, reply.errorMessage())
        self.assertTrue(self.engine.calls, "the player was not touched")

    def test_the_state_reads_back_over_the_bus(self):
        self.assertEqual(self.get("PlaybackStatus"), "Playing")

    def test_the_track_goes_out_as_the_map_the_interface_asks_for(self):
        """Its type, since reading a value back out of a nested variant is
        something the bindings on this side cannot do. Every reader that
        matters is on the other side of the bus and does it there."""
        self.assertEqual(self.get("Metadata").currentSignature(), "a{sv}")

    def test_publishing_twice_leaves_the_first_one_alone(self):
        """The name belongs to the connection, so tidying up after a second
        go would take it away from the one already answering on it."""
        caught = io.StringIO()
        with contextlib.redirect_stderr(caught):
            second = mpris.install(self.player)
        self.assertIsNone(second)
        self.assertIn("media keys are off", caught.getvalue())
        self.assertTrue(self.bus.interface().isServiceRegistered(mpris.BUS_NAME).value())


if __name__ == "__main__":
    unittest.main()
