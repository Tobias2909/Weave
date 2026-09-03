"""Outbound HTTP, behind one global throttle.

Every request the app makes goes through a single Throttle instance. That is
deliberate structure rather than discipline. A per feature "remember to be
polite" rule fails the first time two features poll at once, and getting rate
limited by YouTube looks exactly like the app being broken.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

import requests

from . import __version__

USER_AGENT = f"Weave/{__version__} (+https://github.com/Tobias2909/Weave)"


class HttpError(RuntimeError):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url


class Throttle:
    """Caps concurrency and enforces a minimum gap between request starts."""

    def __init__(self, max_concurrency: int = 4, min_interval_s: float = 0.25) -> None:
        self._sem = threading.BoundedSemaphore(max(1, max_concurrency))
        self._min_interval = max(0.0, min_interval_s)
        self._gate = threading.Lock()
        self._last_start = 0.0

    @contextmanager
    def slot(self) -> Iterator[None]:
        """Hold a request slot. Subprocess callers such as yt-dlp use this too,
        so the throttle covers everything and not only requests calls."""
        self._sem.acquire()
        try:
            with self._gate:
                wait = self._min_interval - (time.monotonic() - self._last_start)
                if wait > 0:
                    time.sleep(wait)
                self._last_start = time.monotonic()
            yield
        finally:
            self._sem.release()


class Fetcher:
    """A requests session with the throttle, a real user agent and retries.

    Retries cover 429 and 5xx only, honour Retry-After when present, and give
    up after `attempts` tries so a poll cannot hang forever on a dead host.
    """

    def __init__(self, throttle: Throttle, timeout: float = 20.0, attempts: int = 3) -> None:
        self.throttle = throttle
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def get_bytes(self, url: str) -> bytes:
        last: Exception | None = None
        for attempt in range(self.attempts):
            with self.throttle.slot():
                try:
                    response = self._session.get(url, timeout=self.timeout)
                except requests.RequestException as exc:
                    last = exc
                    response = None
            if response is not None:
                if response.status_code == 200:
                    return response.content
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise HttpError(response.status_code, url)
                last = HttpError(response.status_code, url)
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if (retry_after or "").isdigit() else 2.0 * (attempt + 1)
            else:
                delay = 2.0 * (attempt + 1)
            if attempt + 1 < self.attempts:
                time.sleep(min(delay, 30.0))
        raise last if last else HttpError(0, url)

    def close(self) -> None:
        self._session.close()
