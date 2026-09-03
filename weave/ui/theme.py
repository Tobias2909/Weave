"""The live theme.

Colours reach QML as one notifying map, so switching a theme is a single
property change rather than a rebuild, and no colour is ever written into a QML
file. See weave/themes.py for the file format.

Files are watched, so saving a theme in an editor repaints the running window.
That matters while a palette is being worked on, which is the only time anyone
edits one.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, Signal, Slot

from .. import themes
from ..db import Database


class Theme(QObject):
    changed = Signal()
    listChanged = Signal()

    def __init__(self, db: Database | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        name = db.get_state("theme", themes.DEFAULT_NAME) if db else themes.DEFAULT_NAME
        self._loaded = themes.find(name or themes.DEFAULT_NAME)

        themes.user_dir().mkdir(parents=True, exist_ok=True)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_disk_changed)
        self._watcher.fileChanged.connect(self._on_disk_changed)
        # An editor usually replaces a file rather than writing into it, which
        # drops the watch, so the list is rebuilt after every event.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(150)
        self._settle.timeout.connect(self.reload)
        self._rewatch()

    # ---- what QML reads --------------------------------------------------

    def _get_colors(self) -> dict:
        return dict(self._loaded.colors)

    def _get_gradient(self) -> dict:
        return dict(self._loaded.gradient) if self._loaded.gradient else {}

    def _get_names(self) -> list:
        return [theme.name for theme in themes.available()]

    def _get_current(self) -> str:
        return self._loaded.name

    def _get_washed(self) -> bool:
        """Whether a gradient is in play. The panels go translucent when there
        is one, otherwise they would cover the very corner the light comes
        from and the wash would never be seen."""
        return self._loaded.gradient is not None

    colors = Property("QVariantMap", _get_colors, notify=changed)
    gradient = Property("QVariantMap", _get_gradient, notify=changed)
    names = Property("QVariantList", _get_names, notify=listChanged)
    current = Property(str, _get_current, notify=changed)
    washed = Property(bool, _get_washed, notify=changed)

    # ---- actions ---------------------------------------------------------

    @Slot(str)
    def select(self, name: str) -> None:
        if not name or name == self._loaded.name:
            return
        self._loaded = themes.find(name)
        if self._db is not None:
            self._db.set_state("theme", self._loaded.name)
        self._rewatch()
        self.changed.emit()

    @Slot()
    def reload(self) -> None:
        """Re-read from disk and repaint. Cheap, so it runs on any change in
        the themes directory rather than working out what changed."""
        self._loaded = themes.find(self._loaded.name)
        self._rewatch()
        self.changed.emit()
        self.listChanged.emit()

    @property
    def problems(self) -> list[str]:
        return list(self._loaded.problems)

    def _rewatch(self) -> None:
        watched = set(self._watcher.directories()) | set(self._watcher.files())
        wanted: set[str] = {str(themes.user_dir())}
        for theme in themes.available():
            if theme.source is not None:
                wanted.add(str(theme.source))
        for path in wanted - watched:
            self._watcher.addPath(path)
        for path in watched - wanted:
            if not Path(path).exists():
                self._watcher.removePath(path)

    def _on_disk_changed(self, _path: str) -> None:
        self._settle.start()
