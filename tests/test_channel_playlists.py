"""The playlists a channel has made.

Two things decide the shape of this. The tab that lists them carries names and
no video count, so a count is one request per playlist and appears only once a
playlist has been opened, which costs nothing extra. And a playlist's videos
hang off a playlists row, so looking at somebody else's means making one, which
must not put it in the sidebar beside your own or be swept away by the next
reading of your own.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave.db import Database
from weave.sources.playlists import Playlist

CHANNEL = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"
ONE = "PLaaaaaaaaaaaaaaaaaaaaaa"
TWO = "PLbbbbbbbbbbbbbbbbbbbbbb"


class TheTab(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_it_is_stored_in_the_order_the_channel_gave(self):
        self.db.replace_channel_playlists(CHANNEL, [Playlist(TWO, "Second"), Playlist(ONE, "First")])
        self.assertEqual([row["title"] for row in self.db.channel_playlists(CHANNEL)],
                         ["Second", "First"])

    def test_reading_it_again_replaces_it(self):
        self.db.replace_channel_playlists(CHANNEL, [Playlist(ONE, "Gone next time")])
        self.db.replace_channel_playlists(CHANNEL, [Playlist(TWO, "The only one now")])
        self.assertEqual([row["ext_id"] for row in self.db.channel_playlists(CHANNEL)], [TWO])

    def test_the_age_is_remembered_so_it_is_read_once_a_day(self):
        self.assertIsNone(self.db.channel_playlists_age_s(CHANNEL))
        self.db.replace_channel_playlists(CHANNEL, [Playlist(ONE, "First")])
        self.assertLess(self.db.channel_playlists_age_s(CHANNEL), 5)

    def test_a_playlist_nobody_opened_has_no_count(self):
        self.db.replace_channel_playlists(CHANNEL, [Playlist(ONE, "First")])
        self.assertEqual(self.db.channel_playlists(CHANNEL)[0]["items"], 0)


class LookingAtOne(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")
        self.db.replace_channel_playlists(CHANNEL, [Playlist(ONE, "Theirs")])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def mine(self):
        return [row["ext_id"] for row in self.db.playlists()]

    def kept(self):
        return [row["ext_id"] for row in self.db.playlists(origin="channel")]

    def test_opening_one_keeps_it_out_of_your_own_list(self):
        self.db.open_channel_playlist(ONE, "Theirs")
        self.assertEqual(self.mine(), [])
        self.assertEqual(self.kept(), [])
        self.assertIsNotNone(self.db.playlist(ONE))

    def test_its_videos_have_somewhere_to_live(self):
        self.db.open_channel_playlist(ONE, "Theirs")
        self.db.replace_playlist_items(ONE, [{
            "ext_id": "aaaaaaaaaaa", "title": "One of theirs", "channel_name": "One",
            "channel_ext_id": "UCaaaaaaaaaaaaaaaaaaaaaa", "duration_s": 60,
            "thumbnail_url": None, "views": 1, "published_at": 1,
        }])
        self.assertEqual(self.db.channel_playlists(CHANNEL)[0]["items"], 1)

    def test_keeping_it_moves_it_into_its_own_section(self):
        self.db.open_channel_playlist(ONE, "Theirs")
        self.db.keep_playlist(ONE)
        self.assertEqual(self.kept(), [ONE])
        self.assertEqual(self.mine(), [])

    def test_and_letting_it_go_takes_it_out_again(self):
        self.db.open_channel_playlist(ONE, "Theirs")
        self.db.keep_playlist(ONE)
        self.db.keep_playlist(ONE, False)
        self.assertEqual(self.kept(), [])

    def test_reading_your_own_playlists_never_takes_a_kept_one(self):
        # The whole reason origin exists. Your feed knows nothing about
        # somebody else's playlist and must not delete it for being absent.
        self.db.open_channel_playlist(ONE, "Theirs")
        self.db.keep_playlist(ONE)
        self.db.replace_playlists([{"ext_id": TWO, "title": "Yours"}])
        self.assertEqual(self.kept(), [ONE])
        self.assertEqual(self.mine(), [TWO])

    def test_but_it_does_take_one_you_only_looked_at(self):
        self.db.open_channel_playlist(ONE, "Theirs")
        self.assertEqual(self.db.sweep_temporary_playlists(older_than_s=0), 1)
        self.assertIsNone(self.db.playlist(ONE))

    def test_and_never_one_that_is_kept(self):
        self.db.open_channel_playlist(ONE, "Theirs")
        self.db.keep_playlist(ONE)
        self.assertEqual(self.db.sweep_temporary_playlists(older_than_s=0), 0)
        self.assertIsNotNone(self.db.playlist(ONE))

    def test_a_kept_one_shows_as_kept_in_the_tab(self):
        self.db.open_channel_playlist(ONE, "Theirs")
        self.db.keep_playlist(ONE)
        self.assertEqual(self.db.channel_playlists(CHANNEL)[0]["origin"], "channel")

    def test_it_can_be_kept_straight_off_the_tab(self):
        # The tile on a channel's tab offers keeping, and nothing has been
        # opened at that point, so there is no row to move into the section.
        # Every other test here opens one first, which is why this held.
        self.db.keep_playlist(ONE)
        self.assertEqual(self.kept(), [ONE])
        self.assertEqual(self.mine(), [])

    def test_and_it_is_kept_under_the_name_the_tab_gave(self):
        self.db.keep_playlist(ONE)
        self.assertEqual(self.db.playlist(ONE)["title"], "Theirs")

    def test_opening_it_afterwards_leaves_it_kept(self):
        self.db.keep_playlist(ONE)
        self.db.open_channel_playlist(ONE, "Theirs")
        self.assertEqual(self.kept(), [ONE])

    def test_and_letting_go_of_one_kept_that_way_still_works(self):
        self.db.keep_playlist(ONE)
        self.db.keep_playlist(ONE, False)
        self.assertEqual(self.kept(), [])

    def test_but_nothing_the_tab_never_listed_is_kept(self):
        self.db.keep_playlist(TWO)
        self.assertEqual(self.kept(), [])
        self.assertIsNone(self.db.playlist(TWO))


class ThePictures(unittest.TestCase):
    """The listing carries a frame from each playlist's first video, so the
    tiles have pictures without a call per playlist."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_a_picture_is_stored_with_the_name(self):
        self.db.replace_channel_playlists(CHANNEL, [Playlist(ONE, "Theirs", "a.jpg")])
        self.assertEqual(self.db.channel_playlists(CHANNEL)[0]["thumbnail_url"], "a.jpg")

    def test_a_listing_from_before_them_reads_as_old(self):
        # Read at most once a day, so without this a listing stored by an
        # older version would show no pictures for a day after this one
        # arrives.
        self.db.replace_channel_playlists(CHANNEL, [Playlist(ONE, "Theirs")])
        self.assertTrue(self.db.channel_playlists_lack_pictures(CHANNEL))

    def test_one_with_pictures_does_not(self):
        self.db.replace_channel_playlists(CHANNEL, [Playlist(ONE, "Theirs", "a.jpg"),
                                                    Playlist(TWO, "Also theirs")])
        self.assertFalse(self.db.channel_playlists_lack_pictures(CHANNEL))

    def test_and_neither_does_a_channel_with_no_playlists_at_all(self):
        self.assertFalse(self.db.channel_playlists_lack_pictures(CHANNEL))


class TheWayBack(unittest.TestCase):
    """A playlist opened off a channel says which channel, so the bar above it
    can offer the way back to the tab it came from."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")
        self.db.replace_channel_playlists(CHANNEL, [Playlist(ONE, "Theirs")])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_it_names_the_channel_it_was_opened_from(self):
        self.db.open_channel_playlist(ONE, "Theirs")
        found = self.db.playlist_source(ONE)
        self.assertEqual(found["channel_key"], CHANNEL)
        self.assertEqual(found["channel_title"], "One")
        self.assertEqual(found["origin"], "temp")

    def test_a_kept_one_still_names_it(self):
        self.db.open_channel_playlist(ONE, "Theirs")
        self.db.keep_playlist(ONE)
        self.assertEqual(self.db.playlist_source(ONE)["origin"], "channel")

    def test_one_of_your_own_has_nowhere_to_go_back_to(self):
        self.db.replace_playlists([{"ext_id": TWO, "title": "Yours"}])
        self.assertIsNone(self.db.playlist_source(TWO))

    def test_and_neither_does_one_that_was_never_opened(self):
        self.assertIsNone(self.db.playlist_source(ONE))


class TheirOwnSection(unittest.TestCase):
    """The kept ones are a list of their own in the sidebar, so they are
    ordered among themselves and not among yours."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "One")
        self.db.replace_playlists([{"ext_id": "PLmine1", "title": "Mine one"},
                                   {"ext_id": "PLmine2", "title": "Mine two"}])
        for ext_id, title in ((ONE, "Theirs one"), (TWO, "Theirs two")):
            self.db.open_channel_playlist(ext_id, title)
            self.db.keep_playlist(ext_id)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def kept(self):
        return [row["ext_id"] for row in self.db.playlists(origin="channel")]

    def mine(self):
        return [row["ext_id"] for row in self.db.playlists()]

    def test_a_kept_one_can_be_moved(self):
        self.assertTrue(self.db.move_playlist(TWO, -1))
        self.assertEqual(self.kept(), [TWO, ONE])

    def test_and_moving_it_leaves_your_own_order_alone(self):
        self.db.move_playlist(TWO, -1)
        self.assertEqual(self.mine(), ["PLmine1", "PLmine2"])

    def test_it_cannot_be_pushed_out_of_its_own_list(self):
        self.assertFalse(self.db.move_playlist(ONE, -1))
        self.assertEqual(self.kept(), [ONE, TWO])

    def test_and_one_of_yours_cannot_be_pushed_into_it(self):
        self.assertFalse(self.db.move_playlist("PLmine2", 1))
        self.assertEqual(self.mine(), ["PLmine1", "PLmine2"])


if __name__ == "__main__":
    unittest.main()
