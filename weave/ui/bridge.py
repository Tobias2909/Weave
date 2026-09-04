"""The single object QML talks to.

Keeping one bridge rather than exposing the database and the poller directly
means QML never makes a blocking call, and every action the interface can
trigger is listed in one place.

The current view is one piece of state rather than several independent filters,
because all, a group, a box and a channel page are mutually exclusive and
letting them be set separately would allow combinations with no meaning.
"""

from __future__ import annotations

import json
import time

from PySide6.QtCore import Property, QObject, Signal, Slot

from .. import format as fmt
from .. import ids
from ..config import Config
from ..db import Database
from ..imagecache import qml_source
from ..player.mpv import Player
from ..poller import (ChannelAdder, ChannelDetailsFetcher, DetailFetcher, FeedPoller,
                      HistoryImporter, LiveWatcher, MusicHome, MusicSearch,
                      SourceDetails, TrackList, SubsImporter, TwitchLogin)
from .feed_model import FeedModel

ALL = "all"
MUSIC = "music"
GROUP = "group"
BOX = "box"
CHANNEL = "channel"
SEARCH = "search"
HISTORY = "history"

# How long the shelves are trusted before being gathered again. They are a
# recommendation, not a fact, and they cost several seconds to fetch.
SHELF_LIFETIME_S = 6 * 3600


class Bridge(QObject):
    statusChanged = Signal()
    busyChanged = Signal()
    hideWatchedChanged = Signal()
    problemsChanged = Signal()
    emptyHintChanged = Signal()
    groupsChanged = Signal()
    boxesChanged = Signal()
    viewChanged = Signal()
    liveChanged = Signal()
    twitchChanged = Signal()
    detailChanged = Signal()
    musicChanged = Signal()

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
        self._history: HistoryImporter | None = None
        self._details: ChannelDetailsFetcher | None = None
        self._live: LiveWatcher | None = None
        self._twitch: TwitchLogin | None = None
        self._twitch_status = ""
        self._twitch_needs_login = False
        self._detail: DetailFetcher | None = None
        self._detail_key = ""
        self._detail_comments: list = []
        self._detail_threads = 5
        self._detail_loading = False
        self._detail_closed = False
        self._audio = None
        self._search: MusicSearch | None = None
        self._results: list = []
        self._searching = False
        self._home: MusicHome | None = None
        self._shelves: list = []
        self._shelves_age = 0
        self._tracks: TrackList | None = None
        self._source_details: list = []
        self._results_label = ""
        self._autoplay_tracks = False

        self._busy = False
        self._problems: list[str] = []
        self._status = ""

        self._view_kind = ALL
        self._view_id = -1
        self._view_channel = ""
        self._search_text = ""
        # Where a search started, so emptying the box goes back there.
        self._before_search: tuple[str, int, str] = (ALL, -1, "")

        self._hide_watched = self._db.get_state("hide_watched", "1") == "1"
        self._live_collapsed = self._db.get_state("live_collapsed", "0") == "1"
        self._panel_width = int(self._db.get_state("panel_width", "380") or 380)

        self._player.watched.connect(self._on_watched)
        self._player.nowPlaying.connect(self._on_now_playing)
        self._player.stopped.connect(self._on_player_stopped)
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
            "avatar": qml_source(found.get("avatar_url")),
            "banner": qml_source(found.get("banner_url")),
            "followers": found.get("follower_count") or 0,
            "followersText": fmt.count_text(found.get("follower_count")),
            "videos": found.get("video_count") or 0,
            "platform": found.get("platform", "youtube"),
        }

    def _get_empty_hint(self) -> str:
        """What to say when the grid is empty. There are several different
        reasons for that and they need different answers."""
        if self._view_kind == SEARCH:
            return f"Nothing stored matches {self._search_text}."
        if self._view_kind == HISTORY:
            return ("Nothing has been watched yet.\n"
                    "Play something, or import your YouTube history.")
        if self._view_kind == BOX:
            return ("This box is empty.\nRight click any video and put it in here.")
        if self._view_kind == CHANNEL:
            return "No videos stored for this channel yet.\nPress Refresh."
        counts = self._db.counts()
        if not counts["channels"]:
            return "Nothing here yet.\nAdd a channel above, then press Refresh."
        if self._view_kind == GROUP:
            return ("This group has no channels in it yet.\n"
                    "Right click a video, or use the Groups button on a channel page.")
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

    def _get_live(self) -> list:
        rows = []
        for row in self._db.live_now():
            rows.append({
                "channelKey": row["channel_key"],
                "platform": row["platform"],
                "login": row.get("login") or "",
                "name": row.get("display_name") or row.get("channel_title") or "",
                "title": row.get("title") or "",
                "game": row.get("game") or "",
                "viewers": int(row.get("viewers") or 0),
                "viewersText": fmt.count_text(row.get("viewers") or None),
                "thumbnail": qml_source(row.get("thumbnail_url")),
                "avatar": qml_source(row.get("avatar_url")),
            })
        return rows

    def _get_twitch_status(self) -> str:
        return self._twitch_status

    def _get_twitch_needs_login(self) -> bool:
        return self._twitch_needs_login

    liveStreams = Property("QVariantList", _get_live, notify=liveChanged)
    twitchStatus = Property(str, _get_twitch_status, notify=twitchChanged)
    twitchNeedsLogin = Property(bool, _get_twitch_needs_login, notify=twitchChanged)

    def _get_live_collapsed(self) -> bool:
        return self._live_collapsed

    liveCollapsed = Property(bool, _get_live_collapsed, notify=liveChanged)

    def _get_detail(self) -> dict:
        row = self._db.video(self._detail_key) if self._detail_key else None
        if not row:
            return {}
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
            # An estimate rather than a count, and said so in the panel.
            "dislikesText": fmt.count_text(row["dislikes"]),
            "watched": bool(row["watched"]),
            "isLive": row["live_status"] == "is_live",
        }

    def _get_detail_open(self) -> bool:
        return bool(self._detail_key) and not self._detail_closed

    def _get_detail_comments(self) -> list:
        return list(self._detail_comments)

    def _get_detail_loading(self) -> bool:
        return self._detail_loading

    def _get_panel_width(self) -> int:
        return self._panel_width

    detail = Property("QVariantMap", _get_detail, notify=detailChanged)
    detailOpen = Property(bool, _get_detail_open, notify=detailChanged)
    detailComments = Property("QVariantList", _get_detail_comments, notify=detailChanged)
    detailLoading = Property(bool, _get_detail_loading, notify=detailChanged)
    panelWidth = Property(int, _get_panel_width, notify=detailChanged)

    def _get_results(self) -> list:
        return list(self._results)

    def _get_searching(self) -> bool:
        return self._searching

    def _get_sources(self) -> list:
        return self._db.sources()

    def _get_shelves(self) -> list:
        """In the order they were arranged, with anything new on the end."""
        shelves = list(self._shelves)
        saved = self._saved_shelf()
        if saved["items"]:
            shelves.insert(0, saved)

        wanted = self._shelf_order()
        if not wanted:
            return shelves

        # Matched one at a time rather than through a map of title to section.
        # Two sections can arrive with the same name, and a map would keep one
        # of them and lose the other, which reads as a row vanishing.
        remaining = list(shelves)
        ordered = []
        for title in wanted:
            for index, shelf in enumerate(remaining):
                if shelf["title"] == title:
                    ordered.append(remaining.pop(index))
                    break
        ordered.extend(remaining)
        return ordered

    def _saved_shelf(self) -> dict:
        """Saved addresses are a section like any other, so they can be moved
        around with the rest rather than being pinned to the top for ever."""
        return {"title": "Saved", "kind": "saved", "items": [{
            "title": row["label"], "subtitle": "live" if row["live"] else "",
            "videoId": "", "playlistId": "", "sourceId": row["id"],
            "thumbnail": qml_source(row["thumbnail"]),
        } for row in self._db.sources()]}

    def _shelf_order(self) -> list:
        stored = self._db.get_state("music_shelf_order")
        if not stored:
            return []
        try:
            order = json.loads(stored)
        except ValueError:
            return []
        return [str(title) for title in order] if isinstance(order, list) else []

    def _get_results_label(self) -> str:
        return self._results_label

    musicShelves = Property("QVariantList", _get_shelves, notify=musicChanged)
    musicLabel = Property(str, _get_results_label, notify=musicChanged)
    musicResults = Property("QVariantList", _get_results, notify=musicChanged)
    musicSearching = Property(bool, _get_searching, notify=musicChanged)
    audioSources = Property("QVariantList", _get_sources, notify=musicChanged)

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
        if self._view_kind == MUSIC:
            self._model.reload(hide_watched=False, channel_key="__none__")
            self.emptyHintChanged.emit()
            self.groupsChanged.emit()
            self.boxesChanged.emit()
            return
        # A search and the history both ignore the hide watched toggle. A
        # search is asking for one particular thing, and hiding the watched
        # half of the history would leave nothing at all.
        honour_toggle = self._view_kind in (ALL, GROUP)
        self._model.reload(
            hide_watched=self._hide_watched and honour_toggle,
            group_id=self._view_id if self._view_kind == GROUP else None,
            box_id=self._view_id if self._view_kind == BOX else None,
            channel_key=self._view_channel if self._view_kind == CHANNEL else None,
            query=self._search_text if self._view_kind == SEARCH else None,
            watched_only=self._view_kind == HISTORY,
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
        # Work a view needs on entry happens here, so every way of reaching it
        # behaves the same. It used to hang off the sidebar row, and the wheel
        # then landed on an empty page.
        if kind == MUSIC and not self._shelves:
            self.loadHome()

    def _selectable(self) -> list[tuple[str, int]]:
        """Everything the sidebar offers, in the order it is drawn. All first,
        then groups, then boxes. A channel page is not in here because it is
        not reachable from the sidebar."""
        entries: list[tuple[str, int]] = [(ALL, -1)]
        entries.extend((GROUP, int(row["id"])) for row in self._db.groups())
        entries.append((HISTORY, -1))
        entries.append((MUSIC, -1))
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

    @Slot(str)
    def search(self, text: str) -> None:
        """Search everything stored, rather than inside whatever is showing.

        Searching is asking for one particular video, and having to remember
        which group it was in first would defeat that. Emptying the box goes
        back to where the search started, so it behaves like a detour and not
        like a place.
        """
        text = (text or "").strip()
        if not text:
            if self._view_kind == SEARCH:
                kind, view_id, channel = self._before_search
                self._search_text = ""
                self._set_view(kind, view_id, channel)
            return
        first = self._view_kind != SEARCH
        if first:
            self._before_search = (self._view_kind, self._view_id, self._view_channel)
        self._search_text = text
        if first:
            self._set_view(SEARCH, -1)
        else:
            # Same view, new words, so the guard in _set_view would drop it.
            self.reload()
            self.viewChanged.emit()

    @Slot()
    def showHistory(self) -> None:
        self._set_view(HISTORY, -1)

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

    # ---- groups ----------------------------------------------------------
    # A group is the channel level twin of a box. Everything below mirrors the
    # box slots above, because from the interface the two are the same idea
    # applied to different things.

    @Slot(str, result=int)
    def createGroup(self, name: str) -> int:
        name = (name or "").strip()
        if not name:
            return -1
        group_id = self._db.create_group(name)
        self.groupsChanged.emit()
        self._set_status(f"group {name} is ready")
        return group_id

    @Slot(int, str)
    def renameGroup(self, group_id: int, name: str) -> None:
        if not (name or "").strip():
            return
        self._db.rename_group(group_id, name)
        self.groupsChanged.emit()
        self.viewChanged.emit()

    @Slot(int)
    def deleteGroup(self, group_id: int) -> None:
        self._db.delete_group(group_id)
        # Deleting a group keeps its channels, so falling back to All shows
        # everything that was in it rather than an empty page.
        if self._view_kind == GROUP and self._view_id == group_id:
            self._set_view(ALL, -1)
        self.groupsChanged.emit()

    @Slot(int, int)
    def moveGroup(self, group_id: int, delta: int) -> None:
        if self._db.move_group(group_id, delta):
            self.groupsChanged.emit()

    @Slot(int, str)
    def addChannelToGroup(self, group_id: int, channel_key: str) -> None:
        if not channel_key:
            return
        self._db.add_to_group(group_id, channel_key)
        self.groupsChanged.emit()
        if self._view_kind == GROUP:
            self.reload()

    @Slot(int, str)
    def removeChannelFromGroup(self, group_id: int, channel_key: str) -> None:
        if not channel_key:
            return
        self._db.remove_from_group(group_id, channel_key)
        self.groupsChanged.emit()
        if self._view_kind == GROUP:
            self.reload()

    @Slot(str, result="QVariantList")
    def groupsHolding(self, channel_key: str) -> list:
        return self._db.groups_holding(channel_key)

    # ---- actions ---------------------------------------------------------

    @Slot()
    def refresh(self) -> None:
        """The button. Sweeps every subscription at once and asks the most
        overdue feeds, ignoring their intervals.

        The sweep is one call and it covers everything you are subscribed to,
        so pressing this does find whatever is new. What it does not do is ask
        several hundred feeds at once, because the endpoint on the other end
        is the same one either way.
        """
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
        # A Twitch entry is only ever a live channel for now, and a YouTube one
        # says so in the row. Either way mpv must not mark it watched.
        live = bool(row["isLive"]) or login is not None
        if self._player.play(row["url"], twitch_login=login, live=live):
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

    # ---- music -----------------------------------------------------------

    def attach_audio(self, audio) -> None:
        """Given after construction, since the player needs the config the
        bridge already holds."""
        self._audio = audio
        self._player.nowPlaying.connect(lambda *_a: self._audio.pause_for_video())

    @Slot()
    def showMusic(self) -> None:
        # Nothing else. Whatever a view needs on entry belongs to entering it,
        # not to one of the ways in, or the ways drift apart.
        self._set_view(MUSIC, -1)

    def _remembered_shelves(self) -> list:
        """What was on the shelves last time, so the view has something the
        moment it opens instead of a blank page for several seconds."""
        stored = self._db.get_state("music_shelves")
        if not stored:
            return []
        try:
            shelves = json.loads(stored)
        except ValueError:
            return []
        return shelves if isinstance(shelves, list) else []

    @Slot()
    def loadHome(self, force: bool = False) -> None:
        """What YouTube Music opens on, which is what fills this view before
        anything has been searched for.

        What was there last time is shown at once, and a fresh copy is fetched
        behind it, since the whole set takes several seconds to gather and
        barely changes between one evening and the next.
        """
        if not self._shelves:
            remembered = self._remembered_shelves()
            if remembered:
                self._shelves = remembered
                self.musicChanged.emit()
                stamp = self._db.get_state("music_shelves_at", "0") or "0"
                self._shelves_age = int(stamp) if stamp.isdigit() else 0
                if not force and time.time() - self._shelves_age < SHELF_LIFETIME_S:
                    return
        if self._home is not None and self._home.isRunning():
            return
        self._home = MusicHome(self._cfg, self)
        self._home.shelves.connect(self._on_shelves)
        self._home.failed.connect(
            lambda message: self._set_status(f"could not load the shelves, {message}"))
        self._home.start()

    @Slot(str, int)
    def moveShelf(self, title: str, direction: int) -> None:
        """Shift one section up or down. Kept by name, so it survives the
        shelves themselves changing."""
        titles = [shelf["title"] for shelf in self._get_shelves()]
        if title not in titles:
            return
        at = titles.index(title)
        to = max(0, min(len(titles) - 1, at + (1 if direction > 0 else -1)))
        if to == at:
            return
        titles.insert(to, titles.pop(at))
        # Only what is actually on screen is kept, so an order cannot collect
        # names of sections that have gone.
        self._db.set_state("music_shelf_order", json.dumps(titles))
        self.musicChanged.emit()

    @Slot()
    def resetShelfOrder(self) -> None:
        self._db.set_state("music_shelf_order", "")
        self.musicChanged.emit()

    @Slot()
    def clearResults(self) -> None:
        self._results = []
        self._results_label = ""
        self.musicChanged.emit()

    @Slot()
    def playLiked(self) -> None:
        """Liked videos come from YouTube rather than YouTube Music. The two
        lists are separate and this is the one with anything in it."""
        self._start_tracks(TrackList(self._cfg, TrackList.LIKED, label="Liked", parent=self))

    @Slot(int, int)
    def playShelfItem(self, shelf_index: int, item_index: int) -> None:
        # The index comes from what is on screen, which is the arranged list
        # with the saved section in it, not the raw one. Reading the raw list
        # here meant a tile acted on some other section's entry as soon as an
        # order was kept or an address was saved.
        try:
            item = self._get_shelves()[shelf_index]["items"][item_index]
        except (IndexError, KeyError, TypeError):
            return
        video = item.get("videoId")
        playlist = item.get("playlistId")

        # A song carries both its own id and the id of the station built from
        # it. Pressing it plays that song and then things like it, which is
        # what the music application does, so the station is what to fetch.
        if video and playlist:
            self._start_tracks(TrackList(self._cfg, TrackList.RADIO, video,
                                         item.get("title", ""), self), autoplay=True)
            return
        # A playlist is opened to look at. Nothing starts until something in it
        # is chosen.
        if playlist:
            self._start_tracks(TrackList(self._cfg, "playlist", playlist,
                                         item.get("title", ""), self))
            return
        if video and self._audio:
            self._audio.play_items([{
                "key": f"yt:{video}", "title": item.get("title", ""),
                "artist": item.get("subtitle", ""), "thumbnail": item.get("thumbnail", ""),
                "live": False, "url": ids.watch_url("youtube", video),
            }])

    def _start_tracks(self, worker: TrackList, autoplay: bool = False) -> None:
        if self._tracks is not None and self._tracks.isRunning():
            return
        self._autoplay_tracks = autoplay
        self._searching = True
        self.musicChanged.emit()
        self._tracks = worker
        self._tracks.tracks.connect(self._on_tracks)
        self._tracks.failed.connect(self._on_search_failed)
        self._tracks.start()

    def _on_shelves(self, shelves: list) -> None:
        self._shelves = shelves
        self._shelves_age = int(time.time())
        self._db.set_state("music_shelves", json.dumps(shelves))
        self._db.set_state("music_shelves_at", str(self._shelves_age))
        self.musicChanged.emit()

    @Slot()
    def refreshMusic(self) -> None:
        self.loadHome(force=True)

    def _on_tracks(self, rows: list, label: str) -> None:
        self._searching = False
        self._results = rows
        self._results_label = label
        self.musicChanged.emit()
        # Only a station starts on its own. A list is opened to look at.
        if rows and self._autoplay_tracks:
            self.playResult(0)

    @Slot(str)
    def musicSearch(self, query: str) -> None:
        if self._search is not None and self._search.isRunning():
            return
        self._searching = True
        self.musicChanged.emit()
        self._search = MusicSearch(self._cfg, query, self)
        self._search.results.connect(self._on_results)
        self._search.failed.connect(self._on_search_failed)
        self._search.start()

    @Slot(int)
    def playResult(self, index: int) -> None:
        """Plays from here to the end of the results, which is what a list of
        songs is for."""
        if not self._audio or not self._results:
            return
        items = [{"key": row["key"], "title": row["title"], "artist": row["artist"],
                  "thumbnail": row["thumbnail"], "live": False,
                  "url": ids.watch_url("youtube", row["videoId"])}
                 for row in self._results]
        self._audio.play_items(items, max(0, min(index, len(items) - 1)))

    @Slot(int)
    def playSource(self, source_id: int) -> None:
        if not self._audio:
            return
        found = next((s for s in self._db.sources() if s["id"] == source_id), None)
        if not found:
            return
        self._audio.play_items([{
            "key": f"source:{found['id']}", "title": found["label"], "artist": "",
            "thumbnail": "", "live": bool(found["live"]), "url": found["url"],
        }])

    @Slot(str)
    def playAudio(self, video_key: str) -> None:
        """The headphone button on a video card. Same video, no window."""
        row = self._model.row_for_key(video_key) or {}
        if not self._audio or not row:
            return
        self._audio.play_items([{
            "key": video_key, "title": row["title"], "artist": row["channelTitle"],
            "thumbnail": row["thumbnail"], "live": bool(row["isLive"]),
            "url": row["url"],
        }])
        self._set_status(f"listening to {row['title']}")

    @Slot(str, str, bool)
    def addSource(self, label: str, url: str, live: bool) -> None:
        if not url.strip():
            return
        self._db.add_source(label, url.strip(), live)
        self.musicChanged.emit()
        # A name and a picture, so the row is worth looking at.
        worker = SourceDetails(self._db, self._cfg, url.strip(), self)
        worker.done.connect(self.musicChanged)
        self._source_details.append(worker)
        worker.start()

    @Slot(int)
    def removeSource(self, source_id: int) -> None:
        self._db.remove_source(source_id)
        self.musicChanged.emit()

    def _on_results(self, rows: list) -> None:
        self._searching = False
        self._results = rows
        self._results_label = "Search results"
        self.musicChanged.emit()

    def _on_search_failed(self, message: str) -> None:
        self._searching = False
        self.musicChanged.emit()
        self._set_status(f"could not search, {message}")

    # ---- the detail panel ------------------------------------------------

    @Slot(str)
    def openDetail(self, key: str) -> None:
        """Show one video. Reopens the panel if it was closed, since asking for
        a video is asking to see it."""
        if not key:
            return
        self._detail_closed = False
        if key == self._detail_key:
            self.detailChanged.emit()
            return
        self._detail_key = key
        self._detail_comments = []
        self._detail_threads = 5
        self.detailChanged.emit()
        self._start_detail()

    @Slot()
    def closeDetail(self) -> None:
        """Closed until the next video starts, rather than closed for good. It
        mirrors what is playing, so the next thing that plays brings it back."""
        self._detail_closed = True
        if self._detail is not None and self._detail.isRunning():
            self._detail.cancel()
        self.detailChanged.emit()

    @Slot()
    def loadMoreComments(self) -> None:
        if self._detail_loading or not self._detail_key:
            return
        self._detail_threads += 10
        self._start_detail()

    @Slot(int)
    def setPanelWidth(self, width: int) -> None:
        width = max(300, min(560, int(width)))
        if width == self._panel_width:
            return
        self._panel_width = width
        self._db.set_state("panel_width", str(width))
        self.detailChanged.emit()

    def _start_detail(self) -> None:
        row = self._db.video(self._detail_key)
        if not row:
            return
        if self._detail is not None and self._detail.isRunning():
            self._detail.cancel()
            self._detail.wait(3000)
        self._detail_loading = True
        self.detailChanged.emit()
        self._detail = DetailFetcher(self._db, self._cfg, row["key"], row["ext_id"],
                                     ids.watch_url(row["platform"], row["ext_id"]),
                                     self._detail_threads, self)
        self._detail.votes.connect(self._on_votes)
        self._detail.comments.connect(self._on_comments)
        self._detail.failed.connect(self._on_detail_failed)
        self._detail.start()

    def _on_votes(self, key: str, _count: int) -> None:
        if key == self._detail_key:
            self.detailChanged.emit()

    def _on_comments(self, key: str, threads: list) -> None:
        self._detail_loading = False
        if key == self._detail_key:
            self._detail_comments = threads
        self.detailChanged.emit()

    def _on_detail_failed(self, source: str, message: str) -> None:
        self._detail_loading = False
        self.detailChanged.emit()
        self._set_status(f"could not load the {source}, {message}")

    def _on_player_stopped(self) -> None:
        """Nothing is playing any more, so there is nothing for the panel to
        mirror. The next video brings it back."""
        self._detail_key = ""
        self._detail_comments = []
        self._detail_closed = False
        if self._detail is not None and self._detail.isRunning():
            self._detail.cancel()
        self.detailChanged.emit()

    def _on_now_playing(self, key: str, _title: str) -> None:
        """The panel follows mpv, so whatever starts playing is what it shows,
        including a track mpv moved to on its own."""
        self.openDetail(key)

    # ---- twitch ----------------------------------------------------------

    @Slot()
    def connectTwitch(self) -> None:
        if self._twitch is not None and self._twitch.isRunning():
            return
        self._twitch_status = "asking Twitch for a code"
        self.twitchChanged.emit()
        self._twitch = TwitchLogin(self._db, self._cfg, self)
        self._twitch.codeReady.connect(self._on_twitch_code)
        self._twitch.finished_login.connect(self._on_twitch_done)
        self._twitch.failed.connect(self._on_twitch_failed)
        self._twitch.start()

    @Slot()
    def refreshLive(self) -> None:
        if self._live is not None and self._live.isRunning():
            return
        self._live = LiveWatcher(self._db, self._cfg, self)
        self._live.updated.connect(self._on_live)
        self._live.needsLogin.connect(self._on_twitch_needs_login)
        self._live.failed.connect(
            lambda message: self._set_status(f"could not check Twitch, {message}"))
        self._live.start()

    @Slot(bool)
    def setLiveCollapsed(self, value: bool) -> None:
        if value == self._live_collapsed:
            return
        self._live_collapsed = value
        self._db.set_state("live_collapsed", "1" if value else "0")
        self.liveChanged.emit()

    @Slot(str)
    def playLive(self, channel_key: str) -> None:
        row = next((entry for entry in self._get_live()
                    if entry["channelKey"] == channel_key), None)
        if not row:
            return
        if row["platform"] == "twitch":
            url = ids.watch_url("twitch", row["login"])
            self._player.play(url, twitch_login=row["login"], live=True)
        else:
            self._player.play(ids.watch_url("youtube", row["login"]), live=True)
        self._set_status(f"playing {row['name']}")

    @Slot()
    def importSubscriptions(self) -> None:
        if self._importer is not None and self._importer.isRunning():
            return
        self._set_status("importing the subscription list")
        self._importer = SubsImporter(self._db, self._cfg, self)
        self._importer.imported.connect(self._on_imported)
        self._importer.failed.connect(self._on_import_failed)
        self._importer.start()

    @Slot()
    def importHistory(self) -> None:
        if self._history is not None and self._history.isRunning():
            return
        self._set_status("reading your YouTube history")
        self._history = HistoryImporter(self._db, self._cfg, parent=self)
        self._history.imported.connect(self._on_history)
        self._history.failed.connect(
            lambda message: self._set_status(f"history, {message}"))
        self._history.start()

    def _on_history(self, marked: int, missing: int) -> None:
        note = f"{marked} marked as watched"
        if missing:
            # Not an error worth a banner. A history row carries no channel, so
            # a video from a channel that is not tracked cannot be placed.
            note += f", {missing} were from channels not tracked here"
        self._set_status(note)
        self.reload()

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
        threads = [self._poller, self._adder, self._importer, self._history,
                   self._details, self._live, self._twitch, self._detail, self._search,
                   self._home, self._tracks, *self._source_details]
        live = [thread for thread in threads if thread is not None and thread.isRunning()]
        for thread in live:
            thread.cancel()
        for thread in live:
            thread.wait(timeout_ms)
        if self._audio is not None:
            self._audio.shutdown()

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

    def _on_twitch_code(self, user_code: str, address: str) -> None:
        """The address already contains the code, so the browser lands on a
        page with nothing to type."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        self._twitch_status = f"approve {user_code} in the browser"
        self.twitchChanged.emit()
        QDesktopServices.openUrl(QUrl(address))

    def _on_twitch_done(self, imported: int) -> None:
        self._twitch_needs_login = False
        self._twitch_status = (f"Twitch connected, {imported} followed channels added"
                               if imported else "Twitch connected")
        self.twitchChanged.emit()
        self._set_status(self._twitch_status)
        self.reload()
        self.refreshLive()

    def _on_twitch_failed(self, message: str) -> None:
        self._twitch_status = f"Twitch login failed, {message}"
        self.twitchChanged.emit()
        self._set_status(self._twitch_status)

    def _on_twitch_needs_login(self) -> None:
        if not self._twitch_needs_login:
            self._twitch_needs_login = True
            self._twitch_status = "not connected to Twitch"
            self.twitchChanged.emit()

    def _on_live(self, count: int) -> None:
        self._twitch_needs_login = False
        self.liveChanged.emit()
        self.twitchChanged.emit()

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
