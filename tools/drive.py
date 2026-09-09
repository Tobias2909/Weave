"""Drive the real window without a display.

A clean boot proves almost nothing about an interface. It never opens a menu,
never commits a popup and never switches a view, and those are exactly the
places a binding reaches for an id it cannot see. This boots the actual
window on the offscreen platform, walks it the way a person would, collects
every warning the QML engine raises, and reports.

Run from the repository root:

    python tools/drive.py smoke --offline
    python tools/drive.py smoke --offline --screenshot /tmp/weave.png

Point it at a scratch home first, or it opens the real database:

    XDG_CONFIG_HOME=/tmp/w/c XDG_STATE_HOME=/tmp/w/s XDG_CACHE_HOME=/tmp/w/k \\
        python tools/drive.py smoke --offline

The helpers at the top are the reusable part. Three things do not work from
PySide and are not retried here. `Menu.itemAt` returns None, a view's
delegates are not children of the view so `findChildren` cannot reach them,
and a QML `MenuItem` has no `text` attribute in Python, so entries are found
by `hasattr(child, "click")` and their label read with `QQmlProperty`. Do not
install a message handler either, a Python one deadlocks with Qt's threads;
the caller reads stderr instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QCoreApplication, QEventLoop, QMetaObject, QObject, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtQml import QQmlProperty  # noqa: E402

# A colour nothing in any theme uses, so finding it in a picture of the window
# can only mean the seeded artwork was drawn.
ARTWORK = (255, 0, 255)


# ---- helpers ---------------------------------------------------------------

def find(window, name: str) -> QObject | None:
    """A named object anywhere under the window. Give things an objectName."""
    if QQmlProperty.read(window, "objectName") == name:
        return window
    return window.findChild(QObject, name)


def read(obj, name: str):
    return QQmlProperty.read(obj, name)


def write(obj, name: str, value) -> None:
    QQmlProperty.write(obj, name, value)


def call(obj, method: str) -> None:
    """Call a QML function with no arguments."""
    QMetaObject.invokeMethod(obj, method)


def menu_entries(menu) -> list[tuple[str, QObject]]:
    """The clickable entries of a Menu, in order, with their labels."""
    found = []
    for child in menu.findChildren(QObject):
        if hasattr(child, "click"):
            label = QQmlProperty.read(child, "text")
            if label is not None:
                found.append((str(label), child))
    return found


def click_entry(menu, label: str) -> bool:
    for text, item in menu_entries(menu):
        if text.strip().lstrip("✓").strip() == label:
            item.click()
            return True
    return False


# Bumped every time the walk waits, which is the only thing it does between
# presses, so a watchdog can tell a walk that is working from one that has
# hung. Read through beat(), never assigned from outside.
_beats = 0


def beat() -> int:
    return _beats


def settle(seconds: float) -> None:
    """Let the event loop run for a while."""
    global _beats
    _beats += 1
    end = time.monotonic() + seconds
    app = QCoreApplication.instance()
    while time.monotonic() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.005)


def wait_until(answer, seconds: float = 3.0) -> bool:
    """Let the loop run until something is true, or give up.

    A fixed settle is a guess about how long a view takes to build, and the
    software renderer takes longer than this one, so a guess that holds here
    fails in the suite.
    """
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if answer():
            return True
        settle(0.1)
    return answer()


def screenshot(window, path: str) -> bool:
    image = window.grabWindow()
    return bool(image.save(path))


def item_named(root, name: str):
    """A named item anywhere below this one, walking the visual tree.

    A Repeater's delegates are not QObject children of anything, so findChild
    cannot see them or anything inside them. The tree they are in is the
    visual one, which is what this walks.
    """
    if root is None:
        return None
    for child in root.childItems():
        if QQmlProperty.read(child, "objectName") == name:
            return child
        found = item_named(child, name)
        if found is not None:
            return found
    return None


def items_named_like(root, prefix: str) -> list:
    """Every named item below this one whose name begins with the prefix.

    The visual tree again, since these are delegates, and more than one of
    them, which is what item_named cannot answer.
    """
    found = []
    if root is None:
        return found
    for child in root.childItems():
        if str(QQmlProperty.read(child, "objectName") or "").startswith(prefix):
            found.append(child)
        found.extend(items_named_like(child, prefix))
    return found


def visible_children(item) -> list:
    """What a positioner has actually laid out, which is where a Repeater puts
    its delegates. The Repeater itself is a child with no size, and is left out
    along with anything the positioner skipped.
    """
    if item is None:
        return []
    return [child for child in item.childItems()
            if QQmlProperty.read(child, "visible")
            and QQmlProperty.read(child, "width") > 0
            and QQmlProperty.read(child, "height") > 0]


def source_of(item) -> str:
    """An image source as the string it was given. Read back it is a QUrl,
    whose repr is not the address."""
    value = QQmlProperty.read(item, "source")
    return value.toString() if hasattr(value, "toString") else str(value or "")


def colour_count(image: QImage, rgb: tuple[int, int, int], tolerance: int = 24) -> int:
    """How many pixels of a picture are about this colour.

    A missing picture is exactly the thing being guarded against, and a source
    string that reads correctly proves only that the binding ran. This looks at
    what was actually painted.
    """
    if image is None or image.isNull():
        return 0
    small = image.convertToFormat(QImage.Format.Format_RGB32)
    want = QColor(*rgb)
    found = 0
    for y in range(0, small.height(), 2):
        for x in range(0, small.width(), 2):
            pixel = QColor(small.pixel(x, y))
            if (abs(pixel.red() - want.red()) <= tolerance
                    and abs(pixel.green() - want.green()) <= tolerance
                    and abs(pixel.blue() - want.blue()) <= tolerance):
                found += 1
    return found


def colours_across(image: QImage, x: float, y: float, width: float) -> int:
    """How many different colours a horizontal run of pixels holds.

    A strip of bare window is one colour and a strip with cards in it is
    several, so this says whether something is being covered without needing
    to know which theme is on.
    """
    if image is None or image.isNull():
        return 0
    small = image.convertToFormat(QImage.Format.Format_RGB32)
    row = int(y)
    if row < 0 or row >= small.height():
        return 0
    seen = set()
    for step in range(int(x), min(int(x + width), small.width()), 4):
        seen.add(QColor(small.pixel(step, row)).name())
    return len(seen)


def artwork_file() -> str:
    """A small picture on disk, so the walk has something real to draw without
    reaching the network. Returned as a URL, which is what QML wants."""
    from weave import paths

    path = paths.CACHE_DIR / "drive-artwork.png"
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(QColor(*ARTWORK))
    image.save(str(path))
    return path.as_uri()


class Warnings:
    """Every warning the QML engine raises while the window is driven."""

    def __init__(self, engine) -> None:
        self.lines: list[str] = []
        engine.warnings.connect(self._on_warnings)

    def _on_warnings(self, errors) -> None:
        for error in errors:
            self.lines.append(error.toString())


# ---- keeping the network out ------------------------------------------------

def go_offline() -> None:
    """Make every request and every subprocess fail fast, so the walk never
    touches the network or yt-dlp and finishes in seconds."""
    from weave import net, process
    from weave.sources import ytmusic

    def no_request(*_a, **_k):
        raise net.Cancelled("offline")

    def no_process(*_a, **_k):
        raise FileNotFoundError("offline")

    def no_music(*_a, **_k):
        raise ytmusic.MusicError("offline")

    net.Fetcher.get_bytes = no_request
    process.run = no_process
    ytmusic.client = no_music


def seed() -> None:
    """A channel with a few videos, so the grid and the menus have something
    to act on, and a music section wider than the two rows it is shown in."""
    import json
    import time

    from weave import paths
    from weave.db import Database, VideoRow

    paths.ensure_dirs()
    db = Database(paths.DB_FILE)
    db.add_channel("yt:UCsmokesmokesmokesmokes1", "youtube", "UCsmokesmokesmokesmokes1", "Smoke")
    db.upsert_videos([
        VideoRow("youtube", f"smokevid{i:03d}", "yt:UCsmokesmokesmokesmokes1", f"Video {i}",
                 published_at=1_700_000_000 + i, duration_s=600 + i)
        for i in range(6)
    ])
    # Kept without being followed, the way a channel behind a saved video is.
    # Putting this one in a group follows it for that group alone, and All must
    # not gain its video, which is what the walk checks.
    db.remember_channel("yt:UCsmokesmokesmokesmokes2", "youtube",
                        "UCsmokesmokesmokesmokes2", "Smoke two")
    db.upsert_videos([
        VideoRow("youtube", "smokegroupvid", "yt:UCsmokesmokesmokesmokes2",
                 "Video in a group only", published_at=1_700_000_100, duration_s=700),
    ])
    # Written where the music view reads what was on the shelves last time, so
    # the sections are there without a request. Forty entries, which is more
    # than two rows hold at any window width worth drawing, and each with a
    # picture on disk so a missing one is a fault and not the network.
    art = artwork_file()
    db.set_state("music_shelves", json.dumps([{
        "title": "Listen again",
        "items": [{"title": f"Track {i}", "subtitle": "Someone",
                   "videoId": f"smoketrack{i:02d}", "playlistId": f"RDsmoke{i:02d}",
                   "thumbnail": art} for i in range(40)],
    }]))
    db.set_state("music_shelves_at", str(int(time.time())))
    db.close()


# ---- the walk ----------------------------------------------------------------

class Smoke:
    def __init__(self, shot: str | None, loud: bool = False) -> None:
        self.shot = shot
        # Say each answer as it is found rather than only in the report at the
        # end. A walk that dies takes an unprinted report with it, and a
        # segfault in the middle of one left no output at all to work from,
        # which is the worst possible thing for a harness to do.
        self.loud = loud
        self.checks: list[tuple[str, bool, str]] = []
        self.warnings: Warnings | None = None

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, bool(ok), detail))
        if self.loud:
            print(f"[{'ok' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""),
                  flush=True)

    def music(self, bridge, window) -> None:
        """The music page: two rows a section, the page behind them, and a
        picture everywhere a track is drawn."""
        bridge.showMusic()
        settle(0.6)
        shelves = read(bridge, "musicShelves")
        total = len(shelves[0]["items"]) if shelves else 0
        self.check("the music page has its sections", total > 0, f"{total} entries")

        # Two rows, ending in the tile that opens the rest.
        shelves_area = find(window, "shelfArea")
        tiles = visible_children(item_named(shelves_area, "shelfRow0"))
        more = item_named(shelves_area, "seeAll0")
        self.check("a section is cut to two rows", 0 < len(tiles) < total,
                   f"{len(tiles)} tiles of {total}")
        self.check("the two rows end in a See all tile",
                   more is not None and bool(read(more, "visible")))
        pictures = [str(read(tile, "picture")) for tile in tiles
                    if read(tile, "picture") is not None]
        self.check("the tiles carry a picture", bool(pictures) and all(pictures),
                   f"{len(pictures)} of {len(tiles)}")

        # The whole section, and a place the mouse buttons walk off again.
        bridge.openShelf(0)
        settle(0.5)
        page = find(window, "shelfPage")
        shown = visible_children(find(window, "shelfPageFlow"))
        self.check("See all opens the whole section",
                   bool(read(page, "visible")) and len(shown) == total,
                   f"{len(shown)} of {total}")
        bridge.goBack()
        settle(0.4)
        self.check("walking back leaves the section page", not read(page, "visible"))

        # Pressing a song fills the queue and opens nothing. Offline the
        # station never arrives, which is the point: the decision not to open
        # a list is taken when the tile is pressed, not when rows land.
        steps_before = bool(read(bridge, "canGoBack"))
        bridge.playShelfItem(0, 0)
        settle(0.4)
        self.check("pressing a song opens no list",
                   not read(find(window, "musicResultsList"), "visible")
                   and read(bridge, "viewKind") == "music")
        self.check("and takes no step to walk back from",
                   bool(read(bridge, "canGoBack")) == steps_before)

        # A queue with a picture in it, which is the third place one was lost.
        art = artwork_file()
        bridge._audio.play_items([
            {"key": f"yt:smoketrack{i:02d}", "title": f"Track {i}", "artist": "Someone",
             "thumbnail": art, "live": False, "url": f"https://example.invalid/{i}"}
            for i in range(3)])
        settle(0.5)
        queued = read(bridge._audio, "queue")
        self.check("the queue holds the tracks with their pictures",
                   len(queued) == 3 and all(row["thumbnail"] == art for row in queued),
                   f"{len(queued)} queued")
        self.check("the player draws the artwork beside what is playing",
                   source_of(find(window, "nowPlayingArt")) == art,
                   source_of(find(window, "nowPlayingArt")))

        # What was painted, rather than what a binding says. A picture that is
        # bound and never drawn is the fault being guarded against.
        if self.shot:
            self.check("music page written", screenshot(window, shot_beside(self.shot, "music")))
        drawn = colour_count(window.grabWindow(), ARTWORK)
        self.check("the artwork is on the screen", drawn > 0, f"{drawn} pixels")

        popup = find(window, "upNext")
        call(popup, "open")
        settle(0.5)
        rows = read(find(window, "queuedList"), "count")
        in_queue = colour_count(window.grabWindow(), ARTWORK)
        self.check("the queue lists what is coming", rows == 3, f"{rows} rows")
        self.check("with a picture on every row", in_queue > drawn,
                   f"{in_queue} pixels against {drawn} with the queue shut")
        if self.shot:
            self.check("queue written", screenshot(window, shot_beside(self.shot, "queue")))
        call(popup, "close")
        settle(0.3)
        # Left on the feed, so what follows this starts where it always did.
        bridge.selectGroup(-1)
        settle(0.3)

    def starting(self, bridge, window) -> None:
        """A press has to say something before mpv has a window.

        It is said on the thumbnail that was pressed, so the answer is where
        the eye already is, and the bottom of the window says nothing about
        playing any more.
        """
        # Back on the feed, since the walk arrives here from the settings page
        # and a hidden grid lays out no cards at all.
        bridge.selectGroup(-1)
        settle(0.4)
        # Emptied so the check below is about this press and not about whatever
        # an earlier step left behind.
        bridge._set_notice("")
        grid = find(window, "grid")
        key = read(bridge, "startingKey")
        self.check("nothing is starting to begin with", key == "", key)
        cards = visible_children(read(grid, "contentItem"))
        wash = next((found for found in (item_named(card, "startingWash") for card in cards)
                     if found is not None), None)
        self.check("a card carries the mpv chip", wash is not None)
        self.check("and it is not drawn while nothing starts",
                   wash is not None and not read(wash, "visible"))

        # Which answer is right depends on the machine. mpv is what a video is
        # handed to, so where there is none there is nothing to start and the
        # press correctly marks nothing. Asked of the player rather than of
        # PATH, since a configured command and the wrapper are both answers
        # PATH does not have.
        playable = getattr(bridge._player, "_error", None) is None
        bridge.play("yt:smokevid005")
        settle(0.4)
        washes = [found for found in
                  (item_named(card, "startingWash")
                   for card in visible_children(read(grid, "contentItem")))
                  if found is not None and read(found, "visible")]
        if playable:
            self.check("pressing a card marks it as starting",
                       read(bridge, "startingKey") == "yt:smokevid005",
                       str(read(bridge, "startingKey")))
            self.check("the chip is drawn on exactly one card", len(washes) == 1,
                       f"{len(washes)} of them")
        else:
            self.check("with no mpv on the machine, a press marks nothing",
                       read(bridge, "startingKey") == "" and not washes,
                       f"key {read(bridge, 'startingKey')!r}, {len(washes)} chips")
        self.check("and the bottom of the window says nothing",
                   read(bridge, "notice") == "", str(read(bridge, "notice")))
        if self.shot:
            self.check("starting written", screenshot(window, shot_beside(self.shot, "starting")))

        # mpv never arriving must not leave it there.
        bridge._on_player_failed("mpv is not installed")
        settle(0.3)
        self.check("a failure takes the chip away", read(bridge, "startingKey") == "",
                   str(read(bridge, "startingKey")))

    def announcements(self, bridge, window) -> None:
        """A stream that has not begun says when it will, in the panel as well.

        The badge on the card says how long there is to wait, which answers a
        different question from the one somebody deciding whether to be there
        asks.
        """
        import time as clock

        from weave import paths
        from weave.db import Database

        db = Database(paths.DB_FILE)
        with db.conn as conn:
            conn.execute("UPDATE videos SET live_status='is_upcoming', scheduled_at=? "
                         "WHERE key='yt:smokevid005'", (int(clock.time()) + 5 * 3600,))
        db.close()
        bridge.selectGroup(-1)
        bridge.reload()
        settle(0.5)
        bridge.openDetail("yt:smokevid005")
        settle(0.6)
        says = read(bridge, "detail").get("startsText", "")
        self.check("the panel says when an announced stream begins", says != "", says)
        row = bridge._model.row_for_key("yt:smokevid005")
        self.check("and the card is not dimmed for being one",
                   row is not None and row.get("isUpcoming") is True)
        bridge.closeDetail()
        settle(0.3)

    def chapters(self, bridge, window) -> None:
        """A track that is really an album, marked on the bar.

        A YouTube video is often a whole record with its songs as chapters
        rather than published one by one. Without them the bar is one long
        block with nothing to say that it is six songs, and the name above it
        is the name of the upload. They come back in the same call that
        resolves the address, so they cost nothing.

        Put in by hand here. Getting them for real is a request, and the walk
        is offline; that the call brings them back is proved against yt-dlp
        itself, and what this checks is that they reach the bar and the line.
        """
        real = [
            {"title": "One", "start": 0.0, "end": 312.0},
            {"title": "Two", "start": 312.0, "end": 637.0},
            {"title": "Three", "start": 637.0, "end": 904.0},
        ]
        audio = bridge._audio
        audio._queue = [{"key": "yt:albumaaaaa", "title": "A whole record",
                         "artist": "Somebody", "url": "https://example/watch"}]
        audio._order = [0]
        audio._at = 0
        audio._chapters["yt:albumaaaaa"] = tuple(real)
        audio._dur = 904.0
        audio._pos = 700.0
        audio._idle = False
        audio.trackChanged.emit()
        audio.progressChanged.emit()
        audio.stateChanged.emit()
        settle(0.6)

        root = window.contentItem()
        track = find(window, "musicScrubTrack")
        marks = [one for one in items_named_like(root, "chapterMark")
                 if read(one, "visible")]
        # The one at the very start is where the bar begins, so a mark there
        # would be a line drawn on the edge of it.
        self.check("a track that is an album is marked where its songs start",
                   len(marks) == 2, f"{len(marks)} marks for {len(real)} songs")
        width = float(read(track, "width")) if track is not None else 0.0
        placed = [(float(read(one, "x")), song["start"] / 904.0)
                  for one, song in zip(sorted(marks, key=lambda m: read(m, "x")),
                                       real[1:], strict=False)]
        self.check("and each mark is as far along as its song is",
                   width > 0 and all(abs(x - want * width) < 2 for x, want in placed),
                   ", ".join(f"{x:.0f} wanted {want * width:.0f}" for x, want in placed))

        line = find(window, "musicSecondLine")
        self.check("the line under the title names the song, not the upload",
                   str(read(line, "text")) == "Three", str(read(line, "text")))
        audio._pos = 400.0
        audio.progressChanged.emit()
        settle(0.3)
        self.check("and follows the playhead into the next one",
                   str(read(line, "text")) == "Two", str(read(line, "text")))

        # A track with none of them is the ordinary case and must not change.
        audio._chapters.clear()
        audio.progressChanged.emit()
        audio.trackChanged.emit()
        settle(0.4)
        left = [one for one in items_named_like(root, "chapterMark")
                if read(one, "visible")]
        self.check("a track with no songs in it carries no marks", not left,
                   f"{len(left)} left over")
        self.check("and its line says who it is by instead",
                   str(read(line, "text")) == "Somebody", str(read(line, "text")))

        audio._queue = []
        audio._order = []
        audio._at = -1
        audio._dur = 0.0
        audio._pos = 0.0
        audio._idle = True
        audio.trackChanged.emit()
        audio.stateChanged.emit()
        settle(0.3)

    def members(self, bridge, window) -> None:
        """A channel's members half.

        What is behind a membership is in no other feed, so nothing is read
        until the button on the channel page is pressed. Pressed here by hand
        in the database rather than through the button, since the button makes
        a request and this walk is offline.

        Three things to hold. The rows stay out of the feed and out of the
        videos half, because for almost every channel they cannot be opened.
        The half exists only once something is in it. And a press there is
        refused, with the picture saying so beforehand.
        """
        from weave import paths
        from weave.db import Database

        channel = "yt:UCsmokesmokesmokesmokes1"
        db = Database(paths.DB_FILE)
        with db.conn as conn:
            conn.execute("UPDATE videos SET members_only=1 WHERE key='yt:smokevid004'")
            conn.execute("UPDATE channels SET members_wanted=1, members=1 WHERE key=?",
                         (channel,))
        db.close()
        bridge.selectGroup(-1)
        bridge.reload()
        settle(0.5)
        grid = find(window, "grid")
        call(grid, "forceLayout")
        settle(0.3)
        self.check("a members only video is out of the feed",
                   bridge._model.row_for_key("yt:smokevid004") is None)

        bridge.openChannel(channel)
        settle(0.5)
        self.check("and out of the channel's videos half",
                   bridge._model.row_for_key("yt:smokevid004") is None)
        tab = find(window, "channelMembersTab")
        self.check("the channel offers a members half once there is one",
                   tab is not None and read(tab, "visible") is True,
                   f"visible {read(tab, 'visible') if tab is not None else 'no button'}")
        # find rather than item_named: a QQuickWindow has no childItems, so a
        # visual walk has to start at its content item, and this one is
        # reachable as a plain child by name.
        button = find(window, "channelMembers")
        self.check("and the header carries the button that fills it",
                   button is not None and read(button, "visible") is True
                   and "Members" in str(read(button, "text")),
                   str(read(button, "text")) if button is not None else "no button")

        # A channel that sells nothing keeps the button and says why on the
        # banner. It used to lose the button instead, which says nothing about
        # what happened and looks like a button that broke.
        bridge._on_no_membership(channel)
        settle(0.4)
        note = find(window, "membersNote")
        words = find(window, "membersNoteText")
        self.check("a channel with no membership keeps its button",
                   read(button, "visible") is True)
        self.check("and says so over its banner",
                   note is not None and read(note, "visible") is True
                   and "No membership videos" in str(read(words, "text")),
                   str(read(words, "text")) if words is not None else "nothing said")
        self.check("and offers to look again",
                   words is not None and "again" in str(read(words, "text")).lower())

        # And when there is one, whether it can be opened is the thing worth
        # saying, since that is what decides whether a press goes anywhere.
        bridge._on_channel_members(channel, 1)
        settle(0.4)
        self.check("one you cannot open says that instead",
                   words is not None and "cannot be opened" in str(read(words, "text")),
                   str(read(words, "text")) if words is not None else "nothing said")
        db = Database(paths.DB_FILE)
        db.set_member_of(channel, True)
        db.close()
        bridge._on_channel_members(channel, 1)
        settle(0.4)
        self.check("and one you hold says it will play",
                   words is not None and "holds" in str(read(words, "text")),
                   str(read(words, "text")) if words is not None else "nothing said")
        # The answer takes itself away after twenty seconds, and the bar
        # along its foot IS that timer rather than a second one kept beside it,
        # so what is drawn and the moment the words go cannot drift apart.
        bar = find(window, "membersNoteBar")
        started = float(read(note, "spent"))
        settle(1.2)
        moved = float(read(note, "spent"))
        self.check("the answer draws its own time running out",
                   bar is not None and moved > started and moved < 1,
                   f"{started:.3f} to {moved:.3f} of the way")
        self.check("and the bar is as far along as the time is",
                   abs(float(read(bar, "width"))
                       - (float(read(note, "width")) - 4) * moved) < 6,
                   f"bar {read(bar, 'width'):.0f} px of {read(note, 'width'):.0f}")

        # Being told the same thing twice is still being told it again, and the
        # words alone cannot say so, so the second answer would otherwise run
        # out the first one's clock and vanish early.
        bridge._on_no_membership(channel)
        settle(0.4)
        self.check("and the same answer again starts its time over",
                   float(read(note, "spent")) < moved,
                   f"{moved:.3f} then {read(note, 'spent'):.3f}")

        bridge.clearMembersNote()
        settle(0.3)
        self.check("and the answer goes when its time is up",
                   read(note, "visible") is False)
        # Put the membership back to one nobody holds, which is what the press
        # below is about. Holding one is what makes the press work, and that is
        # checked where mpv is checked rather than by starting a player here.
        db = Database(paths.DB_FILE)
        db.set_member_of(channel, False)
        db.close()
        bridge.reload()
        settle(0.3)
        call(grid, "forceLayout")
        settle(0.3)

        bridge.showChannelTab("members")
        settle(0.5)
        call(grid, "forceLayout")
        settle(0.3)
        self.check("the half holds it", bridge._model.row_for_key("yt:smokevid004") is not None)

        marked = [found for found in
                  (item_named(card, "membersBadge")
                   for card in visible_children(read(grid, "contentItem")))
                  if found is not None and read(found, "visible")]
        self.check("a members only video is marked on its picture",
                   len(marked) == 1, f"{len(marked)} of them")
        word = item_named(marked[0], "membersWord") if marked else None
        self.check("and the mark is a word rather than a symbol",
                   word is not None and str(read(word, "text")) == "MEMBERS",
                   str(read(word, "text")) if word is not None else "no word")

        bridge._set_notice("")
        bridge.play("yt:smokevid004")
        settle(0.4)
        self.check("pressing it starts nothing",
                   read(bridge, "startingKey") == "", str(read(bridge, "startingKey")))
        self.check("and the window says why rather than nothing at all",
                   "members" in str(read(bridge, "notice")).lower(),
                   str(read(bridge, "notice")))
        bridge._set_notice("")
        # Put the walk back where it found it, since everything after this
        # counts the cards in the feed.
        db = Database(paths.DB_FILE)
        with db.conn as conn:
            conn.execute("UPDATE videos SET members_only=0 WHERE key='yt:smokevid004'")
            conn.execute("UPDATE channels SET members_wanted=0, members=NULL, "
                         "member_of=0 WHERE key=?", (channel,))
        db.close()
        bridge.showChannelTab("videos")
        bridge.selectGroup(-1)
        bridge.reload()
        settle(0.4)

    def suggestions(self, bridge, window) -> None:
        """The suggestions page says how old it is and carries its own button.

        It was one button in the toolbar, which nobody read as belonging to
        the page under it.
        """
        root = window.contentItem()
        bridge.showRecommended()
        settle(0.6)
        state = item_named(root, "recommendedState")
        button = item_named(root, "recommendedRefresh")
        self.check("the suggestions page carries its own button",
                   button is not None and str(read(button, "text")) == "Fresh recommendations",
                   str(read(button, "text")) if button is not None else "missing")
        self.check("and says how old they are",
                   state is not None and str(read(state, "text")) != "",
                   str(read(state, "text")) if state is not None else "missing")
        self.check("the bar no longer offers the same thing twice",
                   str(read(find(window, "viewAction"), "text")) == "",
                   str(read(find(window, "viewAction"), "text")))
        # It sits outside the grid, so scrolling cannot take it away. That is
        # what it did as the grid's own header, which builds and drops it as
        # the view moves.
        grid = find(window, "grid")
        write(grid, "contentY", 600.0)
        settle(0.4)
        write(grid, "contentY", 0.0)
        settle(0.5)
        bar = item_named(root, "recommendedHeader")
        self.check("and scrolling does not take the row away",
                   bar is not None and read(bar, "visible")
                   and read(item_named(root, "gridHeader"), "height") > 0,
                   f"height {read(item_named(root, 'gridHeader'), 'height')}")

        bridge.selectGroup(-1)
        settle(0.4)
        self.check("and none of it follows the feed home",
                   item_named(root, "recommendedRefresh") is None
                   or not read(item_named(root, "recommendedRefresh"), "visible"))

    def strangers(self, bridge, window) -> None:
        """A result from a channel nothing is stored about.

        Its picture would be a page fetch per channel on the page, against a
        ceiling the sweep already spends most of, so there is none. What there
        has to be is a way through to the channel, and before this the only
        one was a line of twelve pixel text.
        """
        root = window.contentItem()
        bridge.search("probe")
        settle(0.4)
        bridge._search_scope = "youtube"
        bridge._on_web_results("probe", 1, [{
            "ext_id": "strangervid", "title": "From a stranger",
            "channel_name": "A Stranger", "channel_ext_id": "UCstrangerstrangerstra",
            "duration_s": 300, "views": 10, "published_at": 1_700_000_000,
            "thumbnail_url": None, "live_status": None, "scheduled_at": None,
        }])
        settle(0.6)
        row = bridge._model.row_at(0)
        self.check("a result names the channel behind it",
                   row["channelKey"] == "yt:UCstrangerstrangerstra" and row["channelTitle"] != "",
                   f"{row['channelKey']} {row['channelTitle']}")
        self.check("and has no picture for it, which costs nothing",
                   row["channelAvatar"] == "")
        mark = item_named(root, "channelInitial")
        self.check("so the card draws a letter to press instead",
                   mark is not None and read(mark, "visible") and read(mark, "width") == 44,
                   f"{read(mark, 'width') if mark else 'missing'} px")
        # The name is a link too. Handlers declared inside the Text itself
        # were never offered the press, which is why only the picture worked.
        card = next(iter(visible_children(read(find(window, "grid"), "contentItem"))), None)
        self.check("the name beside it is a link as well",
                   item_named(card, "channelLink") is not None)
        bridge.openChannel(row["channelKey"])
        settle(0.5)
        self.check("and pressing it reaches that channel",
                   read(bridge, "viewKind") == "channel", read(bridge, "viewKind"))
        # All is one of the lists the groups menu offers on a channel page.
        offered = read(bridge, "groups")
        self.check("the groups menu can put a channel in All",
                   any(row["id"] < 0 for row in offered),
                   ", ".join(str(row["name"]) for row in offered))
        bridge.selectGroup(-1)
        settle(0.3)

    def channel_playlists(self, bridge, window) -> None:
        """The playlists half of a channel page.

        Fed by hand, since reading the tab is a request and this walk makes
        none. What it proves is the half itself: the tabs, the tiles, opening
        one and keeping it.
        """
        from weave import paths
        from weave.db import Database, VideoRow
        from weave.sources.playlists import Playlist

        key = "yt:UCsmokesmokesmokesmokes1"
        listed = Database(paths.DB_FILE)
        listed.replace_channel_playlists(key, [
            Playlist(f"PL{n:022d}", f"List {n}", f"https://i.ytimg.com/vi/list{n}/hq.jpg")
            for n in range(3)])
        listed.close()
        bridge.openChannel(key)
        settle(0.5)
        self.check("a channel opens on its videos", read(bridge, "channelTab") == "videos",
                   read(bridge, "channelTab"))
        root = window.contentItem()
        streamsTab = item_named(root, "channelStreamsTab")
        # The other seeded channel, which has one video and has never streamed.
        bridge.openChannel("yt:UCsmokesmokesmokesmokes2")
        settle(0.5)
        self.check("a channel that has never streamed offers no streams half",
                   streamsTab is not None and read(streamsTab, "visible") is False)

        # A stream of theirs, stored the way the streams feed stores one.
        stored = Database(paths.DB_FILE)
        stored.upsert_videos([VideoRow("youtube", "smokestream", key, "A stream that ended",
                                       published_at=1_700_000_500, live_status="was_live")])
        held = len(stored.feed(channel_key=key, hide_watched=False))
        stored.close()
        bridge.selectGroup(-1)
        settle(0.3)
        bridge.openChannel(key)
        settle(0.5)
        self.check("and one that has offers it",
                   read(streamsTab, "visible") is True)
        videos = read(find(window, "grid"), "count")
        bridge.showChannelTab("streams")
        settle(0.5)
        streams = read(find(window, "grid"), "count")
        badges = [item for item in items_named_like(root, "streamBadge")
                  if read(item, "visible")]
        self.check("a recording of a stream is badged as one",
                   len(badges) == 1, f"{len(badges)} badged")
        self.check("the two halves are the whole channel between them and nothing twice",
                   streams >= 1 and videos >= 1 and videos + streams == held,
                   f"{videos} videos, {streams} streams, {held} stored")
        bridge.showChannelTab("videos")
        settle(0.4)
        bridge.showChannelTab("playlists")
        settle(0.6)
        tiles = read(bridge, "channelPlaylists")
        self.check("and its playlists are a half of their own", len(tiles) == 3,
                   f"{len(tiles)} listed")
        self.check("with no count until one is opened",
                   all(tile["itemsText"] == "" for tile in tiles))
        self.check("and a picture from the listing, which costs no request",
                   all(tile["thumbnail"] != "" for tile in tiles),
                   ", ".join(str(tile["thumbnail"])[:24] for tile in tiles))
        self.check("drawn as tiles", item_named(root, "playlistTile") is not None)

        bridge.openChannelPlaylist(tiles[0]["key"], tiles[0]["title"])
        settle(0.5)
        self.check("opening one shows it", read(bridge, "viewKind") == "playlist"
                   and read(bridge, "viewPlaylist") == tiles[0]["key"],
                   f"{read(bridge, 'viewKind')} {read(bridge, 'viewPlaylist')}")
        self.check("and it stays out of your own playlists",
                   not any(row["ext_id"] == tiles[0]["key"] for row in read(bridge, "playlists")))

        bar = item_named(root, "playlistHeader")
        self.check("a bar above it says where it came from",
                   bar is not None and read(bar, "visible") is True)
        back = item_named(root, "playlistBack")
        self.check("with the channel named on the way back",
                   back is not None and "Smoke" in str(read(back, "text")),
                   str(read(back, "text")) if back else "no button")
        call(back, "clicked")
        settle(0.5)
        self.check("and pressing it lands on the playlists half again",
                   read(bridge, "viewKind") == "channel"
                   and read(bridge, "channelTab") == "playlists",
                   f"{read(bridge, 'viewKind')} {read(bridge, 'channelTab')}")

        bridge.openChannelPlaylist(tiles[0]["key"], tiles[0]["title"])
        settle(0.5)
        keep = item_named(root, "playlistKeep")
        self.check("the bar offers keeping it", read(keep, "text") == "Keep",
                   str(read(keep, "text")))
        call(keep, "clicked")
        settle(0.4)
        self.check("and says so once it is kept", read(keep, "text") == "Kept",
                   str(read(keep, "text")))
        bridge.keepPlaylist(tiles[0]["key"], False)
        settle(0.3)

        bridge.keepPlaylist(tiles[0]["key"], True)
        settle(0.4)
        self.check("keeping it gives it a place of its own",
                   [row["ext_id"] for row in read(bridge, "keptPlaylists")] == [tiles[0]["key"]],
                   ", ".join(str(row["title"]) for row in read(bridge, "keptPlaylists")))

        # The wheel over the sidebar walks the selection rather than scrolling,
        # so a section it does not know about cannot be reached with a wheel at
        # all. The kept ones were drawn below the last entry it walked.
        bridge.keepPlaylist(tiles[0]["key"], True)
        settle(0.4)
        bridge.selectGroup(-1)
        settle(0.3)
        reached = False
        for _ in range(40):
            bridge.stepSelection(1)
            if read(bridge, "viewPlaylist") == tiles[0]["key"]:
                reached = True
                break
        settle(0.3)
        self.check("the wheel reaches the kept ones at the foot of the sidebar", reached,
                   f"{read(bridge, 'viewKind')} {read(bridge, 'viewPlaylist')}")

        heading = find(window, "keptHeading")
        self.check("the section has a heading of its own, with room to be seen",
                   heading is not None and read(heading, "visible") is True
                   and float(read(heading, "height")) > 0,
                   f"height {read(heading, 'height') if heading else 'no heading'}")

        chooser = find(window, "keptChooser")
        call(chooser, "open")
        settle(0.4)
        self.check("they have a settings window of their own",
                   read(chooser, "opened") is True)
        rows = items_named_like(root, "keptDrop")
        self.check("with a way to let one go", len(rows) == 1, f"{len(rows)} rows")
        call(rows[0], "clicked")
        settle(0.4)
        self.check("which takes it out of the section",
                   read(bridge, "keptPlaylists") == [])
        call(chooser, "close")
        settle(0.3)
        bridge.selectGroup(-1)
        settle(0.3)

    def bar(self, bridge, window) -> None:
        """The line in the bar has to say all of what it says.

        It was cut short with plenty of bar left over, because its cell was
        sized from the label's own implicit width, which the label then elided
        to fit the cell.
        """
        label = find(window, "status")
        for text in ("feeds 12 of 15", "durations 1 of 1",
                     "455 subscriptions found, 12 newly tracked"):
            bridge._set_status(text)
            settle(0.35)
            self.check(f"the bar says {text.split()[0]} in full",
                       read(label, "width") >= read(label, "implicitWidth") - 1,
                       f"{read(label, 'width'):.0f} of {read(label, 'implicitWidth'):.0f}")

    def following(self, bridge, window) -> None:
        """Following a channel by name, which the plus above the list offers.

        It was a box in the toolbar beside the search box, which asked people
        to know the difference between the two before they had used either.
        """
        root = window.contentItem()
        self.check("the toolbar holds one box, not two", find(window, "addField") is None)
        menu = find(window, "channelsMenu")
        menu.open()
        settle(0.3)
        entries = [text.strip() for text, _ in menu_entries(menu)]
        self.check("the plus offers both things it could mean",
                   entries == ["Follow a channel", "New group"], ", ".join(entries))
        menu.close()
        settle(0.2)

        popup = find(window, "followChannel")
        popup.open()
        settle(0.4)
        self.check("following one opens its own box",
                   item_named(root, "followField") is not None)
        bridge.addChannel("definitely not a channel")
        settle(0.4)
        answer = item_named(root, "followAnswer")
        self.check("and it says when a reference is not one",
                   answer is not None and read(answer, "visible"),
                   str(read(answer, "text")) if answer is not None else "missing")
        popup.close()
        settle(0.3)

    def boxes(self, bridge, window) -> None:
        """A box is ordered by hand the way a group is."""
        first = bridge.createBox("Alpha")
        second = bridge.createBox("Beta")
        settle(0.3)
        menu = find(window, "boxMenu")
        write(menu, "boxId", first)
        write(menu, "boxName", "Alpha")
        menu.open()
        settle(0.3)
        entries = [text.strip() for text, _ in menu_entries(menu)]
        self.check("the box menu is in the order he asked for",
                   entries == ["Rename", "Move up", "Move down", "Delete the box"],
                   ", ".join(entries))
        menu.close()
        settle(0.2)
        names = [box["name"] for box in read(bridge, "boxes")]
        bridge.moveBox(second, -1)
        settle(0.3)
        moved = [box["name"] for box in read(bridge, "boxes")]
        self.check("a box can be moved up", moved.index("Beta") < moved.index("Alpha"),
                   f"{', '.join(names)} to {', '.join(moved)}")
        bridge.moveBox(second, 1)
        settle(0.3)
        back = [box["name"] for box in read(bridge, "boxes")]
        self.check("and down again", back == names, ", ".join(back))
        # The same question for a box, which lists its videos.
        bridge.addToBox(first, "yt:smokevid001")
        settle(0.3)
        confirm = find(window, "confirmDelete")
        confirm.ask("box", first, "Alpha")
        settle(0.4)
        self.check("deleting a box asks first too", read(confirm, "visible"))
        self.check("and lists the videos in it",
                   read(find(window, "confirmMembers"), "count") == 1,
                   f"count {read(find(window, 'confirmMembers'), 'count')}")
        call(find(window, "confirmDeleteButton"), "click")
        settle(0.4)
        self.check("and the button on it does the deleting",
                   not any(box["id"] == first for box in read(bridge, "boxes")))

        bridge.deleteBox(second)
        settle(0.3)

    def wizard(self, bridge, window) -> None:
        """The pages a fresh install is walked through.

        Opened by hand here. Whether they open by themselves is a rule about
        channels and Twitch, and this walk has both of those in whatever state
        the steps before it left them.
        """
        root = window.contentItem()
        # The settings page says which theme is in use, and it is built whether
        # or not it is the view showing, so it answers from here too.
        current = find(window, "currentTheme")
        bridge.openWizard()
        settle(0.5)
        # The popup itself is not a visual item, so what is looked for is what
        # it draws.
        self.check("the getting started pages open",
                   read(bridge, "wizardOpen") and item_named(root, "wizardTitle") is not None)
        self.check("they begin at the welcome",
                   str(read(item_named(root, "wizardTitle"), "text")) == "Welcome to Weave",
                   str(read(item_named(root, "wizardTitle"), "text")))
        self.check("with nothing to go back to", not read(item_named(root, "wizardBack"), "enabled"))

        titles = []
        while str(read(item_named(root, "wizardNext"), "text")) != "Done":
            bridge.stepWizard(1)
            settle(0.3)
            titles.append(str(read(item_named(root, "wizardTitle"), "text")))
            if len(titles) > 8:
                break
        self.check("and walk through the rest", len(titles) >= 3 and all(titles),
                   ", ".join(titles))

        self.check("the last one finishes rather than going on",
                   str(read(item_named(root, "wizardNext"), "text")) == "Done",
                   str(read(item_named(root, "wizardNext"), "text")))
        if self.shot:
            self.check("wizard written", screenshot(window, shot_beside(self.shot, "wizard")))

        # The themes are tried here rather than described, so the buttons have
        # to be the real ones and pressing one has to change the window.
        # Back onto the page that holds them, since the walk above ended on the
        # last one.
        bridge.stepWizard(-1)
        settle(0.4)
        was = str(read(current, "text"))
        buttons = items_named_like(item_named(root, "wizardThemes"), "wizardTheme")
        self.check("the themes can be tried from the pages", len(buttons) > 3,
                   f"{len(buttons)} of them")
        other = next(item for item in buttons if str(read(item, "text")) != was)
        call(other, "click")
        settle(0.4)
        self.check("and pressing one changes the window",
                   str(read(current, "text")) == str(read(other, "text")),
                   f"{was} to {read(current, 'text')}")
        call(next(item for item in buttons if str(read(item, "text")) == was), "click")
        settle(0.3)
        self.check("and the one it was on can be taken back",
                   str(read(current, "text")) == was, str(read(current, "text")))

        # The import page has to be able to say why it failed, since that is
        # the step that fails and the reason is never obvious.
        bridge.stepWizard(-3)
        bridge._on_import_failed("yt-dlp said: Sign in to confirm you are not a bot")
        settle(0.4)
        said = str(read(item_named(root, "wizardImportState"), "text"))
        self.check("a failed import says what went wrong", "Sign in" in said, said)

        bridge.setWizardHidden(True)
        settle(0.2)
        self.check("the box is remembered", read(bridge, "wizardHidden"))
        bridge.setWizardHidden(False)

        # Not modal on purpose. The overlay a modal popup brings swallows every
        # press that misses the card, and this window has no frame of its own,
        # so that would take away moving and resizing it while these are open.
        # The ground behind is a rectangle with no handler on it instead.
        popup = find(window, "wizard")
        self.check("they do not take the window hostage",
                   popup is not None and not read(popup, "modal") and not read(popup, "dim"))
        dim = find(window, "wizardDim")
        self.check("but the window behind is dimmed", dim is not None and read(dim, "visible"))

        call(item_named(root, "wizardClose"), "click")
        settle(0.4)
        self.check("the cross closes them", not read(bridge, "wizardOpen"))
        self.check("and the ground behind goes with them", not read(dim, "visible"))

    def updates(self, bridge, window) -> None:
        """News of a newer release, at the foot of the panel.

        Fed by hand here. The real answer comes from one request a day, which
        an offline walk must not make and could not rely on anyway.
        """
        line = find(window, "updateLine")
        self.check("nothing is said while there is no newer release",
                   not read(line, "visible"))
        bridge._on_update_found("v99.0.0", "https://example.invalid/releases/99.0.0")
        settle(0.4)
        self.check("a newer release shows at the foot of the panel", read(line, "visible"))
        self.check("and it says which one", read(bridge, "updateVersion") == "99.0.0",
                   str(read(bridge, "updateVersion")))
        self.check("in words rather than a number alone",
                   str(read(find(window, "updateHeadline"), "text")) == "A new version is available",
                   str(read(find(window, "updateHeadline"), "text")))
        self.check("and the list keeps clear of it",
                   read(find(window, "sidebarDrag"), "height") >= 0
                   and read(line, "height") > 0, f"{read(line, 'height'):.0f} px")
        if self.shot:
            self.check("update written", screenshot(window, shot_beside(self.shot, "update")))

        # The case that matters after an update has been installed.
        bridge._on_update_found("v" + str(read(bridge, "version")), "")
        settle(0.3)
        self.check("the version already running is never announced",
                   not read(line, "visible") and read(bridge, "updateVersion") == "",
                   str(read(bridge, "updateVersion")))

    def group_bar(self, bridge, window, group_id) -> None:
        """The row of buttons over a group, and where the first row starts.

        The history keeps its bar in place, because the two words there are the
        whole page. A group's three are a filter over a grid that gets
        scrolled, so they are drawn over the top of the grid and go with the
        reading. What has to hold either way is that the cards start at the
        same height, which is why the grid carries the room the buttons take as
        a content margin in a group and as a bar above it everywhere else.
        """
        from weave import paths
        from weave.db import Database, VideoRow

        # A channel of this step's own, put back at the end. The two seeded
        # channels are what the rest of the walk counts and searches, and one
        # of them is the channel that has never streamed, so borrowing either
        # of them here quietly broke two checks further down.
        third = "yt:UCsmokesmokesmokesmokes3"
        db = Database(paths.DB_FILE)
        db.remember_channel(third, "youtube", "UCsmokesmokesmokesmokes3", "Smoke three")
        # Enough to scroll, plus one stream, so all three buttons have
        # something different to answer. Remembered rather than followed, so
        # none of it reaches All.
        db.upsert_videos([
            VideoRow("youtube", f"grouponly{i:02d}", third, f"Third {i:02d}",
                     published_at=1_700_000_200 + i, duration_s=300)
            for i in range(20)
        ])
        db.upsert_videos([VideoRow("youtube", "groupstream1", third, "Third stream",
                                   published_at=1_700_000_300, duration_s=3600,
                                   live_status="was_live")])
        db.close()
        bridge.addChannelToGroup(group_id, third)
        settle(0.3)

        grid = find(window, "grid")
        # Measured in the history first, which is the bar this one has to line
        # up with. Its own y plus how far its content is pushed down is where
        # the first card sits, whichever way the room above is made.
        bridge.showHistory()
        settle(0.4)
        history_first = read(grid, "y") - read(grid, "contentY")

        bridge.selectGroup(group_id)
        settle(0.5)
        wait_until(lambda: read(grid, "count") > 20, 4.0)
        call(grid, "forceLayout")
        settle(0.2)

        clip = find(window, "groupBarClip")
        bar = find(window, "groupBar")
        edge = find(window, "groupBarEdge")
        ground = find(window, "groupBarGround")
        self.check("a group has the row of buttons",
                   clip is not None and bar is not None and read(clip, "visible"))
        if clip is None or bar is None or ground is None or edge is None:
            return

        group_first = read(grid, "y") - read(grid, "contentY")
        self.check("and its first row starts where the history's does",
                   abs(group_first - history_first) < 1,
                   f"history {history_first:.0f}, group {group_first:.0f}")
        self.check("the buttons are in place before anything is scrolled",
                   read(bar, "y") == 0, f"y {read(bar, 'y'):.0f}")
        self.check("with no line under them, since nothing is behind them",
                   read(edge, "opacity") == 0, f"opacity {read(edge, 'opacity'):.2f}")
        # The ground behind the buttons is the window's own, held still against
        # the window rather than sliding with them, so the strip is the colour
        # the window is painted at that height whatever the theme washes it
        # with. A flat colour here was the base under the wash and looked it.
        self.check("their ground is the window's own, lined up with it",
                   abs(read(ground, "y") + read(clip, "y") + read(bar, "y")) < 1
                   and abs(read(ground, "x") + read(clip, "x")) < 1,
                   f"ground at {read(ground, 'x'):.0f},{read(ground, 'y'):.0f} "
                   f"clip at {read(clip, 'x'):.0f},{read(clip, 'y'):.0f}")

        # All three, on rows that are already stored, so none of this asks
        # anything of YouTube.
        both = read(grid, "count")
        call(find(window, "groupVideos"), "click")
        settle(0.4)
        videos = read(grid, "count")
        call(find(window, "groupStreams"), "click")
        settle(0.4)
        streams = read(grid, "count")
        call(find(window, "groupAll"), "click")
        settle(0.4)
        self.check("videos and streams are the two halves of all of it",
                   videos + streams == both and videos > 0 and streams > 0,
                   f"all {both}, videos {videos}, streams {streams}")
        self.check("and all of it comes back", read(grid, "count") == both,
                   f"count {read(grid, 'count')}")
        self.check("which half is showing is remembered on the group",
                   str(read(bridge, "groupShows")) == "all",
                   str(read(bridge, "groupShows")))

        room = read(grid, "contentHeight") - read(grid, "height")
        self.check("the group is long enough to scroll", room > 0, f"{room:.0f} px")
        write(grid, "contentY", 300.0)
        settle(0.5)
        self.check("scrolling down takes the buttons out of the way",
                   read(bar, "y") <= -read(clip, "barHeight") + 1, f"y {read(bar, 'y'):.0f}")
        self.check("and out of reach with them", not read(bar, "enabled"))
        self.check("the line is under them once there is a card behind",
                   read(edge, "opacity") == 1, f"opacity {read(edge, 'opacity'):.2f}")
        self.check("and their ground is still held against the window",
                   abs(read(ground, "y") + read(clip, "y") + read(bar, "y")) < 1,
                   f"ground {read(ground, 'y'):.0f} clip {read(clip, 'y'):.0f} "
                   f"bar {read(bar, 'y'):.0f}")
        # And that they take the strip they sat in with them. The ground under
        # them is the whole window and is held still against it, so it stayed
        # behind when they left and went on painting a band of empty window
        # over the top of the grid, hiding whatever card was passing under.
        #
        # Measured rather than reasoned about, and by counting colours per row
        # rather than naming one, so it holds on any of the fourteen themes
        # and whatever the cards happen to be showing: a row of bare window is
        # one flat colour, a row with cards in it is not. With the band left
        # behind, every one of these rows was flat; with it gone, most are not.
        #
        # Offscreen paints nothing until it is asked to, and the first grab of
        # a run comes back before the scene graph has drawn, so it is asked
        # twice and the second one is the picture.
        window.grabWindow()
        settle(0.2)
        frame = window.grabWindow()
        rows = range(32, 86, 6)
        lively = sum(1 for down in rows
                     if colours_across(frame, read(grid, "x") + 4,
                                       read(grid, "y") + down,
                                       read(grid, "width") - 8) > 1)
        self.check("and leave the top of the grid to the cards", lively > 0,
                   f"{lively} of {len(rows)} rows below the top hold more than one colour")

        write(grid, "contentY", 250.0)
        settle(0.5)
        self.check("turning round brings them back", read(bar, "y") == 0,
                   f"y {read(bar, 'y'):.0f}")

        write(grid, "contentY", 900.0)
        settle(0.5)
        self.check("and down again takes them away again",
                   read(bar, "y") <= -read(clip, "barHeight") + 1, f"y {read(bar, 'y'):.0f}")
        write(grid, "contentY", -float(read(grid, "topMargin")))
        settle(0.5)
        self.check("back at the top they are in place with no line",
                   read(bar, "y") == 0 and read(edge, "opacity") == 0,
                   f"y {read(bar, 'y'):.0f} opacity {read(edge, 'opacity'):.2f}")
        if self.shot:
            screenshot(window, shot_beside(self.shot, "groupbar"))

        bridge.selectGroup(-1)
        settle(0.4)
        self.check("and no other view has them",
                   not read(clip, "visible"))

        # Put back, so what the rest of the walk counts is what it seeded.
        db = Database(paths.DB_FILE)
        db.remove_from_group(group_id, third)
        db.remove_channel(third)
        db.close()
        bridge.reload()
        settle(0.3)

    def scrolling(self, bridge, window) -> None:
        """A refresh landing while somebody is reading must not move the page.

        This is the one the reader notices. A poll finishes once a minute and
        reloads the grid, and while the model reset for that, the grid went
        back to the top at what felt like random moments.
        """
        from weave import paths
        from weave.db import Database, VideoRow

        db = Database(paths.DB_FILE)
        db.upsert_videos([
            VideoRow("youtube", f"scrollvid{i:02d}", "yt:UCsmokesmokesmokesmokes1",
                     f"Scroll {i}", published_at=1_600_000_000 + i, duration_s=60)
            for i in range(40)
        ])
        bridge.selectGroup(-1)
        bridge.reload()
        settle(0.4)
        grid = find(window, "grid")
        # The rows reach the model at once and the view lays them out when it
        # next draws, which offscreen it may not hurry to do. Measured with the
        # count already at forty six and the content still the height of two
        # rows, so the layout is asked for rather than waited on.
        wait_until(lambda: read(grid, "count") > 40, 4.0)
        call(grid, "forceLayout")
        settle(0.2)
        room = read(grid, "contentHeight") - read(grid, "height")
        self.check("the feed is long enough to scroll", room > 0,
                   f"{room:.0f} px of room, {read(grid, 'count')} cards")
        QQmlProperty.write(grid, "contentY", 300.0)
        settle(0.3)
        was = read(grid, "contentY")

        # What a poll comes back with almost every time: the same videos.
        bridge.reload()
        settle(0.4)
        self.check("a refresh with the same videos does not move the page",
                   abs(read(grid, "contentY") - was) < 1, f"{was:.0f} to {read(grid, 'contentY'):.0f}")

        # And what it comes back with when something was published.
        db.upsert_videos([VideoRow("youtube", "scrollfresh", "yt:UCsmokesmokesmokesmokes1",
                                   "Fresh", published_at=1_900_000_000, duration_s=60)])
        bridge.reload()
        settle(0.4)
        self.check("a new video arriving does not move it either",
                   abs(read(grid, "contentY") - was) < 1,
                   f"{was:.0f} to {read(grid, 'contentY'):.0f}")
        # Six seeded, forty for the scroll, the stream stored on the channel
        # page above and this one. The seventh seeded video is in a group
        # only, so All never held it, and the stream is here because a stream
        # of a channel you follow belongs in what you follow.
        self.check("and the new video is in the grid",
                   read(grid, "count") == 48, f"count {read(grid, 'count')}")

        # A view change is the case that should go back to the top.
        bridge.showHistory()
        settle(0.3)
        bridge.selectGroup(-1)
        settle(0.4)
        self.check("changing view starts at the top", read(grid, "contentY") <= 0,
                   f"{read(grid, 'contentY'):.0f}")
        db.close()

    def run(self, engine, bridge, window) -> None:
        self.warnings = Warnings(engine)
        settle(1.2)
        # A scratch home has channels seeded and no Twitch, which is exactly
        # what the getting started pages are for, so they are already open and
        # everything below is behind them until they are put away.
        self.check("the getting started pages open themselves on a fresh copy",
                   read(bridge, "wizardOpen"))
        bridge.closeWizard()
        settle(0.3)
        grid = find(window, "grid")
        self.check("grid has the seeded videos", read(grid, "count") == 6,
                   f"count {read(grid, 'count')}")

        # Every view, since a binding that only exists in one of them is only
        # evaluated once that view is shown.
        for name, slot in (("music", "showMusic"), ("debug", "showDebug"),
                           ("settings", "showSettings"),
                           ("recommended", "showRecommended"), ("history", "showHistory")):
            getattr(bridge, slot)()
            settle(0.3)
            self.check(f"{name} view opens", read(bridge, "viewKind") == name)
        bridge.selectGroup(-1)
        settle(0.3)

        self.music(bridge, window)

        # A box, then the video menu, whose box entries sit between the
        # separator and the last entry however many entries come above.
        box_id = bridge.createBox("Later")
        settle(0.2)
        menu = find(window, "videoMenu")
        menu.open()
        settle(0.3)
        labels = [text.strip() for text, _ in menu_entries(menu)]
        self.check("video menu opens with its entries", len(labels) >= 6, ", ".join(labels))
        box_at = next((i for i, text in enumerate(labels) if text.endswith("Later")), -1)
        self.check("box entry sits before the last entry",
                   0 < box_at == len(labels) - 2, f"at {box_at} of {len(labels)}")
        menu.close()
        settle(0.2)
        bridge.deleteBox(box_id)

        # A group made and found in the sidebar list.
        before = len(read(bridge, "groups"))
        group_id = bridge.createGroup("Smoke group")
        settle(0.2)
        self.check("a new group appears", len(read(bridge, "groups")) == before + 1)

        # The group's own window, and the rule it exists for: a channel put in
        # a group is followed for that group and All is left as it was.
        other = "yt:UCsmokesmokesmokesmokes2"
        bridge.addChannelToGroup(group_id, other)
        settle(0.3)
        bridge.selectGroup(group_id)
        settle(0.4)
        self.check("the group shows the channel put in it", read(grid, "count") == 1,
                   f"count {read(grid, 'count')}")
        bridge.selectGroup(-1)
        settle(0.4)
        self.check("and All is exactly as it was", read(grid, "count") == 6,
                   f"count {read(grid, 'count')}")

        self.group_bar(bridge, window, group_id)

        menu = find(window, "groupMenu")
        write(menu, "groupId", group_id)
        write(menu, "groupName", "Smoke group")
        menu.open()
        settle(0.3)
        labels = [text.strip() for text, _ in menu_entries(menu)]
        self.check("the group menu is in the order he asked for",
                   labels == ["Rename", "Move up", "Move down", "Manage the group",
                              "Delete the group"], ", ".join(labels))
        menu.close()
        settle(0.2)

        # Deleting asks first, and shows what is inside so the right one goes.
        confirm = find(window, "confirmDelete")
        confirm.ask("group", group_id, "Smoke group")
        settle(0.4)
        self.check("deleting a group asks first", read(confirm, "visible"))
        self.check("and says which one",
                   str(read(find(window, "confirmName"), "text")) == "Smoke group",
                   str(read(find(window, "confirmName"), "text")))
        self.check("and lists what is in it",
                   read(find(window, "confirmMembers"), "count") == 1,
                   f"count {read(find(window, 'confirmMembers'), 'count')}")
        call(find(window, "confirmCancel"), "click")
        settle(0.3)
        self.check("and keeping it changes nothing",
                   not read(confirm, "visible")
                   and any(row["id"] == group_id for row in read(bridge, "groups")))

        # All is managed through the same window, and taking a channel out of
        # it is a decision the next import must not undo.
        write(menu, "groupId", -1)
        menu.open()
        settle(0.3)
        all_entries = [text.strip() for text, item in menu_entries(menu)
                       if read(item, "visible")]
        self.check("All offers only what it can do", all_entries == ["Manage All"],
                   ", ".join(all_entries))
        menu.close()
        settle(0.2)

        # All, which for him is several hundred channels, so it is searched
        # rather than read through, and a reload arriving while somebody is
        # scrolling must not throw them back to the top.
        from weave import paths
        from weave.db import Database

        many = Database(paths.DB_FILE)
        for number in range(20):
            many.add_channel(f"yt:UCdrive{number:018d}", "youtube",
                             f"UCdrive{number:018d}", f"Channel {number:02d}")
        many.close()
        manage = find(window, "manageGroup")
        write(manage, "groupId", -1)
        manage.open()
        settle(0.6)
        rows = find(window, "manageGroupList")
        self.check("All can be managed like a group",
                   read(manage, "everyone").__len__() > 0,
                   f"{len(read(manage, 'everyone'))} channels")
        search = find(window, "manageSearchField")
        self.check("with a search when there are many", search is not None)

        # Something typed into it has to say whether it worked. The status
        # line does, but this window is drawn over it.
        answer = find(window, "manageAddAnswer")
        self.check("nothing is claimed before anything is typed",
                   not read(answer, "visible"), str(read(answer, "text")))
        bridge.addChannelToGroupByRef(-1, "definitely not a channel")
        settle(0.4)
        self.check("a reference that is not one says so",
                   read(answer, "visible") and read(bridge, "addState") == "failed",
                   str(read(answer, "text")))
        bridge.clearAddState()
        settle(0.2)
        self.check("and typing again clears the answer", not read(answer, "visible"))

        # A channel that resolves has to appear in the list it was added to
        # without the window being closed and opened again.
        was = len(read(manage, "everyone"))
        bridge._adding = -1
        bridge._on_channel_added("yt:UCaddedaddedaddedadded1", "youtube",
                                 "UCaddedaddedaddedadded1", "Added by hand")
        settle(0.6)
        self.check("one that is added appears at once",
                   len(read(manage, "everyone")) == was + 1,
                   f"{was} to {len(read(manage, 'everyone'))}")
        write(rows, "contentY", 40.0)
        settle(0.2)
        bridge.groupsChanged.emit()
        settle(0.4)
        self.check("and a reload does not throw the list back to the top",
                   abs(read(rows, "contentY") - 40.0) < 1, f"{read(rows, 'contentY'):.0f}")
        manage.close()
        settle(0.3)

        manage = find(window, "manageGroup")
        write(manage, "groupId", group_id)
        write(manage, "groupName", "Smoke group")
        call(manage, "open")
        settle(0.4)
        rows = find(window, "manageGroupList")
        self.check("the group window lists who is in it",
                   bool(read(manage, "visible")) and read(rows, "count") == 1,
                   f"count {read(rows, 'count')}")
        bridge.removeChannelFromGroup(group_id, other)
        settle(0.4)
        self.check("and empties as the last one is taken out", read(rows, "count") == 0,
                   f"count {read(rows, 'count')}")
        call(manage, "close")
        settle(0.2)
        bridge.deleteGroup(group_id)
        settle(0.2)

        # The two popups open and close cleanly.
        for name in ("playlistChooser", "namePopup"):
            popup = find(window, name)
            call(popup, "open")
            settle(0.3)
            opened = bool(read(popup, "visible"))
            call(popup, "close")
            settle(0.2)
            self.check(f"{name} opens and closes", opened and not read(popup, "visible"))

        # Search, local, then back out of it.
        bridge.search("Video 3")
        settle(0.3)
        self.check("local search shows one match",
                   read(bridge, "viewKind") == "search" and read(grid, "count") == 1)
        bridge.search("")
        settle(0.3)
        self.check("emptying the search returns to the feed", read(bridge, "viewKind") == "all")

        # The settings page. Last, so the picture is of the page rather than
        # of the grid, and so the theme it is drawn in is the one just chosen.
        bridge.showDebug()
        settle(0.2)
        bridge.stepSelection(1)
        settle(0.3)
        self.check("the wheel walks from How things are onto Settings",
                   read(bridge, "viewKind") == "settings", read(bridge, "viewKind"))
        bridge.stepSelection(-1)
        settle(0.3)
        self.check("and back off it the way it came",
                   read(bridge, "viewKind") == "debug", read(bridge, "viewKind"))

        # Both of these pages are a column of rows rather than a grid, and both
        # scrolled at whatever a Flickable does by itself until they were given
        # the wheel step the videos use.
        for page in ("debugView", "settingsView"):
            view = find(window, page)
            self.check(f"{page} lends out the part that scrolls",
                       view is not None and read(view, "scrolls") is not None)

        # The report the page can write, which is the thing somebody sends when
        # nothing is arriving. Written for real, into the scratch home this
        # walk runs in.
        root = window.contentItem()
        save = item_named(root, "exportReport")
        self.check("the page offers to save a report", save is not None)
        call(save, "clicked")
        ok = wait_until(lambda: read(bridge, "reportPath") != "", 20.0)
        self.check("and writing one says where it went", ok, read(bridge, "reportPath"))
        if ok:
            import zipfile
            with zipfile.ZipFile(read(bridge, "reportPath")) as bundle:
                held = sorted(bundle.namelist())
            self.check("the report holds the checks and the numbers",
                       "checks.txt" in held and "numbers.txt" in held, ", ".join(held))
        line = item_named(root, "reportLine")
        self.check("and the page says so", line is not None and read(line, "visible") is True)

        bridge.showSettings()
        settle(0.4)

        # The theme picker that replaced the toolbar's menu, which is the one
        # thing on the page that changes what the window looks like.
        current = find(window, "currentTheme")
        # A Repeater's delegates are visual children and not QObject children,
        # so findChild cannot reach them and childItems can. They arrive as
        # plain items rather than as buttons too, so the press is invoked
        # rather than called.
        choices = [item for item in find(window, "themeChoices").childItems()
                   if str(read(item, "objectName")).startswith("themeChoice")]
        labels = [str(read(item, "text")) for item in choices]
        self.check("the settings page offers the themes", len(choices) >= 2, ", ".join(labels))
        was = str(read(current, "text"))
        other = next((item for item in choices if str(read(item, "text")) != was), None)
        if other is not None:
            call(other, "click")
            settle(0.3)
            self.check("a theme can be chosen from the page",
                       str(read(current, "text")) == str(read(other, "text")),
                       f"{was} to {read(current, 'text')}")
            call(next(item for item in choices if str(read(item, "text")) == was), "click")
            settle(0.3)
            self.check("and the one it was on chosen again", str(read(current, "text")) == was,
                       str(read(current, "text")))

        # The ceiling for the pictures. Its entries live in a menu, whose
        # items are not visual children of anything reachable here, so the
        # choice is made through the same slot the menu calls and the button
        # is read to prove the binding followed.
        ceiling = find(window, "cacheCeiling")
        offered = [row["megabytes"] for row in read(bridge, "cacheChoices")]
        self.check("the settings page offers a ceiling for the pictures",
                   read(bridge, "cacheCeiling") in offered,
                   f"{read(bridge, 'cacheCeilingText')} of " + ", ".join(str(m) for m in offered))
        self.check("the button says which one is in force",
                   read(bridge, "cacheCeilingText") in str(read(ceiling, "text")),
                   str(read(ceiling, "text")))
        was = read(bridge, "cacheCeiling")
        other = next(m for m in offered if m != was)
        bridge.setCacheCeiling(other)
        settle(0.4)
        self.check("a different one can be chosen", read(bridge, "cacheCeiling") == other,
                   f"{was} to {read(bridge, 'cacheCeiling')}")
        self.check("and the line under the buttons says so",
                   read(bridge, "cacheCeilingText") in str(read(find(window, "cacheSize"), "text")),
                   str(read(find(window, "cacheSize"), "text")))
        bridge.setCacheCeiling(was)
        settle(0.4)
        self.check("and the one it was on chosen again",
                   read(bridge, "cacheCeiling") == was, str(read(ceiling, "text")))

        # And the same fact in the check list, which is what a report of what
        # went wrong is made from. Read off the property the page draws.
        bridge.runChecks(False)
        settle(1.2)
        checks = read(bridge, "checks")
        first = checks[0] if checks else {}
        self.check("the check list leads with which Weave this is",
                   first.get("name") == "Weave" and read(bridge, "version") in first.get("detail", ""),
                   f"{first.get('name')}: {first.get('detail')}")

        # Which copy this is, so the version can be read without a terminal.
        self.check("the page states the version running",
                   str(read(find(window, "runningVersion"), "text")) == read(bridge, "version"),
                   str(read(find(window, "runningVersion"), "text")))
        newest = find(window, "newestVersion")
        self.check("and what the newest one is",
                   str(read(newest, "text")) != "", str(read(newest, "text")))
        self.check("the release page cannot be opened before one is known",
                   not read(find(window, "openRelease"), "enabled"))
        bridge._on_update_found("v99.0.0", "https://example.invalid/releases/99.0.0")
        settle(0.3)
        self.check("a newer one is named here too",
                   "99.0.0" in str(read(newest, "text")), str(read(newest, "text")))
        self.check("and then the release page can be opened",
                   read(find(window, "openRelease"), "enabled"))
        bridge._on_update_found("v" + str(read(bridge, "version")), "")
        settle(0.3)
        self.check("with nothing newer it says so without alarm",
                   "this one" in str(read(newest, "text")), str(read(newest, "text")))

        # What the page says about the cache and the connections, which is
        # read rather than acted on, so an empty one is a binding that failed.
        for name in ("cacheSize", "cookieSource", "musicIdentity", "twitchState"):
            self.check(f"the page states the {name}", str(read(find(window, name), "text")) != "",
                       str(read(find(window, name), "text")))

        self.starting(bridge, window)
        self.updates(bridge, window)
        self.announcements(bridge, window)
        self.members(bridge, window)
        self.chapters(bridge, window)
        self.suggestions(bridge, window)
        self.strangers(bridge, window)
        self.channel_playlists(bridge, window)
        self.bar(bridge, window)
        self.following(bridge, window)
        self.boxes(bridge, window)
        self.wizard(bridge, window)
        self.scrolling(bridge, window)

        if self.shot:
            self.check("screenshot written", screenshot(window, self.shot), self.shot)


def shot_beside(path: str, suffix: str) -> str:
    """A second picture next to the one that was asked for."""
    where = Path(path)
    return str(where.with_name(f"{where.stem}-{suffix}{where.suffix}"))


# How long the walk may go without waiting for anything before it is called
# hung, and the outermost bound whatever it does.
QUIET_LIMIT_S = 90.0
WHOLE_LIMIT_S = 900.0


def boot(walk, quiet_s: float = QUIET_LIMIT_S, whole_s: float = WHOLE_LIMIT_S) -> int:
    """Start the real application, hand the window to `walk`, then quit.

    The walk runs inside one event loop callback, so it quits the application
    itself when it is done and the timer here is only for a walk that never
    finishes. That timer used to be a flat deadline of thirty seconds, and the
    walk grew past it: it then fired in the MIDDLE of a walk, and everything
    after that point ran while the application was already quitting. A
    grabWindow() in that state took the whole process down with a fault inside
    the scene graph, which cost hours and looked like a bug in the pictures.

    So it is a watchdog on the heartbeat rather than a deadline. Every wait the
    walk does bumps a counter; a walk still counting is left alone however long
    it takes, and only one that has gone quiet is cut off. There is still an
    outermost bound, for a walk stuck in a loop that waits for ever.
    """
    from weave.app import run

    outcome = {"error": ""}
    state = {"beats": -1, "quiet_since": time.monotonic(), "started": time.monotonic()}

    def on_ready(engine, bridge, window):
        def go():
            try:
                walk(engine, bridge, window)
            except Exception as exc:                                # noqa: BLE001
                outcome["error"] = f"{type(exc).__name__}: {exc}"
            QTimer.singleShot(200, QCoreApplication.instance().quit)

        def look():
            now = time.monotonic()
            if beat() != state["beats"]:
                state["beats"] = beat()
                state["quiet_since"] = now
            quiet = now - state["quiet_since"]
            whole = now - state["started"]
            if quiet > quiet_s or whole > whole_s:
                outcome["error"] = (f"the walk stopped answering after {whole:.0f}s "
                                    f"({quiet:.0f}s quiet)")
                watchdog.stop()
                QCoreApplication.instance().quit()

        QTimer.singleShot(50, go)
        watchdog = QTimer()
        watchdog.setInterval(2000)
        watchdog.timeout.connect(look)
        watchdog.start()

    code = run([sys.argv[0]], on_ready=on_ready)
    if outcome["error"]:
        print(outcome["error"], file=sys.stderr)
        return 2
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="drive the real window offscreen")
    parser.add_argument("what", choices=["smoke"])
    parser.add_argument("--offline", action="store_true",
                        help="fail every request and subprocess at once")
    parser.add_argument("--screenshot", help="write a picture of the window here")
    parser.add_argument("--json", action="store_true", help="report as one JSON line")
    parser.add_argument("--no-seed", action="store_true", help="do not add sample videos")
    args = parser.parse_args()

    missing = [name for name in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")
               if not os.environ.get(name)]
    # A session always sets this one, and it is the session's own. Unset is
    # not the danger here; the danger is the real one, so it counts as missing
    # until it points somewhere else.
    runtime = os.environ.get("XDG_RUNTIME_DIR") or ""
    if not runtime or runtime.startswith("/run/user"):
        missing.append("XDG_RUNTIME_DIR")
    if missing:
        # This walk writes, and it presses things. It seeds channels and
        # videos, follows one, keeps a playlist and overwrites the music
        # shelves, and against a real collection all of that lands in it.
        # The runtime directory matters just as much: mpv's IPC socket lives
        # there, and a press that reaches a running mpv hands a test video to
        # the player somebody is watching. The test harness points every one
        # of these at a scratch copy, and running the walk by hand has to do
        # the same rather than be trusted to remember.
        print("refusing to walk the real collection and the real player: set "
              + ", ".join(missing) + " to a scratch directory", file=sys.stderr)
        return 2

    if args.offline:
        go_offline()
    if not args.no_seed:
        seed()

    smoke = Smoke(args.screenshot, loud=not args.json)
    code = boot(smoke.run)
    warnings = smoke.warnings.lines if smoke.warnings else ["the window never came up"]
    failed = [name for name, ok, _ in smoke.checks if not ok]
    report = {"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in smoke.checks],
              "failed": failed, "warnings": warnings, "exit": code}
    if args.json:
        print(json.dumps(report))
    else:
        # The answers were said as they were found, so only what could not be
        # said until the end is printed here.
        for line in warnings:
            print(f"warning: {line}")
        print(f"{len(smoke.checks) - len(failed)} of {len(smoke.checks)} checks passed, "
              f"{len(warnings)} QML warnings")
    return 1 if failed or warnings or code else 0


if __name__ == "__main__":
    raise SystemExit(main())
