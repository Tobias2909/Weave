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


# Channel ids are UC and twenty two more. Anything shorter is not one, and
# the guard that says so is why short stand ins never reached the code.
TOPIC = "UC" + "t" * 22
REAL = "UC" + "r" * 22


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


class ANonArtistChannel(unittest.TestCase):
    def test_it_answers_rather_than_raising(self) -> None:
        # An artist page is read through a header an ordinary channel does not
        # have, and the library reaches for it without looking. Raised, that
        # arrived in the window as a KeyError about a renderer.
        from weave.sources import ytmusic

        class Client:
            def get_artist(self, _channel_id):
                raise KeyError("musicImmersiveHeaderRenderer")

        was = ytmusic.client
        ytmusic.client = lambda _profile: Client()
        try:
            found = ytmusic.artist(None, "UC1")
        finally:
            ytmusic.client = was
        self.assertEqual(found["songs"], [])
        self.assertEqual(found["name"], "")

    def test_the_empty_answer_is_a_copy(self) -> None:
        # Handed out as the shared one, a caller that put something in it would
        # change what every later call answered.
        from weave.sources import ytmusic

        one = ytmusic.artist(None, "")
        one["songs"].append("something")
        self.assertEqual(ytmusic.artist(None, "")["songs"], [])


class TheRealChannel(unittest.TestCase):
    """An artist id is often a generated channel carrying the songs and nothing
    else. Standing there means no videos, no pictures and no streams."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._db = self.db
        self.bridge._cfg = Config(raw={})
        self.bridge._channel_music = []
        self.bridge._channel_music_name = ""
        self.bridge._channel_music_key = ""
        self.bridge._channel_music_busy = False
        self.bridge._artist_open = None
        self.opened: list = []
        self.tabs: list = []
        # The real one keeps a row for a channel it has never seen, which is
        # what the write below then has something to write to.
        def open_channel(key):
            self.opened.append(key)
            if not self.db.channel(key):
                self.db.conn.execute(
                    "INSERT INTO channels(key, platform, ext_id, title, added_at) "
                    "VALUES(?,'youtube',?,'',1)", (key, key.split(":", 1)[-1]))
                self.db.conn.commit()

        self.bridge.openChannel = open_channel
        self.bridge.showChannelTab = self.tabs.append
        self.bridge._set_status = lambda *_a, **_k: None
        self.bridge.channelTabChanged = type("S", (), {"emit": lambda self: None})()
        self.started: list = []
        self.bridge._launch = lambda worker: self.started.append(worker) or True

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def add_channel(self, key, ext, title, artist_id=None):
        self.db.conn.execute(
            "INSERT INTO channels(key, platform, ext_id, title, added_at) "
            "VALUES(?,'youtube',?,?,1)", (key, ext, title))
        self.db.conn.commit()
        if artist_id is not None:
            self.db.set_channel_music(key, artist_id, title)

    def test_a_channel_already_known_costs_no_request(self) -> None:
        self.add_channel("yt:" + REAL, REAL, "The Band", artist_id=TOPIC)
        Bridge.openArtistMusic(self.bridge, TOPIC)
        self.assertEqual(self.opened, ["yt:" + REAL])
        self.assertEqual(self.tabs, ["music"])
        self.assertEqual(self.started, [], "a known answer was looked up again")

    def test_the_lookup_finds_the_channel_the_artist_page_points_at(self) -> None:
        Bridge._on_artist_opened(self.bridge, "", {
            "artistId": TOPIC, "artistName": "The Band",
            "channelId": REAL, "songs": [{"key": "yt:s1"}]})
        self.assertEqual(self.opened, ["yt:" + REAL],
                         "landed on the generated channel rather than the real one")
        # And the mapping is written down, so the next press costs nothing.
        self.assertEqual(self.db.channel_for_artist(TOPIC), "yt:" + REAL)

    def test_the_songs_come_with_it(self) -> None:
        Bridge._on_artist_opened(self.bridge, "", {
            "artistId": TOPIC, "artistName": "The Band",
            "channelId": REAL, "songs": [{"key": "yt:s1"}, {"key": "yt:s2"}]})
        self.assertEqual(len(self.bridge._channel_music), 2,
                         "the songs already in hand were thrown away")
        self.assertEqual(self.bridge._channel_music_key, "yt:" + REAL)

    def test_without_a_real_channel_the_artist_is_where_it_goes(self) -> None:
        Bridge._on_artist_opened(self.bridge, "", {
            "artistId": TOPIC, "artistName": "The Band",
            "channelId": "", "songs": []})
        self.assertEqual(self.opened, ["yt:" + TOPIC])

    def test_a_channel_that_is_not_one_is_refused(self) -> None:
        Bridge.openArtistMusic(self.bridge, "not-a-channel")
        self.assertEqual(self.opened, [])
        self.assertEqual(self.started, [])


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


class KeptSongsRememberWhoMadeThem(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_the_address_survives_into_the_kept_list(self) -> None:
        # A kept song is read back long after the list it came from is gone, so
        # the address has to be stored with it or the name is words for ever.
        artist = "UC" + "a" * 22
        self.db.remember_played("aaaaaaaaaaa", "One", "Somebody", None, 200, artist)
        self.db.set_music_favorite("aaaaaaaaaaa", True)
        rows = self.db.music_favorites()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["artist_id"], artist)

    def test_playing_it_again_from_a_list_without_one_keeps_it(self) -> None:
        artist = "UC" + "b" * 22
        self.db.remember_played("bbbbbbbbbbb", "One", "Somebody", None, 200, artist)
        self.db.remember_played("bbbbbbbbbbb", "One", "Somebody", None, 200, None)
        row = self.db.conn.execute(
            "SELECT artist_id FROM music_history WHERE ext_id='bbbbbbbbbbb'").fetchone()
        self.assertEqual(row["artist_id"], artist)


class TheSongsAreKept(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._db = self.db
        self.bridge._cfg = Config(raw={})
        self.bridge._view_channel = "yt:UC1"
        self.bridge._channel_music = []
        self.bridge._channel_music_groups = []
        self.bridge._channel_music_from_cache = False
        self.bridge._channel_music_name = ""
        self.bridge._channel_music_key = ""
        self.bridge._channel_music_busy = False
        self.bridge._artist_music = None
        self.bridge.channelTabChanged = type("S", (), {"emit": lambda self: None})()
        self.started: list = []
        self.bridge._launch = lambda worker: self.started.append(worker) or True
        self.db.conn.execute(
            "INSERT INTO channels(key, platform, ext_id, title, added_at) "
            "VALUES('yt:UC1','youtube','UC1','A Channel',1)")
        self.db.conn.commit()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_a_second_visit_costs_nothing(self) -> None:
        # Reading a catalogue is two requests and several seconds, for a list
        # that changes about as often as a playlist does.
        self.bridge._keep_channel_music(
            "yt:UC1", [{"key": "yt:s1", "title": "One"}],
            [{"title": "A Record", "kind": "album", "shuffled": False,
              "songs": [{"key": "yt:s1", "title": "One"}]}])
        Bridge._fetch_channel_music(self.bridge)
        self.assertEqual(self.started, [], "the catalogue was read again")
        self.assertEqual(len(self.bridge._channel_music), 1)

    def test_a_stale_one_is_read_again(self) -> None:
        import time as clock

        self.bridge._keep_channel_music("yt:UC1", [{"key": "yt:s1"}], [])
        self.db.set_state("channel_music_at.yt:UC1",
                          str(int(clock.time()) - 7 * 3600))
        Bridge._fetch_channel_music(self.bridge)
        self.assertEqual(len(self.started), 1, "a stale list was trusted")

    def test_but_it_is_drawn_at_once_while_that_happens(self) -> None:
        """Reading a catalogue is a call per record and eight seconds measured.
        A week old answer to press now beats an empty page for eight seconds."""
        import time as clock

        self.bridge._keep_channel_music(
            "yt:UC1", [{"key": "yt:s1"}],
            [{"title": "A Record", "kind": "album", "shuffled": False,
              "songs": [{"key": "yt:s1"}]}])
        self.db.set_state("channel_music_at.yt:UC1",
                          str(int(clock.time()) - 8 * 24 * 3600))
        Bridge._fetch_channel_music(self.bridge)
        self.assertEqual(len(self.bridge._channel_music_groups), 1,
                         "an old catalogue was thrown away rather than shown")
        self.assertTrue(self.bridge._channel_music_from_cache)
        self.assertEqual(len(self.started), 1, "and it was not read again behind it")

    def test_a_reading_still_arriving_is_not_drawn_over_what_is_shown(self) -> None:
        """It arrives a record at a time, and records already on the page would
        go away and come back one by one."""
        self.bridge._keep_channel_music(
            "yt:UC1", [{"key": "yt:s1"}],
            [{"title": "A Record", "kind": "album", "songs": [{"key": "yt:s1"}]},
             {"title": "Another", "kind": "album", "songs": [{"key": "yt:s2"}]}])
        Bridge._fetch_channel_music(self.bridge)
        Bridge._on_channel_music_growing(
            self.bridge, "yt:UC1",
            [{"title": "A Record", "kind": "album", "songs": [{"key": "yt:s1"}]}])
        self.assertEqual(len(self.bridge._channel_music_groups), 2,
                         "a partial reading took a record off the page")

    def test_but_an_empty_page_fills_as_the_records_land(self) -> None:
        Bridge._on_channel_music_growing(
            self.bridge, "yt:UC1",
            [{"title": "A Record", "kind": "album", "songs": [{"key": "yt:s1"}]}])
        self.assertEqual(len(self.bridge._channel_music_groups), 1)

    def test_records_for_another_channel_are_dropped(self) -> None:
        """They arrive seconds late, by which time the page may have moved."""
        Bridge._on_channel_music_growing(
            self.bridge, "yt:UC2",
            [{"title": "A Record", "kind": "album", "songs": [{"key": "yt:s1"}]}])
        self.assertEqual(self.bridge._channel_music_groups, [])

    def test_walking_to_another_channel_does_not_keep_the_old_songs(self) -> None:
        # Walking back lands on a channel without going through the opener, so
        # nothing was reading this half again and it showed the songs of the
        # channel before it.
        self.bridge._keep_channel_music("yt:UC1", [{"key": "yt:s1"}], [])
        Bridge._fetch_channel_music(self.bridge)
        self.assertEqual(len(self.bridge._channel_music), 1)

        self.db.conn.execute(
            "INSERT INTO channels(key, platform, ext_id, title, added_at) "
            "VALUES('yt:UC2','youtube','UC2','Another',1)")
        self.db.conn.commit()
        self.bridge._view_channel = "yt:UC2"
        Bridge._fetch_channel_music(self.bridge)
        self.assertEqual(self.bridge._channel_music, [],
                         "another channel's songs were left on the page")
