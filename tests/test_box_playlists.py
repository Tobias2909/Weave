"""A box of songs made into a playlist on the account, and a playlist copied
into a box. Either way the one it came from stays as it was.

Making a playlist is a write to the account, so it is only ever reached from a
press, and these tests never let it reach the network: the music client is
replaced by one that writes down what it was asked.
"""

import unittest
from unittest import mock

from PySide6.QtCore import QObject

from weave.config import Config
from weave.sources import ytmusic
from weave.ui.bridge import Bridge

from .test_music_boxes import make_bridge


class FakeClient:
    def __init__(self, made="PLmade", added="STATUS_SUCCEEDED"):
        self.made = made
        self.added = added
        self.calls = []

    def create_playlist(self, title, description, privacy_status="PRIVATE", video_ids=None):
        self.calls.append(("create", title, privacy_status, list(video_ids or [])))
        return self.made

    def add_playlist_items(self, playlist_id, video_ids):
        self.calls.append(("add", playlist_id, list(video_ids)))
        return {"status": self.added}


class MakingOne(unittest.TestCase):
    def make(self, client, ids, privacy="PRIVATE"):
        with mock.patch.object(ytmusic, "client", lambda _profile: client):
            return ytmusic.make_playlist(None, "Road trip", privacy, ids)

    def test_a_short_box_is_one_request_in_its_order(self):
        client = FakeClient()
        self.assertEqual(self.make(client, ["bbbbbbbbbbb", "aaaaaaaaaaa"]), "PLmade")
        self.assertEqual(client.calls,
                         [("create", "Road trip", "PRIVATE", ["bbbbbbbbbbb", "aaaaaaaaaaa"])])

    def test_a_long_one_goes_in_pieces_and_a_repeat_goes_in_once(self):
        ids = [f"song{index:07d}" for index in range(250)]
        client = FakeClient()
        self.make(client, ids + ids[:3])
        self.assertEqual([(call[0], len(call[-1])) for call in client.calls],
                         [("create", 100), ("add", 100), ("add", 50)])
        self.assertEqual(client.calls[2][2][-1], ids[-1])

    def test_a_refusal_is_said_in_words(self):
        with self.assertRaises(ytmusic.MusicError) as caught:
            self.make(FakeClient(made={"error": "no"}), ["aaaaaaaaaaa"])
        self.assertIn("did not make", str(caught.exception))
        ids = [f"song{index:07d}" for index in range(150)]
        with self.assertRaises(ytmusic.MusicError) as caught:
            self.make(FakeClient(added="STATUS_FAILED"), ids)
        self.assertIn("first 100 of 150", str(caught.exception))

    def test_only_the_three_ways_to_be_seen_and_never_an_empty_one(self):
        client = FakeClient()
        with self.assertRaises(ytmusic.MusicError):
            self.make(client, ["aaaaaaaaaaa"], privacy="FRIENDS")
        with self.assertRaises(ytmusic.MusicError):
            self.make(client, [])
        self.assertEqual(client.calls, [])


class Launched(list):
    def __call__(self, worker):
        self.append(worker)
        return True


def bridge_for(test):
    bridge = make_bridge(test)
    # A worker made here is parented to the bridge, which has to be a whole
    # QObject for that.
    QObject.__init__(bridge)
    bridge._cfg = Config(raw={})
    bridge._playlist_maker = None
    bridge._making_playlist = ""
    bridge._making_rows = []
    bridge._box_after_read = ""
    bridge._playlist_items = None
    bridge._launch = Launched()
    for name in ("playlistsChanged",):
        setattr(bridge, name, mock.Mock())
    return bridge


class BoxToPlaylist(unittest.TestCase):
    def test_the_new_playlist_comes_first_marked_as_music_with_its_songs(self):
        bridge = bridge_for(self)
        bridge._db.replace_playlists([{"ext_id": "PLold", "title": "Old one"}])
        box = Bridge.createMusicBox(bridge, "Road trip")
        for ext_id, title in (("bbbbbbbbbbb", "B"), ("aaaaaaaaaaa", "A")):
            bridge._db.put_in_music_box(box, {"ext_id": ext_id, "title": title,
                                              "artist": "Someone", "duration_s": 200})
        Bridge.makePlaylistFromBox(bridge, box, " Road trip ", "UNLISTED")
        worker = bridge._launch[0]
        self.assertEqual((worker._title, worker._privacy, worker._video_ids),
                         ("Road trip", "UNLISTED", ["bbbbbbbbbbb", "aaaaaaaaaaa"]))
        self.assertEqual(Bridge._get_making_playlist(bridge), "Road trip")
        Bridge._on_playlist_made(bridge, "PLnew", "Road trip", 2)
        mine = bridge._db.playlists()
        self.assertEqual([row["ext_id"] for row in mine], ["PLnew", "PLold"])
        self.assertTrue(mine[0]["is_music"])
        self.assertEqual([row["title"] for row in bridge._db.playlist_items("PLnew")],
                         ["B", "A"])
        self.assertEqual(Bridge._get_making_playlist(bridge), "")
        self.assertEqual(len(bridge._db.music_box_songs(box)), 2, "the box stays")

    def test_an_empty_box_or_no_name_asks_nothing(self):
        bridge = bridge_for(self)
        box = Bridge.createMusicBox(bridge, "Empty")
        Bridge.makePlaylistFromBox(bridge, box, "Empty", "PRIVATE")
        Bridge.makePlaylistFromBox(bridge, 0, "  ", "PRIVATE")
        self.assertEqual(bridge._launch, [])

    def test_a_failure_says_why_and_leaves_nothing_behind(self):
        bridge = bridge_for(self)
        bridge._making_playlist = "Road trip"
        Bridge._on_playlist_make_failed(bridge, "the music service answered 401")
        self.assertEqual(bridge._making_playlist, "")
        self.assertIn("401", bridge.notices[-1])
        self.assertEqual(bridge._db.playlists(), [])


class PlaylistToBox(unittest.TestCase):
    def stored(self, bridge, title="Trail nights"):
        bridge._db.replace_playlists([{"ext_id": "PL1", "title": title}])
        bridge._db.replace_playlist_items("PL1", [
            {"ext_id": "aaaaaaaaaaa", "title": "First", "channel_name": "Someone",
             "channel_ext_id": "UC" + "a" * 22, "duration_s": 200},
            {"ext_id": "bbbbbbbbbbb", "title": "[Deleted video]"},
            {"ext_id": "ccccccccccc", "title": "Second", "duration_s": 100},
        ])

    def test_a_stored_playlist_becomes_a_box_of_its_name_and_stays(self):
        bridge = bridge_for(self)
        self.stored(bridge)
        Bridge.boxFromPlaylist(bridge, "PL1")
        boxes = bridge._db.music_boxes()
        self.assertEqual([(box["name"], box["count"]) for box in boxes], [("Trail nights", 2)])
        songs = bridge._db.music_box_songs(boxes[0]["id"])
        self.assertEqual([(song["title"], song["artist"], song["artist_id"]) for song in songs],
                         [("First", "Someone", "UC" + "a" * 22), ("Second", None, None)])
        self.assertEqual(len(bridge._db.playlist_items("PL1")), 3, "the playlist stays")
        self.assertEqual(bridge._launch, [], "a stored playlist is not read again")

    def test_a_name_in_use_gets_a_number(self):
        bridge = bridge_for(self)
        self.stored(bridge)
        Bridge.createMusicBox(bridge, "Trail nights")
        Bridge.boxFromPlaylist(bridge, "PL1")
        Bridge.boxFromPlaylist(bridge, "PL1")
        self.assertEqual([box["name"] for box in bridge._db.music_boxes()],
                         ["Trail nights", "Trail nights 2", "Trail nights 3"])

    def test_a_playlist_never_read_is_read_first_then_copied(self):
        bridge = bridge_for(self)
        bridge._db.replace_playlists([{"ext_id": "PL1", "title": "Trail nights"}])
        bridge._stop_page_reading = lambda *_a: None
        bridge._view_kind = "music"
        Bridge.boxFromPlaylist(bridge, "PL1")
        self.assertEqual(type(bridge._launch[0]).__name__, "PlaylistItemsFetcher")
        self.assertEqual(bridge._db.music_boxes(), [])
        self.stored(bridge)
        Bridge._on_playlist_items(bridge, "PL1", 3)
        self.assertEqual([box["count"] for box in bridge._db.music_boxes()], [2])
        self.assertEqual(bridge._box_after_read, "")

    def test_the_chooser_lists_yours_then_the_kept_ones(self):
        bridge = bridge_for(self)
        db = bridge._db
        db.replace_playlists([{"ext_id": "PL1", "title": "Mine"}])
        db.open_channel_playlist("PL2", "Somebody else's")
        db.keep_playlist("PL2")
        found = Bridge.playlistsForBoxes(bridge)
        self.assertEqual([(row["id"], row["linked"], row["read"]) for row in found],
                         [("PL1", False, False), ("PL2", True, False)])


if __name__ == "__main__":
    unittest.main()
