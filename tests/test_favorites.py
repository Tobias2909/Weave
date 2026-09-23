"""Songs kept on purpose.

A favourite is one of the songs already known, so it is a mark on that row
rather than a copy of it in a second table. Copying is how the two of them
come apart when a title or a picture changes on one side only.
"""

import unittest
from unittest import mock

from tests.support import scratch_db

MAKER = "UC" + "m" * 22
OTHER = "UC" + "o" * 22


class KeepingASong(unittest.TestCase):
    def setUp(self) -> None:
        self.db = scratch_db(self)

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

    def test_who_made_it_is_kept_with_it(self) -> None:
        self.db.set_music_favorite("aaaaaaaaaaa", True, "A song", "An artist", None,
                                   artist_id=MAKER)
        self.assertEqual(self.db.music_favorites()[0]["artist_id"], MAKER)

    def test_a_maker_the_music_service_named_is_not_replaced_by_a_card(self) -> None:
        """The music service says who made a song more exactly than the
        channel a video happens to be on."""
        self.db.remember_played("aaaaaaaaaaa", "A song", "An artist", None, artist_id=MAKER)
        self.db.set_music_favorite("aaaaaaaaaaa", True, artist_id=OTHER)
        self.assertEqual(self.db.music_favorites()[0]["artist_id"], MAKER)

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


class TheMakersOfOldFavourites(unittest.TestCase):
    """Favourites kept before who made them was kept with them.

    What is stored already names most of them for nothing, and only the rest
    are asked of the music service.
    """

    def setUp(self) -> None:
        self.db = scratch_db(self)

    def keep(self, ext_id: str) -> None:
        self.db.set_music_favorite(ext_id, True, "A song", "An artist", None)

    def test_a_video_weave_follows_names_its_channel(self) -> None:
        self.db.conn.execute(
            "INSERT INTO channels(key, platform, ext_id, title, added_at) "
            "VALUES(?, 'youtube', ?, 'Somebody', 1)", ("yt:" + MAKER, MAKER))
        self.db.conn.execute(
            "INSERT INTO videos(key, platform, ext_id, channel_key, title, first_seen_at) "
            "VALUES('yt:aaaaaaaaaaa', 'youtube', 'aaaaaaaaaaa', ?, 'A song', 1)",
            ("yt:" + MAKER,))
        self.db.conn.commit()
        self.keep("aaaaaaaaaaa")
        self.assertEqual(self.db.fill_favourite_makers(), 1)
        self.assertEqual(self.db.music_favorites()[0]["artist_id"], MAKER)

    def test_so_do_a_playlist_a_listing_and_the_owner_lookup(self) -> None:
        for table, ext_id in (("playlist_items", "bbbbbbbbbbb"),
                              ("cached_videos", "ccccccccccc"),
                              ("video_owners", "ddddddddddd")):
            if table == "playlist_items":
                self.db.conn.execute(
                    "INSERT OR IGNORE INTO playlists(ext_id, title, position, seen_at) "
                    "VALUES('PL1', 'A list', 0, 1)")
                self.db.conn.execute(
                    "INSERT INTO playlist_items(playlist_id, ext_id, title, channel_ext_id, "
                    "position) VALUES('PL1', ?, 't', ?, 0)", (ext_id, MAKER))
            elif table == "cached_videos":
                self.db.conn.execute(
                    "INSERT INTO cached_videos(kind, ext_id, title, channel_ext_id, position, "
                    "seen_at) VALUES('recommended', ?, 't', ?, 0, 1)", (ext_id, MAKER))
            else:
                self.db.conn.execute(
                    "INSERT INTO video_owners(ext_id, channel_name, channel_ext_id, seen_at) "
                    "VALUES(?, 'Somebody', ?, 1)", (ext_id, MAKER))
            self.keep(ext_id)
        self.db.conn.commit()
        self.assertEqual(self.db.fill_favourite_makers(), 3)
        self.assertEqual({row["artist_id"] for row in self.db.music_favorites()}, {MAKER})

    def test_one_already_named_is_left_alone(self) -> None:
        self.db.set_music_favorite("aaaaaaaaaaa", True, "A song", None, None,
                                   artist_id=OTHER)
        self.db.conn.execute(
            "INSERT INTO cached_videos(kind, ext_id, title, channel_ext_id, position, "
            "seen_at) VALUES('recommended', 'aaaaaaaaaaa', 't', ?, 0, 1)", (MAKER,))
        self.db.conn.commit()
        self.assertEqual(self.db.fill_favourite_makers(), 0)
        self.assertEqual(self.db.music_favorites()[0]["artist_id"], OTHER)

    def test_what_nothing_names_is_what_is_asked_about(self) -> None:
        self.keep("aaaaaaaaaaa")
        self.keep("bbbbbbbbbbb")
        self.assertEqual(sorted(self.db.favourites_without_maker()),
                         ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        # Asked, and nobody made it as far as the service knows. That is kept
        # so it is not asked again on every launch.
        self.db.set_favourite_maker("aaaaaaaaaaa", "")
        self.assertEqual(self.db.favourites_without_maker(), ["bbbbbbbbbbb"])

    def test_the_lookup_names_what_is_left_and_keeps_every_answer(self) -> None:
        from weave.config import Config
        from weave.poller import FavouriteMakers
        from weave.sources import ytmusic

        self.keep("aaaaaaaaaaa")
        self.keep("bbbbbbbbbbb")
        answers = {"aaaaaaaaaaa": [{"name": "Somebody", "id": MAKER}],
                   "bbbbbbbbbbb": []}
        named = []
        worker = FavouriteMakers(self.db, Config(raw={}))
        worker.ready.connect(named.append)
        with mock.patch.object(ytmusic, "artist_of",
                               lambda _profile, ext_id: answers[ext_id]), \
                mock.patch("weave.poller.cookie_profile", lambda _cfg: None):
            worker.work()
        self.assertEqual(named, [1])
        kept = {row["ext_id"]: row["artist_id"] for row in self.db.music_favorites()}
        self.assertEqual(kept, {"aaaaaaaaaaa": MAKER, "bbbbbbbbbbb": ""})
        self.assertEqual(self.db.favourites_without_maker(), [])

    def test_a_service_that_will_not_answer_leaves_them_to_ask_again(self) -> None:
        from weave.config import Config
        from weave.poller import FavouriteMakers
        from weave.sources import ytmusic

        self.keep("aaaaaaaaaaa")

        def refuse(_profile, _ext_id):
            raise ytmusic.MusicError("offline")

        worker = FavouriteMakers(self.db, Config(raw={}))
        with mock.patch.object(ytmusic, "artist_of", refuse), \
                mock.patch("weave.poller.cookie_profile", lambda _cfg: None):
            worker.work()
        self.assertEqual(self.db.favourites_without_maker(), ["aaaaaaaaaaa"])


class TheBridgeMarksThem(unittest.TestCase):
    def bridge(self):
        from weave.ui.bridge import Bridge

        db = scratch_db(self)

        class Quiet:
            def emit(self, *_a):
                pass

        bridge = Bridge.__new__(Bridge)
        bridge._name_favourite_makers = lambda: None
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
        bridge.asked_makers = []
        bridge._name_favourite_makers = lambda: bridge.asked_makers.append(True)
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

    def test_a_card_keeps_the_channel_its_video_is_on(self) -> None:
        """Without it the name under the favourite led nowhere, and pressing
        it did nothing at all."""
        from weave.ui.bridge import Bridge

        bridge = self.bridge()

        class Model:
            def row_for_key(self, key):
                return {"key": key, "title": "A video", "channelTitle": "Someone",
                        "channelKey": "yt:" + MAKER, "thumbnail": ""}

        bridge._model = Model()
        Bridge.favoriteVideo(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge._db.music_favorites()[0]["artist_id"], MAKER)
        self.assertEqual(bridge.asked_makers, [], "a card that says asked anyway")

    def test_a_card_that_names_no_channel_asks_who_made_it(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()

        class Model:
            def row_for_key(self, key):
                return {"key": key, "title": "A song", "channelTitle": "Someone",
                        "channelKey": "", "thumbnail": ""}

        bridge._model = Model()
        Bridge.favoriteVideo(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.asked_makers, [True])

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
        bridge._name_favourite_makers = lambda: None
        bridge._audio = None
        bridge._db = scratch_db(self)
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
                # The page beside the song reads which song it is about, to
                # tell a new one from a song merely added to the queue.
                self.track = {"key": "yt:a", "url": ""}
                # The window listens to this now. A player that cannot fail
                # is not one the bridge will take.
                self.failed = Wire()
                # Nor one that cannot report a song that has gone from
                # YouTube, which is its own report and not a failure.
                self.gone = Wire()
                # Nor one that cannot say what its resolve learned.
                self.factsChanged = Wire()
                # Whether anything is open to show a picture, which is what
                # decides whether a song's video is worth keeping on disk,
                # and the report that says it has changed. Opening the page
                # during a song is a moment to keep its picture, so the
                # window listens to this too.
                self.videoWanted = False
                self.videoChanged = Wire()
                self.trackFacts = {}

            def pause_for_video(self):
                pass

        class Video:
            def __init__(self):
                self.nowPlaying = Wire()

        bridge = Bridge.__new__(Bridge)
        bridge._name_favourite_makers = lambda: None
        bridge._audio = None
        bridge._player = Video()
        # A track change now also empties what sits beside the song on the Now
        # playing page, and asks whether that page has outlived the music it is
        # about, so the state both of those read has to be here.
        bridge._view_kind = "all"
        bridge._now_side = None
        bridge._now_detail = None
        bridge._now_words = {}
        bridge._now_related = []
        bridge._now_comments = []
        bridge._now_threads = 5
        bridge._now_busy = ""
        bridge._now_song = ""
        bridge.nowChanged = type("S", (), {"emit": lambda self, *a: None})()
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

        db = scratch_db(self)

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
        bridge._name_favourite_makers = lambda: None
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
        self.db = scratch_db(self)

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
        bridge._name_favourite_makers = lambda: None
        bridge._audio = None
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
