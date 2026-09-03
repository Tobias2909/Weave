"""The single object QML talks to.

Keeping one bridge rather than exposing the database and the poller directly
means QML never makes a blocking call, and every action the interface can
trigger is listed in one place.

The current view is one piece of state rather than several independent filters,
because all, a group, a box and a channel page are mutually exclusive and
letting them be set separately would allow combinations with no meaning.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from .. import format as fmt
from .. import ids
from ..config import Config
from ..db import Database
from ..player.mpv import Player
from ..poller import ChannelAdder, ChannelDetailsFetcher, FeedPoller, SubsImporter
from .feed_model import FeedModel

ALL = "all"
GROUP = "group"
BOX = "box"
CHANNEL = "channel"


class Bridge(QObject):
    statusChanged = Signal()
    busyChanged = Signal()
    hideWatchedChanged = Signal()
    problemsChanged = Signal()
    emptyHintChanged = Signal()
    groupsChanged = Signal()
    boxesChanged = Signal()
    viewChanged = Signal()

    def __init__(self, db: Database, cfg: Config, model: FeedModel,
                 player: Player, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._model = model
        self._player = player

        self._poller: FeedPoller | None = None
        self._adder: ChannelAdder | None = None
        self._importer: SubsImporter | None = None
        self._details: ChannelDetailsFetcher | None = None

        self._busy = False
        self._problems: list[str] = []
        self._status = ""

        self._view_kind = ALL
        self._view_id = -1
        self._view_channel = ""

        self._hide_watched = self._db.get_state("hide_watched", "1") == "1"

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

    def _get_groups(self) -> list:
        """All first, then the configured groups. Shipped as one list so QML
        has no special case for the All row."""
        rows = [{"id": -1, "name": "All", "members": len(self._db.channels()),
                 "unwatched": self._db.unwatched_total()}]
        rows.extend(self._db.groups())
        return rows

    def _get_boxes(self) -> list:
        return self._db.boxes()

    def _get_view_kind(self) -> str:
        return self._view_kind

    def _get_view_id(self) -> int:
        return self._view_id

    def _get_channel_info(self) -> dict:
        if self._view_kind != CHANNEL:
            return {}
        found = self._db.channel(self._view_channel) or {}
        return {
            "key": found.get("key", ""),
            "title": found.get("title") or found.get("ext_id", ""),
            "avatar": found.get("avatar_url") or "",
            "banner": found.get("banner_url") or "",
            "followers": found.get("follower_count") or 0,
            "followersText": fmt.count_text(found.get("follower_count")),
            "videos": found.get("video_count") or 0,
            "platform": found.get("platform", "youtube"),
        }

    def _get_empty_hint(self) -> str:
        """What to say when the grid is empty. There are several different
        reasons for that and they need different answers."""
        if self._view_kind == BOX:
            return ("This box is empty.\nRight click any video and put it in here.")
        if self._view_kind == CHANNEL:
            return "No videos stored for this channel yet.\nPress Refresh."
        counts = self._db.counts()
        if not counts["channels"]:
            return "Nothing here yet.\nAdd a channel above, then press Refresh."
        if self._view_kind == GROUP:
            return ("This group has nothing to show.\n"
                    "Put channels in it with the group subcommands.")
        if not len(self._db.channels(platform="youtube")):
            return ("Only Twitch channels are tracked so far.\n"
                    "Twitch appears in the live bar, which is not built yet, so it "
                    "produces no rows here.\nAdd a YouTube channel to fill the feed.")
        if not counts["videos"]:
            return "No videos stored yet.\nPress Refresh to fetch them."
        return "Everything here is watched.\nTurn off Hide watched to see it again."

    status = Property(str, _get_status, notify=statusChanged)
    busy = Property(bool, _get_busy, notify=busyChanged)
    hideWatched = Property(bool, _get_hide_watched, notify=hideWatchedChanged)
    problems = Property("QVariantList", _get_problems, notify=problemsChanged)
    emptyHint = Property(str, _get_empty_hint, notify=emptyHintChanged)
    groups = Property("QVariantList", _get_groups, notify=groupsChanged)
    boxes = Property("QVariantList", _get_boxes, notify=boxesChanged)
    viewKind = Property(str, _get_view_kind, notify=viewChanged)
    viewId = Property(int, _get_view_id, notify=viewChanged)
    channelInfo = Property("QVariantMap", _get_channel_info, notify=viewChanged)

    def _get_scroll_rows(self) -> float:
        return self._cfg.scroll_rows_per_notch

    scrollRowsPerNotch = Property(float, _get_scroll_rows, constant=True)

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

    # ---- the current view ------------------------------------------------

    @Slot()
    def reload(self) -> None:
        # A channel page and a box both ignore the hide watched toggle. The
        # channel page is meant to show everything that channel has, and a box
        # was hand picked, so hiding half of it would be surprising.
        honour_toggle = self._view_kind in (ALL, GROUP)
        self._model.reload(
            hide_watched=self._hide_watched and honour_toggle,
            group_id=self._view_id if self._view_kind == GROUP else None,
            box_id=self._view_id if self._view_kind == BOX else None,
            channel_key=self._view_channel if self._view_kind == CHANNEL else None,
        )
        self.emptyHintChanged.emit()
        self.groupsChanged.emit()
        self.boxesChanged.emit()

    def _set_view(self, kind: str, view_id: int = -1, channel_key: str = "") -> None:
        if (kind, view_id, channel_key) == (self._view_kind, self._view_id, self._view_channel):
            return
        self._view_kind = kind
        self._view_id = view_id
        self._view_channel = channel_key
        self.viewChanged.emit()
        self.reload()

    def _selectable(self) -> list[tuple[str, int]]:
        """Everything the sidebar offers, in the order it is drawn. All first,
        then groups, then boxes. A channel page is not in here because it is
        not reachable from the sidebar."""
        entries: list[tuple[str, int]] = [(ALL, -1)]
        entries.extend((GROUP, int(row["id"])) for row in self._db.groups())
        entries.extend((BOX, int(row["id"])) for row in self._db.boxes())
        return entries

    @Slot(int)
    def stepSelection(self, delta: int) -> None:
        """Move up or down the sidebar. From a channel page this lands on All
        going one way and on the last entry going the other, since a channel
        page has no place in the list."""
        entries = self._selectable()
        if not entries:
            return
        current = (self._view_kind, self._view_id)
        try:
            index = entries.index(current)
        except ValueError:
            index = 0 if delta > 0 else len(entries) - 1
        else:
            index = max(0, min(len(entries) - 1, index + (1 if delta > 0 else -1)))
        kind, view_id = entries[index]
        self._set_view(kind, view_id)

    @Slot(int)
    def selectGroup(self, group_id: int) -> None:
        self._set_view(ALL if group_id < 0 else GROUP, group_id)

    @Slot(int)
    def selectBox(self, box_id: int) -> None:
        self._set_view(BOX, box_id)

    @Slot(str)
    def openChannel(self, channel_key: str) -> None:
        if not channel_key:
            return
        self._set_view(CHANNEL, -1, channel_key)
        found = self._db.channel(channel_key)
        if found and found["platform"] == "youtube" and \
                self._db.channel_details_are_stale(channel_key):
            self._fetch_channel_details(channel_key, found["ext_id"])

    def _fetch_channel_details(self, channel_key: str, ext_id: str) -> None:
        if self._details is not None and self._details.isRunning():
            return
        self._details = ChannelDetailsFetcher(self._db, self._cfg, channel_key, ext_id, self)
        self._details.fetched.connect(lambda _key: self.viewChanged.emit())
        self._details.failed.connect(
            lambda _key, message: self._set_status(f"could not load the channel, {message}"))
        self._details.start()

    # ---- boxes -----------------------------------------------------------

    @Slot(str, result=int)
    def createBox(self, name: str) -> int:
        name = (name or "").strip()
        if not name:
            return -1
        box_id = self._db.create_box(name)
        self.boxesChanged.emit()
        self._set_status(f"box {name} is ready")
        return box_id

    @Slot(int, str)
    def renameBox(self, box_id: int, name: str) -> None:
        if not (name or "").strip():
            return
        self._db.rename_box(box_id, name)
        self.boxesChanged.emit()
        self.viewChanged.emit()

    @Slot(int)
    def deleteBox(self, box_id: int) -> None:
        self._db.delete_box(box_id)
        if self._view_kind == BOX and self._view_id == box_id:
            self._set_view(ALL, -1)
        self.boxesChanged.emit()

    @Slot(int, str)
    def addToBox(self, box_id: int, video_key: str) -> None:
        self._db.add_to_box(box_id, video_key)
        self.boxesChanged.emit()
        if self._view_kind == BOX:
            self.reload()

    @Slot(int, str)
    def removeFromBox(self, box_id: int, video_key: str) -> None:
        self._db.remove_from_box(box_id, video_key)
        self.boxesChanged.emit()
        if self._view_kind == BOX:
            self.reload()

    @Slot(str, result="QVariantList")
    def boxesHolding(self, video_key: str) -> list:
        return self._db.boxes_holding(video_key)

    # ---- actions ---------------------------------------------------------

    @Slot()
    def refresh(self) -> None:
        """The button. Takes every channel and resets the timer."""
        self._start_poll(force_all=True)

    @Slot()
    def poll(self) -> None:
        """The timer. Takes only the channels actually due, so a large
        subscription list is spread out instead of arriving as one burst."""
        self._start_poll(force_all=False)

    def _start_poll(self, force_all: bool) -> None:
        if self._busy:
            return
        self._problems = [p for p in self._problems if not p.startswith("feed ")]
        self.problemsChanged.emit()
        self._set_busy(True)
        self._set_status("refreshing")
        self._poller = FeedPoller(self._db, self._cfg, force_all, self)
        self._poller.progress.connect(
            lambda phase, done, total: self._set_status(
                f"{phase} {done} of {total}" if total > 1 else phase))
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

    @Slot()
    def importSubscriptions(self) -> None:
        if self._importer is not None and self._importer.isRunning():
            return
        self._set_status("importing the subscription list")
        self._importer = SubsImporter(self._db, self._cfg, self)
        self._importer.imported.connect(self._on_imported)
        self._importer.failed.connect(self._on_import_failed)
        self._importer.start()

    @Slot(str, result=bool)
    def addChannel(self, text: str) -> bool:
        """Accepts a channel id, an @handle, a legacy channel URL or a Twitch
        link. Returns whether the reference was understood at all. Resolving a
        handle then happens in the background."""
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

    def shutdown(self, timeout_ms: int = 15000) -> None:
        """Stop every background thread before Qt tears them down.

        Qt treats destroying a running QThread as fatal and aborts the whole
        process, so closing the window during a refresh used to crash on exit.
        All threads are cancelled first and then waited on, so they stop in
        parallel rather than one after another. This runs after the window is
        already gone, so any short wait here is invisible.
        """
        threads = [self._poller, self._adder, self._importer, self._details]
        live = [thread for thread in threads if thread is not None and thread.isRunning()]
        for thread in live:
            thread.cancel()
        for thread in live:
            thread.wait(timeout_ms)

    # ---- reactions -------------------------------------------------------

    def _on_channel_added(self, key: str, platform: str, ext_id: str, title: str) -> None:
        self._db.add_channel(key, platform, ext_id, title or None)
        label = title or ext_id
        if platform == "twitch":
            # Said plainly. A Twitch channel adding no rows to the feed looks
            # broken otherwise.
            self._set_status(f"added {label}, which will show in the live bar rather than the feed")
            self.reload()
        else:
            self._set_status(f"added {label}, fetching videos")
            self.refresh()

    def _on_channel_failed(self, message: str) -> None:
        self._set_status(f"could not add that channel, {message}")

    def _on_imported(self, found: int, added: int) -> None:
        self._set_status(f"{found} subscriptions found, {added} newly tracked")
        self.reload()
        if added:
            self.refresh()

    def _on_import_failed(self, message: str) -> None:
        self._problems.append(f"subscription import, {message}")
        self.problemsChanged.emit()
        self._set_status(f"could not import the subscriptions, {message}")

    def _on_watched(self, key: str, progress: float) -> None:
        self._db.set_watched(key, progress, "mpv")
        self.reload()
        self._set_status(f"marked watched at {int(progress * 100)} percent")

    def _on_player_failed(self, message: str) -> None:
        self._problems.append(message)
        self.problemsChanged.emit()
        self._set_status(message)

    def _on_poll_failure(self, source: str, message: str) -> None:
        self._problems.append(f"feed {source}: {message}")
        self.problemsChanged.emit()

    def _on_poll_finished(self, channels: int, touched: int, failures: int) -> None:
        self._set_busy(False)
        self.reload()
        suffix = f", {failures} failed" if failures else ""
        self._set_status(f"{channels} channels checked, {touched} rows updated{suffix}")
        self._poller = None
