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
from PySide6.QtQml import QQmlProperty  # noqa: E402


# ---- helpers ---------------------------------------------------------------

def find(window, name: str) -> QObject | None:
    """A named object anywhere under the window. Give things an objectName."""
    if QQmlProperty.read(window, "objectName") == name:
        return window
    return window.findChild(QObject, name)


def read(obj, name: str):
    return QQmlProperty.read(obj, name)


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
    to act on."""
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
    db.close()


# ---- the walk ----------------------------------------------------------------

class Smoke:
    def __init__(self, shot: str | None) -> None:
        self.shot = shot
        self.checks: list[tuple[str, bool, str]] = []
        self.warnings: Warnings | None = None

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, bool(ok), detail))

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
        bridge.createGroup("Smoke group")
        settle(0.2)
        self.check("a new group appears", len(read(bridge, "groups")) == before + 1)

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

        # What the page says about the cache and the connections, which is
        # read rather than acted on, so an empty one is a binding that failed.
        for name in ("cacheSize", "cookieSource", "musicIdentity", "twitchState"):
            self.check(f"the page states the {name}", str(read(find(window, name), "text")) != "",
                       str(read(find(window, name), "text")))

        if self.shot:
            self.check("screenshot written", screenshot(window, self.shot), self.shot)


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
