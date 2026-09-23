"""What was written under a video, in the panel beside the feed.

It rides along with the call that brings the comments, so it costs nothing of
its own. A time written in it goes to that point, but only while mpv is
playing that very video, which is the only one a time can be about.
"""

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication, QObject

from weave.config import Config
from weave.ui.bridge import Bridge

_app = QCoreApplication.instance() or QCoreApplication([])

KEY = "yt:aaaaaaaaaaa"
WORDS = "What it is.\n3:25 the middle part"


def bridge_with(mpv_key: str = ""):
    made = Bridge.__new__(Bridge)
    QObject.__init__(made)
    made._detail_key = KEY
    made._detail_extra = {}
    made._detail_dislikes = None
    made._mpv_key = mpv_key
    row = {"key": KEY, "title": "Theirs", "channel_key": "yt:UC1", "channel_title": "One",
           "avatar_url": None, "thumbnail_url": None, "published_at": None,
           "duration_s": None, "views": None, "likes": None, "watched": 0,
           "live_status": None, "scheduled_at": None}
    made._video_for_detail = lambda key: dict(row) if key == KEY else None
    made._keep_extra(KEY, {"description": WORDS, "duration_s": 600})
    return made


class TheDescription(unittest.TestCase):
    def test_it_is_in_the_panel(self):
        detail = Bridge._get_detail(bridge_with())
        self.assertIn("What it is.", detail["descriptionText"])

    def test_a_time_is_plain_while_mpv_plays_something_else(self):
        detail = Bridge._get_detail(bridge_with(mpv_key="yt:bbbbbbbbbbb"))
        self.assertNotIn("weave-seek", detail["descriptionText"])

    def test_and_pressable_while_it_plays_this_one(self):
        detail = Bridge._get_detail(bridge_with(mpv_key=KEY))
        self.assertIn('href="weave-seek:205"', detail["descriptionText"])

    def test_the_song_page_reading_its_own_comments_does_not_wipe_it(self):
        """The panel and the Now playing page each make a comments call, and
        one slot for both let the second throw the first one's words away."""
        made = bridge_with()
        made._keep_extra("yt:bbbbbbbbbbb", {"description": "About the song."})
        self.assertIn("What it is.", Bridge._get_detail(made)["descriptionText"])

    def test_a_time_is_only_sent_to_mpv_for_the_video_it_is_about(self):
        made = bridge_with(mpv_key="yt:bbbbbbbbbbb")

        class Player:
            def __init__(self):
                self.sent = []

            def seek(self, seconds):
                self.sent.append(seconds)
                return True

        made._player = Player()
        Bridge.seekVideo(made, 205)
        self.assertEqual(made._player.sent, [])
        made._mpv_key = KEY
        Bridge.seekVideo(made, 205)
        self.assertEqual(made._player.sent, [205])


class TheSeekItself(unittest.TestCase):
    def test_mpv_is_told_one_absolute_seek_over_its_socket(self):
        from weave.player import mpv as player

        folder = tempfile.TemporaryDirectory(prefix="weave-seek-")
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "mpv.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        server.listen(1)
        self.addCleanup(server.close)
        heard = []

        def take():
            conn, _ = server.accept()
            with conn:
                heard.append(conn.recv(4096))

        listener = threading.Thread(target=take)
        listener.start()
        made = player.Player.__new__(player.Player)
        made._cfg = Config(raw={})
        with mock.patch.object(player, "resolve_socket", lambda _cfg: path):
            self.assertTrue(player.Player.seek(made, 205))
        listener.join(2)
        self.assertEqual(json.loads(heard[0].decode()),
                         {"command": ["seek", 205.0, "absolute"]})

    def test_no_mpv_to_tell_is_said_rather_than_raised(self):
        from weave.player import mpv as player

        made = player.Player.__new__(player.Player)
        made._cfg = Config(raw={})
        with mock.patch.object(player, "resolve_socket",
                               lambda _cfg: Path(tempfile.gettempdir()) / "weave-no-such.sock"):
            self.assertFalse(player.Player.seek(made, 10))


if __name__ == "__main__":
    unittest.main()
