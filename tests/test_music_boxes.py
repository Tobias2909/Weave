"""Boxes of songs, the music page's shelves put out of sight, and which songs
are written to disk.

A box is Weave's own: made, filled and thrown away without a request. The
favourites are the first box and cannot be thrown away, and whether a song
is kept on disk now follows the boxes it is in rather than the favourites
alone.
"""

import json
import unittest

from weave.ui.bridge import FAVORITES, FAVORITES_BOX, Bridge

from .support import scratch_db


def song(ext_id, title="A song"):
    return {"ext_id": ext_id, "title": title, "artist": "Someone", "artist_id": None,
            "thumbnail_url": None, "duration_s": 200}


class TheBoxes(unittest.TestCase):
    def setUp(self):
        self.db = scratch_db(self)

    def test_a_name_is_needed_and_used_once(self):
        self.assertIsNone(self.db.create_music_box("  "))
        first = self.db.create_music_box("Road trip")
        self.assertIsNotNone(first)
        self.assertIsNone(self.db.create_music_box("Road trip"))

    def test_they_keep_the_order_they_were_made_in_until_moved(self):
        a = self.db.create_music_box("A")
        b = self.db.create_music_box("B")
        c = self.db.create_music_box("C")
        self.assertEqual([row["id"] for row in self.db.music_boxes()], [a, b, c])
        self.assertTrue(self.db.move_music_box_to(c, a))
        self.assertEqual([row["name"] for row in self.db.music_boxes()], ["C", "A", "B"])

    def test_songs_go_on_the_end_once_each(self):
        box = self.db.create_music_box("Mix")
        self.assertTrue(self.db.put_in_music_box(box, song("aaaaaaaaaaa", "One")))
        self.assertTrue(self.db.put_in_music_box(box, song("bbbbbbbbbbb", "Two")))
        self.assertFalse(self.db.put_in_music_box(box, song("aaaaaaaaaaa", "One")))
        self.assertEqual([row["title"] for row in self.db.music_box_songs(box)], ["One", "Two"])
        self.assertEqual(self.db.music_boxes()[0]["count"], 2)

    def test_taking_one_out_and_throwing_the_box_away(self):
        box = self.db.create_music_box("Mix")
        self.db.put_in_music_box(box, song("aaaaaaaaaaa"))
        self.assertEqual(self.db.music_boxes_holding("aaaaaaaaaaa"), [box])
        self.assertTrue(self.db.remove_from_music_box(box, "aaaaaaaaaaa"))
        self.assertEqual(self.db.music_box_songs(box), [])
        self.db.put_in_music_box(box, song("aaaaaaaaaaa"))
        self.assertTrue(self.db.delete_music_box(box))
        self.assertEqual(self.db.music_boxes(), [])
        self.assertEqual(self.db.music_boxes_holding("aaaaaaaaaaa"), [])

    def test_a_rename_cannot_take_a_name_in_use(self):
        a = self.db.create_music_box("A")
        self.db.create_music_box("B")
        self.assertFalse(self.db.rename_music_box(a, "B"))
        self.assertTrue(self.db.rename_music_box(a, "Evening"))
        self.assertEqual(self.db.music_box(a)["name"], "Evening")

    def test_kept_on_disk_is_every_song_in_a_box_marked_for_it(self):
        kept = self.db.create_music_box("Kept")
        loose = self.db.create_music_box("Loose")
        self.db.put_in_music_box(kept, song("aaaaaaaaaaa"))
        self.db.put_in_music_box(loose, song("bbbbbbbbbbb"))
        self.db.set_music_box_keep(kept, True)
        self.db.set_music_favorite("ccccccccccc", True, "A favourite", None, None)
        self.assertEqual(self.db.kept_music_ids(True), {"aaaaaaaaaaa", "ccccccccccc"})
        self.assertEqual(self.db.kept_music_ids(False), {"aaaaaaaaaaa"})


class Quiet:
    def emit(self, *_a):
        pass


class FakeAudio:
    def __init__(self, entries=(), playing=None):
        self.entries = list(entries)
        self.track = playing or {}

    def queue_entries(self):
        return list(self.entries)


def make_bridge(test, shelves=None, audio=None):
    bridge = Bridge.__new__(Bridge)
    bridge._db = scratch_db(test)
    bridge._audio = audio
    bridge._music_list = None
    bridge._view_kind = "music"
    bridge._shelves = shelves or []
    bridge._favorites_order = []
    bridge._results = []
    bridge.notices = []
    bridge._set_notice = lambda *a, **k: bridge.notices.append(a[0])
    bridge._set_status = lambda *a, **k: None
    bridge._name_favourite_makers = lambda: None
    bridge._prune_kept = lambda: None
    bridge._keep_this_song = lambda: None
    bridge._music_tab = -1
    bridge.queued = []
    bridge._queue_track = lambda track, play_next: bridge.queued.append((track, play_next))
    for name in ("favoritesChanged", "musicBoxesChanged", "musicChanged", "videosKeptChanged",
                 "musicTabChanged"):
        setattr(bridge, name, Quiet())
    return bridge


SHELVES = [
    {"title": "Quick picks", "kind": "songs", "items": [
        {"title": "A song", "subtitle": "An artist", "thumbnail": "", "videoId": "aaaaaaaaaaa",
         "playlistId": "", "artistId": ""},
        {"title": "A list", "subtitle": "", "thumbnail": "", "videoId": "", "playlistId": "PL1"}]},
    {"title": "Listen again", "kind": "songs", "items": []},
    {"title": "Recaps", "kind": "songs", "items": []},
]


class TheBridge(unittest.TestCase):
    def test_the_favourites_come_first_and_cannot_be_thrown_away(self):
        bridge = make_bridge(self)
        made = Bridge.createMusicBox(bridge, "Road trip")
        boxes = Bridge._get_music_boxes(bridge)
        self.assertEqual([(b["id"], b["name"], b["fixed"]) for b in boxes],
                         [(FAVORITES_BOX, FAVORITES, True), (made, "Road trip", False)])
        Bridge.deleteMusicBox(bridge, FAVORITES_BOX)
        self.assertFalse(Bridge.renameMusicBox(bridge, FAVORITES_BOX, "Other"))
        self.assertEqual(len(Bridge._get_music_boxes(bridge)), 2)

    def test_a_tile_goes_in_a_box_and_out_again(self):
        bridge = make_bridge(self, SHELVES)
        box = Bridge.createMusicBox(bridge, "Mix")
        Bridge.putSongInBox(bridge, "shelf", 0, 0, box)
        self.assertEqual(Bridge.songBoxes(bridge, "shelf", 0, 0), [box])
        self.assertEqual(bridge.notices[-1], "Put in Mix")
        Bridge.putSongInBox(bridge, "shelf", 0, 0, box)
        self.assertEqual(Bridge.songBoxes(bridge, "shelf", 0, 0), [])
        self.assertEqual(bridge.notices[-1], "Taken out of Mix")

    def test_the_favourites_box_is_the_favourites(self):
        bridge = make_bridge(self, SHELVES)
        Bridge.putSongInBox(bridge, "shelf", 0, 0, FAVORITES_BOX)
        self.assertTrue(bridge._db.is_music_favorite("aaaaaaaaaaa"))
        self.assertEqual(Bridge.songBoxes(bridge, "shelf", 0, 0), [FAVORITES_BOX])

    def test_a_whole_list_is_not_a_song(self):
        bridge = make_bridge(self, SHELVES)
        box = Bridge.createMusicBox(bridge, "Mix")
        Bridge.putSongInBox(bridge, "shelf", 0, 1, box)
        self.assertEqual(bridge._db.music_box_songs(box), [])
        self.assertIn("Only a song", bridge.notices[-1])

    def test_the_queue_is_kept_in_the_order_it_plays(self):
        queue = [{"key": "yt:bbbbbbbbbbb", "title": "Two", "artist": "B", "thumbnail": ""},
                 {"key": "source:3", "title": "A stream", "artist": "", "thumbnail": ""},
                 {"key": "yt:aaaaaaaaaaa", "title": "One", "artist": "A", "thumbnail": ""}]
        bridge = make_bridge(self, audio=FakeAudio(queue))
        made = Bridge.saveQueueAsBox(bridge, "Tonight")
        self.assertGreaterEqual(made, 0)
        self.assertEqual([row["title"] for row in bridge._db.music_box_songs(made)],
                         ["Two", "One"])

    def test_an_empty_queue_makes_no_box(self):
        bridge = make_bridge(self, audio=FakeAudio([]))
        self.assertEqual(Bridge.saveQueueAsBox(bridge, "Nothing"), -1)
        self.assertEqual(bridge._db.music_boxes(), [])

    def test_an_open_box_is_its_songs_as_a_list(self):
        bridge = make_bridge(self)
        box = Bridge.createMusicBox(bridge, "Mix")
        bridge._db.put_in_music_box(box, song("aaaaaaaaaaa", "One"))
        rows = Bridge._box_rows(bridge, box)
        self.assertEqual([(r["key"], r["title"], r["duration"]) for r in rows],
                         [("yt:aaaaaaaaaaa", "One", "3:20")])

    def test_kept_on_disk_follows_the_boxes_and_the_favourites_switch(self):
        bridge = make_bridge(self, SHELVES)
        Bridge.putSongInBox(bridge, "shelf", 0, 0, FAVORITES_BOX)
        self.assertTrue(Bridge._is_kept_song(bridge, "aaaaaaaaaaa"), "favourites are kept by default")
        Bridge.setMusicBoxKeep(bridge, FAVORITES_BOX, False)
        self.assertFalse(Bridge._is_kept_song(bridge, "aaaaaaaaaaa"))
        box = Bridge.createMusicBox(bridge, "Mix")
        Bridge.putSongInBox(bridge, "shelf", 0, 0, box)
        self.assertFalse(Bridge._is_kept_song(bridge, "aaaaaaaaaaa"), "a new box is not kept")
        Bridge.setMusicBoxKeep(bridge, box, True)
        self.assertTrue(Bridge._is_kept_song(bridge, "aaaaaaaaaaa"))


class TheTabs(unittest.TestCase):
    def test_the_page_opens_on_the_shelves_and_a_box_is_a_tab(self):
        bridge = make_bridge(self)
        box = Bridge.createMusicBox(bridge, "Mix")
        bridge._db.put_in_music_box(box, song("aaaaaaaaaaa", "One"))
        self.assertEqual(Bridge._get_music_tab(bridge), -1)
        self.assertEqual(Bridge._get_music_tab_songs(bridge), [])
        Bridge.showMusicTab(bridge, box)
        tiles = Bridge._get_music_tab_songs(bridge)
        self.assertEqual([(t["title"], t["subtitle"], t["videoId"]) for t in tiles],
                         [("One", "Someone", "aaaaaaaaaaa")])

    def test_a_box_that_is_not_there_is_the_shelves(self):
        bridge = make_bridge(self)
        Bridge.showMusicTab(bridge, 99)
        self.assertEqual(Bridge._get_music_tab(bridge), -1)

    def test_the_favourites_tab_is_the_favourites(self):
        bridge = make_bridge(self, SHELVES)
        Bridge.putSongInBox(bridge, "shelf", 0, 0, FAVORITES_BOX)
        Bridge.showMusicTab(bridge, FAVORITES_BOX)
        self.assertEqual([t["videoId"] for t in Bridge._get_music_tab_songs(bridge)],
                         ["aaaaaaaaaaa"])
        Bridge.takeOutOfMusicTab(bridge, 0)
        self.assertFalse(bridge._db.is_music_favorite("aaaaaaaaaaa"))

    def test_a_tile_is_taken_out_queued_and_filed_from_its_tab(self):
        bridge = make_bridge(self)
        box = Bridge.createMusicBox(bridge, "Mix")
        other = Bridge.createMusicBox(bridge, "Other")
        bridge._db.put_in_music_box(box, song("aaaaaaaaaaa", "One"))
        bridge._db.put_in_music_box(box, song("bbbbbbbbbbb", "Two"))
        Bridge.showMusicTab(bridge, box)
        Bridge.queueSong(bridge, "tab", 1, -1, True)
        self.assertEqual(bridge.queued[0][0]["key"], "yt:bbbbbbbbbbb")
        self.assertTrue(bridge.queued[0][1])
        Bridge.putSongInBox(bridge, "tab", 0, -1, other)
        self.assertEqual(bridge._db.music_boxes_holding("aaaaaaaaaaa"), [box, other])
        Bridge.takeOutOfMusicTab(bridge, 0)
        self.assertEqual([t["title"] for t in Bridge._get_music_tab_songs(bridge)], ["Two"])

    def test_throwing_away_the_box_on_show_goes_back_to_the_shelves(self):
        bridge = make_bridge(self)
        box = Bridge.createMusicBox(bridge, "Mix")
        Bridge.showMusicTab(bridge, box)
        Bridge.deleteMusicBox(bridge, box)
        self.assertEqual(Bridge._get_music_tab(bridge), -1)


class WatchedInMpv(unittest.TestCase):
    def test_a_box_tile_hands_over_the_whole_box_around_it(self):
        bridge = make_bridge(self)
        box = Bridge.createMusicBox(bridge, "Mix")
        for ext_id in ("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"):
            bridge._db.put_in_music_box(box, song(ext_id))
        handed = []
        bridge._hand_over = lambda key, url, title, login, live: handed.append((key, url))
        Bridge.showMusicTab(bridge, box)
        Bridge.watchSong(bridge, "tab", 2, -1)
        self.assertEqual(handed, [("yt:ccccccccccc", "https://www.youtube.com/watch?v=ccccccccccc")])
        key, after, _at, before = bridge._queue_on_start
        self.assertEqual(key, "yt:ccccccccccc")
        self.assertEqual([u.rsplit("=", 1)[1] for u in before], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        self.assertEqual([u.rsplit("=", 1)[1] for u in after], ["ddddddddddd"])

    def test_a_song_from_anywhere_else_goes_alone(self):
        bridge = make_bridge(self, SHELVES)
        handed = []
        bridge._hand_over = lambda key, url, title, login, live: handed.append(key)
        Bridge.watchSong(bridge, "shelf", 0, 0)
        self.assertEqual(handed, ["yt:aaaaaaaaaaa"])
        self.assertIsNone(bridge._queue_on_start)


class TheShelves(unittest.TestCase):
    def test_a_hidden_shelf_leaves_the_page_but_not_the_settings(self):
        bridge = make_bridge(self, SHELVES)
        Bridge.setShelfHidden(bridge, "Listen again", True)
        self.assertEqual([s["title"] for s in Bridge._get_shelves(bridge)],
                         ["Quick picks", "Recaps"])
        settings = Bridge._get_shelf_settings(bridge)
        self.assertEqual([(s["title"], s["hidden"]) for s in settings],
                         [("Quick picks", False), ("Listen again", True), ("Recaps", False)])

    def test_moving_one_keeps_the_hidden_ones_in_their_place(self):
        bridge = make_bridge(self, SHELVES)
        Bridge.setShelfHidden(bridge, "Listen again", True)
        Bridge.moveShelfTo(bridge, "Recaps", "Quick picks")
        self.assertEqual(json.loads(bridge._db.get_state("music_shelf_order")),
                         ["Recaps", "Quick picks", "Listen again"])
        Bridge.setShelfHidden(bridge, "Listen again", False)
        self.assertEqual([s["title"] for s in Bridge._get_shelves(bridge)],
                         ["Recaps", "Quick picks", "Listen again"])


if __name__ == "__main__":
    unittest.main()
