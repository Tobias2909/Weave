"""Walking back and forward through the views, and the mouse buttons that do it.

Two things live here. A plain record of the views that have been landed on,
which the bridge writes into and reads back, and the event filter that turns
the mouse's back and forward buttons into a step through it. The record needs
no Qt at all, which is what lets it be tested without a window.

The filter is application wide on purpose. The buttons have to work wherever
the pointer happens to be, and the only way of catching them from QML would be
a MouseArea covering the whole window, which would then sit in front of every
ordinary click.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt

# How many views back the buttons reach. Long enough that an evening of
# clicking around stays walkable, short enough that the list is never worth a
# thought. Once it is full the oldest entry is dropped.
LIMIT = 50

# What fully describes a view: its kind, its id, its channel and its playlist.
View = tuple[str, int, str, str]


@dataclass
class Entry:
    """One view that was landed on.

    The words of a search are carried beside the view rather than inside it.
    The same search view with different words is one place and not two, so
    typing must not fill the record a letter at a time. They are remembered
    all the same, because a search walked back to with its words gone would
    show the whole feed under an empty box.
    """

    view: View
    search_text: str = ""


class History:
    """Where the views have been, and where forward still leads.

    One list with a finger in it rather than two stacks. The entries ahead of
    the finger are the forward branch, and landing somewhere new drops them,
    which is what a browser does and what makes forward mean one thing.
    """

    def __init__(self, start: View, limit: int = LIMIT) -> None:
        self._entries: list[Entry] = [Entry(start)]
        self._index = 0
        self._limit = max(1, limit)

    @property
    def entries(self) -> list[Entry]:
        return list(self._entries)

    @property
    def index(self) -> int:
        return self._index

    def current(self) -> Entry:
        return self._entries[self._index]

    def record(self, view: View, search_text: str = "") -> bool:
        """A view has been landed on. True when that counted as a step.

        Landing on the view already showing is not a step, so it adds nothing.
        Anything else drops the forward branch and becomes the newest entry.
        """
        if view == self._entries[self._index].view:
            self._entries[self._index].search_text = search_text
            return False
        del self._entries[self._index + 1:]
        self._entries.append(Entry(view, search_text))
        if len(self._entries) > self._limit:
            del self._entries[:len(self._entries) - self._limit]
        self._index = len(self._entries) - 1
        return True

    def note_search(self, text: str) -> None:
        """New words in the search view already showing. Not a step, but kept,
        so walking back to that search brings its words with it."""
        self._entries[self._index].search_text = text

    def can_go_back(self) -> bool:
        return self._index > 0

    def can_go_forward(self) -> bool:
        return self._index < len(self._entries) - 1

    def back(self) -> Entry | None:
        """One step back, or nothing when there is none."""
        if not self.can_go_back():
            return None
        self._index -= 1
        return self._entries[self._index]

    def forward(self) -> Entry | None:
        """One step towards where the walking back came from."""
        if not self.can_go_forward():
            return None
        self._index += 1
        return self._entries[self._index]


class MouseNavigation(QObject):
    """The mouse's back and forward buttons, walking the bridge's history."""

    BUTTONS = {Qt.MouseButton.BackButton: "goBack",
               Qt.MouseButton.ForwardButton: "goForward"}

    def __init__(self, bridge, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge

    def stop(self) -> None:
        """Let the bridge go, before the application tears anything down.

        The filter is still in place while the window closes, and a press
        arriving then would reach a bridge that has already waited for its
        threads. Dropping the reference makes that press do nothing.
        """
        self._bridge = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._bridge is not None and event.type() == QEvent.Type.MouseButtonPress:
            method = self.BUTTONS.get(event.button())
            if method is not None:
                getattr(self._bridge, method)()
                # Consumed, so nothing underneath sees it as an ordinary click.
                return True
        return super().eventFilter(watched, event)


def install(app, bridge) -> MouseNavigation:
    """Make the mouse's back and forward buttons walk the view history.

    Called once, with the application and the bridge:

        navigation.install(app, bridge)

    The filter is parented to the application, so Qt owns it and it lives
    exactly as long as the application does. It is returned as well, for a
    caller that would rather hold on to it itself.
    """
    nav = MouseNavigation(bridge, parent=app)
    app.installEventFilter(nav)
    app.aboutToQuit.connect(nav.stop)
    return nav
