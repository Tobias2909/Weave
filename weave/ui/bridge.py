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
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from .. import __version__
from .. import format as fmt
from .. import imagecache
from .. import palette, themes
from .. import ids
from .. import paths, tokens
from ..config import Config
from ..cookies import browser_spec
from ..db import GROUP_SHOWS, GROUP_SHOWS_ALL, GROUP_SHOWS_STREAMS, Database
from ..imagecache import SECONDS_PER_DAY, plain_source, qml_source
from ..sources import release as release_source
from ..sources import progress as mpv_progress
from ..player.mpv import Player
from ..poller import (
    ChannelAdder,
    ChannelAvatarsFetcher,
    ChannelDetailsFetcher,
    Checkup,
    DetailFetcher,
    FeedPoller,
    HistoryImporter,
    ChannelFeedFetcher,
    ChannelMembersFetcher,
    ChannelPlaylistsFetcher,
    ImageCacheJob,
    LiveWatcher,
    MusicHistoryReader,
    MusicHome,
    MusicSearch,
    LengthFiller,
    OwnerFetcher,
    PlaylistItemsFetcher,
    PlaylistsFetcher,
    RecommendationsFetcher,
    SearchFetcher,
    SourceDetails,
    SubsImporter,
    TrackList,
    TwitchLogin,
    UpdateCheck,
)
from .feed_model import FeedModel
from .navigation import History, MusicList, TrackCache

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
SETTINGS = "settings"

# How long a set of recommendations is worth showing before asking for another,
# and how long a playlist's contents are trusted before reading them again.
RECOMMENDED_TRUST_S = 6 * 3600
PLAYLIST_TRUST_S = 6 * 3600
# Shorter, because a history changes every time something is played.
HISTORY_TRUST_S = 30 * 60
# How long a set of search results is worth showing before asking again, and
# how long the words are kept at all. Searching for the same thing twice is
# something a person does all the time, and it used to cost a request every
# time; the second ask is now free for most of a day. Kept far longer than
# that so the page has something to draw at once while a fresh set arrives,
# and so a search repeated next week is one request rather than one per page
# scrolled. What is not repeated in a month goes.
SEARCH_TRUST_S = 20 * 3600
SEARCH_KEEP_S = 30 * 86400

# How many channels may be waiting for their details at once. A page fetch each
# against the same budget as everything else, so opening a group of a hundred
# channels asks for the first of them and not for all hundred.
DETAILS_WAITING = 25

# How many results one page of a YouTube search or one more helping of
# recommendations asks for. Small enough to arrive quickly, since scrolling to
# the bottom is what asks for it.
PAGE = 24

# How long the shelves are trusted before being gathered again. They are a
# recommendation, not a fact, and they cost several seconds to fetch.
SHELF_LIFETIME_S = 6 * 3600

# A search of YouTube Music is a track list like any other, so it is a place
# with the same shape as one. Its own kind, since it is not one of the fetches
# TrackList knows.
MUSIC_SEARCH = "search"
MUSIC_SEARCH_LABEL = "Search results"

# Said on a press that cannot go anywhere. One wording for both the card and
# the headphone, since it is the same address being refused for the same
# reason.
MEMBERS_NOTICE = "that one is for members of the channel"

# One shelf shown in full, which is where the tile at the end of a shelf goes.
# A place with the same shape as a track list, so the mouse buttons walk on and
# off it, but nothing is fetched for it. It is the shelf that is already held.
MUSIC_SHELF = "shelf"
# What the section of kept songs is called, in one place, because the
# arrangement of the sections is stored by title.
FAVORITES = "Favorites"

# Told apart from an explicit None, which is the shelves. A route into music
# that names no list means wherever music was left, which is what coming back
# to it did before a track list was a place of its own.
KEEP_MUSIC = object()


# How long an answer about the newest release is kept before asking again. A
# day, because a release is not published twice in an afternoon and the check
# is worth exactly one request.
UPDATE_INTERVAL_S = 24 * 60 * 60

# How recently a channel must have been asked for opening its page to ask
# again. The feed itself is cached for fifteen minutes on the other end, so
# anything shorter would spend a request to be told the same thing.
CHANNEL_FEED_TRUST_S = 15 * 60

# How long a channel's playlists tab is trusted. A day: a channel does not
# make a playlist every hour and reading the tab is a request.
CHANNEL_PLAYLISTS_TRUST_S = 24 * 60 * 60

# The pages of the walk through, counted from the welcome one, so the number
# reads as how far there is to go rather than as a page number.
WIZARD_LAST = 4


class Bridge(QObject):
    statusChanged = Signal()
    busyChanged = Signal()
    hideWatchedChanged = Signal()
    problemsChanged = Signal()
    emptyHintChanged = Signal()
    groupsChanged = Signal()
    playlistsChanged = Signal()
    playlistSkippedChanged = Signal()
    noticeChanged = Signal()
    searchEnded = Signal()
    # The words a search is being walked back onto, so the box can say what
    # the page on screen is answering. Sent after the view has moved, or the
    # box refilling itself would read as somebody typing them again.
    searchRestored = Signal(str)
    checksChanged = Signal()
    cacheChanged = Signal()
    startingChanged = Signal()
    updateChanged = Signal()
    wizardChanged = Signal()
    recommendedChanged = Signal()
    channelTabChanged = Signal()
    # Which half of a group is showing. Its own signal rather than
    # viewChanged, since pressing one of the three is not going anywhere.
    groupShowsChanged = Signal()
    playlistViewChanged = Signal()
    reportChanged = Signal()
    addChanged = Signal()
    importChanged = Signal()
    boxesChanged = Signal()
    viewChanged = Signal()
    liveChanged = Signal()
    twitchChanged = Signal()
    detailChanged = Signal()
    musicChanged = Signal()
    navChanged = Signal()
    favoritesChanged = Signal()
    themesChanged = Signal()

    def __init__(self, db: Database, cfg: Config, model: FeedModel,
                 player: Player, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._model = model
        self._player = player

        self._poller: FeedPoller | None = None
        self._adder: ChannelAdder | None = None
        # References waiting to be resolved, as (ref, group id), and the group
        # the running one belongs to. Resolving is one at a time by design, and
        # before this a second reference typed while the first was in flight
        # was simply refused, which is felt as the window ignoring a paste.
        # A group id below zero is a plain follow, which goes into All.
        self._add_queue: list[tuple[Any, int]] = []
        self._adding = -1
        self._importer: SubsImporter | None = None
        self._history: HistoryImporter | None = None
        self._recommended: RecommendationsFetcher | None = None
        self._avatars: ChannelAvatarsFetcher | None = None
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
        # Channels whose details are wanted and whose turn has not come, as
        # (key, ext id). A group can hold more channels than anyone would want
        # fetched at once, so the list is capped.
        self._details_queue: list[tuple[str, str]] = []
        self._live: LiveWatcher | None = None
        # Raised while a live check is in flight.
        self._live_checking = False
        # Nothing is shown in the live bar until the first check has answered.
        # Twitch takes a few seconds while YouTube is there at once, and a bar
        # that appears and then grows again a moment later looks broken.
        self._live_ready = False
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
        # The station a pressed song built. Its own worker, so asking to hear
        # a song and asking to look at a list never wait on each other.
        self._station: TrackList | None = None
        self._source_details: list = []
        self._results_label = ""
        # Which track list the music view is showing, None being the shelves.
        # Kept while another view is up, since the results are kept too, so
        # coming back to music lands where it was left.
        self._music_list: MusicList | None = None
        # The lists that were visited, so walking back onto one puts it back
        # instead of asking YouTube Music again.
        self._music_cache = TrackCache()

        self._busy = False
        self._problems: list[str] = []
        # Where the last report went, so the page can offer to open it.
        self._report_path = ""
        # The one that asks who made a video nothing here knows the owner of.
        self._owners = None
        self._lengths = None
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
        self._cache_job: ImageCacheJob | None = None
        self._channel_feed: ChannelFeedFetcher | None = None
        self._channel_lists: ChannelPlaylistsFetcher | None = None
        self._channel_members: ChannelMembersFetcher | None = None
        # Which half of a channel page is showing. Not part of the view, since
        # walking back and forth between the two is not walking anywhere.
        self._channel_tab = "videos"
        # What was last handed to mpv, so the thing that was pressed can say
        # so itself. Cleared when mpv reports back, on a failure, and by a
        # timer, because a chip that never leaves is worse than none.
        self._starting_key = ""
        # A newer release than this one, remembered from the last time the
        # question was asked so the foot of the panel can say so before any
        # request is made.
        self._update_tag = self._db.get_state("update_tag") or ""
        self._update_address = self._db.get_state("update_address") or ""
        self._update: UpdateCheck | None = None
        # The pages a fresh install is walked through, and how the import on
        # one of them is going, since that is the step that fails and the page
        # has to be able to say why.
        self._wizard_open = False
        self._wizard_step = 0
        self._import_state = ""
        self._import_message = ""
        # How the last attempt at adding a channel went. The status line says
        # so too, but it is one truncated line in a corner of the toolbar, and
        # the window that manages a group is modal over it, so what happened
        # to something typed in there was invisible.
        self._add_state = ""
        self._add_message = ""
        self._starting_timer = QTimer(self)
        self._starting_timer.setSingleShot(True)
        self._starting_timer.timeout.connect(lambda: self._set_starting(""))
        # What the last measurement found, so lowering the ceiling knows
        # whether anything actually has to be dropped.
        self._cache_held = 0
        # What the picture cache holds, as the line the settings page shows.
        # Empty until it has been measured, because walking the whole cache
        # directory is not free and nothing else needs the answer.
        self._cache_line = ""
        self._cache_working = False
        self._loading_more = False
        self._exhausted = False
        # Where a search started, so emptying the box goes back there.
        self._before_search: tuple[str, int, str, str] = (ALL, -1, "", "")
        # The history view shows what YouTube says was watched, or what has
        # been listened to. One view, two lists, since they answer the same
        # question about two kinds of thing.
        self._history_music = False
        # The order the kept songs are shown in, shuffled once so the tiles
        # stay where they are between reads.
        self._favorites_order: list[str] = []
        self._theme = None
        self._music_history: MusicHistoryReader | None = None
        # Every view landed on, walked by the back and forward mouse buttons.
        # Seeded with the view the window opens on, so the first step back has
        # somewhere to land rather than one fewer place than was visited.
        self._nav = History((self._view_kind, self._view_id, self._view_channel,
                             self._view_playlist, self._music_list))
        # Raised while a remembered view is being restored. Without it the
        # replay would record itself as a fresh step and forward would never
        # be reachable. An explicit flag rather than comparing the view being
        # set against the one the record points at, since those are equal in
        # ordinary use as well.
        self._nav_replaying = False

        self._hide_watched = self._db.get_state("hide_watched", "1") == "1"
        self._live_collapsed = self._db.get_state("live_collapsed", "0") == "1"
        self._panel_width = self._db.get_int("panel_width", 380)

        self._player.watched.connect(self._on_watched)
        self._player.nowPlaying.connect(self._on_now_playing)
        self._player.stopped.connect(self._on_player_stopped)
        self._player.failed.connect(self._on_player_failed)
        if self._player.error:
            self._problems.append(self._player.error)

        # A stream watched live is judged once it has ended, so the answer
        # arrives on the pass after the one that read its length.
        self._judge_finished_streams()
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
        # Counted over the channels in All rather than every channel
        # followed. One kept for a group alone is followed, and is counted as
        # such on the settings page, but it is not part of this row.
        rows = [{"id": -1, "name": "All",
                 "members": len(self._db.channels(in_all_only=True)),
                 "unwatched": self._db.unwatched_total()}]
        rows.extend(self._db.groups())
        return rows

    def _get_boxes(self) -> list:
        return self._db.boxes()

    def _get_playlists(self) -> list:
        return self._db.playlists()

    def _get_kept_playlists(self) -> list:
        """The ones kept off a channel page, which are somebody else's and are
        listed apart from your own for that reason."""
        return self._db.playlists(origin="channel")

    def _get_playlist_view(self) -> dict:
        """What the bar above a playlist has to say, when one is showing that
        came off a channel page.

        Empty for your own playlists, which were not opened from anywhere and
        need no way back."""
        if self._view_kind != PLAYLIST or not self._view_playlist:
            return {}
        found = self._db.playlist_source(self._view_playlist)
        if not found:
            return {}
        return {
            "ext_id": found["ext_id"],
            "title": found["title"],
            "kept": found["origin"] == "channel",
            "channel_key": found["channel_key"],
            "channel_title": found["channel_title"],
        }

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
            # Nothing stored means no button. A channel that has never
            # streamed must not offer a half with nothing on it, and a tab
            # that answers at all often answers with nothing.
            "streams": self._db.channel_stream_count(self._view_channel) if found else 0,
            # The button is a toggle, and the half it fills only exists once
            # something is in it. A channel nobody has pressed it on has no
            # half, and neither has one whose tab answered with nothing.
            "membersWanted": bool(found.get("members_wanted")),
            "members": self._db.channel_members_count(self._view_channel) if found else 0,
            # Whether the tab has ever answered. A channel that sells nothing
            # stops offering the button rather than offering one that can only
            # say so again.
            "sellsMembership": found.get("members") is None or bool(found.get("members")),
        }

    def _get_playlist_skipped_text(self) -> str:
        """A private or a deleted entry is left off the grid rather than shown
        as a broken card, since there is nothing behind either one to play.
        Said once here instead, for the foot of the list, pre-formatted since
        the QML side never builds sentences of its own."""
        if self._view_kind != PLAYLIST or not self._view_playlist:
            return ""
        count = int((self._db.playlist(self._view_playlist) or {}).get("skipped") or 0)
        if count <= 0:
            return ""
        if count == 1:
            return "1 video in this playlist is private or has been deleted, and is left out."
        return (f"{count} videos in this playlist are private or have been deleted, "
                "and are left out.")

    def _get_empty_hint(self) -> str:
        """What to say when the grid is empty. There are several different
        reasons for that and they need different answers."""
        if self._view_kind == PLAYLIST:
            return "This playlist is empty."
        if self._view_kind == RECOMMENDED:
            return "Nothing suggested yet.\nPress Fresh recommendations above."
        if self._view_kind == SEARCH and self._search_scope == "youtube":
            return f"YouTube found nothing for {self._search_text}."
        if self._view_kind == SEARCH:
            return (f"Nothing stored matches {self._search_text}.\n"
                    "Press Enter to search YouTube itself.")
        if self._view_kind == HISTORY:
            return "Nothing in your YouTube history yet."
        if self._view_kind == BOX:
            return ("This box is empty.\nRight click any video and put it in here.")
        if self._view_kind == CHANNEL and self._channel_tab == "members":
            # This half only exists once something has been read into it, so
            # an empty one means the button was switched off and everything
            # read before was watched or hidden rather than nothing being here.
            return "Nothing here from this channel's members tab."
        if self._view_kind == CHANNEL:
            return "No videos stored for this channel yet.\nPress Refresh."
        counts = self._db.counts()
        if not counts["channels"]:
            return ("Nothing here yet.\nFollow a channel with the plus beside Channels, "
                    "then press Refresh.")
        if self._view_kind == GROUP:
            shows = self._db.group_shows(self._view_id)
            if shows != GROUP_SHOWS_ALL:
                # Reading half of a group that does have rows in the other
                # half. Saying it has no channels would be a lie, and the way
                # out is the row of buttons above rather than managing it.
                found = next((row for row in self._db.groups()
                              if row["id"] == self._view_id), None)
                if found and found["members"]:
                    what = ("streams" if shows == GROUP_SHOWS_STREAMS else "videos")
                    return (f"No {what} in this group.\n"
                            "Press All above to see everything in it.")
            return ("This group has no channels in it yet.\n"
                    "Right click the group and manage it, or right click a video.")
        if not len(self._db.channels(platform="youtube")):
            return ("Only Twitch channels are followed so far.\n"
                    "A Twitch channel shows in the live bar while it streams and "
                    "puts no rows here.\nFollow a YouTube channel to fill the feed.")
        if not counts["videos"]:
            return "No videos stored yet.\nPress Refresh to fetch them."
        return "Everything here is watched.\nTurn off Hide watched to see it again."

    def _get_cache_text(self) -> str:
        """What the picture cache holds, in the words the cache subcommand
        prints, since both are reading the same two numbers."""
        if not self._cache_line:
            return "Measuring" if self._cache_working else ""
        return self._cache_line

    def _get_cookie_source(self) -> str:
        """Where yt-dlp is told to look for cookies. The checks answer this
        from the same call, so the two cannot disagree."""
        return browser_spec(self._cfg)

    def _get_music_identity(self) -> str:
        """Which YouTube identity the music requests speak as.

        What the config decides, not what the page says. Reading it off the
        page is a request, and this is a line of text on a page that is only
        being looked at.
        """
        pinned = self._cfg.music_identity
        if pinned and pinned != "auto":
            return f"{pinned}, pinned in the config"
        return "read from the music page"

    def _get_twitch_connected(self) -> bool:
        return tokens.load() is not None

    status = Property(str, _get_status, notify=statusChanged)
    busy = Property(bool, _get_busy, notify=busyChanged)
    hideWatched = Property(bool, _get_hide_watched, notify=hideWatchedChanged)
    problems = Property("QVariantList", _get_problems, notify=problemsChanged)
    emptyHint = Property(str, _get_empty_hint, notify=emptyHintChanged)
    playlistSkippedText = Property(str, _get_playlist_skipped_text,
                                   notify=playlistSkippedChanged)
    groups = Property("QVariantList", _get_groups, notify=groupsChanged)
    boxes = Property("QVariantList", _get_boxes, notify=boxesChanged)
    notice = Property(str, lambda self: self._notice, notify=noticeChanged)
    checks = Property("QVariantList", lambda self: list(self._checks), notify=checksChanged)
    cacheText = Property(str, _get_cache_text, notify=cacheChanged)
    cacheWorking = Property(bool, lambda self: self._cache_working, notify=cacheChanged)
    startingKey = Property(str, lambda self: self._starting_key, notify=startingChanged)
    updateVersion = Property(str, lambda self: self._newer_version(), notify=updateChanged)
    # What is running, for the line that says a newer one exists.
    version = Property(str, lambda _self: __version__, constant=True)
    # The newest release the check has heard of, whether or not it is above
    # this one, so the settings page can state it either way.
    latestVersion = Property(str, lambda self: release_source.numbers_text(self._update_tag),
                             notify=updateChanged)
    hasRelease = Property(bool, lambda self: bool(self._update_address), notify=updateChanged)
    wizardOpen = Property(bool, lambda self: self._wizard_open, notify=wizardChanged)
    wizardStep = Property(int, lambda self: self._wizard_step, notify=wizardChanged)
    wizardHidden = Property(bool, lambda self: self._db.get_state("wizard_hidden") == "1",
                            notify=wizardChanged)
    # "" before anything was asked, then working, done or failed.
    importState = Property(str, lambda self: self._import_state, notify=importChanged)
    # "" before anything was asked, then working, added or failed.
    addState = Property(str, lambda self: self._add_state, notify=addChanged)
    addMessage = Property(str, lambda self: self._add_message, notify=addChanged)
    importMessage = Property(str, lambda self: self._import_message, notify=importChanged)
    recommendedText = Property(str, lambda self: self._recommended_line(),
                               notify=recommendedChanged)
    cacheCeiling = Property(int, lambda self: self._ceiling_mb(), notify=cacheChanged)
    cacheCeilingText = Property(str, lambda self: imagecache.ceiling_label(self._ceiling_mb()),
                                notify=cacheChanged)
    cacheChoices = Property("QVariantList", lambda _self: [
        {"megabytes": step, "label": imagecache.ceiling_label(step)}
        for step in imagecache.CEILING_STEPS_MB], notify=cacheChanged)
    schedule = Property("QVariantList", lambda self: self._get_schedule(),
                        notify=checksChanged)
    playlists = Property("QVariantList", _get_playlists, notify=playlistsChanged)
    keptPlaylists = Property("QVariantList", _get_kept_playlists, notify=playlistsChanged)
    playlistView = Property("QVariantMap", _get_playlist_view, notify=playlistViewChanged)
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
    twitchConnected = Property(bool, _get_twitch_connected, notify=twitchChanged)
    # The config is read once at startup, so neither of these can change while
    # the window is open.
    cookieSource = Property(str, _get_cookie_source, constant=True)
    musicIdentity = Property(str, _get_music_identity, constant=True)

    def _get_live_collapsed(self) -> bool:
        return self._live_collapsed

    def _get_live_checking(self) -> bool:
        return self._live_checking

    liveCollapsed = Property(bool, _get_live_collapsed, notify=liveChanged)
    liveChecking = Property(bool, _get_live_checking, notify=liveChanged)

    def _get_live_ready(self) -> bool:
        return self._live_ready

    liveReady = Property(bool, _get_live_ready, notify=liveChanged)

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
            "isUpcoming": row["live_status"] == "is_upcoming",
            # The panel is where somebody deciding whether to be there looks,
            # so it says the hour rather than how long there is to wait.
            "startsText": fmt.start_time_text(self._extra(row, "scheduled_at")),
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
        favorites = self._favorites_shelf()
        if favorites["items"]:
            shelves.insert(0, favorites)
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

    def _favorites_shelf(self) -> dict:
        """The songs kept on purpose, in a shuffled order.

        Shuffled once and remembered, not on every read. The section is read
        again whenever anything about music changes, so shuffling per read
        would make the tiles swap places under the pointer. The whole list is
        handed over and the window shows two rows of it, so what is on those
        two rows is a sample of everything kept rather than the newest few.
        """
        rows = {row["ext_id"]: row for row in self._db.music_favorites()}
        if not rows:
            self._favorites_order = []
            return {"title": FAVORITES, "kind": "favorites", "items": []}
        kept = [ext_id for ext_id in self._favorites_order if ext_id in rows]
        fresh = [ext_id for ext_id in rows if ext_id not in set(kept)]
        if fresh:
            # Newly kept songs join the order rather than resettling all of
            # it, so keeping one does not rearrange what is on screen.
            random.shuffle(fresh)
            kept = fresh + kept
        self._favorites_order = kept
        return {"title": FAVORITES, "kind": "favorites", "items": [{
            "title": rows[ext_id]["title"],
            "subtitle": rows[ext_id]["channel_title"] or "",
            "videoId": ext_id,
            "playlistId": "",
            "thumbnail": qml_source(rows[ext_id]["thumbnail_url"]),
        } for ext_id in kept]}

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

    def _get_shelf_page(self) -> dict:
        """The shelf being shown in full, or an empty one when none is.

        Found by name rather than kept as a copy, so a shelf that was refreshed
        while it was open shows what arrived rather than what was pressed. Its
        place in the arranged list travels with it, since that is what a tile
        inside it is played by.
        """
        open_on = self._music_list
        if self._view_kind != MUSIC or open_on is None or open_on.what != MUSIC_SHELF:
            return {}
        for index, shelf in enumerate(self._get_shelves()):
            if shelf["title"] == open_on.ident:
                return {"title": shelf["title"], "kind": shelf.get("kind", ""),
                        "index": index, "items": shelf["items"]}
        return {}

    def _get_results_label(self) -> str:
        return self._results_label

    musicShelves = Property("QVariantList", _get_shelves, notify=musicChanged)
    musicShelfPage = Property("QVariantMap", _get_shelf_page, notify=musicChanged)
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
        # Fired unconditionally, not only from the playlist branch below, so
        # the foot of the list clears the moment the view moves on rather than
        # keeping a stale count from whichever playlist was open before.
        self.playlistSkippedChanged.emit()
        # A channel page and a box both ignore the hide watched toggle. The
        # channel page is meant to show everything that channel has, and a box
        # was hand picked, so hiding half of it would be surprising.
        if self._view_kind in (MUSIC, DEBUG, SETTINGS):
            # These draw their own page and the grid is hidden behind them, so
            # the rows in it are nobody's business. Emptying it cost a query
            # that could only answer nothing, and a walk along the sidebar
            # emptied and refilled it once per row, throwing away rows the
            # grid was still building each time.
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
        if self._view_kind == HISTORY and self._history_music:
            self._model.show(self._db.music_history())
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
        # A channel's videos and its streams are two halves of one page, so
        # each half asks for its own rows. Nowhere else says anything here: a
        # stream of a channel you follow belongs in what you follow.
        streams = None
        if self._view_kind == CHANNEL and self._channel_tab in ("videos", "streams"):
            streams = self._channel_tab == "streams"
        # A group is read the same way, from what that group was last told to
        # show. A feed or a box still says nothing here and holds both: a
        # stream of a channel you follow belongs in what you follow.
        if self._view_kind == GROUP:
            shows = self._db.group_shows(self._view_id)
            if shows != GROUP_SHOWS_ALL:
                streams = shows == GROUP_SHOWS_STREAMS
        # The members half is asked for by name. Everywhere else leaves those
        # rows out, since for almost every channel they cannot be opened.
        members = self._view_kind == CHANNEL and self._channel_tab == "members"
        self._model.reload(
            hide_watched=self._hide_watched and honour_toggle,
            group_id=self._view_id if self._view_kind == GROUP else None,
            box_id=self._view_id if self._view_kind == BOX else None,
            channel_key=self._view_channel if self._view_kind == CHANNEL else None,
            query=self._search_text if self._view_kind == SEARCH else None,
            streams=streams,
            members=members,
        )
        self.emptyHintChanged.emit()
        self.groupsChanged.emit()
        self.boxesChanged.emit()

    def _set_starting(self, key: str, clear_after_s: float = 30.0) -> None:
        """Say which item is on its way to mpv.

        Handing a URL over takes a few seconds, and until mpv has a window
        there is nothing on screen to say the press landed. It is said on the
        thing that was pressed rather than in a corner, so the answer is where
        the eye already is.
        """
        self._starting_timer.stop()
        if self._starting_key != key:
            self._starting_key = key
            self.startingChanged.emit()
        if key and clear_after_s > 0:
            self._starting_timer.start(int(clear_after_s * 1000))

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
                  playlist_id: str = "", music=KEEP_MUSIC) -> None:
        # Only music has a place inside it. A route in that names no list
        # means wherever music was left, so reaching it from the sidebar shows
        # the list that was open rather than throwing it away.
        if kind != MUSIC:
            music = None
        elif music is KEEP_MUSIC:
            music = self._music_list
        showing = self._music_list if self._view_kind == MUSIC else None
        if (kind, view_id, channel_key, playlist_id, music) == (
                self._view_kind, self._view_id, self._view_channel,
                self._view_playlist, showing):
            return
        left_search = self._view_kind == SEARCH and kind != SEARCH
        self._view_kind = kind
        self._view_id = view_id
        self._view_channel = channel_key
        self._view_playlist = playlist_id
        if kind == MUSIC:
            self._music_list = music
        # Below the guard above, which returns before this on a view that is
        # already showing, so setting the same view twice is one entry rather
        # than two. The words come along for a search only, and only as
        # something to restore, never as part of what makes a view itself.
        if not self._nav_replaying and self._nav.record(
                (kind, view_id, channel_key, playlist_id, music),
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
        # Which half of a group is showing belongs to the group, so arriving
        # on a different one is the moment the row of buttons is wrong.
        self.groupShowsChanged.emit()
        # The line above the suggestions is about that page, and arriving on it
        # is one of the two moments it can be wrong.
        self.recommendedChanged.emit()
        # The bar above a playlist is about which playlist, so it is wrong the
        # moment the view moves and right again here.
        self.playlistViewChanged.emit()
        self.reload()
        # Work a view needs on entry happens here, so every way of reaching it
        # behaves the same. It used to hang off the sidebar row, and the wheel
        # then landed on an empty page.
        if kind == MUSIC:
            if not self._shelves:
                self.loadHome()
            self._show_music_list(music)
        if kind == DEBUG and not self._checks:
            self.runChecks(True)
        if kind == SETTINGS and not self._cache_line:
            self.measureCache()
        if kind == RECOMMENDED:
            self._exhausted = False
            self._fetch_recommended()
        if kind == HISTORY:
            self._exhausted = False
            if self._history_music:
                self._read_music_history()
            else:
                self._fetch_history()
        if kind == PLAYLIST:
            self._fetch_playlist_items(playlist_id)

    def _name_of_view(self, view) -> str:
        """What to call a view in a sentence, from the record of it.

        Read from the history rather than written next to each button, since a
        label that names a fixed parent goes wrong the moment a view gains a
        second way in, which is exactly what happened with the music page.
        """
        kind, view_id, channel_key, playlist_id, _music = view
        if kind == GROUP:
            found = next((g for g in self._db.groups() if g["id"] == view_id), None)
            return found["name"] if found else "the group"
        if kind == BOX:
            found = next((box for box in self._db.boxes() if box["id"] == view_id), None)
            return found["name"] if found else "the box"
        if kind == PLAYLIST:
            found = self._db.playlist(playlist_id) if playlist_id else None
            return found["title"] if found else "the playlist"
        if kind == CHANNEL:
            found = self._db.channel(channel_key) if channel_key else None
            return (found["title"] if found and found["title"] else "the channel")
        return {
            ALL: "the feed", MUSIC: "music", HISTORY: "history",
            RECOMMENDED: "suggestions", SEARCH: "the search",
            SETTINGS: "settings", DEBUG: "how things are",
        }.get(kind, "the feed")

    def _get_back_label(self) -> str:
        """What the back button in a view should call itself."""
        entry = self._nav.previous()
        if entry is None:
            return ""
        return f"Back to {self._name_of_view(entry.view)}"

    backLabel = Property(str, _get_back_label, notify=navChanged)

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
                self._restore_kept_search()
            self._set_view(*entry.view)
        finally:
            self._nav_replaying = False
        if entry.view[0] == SEARCH:
            # After the view has moved, so the box refilling itself lands on a
            # search that is already showing and is dropped by the guard in
            # search() rather than starting one.
            self.searchRestored.emit(self._search_text)
        self.navChanged.emit()

    def _restore_kept_search(self) -> None:
        """Put back what a search was showing, for a walk back onto it.

        The words alone would search only what is stored here, and something
        that was looked for on YouTube was looked for there because it is not
        in the feed, so that answers nothing: an empty page under an empty
        box, which is what walking back onto a search used to be. What YouTube
        answered is kept per set of words, so the same rows are drawn again
        and nothing is asked.

        A set that has aged past its trust window is still drawn. This is a
        walk back onto a page that was on screen a moment ago, not a fresh
        search, so putting the page back is the whole job and pressing return
        is how somebody asks for newer.
        """
        self._web_results = []
        self._search_scope = "stored"
        self._exhausted = False
        if not self._search_text:
            return
        kind = self._db.search_kind(self._search_text)
        stored = self._db.cached_flat(kind)
        if not stored:
            # Never asked of YouTube, or dropped since. What is stored here
            # still answers, which is what typing the words gives.
            return
        age = self._db.cached_age_s(kind)
        self._search_scope = "youtube"
        # The same call a fresh page goes through, so a restored set and a new
        # one cannot draw differently.
        self._web_results = self._db.decorate(stored)
        self._set_status(f"{len(self._web_results)} results from YouTube, read "
                         f"{fmt.age_text(int(time.time()) - (age or 0))}")

    def _sidebar_playlists(self) -> list[dict]:
        """Both playlist lists as one, in the order the sidebar draws them.

        The wheel walks positions rather than ids, since the ids are long
        strings and the walk is about order, so the ones kept off a channel
        page have to be counted here or the wheel stops at the last of yours
        and never reaches them.
        """
        return self._db.playlists() + self._db.playlists(origin="channel")

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
        entries.append((SETTINGS, -1))
        entries.extend((BOX, int(row["id"])) for row in self._db.boxes())
        entries.extend((PLAYLIST, index) for index, _ in enumerate(self._sidebar_playlists()))
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
            found = [row["ext_id"] for row in self._sidebar_playlists()]
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
            found = self._sidebar_playlists()
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
        if self._view_kind == SEARCH and text == self._search_text:
            # The box saying what the page already answers, which is what a
            # walk back onto a search does to it. Going on would throw away
            # the results that were just put back.
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
        """Search YouTube itself, for something that was never in the feed.

        The same words asked twice cost one request, not two. What one page
        answered is kept, so a search repeated within SEARCH_TRUST_S is drawn
        from here and nothing is asked at all, and an older one is drawn at
        once anyway while a fresh set is on its way.
        """
        if not self._search_text:
            return
        self._search_scope = "youtube"
        self._web_results = []
        self._exhausted = False
        if self._view_kind != SEARCH:
            self._set_view(SEARCH, -1)
        kind = self._db.search_kind(self._search_text)
        # Shaped exactly as a fresh page is, by the same call, so a set from
        # here and a set from YouTube cannot look different.
        stored = self._db.cached_flat(kind)
        age = self._db.cached_age_s(kind)
        if stored:
            self._web_results = self._db.decorate(stored)
            self._set_status(f"{len(self._web_results)} results from YouTube, read "
                             f"{fmt.age_text(int(time.time()) - (age or 0))}")
            self.reload()
        self.viewChanged.emit()
        if stored and age is not None and age < SEARCH_TRUST_S:
            return
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
        flat = [dict(row) for row in rows]
        kind = self._db.search_kind(query)
        if start <= 1:
            self._db.replace_cached(kind, flat)
            # Swept here rather than at startup: a search is the only thing
            # that adds one of these, so it is also the right moment to drop
            # the ones nobody has repeated in a month.
            self._db.forget_old_searches(SEARCH_KEEP_S)
        else:
            self._db.append_cached(kind, flat)
        found = self._db.decorate(flat)
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

    def _get_history_music(self) -> bool:
        return self._history_music

    historyShowsMusic = Property(bool, _get_history_music, notify=viewChanged)

    @Slot(bool)
    def showMusicInHistory(self, music: bool) -> None:
        """Switch the history between what was watched and what was heard."""
        if music == self._history_music:
            return
        self._history_music = music
        if music:
            self._read_music_history()
        self.reload()
        self.viewChanged.emit()

    @Slot()
    def readMusicHistory(self) -> None:
        """Ask the music service again, from the button beside Refresh."""
        self._read_music_history()

    def _read_music_history(self) -> None:
        """Ask the music service what it remembers, behind what is on screen.

        What Weave played is already stored as it played, so the view has
        something to draw at once and this only fills in the older listening.
        """
        if self._music_history is not None and self._music_history.isRunning():
            return
        self._music_history = MusicHistoryReader(self._db, self._cfg, self)
        self._music_history.ready.connect(self._on_music_history)
        self._music_history.failed.connect(
            lambda message: self._set_status(f"music history, {message}"))
        self._launch(self._music_history)

    def _on_music_history(self, count: int) -> None:
        self._set_status(f"{count} songs from your listening history")
        if self._view_kind == HISTORY and self._history_music:
            self.reload()

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
    def setPlaylistMusic(self, playlist_id: str, music: bool) -> None:
        """Say that a playlist holds music, or stop saying it.

        The list itself does not change. All it decides is that a press on one
        of its videos reaches the music player instead of mpv.
        """
        self._db.set_playlist_music(playlist_id, music)
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
        # A playlist opened off a channel page a day ago and never kept has
        # been read once and is not coming back. Its row exists only so its
        # videos had somewhere to live, and this is the moment to sweep those
        # up, since the list of playlists is being rebuilt anyway.
        self._db.sweep_temporary_playlists()
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

    @Slot()
    def showSettings(self) -> None:
        self._set_view(SETTINGS, -1)

    @Slot()
    def measureCache(self) -> None:
        """How much room the pictures take. Asked for on the way into the
        settings page, and again after anything has been dropped."""
        self._run_cache_job(ImageCacheJob.MEASURE)

    @Slot()
    def pruneImageCache(self) -> None:
        """Drop what has aged out and whatever has spilled over the ceiling,
        which is what a launch does and what the cache subcommand prunes."""
        self._run_cache_job(ImageCacheJob.PRUNE)

    @Slot()
    def clearImageCache(self) -> None:
        """Drop the lot. Every picture is fetched again the next time it is
        looked at, so this costs time rather than anything else."""
        self._run_cache_job(ImageCacheJob.CLEAR)

    def _recommended_line(self) -> str:
        """When the suggestions were last read, for the row above them.

        A page of cards with a button over it and nothing else says nothing
        about why they are what they are. Their age is the answer to that, and
        it is also the answer to whether pressing the button is worth a
        request.
        """
        age = self._db.recommended_age_s()
        count = self._db.recommended_count()
        if age is None or not count:
            return "Nothing read yet"
        return f"Read {fmt.age_text(int(time.time()) - age)} · {count} suggestions"

    def _newer_version(self) -> str:
        """The version worth telling him about, or nothing.

        Compared here rather than when the answer arrives, so a release that
        was newer once stops being announced the moment a copy of it is
        running, with no second request and nothing to clear by hand.
        """
        if release_source.is_newer(self._update_tag, __version__):
            return release_source.numbers_text(self._update_tag)
        return ""

    @Slot()
    def checkForUpdate(self) -> None:
        """Ask once a day whether there is a newer release.

        One request to the repository, no account and nothing sent but the
        request. Held to a day by a stamp in the database rather than by the
        process, or restarting the program would ask every time.
        """
        if self._update is not None and self._update.isRunning():
            return
        asked = self._db.get_int("update_checked_at", 0)
        if time.time() - asked < UPDATE_INTERVAL_S:
            return
        self._update = UpdateCheck(self._cfg, self)
        self._update.found.connect(self._on_update_found)
        self._launch(self._update)

    def _on_update_found(self, tag: str, address: str) -> None:
        self._update_tag = tag
        self._update_address = address
        self._db.set_state("update_tag", tag)
        self._db.set_state("update_address", address)
        self._db.set_state("update_checked_at", str(int(time.time())))
        self.updateChanged.emit()

    @Slot()
    def openRelease(self) -> None:
        """The release page, in the browser. Nothing is downloaded here."""
        if self._update_address:
            QDesktopServices.openUrl(QUrl(self._update_address))

    # ---- the pages a fresh install is walked through ---------------------

    def _wizard_is_needed(self) -> bool:
        """Whether there is anything left for those pages to offer.

        Two ways out of them. The box, which is the reader's own answer to
        never seeing them again, and simply being set up, since a copy that already
        has channels and a Twitch connection has nothing to be walked through
        and being asked every launch would be nagging.
        """
        if self._db.get_state("wizard_hidden") == "1":
            return False
        return not (self._db.channels() and self._get_twitch_connected())

    @Slot()
    def showWizardIfNeeded(self) -> None:
        if self._wizard_is_needed():
            self.openWizard()

    @Slot()
    def openWizard(self) -> None:
        self._wizard_step = 0
        self._wizard_open = True
        self.wizardChanged.emit()

    @Slot()
    def closeWizard(self) -> None:
        self._wizard_open = False
        self.wizardChanged.emit()

    @Slot(int)
    def stepWizard(self, by: int) -> None:
        self._wizard_step = max(0, min(WIZARD_LAST, self._wizard_step + by))
        self.wizardChanged.emit()

    @Slot(bool)
    def setWizardHidden(self, hidden: bool) -> None:
        self._db.set_state("wizard_hidden", "1" if hidden else "0")
        self.wizardChanged.emit()

    def _ceiling_mb(self) -> int:
        """The ceiling in force. The config holds the default and the choice
        made here overrides it."""
        return self._db.image_max_mb(self._cfg.image_max_mb)

    @Slot(int)
    def setCacheCeiling(self, megabytes: int) -> None:
        """Choose how much room the pictures may take.

        Lowering it drops the oldest at once rather than waiting for the next
        launch, since the point of choosing a smaller number is usually that
        the room is wanted now. Raising it deletes nothing and only measures,
        so the line under the buttons is right either way.
        """
        megabytes = int(megabytes)
        if megabytes not in imagecache.CEILING_STEPS_MB or megabytes == self._ceiling_mb():
            return
        held = self._cache_held
        self._db.set_image_max_mb(megabytes)
        self.cacheChanged.emit()
        self._run_cache_job(ImageCacheJob.PRUNE if held > megabytes * 1024 * 1024
                            else ImageCacheJob.MEASURE)

    def _run_cache_job(self, what: str) -> None:
        if self._cache_job is not None and self._cache_job.isRunning():
            return
        self._cache_working = True
        self.cacheChanged.emit()
        self._cache_job = ImageCacheJob(paths.IMAGE_CACHE, what,
                                        self._cfg.image_days * SECONDS_PER_DAY,
                                        self._ceiling_mb() * 1024 * 1024, self)
        self._cache_job.done.connect(self._on_cache_job)
        if not self._launch(self._cache_job):
            self._cache_working = False
            self.cacheChanged.emit()

    def _on_cache_job(self, what: str, held: int, dropped: int) -> None:
        self._cache_working = False
        self._cache_held = held
        self._cache_line = (f"{held / 1024 / 1024:.1f} MB of a "
                            f"{imagecache.ceiling_label(self._ceiling_mb())} "
                            f"ceiling, kept for {self._cfg.image_days} days")
        self.cacheChanged.emit()
        if what != ImageCacheJob.MEASURE:
            self._set_status(f"{dropped} pictures dropped from the cache")

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
    def exportReport(self) -> None:
        """Write everything this page knows to one file, to be sent on.

        The page answers what is wrong on the machine it is running on. This
        is the same answers in something that can be attached to a message,
        for a problem somebody else has to look at. It carries no channel
        names, no video titles and nothing secret.
        """
        from .. import report as report_bundle
        self._set_notice("Writing the report", clear_after_s=30)
        try:
            path = report_bundle.write(self._db, self._cfg, network=False,
                                       problems=list(self._problems))
        except Exception as exc:
            self._set_notice("")
            self._set_status(f"the report could not be written, {type(exc).__name__}: {exc}")
            return
        self._set_notice("")
        self._report_path = str(path)
        self.reportChanged.emit()
        self._set_status(f"report written to {path}")

    reportPath = Property(str, lambda self: self._report_path, notify=reportChanged)

    @Slot()
    def showReport(self) -> None:
        """Open the folder the last report went to, so it can be attached to
        something without hunting for it."""
        if self._report_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._report_path).parent)))

    @Slot()
    def showRecommended(self) -> None:
        self._set_view(RECOMMENDED, -1)

    @Slot()
    def refreshRecommended(self) -> None:
        self._fetch_recommended(force=True)

    def _fetch_recommended(self, force: bool = False, start: int = 1,
                           append: bool = False) -> None:
        # Whether or not this call ends up asking YouTube for anything new,
        # the suggestions already on hand may still be missing a picture for
        # the channel behind them, so that is checked every time this is
        # reached rather than only when a fresh page comes in.
        self._fetch_loose_avatars()
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
        # The row above the cards says how old they are, so it has to hear
        # about this. It used to be told only when the view changed, which
        # meant leaving the page and coming back to see the answer move.
        self.recommendedChanged.emit()
        self._loading_more = False
        self._set_notice("")
        # Nothing new means the feed has been walked to its end for now.
        self._exhausted = count == 0 and self._db.recommended_count() > 0
        self._set_status(f"{self._db.recommended_count()} suggestions")
        if self._view_kind == RECOMMENDED:
            self.reload()
        # The batch that just landed may name channels the earlier check, run
        # before this one was on hand, could not have seen yet.
        self._fetch_loose_avatars()

    def _fetch_loose_avatars(self) -> None:
        """Ask for a picture for every suggested channel that still has none.

        A suggestion names its channel but never carries a picture for it,
        only a channel's own page does, so this is what a card's icon is
        actually waiting on. One worker fetches the whole batch, bounded by
        the same request budget every other browse call answers to, and
        redraws the grid once it is done if the suggestions are still what is
        showing.
        """
        if self._avatars is not None and self._avatars.isRunning():
            return
        keys = self._db.channels_missing_picture(
            self._db.channels_named_in(self._db.RECOMMENDED))
        if not keys:
            return
        self._avatars = ChannelAvatarsFetcher(self._db, self._cfg, keys, parent=self)
        self._avatars.ready.connect(self._on_loose_avatars)
        self._launch(self._avatars)

    def _on_loose_avatars(self, found: int) -> None:
        if found and self._view_kind == RECOMMENDED:
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
        # Every channel opens on its videos. Which half of the last one was
        # showing says nothing about this one.
        if self._channel_tab != "videos":
            self._channel_tab = "videos"
            self.channelTabChanged.emit()
        self._set_view(CHANNEL, -1, channel_key)
        found = self._db.channel(channel_key)
        if not found:
            # Reached from a card in the suggestions, the history or a search,
            # where the channel is a stranger and has no row yet. One is kept
            # for it, not followed, so the page has somewhere to put the name
            # and the picture the lookup below is about to bring back.
            ext_id = channel_key.split(":", 1)[-1]
            if not ids.CHANNEL_ID.match(ext_id):
                return
            self._db.remember_channel(channel_key, "youtube", ext_id)
            found = self._db.channel(channel_key)
        if found and found["platform"] == "youtube" and \
                self._db.channel_details_are_stale(channel_key):
            self._fetch_channel_details(channel_key, found["ext_id"])
        if found and found["platform"] == "youtube":
            self._fetch_channel_feed(channel_key, found["ext_id"])

    channelTab = Property(str, lambda self: self._channel_tab, notify=channelTabChanged)
    channelPlaylists = Property("QVariantList", lambda self: self._channel_playlists(),
                                notify=channelTabChanged)

    def _channel_playlists(self) -> list:
        if not self._view_channel:
            return []
        return [{"key": row["ext_id"], "title": row["title"],
                 # A count only once it has been opened, since the listing
                 # carries none and asking for one is a request each.
                 "itemsText": f"{row['items']} videos" if row["items"] else "",
                 "thumbnail": qml_source(row["thumbnail_url"]),
                 "kept": row["origin"] == "channel"}
                for row in self._db.channel_playlists(self._view_channel)]

    def _get_group_shows(self) -> str:
        """Which half of the group showing is being looked at, or all of it.

        Answers all anywhere but in a group, so the row of buttons has
        something to be accented by even while it is on its way out of view.
        """
        if self._view_kind != GROUP:
            return GROUP_SHOWS_ALL
        return self._db.group_shows(self._view_id)

    groupShows = Property(str, _get_group_shows, notify=groupShowsChanged)

    @Slot(str)
    def showInGroup(self, which: str) -> None:
        """Look at all of this group, its videos or its streams.

        Stored on the group, so it is still what it was on the next visit and
        after a restart. Both readings are of rows already here, so this is a
        reload and never a request.
        """
        if which not in GROUP_SHOWS or self._view_kind != GROUP:
            return
        if which == self._db.group_shows(self._view_id):
            return
        if not self._db.set_group_shows(self._view_id, which):
            return
        self.groupShowsChanged.emit()
        self.reload()

    @Slot(str, bool)
    def wantMembers(self, channel_key: str, wanted: bool) -> None:
        """Start or stop reading this channel's members tab.

        Pressing it on asks now rather than waiting for the poller to come
        round to this channel, which can be hours: a button that only sets a
        flag and shows nothing reads as a button that does not work. Pressing
        it off keeps every row already read and simply stops asking, so what
        was paid for once is not thrown away and not fetched again.
        """
        if not channel_key:
            return
        self._db.set_members_wanted(channel_key, wanted)
        self.viewChanged.emit()
        if not wanted:
            self._set_status("no longer reading that channel's members tab")
            self.reload()
            return
        found = self._db.channel(channel_key)
        if not found or found.get("platform") != "youtube":
            return
        if self._channel_members is not None and self._channel_members.isRunning():
            return
        self._set_notice("reading the members tab")
        self._channel_members = ChannelMembersFetcher(
            self._db, self._cfg, channel_key, found["ext_id"], self)
        self._channel_members.fetched.connect(self._on_channel_members)
        self._channel_members.absent.connect(self._on_no_membership)
        self._channel_members.failed.connect(
            lambda _key, message: self._on_members_failed(message))
        self._launch(self._channel_members)

    def _on_channel_members(self, channel_key: str, stored: int) -> None:
        self._set_notice("")
        if self._view_channel == channel_key:
            self.viewChanged.emit()
            self.reload()
        self._set_status(f"read {stored} from that channel's members tab" if stored
                         else "that channel's members tab holds nothing new")

    def _on_no_membership(self, channel_key: str) -> None:
        """The tab did not answer, so there is nothing to read and the button
        goes back to off by itself."""
        self._set_notice("")
        if self._view_channel == channel_key:
            self.viewChanged.emit()
        self._set_status("that channel sells no membership")

    def _on_members_failed(self, message: str) -> None:
        self._set_notice("")
        self._db.set_members_wanted(self._view_channel, False)
        self.viewChanged.emit()
        self._set_status(f"could not read the members tab, {message}")

    @Slot(str)
    def showChannelTab(self, which: str) -> None:
        if which not in ("videos", "playlists", "streams", "members") or which == self._channel_tab:
            return
        self._channel_tab = which
        self.channelTabChanged.emit()
        if which == "playlists":
            self._fetch_channel_playlists()
        else:
            # Videos and streams are two readings of what is stored, so
            # walking between them is a reload rather than a request.
            self.reload()

    def _fetch_channel_playlists(self, force: bool = False) -> None:
        """Read the tab, once a day unless asked again.

        A channel does not make a playlist every hour, and this is a request,
        so what was read yesterday is read again and what was read this
        morning is not.
        """
        if self._channel_lists is not None and self._channel_lists.isRunning():
            return
        found = self._db.channel(self._view_channel)
        if not found or found.get("platform") != "youtube":
            return
        age = self._db.channel_playlists_age_s(self._view_channel)
        # A listing stored before the pictures were read is old however
        # recently it was read, since it cannot answer for the tiles.
        stale = self._db.channel_playlists_lack_pictures(self._view_channel)
        if not force and not stale and age is not None and age < CHANNEL_PLAYLISTS_TRUST_S:
            return
        self._channel_lists = ChannelPlaylistsFetcher(
            self._db, self._cfg, self._view_channel, found["ext_id"], self)
        self._channel_lists.fetched.connect(self._on_channel_playlists)
        self._channel_lists.failed.connect(
            lambda _key, message: self._set_status(f"could not read the playlists, {message}"))
        self._launch(self._channel_lists)

    def _on_channel_playlists(self, channel_key: str, count: int) -> None:
        if self._view_channel == channel_key:
            self.channelTabChanged.emit()
        if not count:
            self._set_status("that channel lists no playlists")

    @Slot(str, str)
    def openChannelPlaylist(self, playlist_id: str, title: str) -> None:
        """Look inside one of a channel's playlists.

        Its videos need a playlists row to hang off, so one is made and marked
        as something being looked at rather than something kept.
        """
        if not playlist_id:
            return
        self._db.open_channel_playlist(playlist_id, title or playlist_id)
        self.playlistsChanged.emit()
        self.selectPlaylist(playlist_id)

    @Slot(str)
    def openChannelPlaylists(self, channel_key: str) -> None:
        """A channel's page, opened on its playlists rather than its videos.

        The way back out of a playlist that was opened from there, which is
        otherwise the mouse button not everybody has.
        """
        if not channel_key:
            return
        self.openChannel(channel_key)
        self.showChannelTab("playlists")

    @Slot(str, bool)
    def keepPlaylist(self, playlist_id: str, keep: bool = True) -> None:
        if not playlist_id:
            return
        self._db.keep_playlist(playlist_id, keep)
        self.playlistsChanged.emit()
        self.channelTabChanged.emit()
        self.playlistViewChanged.emit()
        self._set_status("playlist kept" if keep else "playlist let go")

    def _fetch_channel_feed(self, channel_key: str, ext_id: str) -> None:
        """Ask this one channel for its videos, because its page is open.

        The poller asks after the channels somebody follows, in its own order
        and at its own pace, so a page opened off a card showed whatever
        happened to be stored, which for a stranger is nothing at all and for
        one just put in a group is nothing yet.

        Only when what is stored is old enough to be worth a request. Walking
        back onto a page a minute later asks nothing.
        """
        if self._channel_feed is not None and self._channel_feed.isRunning():
            return
        polled = (self._db.channel(channel_key) or {}).get("last_polled_at") or 0
        if time.time() - polled < CHANNEL_FEED_TRUST_S:
            return
        self._channel_feed = ChannelFeedFetcher(self._db, self._cfg, channel_key, ext_id, self)
        self._channel_feed.fetched.connect(self._on_channel_feed)
        self._channel_feed.failed.connect(
            lambda _key, message: self._set_status(f"could not read that channel, {message}"))
        self._launch(self._channel_feed)

    def _on_channel_feed(self, channel_key: str, touched: int) -> None:
        if self._view_kind == CHANNEL and self._view_channel == channel_key:
            self.reload()
            # What the page says about the channel, which now includes whether
            # it has ever streamed. The streams half appears here or not at
            # all, since this is the one look its tab gets.
            self.viewChanged.emit()
        if touched:
            self._set_status(f"{touched} rows from that channel")

    def _fetch_channel_details(self, channel_key: str, ext_id: str) -> None:
        """Ask for one channel's picture, banner and follower count.

        One at a time, since each is a page fetch against the same budget as
        everything else. A second while one is in flight waits rather than
        being dropped, which is what a group of channels none of which has
        been opened yet needs: it wants every name in the window, not the
        first one that happened to ask.
        """
        if self._details is not None and self._details.isRunning():
            pair = (channel_key, ext_id)
            if pair not in self._details_queue and len(self._details_queue) < DETAILS_WAITING:
                self._details_queue.append(pair)
            return
        self._start_details(channel_key, ext_id)

    def _start_details(self, channel_key: str, ext_id: str) -> None:
        self._details = ChannelDetailsFetcher(self._db, self._cfg, channel_key, ext_id, self)
        self._details.fetched.connect(self._on_details_fetched)
        self._details.failed.connect(self._on_details_failed)
        if not self._launch(self._details):
            self._details_queue.clear()

    def _on_details_fetched(self, _key: str) -> None:
        self.viewChanged.emit()
        # A group's window shows the name, the picture and the follower count
        # of each channel in it, and those are what just arrived.
        self.groupsChanged.emit()
        self._next_details()

    def _on_details_failed(self, _key: str, message: str) -> None:
        self._set_status(f"could not load the channel, {message}")
        self._next_details()

    def _next_details(self) -> None:
        if not self._details_queue:
            return
        channel_key, ext_id = self._details_queue.pop(0)
        self._start_details(channel_key, ext_id)

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
        name = (name or "").strip()
        if not name:
            return
        if not self._db.rename_box(box_id, name):
            self._set_notice(f"A box called {name} already exists", clear_after_s=5)
            return
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
        """Put a video in a box, storing it first if it was only ever borrowed.

        A suggestion, a history entry and a search result are all snapshots
        that get replaced, so putting one in a box keeps it for good. The
        channel it brings along is kept as well, for its name and its picture,
        and is not followed by this.
        """
        if not self._db.add_to_box(box_id, video_key, self._loose_row(video_key)):
            self._set_status("that video could not be stored")
            return
        self.boxesChanged.emit()
        if self._view_kind == BOX:
            self.reload()

    def _loose_row(self, video_key: str) -> dict | None:
        """The row behind a video that is only held in memory.

        Results from YouTube are the one list with nowhere to be read back
        from, so the row goes to the database with the request to store it.
        Everything else is already in a table and is found there.
        """
        return next((row for row in self._web_results if row["key"] == video_key), None)

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
        name = (name or "").strip()
        if not name:
            return
        if not self._db.rename_group(group_id, name):
            self._set_notice(f"A group called {name} already exists", clear_after_s=5)
            return
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

    @Slot(int, int)
    def moveBox(self, box_id: int, delta: int) -> None:
        if self._db.move_box(box_id, delta):
            self.boxesChanged.emit()

    @Slot(int, result="QVariantList")
    def boxVideos(self, box_id: int) -> list:
        """What one box holds, by title, for the window that asks before it is
        deleted. The videos themselves are kept, so this is a reminder of what
        the box was rather than a warning about losing anything."""
        return [{"key": row["key"], "title": row["title"] or row["key"]}
                for row in self._db.feed(limit=200, hide_watched=False, box_id=box_id)]

    @Slot(int, str)
    def addChannelToGroup(self, group_id: int, channel_key: str) -> None:
        if not channel_key:
            return
        # All is one of the lists a channel can be put into. There is no
        # reason a channel followed here should not sit beside a subscribed
        # one, and putting it in All is exactly what following it means.
        if group_id < 0:
            self._db.restore_to_all(channel_key)
        else:
            self._db.add_to_group(group_id, channel_key)
        self.groupsChanged.emit()
        if self._view_kind in (GROUP, ALL):
            self.reload()

    @Slot(int, str)
    def removeChannelFromGroup(self, group_id: int, channel_key: str) -> None:
        if not channel_key:
            return
        found = self._db.channel(channel_key)
        # All is managed the same way a group is, and taking a channel out of
        # it is remembered, so the next subscription import cannot put it back.
        dropped = (self._db.remove_from_all(channel_key) if group_id < 0
                   else self._db.remove_from_group(group_id, channel_key))
        if dropped:
            # Worth saying. The channel was only ever followed because a group
            # asked for it, so taking it out of the last one stops it being
            # polled, and nothing on screen would otherwise show that.
            name = (found or {}).get("title") or channel_key.split(":", 1)[-1]
            self._set_status(f"{name} is no longer followed, nothing was left to show it in")
        self.groupsChanged.emit()
        if self._view_kind in (GROUP, ALL):
            self.reload()

    def _members_of(self, group_id: int) -> list:
        """Who is in a group, or in All, which is managed the same way.

        All is not a row in the groups table and never will be: it is every
        channel followed on its own account, which is a query rather than a
        list somebody keeps.
        """
        if group_id < 0:
            return self._db.channels(platform="youtube", in_all_only=True)
        return self._db.group_channels(group_id)

    @Slot(int, result="QVariantList")
    def groupChannels(self, group_id: int) -> list:
        """The channels in one group, for the window that manages it.

        A follower count is only there once the channel's own page has been
        fetched, so it is handed over pre-formatted and empty when it is not
        known yet rather than shown as a confident zero.
        """
        rows = []
        for row in self._members_of(group_id):
            found = dict(row)
            followers = found.get("follower_count")
            rows.append({
                "key": found.get("key", ""),
                "title": found.get("title") or found.get("ext_id", ""),
                "avatar": qml_source(found.get("avatar_url")),
                "followersText": fmt.count_text(followers) if followers else "",
                "platform": found.get("platform", "youtube"),
                "inAll": bool(found.get("in_all")),
            })
        return rows

    @Slot(int)
    def fillGroupDetails(self, group_id: int) -> None:
        """Ask for whatever this group's channels have not told us yet.

        A channel put in a group off a video card is known by id and by
        whatever name that card carried, which is often none and never a
        picture or a follower count. One page fetch each fills that in, queued
        so they go one at a time.
        """
        if group_id < 0:
            # All is every channel followed, which here is several hundred of
            # them, each already named and pictured by the subscription
            # import. The only thing a page fetch would add is a follower
            # count, and it is not worth one request per channel.
            return
        for row in self._members_of(group_id):
            found = dict(row)
            if found.get("platform") != "youtube":
                continue
            if found.get("title") and found.get("avatar_url") and found.get("follower_count"):
                continue
            if not self._db.channel_details_are_stale(found["key"]):
                continue
            self._fetch_channel_details(found["key"], found["ext_id"])

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
        if row.get("isLocked"):
            # Behind a membership that is not held. There is nothing to hand
            # mpv: what comes back is a sentence about joining the channel, and
            # mpv would open a window to say so. It is said here instead,
            # because a press that is simply ignored reads as the application
            # being broken, which is what the card's own mark is there to
            # prevent. A membership that IS held plays like anything else and
            # keeps only the mark.
            self._set_notice(MEMBERS_NOTICE, 6)
            return
        if row.get("isUpcoming"):
            # An announced stream is still just a listing. Handing its watch
            # URL to mpv crashes it, since there is nothing there yet, so the
            # click opens what can actually be shown right now instead.
            self.openDetail(key)
            return
        if self._view_kind == HISTORY and self._history_music:
            # These are songs, and they were listened to rather than watched.
            self.playAudio(key)
            return
        if self._view_kind == PLAYLIST and self._playing_is_music():
            # A playlist marked as music is listened to rather than watched, so
            # a press means what the headphone on the card means.
            self.playAudio(key)
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
            self._set_starting(row["key"])

    def _get_press_is_music(self) -> bool:
        """Whether a plain press in the open view already means listening.

        The headphone on a card reads as an offer of something else, so where
        it would do exactly what the press does it is not drawn at all.
        """
        if self._view_kind == HISTORY:
            return self._history_music
        return self._view_kind == PLAYLIST and self._playing_is_music()

    pressIsMusic = Property(bool, _get_press_is_music, notify=viewChanged)

    def _playing_is_music(self) -> bool:
        """Whether the open playlist is one that was marked as music."""
        if not self._view_playlist:
            return False
        found = self._db.playlist(self._view_playlist)
        return bool(found and found.get("is_music"))

    @Slot(str)
    def copyLink(self, key: str) -> None:
        """Put the address of a video on the clipboard.

        Inside a playlist the list travels with it, so whoever opens the
        address lands in the list at that video, which is what the address in
        a browser's own bar would have been.
        """
        row = self._model.row_for_key(key)
        if not row:
            return
        url = row["url"]
        if self._view_kind == PLAYLIST and self._view_playlist \
                and not key.startswith("twitch:"):
            url = ids.playlist_watch_url(key.split(":", 1)[1], self._view_playlist)
        QGuiApplication.clipboard().setText(url)
        self._set_status("address copied")
        # The same line that says a video is starting, since a copy is just as
        # invisible as mpv taking a few seconds to put a window up.
        self._set_notice("Address copied, ready to paste", clear_after_s=4)

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

    def attach_theme(self, theme) -> None:
        """Given after construction, like the player, since the window's own
        theme object is built beside the bridge rather than by it."""
        self._theme = theme

    def _get_own_themes(self) -> list:
        """The themes that were made here, by the name they were given.

        These are the ones that can be thrown away. What ships with the
        application cannot be, and a file is read for its name rather than
        having the file name shown, since one is a name and the other is where
        it happens to live.
        """
        found = []
        for path in sorted(themes.user_dir().glob("*.toml")):
            loaded = themes.load_file(path)
            if loaded is not None:
                found.append(loaded.name)
        return found

    ownThemes = Property("QVariantList", _get_own_themes, notify=themesChanged)

    @Slot(str, str, str)
    def previewTheme(self, ground: str, accent: str, second: str) -> None:
        """Paint the window with the dots as they are being moved.

        Nothing is written. The file is only made when it is saved, so a theme
        can be tried for as long as it takes without leaving anything behind.
        """
        if self._theme is None:
            return
        self._theme.show_draft(palette.from_dots(ground, accent, second or None))

    @Slot()
    def stopPreview(self) -> None:
        """Put the draft down and go back to the theme that was chosen."""
        if self._theme is not None:
            self._theme.show_draft(None)

    @Slot(str, str, str, str, result=bool)
    def saveTheme(self, name: str, ground: str, accent: str, second: str) -> bool:
        """Write the dots out as a theme of its own, and wear it.

        It lands in the same folder a hand written theme goes in and is read
        the same way, so there is nothing special about one made here.
        """
        name = name.strip()
        if not name or self._theme is None:
            self._set_notice("A theme needs a name", clear_after_s=4)
            return False
        made = palette.from_dots(ground, accent, second or None)
        target = themes.user_dir() / f"{themes.file_name(name)}.toml"
        try:
            themes.user_dir().mkdir(parents=True, exist_ok=True)
            target.write_text(palette.as_toml(name, made), encoding="utf-8")
        except OSError as exc:
            self._set_notice(f"Could not save the theme, {exc}", clear_after_s=6)
            return False
        self._theme.show_draft(None)
        self._theme.reload()
        self._theme.select(name)
        self.themesChanged.emit()
        self._set_notice(f"Saved {name}", clear_after_s=4)
        return True

    @Slot(str, str, result=bool)
    def exportTheme(self, name: str, where: str) -> bool:
        """Copy a theme out, so it can be handed to somebody.

        A theme is a file with nothing in it but colours, so sharing one is
        copying it. Nothing is rewritten on the way out.
        """
        source = self._theme_file(name)
        if source is None:
            self._set_notice(f"Could not find {name}", clear_after_s=5)
            return False
        target = Path(self._local_path(where))
        if target.is_dir():
            # Named after the theme rather than after the file it happens to
            # live in, since what ships is not named after itself and nobody
            # receiving dark.toml would know it is called Weave Dark.
            target = target / f"{themes.file_name(name)}.toml"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError as exc:
            self._set_notice(f"Could not write it, {exc}", clear_after_s=6)
            return False
        self._set_notice(f"Copied {name} to {target}", clear_after_s=6)
        return True

    @staticmethod
    def _theme_file(name: str) -> Path | None:
        """The file a theme is written in, found by the name it goes by.

        Searched rather than worked out from the name. What ships is not named
        after itself on disk, Weave Dark being dark.toml, so building the file
        name from the theme name finds nothing for half the list.
        """
        for folder in (themes.user_dir(), themes.builtin_dir()):
            for path in sorted(folder.glob("*.toml")):
                loaded = themes.load_file(path)
                if loaded is not None and loaded.name == name:
                    return path
        return None

    @Slot(str, result=bool)
    def importTheme(self, where: str) -> bool:
        """Take a theme somebody else made and keep it with your own.

        It is read before it is kept, so a file that is not a theme is refused
        with what was wrong with it rather than landing in the folder and
        turning up broken in the list.
        """
        source = Path(self._local_path(where))
        loaded = themes.load_file(source) if source.is_file() else None
        if loaded is None:
            self._set_notice("That is not a theme file", clear_after_s=5)
            return False
        if loaded.problems:
            # A file that cannot be read at all comes back looking like a
            # theme, with every role filled in from the fallback, and only the
            # list of problems says otherwise. So anything with a problem is
            # refused rather than kept and shown as a theme that is mostly not
            # the one it claims to be.
            self._set_notice(f"That is not a theme file, {loaded.problems[0]}",
                             clear_after_s=6)
            return False
        target = themes.user_dir() / f"{themes.file_name(loaded.name)}.toml"
        try:
            themes.user_dir().mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError as exc:
            self._set_notice(f"Could not keep it, {exc}", clear_after_s=6)
            return False
        if self._theme is not None:
            self._theme.reload()
        self.themesChanged.emit()
        self._set_notice(f"Took in {loaded.name}", clear_after_s=5)
        return True

    @staticmethod
    def _local_path(where: str) -> str:
        """A path as typed, or as a file address dropped in from elsewhere."""
        where = (where or "").strip()
        if where.startswith("file://"):
            return QUrl(where).toLocalFile()
        return str(Path(where).expanduser())

    @Slot(str, result=bool)
    def deleteTheme(self, name: str) -> bool:
        """Throw away a theme that was made here. What ships is left alone."""
        target = themes.user_dir() / f"{themes.file_name(name)}.toml"
        if not target.exists():
            self._set_notice("That theme is not one of yours", clear_after_s=4)
            return False
        target.unlink()
        if self._theme is not None:
            self._theme.reload()
        self.themesChanged.emit()
        self._set_notice(f"Threw away {name}", clear_after_s=4)
        return True

    def attach_audio(self, audio) -> None:
        """Given after construction, since the player needs the config the
        bridge already holds."""
        self._audio = audio
        self._player.nowPlaying.connect(lambda *_a: self._audio.pause_for_video())
        # Whether the heart is lit depends on the song playing as much as on
        # which songs are kept, so a new song has to say so too. Without this
        # the heart kept whatever it read for the song before.
        audio.trackChanged.connect(self.favoritesChanged.emit)

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
                self._shelves_age = self._db.get_int("music_shelves_at", 0)
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
        """Back to the shelves, which the music view shows when there are no
        results. A place of its own, so the list left behind is still there to
        walk back to."""
        self._set_view(MUSIC, -1, "", "", None)

    @Slot()
    def playLiked(self) -> None:
        """Liked videos come from YouTube rather than YouTube Music. The two
        lists are separate and this is the one with anything in it."""
        self._open_music_list(MusicList(TrackList.LIKED, "", "Liked"))

    @Slot(int)
    def openShelf(self, shelf_index: int) -> None:
        """A whole shelf, rather than the two rows of it the view has room for.

        Kept by name, so walking back onto it after the shelves were gathered
        again lands on the same section and not on whatever took its place.
        """
        try:
            shelf = self._get_shelves()[shelf_index]
        except (IndexError, KeyError, TypeError):
            return
        self._open_music_list(MusicList(MUSIC_SHELF, shelf["title"], shelf["title"]))

    @Slot(str, result=bool)
    def isFavorite(self, key: str) -> bool:
        """Whether a song is one of the kept ones."""
        return key.startswith("yt:") and self._db.is_music_favorite(key.split(":", 1)[1])

    def _get_playing_favorite(self) -> bool:
        track = self._audio.track if self._audio else {}
        key = str((track or {}).get("key") or "")
        return self.isFavorite(key)

    playingIsFavorite = Property(bool, _get_playing_favorite, notify=favoritesChanged)

    def _mark_favorite(self, key: str, title: str, artist: str | None,
                       thumbnail: str | None, keep: bool | None = None) -> None:
        """Keep a song or stop keeping it, and say which just happened."""
        if not key.startswith("yt:"):
            return
        ext_id = key.split(":", 1)[1]
        wanted = (not self._db.is_music_favorite(ext_id)) if keep is None else keep
        # Stored plain. What comes from the window has been wrapped for the
        # cache already, and wrapping it again would leave nothing at all.
        self._db.set_music_favorite(ext_id, wanted, title or "", artist,
                                    plain_source(thumbnail))
        self._set_notice("Added to favorites" if wanted else "Removed from favorites",
                         clear_after_s=4)
        self._set_status("added to favorites" if wanted else "removed from favorites")
        self.favoritesChanged.emit()
        self.musicChanged.emit()
        # Giving back the last one empties the section, and the whole page of
        # it with that. The window falls back to the sections on its own, so
        # the record of where it is follows rather than pointing at a page
        # that no longer exists.
        open_on = self._music_list
        if (not wanted and open_on is not None and open_on.what == MUSIC_SHELF
                and open_on.ident == FAVORITES
                and not self._db.music_favorite_count()):
            self._set_view(MUSIC, -1, "", "", None)

    @Slot(str)
    def favoriteVideo(self, key: str) -> None:
        """From a card, in a playlist that holds music or in the listening
        history, where a video is a song and the card is how it is reached."""
        row = self._model.row_for_key(key) or {}
        self._mark_favorite(key, row.get("title", ""), row.get("channelTitle"),
                            row.get("thumbnail"))

    @Slot()
    def toggleFavorite(self) -> None:
        """The heart beside what is playing."""
        track = (self._audio.track if self._audio else {}) or {}
        key = str(track.get("key") or "")
        self._mark_favorite(key, str(track.get("title") or ""),
                            track.get("artist"), track.get("thumbnail"))

    def _queue_track(self, track: dict | None, play_next: bool) -> None:
        """Put one song in the queue, and say so."""
        if not self._audio or not track:
            return
        if not self._audio.add_item(track, play_next=play_next):
            return
        self._set_notice("Playing it next" if play_next else "Added to the queue",
                         clear_after_s=4)
        self._set_status(f"queued {track.get('title', '')}")

    @Slot(int, int, bool)
    def queueShelfItem(self, shelf_index: int, item_index: int,
                       play_next: bool = False) -> None:
        """From a tile. Only a song, since a list is not one thing to queue."""
        try:
            item = self._get_shelves()[shelf_index]["items"][item_index]
        except (IndexError, KeyError, TypeError):
            return
        video = item.get("videoId")
        if not video:
            self._set_notice("Only a song can be queued, not a whole list",
                             clear_after_s=4)
            return
        self._queue_track({
            "key": f"yt:{video}", "title": item.get("title", ""),
            "artist": item.get("subtitle", ""), "thumbnail": item.get("thumbnail", ""),
            "live": False, "url": ids.watch_url("youtube", video),
        }, play_next)

    @Slot(int, bool)
    def queueResult(self, index: int, play_next: bool = False) -> None:
        """From a row in a list that was opened."""
        try:
            row = self._results[index]
        except (IndexError, TypeError):
            return
        found = self._track_items([row])
        self._queue_track(found[0] if found else None, play_next)

    @Slot(int)
    def favoriteResult(self, index: int) -> None:
        """From a row in an opened list, a playlist or a station alike.

        The same act as the tile and the card, reached from the third place a
        song is drawn.
        """
        try:
            row = self._results[index]
        except (IndexError, TypeError):
            return
        self._mark_favorite(str(row.get("key") or ""), str(row.get("title") or ""),
                            row.get("artist"), row.get("thumbnail"))

    @Slot(int, result=bool)
    def resultIsFavorite(self, index: int) -> bool:
        try:
            row = self._results[index]
        except (IndexError, TypeError):
            return False
        return self.isFavorite(str(row.get("key") or ""))

    @Slot(int, int)
    def favoriteShelfItem(self, shelf_index: int, item_index: int) -> None:
        """From a tile in the music page.

        The index comes from the arranged list that is drawn, never the raw
        one, for the same reason pressing a tile does.
        """
        try:
            item = self._get_shelves()[shelf_index]["items"][item_index]
        except (IndexError, KeyError, TypeError):
            return
        video = item.get("videoId")
        if not video:
            self._set_notice("Only a song can be kept, not a whole list",
                             clear_after_s=4)
            return
        self._mark_favorite(f"yt:{video}", item.get("title", ""),
                            item.get("subtitle"), item.get("thumbnail"))

    @Slot(int, int, result=bool)
    def shelfItemIsFavorite(self, shelf_index: int, item_index: int) -> bool:
        try:
            item = self._get_shelves()[shelf_index]["items"][item_index]
        except (IndexError, KeyError, TypeError):
            return False
        video = item.get("videoId")
        return bool(video) and self._db.is_music_favorite(video)

    def _play_favorites(self, video_id: str) -> None:
        """Start on the song that was pressed and shuffle the rest behind it.

        The queue is built here rather than left to the player's own shuffle,
        so the one pressed is heard first and the order is decided once. It
        goes straight into the queue and opens nothing, like a station.
        """
        rows = self._db.music_favorites()
        if not rows:
            return
        tracks = [{
            "key": row["key"], "title": row["title"],
            "artist": row["channel_title"] or "",
            "thumbnail": qml_source(row["thumbnail_url"]),
            "live": False,
            "url": ids.watch_url("youtube", row["ext_id"]),
        } for row in rows]
        rest = [track for track in tracks if track["key"] != f"yt:{video_id}"]
        random.shuffle(rest)
        chosen = [track for track in tracks if track["key"] == f"yt:{video_id}"]
        queue = chosen + rest
        if not self._audio or not queue:
            return
        self._audio.play_items(queue, start=0)
        self._set_status(f"listening to your favorites from {queue[0]['title']}")

    @Slot(int, int)
    def playShelfItem(self, shelf_index: int, item_index: int) -> None:
        # The index comes from what is on screen, which is the arranged list
        # with the saved section in it, not the raw one. Reading the raw list
        # here meant a tile acted on some other section's entry as soon as an
        # order was kept or an address was saved.
        try:
            shelf = self._get_shelves()[shelf_index]
            item = shelf["items"][item_index]
        except (IndexError, KeyError, TypeError):
            return
        video = item.get("videoId")
        playlist = item.get("playlistId")

        # A kept song is heard among the others that were kept, in no
        # particular order, rather than starting a station of things like it.
        # That is the whole point of having kept them.
        if shelf.get("kind") == "favorites" and video:
            self._play_favorites(video)
            return

        # A song carries both its own id and the id of the station built from
        # it. Pressing it plays that song and then things like it, which is
        # what the music application does, so the station is what to fetch.
        # Into the queue and nowhere else. Pressing a song is asking to hear
        # it, not asking to read what follows, and the player already lists
        # what follows, so nothing is opened and nothing is walked onto.
        if video and playlist:
            self._play_station(video, item.get("title", ""))
            return
        # A playlist is opened to look at. Nothing starts until something in it
        # is chosen.
        if playlist:
            self._open_music_list(MusicList("playlist", playlist, item.get("title", "")))
            return
        if video and self._audio:
            self._audio.play_items([{
                "key": f"yt:{video}", "title": item.get("title", ""),
                "artist": item.get("subtitle", ""), "thumbnail": item.get("thumbnail", ""),
                "live": False, "url": ids.watch_url("youtube", video),
            }])

    def _open_music_list(self, target: MusicList) -> None:
        """A track list or a shelf was asked for. Landing on one is a step, so
        the back button returns to the shelves and forward opens it again."""
        if self._view_kind == MUSIC and self._music_list == target:
            # Already the place showing, so not a step. A list whose rows never
            # arrived is asked for again rather than sitting empty. A shelf has
            # no rows to ask for, since it is what the view already holds.
            if target.what != MUSIC_SHELF and target not in self._music_cache:
                self._fetch_music_list(target)
            return
        self._set_view(MUSIC, -1, "", "", target)

    def _show_music_list(self, target: MusicList | None) -> None:
        """Put the music view on one track list, or back on the shelves.

        Reached from _set_view alone, so pressing a tile, searching and
        walking back onto a list all arrive the same way.
        """
        if target is None or target.what == MUSIC_SHELF:
            # The shelves are what the view shows when there are no results,
            # so landing on them is emptying them. One shelf in full is the
            # same, with the shelf itself naming which of them to draw.
            self._results = []
            self._results_label = ""
            self.musicChanged.emit()
            return
        held = self._music_cache.get(target)
        if held is not None:
            self._results, self._results_label = held
            self._searching = False
            self.musicChanged.emit()
            return
        # Not held any more, so it has to be asked for again. What is on
        # screen stays there while that runs, which is what pressing a tile
        # has always looked like.
        self._fetch_music_list(target)

    def _fetch_music_list(self, target: MusicList) -> None:
        """Ask for a list that is not held in memory."""
        if target.what == MUSIC_SEARCH:
            self._start_music_search(target)
            return
        self._start_tracks(TrackList(self._cfg, target.what, target.ident,
                                     target.label, self), target)

    def _start_tracks(self, worker: TrackList, target: MusicList) -> None:
        if self._tracks is not None and self._tracks.isRunning():
            return
        self._searching = True
        self.musicChanged.emit()
        self._tracks = worker
        # The list the rows belong to travels with the worker, since the view
        # can have moved on by the time they arrive.
        self._tracks.tracks.connect(
            lambda rows, label: self._on_tracks(rows, label, target))
        self._tracks.failed.connect(self._on_search_failed)
        self._launch(self._tracks)

    def _play_station(self, video_id: str, label: str) -> None:
        """The station built from one song, into the player and nowhere else.

        The rows are handed to the queue as they arrive and are not kept, since
        what is not showing does not have to be walked back to. The view stays
        exactly where the press found it.
        """
        if self._station is not None and self._station.isRunning():
            return
        self._searching = True
        self.musicChanged.emit()
        self._set_status(f"starting {label}" if label else "starting a station")
        self._station = TrackList(self._cfg, TrackList.RADIO, video_id, label, self)
        self._station.tracks.connect(lambda rows, _label: self._on_station(rows))
        self._station.failed.connect(self._on_search_failed)
        self._launch(self._station)

    def _on_station(self, rows: list) -> None:
        self._searching = False
        self.musicChanged.emit()
        if not rows or not self._audio:
            return
        self._audio.play_items(self._track_items(rows))

    def _start_music_search(self, target: MusicList) -> None:
        if self._search is not None and self._search.isRunning():
            return
        self._searching = True
        self.musicChanged.emit()
        self._search = MusicSearch(self._cfg, target.ident, self)
        self._search.results.connect(lambda rows: self._on_results(rows, target))
        self._search.failed.connect(self._on_search_failed)
        self._launch(self._search)

    def _on_shelves(self, shelves: list) -> None:
        self._shelves = shelves
        self._shelves_age = int(time.time())
        self._db.set_state("music_shelves", json.dumps(shelves))
        self._db.set_state("music_shelves_at", str(self._shelves_age))
        self.musicChanged.emit()

    @Slot()
    def refreshMusic(self) -> None:
        self.loadHome(force=True)

    def _on_tracks(self, rows: list, label: str, target: MusicList | None = None) -> None:
        """Rows for one list. The heading they arrive with is the one kept,
        since a playlist with removed videos says how many are still
        playable."""
        if target is None:
            target = self._music_list
        if target is not None:
            self._music_cache.put(target, rows, label)
        self._searching = False
        if target is not None and target != self._music_list:
            # Walked away while this was in flight, so it is held for the walk
            # back rather than dropped onto a view that asked for something
            # else.
            self.musicChanged.emit()
            return
        self._results = rows
        self._results_label = label
        self.musicChanged.emit()

    @Slot(str)
    def musicSearch(self, query: str) -> None:
        """Results that replace what the view was showing, so a search is a
        place like a list is. Asked for by pressing search rather than by
        typing, so this is once per search and never once per letter."""
        query = (query or "").strip()
        if not query:
            return
        self._open_music_list(MusicList(MUSIC_SEARCH, query, MUSIC_SEARCH_LABEL))

    @Slot(int)
    def playResult(self, index: int) -> None:
        """Plays from here to the end of the results, which is what a list of
        songs is for."""
        if not self._audio or not self._results:
            return
        items = self._track_items(self._results)
        self._audio.play_items(items, max(0, min(index, len(items) - 1)))

    @staticmethod
    def _track_items(rows: list) -> list:
        """Track rows as the player wants them. One place, so the picture a
        row arrived with reaches the queue whichever list it came from."""
        return [{"key": row["key"], "title": row["title"], "artist": row["artist"],
                 "thumbnail": row["thumbnail"], "live": False,
                 "url": ids.watch_url("youtube", row["videoId"])}
                for row in rows]

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
        if row.get("isLocked"):
            # The headphone reaches the same address the card does, so it is
            # refused for the same reason.
            self._set_notice(MEMBERS_NOTICE, 6)
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

    def _on_results(self, rows: list, target: MusicList | None = None) -> None:
        # A search comes back as a list of tracks like any other, so it is
        # held and shown by the one path rather than a second copy of it.
        self._on_tracks(rows, target.label if target else MUSIC_SEARCH_LABEL, target)

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
            self._keep_details(key, details)
        self._detail_loading = False
        if key == self._detail_key:
            self._detail_comments = threads
        self.detailChanged.emit()

    def _keep_details(self, key: str, details: dict) -> None:
        """Write what the panel learned back onto the stored row.

        A card in the suggestions, the history or a playlist is drawn from a
        listing that carries almost nothing, while opening the same video
        fetches its metadata anyway. Keeping it means the card catches up
        instead of staying the poorer view of the same thing, and it costs no
        request of its own.
        """
        if not key.startswith("yt:"):
            return
        touched = self._db.fill_in_details(
            key.split(":", 1)[1],
            views=details.get("views"),
            published_at=details.get("published_at"),
            duration_s=details.get("duration_s"))
        if touched and self._view_kind in (RECOMMENDED, HISTORY, PLAYLIST):
            self.reload()

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
        # mpv reports the file before its window is up, so the chip stays a
        # while longer rather than going while the screen is still empty. Six
        # seconds, which is his answer to watching it happen.
        if self._starting_key:
            self._set_starting(self._starting_key, clear_after_s=6)
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
    def expectLiveCheck(self) -> None:
        """Say the bar is working before the first check has even begun.

        The first check is scheduled a moment after the window opens and a
        Twitch answer arrives in a fraction of a second, so a flag raised only
        while the request is in flight was on screen too briefly to read. This
        raises it at the point the check is promised instead. Every end of the
        check lowers it again, and a check that never starts at all is caught
        by the guard below.
        """
        self._set_live_checking(True)
        QTimer.singleShot(15000, self._live_check_gave_up)

    def _live_is_ready(self) -> None:
        """The first answer has landed, so the bar may show itself."""
        if not self._live_ready:
            self._live_ready = True
            self.liveChanged.emit()

    def _live_check_gave_up(self) -> None:
        """Nothing may leave the bar saying it is working for ever."""
        if self._live is None or not self._live.isRunning():
            self._set_live_checking(False)

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
            started = self._player.play(url, twitch_login=row["login"], live=True)
        else:
            started = self._player.play(ids.watch_url("youtube", row["login"]), live=True)
        self._set_status(f"playing {row['name']}")
        if started:
            # A live tile carries its channel rather than a video, so that is
            # what the chip is matched against there.
            self._set_starting(channel_key)

    @Slot()
    def importSubscriptions(self) -> None:
        if self._importer is not None and self._importer.isRunning():
            return
        self._set_import("working", "reading the subscription list from YouTube")
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
        self._name_the_strangers(self._db.HISTORY)

    def _name_the_strangers(self, kind: str) -> None:
        """Ask who made the videos in a listing that nothing here knows.

        The history says nothing about the channel, so a card from a channel
        nobody follows has no name and no face. Most answer from the videos
        table for nothing; this is the rest, a few at a time, once in the life
        of a video.
        """
        if self._owners is not None and self._owners.isRunning():
            return
        self._owners = OwnerFetcher(self._db, self._cfg, kind, parent=self)
        self._owners.fetched.connect(self._on_owners)
        self._launch(self._owners)

    def _on_owners(self, named: int) -> None:
        if self._view_kind in (HISTORY, RECOMMENDED):
            self.reload()

    @Slot(str, result=bool)
    def addChannel(self, text: str) -> bool:
        """Accepts a channel id, an @handle, a legacy channel URL or a Twitch
        link. Returns whether the reference was understood at all. Resolving a
        handle then happens in the background.

        This is following a channel by name, so it goes into All, and it says
        so for a channel that was until now kept for one group alone."""
        return self._queue_channel(text, -1)

    @Slot(int, str, result=bool)
    def addChannelToGroupByRef(self, group_id: int, text: str) -> bool:
        """The same reference, wanted in one group and not in All.

        Reached from the window that manages a group. A channel already
        followed keeps its place in All, since being asked for by a group
        never takes one out.
        """
        # A negative id is All, where a reference means the same thing the
        # toolbar box means: follow it, and show it in All.
        return self._queue_channel(text, group_id)

    def _set_add(self, state: str, message: str) -> None:
        self._add_state = state
        self._add_message = message
        self.addChanged.emit()

    @Slot()
    def clearAddState(self) -> None:
        """Forget the last attempt. Called as a box is opened or typed into,
        so an answer about the last reference is not read as one about this."""
        if self._add_state or self._add_message:
            self._set_add("", "")

    def _queue_channel(self, text: str, group_id: int) -> bool:
        ref = ids.parse_channel_ref(text)
        if not ref:
            self._set_add("failed", "That is not a channel id, a handle, a channel address "
                                    "or a twitch.tv link")
            self._set_status("could not read that as a channel")
            return False
        self._set_add("working", f"Looking for {ref.value}")
        self._add_queue.append((ref, group_id))
        if self._adder is not None and self._adder.isRunning():
            waiting = len(self._add_queue)
            self._set_status(f"{ref.value} is waiting, "
                             f"{waiting} to resolve after the one in flight"
                             if waiting > 1 else f"{ref.value} is waiting its turn")
            return True
        self._start_next_add()
        return True

    def _start_next_add(self) -> None:
        """Resolve the next queued reference, if any.

        A new worker is started from inside the previous one's own signal, by
        which point that one has finished resolving even though Qt may not
        have marked the thread done yet. The old one stays in `_threads` until
        it is reaped, so nothing is lost by pointing `_adder` at the new one.
        """
        if not self._add_queue:
            return
        ref, group_id = self._add_queue.pop(0)
        self._adding = group_id
        self._set_status(f"resolving {ref.value}")
        self._adder = ChannelAdder(ref, self._cfg, self)
        self._adder.added.connect(self._on_channel_added)
        self._adder.failed.connect(self._on_channel_failed)
        if not self._launch(self._adder):
            self._add_queue.clear()

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
        # A worker that died on an exception nobody expected says so through
        # this, and the flag that was raised for it is put down again. The
        # worker itself is captured rather than read off sender(), since this
        # runs before the reaper has cleared the attribute that holds it.
        crashed = getattr(thread, "crashed", None)
        if crashed is not None:
            crashed.connect(lambda message, worker=thread:
                            self._on_worker_crashed(worker, message))
        thread.start()
        return True

    def _on_worker_crashed(self, worker, message: str) -> None:
        """A worker stopped on an exception it never expected.

        Every worker raises some flag in here while it runs, and every one of
        them used to lower it only on its own success or failure signal. An
        exception that escaped emitted neither, so the window sat saying
        "working" for the rest of the evening with nothing working. This is
        the one place that knows which flag belongs to which worker, and it
        lowers the right one before saying what happened.
        """
        name = type(worker).__name__
        line = f"{name} stopped on an error, {message}"
        if worker is self._poller:
            self._set_busy(False)
        elif worker is self._importer:
            self._set_import("failed", line)
        elif worker is self._adder:
            self._on_channel_failed(message)
            return
        elif worker is self._details:
            self._next_details()
        elif worker in (self._searcher, self._recommended, self._history):
            self._loading_more = False
            self._set_notice("")
        elif worker in (self._search, self._tracks, self._station):
            self._searching = False
            self.musicChanged.emit()
        elif worker is self._detail:
            self._detail_loading = False
            self.detailChanged.emit()
        elif worker is self._cache_job:
            self._cache_working = False
            self.cacheChanged.emit()
        elif worker is self._twitch:
            self._twitch_status = f"Twitch login failed, {message}"
            self.twitchChanged.emit()
        elif worker in (self._checkup, self._playlists, self._playlist_items):
            self._set_notice("")
        elif worker is self._channel_members:
            # The button was pressed and nothing came of it, so it goes back
            # to off rather than sitting on with an empty half behind it.
            self._db.set_members_wanted(self._view_channel, False)
            self._set_notice("")
            self.viewChanged.emit()
        elif worker is self._lengths:
            # Holds no flag: it is background work nothing is waiting on, and
            # the channel it stopped on is left unstamped so it comes round
            # again. Named here all the same, because the inventory test
            # insists every worker with a handle on the bridge is.
            pass
        self._problems.append(line)
        self.problemsChanged.emit()
        self._set_status(line)

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
        group_id = self._adding
        self._adding = -1
        # A reference typed into a group's own window is followed for that
        # group only, so it is added with in_all off. One typed into the
        # toolbar is a plain follow and goes into All, which also brings a
        # channel back that a group had been keeping on its own.
        self._db.add_channel(key, platform, ext_id, title or None, in_all=group_id < 0)
        if group_id < 0:
            # Following by name is the one thing that undoes having taken a
            # channel out of All, and it should, since it is the same person
            # asking for it back in the same words they first used.
            self._db.restore_to_all(key)
        label = title or ext_id
        self._set_add("added", f"Added {label}")
        # Whichever list it went into, the window that manages that list is
        # listening for this. Following into All only ever said so through the
        # feed, so a channel added in All's own window did not appear until the
        # window was closed and opened again.
        self.groupsChanged.emit()
        if group_id >= 0:
            self._db.add_to_group(group_id, key)
            self.groupsChanged.emit()
            self._set_status(f"added {label} to {self._group_name(group_id)}, "
                             f"which is the only place it shows")
            self.refresh()
        elif platform == "twitch":
            # Said plainly. A Twitch channel adding no rows to the feed looks
            # broken otherwise.
            self._set_status(f"added {label}, which will show in the live bar rather than the feed")
            self.reload()
        else:
            self._set_status(f"added {label}, fetching videos")
            self.refresh()
        self._start_next_add()

    def _on_channel_failed(self, message: str) -> None:
        self._adding = -1
        self._set_add("failed", f"Nothing came back for that one. {message}")
        self._set_status(f"could not add that channel, {message}")
        self._start_next_add()

    def _group_name(self, group_id: int) -> str:
        for row in self._db.groups():
            if int(row["id"]) == group_id:
                return str(row["name"])
        return "the group"

    def _set_import(self, state: str, message: str) -> None:
        self._import_state = state
        self._import_message = message
        self.importChanged.emit()

    def _on_imported(self, found: int, added: int) -> None:
        self._set_import("done", f"{found} subscriptions found, {added} newly tracked")
        self._set_status(f"{found} subscriptions found, {added} newly tracked")
        self.reload()
        if added:
            self.refresh()

    def _on_import_failed(self, message: str) -> None:
        self._set_import("failed", message)
        self._problems.append(f"subscription import, {message}")
        self.problemsChanged.emit()
        self._set_status(f"could not import the subscriptions, {message}")

    def _on_twitch_code(self, user_code: str, address: str) -> None:
        """The address already contains the code, so the browser lands on a
        page with nothing to type."""
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
        self._live_ready = True
        self.liveChanged.emit()
        self.twitchChanged.emit()

    def _on_live_failed(self, message: str) -> None:
        # A check that failed has still answered as far as the bar is
        # concerned. Waiting for a success that may never come would keep
        # whatever is live hidden for the rest of the evening.
        self._live_is_ready()
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
        # Cancelled or finished with nothing to say, the bar has still waited
        # long enough. Anything else leaves it folded away for good.
        self._live_is_ready()
        self._set_live_checking(False)

    def _judge_finished_streams(self) -> None:
        """Mark the streams whose stopped position turned out to be most of
        them.

        Nothing is marked while a stream is live, so this is where a stream
        gets its answer: where playback stopped, over the length the recording
        ended up being. Where you joined and how long you sat there say
        nothing; the position you left at is the whole of it.

        mpv keeps that position itself, in the same resume file that draws the
        bar under a card, so there is nothing to record while watching.
        """
        rows = self._db.streams_to_judge()
        if not rows:
            return
        urls = {row["key"]: ids.watch_url(row["platform"], row["ext_id"]) for row in rows}
        found = mpv_progress.positions_for(list(urls.values()),
                                           self._model.watch_later_dir)
        marked = 0
        for row in rows:
            seconds = found.get(urls[row["key"]])
            if not seconds:
                continue
            share = min(1.0, seconds / row["duration_s"])
            if share >= self._cfg.watched_threshold:
                self._db.set_watched(row["key"], share, "mpv")
                marked += 1
        if marked:
            self._set_status(f"{marked} finished streams marked watched")

    def _on_watched(self, key: str, progress: float) -> None:
        self._db.set_watched(key, progress, "mpv")
        self.reload()
        self._set_status(f"marked watched at {int(progress * 100)} percent")

    def _on_player_failed(self, message: str) -> None:
        # Nothing is starting after all, so the chip goes at once instead of
        # sitting on the card for half a minute.
        self._set_starting("")
        self._problems.append(message)
        self.problemsChanged.emit()
        self._set_status(message)

    def _on_poll_failure(self, source: str, message: str) -> None:
        self._problems.append(f"feed {source}: {message}")
        self.problemsChanged.emit()

    def _on_poll_finished(self, channels: int, touched: int, failures: int) -> None:
        self._set_busy(False)
        self._judge_finished_streams()
        self._fill_lengths()
        self.reload()
        suffix = f", {failures} failed" if failures else ""
        self._set_status(f"{channels} channels checked, {touched} rows updated{suffix}")

    def _fill_lengths(self) -> None:
        """Close the gap RSS leaves in the lengths, a channel at a time.

        Off the end of a poll rather than on a timer of its own, so it can
        never run beside one and the requests stay counted together.
        """
        if not self._cfg.fill_lengths:
            return
        if self._lengths is not None and self._lengths.isRunning():
            return
        self._lengths = LengthFiller(self._db, self._cfg,
                                     self._cfg.length_channels_per_tick, self)
        self._lengths.filled.connect(self._on_lengths_filled)
        self._lengths.failed.connect(self._on_lengths_failed)
        self._launch(self._lengths)

    def _on_lengths_filled(self, rows: int, channels: int) -> None:
        if rows:
            self.reload()

    def _on_lengths_failed(self, message: str) -> None:
        # One channel's tabs not answering is not worth a banner. The channel
        # is left unstamped and comes round again.
        self._set_status(message)
