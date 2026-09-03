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

    def add_channel(self, key: str, platform: str, ext_id: str, title: str | None = None) -> None:
        with self.conn as conn:
            conn.execute(
                "INSERT INTO channels(key, platform, ext_id, title, added_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET title=COALESCE(excluded.title, channels.title)",
                (key, platform, ext_id, title, int(time.time())),
            )

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

    def feed(self, limit: int = 300, hide_watched: bool = True,
             group_id: int | None = None) -> list[sqlite3.Row]:
        where = ["1=1"]
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
