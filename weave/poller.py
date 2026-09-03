"""Feed refresh.

Runs off the GUI thread. Concurrency is bounded twice over, by the executor's
worker count and by the global throttle, so a hundred channels cannot turn into
a hundred simultaneous requests.

One channel failing is not a poll failing. Each error is recorded against its
channel so the Settings debug page can show which source is unhappy, and the
rest of the sweep continues.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, QThread, Signal

from .config import Config
from .db import Database
from .net import Fetcher, Throttle
from .sources import rss


class FeedPoller(QThread):
    finished_poll = Signal(int, int, int)   # channels polled, rows touched, failures
    progress = Signal(int, int)             # done, total
    failure = Signal(str, str)              # channel key, error text

    def __init__(self, db: Database, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._throttle = Throttle(cfg.max_concurrency, cfg.min_request_interval_s)

    def run(self) -> None:
        channels = [c for c in self._db.channels(platform="youtube")]
        total = len(channels)
        if not total:
            self.finished_poll.emit(0, 0, 0)
            return

        fetcher = Fetcher(self._throttle)
        touched = 0
        failures = 0
        done = 0
        try:
            with ThreadPoolExecutor(max_workers=self._cfg.max_concurrency) as pool:
                futures = {
                    pool.submit(self._poll_one, fetcher, row["ext_id"]): row["key"]
                    for row in channels
                }
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:                       # noqa: BLE001
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
                        if not result.videos:
                            # Zero items with no error is exactly how a broken
                            # source looks, so it is worth recording as such.
                            self.failure.emit(key, "returned no entries")
                    done += 1
                    self.progress.emit(done, total)
        finally:
            fetcher.close()
            self._db.close()

        self.finished_poll.emit(total, touched, failures)

    def _poll_one(self, fetcher: Fetcher, channel_id: str) -> rss.FeedResult:
        return rss.fetch(fetcher, channel_id)


class ChannelAdder(QThread):
    """Resolves a channel reference off the interface thread.

    Resolving a handle costs about half a second, which is short enough not to
    need a progress bar and long enough to be felt as a freeze if it ran on the
    interface thread.
    """

    added = Signal(str, str, str, str)   # key, platform, ext_id, title
    failed = Signal(str)

    def __init__(self, ref, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ref = ref
        self._throttle = Throttle(1, cfg.min_request_interval_s)

    def run(self) -> None:
        from .sources.resolve import ResolveError, resolve

        try:
            result = resolve(self._ref, throttle=self._throttle)
        except ResolveError as exc:
            self.failed.emit(str(exc))
            return
        self.added.emit(result.key, result.platform, result.ext_id, result.title or "")
