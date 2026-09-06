"""Songs kept on purpose.

A favourite is one of the songs already known, so it is a mark on that row
rather than a copy of it in a second table. Copying is how the two of them
come apart when a title or a picture changes on one side only.
"""

import tempfile
import unittest
from pathlib import Path

from weave.db import Database


class KeepingASong(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "weave.db")

    def test_a_song_never_played_here_can_still_be_kept(self) -> None:
        self.db.set_music_favorite("aaaaaaaaaaa", True, "A song", "An artist",
                                   "https://x/t.jpg", 200)
        self.assertTrue(self.db.is_music_favorite("aaaaaaaaaaa"))
        row = self.db.music_favorites()[0]
        self.assertEqual(row["title"], "A song")
        self.assertEqual(row["channel_title"], "An artist")
        self.assertEqual(row["key"], "yt:aaaaaaaaaaa")

    def test_playing_it_afterwards_does_not_drop_the_mark(self) -> None:
        self.db.set_music_favorite("aaaaaaaaaaa", True, "A song", "An artist", None)
        self.db.remember_played("aaaaaaaaaaa", "A song", "An artist", None)
        self.assertTrue(self.db.is_music_favorite("aaaaaaaaaaa"))
        self.assertEqual(self.db.music_favorite_count(), 1)

    def test_keeping_a_song_that_was_played_marks_the_same_row(self) -> None:
        self.db.remember_played("aaaaaaaaaaa", "A song", "An artist", None)
        self.db.set_music_favorite("aaaaaaaaaaa", True)
        self.assertEqual(self.db.music_history_count(), 1)
        self.assertEqual(self.db.music_favorites()[0]["title"], "A song")

    def test_an_empty_title_never_overwrites_a_known_one(self) -> None:
        """Keeping a song from the player passes what the player has, and that
        can be less than what is already stored."""
        self.db.remember_played("aaaaaaaaaaa", "A song", "An artist", None)
        self.db.set_music_favorite("aaaaaaaaaaa", True)
        self.assertEqual(self.db.music_favorites()[0]["title"], "A song")

    def test_giving_one_back(self) -> None:
        self.db.set_music_favorite("aaaaaaaaaaa", True, "A song", None, None)
        self.db.set_music_favorite("aaaaaaaaaaa", False)
        self.assertFalse(self.db.is_music_favorite("aaaaaaaaaaa"))
        self.assertEqual(self.db.music_favorites(), [])

    def test_the_service_snapshot_cannot_carry_a_kept_song_away(self) -> None:
        """Reading the listening history again replaces what the service said,
        and a song kept out of that list must survive it."""
        self.db.replace_service_music_history(
            [{"ext_id": "bbbbbbbbbbb", "title": "Older", "artist": "Someone"}])
        self.db.set_music_favorite("bbbbbbbbbbb", True)
        self.db.replace_service_music_history(
            [{"ext_id": "ccccccccccc", "title": "Newer", "artist": "Someone"}])
        self.assertTrue(self.db.is_music_favorite("bbbbbbbbbbb"))

    def test_the_newest_kept_song_comes_first(self) -> None:
        for ext_id in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
            self.db.set_music_favorite(ext_id, True, "A song", None, None)
        self.db.conn.execute(
            "UPDATE music_history SET favorite_at = 1 WHERE ext_id = 'aaaaaaaaaaa'")
        self.db.conn.commit()
        self.assertEqual([row["ext_id"] for row in self.db.music_favorites()],
                         ["bbbbbbbbbbb", "aaaaaaaaaaa"])


class TheBridgeMarksThem(unittest.TestCase):
    def bridge(self):
        from weave.ui.bridge import Bridge

        db = Database(Path(tempfile.mkdtemp()) / "weave.db")

        class Quiet:
            def emit(self, *_a):
                pass

        bridge = Bridge.__new__(Bridge)
        bridge._db = db
        bridge._audio = None
        bridge._shelves = [{"title": "A section", "kind": "songs", "items": [
            {"title": "A song", "subtitle": "An artist", "thumbnail": "",
             "videoId": "aaaaaaaaaaa", "playlistId": "RDAMVMaaa"},
            {"title": "A list", "subtitle": "", "thumbnail": "",
             "videoId": "", "playlistId": "PL1"}]}]
        bridge._set_notice = lambda *a, **k: bridge.notices.append(a[0])
        bridge._set_status = lambda *a, **k: None
        bridge.notices = []
        bridge.favoritesChanged = Quiet()
        bridge.musicChanged = Quiet()
        return bridge

    def test_a_tile_keeps_the_song_it_was_opened_on(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        bridge._get_shelves = lambda: bridge._shelves
        Bridge.favoriteShelfItem(bridge, 0, 0)
        self.assertTrue(bridge._db.is_music_favorite("aaaaaaaaaaa"))
        self.assertEqual(bridge.notices, ["Added to favorites"])

    def test_pressing_it_again_gives_the_song_back(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        bridge._get_shelves = lambda: bridge._shelves
        Bridge.favoriteShelfItem(bridge, 0, 0)
        Bridge.favoriteShelfItem(bridge, 0, 0)
        self.assertFalse(bridge._db.is_music_favorite("aaaaaaaaaaa"))
        self.assertEqual(bridge.notices[-1], "Removed from favorites")

    def test_a_whole_list_is_not_a_song(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        bridge._get_shelves = lambda: bridge._shelves
        Bridge.favoriteShelfItem(bridge, 0, 1)
        self.assertEqual(bridge._db.music_favorite_count(), 0)
        self.assertIn("Only a song", bridge.notices[-1])

    def test_a_tile_that_is_not_there_is_no_error(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        bridge._get_shelves = lambda: bridge._shelves
        Bridge.favoriteShelfItem(bridge, 9, 9)
        self.assertEqual(bridge._db.music_favorite_count(), 0)

    def test_a_card_keeps_what_the_row_says(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()

        class Model:
            def row_for_key(self, key):
                return {"key": key, "title": "A video", "channelTitle": "Someone",
                        "thumbnail": "https://x/t.jpg"}

        bridge._model = Model()
        Bridge.favoriteVideo(bridge, "yt:aaaaaaaaaaa")
        row = bridge._db.music_favorites()[0]
        self.assertEqual(row["title"], "A video")
        self.assertEqual(row["channel_title"], "Someone")

    def test_a_twitch_row_is_not_a_song(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()

        class Model:
            def row_for_key(self, key):
                return {"key": key, "title": "A stream", "channelTitle": "Someone",
                        "thumbnail": ""}

        bridge._model = Model()
        Bridge.favoriteVideo(bridge, "twitch:someone")
        self.assertEqual(bridge._db.music_favorite_count(), 0)


if __name__ == "__main__":
    unittest.main()
