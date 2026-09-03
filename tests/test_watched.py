"""Watched detection, driven by synthetic IPC messages.

This tests the decision rule without needing mpv, which keeps it fast and
deterministic. A separate live check exercises the socket plumbing against a
real mpv, because these two can fail independently.
"""

import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from weave.player.mpv import _IpcWatcher

YT = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
YT_OTHER = "https://www.youtube.com/watch?v=bbbbbbbbbbb"

_app = QCoreApplication.instance() or QCoreApplication([])


class Rule(unittest.TestCase):
    def setUp(self):
        self.watcher = _IpcWatcher(Path("/nonexistent.sock"), threshold=0.7)
        self.marked: list[tuple[str, float]] = []
        self.playing: list[tuple[str, str]] = []
        self.watcher.watched.connect(lambda k, p: self.marked.append((k, p)))
        self.watcher.nowPlaying.connect(lambda k, t: self.playing.append((k, t)))

    def feed(self, name, data):
        self.watcher._handle({"event": "property-change", "name": name, "data": data})

    def load(self, path, duration=100.0):
        self.feed("path", path)
        self.feed("duration", duration)

    def test_reports_at_the_threshold(self):
        self.load(YT)
        for pos in range(0, 70):
            self.feed("time-pos", float(pos))
        self.assertEqual(self.marked, [])
        self.feed("time-pos", 70.0)
        self.assertEqual(len(self.marked), 1)
        key, progress = self.marked[0]
        self.assertEqual(key, "yt:aaaaaaaaaaa")
        self.assertAlmostEqual(progress, 0.7, places=3)

    def test_reports_only_once(self):
        self.load(YT)
        for pos in (70.0, 80.0, 90.0, 99.0):
            self.feed("time-pos", pos)
        self.watcher._handle({"event": "end-file", "reason": "eof"})
        self.assertEqual(len(self.marked), 1)

    def test_end_of_file_counts_even_below_the_threshold(self):
        # A video played to the end still counts, whatever fraction
        # mpv managed to report before it stopped.
        self.load(YT)
        self.feed("time-pos", 5.0)
        self.watcher._handle({"event": "end-file", "reason": "eof"})
        self.assertEqual([k for k, _ in self.marked], ["yt:aaaaaaaaaaa"])

    def test_quitting_early_does_not_count(self):
        self.load(YT)
        self.feed("time-pos", 30.0)
        self.watcher._handle({"event": "end-file", "reason": "quit"})
        self.assertEqual(self.marked, [])

    def test_switching_video_flushes_then_resets(self):
        self.load(YT)
        self.feed("time-pos", 95.0)          # over the threshold, reported
        self.load(YT_OTHER)                  # handoff to another video
        self.feed("time-pos", 10.0)          # only 10 percent of the new one
        self.watcher._handle({"event": "end-file", "reason": "quit"})
        self.assertEqual([k for k, _ in self.marked], ["yt:aaaaaaaaaaa"])

    def test_position_does_not_leak_across_videos(self):
        # A new path must clear both, otherwise the next video inherits the
        # previous one's progress and gets marked watched immediately.
        self.load(YT)
        self.feed("time-pos", 95.0)
        self.feed("path", YT_OTHER)
        self.assertEqual(self.watcher._max_pos, 0.0)
        self.assertIsNone(self.watcher._duration)

    def test_live_stream_never_marks_watched(self):
        # A live stream reports duration 0, so no progress can be computed.
        self.feed("path", YT)
        self.feed("duration", 0)
        for pos in range(0, 600, 30):
            self.feed("time-pos", float(pos))
        self.watcher._handle({"event": "end-file", "reason": "eof"})
        self.assertEqual([k for k, _ in self.marked], ["yt:aaaaaaaaaaa"])
        # Reaching the end of a stream still counts, but nothing marked it on
        # progress alone during those ten minutes.
        self.assertEqual(len(self.marked), 1)

    def test_unidentifiable_path_is_ignored(self):
        self.load("/home/user/holiday.mkv")
        self.feed("time-pos", 99.0)
        self.watcher._handle({"event": "end-file", "reason": "eof"})
        self.assertEqual(self.marked, [])

    def test_twitch_needs_the_hint(self):
        m3u8 = "https://video-weaver.ham02.hls.ttvnw.net/v1/playlist/blob.m3u8"
        self.load(m3u8)
        self.feed("time-pos", 99.0)
        self.assertEqual(self.marked, [])
        self.watcher.set_twitch_hint("examplechannel")
        self.load(m3u8)
        self.feed("time-pos", 99.0)
        self.assertEqual([k for k, _ in self.marked], ["twitch:examplechannel"])

    def test_now_playing_is_announced(self):
        self.load(YT)
        self.assertEqual([k for k, _ in self.playing], ["yt:aaaaaaaaaaa"])

    def test_seeking_backwards_keeps_the_highest_position(self):
        self.load(YT)
        self.feed("time-pos", 80.0)
        self.feed("time-pos", 5.0)
        self.assertEqual(self.watcher._max_pos, 80.0)


if __name__ == "__main__":
    unittest.main()
