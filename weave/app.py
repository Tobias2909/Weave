"""Application wiring.

Startup order matters. The window is shown against the cached database first
and the refresh starts behind it, so launching never waits on the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from . import config, paths
from .db import Database
from .player.mpv import Player
from .ui.bridge import Bridge
from .ui.feed_model import FeedModel
from .ui.theme import Theme

QML_DIR = Path(__file__).parent / "qml"


def _restore_geometry(window, db: Database) -> None:
    for name, setter in (("win_w", "setWidth"), ("win_h", "setHeight"),
                         ("win_x", "setX"), ("win_y", "setY")):
        raw = db.get_state(name)
        if raw and raw.lstrip("-").isdigit():
            getattr(window, setter)(int(raw))


def _save_geometry(window, db: Database) -> None:
    for name, prop in (("win_w", "width"), ("win_h", "height"),
                       ("win_x", "x"), ("win_y", "y")):
        db.set_state(name, str(int(getattr(window, prop)())))


def run(argv: list[str]) -> int:
    paths.ensure_dirs()
    cfg = config.load()
    db = Database(paths.DB_FILE)

    # Pinned on purpose. A system wide desktop style would need QtWidgets and
    # would fight the theme role map.
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(argv)
    app.setApplicationName("Weave")
    app.setOrganizationName("Weave")

    theme = Theme()
    model = FeedModel(db)
    player = Player(cfg)
    bridge = Bridge(db, cfg, model, player)

    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty("App", bridge)
    context.setContextProperty("Theme", theme)
    context.setContextProperty("feedModel", model)
    engine.addImportPath(str(QML_DIR))
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        print("failed to load the interface", file=sys.stderr)
        return 1

    window = engine.rootObjects()[0]
    _restore_geometry(window, db)

    player.start()

    feed_timer = QTimer()
    feed_timer.setInterval(cfg.feed_interval_s * 1000)
    feed_timer.timeout.connect(bridge.refresh)
    feed_timer.start()

    # Refresh once the window has actually painted.
    QTimer.singleShot(400, bridge.refresh)

    def shutdown() -> None:
        feed_timer.stop()
        _save_geometry(window, db)
        player.stop()

    app.aboutToQuit.connect(shutdown)
    return app.exec()
