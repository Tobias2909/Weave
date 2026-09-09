"""Outbound HTTP, behind one global throttle.

Every request the app makes goes through a single Throttle instance. That is
deliberate structure rather than discipline. A per feature "remember to be
polite" rule fails the first time two features poll at once, and getting rate
limited by YouTube looks exactly like the app being broken.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import requests

from . import __version__

USER_AGENT = f"Weave/{__version__} (+https://github.com/Tobias2909/Weave)"


class Cancelled(RuntimeError):
    """Raised when a shutdown interrupts a request."""


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

    A 404 is not retried, and it used to be. The feed host answers a burst
    with a 404 rather than a busy signal, so retrying looked right. Measured,
    it never helped: a refused feed came back after thirty to ninety seconds,
    while the retries waited two and then four, so during a refusal every
    refused address was asked three times within seconds, which tripled the
    load on the endpoint at exactly the moment it was asking for less, and the
    request count only saw one. The poller's own rest is what answers a
    refusal now, and one round later is soon enough for one channel.

    `sent` counts every request actually made, retries included, so a caller
    can charge the budget for what went over the wire rather than for what it
    asked for.
    """

    def __init__(self, throttle: Throttle, timeout: float = 15.0, attempts: int = 3,
                 cancel: threading.Event | None = None) -> None:
        self.throttle = throttle
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.sent = 0
        self._count = threading.Lock()
        # Set when the application is shutting down. Retries and backoff stop
        # immediately, so quitting waits at most one in flight request rather
        # than a full retry ladder.
        self.cancel = cancel
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def _cancelled(self) -> bool:
        return self.cancel is not None and self.cancel.is_set()

    def get_bytes(self, url: str) -> bytes:
        last: Exception | None = None
        for attempt in range(self.attempts):
            if self._cancelled():
                raise Cancelled("cancelled")
            with self.throttle.slot():
                with self._count:
                    self.sent += 1
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
                if self.cancel is not None:
                    if self.cancel.wait(min(delay, 30.0)):
                        raise Cancelled("cancelled")
                else:
                    time.sleep(min(delay, 30.0))
        raise last if last else HttpError(0, url)

    def head_status(self, url: str, cookies: dict[str, str] | None = None) -> tuple[int, str]:
        """Ask for the headers alone, without following redirects, returning
        the status and the Location.

        For a caller that reads the redirect itself as the answer rather than
        as somewhere to go, which is how a Short is told from an ordinary
        video. A HEAD rather than a GET because the body would be a megabyte
        of player HTML that nothing here reads, and no retries because there
        is nothing worth asking twice: an unclear answer is left unanswered
        and the row it was about is asked again in a later round.

        Counted in `sent` like every other request, so a budget is charged for
        what actually went over the wire.
        """
        with self.throttle.slot():
            with self._count:
                self.sent += 1
            response = self._session.head(url, timeout=self.timeout, allow_redirects=False,
                                          cookies=cookies or {})
        return response.status_code, response.headers.get("Location", "")

    def close(self) -> None:
        self._session.close()
