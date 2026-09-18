"""A channel's music, arranged as the records it came out on.

The records themselves are named on the artist page that is already read for
the songs, so listing them costs nothing. What is on each one is a call of its
own to the same music browse endpoint, measured at 0.11 to 0.24 s with no
refusal for fifteen in a row, which is what makes reading them all worth it.

Singles go into one group rather than one group each, and that group is heard
in no particular order: picking a single is picking the singles, not picking a
running order.
"""

import unittest

from weave.config import Config
from weave.poller import ArtistMusic
from weave.sources.ytmusic import MusicError, Track, _releases


def track(video_id, title="A song"):
    return Track(video_id=video_id, title=title, artist="Somebody", album="A Record",
                 duration="3:01", thumbnail_url="https://pictures.invalid/a.jpg")


def song(video_id, title="A song", album=""):
    return {"key": f"yt:{video_id}", "title": title, "thumbnail": "", "album": album}


class Fake:
    """Enough of the music source for the grouping to be exercised."""

    MusicError = MusicError

    def __init__(self, answers, refuse=()):
        self.answers = answers
        self.refuse = set(refuse)
        self.asked = []

    def release_tracks(self, _profile, playlist_id="", browse_id=""):
        ident = playlist_id or browse_id
        self.asked.append(ident)
        if ident in self.refuse:
            raise MusicError("offline")
        return self.answers.get(ident, [])


def release(ident, kind="album", title="A Record", year="2026"):
    return {"kind": kind, "title": title, "year": year, "playlist_id": ident,
            "browse_id": "", "thumbnail": "https://pictures.invalid/cover.jpg"}


def worker_for(key="yt:UC1"):
    """A real worker, built and never started.

    Built rather than made with __new__, because it says what it has read as
    it reads it and a signal needs the Qt object behind it. What is exercised
    is the arranging; the reading it would otherwise do is the network.
    """
    return ArtistMusic(Config(raw={}), key, "UC1", [], "")


def grouped(fake, releases, songs, worker=None):
    worker = worker or worker_for()
    return ArtistMusic._grouped(worker, fake, None, {"releases": releases}, songs)


class WhatAnArtistPageAlreadyCarries(unittest.TestCase):
    def test_albums_and_singles_are_both_read_off_the_page(self):
        page = {
            "albums": {"results": [{"title": "One", "year": "2026",
                                    "audioPlaylistId": "OLAK1", "browseId": "MPREB1"}]},
            "singles": {"results": [{"title": "Two", "year": "2025",
                                     "browseId": "MPREB2"}]},
        }
        found = _releases(page)
        self.assertEqual([one["kind"] for one in found], ["album", "single"])
        self.assertEqual(found[0]["playlist_id"], "OLAK1")

    def test_a_single_names_only_a_browse_id_and_is_still_usable(self):
        """Measured on a real account: an album carries both ways in, a single
        carries only the browse id."""
        page = {"singles": {"results": [{"title": "Two", "browseId": "MPREB2"}]}}
        found = _releases(page)
        self.assertEqual(found[0]["browse_id"], "MPREB2")
        self.assertEqual(found[0]["playlist_id"], "")

    def test_an_entry_with_no_way_in_is_left_out(self):
        page = {"albums": {"results": [{"title": "Nameless"}]}}
        self.assertEqual(_releases(page), [])

    def test_a_page_that_names_no_records_answers_nothing(self):
        self.assertEqual(_releases({}), [])


class TheSongsAreArrangedAsRecords(unittest.TestCase):
    def test_an_album_becomes_a_group_in_the_order_it_was_released_in(self):
        fake = Fake({"OLAK1": [track("aaa"), track("bbb")]})
        groups = grouped(fake, [release("OLAK1", title="First")], [])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["title"], "First")
        self.assertEqual([one["key"] for one in groups[0]["songs"]],
                         ["yt:aaa", "yt:bbb"])
        self.assertFalse(groups[0]["shuffled"])

    def test_singles_are_one_group_and_it_is_heard_in_no_order(self):
        fake = Fake({"S1": [track("aaa")], "S2": [track("bbb")]})
        groups = grouped(fake, [release("S1", kind="single"),
                                release("S2", kind="single")], [])
        self.assertEqual(len(groups), 1, "a group per single reads as one song albums")
        self.assertEqual(groups[0]["title"], "Singles")
        self.assertTrue(groups[0]["shuffled"])
        self.assertEqual(len(groups[0]["songs"]), 2)

    def test_what_is_on_no_record_is_kept_rather_than_lost(self):
        fake = Fake({"OLAK1": [track("aaa")]})
        groups = grouped(fake, [release("OLAK1")], [song("aaa"), song("zzz")])
        self.assertEqual([one["title"] for one in groups], ["A Record", "Other songs"])
        self.assertEqual([one["key"] for one in groups[-1]["songs"]], ["yt:zzz"])

    def test_with_no_records_at_all_the_leftovers_are_simply_the_songs(self):
        groups = grouped(Fake({}), [], [song("aaa")])
        self.assertEqual([one["title"] for one in groups], ["Songs"])

    def test_a_record_that_will_not_answer_does_not_take_the_tab_with_it(self):
        fake = Fake({"OLAK1": [track("aaa")], "OLAK2": [track("bbb")]},
                    refuse=["OLAK1"])
        groups = grouped(fake, [release("OLAK1"), release("OLAK2", title="Second")], [])
        self.assertEqual([one["title"] for one in groups], ["Second"])

    def test_an_empty_record_is_not_drawn_as_an_empty_shelf(self):
        groups = grouped(Fake({"OLAK1": []}), [release("OLAK1")], [])
        self.assertEqual(groups, [])

    def test_only_so_many_records_are_ever_read(self):
        """One call each. A discography of two hundred must not become two
        hundred calls the moment a tab is opened."""
        many = [release(f"OLAK{i}") for i in range(ArtistMusic.RELEASE_CAP + 12)]
        fake = Fake({f"OLAK{i}": [track(f"v{i:03d}")] for i in range(len(many))})
        groups = grouped(fake, many, [])
        self.assertEqual(len(fake.asked), ArtistMusic.RELEASE_CAP)
        self.assertEqual(len(groups), ArtistMusic.RELEASE_CAP)

    def test_a_song_off_a_record_falls_back_to_the_record_s_own_picture(self):
        """An album track often carries no picture of its own, and a square of
        nothing beside a title reads as a song that failed to load."""
        bare = Track(video_id="aaa", title="A song", artist="Somebody",
                     album="A Record", duration="3:01", thumbnail_url="")
        groups = grouped(Fake({"OLAK1": [bare]}), [release("OLAK1")], [])
        self.assertNotEqual(groups[0]["songs"][0]["thumbnail"], "")


class WhatThePageNeverNamed(unittest.TestCase):
    """An artist page names five albums and ten singles; the songs behind it
    run past a hundred. Everything else used to land in one heap.

    Every song says which record it came out on, and that is in the answer
    already. Measured on two real artists, 60 of 60 and 14 of 14 of those
    leftovers named one.
    """

    def test_a_leftover_joins_the_record_it_names(self):
        fake = Fake({"OLAK1": [track("aaa")]})
        groups = grouped(fake, [release("OLAK1", title="A Record")],
                         [song("aaa"), song("zzz", album="A Record")])
        self.assertEqual([one["title"] for one in groups], ["A Record"])
        self.assertEqual(len(groups[0]["songs"]), 2, "the track was left outside it")

    def test_the_name_is_matched_however_it_is_capitalised(self):
        fake = Fake({"OLAK1": [track("aaa")]})
        groups = grouped(fake, [release("OLAK1", title="A Record")],
                         [song("zzz", album="  a record ")])
        self.assertEqual(len(groups), 1, "the same record was drawn twice")

    def test_a_record_nobody_named_is_drawn_from_the_songs_alone(self):
        groups = grouped(Fake({}), [],
                         [song("a", album="Hidden"), song("b", album="Hidden"),
                          song("c", album="Hidden")])
        self.assertEqual([one["title"] for one in groups], ["Hidden"])
        self.assertEqual(len(groups[0]["songs"]), 3)

    def test_but_two_songs_are_a_single_and_its_instrumental(self):
        """Measured: fifteen of twenty blocks on one artist were exactly that,
        a single beside its off vocal or its live version."""
        groups = grouped(Fake({}), [],
                         [song("a", album="A Single"), song("b", album="A Single")])
        self.assertEqual([one["kind"] for one in groups], ["singles"])
        self.assertEqual(len(groups[0]["songs"]), 2)

    def test_a_song_naming_no_record_is_still_kept(self):
        groups = grouped(Fake({}), [], [song("a"), song("b")])
        self.assertEqual([one["title"] for one in groups], ["Songs"])

    def test_nothing_is_lost_and_nothing_is_drawn_twice(self):
        fake = Fake({"OLAK1": [track("aaa"), track("bbb")]})
        rest = [song("aaa", album="A Record"), song("ccc", album="A Record"),
                song("ddd", album="Hidden"), song("eee", album="Hidden"),
                song("fff", album="Hidden"), song("ggg", album="One Off"),
                song("hhh")]
        groups = grouped(fake, [release("OLAK1", title="A Record")], rest)
        keys = [one["key"] for group in groups for one in group["songs"]]
        self.assertEqual(sorted(set(keys)), sorted(keys), "a song was drawn twice")
        self.assertEqual(len(keys), 8, f"a song went missing: {keys}")


class TheRecordsArriveOneAtATime(unittest.TestCase):
    """Sixteen calls is eight seconds, and a page that sits empty for eight
    seconds and then fills all at once is the same wait spent worse."""

    def test_each_record_is_said_as_it_lands(self):
        seen = []
        worker = worker_for()
        worker.growing.connect(lambda _key, groups: seen.append(len(groups)))
        fake = Fake({"OLAK1": [track("aaa")], "OLAK2": [track("bbb")],
                     "OLAK3": [track("ccc")]})
        grouped(fake, [release("OLAK1"), release("OLAK2"), release("OLAK3")], [],
                worker=worker)
        self.assertEqual(seen, [1, 2, 3], "the page filled all at once")

    def test_what_is_said_early_never_holds_the_leftovers(self):
        """They are whatever no record has claimed yet, so early on they are
        everything, and they would shrink as the records land."""
        said = []
        worker = worker_for()
        worker.growing.connect(lambda _key, groups: said.append(groups))
        grouped(Fake({"OLAK1": [track("aaa")]}), [release("OLAK1")],
                [song("aaa"), song("zzz")], worker=worker)
        self.assertEqual([one["kind"] for one in said[0]], ["album"])

    def test_the_name_of_the_channel_travels_with_it(self):
        """The window has to know which page the records belong to, or they
        land on whatever is open when they arrive."""
        seen = []
        worker = worker_for("yt:UCsomebody")
        worker.growing.connect(lambda key, _groups: seen.append(key))
        grouped(Fake({"OLAK1": [track("aaa")]}), [release("OLAK1")], [], worker=worker)
        self.assertEqual(seen, ["yt:UCsomebody"])


class PressingASongOnARecord(unittest.TestCase):
    def bridge(self, groups):
        from weave.ui.bridge import Bridge

        bridge = Bridge.__new__(Bridge)
        bridge._channel_music_groups = groups
        bridge._audio = _Audio()
        bridge._track_items = lambda songs: [
            {"key": one["key"], "title": one["title"], "url": "https://example.test"}
            for one in songs]
        return bridge

    def test_the_rest_of_the_record_follows_the_song_that_was_pressed(self):
        from weave.ui.bridge import Bridge

        bridge = self.bridge([{"songs": [song("aaa"), song("bbb"), song("ccc")],
                               "shuffled": False}])
        Bridge.playChannelGroupSong(bridge, 0, 1)
        items, start, shuffled = bridge._audio.played
        self.assertEqual([one["key"] for one in items], ["yt:aaa", "yt:bbb", "yt:ccc"])
        self.assertEqual(start, 1)
        self.assertFalse(shuffled)

    def test_a_single_takes_the_other_singles_in_no_order(self):
        from weave.ui.bridge import Bridge

        bridge = self.bridge([{"songs": [song("aaa"), song("bbb")], "shuffled": True}])
        Bridge.playChannelGroupSong(bridge, 0, 0)
        self.assertTrue(bridge._audio.played[2])

    def test_a_press_on_a_record_that_is_no_longer_there_does_nothing(self):
        from weave.ui.bridge import Bridge

        bridge = self.bridge([])
        Bridge.playChannelGroupSong(bridge, 3, 0)
        self.assertIsNone(bridge._audio.played)


class ShufflingOneListOnly(unittest.TestCase):
    """The player's own setting is somebody's choice and is not touched by a
    list that asks to be heard in no order."""

    def player(self):
        from weave.audio import AudioPlayer

        player = AudioPlayer.__new__(AudioPlayer)
        player._queue = []
        player._order = []
        player._at = 0
        player._shuffle = False
        player._repeat_mode = 0
        player._forget_recovery = lambda: None
        player._start_current = lambda: None
        player.queueChanged = _Signal()
        player.queueReplaced = _Signal()
        return player

    def items(self, count):
        return [{"key": f"yt:{i}", "title": str(i), "url": "https://example.test"}
                for i in range(count)]

    def test_what_was_picked_stays_first(self):
        from weave.audio import AudioPlayer

        player = self.player()
        AudioPlayer.play_items(player, self.items(8), 3, shuffle_rest=True)
        self.assertEqual(player._order[0], 3)
        self.assertEqual(sorted(player._order), list(range(8)))

    def test_the_setting_is_left_alone(self):
        from weave.audio import AudioPlayer

        player = self.player()
        AudioPlayer.play_items(player, self.items(4), 0, shuffle_rest=True)
        self.assertFalse(player._shuffle, "one shelf turned shuffle on for everything")

    def test_an_ordinary_list_keeps_its_order(self):
        from weave.audio import AudioPlayer

        player = self.player()
        AudioPlayer.play_items(player, self.items(6), 2)
        self.assertEqual(player._order, [0, 1, 2, 3, 4, 5])


class _Audio:
    def __init__(self):
        self.played = None

    def play_items(self, items, start=0, shuffle_rest=False):
        self.played = (items, start, shuffle_rest)


class _Signal:
    def emit(self, *_a):
        pass


if __name__ == "__main__":
    unittest.main()
