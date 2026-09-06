"""Application wiring.

Startup order matters. The window is shown against the cached database first
and the refresh starts behind it, so launching never waits on the network.

run() takes an optional on_ready hook, called once with the engine, the bridge
and the window. It exists so an offscreen script can drive the real interface,
which is the only way to check things a clean startup never touches, such as
whether a menu closes when an entry is chosen.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from . import config, desktop, imagecache, mpris, paths
from .audio import AudioPlayer
from .db import Database
from .player.mpv import Player
from .sources import ytmusic
from .sources.progress import default_dir as default_watch_later
from .ui import navigation
from .ui.bridge import Bridge
from .ui.feed_model import FeedModel
from .ui.theme import Theme

QML_DIR = Path(__file__).parent / "qml"


def _app_icon() -> QIcon:
    """The window icon, built from the shipped pictures.

    Each size is added by hand rather than handing Qt the drawing, so the icon
    needs no SVG plugin and the small sizes are the ones that were rendered
    rather than ones Qt shrank.
    """
    icon = QIcon()
    for size in desktop.PNG_SIZES:
        picture = desktop.SHARE_DIR / f"weave-{size}.png"
        if picture.exists():
            icon.addFile(str(picture))
    return icon


def _effects_available() -> bool:
    """Whether a shader effect will actually draw.

    The software scene graph cannot run one, and reports nothing rather than
    failing, so a masked picture would simply be missing. The backend name is
    empty until the scene graph starts, which is after QML has to be loaded, so
    the environment is read first and the answer is corrected once the window
    exists.
    """
    forced = (os.environ.get("QT_QUICK_BACKEND")
              or os.environ.get("QMLSCENE_DEVICE") or "").lower()
    if forced in ("software", "softwarecontext"):
        return False
    return QQuickWindow.sceneGraphBackend() != "software"


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


def run(argv: list[str], on_ready: Callable | None = None) -> int:
    paths.ensure_dirs()
    cfg = config.load()
    db = Database(paths.DB_FILE)

    # Pinned on purpose. A system wide desktop style would need QtWidgets and
    # would fight the theme role map.
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(argv)
    app.setApplicationName("Weave")
    app.setOrganizationName("Weave")
    # Wayland has no window class to match on. The compositor identifies a
    # window by the desktop entry it names, and that is what a task bar reads
    # the icon and the title from, so this line is the icon on Wayland. The
    # window icon below is what X11 and the window list use instead.
    app.setDesktopFileName(desktop.ICON_NAME)
    app.setWindowIcon(_app_icon())

    configured = cfg.watch_later_dir
    watch_later = (default_watch_later() if configured == "auto"
                   else paths.expand(configured))

    # Parented to the application so Qt owns their lifetime. Without an owner
    # the interpreter can free a context property while the QML engine still
    # holds a pointer to it, which crashes during teardown rather than during
    # the run, so it is easy to miss.
    # A Google account can carry more than one YouTube identity, and requests
    # have to say which. Auto follows the browser.
    ytmusic.configure(cfg.music_identity)

    theme = Theme(db, parent=app)
    model = FeedModel(db, watch_later_dir=watch_later, parent=app)
    player = Player(cfg, parent=app)
    bridge = Bridge(db, cfg, model, player, parent=app)
    audio = AudioPlayer(cfg, db, parent=app)
    bridge.attach_theme(theme)
    bridge.attach_audio(audio)
    # The mouse back and forward buttons are not delivered to any one item,
    # so they are read at the application before anything else sees them.
    navigation.install(app, bridge)

    engine = QQmlApplicationEngine()
    # Installed before anything loads, so the very first images already go
    # through it.
    imagecache.install(engine, paths.IMAGE_CACHE, cfg.image_max_mb, cfg.image_days)
    context = engine.rootContext()
    context.setContextProperty("App", bridge)
    context.setContextProperty("Theme", theme)
    context.setContextProperty("feedModel", model)
    context.setContextProperty("Audio", audio)
    # Rounding a picture needs a shader, and the software scene graph cannot
    # run one. Told to QML so it can fall back to square pictures rather than
    # drawing nothing at all.
    context.setContextProperty("EffectsAvailable", _effects_available())
    engine.addImportPath(str(QML_DIR))
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        print("failed to load the interface", file=sys.stderr)
        return 1

    window = engine.rootObjects()[0]
    # The backend is known for certain now, so correct the guess. Re-setting a
    # context property re-evaluates the bindings that read it.
    context.setContextProperty("EffectsAvailable", _effects_available())
    _restore_geometry(window, db)
    # The media keys reach a player over MPRIS. Installed once the window
    # exists, so the panel can raise it. A machine with no session bus gets
    # no adapter and everything else still runs.
    mpris.install(audio, parent=app, on_raise=window.requestActivate)

    player.start()

    live_timer = QTimer()
    live_timer.setInterval(cfg.live_interval_s * 1000)
    live_timer.timeout.connect(bridge.refreshLive)
    live_timer.start()

    # A short tick taking whatever is due, rather than a long one taking
    # everything at once. Same volume, spread out, and a channel that just
    # became due waits a minute instead of a quarter of an hour.
    feed_timer = QTimer()
    feed_timer.setInterval(cfg.tick_interval_s * 1000)
    feed_timer.timeout.connect(bridge.poll)
    feed_timer.start()

    # Refresh once the window has actually painted.
    QTimer.singleShot(400, bridge.poll)
    # The bar says it is working from the first frame, rather than from
    # the moment the request goes out a breath later.
    bridge.expectLiveCheck()
    QTimer.singleShot(600, bridge.refreshLive)

    def shutdown() -> None:
        feed_timer.stop()
        live_timer.stop()
        _save_geometry(window, db)
        # Order matters. Background threads first, then the watcher, then the
        # engine, so nothing is destroyed while it is still running.
        bridge.shutdown()
        player.stop()

    app.aboutToQuit.connect(shutdown)
    if on_ready is not None:
        on_ready(engine, bridge, window)
    exit_code = app.exec()

    # Tear the engine down while the objects it referenced are still alive.
    # Letting both go out of scope together leaves the order to the
    # interpreter, and the wrong order segfaults after a clean exit.
    engine.clearComponentCache()
    del engine
    return exit_code
