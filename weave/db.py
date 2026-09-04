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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 10

# A Short is at most three minutes. Anything longer needs no further test.
SHORTS_CEILING_S = 180

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

    @property
    def key(self) -> str:
        prefix = "yt" if self.platform == "youtube" else "twitch"
        return f"{prefix}:{self.ext_id}"


# Columns added after the first release. Listed rather than folded into the
# schema above so an existing database gains them too.
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

    def set_state(self, key: str, value: str) -> None:
        with self.conn as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"state.{key}", value),
            )

    # ---- channels --------------------------------------------------------

    def add_channel(self, key: str, platform: str, ext_id: str, title: str | None = None,
                    avatar_url: str | None = None) -> bool:
        """Add or update a channel. Returns whether it was new.

        COALESCE keeps a known title or avatar when the caller has none, so a
        source that carries less detail than an earlier one cannot erase it.
        """
        with self.conn as conn:
            existed = conn.execute("SELECT 1 FROM channels WHERE key=?", (key,)).fetchone()
            conn.execute(
                "INSERT INTO channels(key, platform, ext_id, title, avatar_url, added_at) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "  title=COALESCE(excluded.title, channels.title), "
                "  avatar_url=COALESCE(excluded.avatar_url, channels.avatar_url)",
                (key, platform, ext_id, title, avatar_url, int(time.time())),
            )
            return existed is None

    def channels_missing_avatar(self, platform: str = "twitch") -> list[str]:
        return [row["ext_id"] for row in self.conn.execute(
            "SELECT ext_id FROM channels WHERE platform=? AND "
            "(avatar_url IS NULL OR avatar_url = '')", (platform,))]

    def channels_due(self, tiers: FeedTiers, platform: str = "youtube",
                     limit: int | None = None, force: bool = False) -> list[sqlite3.Row]:
        """Channels that are past their own interval, most overdue first.

        Each channel carries its own interval, derived from when it last
        published rather than stored, so it can never go stale against the
        videos table. A channel that has never been polled has no timestamp,
        counts as infinitely overdue and therefore goes first.

        `force` ignores the intervals but not the limit. The point of the
        limit is that a round is small enough not to look like a burst, and a
        deliberate refresh has the same endpoint on the other end.
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
            "force": 1 if force else 0,
            "limit": limit if limit is not None else -1,
        }
        return list(self.conn.execute(
            """
            SELECT * FROM (
                SELECT c.*,
                       CASE
                           WHEN l.published IS NULL       THEN :frozen_s
                           WHEN l.published >= :hot_cut   THEN :hot_s
                           WHEN l.published >= :warm_cut  THEN :warm_s
                           WHEN l.published >= :cold_cut  THEN :cold_s
                           ELSE :frozen_s
                       END AS interval_s
                FROM channels c
                LEFT JOIN (SELECT channel_key, MAX(published_at) AS published
                             FROM videos GROUP BY channel_key) l
                       ON l.channel_key = c.key
                WHERE c.platform = :platform
            )
            WHERE :force = 1
               OR COALESCE(last_polled_at, 0) <= :now - interval_s
            ORDER BY (:now - COALESCE(last_polled_at, 0)) - interval_s DESC
            LIMIT :limit
            """,
            params,
        ))

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
                "UPDATE channels SET last_polled_at=0 WHERE key=? AND last_polled_at IS NOT 0",
                [(key,) for key in keys],
            )
            return conn.total_changes - before

    def set_feed_variant(self, key: str, variant: str) -> None:
        with self.conn as conn:
            conn.execute("UPDATE channels SET feed_variant=? WHERE key=?", (variant, key))

    def channels_that_stream(self, platform: str = "youtube") -> set[str]:
        """Channels known to broadcast, so the live feed is only asked of the
        ones it can answer for. Most channels have never streamed and asking
        them would double the request count for nothing."""
        return {row[0] for row in self.conn.execute(
            "SELECT DISTINCT channel_key FROM videos "
            "WHERE platform=? AND live_status IS NOT NULL", (platform,))}

    def remove_channel(self, key: str) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM channels WHERE key=?", (key,))

    def channels(self, platform: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM channels"
        args: Sequence[Any] = ()
        if platform:
            sql += " WHERE platform=?"
            args = (platform,)
        return list(self.conn.execute(sql + " ORDER BY title IS NULL, title COLLATE NOCASE", args))

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
        with self.conn as conn:
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

    def fill_details(self, rows: list[tuple[str, int | None, str | None]]) -> int:
        """Apply the durations and live flags the subscriptions sweep found.

        Only fills what is missing. RSS never carries either, and a value
        already stored is not worth overwriting with the same thing.
        """
        if not rows:
            return 0
        with self.conn as conn:
            before = conn.total_changes
            conn.executemany(
                "UPDATE videos SET duration_s=COALESCE(duration_s, ?), "
                "live_status=COALESCE(?, live_status) "
                "WHERE key=? AND (duration_s IS NULL OR live_status IS NOT ?)",
                [(duration, live, key, live) for key, duration, live in rows],
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
        """One video with everything the detail panel shows."""
        row = self.conn.execute(
            "SELECT v.*, c.title AS channel_title, c.avatar_url, "
            "       w.video_key IS NOT NULL AS watched "
            "FROM videos v JOIN channels c ON c.key = v.channel_key "
            "LEFT JOIN watched w ON w.video_key = v.key WHERE v.key=?", (key,)).fetchone()
        return dict(row) if row else None

    def set_live_state(self, video_key: str, viewers: int | None, still_live: bool) -> None:
        """A stream that has stopped becomes an ordinary video rather than
        vanishing, so it stays in the feed and only leaves the live bar."""
        with self.conn as conn:
            conn.execute(
                "UPDATE videos SET live_viewers=?, live_status=? WHERE key=?",
                (viewers if still_live else None,
                 "is_live" if still_live else "was_live", video_key))

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

    def rename_group(self, group_id: int, name: str) -> None:
        with self.conn as conn:
            conn.execute("UPDATE groups SET name=? WHERE id=?", (name, group_id))

    def set_group_order(self, ordered_ids: list[int]) -> None:
        with self.conn as conn:
            conn.executemany("UPDATE groups SET position=? WHERE id=?",
                             list(enumerate(ordered_ids)))

    def add_to_group(self, group_id: int, channel_key: str) -> None:
        with self.conn as conn:
            conn.execute(
                "INSERT INTO group_members(group_id, channel_key) VALUES(?,?) "
                "ON CONFLICT DO NOTHING", (group_id, channel_key))

    def remove_from_group(self, group_id: int, channel_key: str) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM group_members WHERE group_id=? AND channel_key=?",
                         (group_id, channel_key))

    def groups_holding(self, channel_key: str) -> list[int]:
        return [int(row["group_id"]) for row in self.conn.execute(
            "SELECT group_id FROM group_members WHERE channel_key=?", (channel_key,))]

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
            SELECT g.id, g.name, g.position,
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

    def group_by_name(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, name, position FROM groups WHERE name=? COLLATE NOCASE", (name,)
        ).fetchone()
        return dict(row) if row else None

    def group_members(self, group_id: int) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT c.* FROM channels c JOIN group_members m ON m.channel_key = c.key "
            "WHERE m.group_id=? ORDER BY c.title COLLATE NOCASE", (group_id,)))

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

    def rename_box(self, box_id: int, name: str) -> None:
        with self.conn as conn:
            conn.execute("UPDATE boxes SET name=? WHERE id=?", (name.strip(), box_id))

    def delete_box(self, box_id: int) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM boxes WHERE id=?", (box_id,))

    def set_box_order(self, ordered_ids: list[int]) -> None:
        with self.conn as conn:
            conn.executemany("UPDATE boxes SET position=? WHERE id=?", list(enumerate(ordered_ids)))

    def add_to_box(self, box_id: int, video_key: str) -> bool:
        """Newest addition goes last, so a box keeps the order things were put
        in rather than the order they were published.

        Returns whether it went in. A box can only hold a video that is
        actually stored, which the foreign key enforces, so an unknown key is
        reported rather than raised. That is reachable from the command line,
        where a URL can name a video this install has never seen.
        """
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

    def remove_from_box(self, box_id: int, video_key: str) -> None:
        with self.conn as conn:
            conn.execute("DELETE FROM box_items WHERE box_id=? AND video_key=?",
                         (box_id, video_key))

    def boxes(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            "SELECT b.id, b.name, b.position, "
            "  (SELECT COUNT(*) FROM box_items i WHERE i.box_id = b.id) AS items "
            "FROM boxes b ORDER BY b.position, b.id")]

    def box_by_name(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, name, position FROM boxes WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        return dict(row) if row else None

    def boxes_holding(self, video_key: str) -> list[int]:
        return [int(row["box_id"]) for row in self.conn.execute(
            "SELECT box_id FROM box_items WHERE video_key=?", (video_key,))]

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

    def live_now(self) -> list[dict]:
        """Everything live, both platforms, busiest first.

        YouTube streams carry a viewer count too, fetched separately because
        neither the feed nor the sweep reports one, so both platforms order
        against each other in a single row.
        """
        rows = [dict(row) for row in self.conn.execute(
            "SELECT l.*, c.title AS channel_title, c.avatar_url "
            "FROM live_streams l LEFT JOIN channels c ON c.key = l.channel_key")]
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

    def live_keys(self) -> set[str]:
        return {row["channel_key"] for row in
                self.conn.execute("SELECT channel_key FROM live_streams")}

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
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM videos v LEFT JOIN watched w ON w.video_key = v.key "
            "WHERE w.video_key IS NULL AND (v.is_short IS NULL OR v.is_short = 0)"
        ).fetchone()[0])

    def feed(self, limit: int = 300, hide_watched: bool = True,
             group_id: int | None = None, channel_key: str | None = None,
             box_id: int | None = None, query: str | None = None,
             watched_only: bool = False) -> list[sqlite3.Row]:
        """The video list for whichever view is showing.

        A box orders by the order things were put in it rather than by publish
        date, since that is the point of hand picking. History orders by when
        it was watched. Everything else is newest first.

        A search matches the video title or the channel name. LIKE is case
        insensitive for ASCII only in SQLite, so a search for an accented or
        umlauted word matches the case it was typed in and not the other. That
        is a known limit rather than an oversight, and fixing it means shipping
        a collation.
        """
        # An unclassified video still shows. It is hidden only once a channel
        # listing or the redirect test has proven it is a Short.
        where = ["(v.is_short IS NULL OR v.is_short = 0)"]
        args: list[Any] = []
        join = ""
        order = "v.published_at DESC NULLS LAST, v.first_seen_at DESC"

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
            "SELECT (SELECT COUNT(*) FROM channels) AS channels,"
            "       (SELECT COUNT(*) FROM videos)   AS videos,"
            "       (SELECT COUNT(*) FROM watched)  AS watched"
        ).fetchone()
        return {k: row[k] for k in row.keys()}
