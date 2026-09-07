"""A playlist can be marked as music, and then it is listened to."""

import tempfile
import unittest
from pathlib import Path

from weave.db import Database


class MarkingAPlaylist(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "weave.db")
        self.db.replace_playlists([{"ext_id": "PL1", "title": "A list"},
                                   {"ext_id": "PL2", "title": "Another"}])

    def test_a_playlist_starts_out_as_something_to_watch(self) -> None:
        self.assertEqual(self.db.playlist("PL1")["is_music"], 0)
        self.assertEqual(self.db.playlists()[0]["is_music"], 0)

    def test_marking_one_leaves_the_others_alone(self) -> None:
        self.db.set_playlist_music("PL1", True)
        self.assertEqual(self.db.playlist("PL1")["is_music"], 1)
        self.assertEqual(self.db.playlist("PL2")["is_music"], 0)

    def test_the_mark_can_be_taken_off_again(self) -> None:
        self.db.set_playlist_music("PL1", True)
        self.db.set_playlist_music("PL1", False)
        self.assertEqual(self.db.playlist("PL1")["is_music"], 0)

    def test_reading_the_playlists_again_keeps_the_mark(self) -> None:
        """A refresh replaces the rows, and the mark must survive it the way
        the hidden flag and the hand picked order already do."""
        self.db.set_playlist_music("PL1", True)
        self.db.replace_playlists([{"ext_id": "PL1", "title": "A list"},
                                   {"ext_id": "PL2", "title": "Another"}])
        self.assertEqual(self.db.playlist("PL1")["is_music"], 1)

    def test_the_chooser_sees_the_mark_on_a_hidden_playlist(self) -> None:
        self.db.set_playlist_music("PL2", True)
        self.db.set_playlist_hidden("PL2", True)
        found = {row["ext_id"]: row for row in self.db.playlists(include_hidden=True)}
        self.assertEqual(found["PL2"]["is_music"], 1)
        self.assertEqual(found["PL2"]["hidden"], 1)


class PressingAVideoInAMusicPlaylist(unittest.TestCase):
    """Where a press is handed to.

    A playlist marked as music must reach the music player, and one that is
    not must still reach mpv, from the very same view.
    """

    def make_bridge(self, is_music: bool):
        from weave.ui.bridge import Bridge

        row = {"key": "yt:aaaaaaaaaaa", "title": "A song", "url": "https://example/watch",
               "isLive": False, "isUpcoming": False}

        class Model:
            def row_for_key(self, key):
                return row if key == row["key"] else None

        class Player:
            def __init__(self):
                self.calls = []

            def play(self, url, twitch_login=None, live=False):
                self.calls.append(url)
                return True

        bridge = Bridge.__new__(Bridge)
        bridge._model = Model()
        bridge._player = Player()
        bridge._view_kind = "playlist"
        bridge._view_playlist = "PL1"
        bridge._db = self.db
        bridge._set_status = lambda *a, **k: None
        bridge._set_notice = lambda *a, **k: None
        # The chip a pressed card shows while mpv starts. Stubbed like the
        # notice, since the timer behind it belongs to a real bridge.
        bridge._set_starting = lambda *a, **k: None
        bridge.listened = []
        bridge.playAudio = bridge.listened.append
        self.db.set_playlist_music("PL1", is_music)
        return bridge

    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "weave.db")
        self.db.replace_playlists([{"ext_id": "PL1", "title": "A list"}])

    def test_a_marked_playlist_listens_instead_of_watching(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.make_bridge(True)
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.listened, ["yt:aaaaaaaaaaa"])
        self.assertEqual(bridge._player.calls, [])

    def test_an_unmarked_playlist_still_goes_to_mpv(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.make_bridge(False)
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.listened, [])
        self.assertEqual(len(bridge._player.calls), 1)

    def test_the_mark_is_ignored_outside_the_playlist_view(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.make_bridge(True)
        bridge._view_kind = "all"
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.listened, [])
        self.assertEqual(len(bridge._player.calls), 1)


if __name__ == "__main__":
    unittest.main()
