"""The feed, as a QML list model.

Rows are plain dicts built once per reload rather than queried per role call,
because a GridView asks for every role of every visible delegate on each
repaint.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt

from .. import format as fmt
from .. import ids
from ..db import Database

ROLES = (
    "key", "title", "channelTitle", "thumbnail", "ageText",
    "durationText", "viewsText", "likesText", "watched", "url", "isLive",
)


class FeedModel(QAbstractListModel):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._rows: list[dict] = []
        self._role_ids = {
            Qt.ItemDataRole.UserRole + index: name for index, name in enumerate(ROLES)
        }

    def roleNames(self) -> dict[int, QByteArray]:
        return {rid: QByteArray(name.encode()) for rid, name in self._role_ids.items()}

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        name = self._role_ids.get(role)
        return self._rows[index.row()].get(name) if name else None

    def reload(self, hide_watched: bool = True, group_id: int | None = None) -> None:
        rows = self._db.feed(hide_watched=hide_watched, group_id=group_id)
        self.beginResetModel()
        self._rows = [self._build(row) for row in rows]
        self.endResetModel()

    @staticmethod
    def _build(row) -> dict:
        return {
            "key": row["key"],
            "title": row["title"],
            "channelTitle": row["channel_title"] or "",
            "thumbnail": row["thumbnail_url"] or "",
            "ageText": fmt.age_text(row["published_at"]),
            "durationText": fmt.duration_text(row["duration_s"]),
            "viewsText": fmt.count_text(row["views"]),
            "likesText": fmt.count_text(row["likes"]),
            "watched": bool(row["watched"]),
            "url": ids.watch_url(row["platform"], row["ext_id"]),
            "isLive": row["live_status"] == "is_live",
        }

    def key_at(self, row: int) -> str | None:
        return self._rows[row]["key"] if 0 <= row < len(self._rows) else None

    def row_for_key(self, key: str) -> dict | None:
        return next((row for row in self._rows if row["key"] == key), None)
