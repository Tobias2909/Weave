"""What one request does when the far side does not answer 200.

The feed host answers a burst with a 404 rather than a busy signal, and for a
while that made a 404 look worth retrying. Measured, a refused address came
back after thirty to ninety seconds while the retries waited two and then four,
so during a refusal every refused feed was asked three times within seconds and
the request count saw one. These pin down that a 404 is asked once, that real
retries still happen for a busy signal, and that whatever went over the wire is
counted.
"""

from __future__ import annotations

import unittest
from unittest import mock

from weave.net import Fetcher, HttpError, Throttle


class _Response:
    def __init__(self, status: int, content: bytes = b"", headers=None) -> None:
        self.status_code = status
        self.content = content
        self.headers = headers or {}


class _Session:
    """Answers a scripted list of responses, and remembers being asked."""

    def __init__(self, *responses: _Response) -> None:
        self._responses = list(responses)
        self.asked = 0

    def get(self, url: str, timeout: float) -> _Response:
        self.asked += 1
        return self._responses.pop(0)


def _fetcher(*responses: _Response) -> tuple[Fetcher, _Session]:
    fetcher = Fetcher(Throttle(1, 0.0), attempts=3)
    session = _Session(*responses)
    fetcher._session = session
    return fetcher, session


class ANotFound(unittest.TestCase):
    def test_is_asked_once_and_raised_at_once(self):
        fetcher, session = _fetcher(_Response(404))
        with self.assertRaises(HttpError) as caught:
            fetcher.get_bytes("https://example.invalid/feed")
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(session.asked, 1)
        self.assertEqual(fetcher.sent, 1)


class ABusySignal(unittest.TestCase):
    def test_is_retried_and_every_attempt_is_counted(self):
        fetcher, session = _fetcher(_Response(503), _Response(500), _Response(200, b"ok"))
        with mock.patch("weave.net.time.sleep"):
            self.assertEqual(fetcher.get_bytes("https://example.invalid/feed"), b"ok")
        self.assertEqual(session.asked, 3)
        self.assertEqual(fetcher.sent, 3)

    def test_gives_up_after_the_attempts_and_still_counts_them(self):
        fetcher, session = _fetcher(_Response(500), _Response(500), _Response(500))
        with mock.patch("weave.net.time.sleep"):
            with self.assertRaises(HttpError):
                fetcher.get_bytes("https://example.invalid/feed")
        self.assertEqual(fetcher.sent, 3)


class AnAnswer(unittest.TestCase):
    def test_costs_one(self):
        fetcher, _ = _fetcher(_Response(200, b"<feed/>"))
        self.assertEqual(fetcher.get_bytes("https://example.invalid/feed"), b"<feed/>")
        self.assertEqual(fetcher.sent, 1)


if __name__ == "__main__":
    unittest.main()
