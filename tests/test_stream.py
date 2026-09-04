"""Reading a track in pieces.

The point of all of it is that a reset connection never reaches the player. So
what is pinned down here is that a failure is retried, that an address which
has stopped being accepted is replaced rather than retried for ever, and that
the bytes handed over are the right ones either way.
"""

import unittest

import requests

from weave.stream import CHUNK, Prefetcher, RangeReader, StreamGone

BODY = bytes(range(256)) * 8192          # 2 MB of something recognisable


class _Response:
    def __init__(self, status, body=b"", headers=None):
        self.status_code = status
        self.content = body
        self.headers = headers or {}


class _Session:
    """Answers ranges out of BODY, and can be told to fail first."""

    def __init__(self, fail_times=0, status=None, only_for=None):
        self.headers = {}
        self.fail_times = fail_times
        self.status = status
        self.only_for = only_for
        self.asked = []

    def get(self, url, timeout=None, stream=False, headers=None):
        span = headers["Range"].removeprefix("bytes=")
        first, last = (int(part) for part in span.split("-"))
        self.asked.append((url, first, last))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise requests.ConnectionError("connection reset by peer")
        if self.status and (self.only_for is None or url == self.only_for):
            return _Response(self.status)
        piece = BODY[first:last + 1]
        return _Response(206, piece, {"Content-Range": f"bytes {first}-{last}/{len(BODY)}"})


class Reading(unittest.TestCase):
    def test_a_range_comes_back_as_the_right_bytes(self):
        reader = RangeReader("u", session=_Session())
        self.assertEqual(reader.read(100, 50), BODY[100:150])

    def test_the_length_is_learned_from_the_first_answer(self):
        reader = RangeReader("u", session=_Session())
        reader.read(0, 10)
        self.assertEqual(reader.size, len(BODY))

    def test_a_reset_is_tried_again_rather_than_given_up_on(self):
        # The whole reason this module exists.
        session = _Session(fail_times=2)
        reader = RangeReader("u", session=session)
        self.assertEqual(reader.read(0, 10), BODY[0:10])
        self.assertEqual(len(session.asked), 3)

    def test_something_that_never_answers_is_reported(self):
        reader = RangeReader("u", session=_Session(fail_times=99))
        with self.assertRaises(StreamGone):
            reader.read(0, 10)

    def test_an_address_that_is_refused_is_replaced(self):
        # A signed address stops being accepted after a few hours, and no
        # amount of asking it again helps.
        session = _Session(status=403, only_for="stale")
        reader = RangeReader("stale", lambda: "fresh", session=session)
        self.assertEqual(reader.read(0, 10), BODY[0:10])
        self.assertEqual(reader.renewals, 1)
        self.assertEqual(session.asked[-1][0], "fresh")

    def test_a_refusal_with_nowhere_to_turn_is_reported(self):
        reader = RangeReader("stale", session=_Session(status=403))
        with self.assertRaises(StreamGone):
            reader.read(0, 10)

    def test_a_renewal_that_gives_the_same_address_is_not_one(self):
        reader = RangeReader("same", lambda: "same", session=_Session(status=403))
        with self.assertRaises(StreamGone):
            reader.read(0, 10)
        self.assertEqual(reader.renewals, 0)

    def test_a_renewal_that_itself_fails_is_not_an_explosion(self):
        def broken():
            raise RuntimeError("yt-dlp is not there")

        reader = RangeReader("stale", broken, session=_Session(status=403))
        with self.assertRaises(StreamGone):
            reader.read(0, 10)


class Pieces(unittest.TestCase):
    def test_a_piece_is_fetched_once_and_kept(self):
        session = _Session()
        pieces = Prefetcher(RangeReader("u", session=session))
        first = pieces.chunk(0)
        again = pieces.chunk(0)
        self.assertEqual(first, again)
        # One for the piece itself; the rest is reading ahead.
        self.assertEqual(sum(1 for a in session.asked if a[1] == 0), 1)

    def test_the_pieces_join_up_into_what_was_asked_for(self):
        pieces = Prefetcher(RangeReader("u", session=_Session()))
        joined = pieces.chunk(0) + pieces.chunk(1)
        self.assertEqual(joined, BODY[:len(joined)])

    def test_a_piece_past_the_end_is_simply_short(self):
        pieces = Prefetcher(RangeReader("u", session=_Session()))
        last = pieces.chunk(len(BODY) // CHUNK)
        self.assertLess(len(last), CHUNK)


if __name__ == "__main__":
    unittest.main()
