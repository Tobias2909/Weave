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

from PySide6.QtCore import (QCoreApplication, QEventLoop, QMetaObject, QObject,  # noqa: E402
                            Qt, QTimer)
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


# Where the walk is, for anything that has to say so afterwards. A warning
# that only ever appears on the runner cannot be chased without it, and a
# round of pushing to find out which step raised one is a round wasted.
WHERE = {"step": "starting"}


def step(name: str) -> None:
    WHERE["step"] = name
    # To stderr, because that is where Qt prints the warnings this exists to
    # place. A warning the engine raises arrives through the driver and is
    # labelled below; one Qt prints past it, DelegateModel::cancel among them,
    # reaches the harness as a line of stderr and nothing else, so the only
    # way to say where it happened is to be on the same stream in order.
    print(f"[walk] {name}", file=sys.stderr, flush=True)


class Warnings:
    """Every warning the QML engine raises while the window is driven."""

    def __init__(self, engine) -> None:
        self.lines: list[str] = []
        engine.warnings.connect(self._on_warnings)

    def _on_warnings(self, errors) -> None:
        for error in errors:
            self.lines.append(f"{error.toString()}  [during {WHERE['step']}]")


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
        # The address of whoever made it, which every real shelf entry carries
        # now and which is what makes the name under a tile worth pressing.
        # Stored shelves without it are treated as stale and fetched again, so
        # a seed without it would leave the page empty.
        "items": [{"title": f"Track {i}", "subtitle": "Someone",
                   "videoId": f"smoketrack{i:02d}", "playlistId": f"RDsmoke{i:02d}",
                   "artistId": "UC" + "s" * 22,
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

    def now_playing(self, bridge, window) -> None:
        """The page about the song, and the block of words under the picture.

        What goes wrong here is invisible at rest, so it is asked rather than
        looked at: a face that is not there must take no room, and a long
        description must not be allowed to eat the picture.
        """
        # The queue the keys probe put up, rather than another one. What is
        # wanted here is the words about a song, and swapping the queue under
        # the views that draw it is what leaves a row half built.
        step("the Now playing page")
        audio = bridge._audio
        playing = audio._queue[0]["key"] if audio._queue else ""
        audio._facts[playing] = {
            "views": 1500, "likes": 90, "channel": "Somebody",
            "published_at": 1256453853,
            "description": ("A line about it, see https://example.test/a?b=1&c=2 "
                            "and a < b. " * 40),
        }
        audio.factsChanged.emit()
        settle(0.3)
        bridge.showNowPlaying()
        settle(0.8)
        self.check("the Now playing page opens",
                   read(bridge, "viewKind") == "nowplaying")

        facts = find(window, "nowPlayingFacts")
        self.check("the facts under the picture say what the resolve learned",
                   "1.5K views" in str(read(facts, "text")), str(read(facts, "text")))

        # The channel of this song is a stranger, so there is no face for it.
        # An empty picture that is still visible holds a round hole open, which
        # is what reading the wrong property did.
        face = find(window, "nowPlayingAvatar")
        self.check("no face is drawn for a channel nobody follows",
                   not read(face, "visible"),
                   f"source {read(face, 'source')}")

        said = find(window, "nowPlayingDescription")
        shut = read(said, "height")
        write(said, "open", True)
        settle(0.3)
        opened = read(said, "height")
        self.check("the description opens and is still bounded",
                   shut < opened < 200, f"{shut} then {opened}")
        write(said, "open", False)
        settle(0.2)

        # What a description is made of once Qt has it. The words arrive as
        # markup so that an address inside them can be pressed, which puts the
        # burden of escaping everything else on the way in. The label's
        # textFormat is not read here: PySide has no converter for
        # QQuickText::TextFormat and asking for it raises.
        markup = str(read(said, "text"))
        self.check("an address in the description is something to press",
                   '<a href="https://example.test/a?b=1&amp;c=2">' in markup,
                   markup[:120])
        self.check("and the words around it cannot become markup themselves",
                   "&lt;" in markup and "<b" not in markup, markup[:120])

        # ---- the picture filling the screen ------------------------------
        #
        # The same window made bigger, so what is asked here is that the page
        # takes the whole of it and that everything which is not the picture
        # gets out of the way. The surface itself is not asked about: a render
        # context aborts under the offscreen platform, so video is verified on
        # a real session and the shape of the page is verified here.
        slot = find(window, "nowPlayingSlot")
        toolbar_before = read(window, "cinema")
        self.check("the window is not filled to begin with", not toolbar_before,
                   str(toolbar_before))
        narrow = read(slot, "width")
        call(window, "enterCinema")
        settle(0.6)
        self.check("the page can fill the window", read(window, "cinema") is True,
                   str(read(window, "cinema")))
        # The width is the window's, whatever that is. Offscreen the screen is
        # smaller than the window Weave opens at, so filling it makes the
        # window NARROWER, and comparing against the width before says nothing.
        self.check("and takes the whole width, over the sidebar",
                   read(slot, "x") == 0
                   and abs(read(slot, "width") - read(window, "width")) < 1,
                   f"x {read(slot, 'x')} width {read(slot, 'width')} "
                   f"window {read(window, 'width')} was {narrow}")
        self.check("the toolbar gives its room back",
                   not read(find(window, "toolBar"), "visible"),
                   "toolbar still visible")
        self.check("the words under the picture are away",
                   not read(find(window, "nowPlayingWords"), "visible"),
                   "words still drawn")
        self.check("and the way back is offered",
                   read(find(window, "nowPlayingLeaveFullscreen"), "visible") is True,
                   str(read(find(window, "nowPlayingLeaveFullscreen"), "visible")))
        bar = find(window, "miniPlayer")
        self.check("the music bar stays over it",
                   read(bar, "visible") is True and read(bar, "opacity") == 1,
                   f"visible {read(bar, 'visible')} opacity {read(bar, 'opacity')}")

        # Stillness takes the bar away and movement brings it back, which is
        # the whole of what makes it a picture rather than a picture with a
        # bar across it. Faded and switched off rather than hidden, so it keeps
        # its height and cannot take a press meant for the picture behind it.
        write(window, "chromeAwake", False)
        settle(0.5)
        self.check("and goes when nothing moves",
                   read(bar, "opacity") == 0 and not read(bar, "enabled"),
                   f"awake {read(window, 'chromeAwake')} "
                   f"dimmed {read(bar, 'dimmed')} "
                   f"opacity {read(bar, 'opacity')} enabled {read(bar, 'enabled')}")
        self.check("without taking its room with it, so it does not jump back",
                   read(bar, "height") > 0, f"height {read(bar, 'height')}")
        call(window, "wakeChrome")
        settle(0.5)
        self.check("and comes back when something does",
                   read(bar, "opacity") == 1 and read(bar, "enabled") is True,
                   f"opacity {read(bar, 'opacity')} enabled {read(bar, 'enabled')}")

        call(window, "leaveCinema")
        settle(0.6)
        self.check("leaving puts everything back",
                   not read(window, "cinema") and read(slot, "x") > 0,
                   f"cinema {read(window, 'cinema')} x {read(slot, 'x')}")
        self.check("and the words with it",
                   read(find(window, "nowPlayingWords"), "visible") is True,
                   "words still away")

        bridge.closeNowPlaying()
        # The page has to be away before the queue goes, or the rows it is
        # still drawing are cancelled under it. And the view it lands on has
        # to be one that does not redraw itself when the queue changes, which
        # the music page does through the favourites.
        settle(0.8)
        bridge.selectGroup(-1)
        settle(0.6)
        audio._queue = []
        audio._order = []
        audio._at = -1
        audio._idle = True
        audio._facts.clear()
        audio.trackChanged.emit()
        audio.stateChanged.emit()
        settle(0.8)

    def layers(self, bridge, window) -> None:
        step("the layers")
        """What the Now playing page is drawn over, and what it is drawn under.

        Checked as numbers rather than by eye, because the fault it guards
        against is invisible at rest: the page only meets the view behind it
        while it is moving, and it landed in the right place every time.
        """
        slot = read(find(window, "nowPlayingSlot"), "z")
        for name in ("grid", "detailPanel", "musicView", "settingsView"):
            under = find(window, name)
            if under is None:
                continue
            self.check(f"the page is drawn over {name}", slot > read(under, "z"),
                       f"{slot} against {read(under, 'z')}")
        bar = read(find(window, "miniPlayer"), "z")
        self.check("and under the music bar, which is what it comes out from "
                   "behind", slot < bar, f"{slot} against {bar}")

    def space_bar(self, bridge, window) -> None:
        """The space bar stops and starts the music from anywhere, and is a
        space where something is being typed into.

        Driven with a real key rather than by calling the slot, because the
        thing that can be wrong here is which item the key reaches, and a call
        proves nothing about that.
        """
        from PySide6.QtTest import QTest

        step("the space bar")
        # Off the music page first. Putting a queue up and taking it down
        # tells the window the favourites have changed, which rebuilds the
        # shelves, and rebuilding a model while a row is still being built is
        # what leaves a delegate cancelled at an index that has gone.
        bridge.selectGroup(-1)
        settle(0.6)
        audio = bridge._audio
        audio._queue = [{"key": "yt:spacebaraaa", "title": "One", "url": "",
                         "artist": "Somebody", "thumbnail": artwork_file(),
                         "live": False, "duration_s": 213}]
        audio._order = [0]
        audio._at = 0
        audio._idle = False
        audio._paused = True
        audio.trackChanged.emit()
        audio.stateChanged.emit()
        # Long enough for every view that draws a queue to have finished
        # building its rows. Replacing a model while one is still being built
        # is what QML calls DelegateModel::cancel, and the runner is slow
        # enough to be caught at it where this machine never is.
        settle(0.8)

        call(window.contentItem(), "forceActiveFocus")
        settle(0.2)
        QTest.keyClick(window, Qt.Key_Space)
        settle(0.4)
        self.check("the space bar starts the music from anywhere",
                   bool(read(audio, "playing")))

        # Stopping is a fade rather than a cut, so it is not paused for the
        # half second the fade takes.
        QTest.keyClick(window, Qt.Key_Space)
        settle(1.2)
        self.check("and stops it again", not read(audio, "playing"))

        field = find(window, "searchField")
        call(field, "forceActiveFocus")
        settle(0.2)
        QTest.keyClick(window, Qt.Key_Space)
        settle(0.4)
        self.check("but in the search box it is a space",
                   not read(audio, "playing") and " " in str(read(field, "text")),
                   f"box {read(field, 'text')!r}, playing {read(audio, 'playing')}")
        write(field, "text", "")
        call(window.contentItem(), "forceActiveFocus")
        # The queue stays up for the page below, which is about the song it
        # holds. It is taken down once, there.
        settle(0.3)

    def music(self, bridge, window) -> None:
        """The music page: two rows a section, the page behind them, and a
        picture everywhere a track is drawn."""
        step("the music page")
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

    def a_stream_that_ended(self, bridge, window) -> None:
        """A card that says live about a broadcast which has finished.

        A card says live because something said so when it was last asked, and
        nothing asks again until the next round reaches that video. Pressing
        one is what finds out, so the answer has to reach the card as well as
        the person: the badge goes and the bottom of the window says why
        nothing is playing.

        The question itself is a request and the walk is offline, so the
        answer is handed over here rather than asked for. What is checked is
        what the answer does.
        """
        from weave import paths
        from weave.db import Database, VideoRow

        step("a stream that has ended")
        grid = find(window, "grid")
        gone = "yt:smokelive01"
        db = Database(paths.DB_FILE)
        db.upsert_videos([VideoRow("youtube", "smokelive01", "yt:UCsmokesmokesmokesmokes1",
                                   "A broadcast", published_at=1_700_000_600,
                                   live_status="is_live")])
        db.set_live_state(gone, 40, True)
        db.close()
        # Read again rather than selected again. The walk is already on All by
        # now, and selecting the view it is on is a no op, so nothing would be
        # read back and the new row would not be in the grid at all.
        bridge.reload()
        settle(0.5)
        call(grid, "forceLayout")
        settle(0.3)

        def badges():
            return [found for found in
                    (item_named(card, "streamBadge")
                     for card in visible_children(read(grid, "contentItem")))
                    if found is not None and read(found, "visible")]

        was_live = len(badges())
        row = bridge._model.row_for_key(gone) or {}
        self.check("the card says it is live", bool(row.get("isLive")),
                   f"live {row.get('isLive')}")

        bridge._set_notice("")
        # What the worker writes before it answers, done here because the
        # question it asks is a request and this walk is offline.
        db = Database(paths.DB_FILE)
        db.set_live_state(gone, None, False)
        db.close()
        bridge._pending_play = (gone, "https://example/watch", "A broadcast")
        bridge._on_stream_checked(gone, False, False)
        settle(0.6)
        call(grid, "forceLayout")
        settle(0.3)

        row = bridge._model.row_for_key(gone) or {}
        self.check("and after the answer it does not",
                   not row.get("isLive") and row.get("wasLive"),
                   f"live {row.get('isLive')} was {row.get('wasLive')}")
        self.check("the card wears the mark of a stream that has been",
                   len(badges()) == was_live + 1,
                   f"{len(badges())} against {was_live} before")
        self.check("and the bottom of the window says why nothing is playing",
                   "ended" in str(read(bridge, "notice")), str(read(bridge, "notice")))
        self.check("with nothing left saying it is on its way",
                   read(bridge, "startingKey") == "", str(read(bridge, "startingKey")))
        bridge._set_notice("")

        # Taken out again. Everything below counts the feed, and a step that
        # leaves a video behind quietly breaks whatever counts next.
        db = Database(paths.DB_FILE)
        with db.conn as conn:
            conn.execute("DELETE FROM videos WHERE key=?", (gone,))
        db.close()
        bridge.reload()
        settle(0.5)

        self.a_suggested_stream_that_ended(bridge, window)

    def a_suggested_stream_that_ended(self, bridge, window) -> None:
        """The same answer, on the suggestions page, where he found it wrong.

        A suggestion is usually a channel nobody follows, so the video is not
        in `videos` at all and correcting it there reached nothing the card
        reads. It is said on the cached row as well now.

        And the page must survive being told. Reading the rows again is a
        database read and not a request, and a list of the same keys reaches
        the grid as a change to the rows that differ rather than as a fresh
        model, so nothing is fetched, nothing is lost and the page does not
        move under the hand. That is what the last two checks are about.
        """
        from weave import paths
        from weave.db import Database

        step("a suggested stream that has ended")
        gone = "yt:smokelive02"
        db = Database(paths.DB_FILE)
        db.replace_cached(db.RECOMMENDED, [
            {"ext_id": "smokelive02", "title": "A suggested broadcast",
             "channel_name": "Somebody", "channel_ext_id": "UC" + "s" * 22,
             "live_status": "is_live"},
            *[{"ext_id": f"smokesugg{i:02d}", "title": f"Suggestion {i}",
               "channel_name": "Somebody", "channel_ext_id": "UC" + "s" * 22,
               "duration_s": 300} for i in range(30)],
        ])
        db.close()
        bridge.showRecommended()
        settle(0.7)
        grid = find(window, "grid")
        wait_until(lambda: read(grid, "count") > 30, 4.0)
        call(grid, "forceLayout")
        settle(0.3)

        before_count = read(grid, "count")
        write(grid, "contentY", 200.0)
        settle(0.4)
        before_where = read(grid, "contentY")
        row = bridge._model.row_for_key(gone) or {}
        self.check("a suggested stream says it is live", bool(row.get("isLive")),
                   f"live {row.get('isLive')}")

        db = Database(paths.DB_FILE)
        db.set_live_state(gone, None, False)
        db.close()
        bridge._set_notice("")
        bridge._pending_play = (gone, "https://example/watch", "A suggested broadcast")
        bridge._on_stream_checked(gone, False, False)
        settle(0.6)

        row = bridge._model.row_for_key(gone) or {}
        self.check("and after the answer the suggestion does not",
                   not row.get("isLive") and row.get("wasLive"),
                   f"live {row.get('isLive')} was {row.get('wasLive')}")
        self.check("the rest of the suggestions are all still there",
                   read(grid, "count") == before_count,
                   f"{read(grid, 'count')} against {before_count}")
        self.check("and the page has not moved under the hand",
                   abs(read(grid, "contentY") - before_where) < 1,
                   f"{before_where:.0f} to {read(grid, 'contentY'):.0f}")

        bridge._set_notice("")
        db = Database(paths.DB_FILE)
        db.replace_cached(db.RECOMMENDED, [])
        db.close()
        bridge.selectGroup(-1)
        settle(0.5)

    def hiding(self, bridge, window) -> None:
        """Taking a card out of sight, and getting it back.

        Hidden is not deleted. What is checked is that the card leaves the
        feed, that the settings page offers it back by name, and that bringing
        it back puts it where it was. The press itself is made through the
        bridge rather than through the menu, since the offscreen platform
        delivers no clicks, but the entry is read off the real menu so that an
        entry nobody can reach would still be caught.
        """
        from weave import paths
        from weave.db import Database

        step("hiding a video")
        bridge.selectGroup(-1)
        settle(0.5)
        grid = find(window, "grid")
        call(grid, "forceLayout")
        settle(0.2)
        before = read(grid, "count")

        menu = find(window, "videoMenu")
        menu.open()
        settle(0.3)
        labels = [text.strip() for text, _ in menu_entries(menu)]
        self.check("the video menu offers to hide it",
                   "Hide this video" in labels, ", ".join(labels))
        menu.close()
        settle(0.2)

        key = bridge._model.key_at(0)
        # A seeded video has no picture, and what is kept about a hidden one
        # is worth checking. An address that never answers is how pictures are
        # seeded everywhere in this walk: geometry is what is being measured.
        db = Database(paths.DB_FILE)
        with db.conn as conn:
            conn.execute("UPDATE videos SET thumbnail_url=? WHERE key=?",
                         ("https://pictures.invalid/hidden.jpg", key))
        db.close()
        bridge.reload()
        settle(0.4)
        bridge.hideVideo(key)
        settle(0.6)
        call(grid, "forceLayout")
        settle(0.2)
        self.check("hiding one takes it out of the feed",
                   read(grid, "count") == before - 1 and bridge._model.row_for_key(key) is None,
                   f"{read(grid, 'count')} against {before}")
        self.check("and the window says where it went",
                   "Settings" in str(read(bridge, "notice")), str(read(bridge, "notice")))

        bridge.showSettings()
        settle(0.7)
        said = find(window, "hiddenCount")
        listed = find(window, "hiddenVideos")
        self.check("the settings page counts what is hidden",
                   said is not None and "1 video is hidden" in str(read(said, "text")),
                   str(read(said, "text")) if said is not None else "no line")
        self.check("and lists it",
                   listed is not None and read(listed, "visible") is True
                   and read(listed, "count") == 1,
                   f"count {read(listed, 'count')}" if listed is not None else "no list")
        self.check("with the picture it had, stored plain",
                   str(read(bridge, "hiddenVideos")[0]["thumbnail"]).endswith(
                       "https://pictures.invalid/hidden.jpg"),
                   str(read(bridge, "hiddenVideos")[0]["thumbnail"]))

        bridge.unhideVideo(key)
        settle(0.5)
        self.check("bringing it back empties the list",
                   read(bridge, "hiddenCount") == 0,
                   f"{read(bridge, 'hiddenCount')} left")
        bridge.selectGroup(-1)
        settle(0.6)
        call(grid, "forceLayout")
        settle(0.2)
        self.check("and puts the card back where it was",
                   read(grid, "count") == before
                   and bridge._model.row_for_key(key) is not None,
                   f"{read(grid, 'count')} against {before}")
        db = Database(paths.DB_FILE)
        with db.conn as conn:
            conn.execute("UPDATE videos SET thumbnail_url=NULL WHERE key=?", (key,))
        db.close()
        bridge.reload()
        settle(0.3)
        bridge._set_notice("")

    def panel_scale(self, bridge, window) -> None:
        """The panel is dragged wider to read it, so what is in it grows.

        A wider panel that kept eleven pixel text only fitted more of the same
        squint. The narrowest it goes is the size it has always been, on
        purpose: that size was right for that width, and only the widening
        needed an answer.
        """
        step("the panel grows with the panel")
        was = read(bridge, "panelWidth")
        bridge.selectGroup(-1)
        settle(0.4)
        key = bridge._model.key_at(0)
        bridge.openDetail(key)
        # Settled first. Opening one asks for its comments, that ask fails
        # offline, and the failure empties the list, so comments put in before
        # it answered would be thrown away again.
        settle(0.8)
        # Comments of this shape rather than real ones, since what is measured
        # is how big they are drawn and the walk is offline.
        bridge._detail_comments = [{
            "author": "Somebody", "text": "A comment long enough to wrap over a line.",
            "when": "2 days ago", "likes": 12, "avatar": "", "pinned": False,
            "byUploader": False, "replies": [],
        }]
        bridge._detail_loading = False
        bridge.detailChanged.emit()
        settle(0.7)

        panel = find(window, "detailPanel")
        bridge.setPanelWidth(300)
        settle(0.5)
        title = find(window, "detailTitle")
        # A Repeater's delegates are not QObject children of anything, so the
        # comment has to be looked for in the visual tree.
        words = item_named(window.contentItem(), "commentText")
        self.check("the panel draws a title and a comment",
                   title is not None and words is not None,
                   f"title {'yes' if title else 'no'}, comment {'yes' if words else 'no'}, "
                   f"open {read(bridge, 'detailOpen')}, "
                   f"comments {len(read(bridge, 'detailComments'))}")
        if title is None or words is None:
            bridge.setPanelWidth(was)
            bridge.closeDetail()
            return
        narrow_title = float(read(title, "font.pixelSize"))
        narrow_words = float(read(words, "font.pixelSize"))
        self.check("at its narrowest it is the size it always was",
                   narrow_title == 15 and narrow_words == 12,
                   f"title {narrow_title:.0f} comment {narrow_words:.0f}")

        bridge.setPanelWidth(560)
        settle(0.6)
        wide_title = float(read(title, "font.pixelSize"))
        wide_words = float(read(words, "font.pixelSize"))
        self.check("and pulled wide everything in it is bigger",
                   wide_title > narrow_title and wide_words > narrow_words,
                   f"title {narrow_title:.0f} to {wide_title:.0f}, "
                   f"comment {narrow_words:.0f} to {wide_words:.0f}")
        self.check("but not a different application, a third bigger at most",
                   wide_words <= narrow_words * 1.36 and wide_title <= narrow_title * 1.36,
                   f"title x{wide_title / narrow_title:.2f} "
                   f"comment x{wide_words / narrow_words:.2f}")
        self.check("and the panel itself is as wide as it was asked to be",
                   float(read(panel, "width")) == 560, f"{read(panel, 'width'):.0f}")

        bridge.setPanelWidth(was)
        bridge.closeDetail()
        settle(0.4)

    def a_song_that_is_gone(self, bridge, window) -> None:
        """A song pressed and found to be no longer on YouTube.

        A playlist read from YouTube already arrives without its private and
        deleted entries, and the foot of the page says how many were left out.
        One that goes after the list was read cannot be caught that way, so it
        is caught when it is pressed, and the same thing has to happen: out of
        the list, counted with the rest, and said at the foot.

        The discovery itself is a resolve against YouTube and this walk is
        offline, so the answer is handed over here. What is checked is what the
        answer does.
        """
        from weave import paths
        from weave.db import Database

        step("a song that is gone")
        listed = Database(paths.DB_FILE)
        listed.replace_playlists([{"ext_id": "PL0000000000000000000009", "title": "Some songs"}])
        listed.replace_playlist_items("PL0000000000000000000009", [
            {"ext_id": "smokesong01", "title": "A song", "channel_name": "Smoke"},
            {"ext_id": "smokesong02", "title": "Another song", "channel_name": "Smoke"},
        ], skipped=1)
        listed.close()
        bridge.selectPlaylist("PL0000000000000000000009")
        settle(0.7)
        grid = find(window, "grid")
        call(grid, "forceLayout")
        settle(0.3)
        self.check("the playlist holds both of its songs", read(grid, "count") == 2,
                   f"count {read(grid, 'count')}")
        self.check("and says what the reading already left out",
                   "1 video" in str(read(bridge, "playlistSkippedText")),
                   str(read(bridge, "playlistSkippedText")))

        # Through the player, and through the half of it that finds nearly all
        # of them: looking ahead at what the queue will play next. Pressing a
        # song is the rare way to meet one that has gone; ordinarily it comes
        # round in the queue, and the answer arrives minutes early while the
        # song before it is still playing.
        audio = bridge._audio
        audio._queue = [
            {"key": "yt:smokesong02", "title": "Another song", "url": ""},
            {"key": "yt:smokesong01", "title": "A song", "url": ""},
        ]
        audio._order = [0, 1]
        audio._at = 0
        audio._idle = False
        audio.trackChanged.emit()
        audio._on_next_gone("yt:smokesong01")
        settle(0.7)
        self.check("one found gone while looking ahead leaves the queue",
                   [entry["key"] for entry in audio._queue] == ["yt:smokesong02"],
                   str([entry["key"] for entry in audio._queue]))
        self.check("and what was playing keeps playing",
                   audio.track.get("key") == "yt:smokesong02",
                   str(audio.track.get("key")))
        call(grid, "forceLayout")
        settle(0.3)
        self.check("and the list it was in",
                   read(grid, "count") == 1
                   and bridge._model.row_for_key("yt:smokesong01") is None,
                   f"count {read(grid, 'count')}")
        self.check("and it is counted with the rest that were left out",
                   "2 videos" in str(read(bridge, "playlistSkippedText")),
                   str(read(bridge, "playlistSkippedText")))
        # And says it about the right song. The one he is hearing is playing on
        # without trouble, so a notice that says "that one" points at the wrong
        # song and reads as a complaint about what is in his ears.
        self.check("and the window says what happened to it",
                   "deleted" in str(read(bridge, "notice")), str(read(bridge, "notice")))
        self.check("naming the one that went and not the one playing",
                   str(read(bridge, "notice")).startswith("The next one"),
                   str(read(bridge, "notice")))

        audio._queue = []
        audio._order = []
        audio._at = -1
        audio._idle = True
        audio.trackChanged.emit()
        audio.stateChanged.emit()
        bridge._set_notice("")
        bridge.selectGroup(-1)
        settle(0.5)

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

        # What the pointer says over the bar. The hover itself cannot be made
        # here, since the offscreen platform delivers no synthetic input, so
        # what is checked is that it is built, sits where it should, and reads
        # from the same rule as the line under the title.
        peek = find(window, "chapterPeek")
        self.check("the bar has something to say under the pointer",
                   peek is not None and float(read(peek, "height")) > 0)
        self.check("and it hangs above the bar rather than under it",
                   float(read(peek, "y")) + float(read(peek, "height")) <= 0,
                   f"y {read(peek, 'y'):.0f} height {read(peek, 'height'):.0f}")
        self.check("and is kept inside the window at the very start of a track",
                   float(read(peek, "x")) >= 4, f"x {read(peek, 'x'):.0f}")
        self.check("and names the song at the point it is over, from one rule",
                   str(read(peek, "song")) == str(bridge._audio.songAt(read(peek, "along"))),
                   f"{read(peek, 'song')!r} against {bridge._audio.songAt(read(peek, 'along'))!r}")

        # The wheel over the bar. The offscreen platform delivers no synthetic
        # input, so what the turn does is proved in the player's own tests and
        # what is checked here is that the bar has something to catch it.
        wheel = find(window, "musicScrubWheel")
        self.check("the bar catches the wheel as well as the pointer",
                   wheel is not None and read(wheel, "enabled") is True)

        # The list of songs, on the page about the song. Opened and closed
        # again here, because the queue is replaced further down this step and
        # replacing a model under a page that is drawing it is what leaves a
        # row half built.
        bridge.showNowPlaying()
        settle(0.7)
        button = find(window, "nowPlayingChaptersButton")
        chapter_list = find(window, "nowPlayingChapters")
        self.check("the page offers the chapters by name",
                   button is not None and str(read(button, "text")).startswith("Chapters"),
                   str(read(button, "text")) if button is not None else "no button")
        if button is not None and chapter_list is not None:
            call(button, "click")
            settle(0.4)
            self.check("and pressing it lists every one of them",
                       read(chapter_list, "visible") is True
                       and read(chapter_list, "count") == len(real),
                       f"visible {read(chapter_list, 'visible')} "
                       f"count {read(chapter_list, 'count')}")
            self.check("and says what pressing it again would do",
                       str(read(button, "text")).startswith("Hide the chapters"),
                       str(read(button, "text")))
            call(button, "click")
            settle(0.4)
            self.check("which puts the list away",
                       read(chapter_list, "visible") is False)
        bridge.closeNowPlaying()
        settle(0.6)

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
        self.check("and the pointer has no song to name over it",
                   str(read(peek, "song")) == "", str(read(peek, "song")))
        self.check("and its line says who it is by instead",
                   str(read(line, "text")) == "Somebody", str(read(line, "text")))

        # A broadcast has no length, and mpv says it has fourteen seconds
        # because that is the window it is holding. Believed, the bar filled
        # and reset every fourteen seconds and the word live went out the
        # moment the sound came in.
        audio._queue = [{"key": "source:1", "title": "A radio", "artist": "",
                         "url": "https://example/watch", "live": True}]
        audio._dur = 14.98
        audio._pos = 7.0
        audio.trackChanged.emit()
        audio.progressChanged.emit()
        settle(0.5)
        word = find(window, "musicLiveWord")
        self.check("a broadcast is not given a length by the window mpv holds",
                   read(audio, "isLive") is True and read(audio, "length") == 0,
                   f"isLive {read(audio, 'isLive')} length {read(audio, 'length')}")
        self.check("so it says live rather than counting to fourteen seconds",
                   read(word, "visible") is True)
        self.check("and has no bar to drag, since there is nowhere to drag to",
                   read(find(window, "musicScrubTrack"), "visible") is False)

        audio._queue[0]["live"] = False
        audio._dur = 254.0
        audio.trackChanged.emit()
        audio.progressChanged.emit()
        settle(0.5)
        self.check("an ordinary track keeps its length and its bar",
                   read(audio, "length") == 254 and read(word, "visible") is False
                   and read(find(window, "musicScrubTrack"), "visible") is True,
                   f"length {read(audio, 'length')}")

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

    def live_cards(self, bridge, window) -> None:
        """The streamer's face on a live card, and what a long title does.

        It used to sit in the row with the name, in a column that is centred
        and grows with what is in it, so a title needing two lines pushed the
        face to within two pixels of the top of the card, inside a corner eight
        pixels round and over the coloured edge. Nothing can move it now, which
        is what this measures, with the worst title the card can be given.
        """
        from weave import paths
        from weave.db import Database

        # An address rather than a file, because qml_source blanks anything
        # that is not http and an empty avatar draws nothing to measure. It
        # never answers, which is fine: what is being measured is where the
        # face sits, not what is in it.
        art = "https://pictures.invalid/live-face.jpg"
        db = Database(paths.DB_FILE)
        rows = []
        for index, title in enumerate(
                ["Short one",
                 "A much longer stream title that will certainly wrap onto two lines"]):
            login = f"streamer{index}"
            db.add_channel(f"twitch:{login}", "twitch", login, f"Streamer {index}", art)
            rows.append({"channel_key": f"twitch:{login}", "login": login,
                         "display_name": f"Streamer {index}", "title": title,
                         "game": "A game", "viewers": 900 + index,
                         "started_at": 1, "thumbnail_url": art})
        db.replace_live("twitch", rows)
        db.close()
        # The bar shows only once a check has answered and only while it is
        # unrolled. Neither is true by itself in a walk that never asks
        # anything, so both are said here rather than waited for.
        bridge._live_ready = True
        bridge._live_collapsed = False
        bridge.liveChanged.emit()
        settle(1.0)
        self.check("the live bar unrolls for them",
                   float(read(find(window, "liveBar"), "height")) > 100,
                   f"{read(find(window, 'liveBar'), 'height'):.0f} px tall")

        root = window.contentItem()
        faces = [one for one in items_named_like(root, "streamAvatarRing")
                 if read(one, "visible")]
        self.check("a live card carries the streamer's face", len(faces) == 2,
                   f"{len(faces)} of them")
        self.check("and it is worth seeing rather than a dot",
                   all(float(read(one, "width")) >= 26 for one in faces),
                   ", ".join(f"{read(one, 'width'):.0f}" for one in faces))

        worst = 0.0
        card_height = 0.0
        radius = 0.0
        for one in faces:
            card = one.parent().parent()          # the ring's picture, then the card
            top = one.mapToItem(card, 0, 0).y()
            bottom = top + float(read(one, "height"))
            card_height = float(read(card, "height"))
            radius = float(read(card, "radius"))
            worst = max(worst, radius - top, bottom - (card_height - radius))
        self.check("and no title can push it onto the card's edge",
                   worst <= 0.5,
                   f"{worst:.1f} px into a {radius:.0f} px corner of a "
                   f"{card_height:.0f} px card")

        db = Database(paths.DB_FILE)
        db.replace_live("twitch", [])
        db.close()
        bridge._live_ready = False
        bridge.liveChanged.emit()
        settle(0.4)

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

    def sidebar_order(self, bridge, window, box_id) -> None:
        """Where the sections sit, and that the wheel agrees with the eye.

        The boxes are drawn above Yours, which is the order he asked for, and
        the wheel walks positions rather than names, so the list behind it has
        to be moved with the sidebar or the wheel steps past a section that is
        plainly there.
        """
        boxes = find(window, "boxesHeading")
        yours = find(window, "yoursHeading")
        self.check("the sidebar has both headings",
                   boxes is not None and yours is not None)
        if boxes is None or yours is None:
            return
        self.check("the boxes are drawn above Yours",
                   read(boxes, "y") < read(yours, "y"),
                   f"boxes {read(boxes, 'y'):.0f}, yours {read(yours, 'y'):.0f}")

        # One step down from All, which is the first entry either way. The box
        # made for this walk is the only one there is, so landing anywhere else
        # means the wheel is walking the old order.
        bridge.selectGroup(-1)
        settle(0.3)
        bridge.stepSelection(1)
        settle(0.3)
        self.check("and the wheel reaches a box before Yours",
                   read(bridge, "viewKind") == "box" and read(bridge, "viewId") == box_id,
                   f"{read(bridge, 'viewKind')} {read(bridge, 'viewId')}")
        bridge.selectGroup(-1)
        settle(0.3)

    def history_button(self, bridge, window) -> None:
        """Reading the history again, on the page rather than in the bar."""
        bridge.showHistory()
        settle(0.4)
        again = find(window, "historyRefresh")
        self.check("the history carries its own read it again button",
                   again is not None and read(again, "visible") is True)
        if again is not None:
            self.check("which says which half it would read",
                       str(read(again, "text")) == "Read it again",
                       str(read(again, "text")))
            bridge.showMusicInHistory(True)
            settle(0.4)
            self.check("and says the other thing over the listening",
                       str(read(again, "text")) == "Read the listening again",
                       str(read(again, "text")))
            bridge.showMusicInHistory(False)
            settle(0.3)
        action = find(window, "viewAction")
        self.check("and the bar no longer offers it",
                   action is not None and not read(action, "visible"),
                   str(read(action, "text")) if action is not None else "no button")
        bridge.selectGroup(-1)
        settle(0.3)

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
        step("the boot")
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
            step(f"opening the {name} view")
            getattr(bridge, slot)()
            settle(0.3)
            self.check(f"{name} view opens", read(bridge, "viewKind") == name)
        step("back to All after the views")
        bridge.selectGroup(-1)
        settle(0.3)

        self.music(bridge, window)
        self.space_bar(bridge, window)
        self.now_playing(bridge, window)
        self.layers(bridge, window)

        # A box, then the video menu, whose box entries sit between the
        # separator and the last entry however many entries come above.
        step("the boxes and the video menu")
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

        step("the sidebar order and the history's own button")
        self.sidebar_order(bridge, window, box_id)
        self.history_button(bridge, window)

        bridge.deleteBox(box_id)

        # A group made and found in the sidebar list.
        step("the groups")
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
        for name in ("cacheSize", "cookieSource", "musicIdentity", "twitchState",
                     "videosKept"):
            self.check(f"the page states the {name}", str(read(find(window, name), "text")) != "",
                       str(read(find(window, name), "text")))

        self.starting(bridge, window)
        self.panel_scale(bridge, window)
        self.updates(bridge, window)
        self.announcements(bridge, window)
        self.members(bridge, window)
        self.chapters(bridge, window)
        self.suggestions(bridge, window)
        self.strangers(bridge, window)
        self.channel_playlists(bridge, window)
        self.bar(bridge, window)
        self.live_cards(bridge, window)
        self.following(bridge, window)
        self.boxes(bridge, window)
        self.wizard(bridge, window)
        self.scrolling(bridge, window)
        # Last, these three, because each puts a row into the feed or takes one
        # out and every step above that counts the feed would count it. The
        # scrolling step is the strict one: it measures where the grid sits
        # after a view change, and a model that was rebuilt rather than reset
        # earlier in the walk leaves it somewhere else.
        self.hiding(bridge, window)
        self.a_stream_that_ended(bridge, window)
        self.a_song_that_is_gone(bridge, window)

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
