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

SCHEMA_VERSION = 1

# A Short is at most three minutes. Anything longer needs no further test.
SHORTS_CEILING_S = 180

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS watched (
    video_key  TEXT PRIMARY KEY,
    watched_at INTEGER NOT NULL,
    progress   REAL,                           -- fraction of the duration seen
    source     TEXT NOT NULL                   -- mpv, manual or seed
);
"""


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

    @property
    def key(self) -> str:
        prefix = "yt" if self.platform == "youtube" else "twitch"
        return f"{prefix}:{self.ext_id}"


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
        with self.conn as conn:
            conn.executescript(_SCHEMA)
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

    def channels_due(self, interval_s: int, platform: str = "youtube") -> list[sqlite3.Row]:
        """Channels whose last poll is older than the interval.

        With several hundred channels a full sweep every cycle is a thundering
        herd, so the timer only takes what is actually due and the manual
        refresh button takes everything.
        """
        cutoff = int(time.time()) - max(0, interval_s)
        return list(self.conn.execute(
            # At or before the cutoff, so an interval of zero means every
            # channel is due rather than none of them.
            "SELECT * FROM channels WHERE platform=? "
            "AND (last_polled_at IS NULL OR last_polled_at <= ?) "
            "ORDER BY last_polled_at IS NOT NULL, last_polled_at",
            (platform, cutoff),
        ))

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
                r.thumbnail_url, r.duration_s, r.views, r.likes, r.live_status, now,
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
                                   first_seen_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    title         = excluded.title,
                    published_at  = COALESCE(excluded.published_at, videos.published_at),
                    thumbnail_url = COALESCE(excluded.thumbnail_url, videos.thumbnail_url),
                    duration_s    = COALESCE(excluded.duration_s, videos.duration_s),
                    views         = COALESCE(excluded.views, videos.views),
                    likes         = COALESCE(excluded.likes, videos.likes),
                    live_status   = COALESCE(excluded.live_status, videos.live_status)
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

    def set_short(self, video_key: str, value: bool) -> None:
        with self.conn as conn:
            conn.execute("UPDATE videos SET is_short=? WHERE key=?", (1 if value else 0, video_key))

    def videos_needing_short_check(self, limit: int = 40) -> list[sqlite3.Row]:
        """Candidates for the redirect test.

        A known duration past the ceiling has already been settled for free, so
        only videos short enough to actually be a Short get a request. A video
        with no duration yet is deliberately not a candidate. Testing those
        would mean thousands of requests, and the sweep gives them a duration
        soon enough. Newest first, since those are the ones being looked at.
        """
        return list(self.conn.execute(
            "SELECT key, ext_id FROM videos "
            "WHERE platform='youtube' AND is_short IS NULL "
            "  AND duration_s IS NOT NULL AND duration_s <= ? "
            "ORDER BY published_at DESC NULLS LAST LIMIT ?",
            (SHORTS_CEILING_S, limit),
        ))

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

    def unwatched_total(self) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM videos v LEFT JOIN watched w ON w.video_key = v.key "
            "WHERE w.video_key IS NULL AND (v.is_short IS NULL OR v.is_short = 0)"
        ).fetchone()[0])

    def feed(self, limit: int = 300, hide_watched: bool = True,
             group_id: int | None = None) -> list[sqlite3.Row]:
        # An unclassified video still shows. It is hidden only once the
        # redirect test has actually proven it is a Short.
        where = ["(v.is_short IS NULL OR v.is_short = 0)"]
        args: list[Any] = []
        if hide_watched:
            where.append("w.video_key IS NULL")
        if group_id is not None:
            where.append("v.channel_key IN (SELECT channel_key FROM group_members WHERE group_id=?)")
            args.append(group_id)
        args.append(limit)
        return list(self.conn.execute(
            f"""
            SELECT v.*, c.title AS channel_title, c.avatar_url,
                   w.video_key IS NOT NULL AS watched
            FROM videos v
            JOIN channels c ON c.key = v.channel_key
            LEFT JOIN watched w ON w.video_key = v.key
            WHERE {' AND '.join(where)}
            ORDER BY v.published_at DESC NULLS LAST, v.first_seen_at DESC
            LIMIT ?
            """,
            args,
        ))

    # ---- watched ---------------------------------------------------------

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
