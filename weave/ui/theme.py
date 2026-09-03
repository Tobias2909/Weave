"""Colors, as data.

Themes are a map of named roles rather than colors written into QML, because
several gradient themes are planned and retrofitting that later would mean
touching every QML file. The map is exposed as one notifying property, so
swapping it at runtime is all a hot reload needs to do.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal

# The role set the QML layer is allowed to use. Adding a role here and using it
# is fine. Using a raw color literal in QML is not.
DARK = {
    "name": "Weave Dark",
    "background": "#0f1115",
    "surface": "#171a21",
    "surfaceRaised": "#1f2430",
    "border": "#2a3040",
    "text": "#e7eaf0",
    "textMuted": "#98a0b3",
    "accent": "#7c5cff",
    "accentHover": "#9a80ff",
    "live": "#ff4d4f",
    # Platform marks. Used as a thin edge and a tinted border
    # rather than as a fill, so a card is never washed in them.
    "twitch": "#9146ff",
    "youtube": "#ff3d3d",
    "progress": "#ff3b30",
    "watchedDim": "#5a6072",
    "badgeBackground": "#000000b0",
    "badgeText": "#f2f4f8",
    "error": "#ffb020",
    "gradient": "",          # empty means a flat background
}


class Theme(QObject):
    changed = Signal()

    def __init__(self, colors: dict | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._colors = dict(colors or DARK)

    def _get(self) -> dict:
        return self._colors

    def apply(self, colors: dict) -> None:
        merged = dict(DARK)
        merged.update(colors)
        self._colors = merged
        self.changed.emit()

    colors = Property("QVariantMap", _get, notify=changed)
