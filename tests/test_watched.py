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
        # A real session sets this when it connects.
        self.watcher._had_session = True
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

    def test_a_live_stream_is_never_marked(self):
        # The trap this guards. mpv reports a duration for a live stream, but
        # it is the length of the sliding window rather than of the stream,
        # measured at about fifteen seconds, so a few seconds of watching
        # already looks like most of the video.
        self.feed("path", YT)
        self.feed("seekable", False)
        self.feed("duration", 15.0)
        for pos in range(0, 600, 5):
            self.feed("time-pos", float(pos))
        self.assertEqual(self.marked, [])

    def test_a_live_stream_ending_is_not_a_video_being_finished(self):
        self.feed("path", YT)
        self.feed("seekable", False)
        self.feed("duration", 15.0)
        self.feed("time-pos", 14.0)
        self.watcher._handle({"event": "end-file", "reason": "eof"})
        self.assertEqual(self.marked, [])

    def test_weave_saying_it_is_live_is_enough_on_its_own(self):
        # Covers a stream whose seekable flag has not arrived yet.
        self.watcher.set_live_hint(True)
        self.load(YT)
        self.feed("time-pos", 99.0)
        self.watcher._handle({"event": "end-file", "reason": "eof"})
        self.assertEqual(self.marked, [])

    def test_mpv_saying_it_is_not_seekable_is_enough_on_its_own(self):
        # Covers a stream started from somewhere other than Weave.
        self.load(YT)
        self.feed("seekable", False)
        self.feed("time-pos", 99.0)
        self.assertEqual(self.marked, [])

    def test_an_ordinary_seekable_video_is_still_marked(self):
        self.load(YT)
        self.feed("seekable", True)
        self.feed("time-pos", 71.0)
        self.assertEqual([k for k, _ in self.marked], ["yt:aaaaaaaaaaa"])

    def test_weaves_live_flag_applies_to_the_file_it_started(self):
        # The flag is set before the handoff, so it has to survive until the
        # path arrives and then be consumed by it.
        self.watcher.set_live_hint(True)
        self.load(YT)
        self.feed("time-pos", 99.0)
        self.assertEqual(self.marked, [])

    def test_weaves_live_flag_does_not_carry_to_a_later_track(self):
        # mpv moving on by itself must start from a clean slate, otherwise a
        # normal video after a stream could never be marked.
        self.watcher.set_live_hint(True)
        self.load(YT)
        self.feed("time-pos", 99.0)
        self.load(YT_OTHER)
        self.feed("seekable", True)
        self.feed("time-pos", 95.0)
        self.assertEqual([k for k, _ in self.marked], ["yt:bbbbbbbbbbb"])

    def test_the_live_flag_does_not_leak_to_the_next_video(self):
        self.feed("path", YT)
        self.feed("seekable", False)
        self.feed("duration", 15.0)
        self.feed("time-pos", 14.0)
        self.load(YT_OTHER)
        self.feed("seekable", True)
        self.feed("time-pos", 90.0)
        self.assertEqual([k for k, _ in self.marked], ["yt:bbbbbbbbbbb"])

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

    def test_a_clean_exit_is_announced(self):
        # The panel mirrors what is playing, so it needs to know when there is
        # nothing playing any more.
        gone = []
        self.watcher.stopped.connect(lambda: gone.append(True))
        self.load(YT)
        self.watcher._handle({"event": "shutdown"})
        self.assertEqual(len(gone), 1)

    def test_an_exit_is_only_announced_once(self):
        gone = []
        self.watcher.stopped.connect(lambda: gone.append(True))
        self.load(YT)
        self.watcher._handle({"event": "shutdown"})
        self.watcher._handle({"event": "shutdown"})
        self.assertEqual(len(gone), 1)

    def test_nothing_is_announced_before_anything_connected(self):
        gone = []
        self.watcher.stopped.connect(lambda: gone.append(True))
        self.watcher._announce_gone()
        self.assertEqual(gone, [])

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
