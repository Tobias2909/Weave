"""mpv's own playlist, read and changed over its socket for the companion page.

Against a real mpv where one is installed, since what each command does to the
order is mpv's business and is only known by asking it.
"""

import json
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from weave.config import Config
from weave.player.mpv import Player, _IpcWatcher, looping, playlist_entries

_app = QCoreApplication.instance() or QCoreApplication([])

SONG = "av://lavfi:sine=frequency={}:duration=30"


class ReadingIt(unittest.TestCase):
    def test_each_entry_says_its_address_and_whether_it_plays(self):
        self.assertEqual(
            playlist_entries([{"filename": "a", "current": True, "playing": True, "id": 1},
                              {"filename": "b", "title": "B", "id": 2}, "junk", {"id": 3}]),
            [{"url": "a", "current": True, "title": ""},
             {"url": "b", "current": False, "title": "B"}])
        self.assertEqual(playlist_entries(None), [])

    def test_what_goes_round_again(self):
        for value in ("inf", "force", 3, True):
            self.assertTrue(looping(value), value)
        for value in ("no", False, None, 0):
            self.assertFalse(looping(value), value)


class TheWatcherSaysSo(unittest.TestCase):
    def setUp(self):
        self.watcher = _IpcWatcher(Path("/nonexistent.sock"), threshold=0.85)
        self.lists, self.loops = [], []
        self.watcher.playlistChanged.connect(self.lists.append)
        self.watcher.loopChanged.connect(self.loops.append)

    def test_every_change_of_the_playlist_and_its_going_round(self):
        self.watcher._handle({"event": "property-change", "name": "playlist",
                              "data": [{"filename": "a", "current": True}]})
        self.watcher._handle({"event": "property-change", "name": "loop-playlist",
                              "data": "inf"})
        self.assertEqual(self.lists, [[{"url": "a", "current": True, "title": ""}]])
        self.assertEqual(self.loops, [True])

    def test_a_player_gone_leaves_an_empty_playlist(self):
        self.watcher._had_session = True
        self.watcher._announce_gone()
        self.assertEqual(self.lists, [[]])


@unittest.skipUnless(shutil.which("mpv"), "mpv is not installed")
class ChangingItInARealPlayer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sock = Path(self._tmp.name) / "probe.sock"
        self.mpv = subprocess.Popen(
            ["mpv", "--no-config", "--idle=yes", "--ao=null", "--vo=null", "--really-quiet",
             f"--input-ipc-server={self.sock}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while not self.sock.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.player = Player(Config(raw={"player": {"ipc_socket": str(self.sock)}}))

    def tearDown(self):
        self.mpv.terminate()
        self.mpv.wait(5)
        self._tmp.cleanup()

    def say(self, command):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(str(self.sock))
            sock.sendall(json.dumps({"command": command, "request_id": 1}).encode() + b"\n")
            buffer = b""
            while True:
                buffer += sock.recv(65536)
                for line in buffer.split(b"\n"):
                    if line.strip() and json.loads(line).get("request_id") == 1:
                        return json.loads(line).get("data")

    def order(self):
        time.sleep(0.3)
        return [entry["filename"] for entry in self.say(["get_property", "playlist"])]

    def start(self, *freqs):
        for place, freq in enumerate(freqs):
            self.say(["loadfile", SONG.format(freq), "replace" if place == 0 else "append"])
        time.sleep(0.3)

    def test_appended_at_the_end_and_played_when_nothing_plays(self):
        self.assertTrue(self.player.append(SONG.format(100)))
        self.assertEqual(self.order(), [SONG.format(100)])
        self.assertEqual(self.say(["get_property", "playlist-pos"]), 0)
        self.assertTrue(self.player.append(SONG.format(200)))
        self.assertEqual(self.order(), [SONG.format(100), SONG.format(200)])
        self.assertEqual(self.say(["get_property", "playlist-pos"]), 0)

    def test_next_goes_right_after_the_one_playing(self):
        self.start(100, 200, 300)
        self.say(["playlist-play-index", 1])
        time.sleep(0.3)
        self.assertTrue(self.player.insert_next(SONG.format(900)))
        self.assertEqual(self.order(), [SONG.format(f) for f in (100, 200, 900, 300)])
        self.assertEqual(self.say(["get_property", "playlist-pos"]), 1)

    def test_now_goes_there_and_plays(self):
        self.start(100, 200)
        self.assertTrue(self.player.insert_next(SONG.format(900), play=True))
        self.assertEqual(self.order(), [SONG.format(f) for f in (100, 900, 200)])
        time.sleep(0.3)
        self.assertEqual(self.say(["get_property", "playlist-pos"]), 1)

    def test_next_after_the_last_one_is_simply_the_end(self):
        self.start(100, 200)
        self.say(["playlist-play-index", 1])
        time.sleep(0.3)
        self.assertTrue(self.player.insert_next(SONG.format(900)))
        self.assertEqual(self.order(), [SONG.format(f) for f in (100, 200, 900)])

    def test_jump_remove_and_move(self):
        self.start(100, 200, 300, 400)
        self.assertTrue(self.player.jump(2))
        time.sleep(0.3)
        self.assertEqual(self.say(["get_property", "playlist-pos"]), 2)
        self.assertTrue(self.player.remove(0))
        self.assertEqual(self.order(), [SONG.format(f) for f in (200, 300, 400)])
        # In front of the one at the place given, the end for the length.
        self.assertTrue(self.player.move(2, 0))
        self.assertEqual(self.order(), [SONG.format(f) for f in (400, 200, 300)])
        self.assertTrue(self.player.move(0, 3))
        self.assertEqual(self.order(), [SONG.format(f) for f in (200, 300, 400)])

    def test_clear_leaves_only_the_one_playing(self):
        self.start(100, 200, 300, 400)
        self.assertTrue(self.player.jump(2))
        time.sleep(0.3)
        self.assertTrue(self.player.clear())
        self.assertEqual(self.order(), [SONG.format(300)])
        self.assertEqual(self.say(["get_property", "playlist-pos"]), 0)

    def test_the_watcher_follows_the_playlist_of_a_real_player(self):
        lists, loops = [], []
        watcher = _IpcWatcher(self.sock, threshold=0.85)
        watcher.playlistChanged.connect(lists.append)
        watcher.loopChanged.connect(loops.append)
        watcher.start()
        try:
            self.start(100, 200)
            self.say(["set_property", "loop-playlist", "inf"])
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not (
                    lists and len(lists[-1]) == 2 and loops and loops[-1]):
                QCoreApplication.processEvents()
                time.sleep(0.05)
            self.assertEqual([entry["url"] for entry in lists[-1]],
                             [SONG.format(100), SONG.format(200)])
            self.assertTrue(lists[-1][0]["current"])
            self.assertEqual(loops[-1], True)
        finally:
            watcher.stop()
            watcher.wait(3000)

    def test_no_player_is_said_rather_than_raised(self):
        self.mpv.terminate()
        self.mpv.wait(5)
        self.sock.unlink(missing_ok=True)
        self.assertFalse(self.player.append(SONG.format(100)))
        self.assertFalse(self.player.jump(0))
        self.mpv = subprocess.Popen(["true"])


if __name__ == "__main__":
    unittest.main()
