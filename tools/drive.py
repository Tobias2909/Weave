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


def settle(seconds: float) -> None:
    """Let the event loop run for a while."""
    end = time.monotonic() + seconds
    app = QCoreApplication.instance()
    while time.monotonic() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.005)


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
    def __init__(self, shot: str | None) -> None:
        self.shot = shot
        self.checks: list[tuple[str, bool, str]] = []
        self.warnings: Warnings | None = None

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, bool(ok), detail))

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

    def run(self, engine, bridge, window) -> None:
        self.warnings = Warnings(engine)
        settle(1.2)
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

        menu = find(window, "groupMenu")
        write(menu, "groupId", group_id)
        write(menu, "groupName", "Smoke group")
        menu.open()
        settle(0.3)
        labels = [text.strip() for text, _ in menu_entries(menu)]
        self.check("the group menu leads with managing it",
                   labels[:1] == ["Manage the group"], ", ".join(labels))
        menu.close()
        settle(0.2)

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

        # What the page says about the cache and the connections, which is
        # read rather than acted on, so an empty one is a binding that failed.
        for name in ("cacheSize", "cookieSource", "musicIdentity", "twitchState"):
            self.check(f"the page states the {name}", str(read(find(window, name), "text")) != "",
                       str(read(find(window, name), "text")))

        if self.shot:
            self.check("screenshot written", screenshot(window, self.shot), self.shot)


def shot_beside(path: str, suffix: str) -> str:
    """A second picture next to the one that was asked for."""
    where = Path(path)
    return str(where.with_name(f"{where.stem}-{suffix}{where.suffix}"))


def boot(walk, hold_s: float = 6.0) -> int:
    """Start the real application, hand the window to `walk`, then quit."""
    from weave.app import run

    outcome = {"error": ""}

    def on_ready(engine, bridge, window):
        def go():
            try:
                walk(engine, bridge, window)
            except Exception as exc:                                # noqa: BLE001
                outcome["error"] = f"{type(exc).__name__}: {exc}"
            QTimer.singleShot(200, QCoreApplication.instance().quit)

        QTimer.singleShot(50, go)
        # A stuck walk must not hang forever.
        QTimer.singleShot(int(hold_s * 1000 * 5), QCoreApplication.instance().quit)

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

    if args.offline:
        go_offline()
    if not args.no_seed:
        seed()

    smoke = Smoke(args.screenshot)
    code = boot(smoke.run)
    warnings = smoke.warnings.lines if smoke.warnings else ["the window never came up"]
    failed = [name for name, ok, _ in smoke.checks if not ok]
    report = {"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in smoke.checks],
              "failed": failed, "warnings": warnings, "exit": code}
    if args.json:
        print(json.dumps(report))
    else:
        for name, ok, detail in smoke.checks:
            print(f"[{'ok' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
        for line in warnings:
            print(f"warning: {line}")
        print(f"{len(smoke.checks) - len(failed)} of {len(smoke.checks)} checks passed, "
              f"{len(warnings)} QML warnings")
    return 1 if failed or warnings or code else 0


if __name__ == "__main__":
    raise SystemExit(main())
