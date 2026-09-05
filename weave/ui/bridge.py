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

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot

from .. import format as fmt
from .. import ids
from ..config import Config
from ..db import Database
from ..imagecache import qml_source
from ..player.mpv import Player
from ..poller import (
    ChannelAdder,
    ChannelDetailsFetcher,
    Checkup,
    DetailFetcher,
    FeedPoller,
    HistoryImporter,
    LiveWatcher,
    MusicHome,
    MusicSearch,
    PlaylistItemsFetcher,
    PlaylistsFetcher,
    RecommendationsFetcher,
    SearchFetcher,
    SourceDetails,
    SubsImporter,
    TrackList,
    TwitchLogin,
)
from .feed_model import FeedModel
from .navigation import History

ALL = "all"
MUSIC = "music"
GROUP = "group"
BOX = "box"
CHANNEL = "channel"
SEARCH = "search"
HISTORY = "history"
RECOMMENDED = "recommended"
PLAYLIST = "playlist"
DEBUG = "debug"

# How long a set of recommendations is worth showing before asking for another,
# and how long a playlist's contents are trusted before reading them again.
RECOMMENDED_TRUST_S = 6 * 3600
PLAYLIST_TRUST_S = 6 * 3600
# Shorter, because a history changes every time something is played.
HISTORY_TRUST_S = 30 * 60

# How many results one page of a YouTube search or one more helping of
# recommendations asks for. Small enough to arrive quickly, since scrolling to
# the bottom is what asks for it.
PAGE = 24

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
    playlistsChanged = Signal()
    noticeChanged = Signal()
    searchEnded = Signal()
    checksChanged = Signal()
    boxesChanged = Signal()
    viewChanged = Signal()
    liveChanged = Signal()
    twitchChanged = Signal()
    detailChanged = Signal()
    musicChanged = Signal()
    navChanged = Signal()

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
        self._recommended: RecommendationsFetcher | None = None
        self._playlists: PlaylistsFetcher | None = None
        self._playlist_items: PlaylistItemsFetcher | None = None
        self._view_playlist = ""
        # Set once the window is going away, so nothing starts a new thread
        # after the shutdown has already waited for the old ones.
        self._stopping = False
        # Every worker that has been started and has not finished. Kept so
        # the shutdown knows exactly what to wait for, and so a finished one
        # can be let go rather than kept for the life of the window.
        self._threads: set = set()
        self._details: ChannelDetailsFetcher | None = None
        self._live: LiveWatcher | None = None
        # Raised while a live check is in flight. The bar reads it so the
        # first check after start says it is working instead of sitting empty.
        self._live_checking = False
        self._twitch: TwitchLogin | None = None
        self._twitch_status = ""
        self._twitch_needs_login = False
        self._detail: DetailFetcher | None = None
        self._detail_key = ""
        # Dislikes for a video that is not in the videos table. Storing them
        # has nowhere to go there, and they are worth showing anyway.
        self._detail_dislikes: tuple[str, int] | None = None
        # Likes, the publish date and an exact view count for a video that is
        # not in the feed. They arrive with the comments, from the metadata
        # file that call already writes.
        self._detail_extra: tuple[str, dict] | None = None
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
        # Stored is the local query, youtube is the one that costs a request.
        self._search_scope = "stored"
        # A short line about something happening now, shown over the grid. The
        # status text in the bar is easy to miss, and some of these take
        # several seconds with nothing else on screen to show for them.
        self._notice = ""
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: self._set_notice(""))
        # Named apart from the music search results, which live on the same
        # object under a name that used to be _results as well.
        self._web_results: list[dict] = []
        self._searcher: SearchFetcher | None = None
        self._checkup: Checkup | None = None
        self._checks: list = []
        self._loading_more = False
        self._exhausted = False
        # Where a search started, so emptying the box goes back there.
        self._before_search: tuple[str, int, str, str] = (ALL, -1, "", "")
        # Every view landed on, walked by the back and forward mouse buttons.
        # Seeded with the view the window opens on, so the first step back has
        # somewhere to land rather than one fewer place than was visited.
        self._nav = History((self._view_kind, self._view_id, self._view_channel,
                             self._view_playlist))
        # Raised while a remembered view is being restored. Without it the
        # replay would record itself as a fresh step and forward would never
        # be reachable. An explicit flag rather than comparing the view being
        # set against the one the record points at, since those are equal in
        # ordinary use as well.
        self._nav_replaying = False

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

    def _get_playlists(self) -> list:
        return self._db.playlists()

    def _get_all_playlists(self) -> list:
        """Every playlist including the hidden ones, for the chooser. Hiding
        is not forgetting, so the chooser has to show what is hidden too."""
        return self._db.playlists(include_hidden=True)

    def _get_view_kind(self) -> str:
        return self._view_kind

    def _get_view_id(self) -> int:
        return self._view_id

    def _get_can_go_back(self) -> bool:
        return self._nav.can_go_back()

    def _get_can_go_forward(self) -> bool:
        return self._nav.can_go_forward()

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
        if self._view_kind == PLAYLIST:
            return "This playlist is empty."
        if self._view_kind == RECOMMENDED:
            return "Nothing suggested yet.\nPress Ask again in the bar."
        if self._view_kind == SEARCH and self._search_scope == "youtube":
            return f"YouTube found nothing for {self._search_text}."
        if self._view_kind == SEARCH:
            return (f"Nothing stored matches {self._search_text}.\n"
                    "Press Enter to search YouTube itself.")
        if self._view_kind == HISTORY:
            return "Nothing in your YouTube history yet."
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
    notice = Property(str, lambda self: self._notice, notify=noticeChanged)
    checks = Property("QVariantList", lambda self: list(self._checks), notify=checksChanged)
    schedule = Property("QVariantList", lambda self: self._get_schedule(),
                        notify=checksChanged)
    playlists = Property("QVariantList", _get_playlists, notify=playlistsChanged)
    allPlaylists = Property("QVariantList", _get_all_playlists, notify=playlistsChanged)
    viewKind = Property(str, _get_view_kind, notify=viewChanged)
    viewId = Property(int, _get_view_id, notify=viewChanged)
    viewPlaylist = Property(str, lambda self: self._view_playlist, notify=viewChanged)
    searchScope = Property(str, lambda self: self._search_scope, notify=viewChanged)
    channelInfo = Property("QVariantMap", _get_channel_info, notify=viewChanged)
    canGoBack = Property(bool, _get_can_go_back, notify=navChanged)
    canGoForward = Property(bool, _get_can_go_forward, notify=navChanged)

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

    def _get_live_checking(self) -> bool:
        return self._live_checking

    liveCollapsed = Property(bool, _get_live_collapsed, notify=liveChanged)
    liveChecking = Property(bool, _get_live_checking, notify=liveChanged)

    def _video_for_detail(self, key: str):
        """The video the panel is showing, from wherever it is known.

        Search results are held here and stored nowhere, on purpose, so they
        have to be looked up in memory or the panel comes up empty for exactly
        the videos that are hardest to find again.
        """
        if not key:
            return None
        found = self._db.video(key)
        if found:
            return found
        return next((row for row in self._web_results if row["key"] == key), None)

    def _get_detail(self) -> dict:
        if self._detail_key.startswith("twitch:"):
            return self._stream_detail(self._detail_key)
        row = self._video_for_detail(self._detail_key)
        if not row:
            return {}
        return {
            "key": row["key"],
            "title": row["title"],
            "channelKey": row["channel_key"],
            "channelTitle": row["channel_title"] or "",
            "channelAvatar": qml_source(row["avatar_url"]),
            "thumbnail": qml_source(row["thumbnail_url"]),
            "ageText": fmt.age_text(self._extra(row, "published_at")),
            "durationText": fmt.duration_text(self._extra(row, "duration_s")),
            "viewsText": fmt.count_text(self._extra(row, "views")),
            "likesText": fmt.count_text(self._extra(row, "likes")),
            # An estimate rather than a count, and said so in the panel.
            "dislikesText": fmt.count_text(self._dislikes_for(row)),
            "watched": bool(row["watched"]),
            "isLive": row["live_status"] == "is_live",
        }

    def _extra(self, row, name: str):
        """What is stored, or what the comments call brought back for a video
        that is not stored. Never the other way round, since a stored row is
        the more exact of the two."""
        stored = row.get(name)
        if stored is not None:
            return stored
        if self._detail_extra and self._detail_extra[0] == row["key"]:
            return self._detail_extra[1].get(name)
        return None

    def _dislikes_for(self, row) -> int | None:
        if row.get("dislikes") is not None:
            return row["dislikes"]
        if self._detail_dislikes and self._detail_dislikes[0] == row["key"]:
            return self._detail_dislikes[1]
        return None

    def _stream_detail(self, key: str) -> dict:
        """A Twitch stream in the panel.

        It is not a video and has no row among them, so what it shows is what a
        stream has: who, what they are playing, how many are watching and how
        long it has been going. There are no comments and no likes to fetch.
        """
        row = self._db.live_stream(key)
        if not row:
            return {}
        started = row.get("started_at") or ""
        since = None
        if started:
            try:
                from datetime import datetime
                since = int(datetime.fromisoformat(
                    started.replace("Z", "+00:00")).timestamp())
            except ValueError:
                since = None
        return {
            "key": key,
            "title": row.get("title") or row.get("display_name") or "",
            "channelKey": key,
            "channelTitle": row.get("display_name") or row.get("channel_title") or "",
            "channelAvatar": qml_source(row.get("avatar_url")),
            "thumbnail": qml_source(row.get("thumbnail_url")),
            "ageText": f"live since {fmt.age_text(since)}" if since else "",
            "durationText": "",
            "viewsText": "",
            "watchingText": fmt.count_text(row.get("viewers")),
            "gameText": row.get("game") or "",
            "likesText": "",
            "dislikesText": "",
            "watched": False,
            "isLive": True,
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

    def _set_live_checking(self, value: bool) -> None:
        if value != self._live_checking:
            self._live_checking = value
            self.liveChanged.emit()

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
        if self._view_kind == SEARCH and self._search_scope == "youtube":
            # Results from YouTube are not stored anywhere. They are joined to
            # what is known here so a channel already followed keeps its icon.
            self._model.show(self._web_results)
            self.emptyHintChanged.emit()
            return
        if self._view_kind == PLAYLIST:
            # A playlist keeps the order somebody put it in, which is why it
            # is not sorted by date like the feed.
            self._model.show(self._db.playlist_items(self._view_playlist))
            self.emptyHintChanged.emit()
            return
        if self._view_kind in (RECOMMENDED, HISTORY):
            # Both come from YouTube rather than from the feed, and are shaped
            # the same so one grid draws them. Nothing here is a video you
            # follow.
            kind = self._db.RECOMMENDED if self._view_kind == RECOMMENDED else self._db.HISTORY
            self._model.show(self._db.cached(kind))
            self.emptyHintChanged.emit()
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
        )
        self.emptyHintChanged.emit()
        self.groupsChanged.emit()
        self.boxesChanged.emit()

    def _set_notice(self, text: str, clear_after_s: float = 0) -> None:
        """Say what is happening, and stop saying it when it stops.

        A fallback timer clears it, because the thing being waited for can
        fail to arrive at all. mpv may never report a file, and a line that
        never goes away is worse than no line.
        """
        if text != self._notice:
            self._notice = text
            self.noticeChanged.emit()
        self._notice_timer.stop()
        if text and clear_after_s:
            self._notice_timer.start(int(clear_after_s * 1000))

    def _set_view(self, kind: str, view_id: int = -1, channel_key: str = "",
                  playlist_id: str = "") -> None:
        if (kind, view_id, channel_key, playlist_id) == (
                self._view_kind, self._view_id, self._view_channel, self._view_playlist):
            return
        left_search = self._view_kind == SEARCH and kind != SEARCH
        self._view_kind = kind
        self._view_id = view_id
        self._view_channel = channel_key
        self._view_playlist = playlist_id
        # Below the guard above, which returns before this on a view that is
        # already showing, so setting the same view twice is one entry rather
        # than two. The words come along for a search only, and only as
        # something to restore, never as part of what makes a view itself.
        if not self._nav_replaying and self._nav.record(
                (kind, view_id, channel_key, playlist_id),
                self._search_text if kind == SEARCH else ""):
            self.navChanged.emit()
        if left_search:
            # Going anywhere else ends the search, so the words go with it
            # rather than sitting in the box describing a view you left.
            self._search_text = ""
            self._search_scope = "stored"
            # The results themselves are kept. The panel follows what mpv is
            # playing, and that can well be a result you found and then walked
            # away from.
            self.searchEnded.emit()
        self.viewChanged.emit()
        self.reload()
        # Work a view needs on entry happens here, so every way of reaching it
        # behaves the same. It used to hang off the sidebar row, and the wheel
        # then landed on an empty page.
        if kind == MUSIC and not self._shelves:
            self.loadHome()
        if kind == DEBUG and not self._checks:
            self.runChecks(True)
        if kind == RECOMMENDED:
            self._exhausted = False
            self._fetch_recommended()
        if kind == HISTORY:
            self._exhausted = False
            self._fetch_history()
        if kind == PLAYLIST:
            self._fetch_playlist_items(playlist_id)

    @Slot()
    def goBack(self) -> None:
        """One view back, the way a browser's back button walks."""
        self._walk(self._nav.back())

    @Slot()
    def goForward(self) -> None:
        """Back towards where walking back came from."""
        self._walk(self._nav.forward())

    def _walk(self, entry) -> None:
        """Show a remembered view without recording it as a new one.

        A search is put back with the words it was made with, and always
        against what is stored rather than against YouTube. The results of a
        web search are held in memory and a later search replaces them, so
        restoring that scope could show one search's results under another
        search's words. Pressing Enter asks YouTube again.
        """
        if entry is None:
            return
        self._nav_replaying = True
        try:
            if entry.view[0] == SEARCH:
                self._search_text = entry.search_text
                self._search_scope = "stored"
            self._set_view(*entry.view)
        finally:
            self._nav_replaying = False
        self.navChanged.emit()

    def _selectable(self) -> list[tuple[str, int]]:
        """Everything the sidebar offers, in the order it is drawn.

        The order has to match the sidebar exactly. When the playlists moved
        below the boxes and this did not, the wheel walked straight past the
        boxes and landed in the playlists, which is not where the eye was.
        A channel page is not in here because it is not reachable from the
        sidebar.
        """
        entries: list[tuple[str, int]] = [(ALL, -1)]
        entries.extend((GROUP, int(row["id"])) for row in self._db.groups())
        entries.append((RECOMMENDED, -1))
        entries.append((HISTORY, -1))
        entries.append((MUSIC, -1))
        entries.append((DEBUG, -1))
        entries.extend((BOX, int(row["id"])) for row in self._db.boxes())
        entries.extend((PLAYLIST, index) for index, _ in enumerate(self._db.playlists()))
        return entries

    @Slot(int)
    def stepSelection(self, delta: int) -> None:
        """Move up or down the sidebar. From a channel page this lands on All
        going one way and on the last entry going the other, since a channel
        page has no place in the list."""
        entries = self._selectable()
        if not entries:
            return
        if self._view_kind == PLAYLIST:
            found = [row["ext_id"] for row in self._db.playlists()]
            position = found.index(self._view_playlist) if self._view_playlist in found else 0
            current = (PLAYLIST, position)
        else:
            current = (self._view_kind, self._view_id)
        try:
            index = entries.index(current)
        except ValueError:
            index = 0 if delta > 0 else len(entries) - 1
        else:
            index = max(0, min(len(entries) - 1, index + (1 if delta > 0 else -1)))
        kind, view_id = entries[index]
        if kind == PLAYLIST:
            # The walk carries a position rather than an id, since the ids are
            # long strings and the walk is about order.
            found = self._db.playlists()
            if 0 <= view_id < len(found):
                self._set_view(PLAYLIST, -1, "", found[view_id]["ext_id"])
            return
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
                kind, view_id, channel, playlist = self._before_search
                self._search_text = ""
                self._set_view(kind, view_id, channel, playlist)
            return
        first = self._view_kind != SEARCH
        if first:
            self._before_search = (self._view_kind, self._view_id, self._view_channel,
                                   self._view_playlist)
        self._search_text = text
        # Typing is always the local search. Asking YouTube is a separate
        # thing you press for, since it costs a request.
        self._search_scope = "stored"
        self._web_results = []
        if first:
            self._set_view(SEARCH, -1)
        else:
            # Same view, new words, so the guard in _set_view would drop it.
            self._nav.note_search(text)
            self.reload()
            self.viewChanged.emit()

    @Slot()
    def searchYouTube(self) -> None:
        """Search YouTube itself, for something that was never in the feed."""
        if not self._search_text:
            return
        self._search_scope = "youtube"
        self._web_results = []
        self._exhausted = False
        if self._view_kind != SEARCH:
            self._set_view(SEARCH, -1)
        self.viewChanged.emit()
        self._fetch_results(start=1)

    @Slot()
    def loadMore(self) -> None:
        """Another helping, asked for by reaching the bottom of the grid.

        Both feeds page properly, verified against the endpoint, so this asks
        for a later slice rather than the same one again.
        """
        if self._loading_more or self._exhausted:
            return
        if self._view_kind == SEARCH and self._search_scope == "youtube":
            self._fetch_results(start=len(self._web_results) + 1)
        elif self._view_kind == RECOMMENDED:
            self._fetch_recommended(force=True, start=self._db.recommended_count() + 1,
                                    append=True)
        elif self._view_kind == HISTORY:
            self._fetch_history(force=True,
                                start=self._db.cached_count(self._db.HISTORY) + 1,
                                append=True)

    def _fetch_results(self, start: int) -> None:
        if self._searcher is not None and self._searcher.isRunning():
            return
        self._loading_more = True
        self._set_status(f"searching YouTube for {self._search_text}")
        self._set_notice("Loading more" if start > 1 else "Searching YouTube",
                         clear_after_s=60)
        self._searcher = SearchFetcher(self._db, self._cfg, self._search_text, start, PAGE, self)
        self._searcher.results.connect(self._on_web_results)
        self._searcher.failed.connect(self._on_web_search_failed)
        self._launch(self._searcher)

    def _on_web_results(self, query: str, start: int, rows: list) -> None:
        """Named apart from the music search handler, which this class already
        had under the shorter name. Two methods with one name silently leaves
        whichever came last, and the loss is invisible until it runs."""
        self._loading_more = False
        self._set_notice("")
        if query != self._search_text:
            return                          # the words moved on while it ran
        found = self._db.decorate([dict(row) for row in rows])
        if start <= 1:
            self._web_results = found
        else:
            known = {row["key"] for row in self._web_results}
            self._web_results.extend(row for row in found if row["key"] not in known)
        # A page that brought nothing new is the end of the results.
        self._exhausted = not found
        self._set_status(f"{len(self._web_results)} results from YouTube")
        if self._view_kind == SEARCH:
            self.reload()

    def _on_web_search_failed(self, message: str) -> None:
        self._loading_more = False
        self._set_notice("")
        self._set_status(f"search, {message}")

    @Slot()
    def showHistory(self) -> None:
        self._set_view(HISTORY, -1)

    @Slot(str)
    def selectPlaylist(self, playlist_id: str) -> None:
        if playlist_id:
            self._set_view(PLAYLIST, -1, "", playlist_id)

    @Slot(str, int)
    def movePlaylist(self, playlist_id: str, delta: int) -> None:
        if self._db.move_playlist(playlist_id, delta):
            self.playlistsChanged.emit()

    @Slot(str, bool)
    def setPlaylistHidden(self, playlist_id: str, hidden: bool) -> None:
        self._db.set_playlist_hidden(playlist_id, hidden)
        if hidden and self._view_kind == PLAYLIST and self._view_playlist == playlist_id:
            self._set_view(ALL, -1)
        self.playlistsChanged.emit()

    @Slot()
    def refreshPlaylists(self) -> None:
        if self._playlists is not None and self._playlists.isRunning():
            return
        self._set_status("reading your playlists")
        self._set_notice("Reading your playlists", clear_after_s=120)
        self._playlists = PlaylistsFetcher(self._db, self._cfg, self)
        self._playlists.ready.connect(self._on_playlists)
        self._playlists.failed.connect(
            lambda message: self._set_status(f"playlists, {message}"))
        self._launch(self._playlists)

    def _on_playlists(self, count: int) -> None:
        self._set_notice("")
        self._set_status(f"{count} playlists")
        self.playlistsChanged.emit()

    @Slot()
    def refreshPlaylist(self) -> None:
        """Read the open playlist again. Its contents change without the list
        of playlists changing at all."""
        if self._view_kind == PLAYLIST:
            self._fetch_playlist_items(self._view_playlist, force=True)

    def _fetch_playlist_items(self, playlist_id: str, force: bool = False) -> None:
        if not playlist_id:
            return
        if self._playlist_items is not None and self._playlist_items.isRunning():
            return
        found = self._db.playlist(playlist_id)
        stamp = (found or {}).get("items_at")
        if not force and stamp and int(time.time()) - int(stamp) < PLAYLIST_TRUST_S:
            return
        self._set_status("reading the playlist")
        self._set_notice("Reading the playlist", clear_after_s=120)
        self._playlist_items = PlaylistItemsFetcher(self._db, self._cfg, playlist_id, self)
        self._playlist_items.ready.connect(self._on_playlist_items)
        self._playlist_items.failed.connect(
            lambda _id, message: self._set_status(f"playlist, {message}"))
        self._launch(self._playlist_items)

    def _on_playlist_items(self, playlist_id: str, count: int) -> None:
        self._set_notice("")
        self._set_status(f"{count} videos in this playlist")
        self.playlistsChanged.emit()
        if self._view_kind == PLAYLIST and self._view_playlist == playlist_id:
            self.reload()

    def _get_schedule(self) -> list:
        from .. import doctor

        rows = doctor.schedule(self._db, self._cfg, limit=60)
        for row in rows:
            row["lastText"] = ("never" if not row["last_polled_at"]
                               else fmt.age_text(row["last_polled_at"]) or "just now")
            row["dueText"] = ("now" if not row["due_in_s"]
                              else fmt.duration_text(row["due_in_s"]))
        return rows

    @Slot()
    def showDebug(self) -> None:
        self._set_view(DEBUG, -1)

    @Slot(bool)
    def runChecks(self, network: bool = True) -> None:
        if self._checkup is not None and self._checkup.isRunning():
            return
        self._set_notice("Checking", clear_after_s=60)
        self._checkup = Checkup(self._db, self._cfg, network, self)
        self._checkup.ready.connect(self._on_checks)
        self._launch(self._checkup)

    def _on_checks(self, checks: list) -> None:
        self._set_notice("")
        self._checks = [dict(check) for check in checks]
        self.checksChanged.emit()

    @Slot()
    def showRecommended(self) -> None:
        self._set_view(RECOMMENDED, -1)

    @Slot()
    def refreshRecommended(self) -> None:
        self._fetch_recommended(force=True)

    def _fetch_recommended(self, force: bool = False, start: int = 1,
                           append: bool = False) -> None:
        if self._recommended is not None and self._recommended.isRunning():
            return
        # An empty list is worth asking for whatever its age. Otherwise a run
        # that came back with nothing wedges the view until the age runs out.
        age = self._db.recommended_age_s()
        if (not force and age is not None and age < RECOMMENDED_TRUST_S
                and self._db.recommended_count()):
            return
        self._loading_more = append
        self._set_status("asking YouTube for more" if append
                         else "asking YouTube what it suggests")
        self._set_notice("Loading more" if append else "Asking YouTube what it suggests",
                         clear_after_s=90)
        self._recommended = RecommendationsFetcher(self._db, self._cfg, PAGE * 2, start,
                                                   append, parent=self)
        self._recommended.ready.connect(self._on_recommended)
        self._recommended.failed.connect(
            lambda message: self._set_status(f"recommendations, {message}"))
        self._launch(self._recommended)

    def _on_recommended(self, count: int) -> None:
        self._loading_more = False
        self._set_notice("")
        # Nothing new means the feed has been walked to its end for now.
        self._exhausted = count == 0 and self._db.recommended_count() > 0
        self._set_status(f"{self._db.recommended_count()} suggestions")
        if self._view_kind == RECOMMENDED:
            self.reload()

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
        self._launch(self._details)

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
        self._launch(self._poller)

    @Slot(str)
    def play(self, key: str) -> None:
        row = self._model.row_for_key(key)
        if not row:
            return
        login = key.split(":", 1)[1] if key.startswith("twitch:") else None
        # A Twitch entry is only ever a live channel for now, and a YouTube one
        # says so in the row. Either way mpv must not mark it watched.
        live = bool(row["isLive"]) or login is not None
        url = row["url"]
        if self._view_kind == PLAYLIST and self._view_playlist and not login:
            # Opened from a playlist, so the playlist is what is handed over,
            # starting on the video that was clicked. Otherwise the window
            # closes after one and the list is not a list.
            url = ids.playlist_watch_url(row["key"].split(":", 1)[1], self._view_playlist)
        if self._player.play(url, twitch_login=login, live=live):
            self._set_status(f"playing {row['title']}")
            # Handing a URL to mpv takes a few seconds, and until it reports
            # back there is nothing on screen to say anything happened.
            self._set_notice("Starting in mpv", clear_after_s=30)

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
        self._launch(self._home)

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
        self._launch(self._tracks)

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
        self._launch(self._search)

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
        """The headphone button on a video card.

        In a playlist the whole list is queued, starting on the video that was
        clicked, so listening to a playlist behaves like a playlist. Anywhere
        else it is the one video, since queueing a feed of several hundred is
        not what a headphone on one card means.
        """
        row = self._model.row_for_key(video_key) or {}
        if not self._audio or not row:
            return
        if self._view_kind == PLAYLIST:
            queue = [self._as_track(self._model.row_at(index))
                     for index in range(self._model.rowCount())]
            queue = [track for track in queue if track]
            start = next((i for i, track in enumerate(queue)
                          if track["key"] == video_key), 0)
            if queue:
                self._audio.play_items(queue, start=start)
                self._set_status(f"listening to this playlist from {row['title']}")
                return
        self._audio.play_items([self._as_track(row)])
        self._set_status(f"listening to {row['title']}")

    @staticmethod
    def _as_track(row) -> dict | None:
        if not row:
            return None
        return {
            "key": row["key"], "title": row["title"], "artist": row["channelTitle"],
            "thumbnail": row["thumbnail"], "live": bool(row["isLive"]),
            "url": row["url"],
        }

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
        self._launch(worker)

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
        # A stream has no comments and no likes to go and get, and the two
        # sources that would be asked are YouTube's.
        if self._detail_key.startswith("twitch:"):
            return
        row = self._video_for_detail(self._detail_key)
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
        self._launch(self._detail)

    def _on_votes(self, key: str, count: int) -> None:
        self._detail_dislikes = (key, count)
        if key == self._detail_key:
            self.detailChanged.emit()

    def _on_comments(self, key: str, threads: list, details: dict | None = None) -> None:
        if details:
            self._detail_extra = (key, dict(details))
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
        # mpv reports the file before its window is up, so the line stays a
        # moment longer rather than going as the screen is still empty.
        if self._notice:
            self._set_notice(self._notice, clear_after_s=3)
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
        self._launch(self._twitch)

    @Slot()
    def refreshLive(self) -> None:
        if self._live is not None and self._live.isRunning():
            return
        self._live = LiveWatcher(self._db, self._cfg, self)
        self._live.updated.connect(self._on_live)
        self._live.needsLogin.connect(self._on_twitch_needs_login)
        self._live.failed.connect(self._on_live_failed)
        # A check ends three ways and can also be cancelled on the way out,
        # and only one of those three carries results. Lowering the flag on
        # finished covers every one of them, so the bar cannot be left saying
        # it is working when nothing is.
        self._live.finished.connect(self._on_live_done,
                                    Qt.ConnectionType.QueuedConnection)
        if self._launch(self._live):
            self._set_live_checking(True)

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
        self._launch(self._importer)

    @Slot()
    def importHistory(self) -> None:
        self._fetch_history(force=True)

    def _fetch_history(self, force: bool = False, start: int = 1,
                       append: bool = False) -> None:
        if self._history is not None and self._history.isRunning():
            return
        age = self._db.cached_age_s(self._db.HISTORY)
        if (not force and age is not None and age < HISTORY_TRUST_S
                and self._db.cached_count(self._db.HISTORY)):
            return
        self._loading_more = append
        self._set_status("reading your YouTube history")
        self._set_notice("Loading more" if append else "Reading your history",
                         clear_after_s=120)
        self._history = HistoryImporter(self._db, self._cfg, PAGE * 2, start, append,
                                        parent=self)
        self._history.imported.connect(self._on_history)
        self._history.failed.connect(
            lambda message: self._set_status(f"history, {message}"))
        self._launch(self._history)

    def _on_history(self, added: int, marked: int) -> None:
        self._loading_more = False
        self._set_notice("")
        total = self._db.cached_count(self._db.HISTORY)
        self._exhausted = added == 0 and total > 0
        note = f"{total} in your history"
        if marked:
            note += f", {marked} of them stored here and now marked watched"
        self._set_status(note)
        if self._view_kind == HISTORY:
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
        self._launch(self._adder)
        return True

    def _launch(self, thread) -> bool:
        """Start a background thread, unless the application is going away.

        Cancelling the running threads is not enough on its own. A timer that
        was already due can fire after the shutdown has finished, start a
        fresh thread, and Qt then aborts the process when it destroys a live
        QThread. So starting is refused once shutdown has begun.

        Every worker is parented to this object so Qt owns its lifetime, and
        without the reaping below each one would then be kept until the window
        closed. A poll a minute and a live check every ninety seconds add up
        over an evening, so a finished worker is let go and the attribute that
        held it is cleared.
        """
        if self._stopping:
            return False
        self._threads.add(thread)
        thread.finished.connect(self._reap, Qt.ConnectionType.QueuedConnection)
        thread.start()
        return True

    @Slot()
    def _reap(self) -> None:
        """A worker has finished. Forget it everywhere and let Qt delete it.

        Runs on this object's thread through a queued connection, after the
        worker's own thread has stopped, which is the one moment a QThread
        may be deleted. Deleting it later rather than now is the idiom Qt
        documents for exactly this.
        """
        thread = self.sender()
        done = [thread] if thread is not None else [
            worker for worker in self._threads if worker.isFinished()]
        for worker in done:
            self._threads.discard(worker)
            for name, value in list(vars(self).items()):
                if value is worker:
                    setattr(self, name, None)
            if worker in self._source_details:
                self._source_details.remove(worker)
            worker.deleteLater()

    def shutdown(self, timeout_ms: int = 15000) -> None:
        """Stop every background thread before Qt tears them down.

        Qt treats destroying a running QThread as fatal and aborts the whole
        process, so closing the window during a refresh used to crash on exit.
        All threads are cancelled first and then waited on, so they stop in
        parallel rather than one after another. This runs after the window is
        already gone, so any short wait here is invisible.

        What is waited for is what was launched and has not been reaped, so a
        worker added later is covered by being started the same way every
        other one is.
        """
        self._stopping = True
        alive = list(self._threads)
        for thread in alive:
            thread.cancel()
        for thread in alive:
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
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

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
        self._live_checking = False
        self.liveChanged.emit()
        self.twitchChanged.emit()

    def _on_live_failed(self, message: str) -> None:
        self._set_live_checking(False)
        self._set_status(f"could not check Twitch, {message}")

    @Slot()
    def _on_live_done(self) -> None:
        """A check has stopped, whichever way it stopped.

        Delivered queued, so a check that started in the meantime would
        otherwise be cut short by the previous one ending. The sender is
        compared against the current worker for that reason.
        """
        worker = self.sender()
        if worker is not None and self._live is not None and self._live is not worker:
            return
        self._set_live_checking(False)

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
