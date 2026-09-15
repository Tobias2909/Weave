"""The music a channel releases, and finding out which artist that is.

The hard part is not fetching the songs, it is that a channel and the artist it
releases under are often two different channels. What is pinned here is the walk
that finds one from the other, and the remembering that keeps an ordinary
channel from being asked the same question on every visit.
"""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QObject

from weave.config import Config
from weave.db import Database
from weave.poller import ArtistMusic
from weave.ui.bridge import Bridge


class FakeMusic:
    """Stands in for the music service. Records what it was asked."""

    MusicError = RuntimeError

    def __init__(self, artists: dict | None = None, pages: dict | None = None) -> None:
        self.artists = artists or {}
        self.pages = pages or {}
        self.asked: list = []

    def artist(self, _profile, channel_id):
        self.asked.append(("artist", channel_id))
        return self.pages.get(channel_id, {"name": "", "songs": []})

    def artist_of(self, _profile, video_id):
        self.asked.append(("artist_of", video_id))
        return self.artists.get(video_id, [])


def worker(channel_id="UC1", videos=(), known="") -> ArtistMusic:
    return ArtistMusic(Config(raw={}), "yt:UC1", channel_id, list(videos), known)


class WhichArtistIsThis(unittest.TestCase):
    def test_a_known_answer_is_not_looked_up_again(self) -> None:
        music = FakeMusic()
        found = worker(known="UCartist")._identity(music, None)
        self.assertEqual(found[0], "UCartist")
        self.assertEqual(music.asked, [], "a kept answer was asked for again")

    def test_a_channel_that_is_itself_an_artist_answers_at_once(self) -> None:
        # Every channel reached from a song is this case, since the id on the
        # song is the artist already.
        music = FakeMusic(pages={"UC1": {"name": "Somebody", "songs": [1]}})
        artist_id, name = worker()._identity(music, None)
        self.assertEqual((artist_id, name), ("UC1", "Somebody"))
        self.assertEqual(music.asked, [("artist", "UC1")],
                         "its own videos were asked about needlessly")

    def test_otherwise_its_videos_are_asked_who_made_them(self) -> None:
        # The case that matters: the songs live on a separate channel, so the
        # channel itself is not an artist and only its videos know.
        music = FakeMusic(artists={
            "v1": [{"name": "The Artist", "id": "UCart"}],
            "v2": [{"name": "The Artist", "id": "UCart"}],
        })
        artist_id, name = worker(videos=["v1", "v2"])._identity(music, None)
        self.assertEqual((artist_id, name), ("UCart", "The Artist"))

    def test_one_guest_does_not_outvote_the_channel(self) -> None:
        # A single track can name a featured artist rather than the artist the
        # channel releases as, which is why more than one is sampled.
        music = FakeMusic(artists={
            "v1": [{"name": "A Guest", "id": "UCguest"}],
            "v2": [{"name": "The Artist", "id": "UCart"}],
            "v3": [{"name": "The Artist", "id": "UCart"}],
        })
        artist_id, _name = worker(videos=["v1", "v2", "v3"])._identity(music, None)
        self.assertEqual(artist_id, "UCart")

    def test_a_channel_nobody_names_has_no_music_side(self) -> None:
        music = FakeMusic(artists={"v1": [], "v2": [{"name": "No id", "id": ""}]})
        self.assertEqual(worker(videos=["v1", "v2"])._identity(music, None), ("", ""))

    def test_only_a_few_videos_are_ever_sampled(self) -> None:
        many = [f"v{i}" for i in range(20)]
        self.assertEqual(len(worker(videos=many)._video_ids), ArtistMusic.SAMPLE)


class WhatIsRemembered(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.conn.execute(
            "INSERT INTO channels(key, platform, ext_id, title, added_at) "
            "VALUES('yt:UC1','youtube','UC1','A Channel',1)")
        self.db.conn.commit()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_an_answer_is_kept(self) -> None:
        self.db.set_channel_music("yt:UC1", "UCart", "The Artist")
        row = self.db.channel("yt:UC1")
        self.assertEqual(row["music_artist_id"], "UCart")
        self.assertEqual(row["music_artist_name"], "The Artist")
        self.assertTrue(row["music_checked_at"])

    def test_a_negative_answer_is_kept_as_well(self) -> None:
        # Otherwise every visit to an ordinary channel puts the same question
        # and spends the same requests to be told the same nothing.
        self.db.set_channel_music("yt:UC1", "", "")
        row = self.db.channel("yt:UC1")
        self.assertEqual(row["music_artist_id"], "")
        self.assertTrue(row["music_checked_at"], "the asking was not recorded")

    def test_shorts_are_left_out_of_the_sample(self) -> None:
        for ext, short in (("aaa", 0), ("bbb", 1), ("ccc", 0)):
            self.db.conn.execute(
                "INSERT INTO videos(key, channel_key, platform, ext_id, title, "
                "is_short, published_at, first_seen_at) "
                "VALUES(?,'yt:UC1','youtube',?,?,?,?,?)",
                (f"yt:{ext}", ext, ext, short, 100, 100))
        self.db.conn.commit()
        self.assertEqual(sorted(self.db.channel_video_ids("yt:UC1")), ["aaa", "ccc"])


class TheTab(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.conn.execute(
            "INSERT INTO channels(key, platform, ext_id, title, added_at) "
            "VALUES('yt:UC1','youtube','UC1','A Channel',1)")
        self.db.conn.commit()
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._db = self.db
        self.bridge._cfg = Config(raw={})
        self.bridge._view_channel = "yt:UC1"
        self.bridge._channel_music = []
        self.bridge._channel_music_name = ""
        self.bridge._channel_music_busy = False
        self.bridge._channel_music_key = ""
        self.bridge._artist_music = None
        self.started: list = []
        self.bridge._launch = lambda worker: self.started.append(worker) or True

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_a_channel_known_to_have_none_is_not_asked_again(self) -> None:
        self.db.set_channel_music("yt:UC1", "", "")
        Bridge._fetch_channel_music(self.bridge)
        self.assertEqual(self.started, [], "a settled question was put again")

    def test_a_channel_never_asked_is_asked(self) -> None:
        Bridge._fetch_channel_music(self.bridge)
        self.assertEqual(len(self.started), 1)
        self.assertTrue(self.bridge._channel_music_busy)

    def test_a_kept_identity_is_handed_to_the_worker(self) -> None:
        self.db.set_channel_music("yt:UC1", "UCart", "The Artist")
        Bridge._fetch_channel_music(self.bridge)
        self.assertEqual(self.started[0]._known_id, "UCart",
                         "the artist was looked up again from nothing")

    def test_the_answer_is_written_down(self) -> None:
        Bridge._on_channel_music(self.bridge, "yt:UC1", {
            "artistId": "UCart", "artistName": "The Artist",
            "songs": [{"key": "yt:s1", "title": "One"}]})
        self.assertEqual(self.db.channel("yt:UC1")["music_artist_id"], "UCart")
        self.assertEqual(len(self.bridge._channel_music), 1)
        self.assertFalse(self.bridge._channel_music_busy)

    def test_the_line_names_the_artist_only_when_it_is_somebody_else(self) -> None:
        self.bridge._channel_music_name = "A Channel"
        self.assertEqual(Bridge._get_channel_music_by(self.bridge), "",
                         "the page explained a name that needed no explaining")
        self.bridge._channel_music_name = "The Artist"
        self.assertEqual(Bridge._get_channel_music_by(self.bridge), "The Artist")


if __name__ == "__main__":
    unittest.main()
