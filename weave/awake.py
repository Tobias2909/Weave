"""The screen kept on while a video plays in the window.

A desktop dims the screen, blanks it and locks it after a while without
input, which is exactly what somebody watching gives it. A player asks it not
to over the freedesktop ScreenSaver interface while a video is actually
playing, and lets go when it is paused or stops, so a paused video does not
keep the screen on all night. A video sent to mpv is mpv's own business.

Each hold is asked for over a connection to the session bus of its own, and
letting go is closing that connection. The desktop forgets the holds of a
caller that has left the bus, and doing it that way needs no cookie handed
back: the cookie is an unsigned number, which PySide has no way to send, and
an answer sent with the wrong type of number is refused and the hold stays.
It also means a Weave that crashes takes its hold with it.

A machine without a session bus, or a desktop without the interface, simply
blanks the screen as it would have. Nothing here fails startup.
"""

from __future__ import annotations

import itertools

from PySide6.QtCore import QObject
from PySide6.QtDBus import QDBusConnection, QDBusMessage, QDBusPendingCallWatcher

from . import trace

SERVICE = "org.freedesktop.ScreenSaver"
PATH = "/org/freedesktop/ScreenSaver"
INTERFACE = "org.freedesktop.ScreenSaver"
REASON = "Playing a video"

# A hold that was asked for and refused, so it is not asked for again on every
# change until the video stops playing.
REFUSED = "refused"

_numbers = itertools.count(1)


class SessionBus:
    """The holds, on the real session bus."""

    def __init__(self) -> None:
        self._watchers: dict[str, QDBusPendingCallWatcher] = {}

    def open(self) -> str:
        """A connection of its own, by name, or "" when there is none."""
        name = f"weave-awake-{next(_numbers)}"
        connection = QDBusConnection.connectToBus(QDBusConnection.BusType.SessionBus, name)
        if not connection.isConnected():
            QDBusConnection.disconnectFromBus(name)
            return ""
        return name

    def inhibit(self, name: str, done) -> None:
        """Ask over that connection; `done(ok)` once the desktop answers."""
        message = QDBusMessage.createMethodCall(SERVICE, PATH, INTERFACE, "Inhibit")
        message.setArguments(["Weave", REASON])
        watcher = QDBusPendingCallWatcher(QDBusConnection(name).asyncCall(message))

        def answered(_watcher) -> None:
            self._watchers.pop(name, None)
            reply = watcher.reply()
            ok = reply.type() == QDBusMessage.MessageType.ReplyMessage
            if not ok:
                trace.mark("awake_refused", why=reply.errorMessage())
            done(ok)

        watcher.finished.connect(answered)
        self._watchers[name] = watcher

    def close(self, name: str) -> None:
        self._watchers.pop(name, None)
        QDBusConnection.disconnectFromBus(name)


class KeepAwake(QObject):
    """Holds the screen on for as long as the window's video plays."""

    def __init__(self, video, bus=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._video = video
        self._bus = bus if bus is not None else SessionBus()
        # The connection holding the screen on, or asking to, or REFUSED.
        self._held = ""
        video.stateChanged.connect(self._check)
        video.videoChanged.connect(self._check)
        self._check()

    @property
    def holding(self) -> bool:
        return self._held not in ("", REFUSED)

    def _wanted(self) -> bool:
        return bool(self._video.playing and self._video.videoShowing)

    def _check(self) -> None:
        if self._wanted():
            if not self._held:
                self._hold()
        elif self._held:
            self._let_go()

    def _hold(self) -> None:
        name = self._bus.open()
        if not name:
            self._held = REFUSED
            return
        self._held = name
        trace.mark("awake_hold")
        self._bus.inhibit(name, lambda ok, asked=name: self._answered(asked, ok))

    def _answered(self, name: str, ok: bool) -> None:
        if name != self._held:
            # Let go of while the desktop was still answering.
            return
        if not ok:
            self._bus.close(name)
            self._held = REFUSED

    def _let_go(self) -> None:
        if self.holding:
            self._bus.close(self._held)
            trace.mark("awake_let_go")
        self._held = ""

    def shutdown(self) -> None:
        self._let_go()


def install(video_player, parent: QObject | None = None) -> KeepAwake | None:
    """Keep the screen on while the window's video plays, where there is a
    session bus to ask on. Never raises."""
    try:
        if not QDBusConnection.sessionBus().isConnected():
            return None
        return KeepAwake(video_player, parent=parent)
    except Exception:
        return None
