"""The music player on the desktop's media controls.

A keyboard's play, next and previous keys never reach an application on their
own. The desktop takes them and hands them to whatever is registered on MPRIS,
which is also what the panel's media controller and playerctl read. This
module puts Weave's music player there and nothing else: video is played by
mpv, which is a separate program with keys of its own, and two players
answering one key press is worse than none.

Everything here drives `audio.AudioPlayer` through the same public surface the
interface uses, so the fades and the pause handling behave exactly as they do
when a button is clicked.

A missing session bus, or a name already taken by another Weave, is a reason
to go without media keys, never a reason to fail startup, so `install` reports
once and returns None.
"""

from __future__ import annotations

import re
import sys

from PySide6.QtCore import ClassInfo, Property, QCoreApplication, QMetaType, QObject, Slot
from PySide6.QtDBus import (
    QDBusAbstractAdaptor,
    QDBusArgument,
    QDBusConnection,
    QDBusMessage,
    QDBusObjectPath,
)

BUS_NAME = "org.mpris.MediaPlayer2.weave"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

# The name of the shipped desktop file, without its suffix. The panel reads it
# to find the icon and the window that belongs to the player.
DESKTOP_ENTRY = "weave"

# Every track needs an object path of its own, and a queue key is not one:
# `yt:dQw4` has a colon in it. Anything outside the allowed set becomes an
# underscore, which is enough because the path only has to be distinct.
TRACK_PATH = "/org/mpris/MediaPlayer2/weave/track/"


def _no_strings() -> QDBusArgument:
    """An empty array of strings, with the element type still on it.

    PropertiesChanged ends with the names that have to be read again, and that
    is an array of strings even when it is empty. An empty Python list has no
    element type left to marshal, so it goes out as an array of variants, and
    a reader that checks the whole signature, which every glib one does, drops
    the signal rather than reading it.
    """
    empty = QDBusArgument()
    empty.beginArray(QMetaType.Type.QString)
    empty.endArray()
    return empty


def _track_path(key: str) -> QDBusObjectPath:
    return QDBusObjectPath(TRACK_PATH + (re.sub(r"[^A-Za-z0-9_]", "_", key) or "none"))


def metadata(track: dict, length_s: int) -> dict:
    """One queue entry as the map the panel reads.

    A field that is not known is left out rather than sent empty, since a
    reader treats an empty string as a title and draws it.
    """
    if not track:
        return {}
    found = {
        "mpris:trackid": _track_path(str(track.get("key", ""))),
        "xesam:title": str(track.get("title", "")),
    }
    if length_s > 0:
        found["mpris:length"] = int(length_s) * 1_000_000
    if track.get("artist"):
        found["xesam:artist"] = [str(track["artist"])]
    if track.get("thumbnail"):
        found["mpris:artUrl"] = str(track["thumbnail"])
    return found


@ClassInfo({"D-Bus Interface": ROOT_IFACE})
class _Root(QDBusAbstractAdaptor):
    """What the player is, rather than what it is playing."""

    def __init__(self, owner: MprisAdapter) -> None:
        super().__init__(owner)
        self._owner = owner

    @Slot()
    def Raise(self) -> None:
        self._owner.raise_window()

    @Slot()
    def Quit(self) -> None:
        self._owner.quit()

    def _identity(self) -> str:
        return "Weave"

    def _desktop_entry(self) -> str:
        return DESKTOP_ENTRY

    def _can_quit(self) -> bool:
        return True

    def _can_raise(self) -> bool:
        # Only true once something has been handed over that can actually
        # bring the window forward.
        return self._owner.can_raise()

    def _has_track_list(self) -> bool:
        # Weave has a queue, but not the TrackList interface that would let
        # anything else edit it.
        return False

    Identity = Property(str, _identity, constant=True)
    DesktopEntry = Property(str, _desktop_entry, constant=True)
    CanQuit = Property(bool, _can_quit, constant=True)
    CanRaise = Property(bool, _can_raise)
    HasTrackList = Property(bool, _has_track_list, constant=True)


@ClassInfo({"D-Bus Interface": PLAYER_IFACE})
class _Player(QDBusAbstractAdaptor):
    """The controls the media keys land on."""

    def __init__(self, owner: MprisAdapter, audio) -> None:
        super().__init__(owner)
        self._audio = audio

    @Slot()
    def PlayPause(self) -> None:
        self._audio.toggle()

    @Slot()
    def Play(self) -> None:
        # toggle() is the only switch there is, so it is only pressed when it
        # would go the wanted way.
        if not self._audio.playing:
            self._audio.toggle()

    @Slot()
    def Pause(self) -> None:
        if self._audio.playing:
            self._audio.toggle()

    @Slot()
    def Stop(self) -> None:
        self._audio.stop()

    @Slot()
    def Next(self) -> None:
        self._audio.next()

    @Slot()
    def Previous(self) -> None:
        self._audio.previous()

    def _playback_status(self) -> str:
        if not self._audio.track:
            return "Stopped"
        return "Playing" if self._audio.playing else "Paused"

    def _metadata(self) -> dict:
        return metadata(self._audio.track, self._audio.length)

    def _volume(self) -> float:
        return self._audio.volume / 100

    def _set_volume(self, value: float) -> None:
        self._audio.setVolume(round(max(0.0, min(1.0, float(value))) * 100))

    def _position(self) -> int:
        return int(self._audio.elapsed) * 1_000_000

    def _can_go_next(self) -> bool:
        return bool(self._audio.hasQueue)

    def _can_go_previous(self) -> bool:
        return bool(self._audio.hasQueue)

    def _can_play(self) -> bool:
        return bool(self._audio.hasQueue)

    def _can_pause(self) -> bool:
        return bool(self._audio.hasQueue)

    def _can_control(self) -> bool:
        return True

    PlaybackStatus = Property(str, _playback_status)
    Metadata = Property("QVariantMap", _metadata)
    Volume = Property(float, _volume, _set_volume)
    Position = Property("qlonglong", _position)
    CanGoNext = Property(bool, _can_go_next)
    CanGoPrevious = Property(bool, _can_go_previous)
    CanPlay = Property(bool, _can_play)
    CanPause = Property(bool, _can_pause)
    CanControl = Property(bool, _can_control, constant=True)


class MprisAdapter(QObject):
    """The object published at the MPRIS path, holding both interfaces.

    It also announces what changed. Without that the panel keeps whatever
    title it read first, since nothing polls a player it can be told about.
    """

    def __init__(self, audio, bus: QDBusConnection, on_raise=None, on_quit=None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio = audio
        self._bus = bus
        self._on_raise = on_raise
        self._on_quit = on_quit
        self._root = _Root(self)
        self._player = _Player(self, audio)
        # Position is deliberately not announced. It moves every tick and the
        # interface says a reader works it out from the status instead.
        audio.trackChanged.connect(self._publish)
        audio.stateChanged.connect(self._publish)
        # What a reader would see right now, so the first announcement carries
        # what has actually changed rather than everything.
        self._sent = self._values()

    # ---- what the root interface calls -----------------------------------

    def can_raise(self) -> bool:
        return self._on_raise is not None

    def raise_window(self) -> None:
        if self._on_raise is not None:
            self._on_raise()

    def quit(self) -> None:
        if self._on_quit is not None:
            self._on_quit()
            return
        app = QCoreApplication.instance()
        if app is not None:
            app.quit()

    # ---- announcing ------------------------------------------------------

    def _values(self) -> dict:
        """The player properties worth announcing, as they are on the bus."""
        player = self._player
        return {
            "PlaybackStatus": player.PlaybackStatus,
            "Metadata": player.Metadata,
            "Volume": player.Volume,
            "CanGoNext": player.CanGoNext,
            "CanGoPrevious": player.CanGoPrevious,
            "CanPlay": player.CanPlay,
            "CanPause": player.CanPause,
        }

    def _publish(self) -> None:
        """Send what has actually changed since the last time.

        Both signals underneath fire for more than this cares about, a mode
        switch or a volume nudge among them, so a comparison keeps the bus
        quiet rather than announcing a track every time anything moves.
        """
        values = self._values()
        changed = {name: value for name, value in values.items()
                   if self._sent.get(name) != value}
        if not changed:
            return
        self._sent = values
        message = QDBusMessage.createSignal(OBJECT_PATH, PROPERTIES_IFACE, "PropertiesChanged")
        message.setArguments([PLAYER_IFACE, changed, _no_strings()])
        self._bus.send(message)


def _declined(reason: str) -> None:
    print(f"media keys are off, {reason}", file=sys.stderr)


def install(audio_player, parent: QObject | None = None,
            on_raise=None, on_quit=None) -> MprisAdapter | None:
    """Publish the music player on the session bus.

    Returns the adapter, which has to be kept alive for as long as the
    player is, or None when there is nothing to publish on. Never raises:
    a machine with no session bus runs Weave without media keys.

    `on_raise` is called for the Raise method and decides whether CanRaise is
    true at all, so leaving it out simply says the window cannot be brought
    forward. `on_quit` replaces the default, which quits the application.
    """
    try:
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return _declined("there is no session bus")
        if bus.objectRegisteredAt(OBJECT_PATH) is not None:
            # Installed twice in one process. Going on from here would take
            # the name away from the adapter that already holds it, since the
            # name belongs to the connection rather than to either of them.
            return _declined("the player is already published")
        if not bus.registerService(BUS_NAME):
            # Another Weave holds the name. The interface allows a second
            # player under a numbered name, which would give the panel two
            # entries for one queue, so this one goes without instead.
            return _declined(f"{BUS_NAME} is already taken")
        adapter = MprisAdapter(audio_player, bus, on_raise, on_quit, parent)
        options = QDBusConnection.RegisterOption.ExportAdaptors
        if not bus.registerObject(OBJECT_PATH, adapter, options):
            bus.unregisterService(BUS_NAME)
            adapter.setParent(None)
            return _declined("the player could not be published")
        return adapter
    except Exception as exc:
        return _declined(f"{type(exc).__name__}, {exc}")
