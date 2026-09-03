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

SCHEMA_VERSION = 5

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


# Columns added after the first release. Listed rather than folded into the
# schema above so an existing database gains them too.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("channels", "last_classified_at", "INTEGER"),
    ("channels", "banner_url", "TEXT"),
    ("channels", "follower_count", "INTEGER"),
    ("channels", "details_fetched_at", "INTEGER"),
    ("videos", "dislikes", "INTEGER"),
    ("videos", "dislikes_at", "INTEGER"),
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

    def channels_needing_classification(self, interval_s: int, limit: int = 40) -> list[sqlite3.Row]:
        """Channels that still hold videos of unknown kind.

        A channel whose videos are all decided needs no request at all, so in
        the steady state this is only the channels that just gained a video.
        """
        cutoff = int(time.time()) - max(0, interval_s)
        return list(self.conn.execute(
            """
            SELECT c.* FROM channels c
            WHERE c.platform = 'youtube'
              AND (c.last_classified_at IS NULL OR c.last_classified_at <= ?)
              AND EXISTS (SELECT 1 FROM videos v
                           WHERE v.channel_key = c.key AND v.is_short IS NULL)
            ORDER BY c.last_classified_at IS NOT NULL, c.last_classified_at
            LIMIT ?
            """,
            (cutoff, limit),
        ))

    def mark_classified(self, key: str) -> None:
        with self.conn as conn:
            conn.execute("UPDATE channels SET last_classified_at=? WHERE key=?",
                         (int(time.time()), key))

    def set_kind(self, channel_key: str, ext_ids: set[str], is_short: bool) -> int:
        """Record which of a channel's stored videos are Shorts and which are
        not. Only touches rows that are still undecided, so a decision already
        made is never overwritten."""
        if not ext_ids:
            return 0
        with self.conn as conn:
            before = conn.total_changes
            conn.executemany(
                "UPDATE videos SET is_short=? WHERE channel_key=? AND ext_id=? "
                "AND is_short IS NULL",
                [(1 if is_short else 0, channel_key, ext_id) for ext_id in ext_ids],
            )
            return conn.total_changes - before

    def unclassified_count(self, channel_key: str | None = None) -> int:
        if channel_key is None:
            return int(self.conn.execute(
                "SELECT COUNT(*) FROM videos WHERE is_short IS NULL").fetchone()[0])
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM videos WHERE is_short IS NULL AND channel_key=?",
            (channel_key,)).fetchone()[0])

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

    def set_short(self, video_key: str, value: bool) -> None:
        with self.conn as conn:
            conn.execute("UPDATE videos SET is_short=? WHERE key=?", (1 if value else 0, video_key))

    def videos_needing_short_check(self, limit: int = 40) -> list[sqlite3.Row]:
        """Stragglers for the per video redirect test.

        The channel tabs decide almost everything, so this is the fallback for
        a video that appeared in neither of them, which happens for a premiere
        or a stream that has not settled into a tab yet.

        Restricting this to videos of known short duration was a mistake worth
        remembering. Most stored videos never get a duration, because the
        subscriptions sweep only reaches the newest entries, so that rule left
        the vast majority permanently unclassified and hid nothing at all.
        Newest first, since those are the ones being looked at.
        """
        return list(self.conn.execute(
            "SELECT key, ext_id FROM videos "
            "WHERE platform='youtube' AND is_short IS NULL "
            "  AND (duration_s IS NULL OR duration_s <= ?) "
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

        A YouTube stream carries no viewer count here, since neither the feed
        nor the sweep reports one, so those sort after the Twitch entries.
        """
        rows = [dict(row) for row in self.conn.execute(
            "SELECT l.*, c.title AS channel_title, c.avatar_url "
            "FROM live_streams l LEFT JOIN channels c ON c.key = l.channel_key")]
        for row in self.conn.execute(
            "SELECT v.key AS video_key, v.ext_id, v.title, v.thumbnail_url, "
            "       v.channel_key, c.title AS channel_title, c.avatar_url "
            "FROM videos v JOIN channels c ON c.key = v.channel_key "
            "WHERE v.live_status = 'is_live'"
        ):
            rows.append({
                "channel_key": row["channel_key"], "platform": "youtube",
                "login": row["ext_id"], "display_name": row["channel_title"] or "",
                "title": row["title"], "game": "", "viewers": 0,
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

    def unwatched_total(self) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM videos v LEFT JOIN watched w ON w.video_key = v.key "
            "WHERE w.video_key IS NULL AND (v.is_short IS NULL OR v.is_short = 0)"
        ).fetchone()[0])

    def feed(self, limit: int = 300, hide_watched: bool = True,
             group_id: int | None = None, channel_key: str | None = None,
             box_id: int | None = None) -> list[sqlite3.Row]:
        """The video list for whichever view is showing.

        A box orders by the order things were put in it rather than by publish
        date, since that is the point of hand picking. Everything else is
        newest first.
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
