"""What the music page shows before it has asked anything.

Gathering the shelves takes several seconds, so what was on them last time is
written down and drawn at once while a fresh copy is fetched behind it. That
was built and it never worked: a guard meant to throw away a set written
before songs carried the address of whoever made them asked EVERY item for
that address, including the two shelves Weave builds itself, which never had
one to carry. So every set it wrote was thrown away on the next launch and the
page he opened was blank for as long as a fetch takes, which is what he
reported.

Measured on a real database: 23 shelves, 79 KB, and the one built from the
ordinary suggestions carrying no such key on any of its 20 songs.
"""

import json
import unittest

from weave.ui.bridge import Bridge


class Db:
    def __init__(self, blob):
        self.blob = blob

    def get_state(self, key, default=None):
        return self.blob if key == "music_shelves" else default


def remembered(shelves):
    bridge = Bridge.__new__(Bridge)
    bridge._db = Db(json.dumps(shelves) if shelves is not None else None)
    return Bridge._remembered_shelves(bridge)


def song(name, artist_id=""):
    return {"title": name, "videoId": "a" * 11, "playlistId": "",
            "artistId": artist_id, "thumbnail": ""}


def tile(name):
    """A playlist rather than a song. It never had an artist to name."""
    return {"title": name, "videoId": "", "playlistId": "PL1",
            "artistId": "", "thumbnail": ""}


class WhatIsTrusted(unittest.TestCase):
    def test_a_set_of_songs_is_kept(self):
        kept = remembered([{"title": "Listen again", "items": [song("One", "UC1")]}])
        self.assertEqual([shelf["title"] for shelf in kept], ["Listen again"])

    def test_a_shelf_of_playlists_is_kept_although_it_names_no_artist(self):
        """Your playlists is one of these, and asking it for an artist is what
        threw the whole set away every time."""
        kept = remembered([{"title": "Listen again", "items": [song("One", "UC1")]},
                           {"title": "Your playlists", "items": [tile("A list")]}])
        self.assertEqual(len(kept), 2)

    def test_and_so_are_songs_with_nobody_to_name(self):
        """The shelf built from the ordinary suggestions carries the key and
        nothing in it, since that listing has no artist address at all."""
        kept = remembered([{"title": "From your YouTube", "items": [song("One")]}])
        self.assertEqual(len(kept), 1)

    def test_but_a_set_from_before_the_key_existed_is_not(self):
        stale = {"title": "A song", "videoId": "a" * 11, "thumbnail": ""}
        self.assertEqual(remembered([{"title": "Listen again", "items": [stale]}]), [])

    def test_nothing_stored_is_nothing_to_show(self):
        self.assertEqual(remembered(None), [])

    def test_and_so_is_something_that_is_not_a_set_of_shelves(self):
        bridge = Bridge.__new__(Bridge)
        bridge._db = Db("not json at all")
        self.assertEqual(Bridge._remembered_shelves(bridge), [])
        bridge._db = Db(json.dumps({"title": "not a list"}))
        self.assertEqual(Bridge._remembered_shelves(bridge), [])


class WhatWeaveWrites(unittest.TestCase):
    """Every item Weave builds itself carries the same keys as one from the
    music service, or the guard above throws away the set holding it."""

    def shelf_items(self, name):
        from weave import poller

        class Home(poller.MusicHome):
            def __init__(self):
                pass

        from weave.config import Config

        home = Home()
        home._cfg = Config(raw={})
        if name == "playlists":
            from weave.sources import ytmusic

            was = ytmusic.playlists
            ytmusic.playlists = lambda *a, **k: [
                {"id": "PL1", "title": "A list", "count": 3, "thumbnail": ""}]
            try:
                return home._own_playlists()["items"]
            finally:
                ytmusic.playlists = was
        raise AssertionError(name)

    def test_the_playlists_shelf_carries_the_key(self):
        for item in self.shelf_items("playlists"):
            self.assertIn("artistId", item)


if __name__ == "__main__":
    unittest.main()
