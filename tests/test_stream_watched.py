"""When a stream counts as watched.

A stream cannot be judged while it is live. mpv reports the rewind window as
the length and starts playback at the live edge, so any share read then says
that all of it has been seen after a second or two. It is judged once it has
ended, against the length the recording turned out to be, and what decides it
is where playback stopped rather than when it was joined or how long it ran.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave import ids
from weave.db import Database, VideoRow
from weave.sources import progress

CHANNEL = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"
HOUR = 3600


class Judging(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.later = self.root / "watch_later"
        self.later.mkdir()
        self.db = Database(self.root / "t.db")
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def stream(self, ext_id: str, length: int, status: str = "was_live") -> str:
        self.db.upsert_videos([VideoRow("youtube", ext_id, CHANNEL, ext_id,
                                        published_at=1_700_000_000, duration_s=length,
                                        live_status=status)])
        return f"yt:{ext_id}"

    def stopped_at(self, ext_id: str, seconds: float) -> None:
        url = ids.watch_url("youtube", ext_id)
        (self.later / progress.filename_for(url)).write_text(
            f"# {url}\nstart={seconds}\n")

    def judge(self, threshold: float = 0.85) -> list[str]:
        """What the bridge's sweep does, without a bridge. Kept in step with
        it by the drive walk, which runs the real one."""
        marked = []
        rows = self.db.streams_to_judge()
        urls = {row["key"]: ids.watch_url(row["platform"], row["ext_id"]) for row in rows}
        found = progress.positions_for(list(urls.values()), self.later)
        for row in rows:
            seconds = found.get(urls[row["key"]])
            if not seconds:
                continue
            share = min(1.0, seconds / row["duration_s"])
            if share >= threshold:
                self.db.set_watched(row["key"], share, "mpv")
                marked.append(row["key"])
        return marked

    def test_stopping_near_the_end_marks_it(self):
        key = self.stream("endofit0001", 2 * HOUR)
        self.stopped_at("endofit0001", 1.9 * HOUR)
        self.assertEqual(self.judge(), [key])

    def test_stopping_in_the_middle_does_not(self):
        self.stream("halfway0001", 6 * HOUR)
        self.stopped_at("halfway0001", 3 * HOUR)
        self.assertEqual(self.judge(), [])

    def test_a_few_minutes_of_a_long_stream_does_not(self):
        # His own case. Five minutes of a six hour stream was marked watched
        # because the live window said it was all of it.
        self.stream("fewmins0001", 6 * HOUR)
        self.stopped_at("fewmins0001", 5 * 60)
        self.assertEqual(self.judge(), [])

    def test_when_you_joined_makes_no_difference(self):
        # Joined for the last ten minutes and stayed to the end. Where it
        # stopped is the whole of the answer.
        key = self.stream("joinlate001", HOUR)
        self.stopped_at("joinlate001", HOUR - 30)
        self.assertEqual(self.judge(), [key])

    def test_a_stream_still_running_is_not_judged(self):
        self.stream("stillon0001", HOUR, status="is_live")
        self.stopped_at("stillon0001", HOUR - 10)
        self.assertEqual(self.judge(), [])

    def test_nor_is_one_with_no_length_yet(self):
        self.db.upsert_videos([VideoRow("youtube", "nolength001", CHANNEL, "No length",
                                        published_at=1_700_000_000, live_status="was_live")])
        self.stopped_at("nolength001", 600)
        self.assertEqual(self.judge(), [])

    def test_nor_one_nobody_has_played(self):
        self.stream("neverplay01", HOUR)
        self.assertEqual(self.judge(), [])

    def test_and_one_already_marked_is_left_alone(self):
        key = self.stream("already0001", HOUR)
        self.db.set_watched(key, 0.2, "youtube")
        self.stopped_at("already0001", HOUR - 10)
        self.assertEqual(self.judge(), [])
        self.assertAlmostEqual(
            self.db.conn.execute("SELECT progress FROM watched WHERE video_key=?",
                                 (key,)).fetchone()[0], 0.2)


if __name__ == "__main__":
    unittest.main()
