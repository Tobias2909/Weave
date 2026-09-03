"""Background work.

A refresh runs in three phases, and each one is allowed to fail on its own.
RSS is the only phase the feed truly needs, so a broken login or a missing
yt-dlp costs the duration badges and the Shorts filter while the feed itself
keeps working.

  1  channel RSS, which brings new videos with their publish times
  2  the subscriptions sweep, which joins in durations and live flags
  3  the Shorts redirect test on whatever is still undecided

Concurrency is bounded twice over, by the executor and by the global throttle,
so a few hundred channels cannot become a few hundred simultaneous requests.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, QThread, Signal

from .classify import classify_channel
from .config import Config
from .db import Database
from .net import Cancelled as FetchCancelled
from .net import Fetcher, Throttle
from .process import Cancelled as ProcessCancelled
from .sources import channel as channel_source
from .sources import rss, shorts, subs, sweep, tabs


class FeedPoller(QThread):
    finished_poll = Signal(int, int, int)   # channels polled, rows touched, failures
    progress = Signal(str, int, int)        # phase, done, total
    failure = Signal(str, str)              # source label, error text

    def __init__(self, db: Database, cfg: Config, force_all: bool = False,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._force_all = force_all
        self._throttle = Throttle(cfg.max_concurrency, cfg.min_request_interval_s)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Ask the poll to stop. Qt aborts the whole process if a running
        QThread is destroyed, so every thread needs this."""
        self._cancel.set()

    def run(self) -> None:
        fetcher = Fetcher(self._throttle, cancel=self._cancel)
        polled = touched = failures = 0
        try:
            polled, touched, failures = self._phase_rss(fetcher)
            if not self._cancel.is_set():
                touched += self._phase_sweep()
            if not self._cancel.is_set():
                self._phase_classify()
            if not self._cancel.is_set():
                self._phase_shorts(fetcher)
        except (FetchCancelled, ProcessCancelled):
            pass
        finally:
            fetcher.close()
            self._db.close()
        self.finished_poll.emit(polled, touched, failures)

    # ---- phase 1 ---------------------------------------------------------

    def _phase_rss(self, fetcher: Fetcher) -> tuple[int, int, int]:
        channels = (self._db.channels(platform="youtube") if self._force_all
                    else self._db.channels_due(self._cfg.feed_interval_s))
        total = len(channels)
        if not total:
            return 0, 0, 0

        touched = failures = done = 0
        with ThreadPoolExecutor(max_workers=self._cfg.max_concurrency) as pool:
            futures = {pool.submit(rss.fetch, fetcher, row["ext_id"]): row["key"]
                       for row in channels}
            for future in as_completed(futures):
                if self._cancel.is_set():
                    # Drops what has not started. Anything already in flight
                    # finishes on its own timeout, which is why the request
                    # timeout is kept short.
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                key = futures[future]
                try:
                    result = future.result()
                except (FetchCancelled, ProcessCancelled):
                    break
                except Exception as exc:                            # noqa: BLE001
                    failures += 1
                    message = f"{type(exc).__name__}: {exc}"
                    self._db.mark_polled(key, message)
                    self.failure.emit(key, message)
                else:
                    touched += self._db.upsert_videos(result.videos)
                    if result.channel_title:
                        self._db.add_channel(key, "youtube", key.split(":", 1)[1],
                                             result.channel_title)
                    self._db.mark_polled(key, None)
                    if not result.videos and self._db.channel_has_videos(key):
                        # Zero entries with no error is what a broken source
                        # looks like. But a channel that has never produced a
                        # video is simply empty, and there are plenty of those
                        # in a large subscription list, so only a channel that
                        # used to have videos and now has none is reported.
                        self.failure.emit(key, "returned no entries")
                done += 1
                self.progress.emit("feeds", done, total)
        return total, touched, failures

    # ---- phase 2 ---------------------------------------------------------

    def _phase_sweep(self) -> int:
        if not self._cfg.sweep_limit:
            return 0
        self.progress.emit("durations", 0, 1)
        try:
            videos = sweep.fetch(self._cfg, self._cfg.sweep_limit, self._throttle,
                                 cancel=self._cancel)
        except ProcessCancelled:
            return 0
        except sweep.SweepError as exc:
            self.failure.emit("durations", str(exc))
            return 0
        filled = self._db.fill_details([(v.key, v.duration_s, v.live_status) for v in videos])
        self.progress.emit("durations", 1, 1)
        return filled

    # ---- phase 3 ---------------------------------------------------------

    def _phase_classify(self) -> None:
        limit = self._cfg.classify_per_cycle
        if not limit:
            return
        channels = self._db.channels_needing_classification(
            self._cfg.classify_interval_s, limit)
        total = len(channels)
        if not total:
            return

        done = 0
        with ThreadPoolExecutor(max_workers=self._cfg.max_concurrency) as pool:
            futures = {
                pool.submit(classify_channel, self._db, row["key"], row["ext_id"],
                            self._throttle, self._cancel): row["key"]
                for row in channels
            }
            for future in as_completed(futures):
                if self._cancel.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return
                try:
                    future.result()
                except ProcessCancelled:
                    return
                except tabs.TabError as exc:
                    self.failure.emit(futures[future], f"listing, {exc}")
                except Exception as exc:                            # noqa: BLE001
                    self.failure.emit(futures[future], f"{type(exc).__name__}: {exc}")
                done += 1
                self.progress.emit("kinds", done, total)

    # ---- phase 4 ---------------------------------------------------------

    def _phase_shorts(self, fetcher: Fetcher) -> None:
        limit = self._cfg.shorts_per_cycle
        if not limit:
            return
        candidates = self._db.videos_needing_short_check(limit)
        total = len(candidates)
        for index, row in enumerate(candidates, start=1):
            if self._cancel.is_set():
                return
            try:
                self._db.set_short(row["key"], shorts.classify(fetcher, row["ext_id"]))
            except FetchCancelled:
                return
            except shorts.UndecidedError:
                # Left unclassified on purpose, so it is retried later rather
                # than filed wrongly.
                pass
            except Exception as exc:                                # noqa: BLE001
                self.failure.emit("shorts", f"{type(exc).__name__}: {exc}")
                return
            self.progress.emit("shorts", index, total)


class ChannelAdder(QThread):
    """Resolves a channel reference off the interface thread.

    Resolving costs about half a second, short enough not to need a progress
    bar and long enough to be felt as a freeze on the interface thread.
    """

    added = Signal(str, str, str, str)   # key, platform, ext_id, title
    failed = Signal(str)

    def __init__(self, ref, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ref = ref
        self._throttle = Throttle(1, cfg.min_request_interval_s)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        from .sources.resolve import ResolveError, resolve

        try:
            result = resolve(self._ref, throttle=self._throttle, cancel=self._cancel)
        except ProcessCancelled:
            return
        except ResolveError as exc:
            self.failed.emit(str(exc))
            return
        self.added.emit(result.key, result.platform, result.ext_id, result.title or "")


class SubsImporter(QThread):
    """Imports the subscription list, names and avatars included."""

    imported = Signal(int, int)          # total found, newly added
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._throttle = Throttle(1, cfg.min_request_interval_s)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            channels = subs.fetch(self._cfg, self._throttle, cancel=self._cancel)
        except ProcessCancelled:
            return
        except subs.ImportError_ as exc:
            self.failed.emit(str(exc))
            return
        added = 0
        for channel in channels:
            if self._db.add_channel(channel.key, "youtube", channel.ext_id,
                                    channel.title, channel.avatar_url):
                added += 1
        self._db.close()
        self.imported.emit(len(channels), added)


class ChannelDetailsFetcher(QThread):
    """Fills in a channel's banner and subscriber count the first time its page
    is opened."""

    fetched = Signal(str)
    failed = Signal(str, str)

    def __init__(self, db: Database, cfg: Config, channel_key: str, ext_id: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._key = channel_key
        self._ext_id = ext_id
        self._throttle = Throttle(1, cfg.min_request_interval_s)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            details = channel_source.fetch(self._ext_id, self._throttle, self._cancel)
        except ProcessCancelled:
            return
        except channel_source.DetailsError as exc:
            self.failed.emit(self._key, str(exc))
            return
        self._db.set_channel_details(self._key, details.title, details.avatar_url,
                                     details.banner_url, details.follower_count)
        self._db.close()
        self.fetched.emit(self._key)
