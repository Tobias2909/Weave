"""A playlist turned round, drawn and played from its end.

mpv plays a playlist address from its start onwards, and the wrapper that
hands it over takes no options, so a turned round playlist sends the pressed
video alone and puts the rest after it over mpv's socket. Not while queue mode
is on, where a press adds only the one video it was for.
"""

import json
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from weave.config import Config
from weave.player.mpv import Player

from . import support


def rows(db, playlist="PLturn"):
    db.replace_playlists([{"ext_id": playlist, "title": "A list"}])
    db.replace_playlist_items(playlist, [
        {"ext_id": f"vid{n}aaaaaaa"[:11], "title": f"Video {n}", "channel_name": "Someone",
         "channel_ext_id": None, "duration_s": 60, "thumbnail_url": None, "views": 1,
         "published_at": None}
        for n in range(4)])


class TheStoredOrder(unittest.TestCase):
    def setUp(self):
        self.db = support.scratch_db(self)
        rows(self.db)

    def titles(self):
        return [row["title"] for row in self.db.playlist_items("PLturn")]

    def test_from_its_start_by_default(self):
        self.assertEqual(self.titles(), ["Video 0", "Video 1", "Video 2", "Video 3"])

    def test_turned_round(self):
        self.db.set_playlist_reversed("PLturn", True)
        self.assertEqual(self.titles(), ["Video 3", "Video 2", "Video 1", "Video 0"])
        self.assertTrue(self.db.playlists(include_hidden=True)[0]["reversed"])

    def test_and_back(self):
        self.db.set_playlist_reversed("PLturn", True)
        self.db.set_playlist_reversed("PLturn", False)
        self.assertEqual(self.titles(), ["Video 0", "Video 1", "Video 2", "Video 3"])

    def test_one_never_kept_can_be_turned_round_too(self):
        self.db.set_playlist_reversed("PLnotkept", True)
        self.assertTrue(self.db.playlist_reversed("PLnotkept"))


class WhatFollowsThePressedVideo(unittest.TestCase):
    def setUp(self):
        from weave.ui.bridge import Bridge

        self.db = support.scratch_db(self)
        rows(self.db)
        self.db.set_playlist_reversed("PLturn", True)
        bridge = Bridge.__new__(Bridge)
        bridge._db = self.db
        bridge._view_playlist = "PLturn"
        self.bridge = bridge

    def test_the_rest_in_the_order_shown(self):
        from weave.ui.bridge import Bridge

        pressed = self.db.playlist_items("PLturn")[1]["key"]          # Video 2
        following = Bridge._following_in_playlist(self.bridge, pressed)
        self.assertEqual([url.rsplit("=", 1)[1] for url in following],
                         ["vid1aaaaaaa", "vid0aaaaaaa"])

    def test_what_would_only_be_refused_is_left_out(self):
        from weave.ui.bridge import Bridge

        with self.db.conn as conn:
            conn.execute("UPDATE playlist_items SET title='[Deleted video]' "
                         "WHERE ext_id='vid1aaaaaaa'")
        pressed = self.db.playlist_items("PLturn")[0]["key"]          # Video 3
        following = Bridge._following_in_playlist(self.bridge, pressed)
        self.assertEqual([url.rsplit("=", 1)[1] for url in following],
                         ["vid2aaaaaaa", "vid0aaaaaaa"])


@unittest.skipUnless(shutil.which("mpv"), "mpv is not installed")
class PutAfterItInARealPlayer(unittest.TestCase):
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
        self.say(["loadfile", "av://lavfi:sine=duration=30", "replace"])
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

    def test_they_go_after_it_in_order(self):
        urls = [f"av://lavfi:sine=frequency={f}:duration=5" for f in (300, 400, 500)]
        self.assertTrue(self.player.queue_after(urls))
        time.sleep(0.3)
        names = [entry["filename"] for entry in self.say(["get_property", "playlist"])]
        self.assertEqual(names[1:], urls)

    def test_not_while_queue_mode_loops_the_playlist(self):
        self.say(["set_property", "loop-playlist", "inf"])
        self.assertFalse(self.player.queue_after(["av://lavfi:sine=duration=5"]))
        time.sleep(0.3)
        self.assertEqual(self.say(["get_property", "playlist-count"]), 1)


if __name__ == "__main__":
    unittest.main()


class PuttingOneWhereAnotherIs(unittest.TestCase):
    """A row dropped on another takes its place, whatever is hidden between."""

    def setUp(self):
        self.db = support.scratch_db(self)
        self.db.replace_playlists([{"ext_id": f"PL{c}", "title": c} for c in "abcde"])
        self.db.set_playlist_hidden("PLb", True)

    def order(self):
        return [row["title"] for row in self.db.playlists(include_hidden=True)]

    def test_upwards_over_a_hidden_one(self):
        self.assertTrue(self.db.move_playlist_to("PLe", "PLa"))
        self.assertEqual(self.order(), list("eabcd"))

    def test_downwards(self):
        self.assertTrue(self.db.move_playlist_to("PLa", "PLd"))
        self.assertEqual(self.order(), list("bcdae"))

    def test_onto_itself_or_nothing_moves_nothing(self):
        self.assertFalse(self.db.move_playlist_to("PLa", "PLa"))
        self.assertFalse(self.db.move_playlist_to("PLa", "PLz"))
        self.assertEqual(self.order(), list("abcde"))
