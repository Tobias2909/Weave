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
        bridge._music_list = None
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


class FromAnOpenedList(unittest.TestCase):
    """A playlist or a station opened in music draws its songs as rows rather
    than tiles, and a song is a song wherever it is drawn."""

    def bridge(self, rows):
        from weave.ui.bridge import Bridge

        class Quiet:
            def emit(self, *_a):
                pass

        bridge = Bridge.__new__(Bridge)
        bridge._db = Database(Path(tempfile.mkdtemp()) / "weave.db")
        bridge._results = rows
        bridge._music_list = None
        bridge.notices = []
        bridge._set_notice = lambda *a, **k: bridge.notices.append(a[0])
        bridge._set_status = lambda *a, **k: None
        bridge.favoritesChanged = Quiet()
        bridge.musicChanged = Quiet()
        return bridge

    def rows(self):
        return [{"key": "yt:aaaaaaaaaaa", "videoId": "aaaaaaaaaaa",
                 "title": "A song", "artist": "An artist",
                 "thumbnail": "https://example/a.jpg"}]

    def test_a_row_can_be_kept(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(self.rows())
        Bridge.favoriteResult(bridge, 0)
        kept = bridge._db.music_favorites()[0]
        self.assertEqual(kept["title"], "A song")
        self.assertEqual(kept["channel_title"], "An artist")
        self.assertEqual(kept["thumbnail_url"], "https://example/a.jpg")
        self.assertEqual(bridge.notices, ["Added to favorites"])

    def test_the_menu_knows_whether_it_is_kept(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(self.rows())
        self.assertFalse(Bridge.resultIsFavorite(bridge, 0))
        Bridge.favoriteResult(bridge, 0)
        self.assertTrue(Bridge.resultIsFavorite(bridge, 0))

    def test_pressing_it_again_gives_the_song_back(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(self.rows())
        Bridge.favoriteResult(bridge, 0)
        Bridge.favoriteResult(bridge, 0)
        self.assertEqual(bridge._db.music_favorite_count(), 0)

    def test_a_row_that_is_not_there_is_no_error(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(self.rows())
        Bridge.favoriteResult(bridge, 99)
        self.assertFalse(Bridge.resultIsFavorite(bridge, 99))
        self.assertEqual(bridge._db.music_favorite_count(), 0)


class TheHeartFollowsTheSong(unittest.TestCase):
    """Whether the heart is lit depends on two things, and both must say so.

    It is a binding on which songs are kept, so a new song playing had to
    announce itself as well. Without that the heart kept whatever it had read
    for the song before, which showed as the first song of a session never
    lighting up while every one after it did.
    """

    def test_a_new_song_announces_itself_to_the_heart(self) -> None:
        from weave.ui.bridge import Bridge

        class Wire:
            def __init__(self):
                self.slots = []

            def connect(self, slot):
                self.slots.append(slot)

            def emit(self, *a):
                for slot in self.slots:
                    slot(*a)

        class Player:
            def __init__(self):
                self.trackChanged = Wire()

            def pause_for_video(self):
                pass

        class Video:
            def __init__(self):
                self.nowPlaying = Wire()

        bridge = Bridge.__new__(Bridge)
        bridge._player = Video()
        told = []
        bridge.favoritesChanged = type("S", (), {"emit": lambda self, *a: told.append(True)})()
        audio = Player()
        Bridge.attach_audio(bridge, audio)
        self.assertEqual(told, [], "nothing has played yet")
        audio.trackChanged.emit()
        self.assertEqual(told, [True], "the heart was not told a song started")


if __name__ == "__main__":
    unittest.main()


class WithNothingKept(unittest.TestCase):
    """Every path has to cope with an empty list, which is what everybody has
    until they keep their first song."""

    def bridge(self):
        from weave.ui.bridge import Bridge

        db = Database(Path(tempfile.mkdtemp()) / "weave.db")

        class Quiet:
            def emit(self, *_a):
                pass

        class Audio:
            def __init__(self):
                self.queues = []
                self.track = {}

            def play_items(self, items, start=0):
                self.queues.append(list(items))

        bridge = Bridge.__new__(Bridge)
        bridge._db = db
        bridge._audio = Audio()
        bridge._shelves = []
        bridge._favorites_order = []
        bridge._view_kind = "music"
        bridge._music_list = None
        bridge._set_notice = lambda *a, **k: None
        bridge._set_status = lambda *a, **k: None
        bridge.favoritesChanged = Quiet()
        bridge.musicChanged = Quiet()
        return bridge

    def test_there_is_no_section_until_a_song_is_kept(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        bridge._db.set_state = lambda *a, **k: None
        bridge._db.sources = lambda: []
        self.assertEqual(Bridge._favorites_shelf(bridge)["items"], [])
        titles = [shelf["title"] for shelf in Bridge._get_shelves(bridge)]
        self.assertNotIn("Favorites", titles)

    def test_the_section_appears_once_one_is_kept(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        bridge._db.set_state = lambda *a, **k: None
        bridge._db.sources = lambda: []
        bridge._db.set_music_favorite("aaaaaaaaaaa", True, "A song", "An artist", None)
        titles = [shelf["title"] for shelf in Bridge._get_shelves(bridge)]
        self.assertEqual(titles, ["Favorites"])

    def test_pressing_play_with_nothing_kept_does_nothing(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge._play_favorites(bridge, "aaaaaaaaaaa")
        self.assertEqual(bridge._audio.queues, [])

    def test_the_heart_is_dark_when_nothing_is_playing(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        self.assertFalse(Bridge._get_playing_favorite(bridge))

    def test_giving_back_the_last_one_leaves_its_page(self) -> None:
        from weave.ui.bridge import Bridge
        from weave.ui.navigation import MusicList

        bridge = self.bridge()
        bridge._db.set_music_favorite("aaaaaaaaaaa", True, "A song", None, None)
        bridge._music_list = MusicList("shelf", "Favorites", "Favorites")
        bridge.left = []
        bridge._set_view = lambda *a, **k: bridge.left.append(a)

        class Model:
            def row_for_key(self, key):
                return {"key": key, "title": "A song", "channelTitle": None,
                        "thumbnail": None}

        bridge._model = Model()
        Bridge.favoriteVideo(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge._db.music_favorite_count(), 0)
        self.assertEqual(bridge.left, [("music", -1, "", "", None)])

    def test_keeping_a_song_does_not_leave_the_page(self) -> None:
        from weave.ui.bridge import Bridge
        from weave.ui.navigation import MusicList

        bridge = self.bridge()
        bridge._music_list = MusicList("shelf", "Favorites", "Favorites")
        bridge.left = []
        bridge._set_view = lambda *a, **k: bridge.left.append(a)

        class Model:
            def row_for_key(self, key):
                return {"key": key, "title": "A song", "channelTitle": None,
                        "thumbnail": None}

        bridge._model = Model()
        Bridge.favoriteVideo(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.left, [])


class ThePicture(unittest.TestCase):
    """Wrapping an address twice leaves nothing at all.

    Everything read back out of the window has already been wrapped for the
    picture cache, and the wrapper only accepts an address beginning with
    http, so wrapping it again returns an empty string. Whatever is stored is
    stored plain.
    """

    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "weave.db")

    def test_wrapping_a_wrapped_address_gives_nothing(self) -> None:
        from weave.imagecache import plain_source, qml_source

        wrapped = qml_source("https://example/a.jpg")
        self.assertEqual(qml_source(wrapped), "")
        self.assertEqual(plain_source(wrapped), "https://example/a.jpg")

    def test_a_plain_address_is_left_as_it_is(self) -> None:
        from weave.imagecache import plain_source

        self.assertEqual(plain_source("https://example/a.jpg"), "https://example/a.jpg")
        self.assertEqual(plain_source(""), "")
        self.assertEqual(plain_source(None), "")

    def test_what_the_window_hands_over_is_stored_plain(self) -> None:
        from weave.imagecache import qml_source
        from weave.ui.bridge import Bridge

        class Quiet:
            def emit(self, *_a):
                pass

        bridge = Bridge.__new__(Bridge)
        bridge._db = self.db
        bridge._music_list = None
        bridge._set_notice = lambda *a, **k: None
        bridge._set_status = lambda *a, **k: None
        bridge.favoritesChanged = Quiet()
        bridge.musicChanged = Quiet()
        Bridge._mark_favorite(bridge, "yt:aaaaaaaaaaa", "A song", "An artist",
                              qml_source("https://example/a.jpg"), keep=True)
        stored = self.db.music_favorites()[0]["thumbnail_url"]
        self.assertEqual(stored, "https://example/a.jpg")
        self.assertTrue(qml_source(stored).startswith("image://"))

    def test_a_song_played_here_stores_its_picture_plain(self) -> None:
        from weave.audio import AudioPlayer
        from weave.imagecache import qml_source

        player = AudioPlayer.__new__(AudioPlayer)
        player._db = self.db
        AudioPlayer._remember(player, {
            "key": "yt:bbbbbbbbbbb", "title": "A song", "artist": "An artist",
            "thumbnail": qml_source("https://example/b.jpg"), "live": False})
        row = self.db.music_history()[0]
        self.assertEqual(row["thumbnail_url"], "https://example/b.jpg")
