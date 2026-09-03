"""The single object QML talks to.

Keeping one bridge rather than exposing the database and the poller directly
means QML never sees a blocking call, and every action the UI can trigger is
listed in one place.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..config import Config
from ..db import Database
from ..player.mpv import Player
from ..poller import ChannelAdder, FeedPoller
from .feed_model import FeedModel


class Bridge(QObject):
    statusChanged = Signal()
    busyChanged = Signal()
    hideWatchedChanged = Signal()
    problemsChanged = Signal()
    emptyHintChanged = Signal()

    def __init__(self, db: Database, cfg: Config, model: FeedModel,
                 player: Player, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._model = model
        self._player = player
        self._poller: FeedPoller | None = None
        self._adder: ChannelAdder | None = None
        self._busy = False
        self._problems: list[str] = []

        self._hide_watched = self._db.get_state("hide_watched", "1") == "1"
        self._status = ""

        self._player.watched.connect(self._on_watched)
        self._player.failed.connect(self._on_player_failed)

        if self._player.error:
            self._problems.append(self._player.error)

        self.reload()
        self._set_status(self._idle_status())

    # ---- properties ------------------------------------------------------

    def _get_status(self) -> str:
        return self._status

    def _get_busy(self) -> bool:
        return self._busy

    def _get_hide_watched(self) -> bool:
        return self._hide_watched

    def _get_problems(self) -> list:
        return list(self._problems)

    def _get_empty_hint(self) -> str:
        """What to say when the grid is empty. There are three different
        reasons for that and they need three different answers."""
        counts = self._db.counts()
        if not counts["channels"]:
            return "Nothing here yet.\nAdd a channel above, then press Refresh."
        youtube = len(self._db.channels(platform="youtube"))
        if not youtube:
            return ("Only Twitch channels are tracked so far.\n"
                    "Twitch appears in the live bar, which is not built yet, so it "
                    "produces no rows here.\nAdd a YouTube channel to fill the feed.")
        if not counts["videos"]:
            return "No videos stored yet.\nPress Refresh to fetch them."
        return "Everything here is watched.\nTurn off Hide watched to see it again."

    status = Property(str, _get_status, notify=statusChanged)
    emptyHint = Property(str, _get_empty_hint, notify=emptyHintChanged)
    busy = Property(bool, _get_busy, notify=busyChanged)
    hideWatched = Property(bool, _get_hide_watched, notify=hideWatchedChanged)
    problems = Property("QVariantList", _get_problems, notify=problemsChanged)

    def _set_status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    def _set_busy(self, value: bool) -> None:
        if value != self._busy:
            self._busy = value
            self.busyChanged.emit()

    def _idle_status(self) -> str:
        counts = self._db.counts()
        return (f"{counts['channels']} channels, {counts['videos']} videos, "
                f"{counts['watched']} watched")

    # ---- actions ---------------------------------------------------------

    @Slot()
    def reload(self) -> None:
        self._model.reload(hide_watched=self._hide_watched)
        self.emptyHintChanged.emit()

    @Slot()
    def refresh(self) -> None:
        """Manual refresh. Also the button that resets the poll timers."""
        if self._busy:
            return
        self._problems = [p for p in self._problems if not p.startswith("feed ")]
        self.problemsChanged.emit()
        self._set_busy(True)
        self._set_status("refreshing")
        self._poller = FeedPoller(self._db, self._cfg, self)
        self._poller.progress.connect(
            lambda done, total: self._set_status(f"refreshing {done} of {total}"))
        self._poller.failure.connect(self._on_poll_failure)
        self._poller.finished_poll.connect(self._on_poll_finished)
        self._poller.start()

    @Slot(str)
    def play(self, key: str) -> None:
        row = self._model.row_for_key(key)
        if not row:
            return
        login = key.split(":", 1)[1] if key.startswith("twitch:") else None
        if self._player.play(row["url"], twitch_login=login):
            self._set_status(f"playing {row['title']}")

    @Slot(str)
    def markWatched(self, key: str) -> None:
        self._db.set_watched(key, None, "manual")
        self.reload()

    @Slot(str)
    def markUnwatched(self, key: str) -> None:
        self._db.clear_watched(key)
        self.reload()

    @Slot(bool)
    def setHideWatched(self, value: bool) -> None:
        if value == self._hide_watched:
            return
        self._hide_watched = value
        self._db.set_state("hide_watched", "1" if value else "0")
        self.hideWatchedChanged.emit()
        self.reload()

    @Slot(str, result=bool)
    def addChannel(self, text: str) -> bool:
        """Accepts a channel id, an @handle, a legacy channel URL or a Twitch
        link. Returns whether the reference was understood at all. Resolving a
        handle then happens in the background.
        """
        from .. import ids

        ref = ids.parse_channel_ref(text)
        if not ref:
            self._set_status("could not read that as a channel")
            return False
        if self._adder is not None and self._adder.isRunning():
            self._set_status("still adding the previous channel")
            return False

        self._set_status(f"resolving {ref.value}")
        self._adder = ChannelAdder(ref, self._cfg, self)
        self._adder.added.connect(self._on_channel_added)
        self._adder.failed.connect(self._on_channel_failed)
        self._adder.start()
        return True

    # ---- reactions -------------------------------------------------------

    def _on_channel_added(self, key: str, platform: str, ext_id: str, title: str) -> None:
        self._db.add_channel(key, platform, ext_id, title or None)
        label = title or ext_id
        if platform == "twitch":
            # Say this plainly. A Twitch channel adding no rows to the feed
            # looks broken otherwise.
            self._set_status(f"added {label}, which will show in the live bar rather than the feed")
            self.reload()
        else:
            self._set_status(f"added {label}, fetching videos")
            self.refresh()

    def _on_channel_failed(self, message: str) -> None:
        self._set_status(f"could not add that channel, {message}")

    def _on_watched(self, key: str, progress: float) -> None:
        self._db.set_watched(key, progress, "mpv")
        self.reload()
        self._set_status(f"marked watched at {int(progress * 100)} percent")

    def _on_player_failed(self, message: str) -> None:
        self._problems.append(message)
        self.problemsChanged.emit()
        self._set_status(message)

    def _on_poll_failure(self, key: str, message: str) -> None:
        self._problems.append(f"feed {key}: {message}")
        self.problemsChanged.emit()

    def _on_poll_finished(self, channels: int, touched: int, failures: int) -> None:
        self._set_busy(False)
        self.reload()
        suffix = f", {failures} failed" if failures else ""
        self._set_status(f"{channels} channels checked, {touched} rows updated{suffix}")
        self._poller = None
