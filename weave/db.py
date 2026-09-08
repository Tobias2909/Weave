"""SQLite storage.

One connection per thread, because SQLite objects cannot cross threads and the
poller runs off the GUI thread. WAL is on so a poll writing does not block the
UI reading.

Feed rows are kept forever. They are a few hundred bytes each, and throwing
them away would mean a video that scrolled out of a channel's 15 entry RSS
window could never be found again.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 38

# A Short is at most three minutes. Anything longer needs no further test.
SHORTS_CEILING_S = 180

# The channel a video points at when nothing knows which channel it came from.
# A history row carries no channel whatsoever, measured, and a video row has to
# name one, so those all point here. The key is the empty string because that
# is already what every list reports for "no channel", so the grid and the
# menus treat such a video exactly as they treated it before it was stored.
NO_CHANNEL = ""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per endpoint per minute, counting the requests sent to it. The
-- feed endpoint answers a burst with a refusal rather than with a busy
-- signal, so the only way to stay under its patience is to know how much has
-- been asked recently. Buckets rather than one row per request keeps this to
-- sixty rows an hour per endpoint, and a rolling window is one SUM.
CREATE TABLE IF NOT EXISTS request_budget (
    endpoint TEXT    NOT NULL,
    minute   INTEGER NOT NULL,          -- unix time divided by sixty
    count    INTEGER NOT NULL DEFAULT 0,
    refused  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (endpoint, minute)
);

-- Lists that come from YouTube rather than from the channels you track: what
-- it suggests, and what you have watched. Kept apart from videos on purpose,
-- since these are mostly from channels that are not tracked and writing them
-- in there would make them look like something followed. One table with a
-- kind rather than one table each, because they are the same shape and the
-- same operations.
CREATE TABLE IF NOT EXISTS cached_videos (
    kind           TEXT NOT NULL,          -- recommended or history
    ext_id         TEXT NOT NULL,
    title          TEXT NOT NULL,
    channel_name   TEXT,
    channel_ext_id TEXT,
    duration_s     INTEGER,
    thumbnail_url  TEXT,
    views          INTEGER,
    published_at   INTEGER,                 -- approximate, from "3 weeks ago"
    position       INTEGER NOT NULL,
    seen_at        INTEGER NOT NULL,
    PRIMARY KEY (kind, ext_id)
);

-- YouTube's own playlists, as opposed to boxes, which are this application's.
-- Their videos live here rather than in videos for the same reason as the
-- recommendations: a playlist is full of channels you may not track.
CREATE TABLE IF NOT EXISTS playlists (
    ext_id     TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0,
    items_at   INTEGER,                    -- when its contents were last read
    hidden     INTEGER NOT NULL DEFAULT 0, -- kept, but out of the sidebar
    seen_at    INTEGER NOT NULL
);

-- What a channel's playlists tab lists. Names only: the listing carries no
-- video count, and a real one is a request per playlist, so a count appears
-- once a playlist has been opened and its contents are known.
CREATE TABLE IF NOT EXISTS channel_playlists (
    channel_key TEXT NOT NULL REFERENCES channels(key) ON DELETE CASCADE,
    ext_id      TEXT NOT NULL,
    title       TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    seen_at     INTEGER NOT NULL,
    PRIMARY KEY (channel_key, ext_id)
);

-- Who made a video, for videos that are not in the videos table and never
-- will be. A history row says nothing about its channel, measured, and the
-- listing it came from is replaced wholesale every time it is read, so an
-- answer worth one request has to live somewhere that survives that.
CREATE TABLE IF NOT EXISTS video_owners (
    ext_id         TEXT PRIMARY KEY,
    channel_name   TEXT NOT NULL,
    handle         TEXT,
    channel_ext_id TEXT,
    seen_at        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id    TEXT NOT NULL REFERENCES playlists(ext_id) ON DELETE CASCADE,
    ext_id         TEXT NOT NULL,
    title          TEXT NOT NULL,
    channel_name   TEXT,
    channel_ext_id TEXT,
    duration_s     INTEGER,
    thumbnail_url  TEXT,
    views          INTEGER,
    published_at   INTEGER,                 -- approximate, from "3 weeks ago"
    position       INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, ext_id)
);

-- What has been listened to. Two sources meet here. A row written by Weave
-- knows exactly when it was played, and one read from the music service knows
-- only the phrase it gave, such as last week, so that phrase is kept as it was
-- rather than being turned into a time it does not really have. A song played
-- here wins over the service's memory of it.
CREATE TABLE IF NOT EXISTS music_history (
    ext_id        TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    artist        TEXT,
    thumbnail_url TEXT,
    duration_s    INTEGER,
    played_at     INTEGER,
    played_text   TEXT,
    plays         INTEGER NOT NULL DEFAULT 0,
    position      INTEGER NOT NULL DEFAULT 0,
    source        TEXT NOT NULL DEFAULT 'weave'
);

CREATE TABLE IF NOT EXISTS channels (
    key            TEXT PRIMARY KEY,          -- yt:UC... or twitch:login
    platform       TEXT NOT NULL,
    ext_id         TEXT NOT NULL,
    title          TEXT,
    avatar_url     TEXT,
    added_at       INTEGER NOT NULL,
    last_polled_at INTEGER,
    last_error     TEXT
);

CREATE TABLE IF NOT EXISTS groups (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id    INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    channel_key TEXT    NOT NULL REFERENCES channels(key) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, channel_key)
);

-- A box is a hand picked collection of individual videos, as opposed to a
-- group, which collects whole channels. Named "box" rather than "playlist"
-- because real YouTube playlists arrive later and two things called playlist
-- in one sidebar would be confusing.
CREATE TABLE IF NOT EXISTS boxes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS box_items (
    box_id    INTEGER NOT NULL REFERENCES boxes(id) ON DELETE CASCADE,
    video_key TEXT    NOT NULL REFERENCES videos(key) ON DELETE CASCADE,
    position  INTEGER NOT NULL DEFAULT 0,
    added_at  INTEGER NOT NULL,
    PRIMARY KEY (box_id, video_key)
);

CREATE TABLE IF NOT EXISTS videos (
    key           TEXT PRIMARY KEY,           -- yt:<id> or twitch:<login>
    platform      TEXT NOT NULL,
    ext_id        TEXT NOT NULL,
    channel_key   TEXT NOT NULL REFERENCES channels(key) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    published_at  INTEGER,
    thumbnail_url TEXT,
    duration_s    INTEGER,                    -- NULL until a subs sweep fills it
    views         INTEGER,
    likes         INTEGER,
    is_short      INTEGER,                    -- NULL means not classified yet
    live_status   TEXT,                       -- NULL, is_live or was_live
    first_seen_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS videos_published  ON videos (published_at DESC);
CREATE INDEX IF NOT EXISTS videos_by_channel ON videos (channel_key);

-- Who is live right now. Rewritten wholesale on every check rather than
-- updated, because a channel going offline is the absence of a row and there
-- is nothing to update it from.
CREATE TABLE IF NOT EXISTS live_streams (
    channel_key   TEXT PRIMARY KEY,
    platform      TEXT NOT NULL,
    login         TEXT,
    display_name  TEXT,
    title         TEXT,
    game          TEXT,
    viewers       INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT,
    thumbnail_url TEXT,
    seen_at       INTEGER NOT NULL
);

-- Things to listen to that are not in any library. A round the clock stream is
-- the obvious case, since it is returned to rather than searched for.
CREATE TABLE IF NOT EXISTS audio_sources (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    label    TEXT NOT NULL,
    url      TEXT NOT NULL UNIQUE,
    live     INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    added_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS watched (
    video_key  TEXT PRIMARY KEY,
    watched_at INTEGER NOT NULL,
    progress   REAL,                           -- fraction of the duration seen
    source     TEXT NOT NULL                   -- mpv, manual or seed
);
"""


# What "owed a length" means, in one place, so the worker, the page and the
# doctor cannot disagree about it. A Short never reaches a feed. A stream that
# is on the air has no length yet, and an announcement that has not started has
# none to have; both would keep a channel owed for ever and the doctor warning
# about a gap nothing can close. An announcement whose start has passed is
# owed one, since by then the tab listing knows how long it ran.
_OWED_A_LENGTH = (
    "v.duration_s IS NULL AND COALESCE(v.is_short, 0) = 0 "
    "AND COALESCE(v.live_status, '') <> 'is_live' "
    "AND NOT (COALESCE(v.live_status, '') = 'is_upcoming' "
    "         AND COALESCE(v.scheduled_at, CAST(strftime('%s', 'now') AS INTEGER) + 1) "
    "             > CAST(strftime('%s', 'now') AS INTEGER))"
)


@dataclass(frozen=True)
class FeedTiers:
    """How often a channel is asked, decided by how recently it posted.

    Polling every channel at the same rate spends most of the budget on
    channels that have not posted in years, which is what made a full lap take
    over an hour. A channel that posts weekly is worth asking every quarter of
    an hour; one that has been silent for three months is not.

    The intervals are in seconds and the boundaries in days. The shortest one
    is a quarter of an hour because that is what the feed itself declares in
    its Cache-Control header, so asking again sooner returns the same cached
    body.
    """

    hot_days: int = 7
    warm_days: int = 30
    cold_days: int = 90
    hot_s: int = 900
    warm_s: int = 3600
    cold_s: int = 21600
    frozen_s: int = 86400
    # A channel the subscriptions sweep has named within coverage_days is
    # asked no more often than covered_s, whatever its tier says, because the
    # sweep is what finds anything new from it and promotes it at once. The
    # tiered interval still wins where it is longer, so a dormant channel is
    # not asked more often than before.
    covered_s: int = 21600
    coverage_days: int = 30


@dataclass(frozen=True)
class VideoRow:
    """One video as a source produced it. Fields a source cannot know are None
    and get filled in by a later pass."""

    platform: str
    ext_id: str
    channel_key: str
    title: str
    published_at: int | None = None
    thumbnail_url: str | None = None
    duration_s: int | None = None
    views: int | None = None
    likes: int | None = None
    live_status: str | None = None
    # Known at insert time now that each tab has its own feed. None means the
    # source could not say, which only happens on the mixed channel feed.
    is_short: bool | None = None
    # The name of the channel that posted it, when the source happened to say.
    # Only used to name a channel Weave has never heard of, which a feed can
    # hand over, so it is never written over a name already stored.
    channel_title: str | None = None

    @property
    def key(self) -> str:
        prefix = "yt" if self.platform == "youtube" else "twitch"
        return f"{prefix}:{self.ext_id}"


# Columns added after the first release. Listed rather than folded into the
# schema above so an existing database gains them too.
# What a group can be told to show. Named here rather than as strings in the
# window, since the value is stored and a typo would be stored with it.
GROUP_SHOWS_ALL = "all"
GROUP_SHOWS_VIDEOS = "videos"
GROUP_SHOWS_STREAMS = "streams"
GROUP_SHOWS = (GROUP_SHOWS_ALL, GROUP_SHOWS_VIDEOS, GROUP_SHOWS_STREAMS)


_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("channels", "last_classified_at", "INTEGER"),
    ("channels", "banner_url", "TEXT"),
    ("channels", "follower_count", "INTEGER"),
    ("channels", "details_fetched_at", "INTEGER"),
    ("videos", "dislikes", "INTEGER"),
    ("videos", "dislikes_at", "INTEGER"),
    ("videos", "live_viewers", "INTEGER"),
    ("audio_sources", "thumbnail", "TEXT"),
    # Which feed address answers for this channel. The per tab playlist feed
    # is the default; a channel with no long form tab falls back to the mixed
    # channel feed and is remembered so the discovery is not repeated.
    ("channels", "feed_variant", "TEXT"),
    # Taken out of All by hand, which is a decision rather than a state. Every
    # other way in_all is written raises it, and without this the next
    # subscription import would quietly put back exactly the channels somebody
    # had just taken out.
    ("channels", "left_all", "INTEGER NOT NULL DEFAULT 0"),
    # A video that arrived from a channel's streams tab with nothing watching
    # it, which is what an announcement looks like the moment it is published
    # and what an ordinary video never looks like there. One question settles
    # it, and this is the note that one is owed.
    ("videos", "stream_pending", "INTEGER"),
    # Behind a channel's membership. Nothing here can be opened without one,
    # so there is no live state to learn, no length to fill in and nothing to
    # hand mpv. The card says so and the press is refused, rather than the
    # player being handed an address that answers with a sentence about
    # joining the channel.
    ("videos", "members_only", "INTEGER NOT NULL DEFAULT 0"),
    # Where a playlist row came from. mine is one of yours, read from your own
    # playlists feed. channel is one you kept off a channel page, which your
    # feed knows nothing about and must never delete. temp is one you opened
    # to look at, which needs a row of its own only because a playlist's items
    # hang off one, and which is swept up later.
    ("playlists", "origin", "TEXT NOT NULL DEFAULT 'mine'"),
    ("channels", "playlists_at", "INTEGER"),
    # Which half of a group is being looked at: all of it, the videos or the
    # streams. Kept per group rather than as one setting for all of them,
    # because a group of people who stream and a group of people who do not
    # are not looked at the same way.
    ("groups", "shows", f"TEXT NOT NULL DEFAULT '{GROUP_SHOWS_ALL}'"),
    # When this channel's stored videos were last read against its own tab
    # listings to fill in the lengths RSS cannot carry. A stamp rather than a
    # flag, so the gap can be looked at again once there is a reason to.
    ("channels", "lengths_at", "INTEGER"),
    # When the subscriptions sweep last named this channel. A channel the
    # sweep covers has anything new from it arrive through the sweep, which
    # promotes it, so its own feed is asked only now and then to refresh the
    # counts rather than on the tiered schedule. Measured before this: the
    # hot tier alone was over two hundred feed requests a quarter of an hour,
    # every one of them re-reading fifteen entries the sweep had already seen.
    ("channels", "sweep_seen_at", "INTEGER"),
    # The first video's frame, which the playlists tab hands over with the
    # names. A playlist has no picture of its own here for the same reason it
    # has no count: asking one for either is a call each.
    ("channel_playlists", "thumbnail_url", "TEXT"),
    # A long playlist list buries everything under it, so each one can be put
    # out of the way without being forgotten.
    ("playlists", "hidden", "INTEGER NOT NULL DEFAULT 0"),
    # The suggestions carry a view count. The history and a playlist do not,
    # measured, so it stays empty for those rather than being invented.
    ("cached_videos", "views", "INTEGER"),
    # A playlist entry carries a view count as well, measured.
    ("playlist_items", "views", "INTEGER"),
    # Approximate, since a listing gives the age of a video as a phrase rather
    # than a date. It is what every other client shows for these.
    ("cached_videos", "published_at", "INTEGER"),
    ("playlist_items", "published_at", "INTEGER"),
    # Whether this is a channel that is followed. A video saved out of the
    # suggestions, the history or a search brings its channel along so the
    # card has a name and a picture, but that channel is not something to
    # poll, to count, or to pour into the feed. Existing rows default to
    # followed, since everything stored before this was added by hand.
    ("channels", "tracked", "INTEGER NOT NULL DEFAULT 1"),
    # When an announced stream or premiere is due to begin. Such a video sits
    # in a listing like any other and cannot be played yet, so the time is kept
    # to say so on the card rather than letting a press reach the player.
    ("videos", "scheduled_at", "INTEGER"),
    # How many entries of a playlist could not be shown because they are
    # private or gone. Counted rather than guessed, so the foot of the list can
    # say what is missing instead of the list quietly being short.
    ("playlists", "skipped", "INTEGER NOT NULL DEFAULT 0"),
    # Whether this playlist holds music. A press on one of its videos then
    # goes to the music player rather than to mpv, which is what the headphone
    # on the card does everywhere else.
    ("playlists", "is_music", "INTEGER NOT NULL DEFAULT 0"),
    # A song kept on purpose. It sits beside what was played rather than in a
    # table of its own, because a favourite is one of these songs and copying
    # the same row into two places is how the two of them come apart.
    ("music_history", "favorite", "INTEGER NOT NULL DEFAULT 0"),
    ("music_history", "favorite_at", "INTEGER"),
    # Whether this channel belongs in All. Following one by name puts it there;
    # putting one in a group only asks for it inside that group, so a channel
    # reached that way is polled and shows in its group without pouring into
    # the feed. Existing rows default to being in All, since everything stored
    # before this was followed by hand.
    ("channels", "in_all", "INTEGER NOT NULL DEFAULT 1"),
    # A search result and a suggestion can be a stream that is on now or one
    # that is announced, exactly as a feed row can, and the flat listing says
    # which without being asked twice. Kept so the card can badge it and the
    # play path can refuse to hand an announced stream to a player.
    ("cached_videos", "live_status", "TEXT"),
    ("cached_videos", "scheduled_at", "INTEGER"),
    # Whether this channel has a streams tab. NULL means nobody has looked
    # yet, which is what gets it looked at. Before this the answer was
    # inferred from having stored a stream already, and the only thing that
    # stores one for a channel nobody is subscribed to is that very tab, so a
    # channel added by hand never had its streams read at all.
    ("channels", "streams", "INTEGER"),
    # How many rounds in a row the long form feed answered 404 for this
    # channel. A missing long form tab and the feed endpoint refusing us look
    # exactly alike, and the endpoint refuses in bursts, so one 404 says
    # nothing. Counted per round rather than per request, and cleared the
    # moment the tab answers again.
    ("channels", "long_form_404s", "INTEGER NOT NULL DEFAULT 0"),
    # When the long form feed was last asked for a channel that had fallen
    # back to the mixed one. The fallback is a guess about a tab that may
    # appear later, so it is re-tested rather than believed for ever.
    ("channels", "variant_checked_at", "INTEGER"),
    # When this channel's Shorts tab was last read. Only a channel on the
    # mixed feed needs it: that feed says nothing about the kind of what it
    # carries, so the Shorts tab is what tells its rows apart.
    ("channels", "shorts_sweep_at", "INTEGER"),
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _migrate(self) -> None:
        """Create what is missing, then apply column additions in order.

        Additions are done by inspecting the table rather than by trusting the
        recorded version, so a database that was created at an older version
        and a database that was half upgraded both end up in the same place.
        """
        with self.conn as conn:
            conn.executescript(_SCHEMA)
            for table, column, definition in _ADDED_COLUMNS:
                existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            was = int(row["value"]) if row else 0
            if was and was < 28:
                # Avatars asked for at their original size. Most are harmless,
                # one measured 265 MB of pixels and could not be decoded at
                # all, and every one of them costs far more to fetch than it
                # is worth. The address carries the size, so it is rewritten
                # in place; the pictures come back at the next visit.
                conn.execute(
                    "UPDATE channels "
                    "SET avatar_url = substr(avatar_url, 1, length(avatar_url) - 3) || '=s512' "
                    "WHERE avatar_url LIKE '%=s0'")
            if was and was < 27:
                # A channel already seen streaming is known to stream, so it
                # keeps its answer rather than being asked again. Everything
                # else is left unknown and gets one look at its streams tab.
                conn.execute(
                    "UPDATE channels SET streams=1 WHERE key IN "
                    "(SELECT DISTINCT channel_key FROM videos WHERE live_status IS NOT NULL)")
            if was and was < 25:
                # in_all arrives set for every existing row, which is right for
                # the channels followed and wrong for the ones a saved video
                # brought along. Left as it came, putting one of those in a
                # group would raise it into All, which is the one thing the
                # flag exists to prevent.
                conn.execute("UPDATE channels SET in_all=0 WHERE tracked=0")
            if was and was < 24:
                # Pictures were stored as the window had them, wrapped for the
                # cache. Read back out they were wrapped a second time, which
                # leaves an empty address, so a kept song showed no picture.
                # The wrapper is taken back off what was stored that way.
                conn.execute(
                    "UPDATE music_history "
                    "SET thumbnail_url = substr(thumbnail_url, length('image://cached/') + 1) "
                    "WHERE thumbnail_url LIKE 'image://cached/%'")
            if was and was < 18:
                # Stored before there was anywhere to put a publish date, and
                # nothing revisits a row, so they are fetched again.
                conn.execute("DELETE FROM cached_videos")
                conn.execute("DELETE FROM meta WHERE key LIKE 'state.%_at'")
            if was and was < 17:
                # Suggestions stored before there was a column for it have no
                # view count and nothing will ever fill one in, since more is
                # added on the end rather than revisited. They are a snapshot
                # and are fetched again on the next visit, so they go.
                conn.execute("DELETE FROM cached_videos WHERE kind='recommended'")
                conn.execute("DELETE FROM meta WHERE key='state.recommended_at'")
            if was and was < 14:
                # Recommendations moved into the shared cached_videos table.
                # They are a snapshot and are fetched again, so the old rows
                # are not worth carrying across.
                conn.execute("DROP TABLE IF EXISTS recommended")
            if was and was < 10:
                # Banners stored before this were the uncropped artwork, which
                # is the wrong shape for the band it goes in and looks like a
                # picture that failed to load. Forgetting when the details were
                # fetched makes the next visit to that channel pick the crop.
                conn.execute(
                    "UPDATE channels SET details_fetched_at=NULL, banner_url=NULL "
                    "WHERE banner_url LIKE '%=s0'")
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    # ---- app state -------------------------------------------------------
    # Mutable UI state lives here rather than in config.toml, so the config
    # file stays something a human wrote and can still read.

    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (f"state.{key}",)).fetchone()
        return row["value"] if row else default

    def get_int(self, key: str, default: int = 0) -> int:
        """A stored number, or the default when nothing usable is stored.

        State is written as text, and a value that is not a whole number is
        a row this program never wrote, or wrote in a version that spelt it
        differently. Either way it is worth the default and not a crash on
        the way into the window.
        """
        raw = self.get_state(key)
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return default

    def image_max_mb(self, default: int) -> int:
        """The ceiling for the picture cache, in megabytes.

        The config carries the default and the settings page writes a choice
        here, because config.toml stays a file a person wrote and can still
        read. Only sanity is checked, not which sizes the window offers: the
        list belongs to the window, and a number typed in by hand is still a
        number this has to honour.
        """
        raw = self.get_state("image_max_mb")
        try:
            chosen = int(raw)
        except (TypeError, ValueError):
            return default
        return max(16, chosen)

    def set_image_max_mb(self, megabytes: int) -> None:
        self.set_state("image_max_mb", str(max(16, int(megabytes))))

    def set_state(self, key: str, value: str) -> None:
        with self.conn as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"state.{key}", value),
            )

    # ---- channels --------------------------------------------------------

    def add_channel(self, key: str, platform: str, ext_id: str, title: str | None = None,
                    avatar_url: str | None = None, in_all: bool = True) -> bool:
        """Follow a channel. Returns whether it was newly followed.

        COALESCE keeps a known title or avatar when the caller has none, so a
        source that carries less detail than an earlier one cannot erase it.

        A channel that was only carried along by a saved video becomes a
        followed one here, so a row that already existed but was not followed
        still counts as new.

        `in_all` false is a channel wanted inside a group and nowhere else. It
        is taken as the greater of what is asked and what is already there, so
        following a channel by name puts it in All and being added to a second
        group afterwards cannot take it back out again.
        """
        with self.conn as conn:
            existed = conn.execute(
                "SELECT tracked FROM channels WHERE key=?", (key,)).fetchone()
            conn.execute(
                "INSERT INTO channels(key, platform, ext_id, title, avatar_url, added_at, "
                "  tracked, in_all) "
                "VALUES(?,?,?,?,?,?,1,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "  title=COALESCE(excluded.title, channels.title), "
                "  avatar_url=COALESCE(excluded.avatar_url, channels.avatar_url), "
                "  tracked=1, "
                # Raised, as it always was, except where somebody has taken
                # this channel out of All themselves. Following it by name
                # again is what undoes that, through restore_to_all, and it is
                # the one thing that should.
                "  in_all=MAX(channels.in_all, "
                "            excluded.in_all * (1 - channels.left_all))",
                (key, platform, ext_id, title, avatar_url, int(time.time()), int(in_all)),
            )
            return existed is None or not existed["tracked"]

    def remember_channel(self, key: str, platform: str, ext_id: str,
                         title: str | None = None, avatar_url: str | None = None) -> None:
        """Keep a channel without following it.

        This is what a video saved out of the suggestions, the history or a
        search brings with it. The row exists so the card has a name and
        somewhere for a picture to live, and for nothing else: it is never
        polled, never counted among the channels followed, and its videos
        never reach the feed. A channel already followed stays followed, since
        the conflict clause leaves the flag alone.

        With no title given, one is looked for in the lists this channel was
        seen in, the same way following it by key alone does.
        """
        title = title or self._name_from_lists(ext_id)
        with self.conn as conn:
            conn.execute(
                "INSERT INTO channels(key, platform, ext_id, title, avatar_url, added_at, "
                "  tracked, in_all) "
                "VALUES(?,?,?,?,?,?,0,0) "
                "ON CONFLICT(key) DO UPDATE SET "
                "  title=COALESCE(excluded.title, channels.title), "
                "  avatar_url=COALESCE(excluded.avatar_url, channels.avatar_url)",
                (key, platform, ext_id, title, avatar_url, int(time.time())),
            )

    def track_channel(self, key: str, title: str | None = None,
                      avatar_url: str | None = None, in_all: bool = True) -> bool:
        """Follow a channel named only by its key.

        Reached from putting a channel in a group, where all that is on hand
        is the key off a video card. A name is looked for in the lists that
        card came from, so a channel followed this way is not left unnamed
        until something else fetches its details.
        """
        prefix, sep, ext_id = key.partition(":")
        if not sep or not ext_id:
            return False
        platform = "youtube" if prefix == "yt" else "twitch"
        return self.add_channel(key, platform, ext_id,
                                title or self._name_from_lists(ext_id), avatar_url,
                                in_all=in_all)

    def remove_from_all(self, key: str) -> bool:
        """Take a channel out of All and remember that it was taken out.

        Says whether that also stopped it being polled, which it does when no
        group holds it either. A channel with nowhere for its videos to appear
        is a channel there is no reason to ask about, and asking anyway is
        what the request budget is for.
        """
        with self.conn as conn:
            conn.execute("UPDATE channels SET in_all=0, left_all=1 WHERE key=?", (key,))
            held = conn.execute(
                "SELECT 1 FROM group_members WHERE channel_key=? LIMIT 1", (key,)).fetchone()
            if held is not None:
                return False
            conn.execute("UPDATE channels SET tracked=0 WHERE key=?", (key,))
            return True

    def restore_to_all(self, key: str) -> None:
        """Put a channel back in All, and forget that it was ever taken out.

        Following a channel by name is the way back in, so it also clears the
        decision. Nothing else does, which is what keeps an import from
        undoing it.
        """
        with self.conn as conn:
            conn.execute(
                "UPDATE channels SET in_all=1, left_all=0, tracked=1 WHERE key=?", (key,))

    def _name_from_lists(self, ext_id: str) -> str | None:
        """What the lists that come from YouTube call this channel, if any of
        them named it. The history names none of them, measured."""
        row = self.conn.execute(
            "SELECT channel_name FROM ("
            "  SELECT channel_name FROM cached_videos WHERE channel_ext_id=? "
            "  UNION ALL "
            "  SELECT channel_name FROM playlist_items WHERE channel_ext_id=?"
            ") WHERE channel_name IS NOT NULL LIMIT 1",
            (ext_id, ext_id)).fetchone()
        return row["channel_name"] if row else None

    def channels_missing_avatar(self, platform: str = "twitch") -> list[str]:
        return [row["ext_id"] for row in self.conn.execute(
            "SELECT ext_id FROM channels WHERE platform=? AND tracked=1 AND "
            "(avatar_url IS NULL OR avatar_url = '')", (platform,))]

    def channels_named_in(self, kind: str) -> list[str]:
        """Every channel behind a cached list, with a bare row kept for each
        so a picture that arrives later has somewhere to land.

        A suggestion names its channel but yt-dlp's flat listing of them
        never carries a picture, only a channel's own page does, which is
        why this is the list a picture fetch works its way through. The
        history is exactly the list left out here: measured, it names no
        channel at all.
        """
        rows = self.conn.execute(
            "SELECT DISTINCT channel_ext_id, channel_name FROM cached_videos "
            "WHERE kind=? AND channel_ext_id IS NOT NULL", (kind,))
        keys = []
        for row in rows:
            key = f"yt:{row['channel_ext_id']}"
            self.remember_channel(key, "youtube", row["channel_ext_id"], row["channel_name"])
            keys.append(key)
        return keys

    def channels_missing_picture(self, keys: list[str]) -> list[str]:
        """Which of these channels still have no picture to show."""
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        have = {row["key"] for row in self.conn.execute(
            f"SELECT key FROM channels WHERE key IN ({marks}) "
            f"AND avatar_url IS NOT NULL AND avatar_url != ''", keys)}
        return [key for key in keys if key not in have]

    def channels_due(self, tiers: FeedTiers, platform: str = "youtube",
                     limit: int | None = None, force: bool = False,
                     sweep_fresh: bool = False) -> list[sqlite3.Row]:
        """Channels that are past their own interval, most overdue first.

        With `sweep_fresh`, a channel the subscriptions sweep has named lately
        is asked only every `tiers.covered_s`: the sweep sees anything new
        from it first and promotes it, so its own feed is read on promotion
        and otherwise only to refresh the counts. Without it, when the sweep
        is stale or off, every channel is on its tiered interval as before.

        Only channels that are followed. One carried along by a video saved
        out of the suggestions is here for its name and its picture, and
        asking after it would spend a request on something never chosen.

        Each channel carries its own interval, derived from when it last
        published rather than stored, so it can never go stale against the
        videos table. A channel that has never been polled has no timestamp,
        counts as infinitely overdue and therefore goes first.

        `force` ignores the intervals but not the limit. The point of the
        limit is that a round is small enough not to look like a burst, and a
        deliberate refresh has the same endpoint on the other end.

        Each row also carries `last_published_at`, which is NULL for a channel
        nothing is stored from. That is a different thing from a channel that
        has published nothing lately, and the two want different treatment.
        """
        now = int(time.time())
        params = {
            "platform": platform,
            "now": now,
            "hot_cut": now - tiers.hot_days * 86400,
            "warm_cut": now - tiers.warm_days * 86400,
            "cold_cut": now - tiers.cold_days * 86400,
            "hot_s": tiers.hot_s,
            "warm_s": tiers.warm_s,
            "cold_s": tiers.cold_s,
            "frozen_s": tiers.frozen_s,
            "covered_s": tiers.covered_s,
            "seen_cut": now - tiers.coverage_days * 86400,
            "sweep_fresh": 1 if sweep_fresh else 0,
            "force": 1 if force else 0,
            "limit": limit if limit is not None else -1,
        }
        return list(self.conn.execute(
            """
            SELECT * FROM (
                SELECT t.*,
                       CASE
                           WHEN :sweep_fresh = 1 AND t.sweep_seen_at >= :seen_cut
                                THEN MAX(:covered_s, t.tier_s)
                           ELSE t.tier_s
                       END AS interval_s
                FROM (
                    SELECT c.*,
                           l.published AS last_published_at,
                           CASE
                               WHEN l.published IS NULL       THEN :frozen_s
                               WHEN l.published >= :hot_cut   THEN :hot_s
                               WHEN l.published >= :warm_cut  THEN :warm_s
                               WHEN l.published >= :cold_cut  THEN :cold_s
                               ELSE :frozen_s
                           END AS tier_s
                    FROM channels c
                    LEFT JOIN (SELECT channel_key, MAX(published_at) AS published
                                 FROM videos GROUP BY channel_key) l
                           ON l.channel_key = c.key
                    WHERE c.platform = :platform AND c.tracked = 1
                ) t
            )
            WHERE :force = 1
               OR COALESCE(last_polled_at, 0) <= :now - interval_s
            ORDER BY (:now - COALESCE(last_polled_at, 0)) - interval_s DESC
            LIMIT :limit
            """,
            params,
        ))

    def mark_sweep_seen(self, keys: Iterable[str]) -> int:
        """Remember that the subscriptions sweep named these channels.

        Named at all, not only with something new: the point is which channels
        the sweep watches, and it watches every channel whose videos it
        lists. A channel it stops naming for a month falls back to its tiered
        interval on its own, since the stamp ages out.
        """
        keys = list(keys)
        if not keys:
            return 0
        now = int(time.time())
        with self.conn as conn:
            before = conn.total_changes
            conn.executemany("UPDATE channels SET sweep_seen_at=? WHERE key=?",
                             [(now, key) for key in keys])
            return conn.total_changes - before

    def sweep_coverage(self, days: int) -> tuple[int, int]:
        """How many followed channels the sweep has named within `days`, and
        how many there are."""
        cut = int(time.time()) - max(1, days) * 86400
        row = self.conn.execute(
            "SELECT COALESCE(SUM(sweep_seen_at >= ?), 0), COUNT(*) FROM channels "
            "WHERE platform='youtube' AND tracked=1", (cut,)).fetchone()
        return int(row[0]), int(row[1])

    def raise_views(self, rows: list[tuple[str, int]]) -> int:
        """Apply the view counts the sweep carries, upwards only.

        The sweep rounds them, so a stored exact count could be replaced with
        a smaller round one and a card would count down. A count that is
        higher is newer, whatever its precision.
        """
        if not rows:
            return 0
        with self.conn as conn:
            before = conn.total_changes
            conn.executemany(
                "UPDATE videos SET views=? WHERE key=? AND (views IS NULL OR views < ?)",
                [(views, key, views) for key, views in rows])
            return conn.total_changes - before

    def promote_channels(self, keys: Iterable[str]) -> int:
        """Make these channels the next ones asked.

        Used when a cheap global check has already established that a channel
        has something new. Clearing the timestamp rather than setting a flag
        keeps one notion of due in the scheduler.
        """
        keys = list(keys)
        if not keys:
            return 0
        with self.conn as conn:
            before = conn.total_changes
            conn.executemany(
                "UPDATE channels SET last_polled_at=0 "
                "WHERE key=? AND tracked=1 AND last_polled_at IS NOT 0",
                [(key,) for key in keys],
            )
            return conn.total_changes - before

    def set_feed_variant(self, key: str, variant: str | None) -> None:
        """Remember which feed address answers for this channel.

        Clearing it clears the strikes against the long form tab as well. The
        two are one decision: the tab answered, so nothing is held against it.
        """
        with self.conn as conn:
            if variant is None:
                conn.execute(
                    "UPDATE channels SET feed_variant=NULL, long_form_404s=0 WHERE key=?",
                    (key,))
            else:
                conn.execute("UPDATE channels SET feed_variant=? WHERE key=?", (variant, key))

    def note_long_form_missing(self, key: str) -> int:
        """Count one round in which the long form feed answered 404, and say
        how many rounds in a row that now is.

        A 404 there is ambiguous. The channel may have no long form tab, or
        the endpoint may be refusing, which it does with a 404, in bursts, and
        for channels that are perfectly healthy. A burst lasts minutes; a
        missing tab lasts for ever. Counting rounds is what tells them apart,
        and it is what keeps a bad afternoon from moving a hundred channels
        onto the mixed feed, which carries Shorts.
        """
        with self.conn as conn:
            conn.execute(
                "UPDATE channels SET long_form_404s = COALESCE(long_form_404s, 0) + 1 "
                "WHERE key=?", (key,))
            row = conn.execute(
                "SELECT long_form_404s FROM channels WHERE key=?", (key,)).fetchone()
        return int(row["long_form_404s"]) if row else 0

    def clear_long_form_strikes(self, key: str) -> None:
        with self.conn as conn:
            conn.execute("UPDATE channels SET long_form_404s=0 WHERE key=?", (key,))

    def stamp_variant_checked(self, key: str) -> None:
        """Note that the long form tab of a fallen back channel was asked,
        whatever it answered, so it is not asked again for a while."""
        with self.conn as conn:
            conn.execute("UPDATE channels SET variant_checked_at=? WHERE key=?",
                         (int(time.time()), key))

    def stamp_shorts_sweep(self, key: str) -> None:
        with self.conn as conn:
            conn.execute("UPDATE channels SET shorts_sweep_at=? WHERE key=?",
                         (int(time.time()), key))

    def channels_that_stream(self, platform: str = "youtube") -> set[str]:
        """Channels whose streams tab is worth asking for.

        Streams live in their own tab, so a channel not asked for it shows a
        stream only once it has ended. Most channels have never streamed and
        asking all of them every round would double the request count for
        nothing, so the answer is remembered per channel.

        This is the ones known to stream, either because the tab answered once
        or because a stream of theirs has been stored from somewhere else. The
        ones nobody has looked at are a separate question, since asking those
        is a one off cost that has to be paced.
        """
        return {row[0] for row in self.conn.execute(
            "SELECT c.key FROM channels c "
            "WHERE c.platform=? AND c.tracked=1 "
            "  AND (c.streams=1 "
            "       OR EXISTS (SELECT 1 FROM videos v WHERE v.channel_key=c.key "
            "                  AND v.live_status IS NOT NULL))", (platform,))}

    def channels_not_asked_for_streams(self, platform: str = "youtube") -> set[str]:
        """Channels whose streams tab has never been asked for.

        Nothing else reveals that a channel streams. The subscriptions sweep
        only reaches the newest entries across every subscription, so over a
        long list a channel's stream may never appear in one, and a channel
        added by hand or reached through a group is not in a sweep at all.
        Waiting to be told therefore meant waiting for ever, which is why
        these are asked once and the answer kept.
        """
        return {row[0] for row in self.conn.execute(
            "SELECT c.key FROM channels c "
            "WHERE c.platform=? AND c.tracked=1 AND c.streams IS NULL "
            "  AND NOT EXISTS (SELECT 1 FROM videos v WHERE v.channel_key=c.key "
            "                  AND v.live_status IS NOT NULL)", (platform,))}

    def channel_stream_count(self, channel_key: str) -> int:
        """How many of this channel's stored videos are streams.

        What decides whether a channel page offers a streams half at all. A
        channel that has never streamed gets no button rather than a button
        onto an empty page, and plenty of channels whose streams tab answers
        at all answer it with nothing.
        """
        return int(self.conn.execute(
            f"SELECT COUNT(*) FROM videos v WHERE v.channel_key=? AND {self.IS_A_STREAM}",
            (channel_key,)).fetchone()[0])

    def set_channel_streams(self, key: str, streams: bool) -> None:
        """Remember whether this channel has a streams tab, so the question is
        asked once rather than every round."""
        with self.conn as conn:
            conn.execute("UPDATE channels SET streams=? WHERE key=?",
                         (1 if streams else 0, key))

    def remove_channel(self, key: str) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM channels WHERE key=?", (key,))

    def channels(self, platform: str | None = None,
                 include_untracked: bool = False,
                 in_all_only: bool = False) -> list[sqlite3.Row]:
        """The channels followed. This is the answer to how many there are, so
        the ones carried along by a saved video are left out unless asked
        for. A channel wanted inside a group and nowhere else is one of the
        channels followed, and it is counted here, but it is not one of the
        channels All is made of, which is what `in_all_only` asks for."""
        where = [] if include_untracked else ["tracked=1"]
        if in_all_only:
            where.append("in_all=1")
        args: Sequence[Any] = ()
        if platform:
            where.append("platform=?")
            args = (platform,)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        return list(self.conn.execute(
            "SELECT * FROM channels" + clause
            + " ORDER BY title IS NULL, title COLLATE NOCASE", args))

    def channel_has_videos(self, key: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM videos WHERE channel_key=? LIMIT 1", (key,)
        ).fetchone() is not None

    def set_channel_details(self, key: str, title: str | None, avatar_url: str | None,
                            banner_url: str | None, follower_count: int | None) -> None:
        """Store what the channel page needs. COALESCE again, so a call that
        found less than an earlier one cannot erase the difference."""
        with self.conn as conn:
            conn.execute(
                "UPDATE channels SET "
                "  title=COALESCE(?, title), avatar_url=COALESCE(?, avatar_url), "
                "  banner_url=COALESCE(?, banner_url), "
                "  follower_count=COALESCE(?, follower_count), details_fetched_at=? "
                "WHERE key=?",
                (title, avatar_url, banner_url, follower_count, int(time.time()), key),
            )

    def channel(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM channels WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        found = dict(row)
        found["video_count"] = int(self.conn.execute(
            "SELECT COUNT(*) FROM videos WHERE channel_key=? "
            "AND (is_short IS NULL OR is_short = 0)", (key,)).fetchone()[0])
        return found

    def channel_details_are_stale(self, key: str, interval_s: int = 604800) -> bool:
        row = self.conn.execute(
            "SELECT details_fetched_at FROM channels WHERE key=?", (key,)).fetchone()
        if not row:
            return False
        stamp = row["details_fetched_at"]
        return stamp is None or stamp <= int(time.time()) - max(0, interval_s)

    def mark_polled(self, key: str, error: str | None = None) -> None:
        with self.conn as conn:
            conn.execute(
                "UPDATE channels SET last_polled_at=?, last_error=? WHERE key=?",
                (int(time.time()), error, key),
            )

    # ---- videos ----------------------------------------------------------

    def upsert_videos(self, rows: Iterable[VideoRow]) -> int:
        """Insert new videos, refresh the volatile numbers on known ones.

        Title, views and likes are refreshed because they genuinely change.
        first_seen_at is never touched, so "new to me" stays stable even if a
        channel edits a title later.
        """
        now = int(time.time())
        rows = list(rows)
        payload = [
            (
                r.key, r.platform, r.ext_id, r.channel_key, r.title, r.published_at,
                r.thumbnail_url, r.duration_s, r.views, r.likes, r.live_status,
                None if r.is_short is None else int(r.is_short), now,
            )
            for r in rows
        ]
        if not payload:
            return 0
        # A video cannot be stored without its channel, and the channel a feed
        # names is not always one Weave knows. An artist channel's own live
        # streams playlist carries a stream owned by the linked label channel,
        # and the foreign key turned that into an exception that took the whole
        # poll down with it. So a stranger gets the same untracked row a video
        # saved out of a search brings with it: it has a name and somewhere
        # for a picture, it is never polled and it never reaches All. IGNORE
        # rather than a conflict clause, so a channel already followed keeps
        # every flag it has.
        strangers: dict[str, tuple[str, str | None]] = {}
        for r in rows:
            platform, title = strangers.get(r.channel_key, (r.platform, None))
            strangers[r.channel_key] = (platform, title or r.channel_title)
        with self.conn as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO channels(key, platform, ext_id, title, added_at, "
                "  tracked, in_all) VALUES(?,?,?,?,?,0,0)",
                [(key, platform, key.split(":", 1)[-1], title, now)
                 for key, (platform, title) in strangers.items()],
            )
            before = conn.total_changes
            conn.executemany(
                """
                INSERT INTO videos(key, platform, ext_id, channel_key, title, published_at,
                                   thumbnail_url, duration_s, views, likes, live_status,
                                   is_short, first_seen_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    title         = excluded.title,
                    published_at  = COALESCE(excluded.published_at, videos.published_at),
                    thumbnail_url = COALESCE(excluded.thumbnail_url, videos.thumbnail_url),
                    duration_s    = COALESCE(excluded.duration_s, videos.duration_s),
                    views         = COALESCE(excluded.views, videos.views),
                    likes         = COALESCE(excluded.likes, videos.likes),
                    live_status   = COALESCE(excluded.live_status, videos.live_status),
                    is_short      = COALESCE(videos.is_short, excluded.is_short)
                """,
                payload,
            )
            return conn.total_changes - before

    def channels_missing_lengths(self, limit: int = 2, older_than_s: int = 0,
                                 now: int | None = None) -> list[sqlite3.Row]:
        """Channels holding videos with no length, worst first.

        RSS carries no duration at all, and the only thing that fills one in is
        the subscriptions sweep, which reaches roughly the newest thousand
        videos across every subscription. Anything that arrived from a channel
        feed's fifteen entry window, or from opening a channel page, was
        already older than that when it was stored, and nothing ever asked a
        second time. So a library that has been running a while is mostly rows
        with no length, and it shows as the durations simply stopping partway
        down a feed.

        Shorts are left out. They never reach a feed, so a length for one is
        of no use to anybody, and they are a fifth of the gap.

        The count is what orders this, because one call answers a whole
        channel however many rows it is owed.

        `older_than_s` of zero means channels never read at all, not every
        channel: a cutoff of now is a cutoff every stamp is already older
        than, which would make the stamp do nothing and ask the same channel
        every poll for ever.
        """
        now = int(time.time()) if now is None else now
        cutoff = now - max(0, older_than_s)
        return list(self.conn.execute(
            f"""
            SELECT c.key, c.ext_id, c.streams, c.lengths_at,
                   COUNT(*) AS missing
              FROM videos v
              JOIN channels c ON c.key = v.channel_key
             WHERE {_OWED_A_LENGTH}
               AND c.platform = 'youtube'
               AND c.tracked = 1
               AND (c.lengths_at IS NULL
                    OR (? > 0 AND c.lengths_at <= ?))
             GROUP BY c.key
             ORDER BY missing DESC, c.key
             LIMIT ?
            """,
            (max(0, older_than_s), cutoff, max(1, limit)),
        ))

    def lengths_gap(self, older_than_s: int = 0, now: int | None = None) -> tuple[int, int]:
        """How many videos still have no length, and how many channels still
        have somewhere to look for one. What the page and the doctor say, so
        the filling can be watched rather than guessed at."""
        now = int(time.time()) if now is None else now
        cutoff = now - max(0, older_than_s)
        videos = self.conn.execute(
            f"SELECT COUNT(*) FROM videos v JOIN channels c ON c.key = v.channel_key "
            f"WHERE {_OWED_A_LENGTH} "
            f"AND c.platform = 'youtube' AND c.tracked = 1").fetchone()[0]
        channels = self.conn.execute(
            f"SELECT COUNT(DISTINCT c.key) FROM videos v JOIN channels c ON c.key = v.channel_key "
            f"WHERE {_OWED_A_LENGTH} "
            f"AND c.platform = 'youtube' AND c.tracked = 1 "
            f"AND (c.lengths_at IS NULL OR (? > 0 AND c.lengths_at <= ?))",
            (max(0, older_than_s), cutoff)).fetchone()[0]
        return int(videos), int(channels)

    def mark_lengths_read(self, channel_key: str, now: int | None = None) -> None:
        """This channel's gap has been looked at. Stamped whatever came back,
        so a channel whose remaining rows are private or deleted is not asked
        about for ever."""
        with self.conn as conn:
            conn.execute("UPDATE channels SET lengths_at=? WHERE key=?",
                         (int(time.time()) if now is None else now, channel_key))

    def fill_lengths(self, rows: Iterable[tuple[str, int | None, str | None]]) -> int:
        """Apply lengths, and live states, read off a channel's tab listings.

        Both are COALESCEd, so nothing already known is overwritten and a
        listing that says NA cannot blank a value out. The live state matters
        as much as the length here: a video read out of the streams tab is a
        stream, and rows that came in through RSS carry no live state at all,
        so without this they sit in the videos half of a group being streams.
        """
        rows = [row for row in rows if row[1] is not None or row[2] is not None]
        if not rows:
            return 0
        with self.conn as conn:
            before = conn.total_changes
            conn.executemany(
                "UPDATE videos SET duration_s = COALESCE(duration_s, ?), "
                "live_status = COALESCE(live_status, ?) "
                "WHERE key = ? AND (duration_s IS NULL OR live_status IS NULL)",
                [(duration, live, key) for key, duration, live in rows],
            )
            # A length past the Shorts ceiling settles that question too, the
            # same way the sweep's own fill does.
            conn.execute(
                "UPDATE videos SET is_short=0 WHERE is_short IS NULL AND duration_s > ?",
                (SHORTS_CEILING_S,),
            )
            return conn.total_changes - before

    def videos_without_a_length(self, channel_key: str, limit: int = 1000) -> set[str]:
        """The ids of this channel's stored videos that have no length, so a
        listing is only asked to answer for rows that are owed one."""
        return {row["ext_id"] for row in self.conn.execute(
            f"SELECT v.ext_id FROM videos v WHERE v.channel_key=? AND {_OWED_A_LENGTH} "
            f"LIMIT ?", (channel_key, max(1, limit)))}

    def fill_details(self, rows: list[tuple[str, int | None, str | None, int | None]]) -> int:
        """Apply the durations, live flags and start times the subscriptions
        sweep found.

        Only fills what is missing. RSS never carries any of them, and a
        value already stored is not worth overwriting with the same thing.
        A stale scheduled_at left behind once a stream goes live is harmless,
        since the card only reads it while live_status is still is_upcoming.
        """
        if not rows:
            return 0
        with self.conn as conn:
            before = conn.total_changes
            conn.executemany(
                "UPDATE videos SET duration_s=COALESCE(duration_s, ?), "
                "live_status=COALESCE(?, live_status), "
                "scheduled_at=COALESCE(scheduled_at, ?) "
                "WHERE key=? AND (duration_s IS NULL OR live_status IS NOT ?)",
                [(duration, live, scheduled, key, live)
                 for key, duration, live, scheduled in rows],
            )
            # A duration past the Shorts ceiling settles the question with no
            # request at all, which is what keeps the redirect test to a
            # handful of videos instead of thousands.
            conn.execute(
                "UPDATE videos SET is_short=0 WHERE is_short IS NULL AND duration_s > ?",
                (SHORTS_CEILING_S,),
            )
            return conn.total_changes - before

    def set_dislikes(self, video_key: str, count: int | None) -> None:
        with self.conn as conn:
            conn.execute("UPDATE videos SET dislikes=?, dislikes_at=? WHERE key=?",
                         (count, int(time.time()), video_key))

    def video(self, key: str) -> dict | None:
        """One video with everything the detail panel shows.

        Falls back to the lists that came from YouTube, since a suggestion, a
        history entry or a playlist entry is a real video you can open and is
        not in the videos table on purpose. Those carry less, so the missing
        columns come back empty rather than absent.
        """
        row = self.conn.execute(
            "SELECT v.*, c.title AS channel_title, c.avatar_url, "
            "       w.video_key IS NOT NULL AS watched "
            "FROM videos v JOIN channels c ON c.key = v.channel_key "
            "LEFT JOIN watched w ON w.video_key = v.key WHERE v.key=?", (key,)).fetchone()
        return dict(row) if row else self.unstored_video(key)

    def unstored_video(self, key: str) -> dict | None:
        """A video known only from one of the lists YouTube gave us."""
        row = self.conn.execute(
            """
            SELECT 'yt:' || r.ext_id AS key, 'youtube' AS platform, r.ext_id AS ext_id,
                   COALESCE(c.key, IIF(r.channel_ext_id IS NULL, '',
                                       'yt:' || r.channel_ext_id)) AS channel_key,
                   r.title AS title,
                   r.published_at AS published_at, r.thumbnail_url AS thumbnail_url,
                   r.duration_s AS duration_s, r.views AS views,
                   NULL AS likes, NULL AS dislikes,
                   -- A suggestion or a history entry can be a stream that has
                   -- not begun, and the panel says when it does, so these two
                   -- are read rather than left empty the way the rest are.
                   r.live_status AS live_status, r.scheduled_at AS scheduled_at,
                   NULL AS is_short,
                   COALESCE(c.title, r.channel_name) AS channel_title,
                   c.avatar_url AS avatar_url,
                   w.video_key IS NOT NULL AS watched
            FROM cached_videos r
            LEFT JOIN channels c ON c.ext_id = r.channel_ext_id AND c.platform = 'youtube'
            LEFT JOIN watched w ON w.video_key = 'yt:' || r.ext_id
            WHERE r.ext_id = ?
            UNION ALL
            SELECT 'yt:' || i.ext_id, 'youtube', i.ext_id,
                   COALESCE(c.key, IIF(i.channel_ext_id IS NULL, '',
                                       'yt:' || i.channel_ext_id)), i.title,
                   i.published_at, i.thumbnail_url, i.duration_s, i.views,
                   -- A playlist entry carries neither of them.
                   NULL, NULL, NULL, NULL, NULL,
                   COALESCE(c.title, i.channel_name), c.avatar_url,
                   w.video_key IS NOT NULL
            FROM playlist_items i
            LEFT JOIN channels c ON c.ext_id = i.channel_ext_id AND c.platform = 'youtube'
            LEFT JOIN watched w ON w.video_key = 'yt:' || i.ext_id
            WHERE i.ext_id = ?
            LIMIT 1
            """,
            (key.split(":", 1)[-1], key.split(":", 1)[-1]),
        ).fetchone()
        return dict(row) if row else None

    def set_live_state(self, video_key: str, viewers: int | None, still_live: bool) -> None:
        """A stream that has stopped becomes an ordinary video rather than
        vanishing, so it stays in the feed and only leaves the live bar."""
        with self.conn as conn:
            conn.execute(
                "UPDATE videos SET live_viewers=?, live_status=? WHERE key=?",
                (viewers if still_live else None,
                 "is_live" if still_live else "was_live", video_key))

    def set_scheduled_at(self, video_key: str, starts_at: int | None) -> None:
        """When an announced stream is due, in real time rather than as the
        phrase the sweep hands over, which is nothing at all."""
        if starts_at is None:
            return
        with self.conn as conn:
            conn.execute("UPDATE videos SET scheduled_at=? WHERE key=?", (starts_at, video_key))

    def mark_streams_pending(self, keys: Iterable[str]) -> None:
        """Note that these are owed a question.

        Only ones nothing knows a live state for. A stream the sweep has
        already called live or ended is settled, and asking again would spend
        a request to be told what is already stored.
        """
        keys = list(keys)
        if not keys:
            return
        with self.conn as conn:
            conn.executemany(
                "UPDATE videos SET stream_pending=1 WHERE key=? AND live_status IS NULL",
                [(key,) for key in keys])

    def streams_to_settle(self, limit: int = 3) -> list[sqlite3.Row]:
        """The ones still owed that question, newest first, since a stream
        about to begin matters more than one from last week."""
        return list(self.conn.execute(
            "SELECT key, ext_id FROM videos WHERE stream_pending=1 AND members_only=0 "
            "ORDER BY published_at DESC NULLS LAST LIMIT ?", (limit,)))

    def set_members_only(self, key: str, members_only: bool = True) -> None:
        """Mark a video as behind the channel's membership.

        Written from the one place that can tell, the live check, because the
        feeds carry no sign of it at all. Once marked, nothing asks about it
        again: without a membership the answer cannot change and every ask
        would spend a request to be told the same thing.
        """
        with self.conn as conn:
            conn.execute("UPDATE videos SET members_only=? WHERE key=?",
                         (1 if members_only else 0, key))

    def settle_stream(self, key: str) -> None:
        with self.conn as conn:
            conn.execute("UPDATE videos SET stream_pending=NULL WHERE key=?", (key,))

    def set_upcoming(self, key: str, starts_at: int | None) -> None:
        """It has not begun. Said outright rather than through set_live_state,
        which only knows running and finished."""
        with self.conn as conn:
            conn.execute(
                "UPDATE videos SET live_status='is_upcoming', "
                "scheduled_at=COALESCE(?, scheduled_at), stream_pending=NULL WHERE key=?",
                (starts_at, key))

    def upcoming_without_start(self, limit: int = 3) -> list[sqlite3.Row]:
        """Announced streams whose start time nothing has learned yet.

        The subscriptions sweep reports the time as NA for every one of them,
        so the only way to a real time is to ask about the video itself, which
        is one request each and is why this is handed out a few at a time.
        """
        return list(self.conn.execute(
            "SELECT key, ext_id FROM videos "
            "WHERE live_status='is_upcoming' AND scheduled_at IS NULL AND members_only=0 "
            "ORDER BY published_at DESC LIMIT ?", (limit,)))

    def live_youtube(self, limit: int = 12) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT key, ext_id FROM videos WHERE live_status='is_live' "
            "ORDER BY live_viewers IS NULL DESC, published_at DESC LIMIT ?", (limit,)))

    def unknown_video_keys(self, keys: Iterable[str]) -> set[str]:
        """Which of these videos are not stored yet.

        Asked of the subscriptions sweep's output, which is how one call over
        every subscription turns into a list of the channels worth asking.
        """
        keys = list(keys)
        if not keys:
            return set()
        known: set[str] = set()
        # Chunked because SQLite caps the number of bound parameters, and a
        # sweep can easily carry a thousand ids.
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            marks = ",".join("?" * len(chunk))
            known.update(row[0] for row in self.conn.execute(
                f"SELECT key FROM videos WHERE key IN ({marks})", chunk))
        return {key for key in keys if key not in known}

    # ---- request budget --------------------------------------------------

    def record_requests(self, endpoint: str, count: int = 1, refused: int = 0) -> None:
        """Add to this minute's bucket for an endpoint.

        Called for every outbound request, including the ones yt-dlp makes on
        our behalf, because the endpoint counts those the same way.
        """
        minute = int(time.time()) // 60
        with self.conn as conn:
            conn.execute(
                "INSERT INTO request_budget(endpoint, minute, count, refused) VALUES(?,?,?,?) "
                "ON CONFLICT(endpoint, minute) DO UPDATE SET "
                "  count = count + excluded.count, refused = refused + excluded.refused",
                (endpoint, minute, count, refused),
            )

    def requests_in_window(self, endpoint: str, window_s: int) -> tuple[int, int]:
        """How much has been asked of an endpoint recently, as sent and
        refused. The window is rounded out to whole minutes, which errs
        towards counting one bucket too many rather than one too few."""
        first = (int(time.time()) - max(0, window_s)) // 60
        row = self.conn.execute(
            "SELECT COALESCE(SUM(count), 0), COALESCE(SUM(refused), 0) "
            "FROM request_budget WHERE endpoint=? AND minute >= ?",
            (endpoint, first),
        ).fetchone()
        return int(row[0]), int(row[1])

    def resting_until(self, endpoint: str) -> int:
        """When this endpoint may be asked again, as a unix time.

        In the database rather than in the poller, because a restart begins a
        round at once and a rest that a restart walks past is no rest at all.
        """
        return self.get_int(f"rest.{endpoint}", 0)

    def rest_step(self, endpoint: str) -> int:
        """How many times in a row this endpoint has been rested. What makes
        the next rest longer than the last."""
        return self.get_int(f"rest_step.{endpoint}", 0)

    def rest_endpoint(self, endpoint: str, until: int, step: int) -> None:
        """Leave it alone until then, or clear a rest when until is 0."""
        self.set_state(f"rest.{endpoint}", str(int(until)))
        self.set_state(f"rest_step.{endpoint}", str(int(step)))

    def budget_frees_at(self, endpoint: str, window_s: int) -> int:
        """When the oldest bucket still inside the window leaves it, as a unix
        time. That is the soonest a full budget can have room again, and it is
        what the interface reports instead of simply doing nothing."""
        first = (int(time.time()) - max(0, window_s)) // 60
        row = self.conn.execute(
            "SELECT MIN(minute) FROM request_budget WHERE endpoint=? AND minute >= ?",
            (endpoint, first),
        ).fetchone()
        if row is None or row[0] is None:
            return int(time.time())
        return int(row[0]) * 60 + max(0, window_s) + 60

    def request_totals(self, window_s: int) -> list[sqlite3.Row]:
        first = (int(time.time()) - max(0, window_s)) // 60
        return list(self.conn.execute(
            "SELECT endpoint, SUM(count) AS count, SUM(refused) AS refused "
            "FROM request_budget WHERE minute >= ? GROUP BY endpoint ORDER BY count DESC",
            (first,),
        ))

    def prune_request_budget(self, older_than_s: int = 86400) -> int:
        cutoff = (int(time.time()) - max(0, older_than_s)) // 60
        with self.conn as conn:
            before = conn.total_changes
            conn.execute("DELETE FROM request_budget WHERE minute < ?", (cutoff,))
            return conn.total_changes - before

    # ---- groups ----------------------------------------------------------

    def create_group(self, name: str) -> int:
        with self.conn as conn:
            position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM groups").fetchone()[0]
            cursor = conn.execute(
                "INSERT INTO groups(name, position) VALUES(?, ?) "
                "ON CONFLICT(name) DO UPDATE SET name=excluded.name RETURNING id",
                (name, position),
            )
            return int(cursor.fetchone()[0])

    def delete_group(self, group_id: int) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM groups WHERE id=?", (group_id,))

    def rename_group(self, group_id: int, name: str) -> bool:
        """Give a group a new name. False when another group has it already,
        since a name is what tells the rows in the sidebar apart."""
        try:
            with self.conn as conn:
                conn.execute("UPDATE groups SET name=? WHERE id=?", (name.strip(), group_id))
        except sqlite3.IntegrityError:
            return False
        return True

    def set_group_order(self, ordered_ids: list[int]) -> None:
        with self.conn as conn:
            conn.executemany("UPDATE groups SET position=? WHERE id=?",
                             list(enumerate(ordered_ids)))

    def add_to_group(self, group_id: int, channel_key: str) -> bool:
        """Put a channel in a group, following it if it was not followed yet.

        This is the difference between a group and a box. A box holds the one
        video that was put in it, so the channel behind it stays a stranger. A
        group holds a whole channel and fills itself from what that channel
        posts, so a group of channels nothing ever asks after would sit empty
        for good.

        What it does not do is add to All. A group is a question about a few
        channels, and answering it by also pouring them into the feed makes
        the group the only place they are not. A channel already followed by
        name stays in All, since `in_all` is only ever raised.
        """
        if not self.track_channel(channel_key, in_all=False) \
                and not self.channel(channel_key):
            return False
        with self.conn as conn:
            conn.execute(
                "INSERT INTO group_members(group_id, channel_key) VALUES(?,?) "
                "ON CONFLICT DO NOTHING", (group_id, channel_key))
        return True

    def remove_from_group(self, group_id: int, channel_key: str) -> bool:
        """Take a channel out of a group. Says whether that also stopped it
        being followed.

        A channel that is in All was followed on its own account and stays
        followed. One that is not is here because a group asked for it, so
        once the last group lets go of it there is nothing left that shows it
        and nothing that should go on polling it. The row itself stays, the
        way a box's channel does, so a card that names it still has a name and
        a picture to show.
        """
        with self.conn as conn:
            conn.execute("DELETE FROM group_members WHERE group_id=? AND channel_key=?",
                         (group_id, channel_key))
            row = conn.execute(
                "SELECT in_all FROM channels WHERE key=? AND tracked=1", (channel_key,)
            ).fetchone()
            if row is None or row["in_all"]:
                return False
            held = conn.execute(
                "SELECT 1 FROM group_members WHERE channel_key=? LIMIT 1", (channel_key,)
            ).fetchone()
            if held is not None:
                return False
            conn.execute("UPDATE channels SET tracked=0 WHERE key=?", (channel_key,))
            return True

    def group_channels(self, group_id: int) -> list[sqlite3.Row]:
        """The channels in one group, for the window that manages it. Named
        ones first and alphabetically, since a channel added by id before its
        details arrived has no name yet and would otherwise sort under it."""
        return list(self.conn.execute(
            "SELECT c.* FROM group_members m JOIN channels c ON c.key = m.channel_key "
            "WHERE m.group_id=? ORDER BY c.title IS NULL, c.title COLLATE NOCASE",
            (group_id,)))

    def groups_holding(self, channel_key: str) -> list[int]:
        """Which lists show this channel, All among them as -1.

        All is not a row in the groups table and this does not pretend it is,
        but the window asks one question of both, so it answers for both.
        """
        held = [int(row["group_id"]) for row in self.conn.execute(
            "SELECT group_id FROM group_members WHERE channel_key=?", (channel_key,))]
        found = self.conn.execute(
            "SELECT in_all FROM channels WHERE key=? AND tracked=1", (channel_key,)).fetchone()
        if found and found["in_all"]:
            held.insert(0, -1)
        return held

    def move_group(self, group_id: int, delta: int) -> bool:
        """Shift a group one place in the sidebar.

        Positions are rewritten from the resulting order rather than swapped,
        so a list that was never ordered, or was left with gaps by a deletion,
        comes out consecutive either way.
        """
        order = [row["id"] for row in self.groups()]
        if group_id not in order:
            return False
        was = order.index(group_id)
        now = max(0, min(len(order) - 1, was + delta))
        if now == was:
            return False
        order.insert(now, order.pop(was))
        self.set_group_order(order)
        return True

    def groups(self) -> list[dict]:
        """Groups with their member and unwatched counts, in display order."""
        return [dict(row) for row in self.conn.execute(
            """
            SELECT g.id, g.name, g.position, g.shows,
                   (SELECT COUNT(*) FROM group_members m WHERE m.group_id = g.id) AS members,
                   (SELECT COUNT(*)
                      FROM videos v
                      JOIN group_members m ON m.channel_key = v.channel_key
                      LEFT JOIN watched w ON w.video_key = v.key
                     WHERE m.group_id = g.id AND w.video_key IS NULL
                       AND (v.is_short IS NULL OR v.is_short = 0)) AS unwatched
            FROM groups g
            ORDER BY g.position, g.id
            """
        )]

    def group_shows(self, group_id: int) -> str:
        """Which half of a group is being looked at.

        Its own query rather than a walk over groups(), since the feed asks
        this on every reload and groups() counts the unwatched rows of every
        group to answer. A group that has gone answers all, so a view left
        pointing at a deleted one shows a whole empty feed rather than a
        filtered one.
        """
        row = self.conn.execute("SELECT shows FROM groups WHERE id=?", (group_id,)).fetchone()
        found = row["shows"] if row else None
        return found if found in GROUP_SHOWS else GROUP_SHOWS_ALL

    def set_group_shows(self, group_id: int, shows: str) -> bool:
        """Look at all of a group, its videos or its streams. False when that
        is not one of the three, so a value nothing can read is never stored."""
        if shows not in GROUP_SHOWS:
            return False
        with self.conn as conn:
            conn.execute("UPDATE groups SET shows=? WHERE id=?", (shows, group_id))
        return True

    def group_by_name(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, name, position FROM groups WHERE name=? COLLATE NOCASE", (name,)
        ).fetchone()
        return dict(row) if row else None

    # ---- boxes -----------------------------------------------------------

    def create_box(self, name: str) -> int:
        name = name.strip()
        with self.conn as conn:
            position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM boxes").fetchone()[0]
            cursor = conn.execute(
                "INSERT INTO boxes(name, position, created_at) VALUES(?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET name=excluded.name RETURNING id",
                (name, position, int(time.time())),
            )
            return int(cursor.fetchone()[0])

    def rename_box(self, box_id: int, name: str) -> bool:
        """Give a box a new name. False when another box has it already."""
        try:
            with self.conn as conn:
                conn.execute("UPDATE boxes SET name=? WHERE id=?", (name.strip(), box_id))
        except sqlite3.IntegrityError:
            return False
        return True

    def delete_box(self, box_id: int) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM boxes WHERE id=?", (box_id,))

    def set_box_order(self, ordered_ids: list[int]) -> None:
        with self.conn as conn:
            conn.executemany("UPDATE boxes SET position=? WHERE id=?", list(enumerate(ordered_ids)))

    def add_to_box(self, box_id: int, video_key: str, row: dict | None = None) -> bool:
        """Newest addition goes last, so a box keeps the order things were put
        in rather than the order they were published.

        A box can only hold a video that is stored, which the foreign key
        enforces, so anything picked out of the suggestions, the history or a
        search is stored on the way in. `row` is for the one list that lives
        nowhere: a search result, which is only ever held in memory.

        Returns whether it went in. A key nothing knows anything about is
        reported rather than raised, which is reachable from the command line
        where a URL can name a video this install has never seen.
        """
        if not self.remember_video(video_key, row):
            return False
        try:
            with self.conn as conn:
                position = conn.execute(
                    "SELECT COALESCE(MAX(position), 0) + 1 FROM box_items WHERE box_id=?",
                    (box_id,)).fetchone()[0]
                conn.execute(
                    "INSERT INTO box_items(box_id, video_key, position, added_at) "
                    "VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                    (box_id, video_key, position, int(time.time())))
        except sqlite3.IntegrityError:
            return False
        return True

    def remember_video(self, video_key: str, row: dict | None = None) -> bool:
        """Store a video that came from a list rather than from a channel
        followed, so that something can hold on to it.

        The suggestions, the history and a search are all snapshots that get
        thrown away and fetched again, so a video picked out of one has to be
        copied somewhere that lasts before a box can point at it. Its channel
        comes along as a row that is not followed, which is where the name and
        the picture live; a history entry names no channel at all, measured,
        so those point at the one row that stands for none.

        Returns whether the video is stored afterwards. Already having it is
        success, and knowing nothing about the key is not.
        """
        if self.conn.execute("SELECT 1 FROM videos WHERE key=?", (video_key,)).fetchone():
            return True
        found = row if row is not None else self._loose_source(video_key)
        if not found or not found.get("ext_id"):
            return False
        channel_ext_id = found.get("channel_ext_id") or ""
        channel_key = f"yt:{channel_ext_id}" if channel_ext_id else NO_CHANNEL
        self.remember_channel(channel_key, "youtube", channel_ext_id,
                              found.get("channel_name") or found.get("channel_title"))
        self.upsert_videos([VideoRow(
            platform="youtube",
            ext_id=found["ext_id"],
            channel_key=channel_key,
            title=found.get("title") or found["ext_id"],
            published_at=found.get("published_at"),
            thumbnail_url=found.get("thumbnail_url"),
            duration_s=found.get("duration_s"),
            views=found.get("views"),
        )])
        return True

    def _loose_source(self, video_key: str) -> dict | None:
        """The row behind a video key in the lists that come from YouTube.

        Ordered so the suggestions and the history win over a playlist, since
        those carry a publish date and a view count and a playlist entry may
        not.
        """
        ext_id = video_key.split(":", 1)[-1]
        row = self.conn.execute(
            """
            SELECT ext_id, title, channel_name, channel_ext_id, duration_s,
                   thumbnail_url, views, published_at
            FROM cached_videos WHERE ext_id = ?
            UNION ALL
            SELECT ext_id, title, channel_name, channel_ext_id, duration_s,
                   thumbnail_url, views, published_at
            FROM playlist_items WHERE ext_id = ?
            LIMIT 1
            """,
            (ext_id, ext_id)).fetchone()
        return dict(row) if row else None

    def remove_from_box(self, box_id: int, video_key: str) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM box_items WHERE box_id=? AND video_key=?",
                         (box_id, video_key))

    def boxes(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            "SELECT b.id, b.name, b.position, "
            "  (SELECT COUNT(*) FROM box_items i WHERE i.box_id = b.id) AS items "
            "FROM boxes b ORDER BY b.position, b.id")]

    def move_box(self, box_id: int, delta: int) -> bool:
        """Shift a box one place in the sidebar, the way a group moves.

        Positions are rewritten from the resulting order rather than swapped,
        so a list that was never ordered, or was left with gaps by a deletion,
        comes out consecutive either way.
        """
        order = [row["id"] for row in self.boxes()]
        if box_id not in order:
            return False
        was = order.index(box_id)
        now = max(0, min(len(order) - 1, was + delta))
        if now == was:
            return False
        order.insert(now, order.pop(was))
        self.set_box_order(order)
        return True

    def box_by_name(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, name, position FROM boxes WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        return dict(row) if row else None

    def boxes_holding(self, video_key: str) -> list[int]:
        return [int(row["box_id"]) for row in self.conn.execute(
            "SELECT box_id FROM box_items WHERE video_key=?", (video_key,))]

    # ---- lists that come from YouTube ------------------------------------

    def remember_played(self, ext_id: str, title: str, artist: str | None,
                        thumbnail_url: str | None, duration_s: int | None = None) -> None:
        """Note that a song was played here, now.

        Playing the same song again moves it to the top and counts one more
        play rather than making a second row, which is what a list of what has
        been listened to is for. A song the service also remembers becomes
        ours, since our time is the exact one.
        """
        with self.conn as conn:
            conn.execute(
                "INSERT INTO music_history(ext_id, title, artist, thumbnail_url, "
                "                          duration_s, played_at, plays, source) "
                "VALUES(?,?,?,?,?,?,1,'weave') "
                "ON CONFLICT(ext_id) DO UPDATE SET "
                "  title=excluded.title, "
                "  artist=COALESCE(excluded.artist, music_history.artist), "
                "  thumbnail_url=COALESCE(excluded.thumbnail_url, music_history.thumbnail_url), "
                "  duration_s=COALESCE(excluded.duration_s, music_history.duration_s), "
                "  played_at=excluded.played_at, "
                "  plays=music_history.plays + 1, "
                "  source='weave'",
                (ext_id, title, artist, thumbnail_url, duration_s, int(time.time())),
            )

    def replace_service_music_history(self, rows: list[dict]) -> int:
        """Take the service's own memory of what was listened to.

        It is a snapshot, so it replaces the last one it gave. Songs played
        here are left alone, because their exact time is better than the
        phrase the service offers.
        """
        with self.conn as conn:
            # A favourite marked on one of these is kept. The rest are a
            # snapshot and are replaced.
            conn.execute(
                "DELETE FROM music_history WHERE source='youtube' AND favorite=0")
            written = 0
            for position, row in enumerate(rows):
                ext_id = (row.get("ext_id") or "").strip()
                if not ext_id:
                    continue
                written += conn.execute(
                    "INSERT INTO music_history(ext_id, title, artist, thumbnail_url, "
                    "                          duration_s, played_text, position, source) "
                    "VALUES(?,?,?,?,?,?,?,'youtube') "
                    "ON CONFLICT(ext_id) DO NOTHING",
                    (ext_id, row.get("title") or "", row.get("artist"),
                     row.get("thumbnail_url"), row.get("duration_s"),
                     row.get("played_text"), position),
                ).rowcount
            return written

    def fill_in_details(self, ext_id: str, views: int | None = None,
                        published_at: int | None = None,
                        duration_s: int | None = None) -> int:
        """Keep what was learned about a video that is only cached.

        A suggestion, a history entry and a playlist entry come from listings
        that carry almost nothing, but opening one fetches its metadata for
        the panel anyway. Writing that back means the card stops being the
        poorer of the two views of the same video. Nothing is overwritten with
        nothing, so a field the listing did have survives.
        """
        touched = 0
        with self.conn as conn:
            for table in ("cached_videos", "playlist_items"):
                # Only rows a value would really reach. An update that matches
                # a row and changes nothing still counts as one, and the view
                # was being drawn again for it, which throws away rows the
                # grid is still building.
                touched += conn.execute(
                    f"UPDATE {table} SET "
                    "  views = COALESCE(?, views), "
                    "  published_at = COALESCE(?, published_at), "
                    "  duration_s = COALESCE(?, duration_s) "
                    "WHERE ext_id = ? AND ("
                    "  (? IS NOT NULL AND views IS NULL) OR "
                    "  (? IS NOT NULL AND published_at IS NULL) OR "
                    "  (? IS NOT NULL AND duration_s IS NULL))",
                    (views, published_at, duration_s, ext_id,
                     views, published_at, duration_s)).rowcount
        return touched

    def set_music_favorite(self, ext_id: str, favorite: bool, title: str = "",
                           artist: str | None = None,
                           thumbnail_url: str | None = None,
                           duration_s: int | None = None) -> None:
        """Keep a song, or stop keeping it.

        A song that has never been played here has no row yet, so one is made
        for it. Nothing about what was played is disturbed either way.
        """
        now = int(time.time())
        with self.conn as conn:
            conn.execute(
                "INSERT INTO music_history(ext_id, title, artist, thumbnail_url, "
                "                          duration_s, favorite, favorite_at, source) "
                "VALUES(?,?,?,?,?,?,?,'weave') "
                "ON CONFLICT(ext_id) DO UPDATE SET "
                "  title=CASE WHEN excluded.title = '' THEN music_history.title "
                "             ELSE excluded.title END, "
                "  artist=COALESCE(excluded.artist, music_history.artist), "
                "  thumbnail_url=COALESCE(excluded.thumbnail_url, "
                "                         music_history.thumbnail_url), "
                "  duration_s=COALESCE(excluded.duration_s, music_history.duration_s), "
                "  favorite=excluded.favorite, "
                "  favorite_at=excluded.favorite_at",
                (ext_id, title, artist, thumbnail_url, duration_s,
                 1 if favorite else 0, now if favorite else None),
            )

    def is_music_favorite(self, ext_id: str) -> bool:
        row = self.conn.execute(
            "SELECT favorite FROM music_history WHERE ext_id=?", (ext_id,)).fetchone()
        return bool(row and row["favorite"])

    def music_favorites(self, limit: int = 500) -> list[sqlite3.Row]:
        """Every song kept, newest first, shaped like a feed row."""
        return list(self.conn.execute(
            """
            SELECT 'yt:' || h.ext_id     AS key,
                   'youtube'             AS platform,
                   h.ext_id              AS ext_id,
                   ''                    AS channel_key,
                   h.title               AS title,
                   h.favorite_at         AS published_at,
                   h.thumbnail_url       AS thumbnail_url,
                   h.duration_s          AS duration_s,
                   NULL                  AS views,
                   NULL                  AS likes,
                   NULL                  AS live_status,
                   h.artist              AS channel_title,
                   NULL                  AS avatar_url,
                   (w.video_key IS NOT NULL) AS watched
            FROM music_history h
            LEFT JOIN watched w ON w.video_key = 'yt:' || h.ext_id
            WHERE h.favorite = 1
            ORDER BY h.favorite_at DESC, h.title
            LIMIT ?
            """, (limit,)))

    def music_favorite_count(self) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM music_history WHERE favorite=1").fetchone()[0])

    def music_history(self, limit: int = 400) -> list[sqlite3.Row]:
        """Shaped like a feed row, so the same grid draws it.

        What was played here comes first, newest first, then what the service
        remembers in the order it gave. A song has no channel to open, so the
        artist stands in as the name and the key is left empty.
        """
        return list(self.conn.execute(
            """
            SELECT 'yt:' || h.ext_id     AS key,
                   'youtube'             AS platform,
                   h.ext_id              AS ext_id,
                   ''                    AS channel_key,
                   h.title               AS title,
                   h.played_at           AS published_at,
                   h.thumbnail_url       AS thumbnail_url,
                   h.duration_s          AS duration_s,
                   NULL                  AS views,
                   NULL                  AS likes,
                   NULL                  AS live_status,
                   h.artist              AS channel_title,
                   NULL                  AS avatar_url,
                   h.played_text         AS played_text,
                   h.source              AS source,
                   (w.video_key IS NOT NULL) AS watched
            FROM music_history h
            LEFT JOIN watched w ON w.video_key = 'yt:' || h.ext_id
            ORDER BY h.source = 'weave' DESC,
                     COALESCE(h.played_at, 0) DESC,
                     h.position
            LIMIT ?
            """, (limit,)))

    def music_history_count(self) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM music_history").fetchone()[0])

    RECOMMENDED = "recommended"
    HISTORY = "history"
    # One kind per set of words. A search is the same shape of thing as the
    # suggestions and the history, a snapshot of what one call answered, so it
    # lives in the same table rather than in a table of its own.
    SEARCH = "search:"

    @staticmethod
    def search_kind(query: str) -> str:
        """The key a set of words is stored under.

        Case and spacing do not change what comes back, so they do not change
        the key either, and searching for the same thing twice finds the rows
        already here.
        """
        return Database.SEARCH + " ".join(query.lower().split())

    def replace_cached(self, kind: str, rows: list[dict]) -> int:
        """Swap in a fresh set. Replacing rather than merging, since these are
        a snapshot of a moment and an old one has no value."""
        now = int(time.time())
        with self.conn as conn:
            conn.execute("DELETE FROM cached_videos WHERE kind=?", (kind,))
            conn.executemany(
                "INSERT INTO cached_videos(kind, ext_id, title, channel_name, "
                "  channel_ext_id, duration_s, thumbnail_url, views, published_at, "
                "  live_status, scheduled_at, position, seen_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                [(kind, row["ext_id"], row["title"], row.get("channel_name"),
                  row.get("channel_ext_id"), row.get("duration_s"),
                  row.get("thumbnail_url"), row.get("views"),
                  row.get("published_at"), row.get("live_status"),
                  row.get("scheduled_at"), index, now)
                 for index, row in enumerate(rows)],
            )
        if not kind.startswith(self.SEARCH):
            # A stamp per kind, and there is one kind per search, so this
            # would leave a row of state behind for every set of words ever
            # typed. The rows carry their own age.
            self.set_state(f"{kind}_at", str(now))
        return len(rows)

    def append_cached(self, kind: str, rows: list[dict]) -> int:
        """Add more onto the end, keeping what is already shown.

        Scrolling to the bottom asks for a later slice, so the new ones go
        after the old rather than replacing them. Returns how many were
        actually new, which is what says whether there is more to come.
        """
        if not rows:
            return 0
        now = int(time.time())
        with self.conn as conn:
            start = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM cached_videos WHERE kind=?",
                (kind,)).fetchone()[0]
            before = conn.total_changes
            conn.executemany(
                "INSERT INTO cached_videos(kind, ext_id, title, channel_name, "
                "  channel_ext_id, duration_s, thumbnail_url, views, published_at, "
                "  live_status, scheduled_at, position, seen_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                [(kind, row["ext_id"], row["title"], row.get("channel_name"),
                  row.get("channel_ext_id"), row.get("duration_s"),
                  row.get("thumbnail_url"), row.get("views"),
                  row.get("published_at"), row.get("live_status"),
                  row.get("scheduled_at"), start + index, now)
                 for index, row in enumerate(rows)],
            )
            return conn.total_changes - before

    def cached_flat(self, kind: str, limit: int = 400) -> list[dict]:
        """A cached set as the source handed it over, for decorate() to shape.

        The shaped form is what the grid draws, and cached() answers with that
        already. This is the other half, for a caller that goes on to join the
        rows to what is known here in the same way a fresh page is joined, so
        that a set served from here and a set just fetched are the same thing.
        """
        return [dict(row) for row in self.conn.execute(
            "SELECT ext_id, title, channel_name, channel_ext_id, duration_s, "
            "       thumbnail_url, views, published_at, live_status, scheduled_at "
            "FROM cached_videos WHERE kind=? ORDER BY position LIMIT ?",
            (kind, limit))]

    def forget_old_searches(self, older_than_s: int) -> int:
        """Drop the searches nobody has repeated in a long time.

        A search is kept so that asking the same thing again costs nothing,
        which is worth a great deal more than the few kilobytes it holds. It
        is not kept for ever, because a set of words typed once a year says
        nothing about what is on YouTube now.
        """
        cut = int(time.time()) - max(0, older_than_s)
        with self.conn as conn:
            before = conn.total_changes
            conn.execute(
                "DELETE FROM cached_videos WHERE kind LIKE ? AND seen_at <= ?",
                (self.SEARCH + "%", cut))
            return conn.total_changes - before

    def cached_count(self, kind: str) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM cached_videos WHERE kind=?", (kind,)).fetchone()[0])

    def cached(self, kind: str, limit: int = 400) -> list[sqlite3.Row]:
        """Shaped like a feed row so the same grid can draw it.

        The channel is joined in when it happens to be one that is known
        here, which is how one of these gets its icon, and left as whatever
        the source said otherwise. The key is worked out from the channel id
        even when there is no row, because that key is what putting the
        channel in a group is addressed to.

        The history says nothing whatsoever about the channel, measured: a row
        there carries an id, a title, a duration and a picture and no more. So
        a second join answers from the other end, on the video itself. A video
        already stored knows its channel, and that channel knows its name and
        its picture, which is how a history card gets a face without a single
        request. Whatever the listing itself said still wins, since that came
        from the same reading as the row.
        """
        return list(self.conn.execute(
            """
            SELECT 'yt:' || r.ext_id           AS key,
                   'youtube'                   AS platform,
                   r.ext_id                    AS ext_id,
                   COALESCE(c.key, v.channel_key, named.key,
                            IIF(o.channel_ext_id IS NULL, NULL, 'yt:' || o.channel_ext_id),
                            IIF(r.channel_ext_id IS NULL, '', 'yt:' || r.channel_ext_id)) AS channel_key,
                   r.title                     AS title,
                   COALESCE(r.published_at, v.published_at)   AS published_at,
                   COALESCE(r.thumbnail_url, v.thumbnail_url) AS thumbnail_url,
                   COALESCE(r.duration_s, v.duration_s)       AS duration_s,
                   COALESCE(r.views, v.views)                 AS views,
                   v.likes                     AS likes,
                   COALESCE(r.live_status, v.live_status)     AS live_status,
                   COALESCE(r.scheduled_at, v.scheduled_at)   AS scheduled_at,
                   COALESCE(c.title, r.channel_name, own.title,
                            named.title, o.channel_name)            AS channel_title,
                   COALESCE(c.avatar_url, own.avatar_url,
                            named.avatar_url)                       AS avatar_url,
                   w.video_key IS NOT NULL     AS watched
            FROM cached_videos r
            LEFT JOIN channels c ON c.ext_id = r.channel_ext_id AND c.platform = 'youtube'
            LEFT JOIN videos v ON v.ext_id = r.ext_id AND v.platform = 'youtube'
            LEFT JOIN channels own ON own.key = v.channel_key
            -- What one small call said about a video nothing else here knows.
            -- Its name is matched against the channels already here as well,
            -- which is how such a card gets a picture: a channel can be known
            -- while a video of theirs from years ago is not.
            LEFT JOIN video_owners o ON o.ext_id = r.ext_id
            LEFT JOIN channels named ON named.title = o.channel_name
                                    AND named.platform = 'youtube'
            LEFT JOIN watched w ON w.video_key = 'yt:' || r.ext_id
            WHERE r.kind = ?
            ORDER BY r.position
            LIMIT ?
            """,
            (kind, limit),
        ))

    def videos_without_an_owner(self, kind: str, limit: int = 25) -> list[str]:
        """Ids in a listing that nothing here knows the channel of.

        The history is what this is for. Its rows carry no channel at all, and
        the ones that are also in the videos table answer from there, so what
        is left is videos from channels nobody here follows.
        """
        return [row["ext_id"] for row in self.conn.execute(
            """
            SELECT r.ext_id FROM cached_videos r
            LEFT JOIN videos v ON v.ext_id = r.ext_id AND v.platform = 'youtube'
            LEFT JOIN video_owners o ON o.ext_id = r.ext_id
            WHERE r.kind = ?
              AND (r.channel_name IS NULL OR r.channel_name = '')
              AND v.ext_id IS NULL AND o.ext_id IS NULL
            ORDER BY r.position
            LIMIT ?
            """, (kind, limit))]

    def remember_owner(self, ext_id: str, channel_name: str, handle: str = "",
                       channel_ext_id: str = "") -> None:
        """Keep who made a video. Once in the life of a video: a video does not
        change hands, and the point of the table is that this answer outlives
        the listing that needed it."""
        if not ext_id or not channel_name:
            return
        with self.conn as conn:
            conn.execute(
                "INSERT INTO video_owners(ext_id, channel_name, handle, channel_ext_id, seen_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(ext_id) DO UPDATE SET "
                "  channel_name=excluded.channel_name, handle=excluded.handle, "
                "  channel_ext_id=COALESCE(excluded.channel_ext_id, video_owners.channel_ext_id)",
                (ext_id, channel_name, handle or None, channel_ext_id or None, int(time.time())))

    def owner_of(self, ext_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT ext_id, channel_name, handle, channel_ext_id FROM video_owners "
            "WHERE ext_id=?", (ext_id,)).fetchone()
        return dict(row) if row else None

    def cached_age_s(self, kind: str) -> int | None:
        """How long ago this set was read, or None if it never was.

        The two named kinds carry a stamp of their own. A search does not,
        since there is one kind per set of words and that would leave a row of
        state behind for every one ever typed, so its age comes from the rows
        themselves. Which cannot disagree with what is stored, and is the
        reason this is asked of the database rather than kept in the window.
        """
        stamp = self.get_int(f"{kind}_at", 0)
        if stamp:
            return int(time.time()) - stamp
        found = self.conn.execute(
            "SELECT MAX(seen_at) AS seen FROM cached_videos WHERE kind=?",
            (kind,)).fetchone()
        if not found or found["seen"] is None:
            return None
        return max(0, int(time.time()) - int(found["seen"]))

    # The recommendations under their own names, since that is what the rest
    # of the application calls them.
    def replace_recommended(self, rows: list[dict]) -> int:
        return self.replace_cached(self.RECOMMENDED, rows)

    def append_recommended(self, rows: list[dict]) -> int:
        return self.append_cached(self.RECOMMENDED, rows)

    def recommended(self, limit: int = 400) -> list[sqlite3.Row]:
        # The same ceiling the view uses, so the two cannot disagree about how
        # many there are.
        return self.cached(self.RECOMMENDED, limit)

    def recommended_count(self) -> int:
        return self.cached_count(self.RECOMMENDED)

    def recommended_age_s(self) -> int | None:
        return self.cached_age_s(self.RECOMMENDED)

    def decorate(self, rows: list[dict]) -> list[dict]:
        """Turn flat rows from a source into the shape the grid draws.

        A source hands over a flat listing, which is joined to what is known
        here: the channel, when there is a row for it, and whether the video
        has been watched. Two queries whatever the number of rows. A set of
        search results kept from an earlier ask goes through this as well, so
        that it draws exactly as a set that has just arrived.

        The channel id and the name YouTube gave come along untouched, because
        a result put in a box is stored from this row and there is nowhere
        else left to read them from.
        """
        if not rows:
            return []
        keys = [f"yt:{row['ext_id']}" for row in rows]
        channel_ids = [row.get("channel_ext_id") for row in rows if row.get("channel_ext_id")]
        known: dict[str, sqlite3.Row] = {}
        if channel_ids:
            marks = ",".join("?" * len(channel_ids))
            known = {row["ext_id"]: row for row in self.conn.execute(
                f"SELECT ext_id, key, title, avatar_url FROM channels "
                f"WHERE platform='youtube' AND ext_id IN ({marks})", channel_ids)}
        marks = ",".join("?" * len(keys))
        watched = {row[0] for row in self.conn.execute(
            f"SELECT video_key FROM watched WHERE video_key IN ({marks})", keys)}

        out = []
        for row in rows:
            channel = known.get(row.get("channel_ext_id") or "")
            key = f"yt:{row['ext_id']}"
            channel_ext_id = row.get("channel_ext_id") or ""
            out.append({
                "key": key, "platform": "youtube", "ext_id": row["ext_id"],
                "channel_key": channel["key"] if channel
                               else (f"yt:{channel_ext_id}" if channel_ext_id else ""),
                "channel_ext_id": channel_ext_id or None,
                "channel_name": row.get("channel_name"),
                "title": row["title"], "published_at": row.get("published_at"),
                "thumbnail_url": row.get("thumbnail_url"),
                "duration_s": row.get("duration_s"),
                "views": row.get("views"), "likes": None,
                "live_status": row.get("live_status"),
                "scheduled_at": row.get("scheduled_at"),
                "channel_title": (channel["title"] if channel else None)
                                 or row.get("channel_name") or "",
                "avatar_url": channel["avatar_url"] if channel else None,
                "watched": key in watched,
            })
        return out

    # ---- playlists -------------------------------------------------------

    def replace_playlists(self, rows: list[dict]) -> int:
        """Swap in the current list. One that is gone from YouTube is gone from
        here, and its contents go with it through the foreign key.

        A playlist that is already known keeps the place it has, since that
        place may have been chosen by hand and reading the list again is not a
        reason to undo that. New ones go on the end, in the order they came.
        """
        now = int(time.time())
        with self.conn as conn:
            keep = [row["ext_id"] for row in rows]
            marks = ",".join("?" * len(keep)) or "''"
            # Only your own. One kept off a channel page is not in this feed
            # and reading the feed is not a reason to lose it.
            conn.execute(
                f"DELETE FROM playlists WHERE origin='mine' AND ext_id NOT IN ({marks})", keep)
            known = {row["ext_id"]: row["position"] for row in
                     conn.execute("SELECT ext_id, position FROM playlists WHERE origin='mine'")}
            next_place = max(known.values(), default=-1) + 1
            payload = []
            for row in rows:
                place = known.get(row["ext_id"])
                if place is None:
                    place = next_place
                    next_place += 1
                payload.append((row["ext_id"], row["title"], place, now))
            conn.executemany(
                "INSERT INTO playlists(ext_id, title, position, seen_at) VALUES(?,?,?,?) "
                "ON CONFLICT(ext_id) DO UPDATE SET title=excluded.title, "
                "  position=excluded.position, seen_at=excluded.seen_at",
                payload,
            )
        self.set_state("playlists_at", str(now))
        return len(rows)

    def move_playlist(self, playlist_id: str, delta: int) -> bool:
        """Shift a playlist one place in the sidebar.

        Positions are rewritten from the resulting order rather than swapped,
        so a list left with gaps by a deletion comes out consecutive either
        way. Hidden ones move with the rest, since they are only out of sight.

        Inside its own list. Yours and the ones kept off a channel page are
        drawn as two sections and numbered apart, so a move is a move among
        the ones it is drawn beside.
        """
        found = self.conn.execute(
            "SELECT origin FROM playlists WHERE ext_id=?", (playlist_id,)).fetchone()
        if found is None:
            return False
        order = [row["ext_id"] for row
                 in self.playlists(include_hidden=True, origin=found["origin"])]
        if playlist_id not in order:
            return False
        was = order.index(playlist_id)
        now = max(0, min(len(order) - 1, was + delta))
        if now == was:
            return False
        order.insert(now, order.pop(was))
        with self.conn as conn:
            conn.executemany("UPDATE playlists SET position=? WHERE ext_id=?",
                             list(enumerate(order)))
        return True

    def playlists(self, include_hidden: bool = False, origin: str = "mine") -> list[dict]:
        """The playlists, hidden ones left out unless asked for.

        Hiding is not forgetting. A hidden playlist keeps its contents and
        comes back the moment it is shown again, which is the difference
        between this and removing it.

        `origin` says which list is being asked for. Yours, the ones kept off
        a channel page, or everything.
        """
        where = ["p.origin != 'temp'"] if origin == "any" else [f"p.origin = '{origin}'"]
        if not include_hidden:
            where.append("p.hidden = 0")
        clause = " WHERE " + " AND ".join(where)
        return [dict(row) for row in self.conn.execute(
            "SELECT p.ext_id, p.title, p.position, p.items_at, p.hidden, p.is_music, p.origin, "
            "       (SELECT COUNT(*) FROM playlist_items i WHERE i.playlist_id = p.ext_id) "
            "         AS items "
            f"FROM playlists p {clause} ORDER BY p.position, p.title")]

    # ---- playlists a channel has made -----------------------------------

    def replace_channel_playlists(self, channel_key: str, rows: list) -> int:
        """What this channel's playlists tab lists now, in the order it gave.

        Swapped in wholesale. This is a listing rather than anything of yours,
        so nothing here is worth keeping when the channel no longer offers it,
        and a playlist you kept lives in the playlists table and is untouched
        by this.
        """
        now = int(time.time())
        with self.conn as conn:
            conn.execute("DELETE FROM channel_playlists WHERE channel_key=?", (channel_key,))
            conn.executemany(
                "INSERT INTO channel_playlists"
                "(channel_key, ext_id, title, position, seen_at, thumbnail_url) "
                "VALUES(?,?,?,?,?,?)",
                [(channel_key, row.ext_id, row.title, place, now,
                  getattr(row, "thumbnail", "") or None)
                 for place, row in enumerate(rows)])
            conn.execute("UPDATE channels SET playlists_at=? WHERE key=?", (now, channel_key))
        return len(rows)

    def channel_playlists(self, channel_key: str) -> list[dict]:
        """The tab as it was last read, with what is known about each one.

        A count is only there once a playlist has been opened, since the
        listing carries none and asking for one is a request per playlist.
        """
        return [dict(row) for row in self.conn.execute(
            "SELECT c.ext_id, c.title, c.thumbnail_url, "
            "       (SELECT COUNT(*) FROM playlist_items i WHERE i.playlist_id = c.ext_id) "
            "         AS items, "
            "       (SELECT p.origin FROM playlists p WHERE p.ext_id = c.ext_id) AS origin "
            "FROM channel_playlists c WHERE c.channel_key=? ORDER BY c.position", (channel_key,))]

    def channel_playlists_age_s(self, channel_key: str) -> int | None:
        row = self.conn.execute(
            "SELECT playlists_at FROM channels WHERE key=?", (channel_key,)).fetchone()
        stamp = row["playlists_at"] if row else None
        return None if not stamp else int(time.time()) - int(stamp)

    def channel_playlists_lack_pictures(self, channel_key: str) -> bool:
        """Whether what is stored for this channel is a listing from before
        the pictures were read.

        The tab is re-read at most once a day, so a listing stored without
        pictures would show none for a day after the version that reads them
        arrives. Rows with not one picture between them are treated as old
        rather than as a channel whose playlists happen to have none, which
        would mean every playlist of theirs being empty.
        """
        row = self.conn.execute(
            "SELECT COUNT(*) AS held, COUNT(thumbnail_url) AS pictures "
            "FROM channel_playlists WHERE channel_key=?", (channel_key,)).fetchone()
        return bool(row["held"]) and not row["pictures"]

    def playlist_source(self, ext_id: str) -> dict | None:
        """Which channel a playlist was opened off, if it was opened off one.

        The bar above such a playlist offers the way back to the tab it came
        from, so it needs the channel and not only the playlist. One of your
        own has no channel behind it and answers nothing.
        """
        row = self.conn.execute(
            "SELECT p.ext_id, p.title, p.origin, cp.channel_key, "
            "       ch.title AS channel_title "
            "FROM playlists p "
            "JOIN channel_playlists cp ON cp.ext_id = p.ext_id "
            "JOIN channels ch ON ch.key = cp.channel_key "
            "WHERE p.ext_id = ? AND p.origin != 'mine' "
            "ORDER BY cp.position LIMIT 1", (ext_id,)).fetchone()
        return dict(row) if row else None

    def open_channel_playlist(self, ext_id: str, title: str) -> None:
        """Give a playlist somewhere to hang its contents.

        A playlist's videos hang off a playlists row, so looking at one means
        making a row for it. It is marked temp, which keeps it out of the
        sidebar and marks it as something to sweep up later, and keeping it is
        what makes it stay.
        """
        with self.conn as conn:
            conn.execute(
                "INSERT INTO playlists(ext_id, title, position, seen_at, hidden, origin) "
                "VALUES(?,?,0,?,1,'temp') "
                "ON CONFLICT(ext_id) DO UPDATE SET title=excluded.title",
                (ext_id, title, int(time.time())))

    def keep_playlist(self, ext_id: str, keep: bool = True) -> None:
        """Keep a channel's playlist, or stop keeping it.

        Kept, it moves into the sidebar's own section and stays through every
        reading of your own playlists feed. Dropped, it becomes what it was
        before, something you were looking at.

        Keeping can be asked for from the tile on a channel's tab, and a
        playlists row is only made by opening one, so from there there was
        nothing to update and the press did nothing at all. A missing row is
        made here out of what the tab already knows, which is the same row
        opening it would have made. Nothing the tab never listed is kept,
        since there would be no name to make it under.
        """
        if keep and self.playlist(ext_id) is None:
            named = self.conn.execute(
                "SELECT title FROM channel_playlists WHERE ext_id=? ORDER BY position LIMIT 1",
                (ext_id,)).fetchone()
            if named is None:
                return
            self.open_channel_playlist(ext_id, named["title"] or ext_id)
        with self.conn as conn:
            if keep:
                place = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM playlists "
                    "WHERE origin='channel'").fetchone()[0]
                conn.execute(
                    "UPDATE playlists SET origin='channel', hidden=0, position=? WHERE ext_id=?",
                    (place, ext_id))
            else:
                conn.execute(
                    "UPDATE playlists SET origin='temp', hidden=1 WHERE ext_id=?", (ext_id,))

    def sweep_temporary_playlists(self, older_than_s: int = 86400) -> int:
        """Drop the rows made only to look at a playlist once. Their contents
        go with them, through the foreign key."""
        cut = int(time.time()) - max(0, older_than_s)
        with self.conn as conn:
            # Counted before the delete rather than from total_changes, which
            # would also count every item that went with them.
            gone = [row["ext_id"] for row in conn.execute(
                "SELECT ext_id FROM playlists WHERE origin='temp' AND seen_at <= ?", (cut,))]
            conn.executemany("DELETE FROM playlists WHERE ext_id=?", [(one,) for one in gone])
            return len(gone)

    def set_playlist_music(self, playlist_id: str, music: bool) -> None:
        """Mark a playlist as music, or stop marking it.

        Nothing about the stored videos changes. It only decides where a press
        on one of them is handed to.
        """
        with self.conn as conn:
            conn.execute("UPDATE playlists SET is_music=? WHERE ext_id=?",
                         (1 if music else 0, playlist_id))

    def set_playlist_hidden(self, playlist_id: str, hidden: bool) -> None:
        with self.conn as conn:
            conn.execute("UPDATE playlists SET hidden=? WHERE ext_id=?",
                         (1 if hidden else 0, playlist_id))

    def playlist(self, playlist_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT ext_id, title, items_at, skipped, is_music FROM playlists WHERE ext_id=?",
            (playlist_id,)).fetchone()
        return dict(row) if row else None

    def replace_playlist_items(self, playlist_id: str, rows: list[dict],
                               skipped: int = 0) -> int:
        """Swap in one playlist's videos.

        `skipped` is how many rows the fetch itself already left out, a video
        gone private or deleted, YouTube's own placeholder rather than an
        error. Kept on the playlist itself rather than counted from the rows
        here, since by the time they reach this call they are already gone.
        """
        with self.conn as conn:
            conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (playlist_id,))
            conn.executemany(
                "INSERT INTO playlist_items(playlist_id, ext_id, title, channel_name, "
                "  channel_ext_id, duration_s, thumbnail_url, views, published_at, "
                "  position) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                [(playlist_id, row["ext_id"], row["title"], row.get("channel_name"),
                  row.get("channel_ext_id"), row.get("duration_s"),
                  row.get("thumbnail_url"), row.get("views"), row.get("published_at"),
                  index)
                 for index, row in enumerate(rows)],
            )
            conn.execute("UPDATE playlists SET items_at=?, skipped=? WHERE ext_id=?",
                         (int(time.time()), skipped, playlist_id))
        return len(rows)

    def playlist_items(self, playlist_id: str, limit: int = 500) -> list[sqlite3.Row]:
        """Shaped like a feed row, so the same grid draws it. A playlist keeps
        its own order rather than being sorted by date, which is the whole
        point of somebody having made it."""
        return list(self.conn.execute(
            """
            SELECT 'yt:' || i.ext_id           AS key,
                   'youtube'                   AS platform,
                   i.ext_id                    AS ext_id,
                   COALESCE(c.key, IIF(i.channel_ext_id IS NULL, '', 'yt:' || i.channel_ext_id)) AS channel_key,
                   i.title                     AS title,
                   i.published_at              AS published_at,
                   i.thumbnail_url             AS thumbnail_url,
                   i.duration_s                AS duration_s,
                   i.views                     AS views,
                   NULL                        AS likes,
                   NULL                        AS live_status,
                   COALESCE(c.title, i.channel_name) AS channel_title,
                   c.avatar_url                AS avatar_url,
                   w.video_key IS NOT NULL     AS watched
            FROM playlist_items i
            LEFT JOIN channels c ON c.ext_id = i.channel_ext_id AND c.platform = 'youtube'
            LEFT JOIN watched w ON w.video_key = 'yt:' || i.ext_id
            WHERE i.playlist_id = ?
            ORDER BY i.position
            LIMIT ?
            """,
            (playlist_id, limit),
        ))

    # ---- who is live -----------------------------------------------------

    def replace_live(self, platform: str, rows: list[dict]) -> int:
        """Swap in the current picture for one platform.

        Replacing rather than updating because a channel that has gone offline
        shows up as a missing row, not as a changed one.
        """
        now = int(time.time())
        with self.conn as conn:
            conn.execute("DELETE FROM live_streams WHERE platform=?", (platform,))
            conn.executemany(
                "INSERT INTO live_streams(channel_key, platform, login, display_name, "
                "  title, game, viewers, started_at, thumbnail_url, seen_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(channel_key) DO NOTHING",
                [(r["channel_key"], platform, r.get("login"), r.get("display_name"),
                  r.get("title"), r.get("game"), int(r.get("viewers") or 0),
                  r.get("started_at"), r.get("thumbnail_url"), now) for r in rows],
            )
        return len(rows)

    # A Twitch row is only as good as the last check that stored it. Rows are
    # replaced wholesale on a successful check, so a check that keeps failing
    # would otherwise leave yesterday's streams on screen looking current, and
    # a bar that lies is worse than an empty one.
    LIVE_STALE_S = 600

    def live_now(self) -> list[dict]:
        """Everything live, both platforms, busiest first.

        YouTube streams carry a viewer count too, fetched separately because
        neither the feed nor the sweep reports one, so both platforms order
        against each other in a single row.
        """
        fresh = int(time.time()) - self.LIVE_STALE_S
        rows = [dict(row) for row in self.conn.execute(
            "SELECT l.*, c.title AS channel_title, c.avatar_url "
            "FROM live_streams l LEFT JOIN channels c ON c.key = l.channel_key "
            "WHERE l.seen_at >= ?", (fresh,))]
        for row in self.conn.execute(
            "SELECT v.key AS video_key, v.ext_id, v.title, v.thumbnail_url, "
            "       v.live_viewers, v.channel_key, c.title AS channel_title, c.avatar_url "
            "FROM videos v JOIN channels c ON c.key = v.channel_key "
            "WHERE v.live_status = 'is_live'"
        ):
            rows.append({
                "channel_key": row["channel_key"], "platform": "youtube",
                "login": row["ext_id"], "display_name": row["channel_title"] or "",
                "title": row["title"], "game": "",
                # A real number now, so a busy stream sorts among the Twitch
                # ones instead of always landing at the end of the bar.
                "viewers": int(row["live_viewers"] or 0),
                "started_at": None, "thumbnail_url": row["thumbnail_url"],
                "channel_title": row["channel_title"], "avatar_url": row["avatar_url"],
                "video_key": row["video_key"],
            })
        rows.sort(key=lambda row: (-int(row.get("viewers") or 0),
                                   (row.get("display_name") or "").lower()))
        return rows

    def live_stream(self, channel_key: str) -> dict | None:
        """One stream that is on now, for the panel. A stream is not a video
        and has no row in videos, so it is looked up where it does live."""
        fresh = int(time.time()) - self.LIVE_STALE_S
        row = self.conn.execute(
            "SELECT l.*, c.title AS channel_title, c.avatar_url "
            "FROM live_streams l LEFT JOIN channels c ON c.key = l.channel_key "
            "WHERE l.channel_key = ? AND l.seen_at >= ?", (channel_key, fresh)).fetchone()
        return dict(row) if row else None

    # ---- saved audio sources ---------------------------------------------

    def add_source(self, label: str, url: str, live: bool = False) -> None:
        now = int(time.time())
        with self.conn as conn:
            position = conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM audio_sources").fetchone()[0]
            conn.execute(
                "INSERT INTO audio_sources(label, url, live, position, added_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET label=excluded.label",
                (label.strip() or url, url, 1 if live else 0, position, now))

    def set_source_details(self, url: str, label: str | None, thumbnail: str | None) -> None:
        with self.conn as conn:
            conn.execute(
                "UPDATE audio_sources SET label=COALESCE(?, label), "
                "thumbnail=COALESCE(?, thumbnail) WHERE url=?", (label, thumbnail, url))

    def remove_source(self, source_id: int) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM audio_sources WHERE id=?", (source_id,))

    def sources(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            "SELECT id, label, url, live, thumbnail FROM audio_sources "
            "ORDER BY position, id")]

    def unwatched_total(self) -> int:
        """What the All row counts. Only videos from channels followed, since
        those are the only ones All shows."""
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM videos v "
            "JOIN channels c ON c.key = v.channel_key AND c.tracked = 1 AND c.in_all = 1 "
            "LEFT JOIN watched w ON w.video_key = v.key "
            "WHERE w.video_key IS NULL AND (v.is_short IS NULL OR v.is_short = 0)"
        ).fetchone()[0])

    # What tells a stream from a video here. A stream that has ended keeps its
    # live_status, an announced one has an hour and no status yet, and one only
    # suspected of being an announcement is being asked about. All three belong
    # on a channel's streams half rather than among its videos.
    # Every part answers true or false and never NULL. An unset stream_pending
    # compared with = leaves the whole test NULL, and NOT NULL is NULL, so the
    # videos half came back empty while both halves looked right on their own.
    IS_A_STREAM = ("(v.live_status IS NOT NULL OR v.scheduled_at IS NOT NULL "
                   "OR COALESCE(v.stream_pending, 0) = 1)")

    def feed(self, limit: int = 300, hide_watched: bool = True,
             group_id: int | None = None, channel_key: str | None = None,
             box_id: int | None = None, query: str | None = None,
             watched_only: bool = False, streams: bool | None = None) -> list[sqlite3.Row]:
        """The video list for whichever view is showing.

        A box orders by the order things were put in it rather than by publish
        date, since that is the point of hand picking. History orders by when
        it was watched. Everything else is newest first.

        A search matches the video title or the channel name. LIKE is case
        insensitive for ASCII only in SQLite, so a search for an accented or
        umlauted word matches the case it was typed in and not the other. That
        is a known limit rather than an oversight, and fixing it means shipping
        a collation.

        The list with nothing named is the feed itself, and it shows only the
        channels followed. A video saved out of the suggestions or the history
        is stored the same way as any other, so without this the channel it
        brought with it would pour into All, which is exactly what saving one
        video must not do. Naming a box, a group, a channel or a search asks
        for something particular and answers with it whatever the channel is.
        """
        # An unclassified video still shows. It is hidden only once a channel
        # listing or the redirect test has proven it is a Short.
        where = ["(v.is_short IS NULL OR v.is_short = 0)"]
        args: list[Any] = []
        join = ""
        order = "v.published_at DESC NULLS LAST, v.first_seen_at DESC"

        if group_id is None and box_id is None and channel_key is None and not query:
            where.append("c.tracked = 1")
            # A channel put in a group and never followed by name is asked
            # after inside that group only, so All leaves it out the same way
            # it leaves out the channel behind a video saved into a box.
            where.append("c.in_all = 1")
        if hide_watched:
            where.append("w.video_key IS NULL")
        if group_id is not None:
            where.append("v.channel_key IN (SELECT channel_key FROM group_members WHERE group_id=?)")
            args.append(group_id)
        if channel_key is not None:
            where.append("v.channel_key = ?")
            args.append(channel_key)
        if box_id is not None:
            join = "JOIN box_items bi ON bi.video_key = v.key AND bi.box_id = ?"
            args.insert(0, box_id)
            order = "bi.position"
        if query:
            # The wildcards are escaped rather than stripped, so searching for
            # a title that really contains one finds it.
            pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(v.title LIKE ? ESCAPE '\\' OR c.title LIKE ? ESCAPE '\\')")
            args.extend([pattern, pattern])
        if watched_only:
            where.append("w.video_key IS NOT NULL")
            order = "w.watched_at DESC"
        if streams is not None:
            # The two halves of a channel page. A feed, a group or a box says
            # nothing here and holds both, which is right: a stream of a
            # channel you follow belongs in what you follow.
            where.append(self.IS_A_STREAM if streams else f"NOT {self.IS_A_STREAM}")

        args.append(limit)
        return list(self.conn.execute(
            f"""
            SELECT v.*, c.title AS channel_title, c.avatar_url,
                   w.video_key IS NOT NULL AS watched
            FROM videos v
            JOIN channels c ON c.key = v.channel_key
            {join}
            LEFT JOIN watched w ON w.video_key = v.key
            WHERE {' AND '.join(where)}
            ORDER BY {order}
            LIMIT ?
            """,
            args,
        ))

    # ---- watched ---------------------------------------------------------

    def mark_watched_many(self, keys: list[str], source: str) -> tuple[int, int]:
        """Mark stored videos as watched, returning how many were newly marked
        and how many were not stored at all.

        A video the database has never seen is skipped rather than invented,
        because a history row carries no channel, measured, and a video here
        has to belong to one. An existing mark is left alone so an import
        cannot overwrite what mpv observed.
        """
        if not keys:
            return 0, 0
        stored = self._stored_of(keys)
        now = int(time.time())
        with self.conn as conn:
            before = conn.total_changes
            conn.executemany(
                "INSERT INTO watched(video_key, watched_at, progress, source) "
                "VALUES(?,?,NULL,?) ON CONFLICT(video_key) DO NOTHING",
                [(key, now, source) for key in keys if key in stored],
            )
            marked = conn.total_changes - before
        return marked, len(keys) - len(stored)

    def _stored_of(self, keys: list[str]) -> set[str]:
        """Which of these video keys the database actually holds. Chunked,
        since SQLite caps how many parameters one statement may bind."""
        found: set[str] = set()
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            marks = ",".join("?" * len(chunk))
            found.update(row[0] for row in self.conn.execute(
                f"SELECT key FROM videos WHERE key IN ({marks})", chunk))
        return found

    def streams_to_judge(self, limit: int = 400) -> list[sqlite3.Row]:
        """Streams that have ended, have a length, and carry no mark yet.

        A stream watched while it was live is never marked at the time. What
        it will turn out to be is not known until it ends: mpv reports the
        rewind window as the length and starts you at the live edge, so any
        share of it read while the broadcast is running says nothing. Once it
        has ended there is a real length to measure the stopped position
        against, which is what this is for.
        """
        return list(self.conn.execute(
            "SELECT v.key, v.platform, v.ext_id, v.duration_s FROM videos v "
            "LEFT JOIN watched w ON w.video_key = v.key "
            "WHERE v.live_status = 'was_live' AND v.duration_s > 0 "
            "  AND w.video_key IS NULL "
            "ORDER BY v.published_at DESC NULLS LAST LIMIT ?", (limit,)))

    def set_watched(self, video_key: str, progress: float | None, source: str) -> None:
        with self.conn as conn:
            conn.execute(
                "INSERT INTO watched(video_key, watched_at, progress, source) VALUES(?,?,?,?) "
                "ON CONFLICT(video_key) DO UPDATE SET watched_at=excluded.watched_at, "
                "progress=excluded.progress, source=excluded.source",
                (video_key, int(time.time()), progress, source),
            )

    def clear_watched(self, video_key: str) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM watched WHERE video_key=?", (video_key,))

    def is_watched(self, video_key: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM watched WHERE video_key=?", (video_key,)
        ).fetchone() is not None

    def counts(self) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM channels WHERE tracked=1) AS channels,"
            "       (SELECT COUNT(*) FROM channels WHERE tracked=0) AS loose,"
            "       (SELECT COUNT(*) FROM channels WHERE tracked=1 AND in_all=0)"
            "                                                       AS group_only,"
            "       (SELECT COUNT(*) FROM videos)   AS videos,"
            "       (SELECT COUNT(*) FROM watched)  AS watched"
        ).fetchone()
        # Iterating a Row yields its values, so the keys are asked for by name.
        return {k: row[k] for k in row.keys()}                     # noqa: SIM118
