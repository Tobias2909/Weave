"""Walking back and forward through the views, and the mouse buttons that do it.

Three things live here. A plain record of the views that have been landed on,
which the bridge writes into and reads back, the memory of the music track
lists that were visited, so walking back onto one does not fetch it again, and
the event filter that turns the mouse's back and forward buttons into a step
through the record. Only the filter needs Qt, which is what lets the rest be
tested without a window.

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

# How many track lists are held in memory at once. A list is a few hundred
# small rows, so the cost is nothing beside a fetch of several seconds against
# YouTube Music, and holding the last few covers a walk back through an
# evening of pressing tiles. Bounded by lists rather than by rows, since what
# is walked back to is a list and not a number of songs.
TRACK_LISTS = 8


@dataclass(frozen=True)
class MusicList:
    """One track list inside the music view.

    What kind of fetch it is, what to fetch it for, and the heading it is
    shown under, which together are both what tells two lists apart and what
    is needed to ask for one again. The shelves are not one of these. They are
    what the music view shows when there is no list at all, which is None.

    Frozen, so it can be compared and used as a key.
    """

    what: str
    ident: str = ""
    label: str = ""


# What fully describes a view: its kind, its id, its channel, its playlist and,
# inside music, the track list showing rather than the shelves.
View = tuple[str, int, str, str, MusicList | None]


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

    def previous(self) -> Entry | None:
        """Where a step back would land, without taking it.

        What a back button is allowed to call itself, so that the label can
        never claim somewhere the button does not actually go.
        """
        if self._index <= 0:
            return None
        return self._entries[self._index - 1]

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


class TrackCache:
    """The last few music track lists, so walking back onto one puts it back
    rather than asking YouTube Music for it a second time.

    Newest last, and reading a list makes it the newest again, so the ones
    being walked through are the ones that stay held.
    """

    def __init__(self, limit: int = TRACK_LISTS) -> None:
        self._held: dict[MusicList, tuple[list, str]] = {}
        self._limit = max(1, limit)

    def __len__(self) -> int:
        return len(self._held)

    def __contains__(self, key: MusicList) -> bool:
        return key in self._held

    def put(self, key: MusicList, rows: list, label: str) -> None:
        """Hold the rows a list arrived with, dropping the oldest once full.

        The heading is held beside them because it is not always the one that
        was asked for. A playlist with removed videos in it comes back saying
        how many are still playable.
        """
        self._held.pop(key, None)
        self._held[key] = (list(rows), label)
        while len(self._held) > self._limit:
            del self._held[next(iter(self._held))]

    def get(self, key: MusicList) -> tuple[list, str] | None:
        """The rows and heading held for a list, or nothing when it has gone."""
        found = self._held.get(key)
        if found is None:
            return None
        del self._held[key]
        self._held[key] = found
        return found


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
