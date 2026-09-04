"""Reading a track in pieces.

The point of all of it is that a reset connection never reaches the player. So
what is pinned down here is that a failure is retried, that an address which
has stopped being accepted is replaced rather than retried for ever, and that
the bytes handed over are the right ones either way.
"""

import unittest

import requests
from PySide6.QtCore import QCoreApplication

from weave.stream import CHUNK, Prefetcher, RangedSource, RangeReader, StreamGone

_app = QCoreApplication.instance() or QCoreApplication([])

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


class ShortAnswers(unittest.TestCase):
    """A server may answer a range with less than was asked for, and does.

    Handing that back short is quietly wrong rather than obviously wrong. Every
    piece is addressed by multiplying its number by the piece size, so one
    short piece puts every later read at the wrong offset, and the player is
    fed nonsense from the middle of the file. It shows up as the demuxer
    complaining about unknown sized elements and truncating packets of
    impossible length.
    """

    class Stingy(_Session):
        """Never gives more than this much at a time."""

        def __init__(self, most):
            super().__init__()
            self.most = most

        def get(self, url, timeout=None, stream=False, headers=None):
            span = headers["Range"].removeprefix("bytes=")
            first, last = (int(part) for part in span.split("-"))
            last = min(last, first + self.most - 1)
            self.asked.append((url, first, last))
            piece = BODY[first:last + 1]
            return _Response(206, piece,
                             {"Content-Range": f"bytes {first}-{last}/{len(BODY)}"})

    def test_a_short_answer_is_completed_rather_than_passed_on(self):
        session = self.Stingy(1000)
        reader = RangeReader("u", session=session)
        got = reader.read(0, 4096)
        self.assertEqual(len(got), 4096)
        self.assertEqual(got, BODY[:4096])
        self.assertGreater(len(session.asked), 1)

    def test_it_asks_from_where_it_got_to(self):
        session = self.Stingy(1000)
        RangeReader("u", session=session).read(500, 2500)
        self.assertEqual([a[1] for a in session.asked], [500, 1500, 2500])

    def test_the_end_of_the_file_stops_it_rather_than_looping(self):
        session = self.Stingy(1000)
        reader = RangeReader("u", session=session)
        got = reader.read(len(BODY) - 100, 4096)
        self.assertEqual(got, BODY[-100:])

    def test_a_full_piece_is_a_full_piece(self):
        # Which is what keeps every later read at the right offset.
        pieces = Prefetcher(RangeReader("u", session=self.Stingy(7000)))
        self.assertEqual(len(pieces.chunk(0)), CHUNK)


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


class DeviceReads(unittest.TestCase):
    """The device the player reads through, driven the way a player drives it.

    This is the shape of what he saw. Skipping around threw errors and a track
    started ten seconds in, because a short piece had put every later read at
    the wrong offset.
    """

    def source(self, most=None):
        session = ShortAnswers.Stingy(most) if most else _Session()
        device = RangedSource("u")
        device._reader = RangeReader("u", session=session)
        device._pieces = Prefetcher(device._reader)
        self.assertTrue(device.start())
        return device

    def test_it_knows_how_long_the_track_is(self):
        self.assertEqual(self.source().size(), len(BODY))

    def test_reading_from_the_start(self):
        device = self.source()
        self.assertEqual(bytes(device.read(1000)), BODY[:1000])

    def test_reading_after_a_seek(self):
        device = self.source()
        device.seek(5000)
        self.assertEqual(bytes(device.read(1000)), BODY[5000:6000])

    def test_reading_across_a_piece_boundary(self):
        device = self.source()
        device.seek(CHUNK - 500)
        self.assertEqual(bytes(device.read(1000)), BODY[CHUNK - 500:CHUNK + 500])

    def test_seeking_backwards(self):
        device = self.source()
        device.seek(CHUNK + 1000)
        device.read(10)
        device.seek(200)
        self.assertEqual(bytes(device.read(100)), BODY[200:300])

    def test_the_end_of_the_track_is_short_rather_than_wrong(self):
        device = self.source()
        device.seek(len(BODY) - 50)
        self.assertEqual(bytes(device.read(1000)), BODY[-50:])

    def test_all_of_that_holds_when_the_answers_come_up_short(self):
        # The bug. Without completing a short range, every read past the first
        # short piece lands somewhere else entirely.
        device = self.source(most=6000)
        for at in (0, 5000, CHUNK - 500, CHUNK + 4000, 2 * CHUNK + 17):
            device.seek(at)
            self.assertEqual(bytes(device.read(800)), BODY[at:at + 800], f"at {at}")


if __name__ == "__main__":
    unittest.main()
