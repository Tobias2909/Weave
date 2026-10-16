"""Who is live, as a QML list model.

The bar used to be handed a plain list, and every check made a new one: every
ninety seconds, and in practice always different, since a viewer count moves
in that time. A view handed a new list throws every card away and builds them
all again. MEASURED: every card, on every check, and a bar scrolled along to
find somebody was sent back to its start, 900 px to 0. A card being built
again also had nothing to show while its picture was asked for, which a frame
that changes every five minutes would have made a blink.

So rows are changed where they stand, the way the feed's grid has its rows
changed. A card lives as long as its stream does, a stream that starts is put
in, one that ends is taken out, and one overtaken in viewers is moved.
"""

from __future__ import annotations

from PySide6.QtCore import (QAbstractListModel, QByteArray, QModelIndex, Property, Qt,
                            Signal)

ROLES = (
    "id", "channelKey", "platform", "login", "name", "title", "game", "viewers",
    "viewersText", "thumbnail", "avatar", "isHidden",
)


class LiveModel(QAbstractListModel):
    countChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._hidden = 0
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

    def _get_count(self) -> int:
        return len(self._rows)

    def _get_seen(self) -> int:
        return sum(1 for row in self._rows if not row.get("isHidden"))

    def _get_hidden(self) -> int:
        return self._hidden

    # Every card drawn, the ones of them that are not hidden, and how many
    # hidden streams are live now, drawn or not. One signal for all three,
    # since one change of rows can move any of them.
    count = Property(int, _get_count, notify=countChanged)
    seenCount = Property(int, _get_seen, notify=countChanged)
    hiddenCount = Property(int, _get_hidden, notify=countChanged)

    def rows(self) -> list[dict]:
        return list(self._rows)

    def show(self, rows: list[dict], hidden: int = 0) -> None:
        """Make the rows these, in this order, by changing as little as there
        is to change. Rows are told apart by their id. `hidden` is how many
        hidden streams are live, whether or not they are among the rows."""
        before = (len(self._rows), self._get_seen(), self._hidden)
        self._hidden = hidden
        wanted = {row["id"] for row in rows}
        for index in reversed(range(len(self._rows))):
            if self._rows[index]["id"] not in wanted:
                self.beginRemoveRows(QModelIndex(), index, index)
                del self._rows[index]
                self.endRemoveRows()

        for index, row in enumerate(rows):
            if not (index < len(self._rows) and self._rows[index]["id"] == row["id"]):
                held = next((at for at in range(index + 1, len(self._rows))
                             if self._rows[at]["id"] == row["id"]), None)
                if held is None:
                    self.beginInsertRows(QModelIndex(), index, index)
                    self._rows.insert(index, row)
                    self.endInsertRows()
                    continue
                self.beginMoveRows(QModelIndex(), held, held, QModelIndex(), index)
                self._rows.insert(index, self._rows.pop(held))
                self.endMoveRows()
            if self._rows[index] != row:
                self._rows[index] = row
                self.dataChanged.emit(self.index(index), self.index(index))

        # Only reachable when the same id was handed over twice, which would
        # otherwise leave the copy hanging off the end.
        if len(self._rows) > len(rows):
            self.beginRemoveRows(QModelIndex(), len(rows), len(self._rows) - 1)
            del self._rows[len(rows):]
            self.endRemoveRows()

        if (len(self._rows), self._get_seen(), self._hidden) != before:
            self.countChanged.emit()
