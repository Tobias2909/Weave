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
from ..imagecache import qml_source
from ..sources import progress as mpv_progress

ROLES = (
    "key", "title", "channelKey", "channelTitle", "channelAvatar", "thumbnail", "ageText",
    "durationText", "viewsText", "likesText", "watched", "url", "isLive",
    "progress",
)


class FeedModel(QAbstractListModel):
    def __init__(self, db: Database, watch_later_dir=None, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._watch_later_dir = watch_later_dir
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

    def reload(self, hide_watched: bool = True, group_id: int | None = None,
               channel_key: str | None = None, box_id: int | None = None,
               query: str | None = None, watched_only: bool = False) -> None:
        self.show(self._db.feed(hide_watched=hide_watched, group_id=group_id,
                                channel_key=channel_key, box_id=box_id,
                                query=query, watched_only=watched_only))

    def show(self, rows) -> None:
        """Draw these rows, whatever produced them.

        Recommendations come from their own table rather than from the feed,
        and are shaped the same on purpose so one grid draws both.

        A list that begins with what is already shown is treated as an
        addition rather than as a new list. Resetting a model sends the view
        back to the top, and being thrown to the top is exactly what loading
        more at the bottom must not do.
        """
        built = [self._build(row) for row in rows]

        # Partial progress comes from mpv's own resume files rather than being
        # tracked here. Looked up in one pass for the rows actually on screen.
        positions = mpv_progress.positions_for([r["url"] for r in built],
                                               self._watch_later_dir)
        for item, row in zip(built, rows):
            seconds = positions.get(item["url"])
            duration = row["duration_s"]
            item["progress"] = (min(1.0, seconds / duration)
                                if seconds and duration and duration > 0 else 0.0)

        grew = (len(built) > len(self._rows) and self._rows
                and [row["key"] for row in built[:len(self._rows)]]
                == [row["key"] for row in self._rows])
        if grew:
            self.beginInsertRows(QModelIndex(), len(self._rows), len(built) - 1)
            self._rows = built
            self.endInsertRows()
            return
        self.beginResetModel()
        self._rows = built
        self.endResetModel()

    @staticmethod
    def _build(row) -> dict:
        return {
            "key": row["key"],
            "title": row["title"],
            "channelKey": row["channel_key"],
            "channelTitle": row["channel_title"] or "",
            "channelAvatar": qml_source(row["avatar_url"]),
            "thumbnail": qml_source(row["thumbnail_url"]),
            "ageText": fmt.age_text(row["published_at"]),
            "durationText": fmt.duration_text(row["duration_s"]),
            "viewsText": fmt.count_text(row["views"]),
            "likesText": fmt.count_text(row["likes"]),
            "watched": bool(row["watched"]),
            "url": ids.watch_url(row["platform"], row["ext_id"]),
            "isLive": row["live_status"] == "is_live",
            "progress": 0.0,
        }

    def row_at(self, row: int) -> dict | None:
        """The whole row, for the places that need more than its key."""
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def key_at(self, row: int) -> str | None:
        return self._rows[row]["key"] if 0 <= row < len(self._rows) else None

    def row_for_key(self, key: str) -> dict | None:
        return next((row for row in self._rows if row["key"] == key), None)
