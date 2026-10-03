"""The companion page: what YouTube puts beside the video mpv plays, and mpv's
own playlist beside it. Nothing here reaches the network or a player; both are
replaced by stand-ins that write down what they were asked."""

import unittest

from PySide6.QtCore import QObject

from weave.config import Config
from weave.sources import watchnext
from weave.ui.bridge import COMPANION, COMPANION_CHIP_STATE, Bridge

from .support import scratch_db

NOW = "nownownownn"


def card(video_id, title="A song", channel="Someone", duration="3:25"):
    return {"video_id": video_id, "title": title, "channel": channel,
            "channel_id": "UC" + "c" * 22, "duration": duration, "views": "", "age": "",
            "picture": f"https://pictures.invalid/{video_id}.jpg"}


CHIPS = [{"label": "Mix", "token": ""}, {"label": "All", "token": "tok-all"},
         {"label": "From Someone", "token": "tok-from"}, {"label": "Related", "token": "tok-rel"}]


class Count:
    def __init__(self):
        self.count = 0

    def emit(self, *_a):
        self.count += 1


class FakePlayer:
    def __init__(self, alive=True):
        self.alive = alive
        self.said = []

    def __getattr__(self, name):
        if name not in ("append", "insert_next", "jump", "remove", "move", "clear"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.said.append((name, args, kwargs))
            return self.alive
        return call


def make(test, alive=True):
    bridge = Bridge.__new__(Bridge)
    # A worker made here is parented to the bridge, which has to be a whole
    # QObject for that.
    QObject.__init__(bridge)
    bridge._db = scratch_db(test)
    bridge._cfg = Config(raw={})
    bridge._view_kind = COMPANION
    bridge._mpv_key = ""
    bridge._companion_cache = {}
    bridge._companion_video = ""
    bridge._companion_fetch = None
    bridge._companion_state = ""
    bridge._companion_why = ""
    bridge._mpv_playlist = []
    bridge._mpv_looping = False
    bridge._mpv_running = alive
    bridge._companion_known = {}
    bridge._companion_namer = None
    bridge._companion_asked = set()
    # Weave's own player, and its page's tab, neither of which is in play here.
    bridge._audio = None
    bridge._now_rec_open = False
    bridge._web_results = []
    bridge.asked = []
    bridge._companion_ask = lambda *args: bridge.asked.append(args)
    bridge.launched = []
    bridge._launch = lambda worker: bridge.launched.append(worker) or True
    bridge._player = FakePlayer(alive)
    bridge.handed = []
    bridge._hand_over = lambda *args: bridge.handed.append(args)
    bridge.notices = []
    bridge._set_notice = lambda text, *a, **k: bridge.notices.append(text)
    for name in ("companionChanged", "companionQueueChanged", "musicBoxesChanged"):
        setattr(bridge, name, Count())
    return bridge


def answered(bridge, video_id=NOW, chips=CHIPS, cards=None):
    Bridge._on_companion_beside(bridge, video_id, chips, cards or {
        "Mix": [card("mixmixmix01"), card("mixmixmix02")],
        "All": [card("allallall01")]})


class WhatIsAsked(unittest.TestCase):
    def test_a_new_song_is_asked_about_once(self):
        bridge = make(self)
        bridge._companion_video = NOW
        Bridge._companion_follow(bridge)
        self.assertEqual(bridge.asked, [(NOW,)])
        answered(bridge)
        Bridge._companion_follow(bridge)
        self.assertEqual(len(bridge.asked), 1, "a kept answer was asked for again")

    def test_a_chip_picked_before_is_asked_with_its_token_once_the_chips_are_known(self):
        bridge = make(self)
        bridge._db.set_state(COMPANION_CHIP_STATE, "Related")
        bridge._companion_video = NOW
        answered(bridge)
        Bridge._companion_follow(bridge)
        self.assertEqual(bridge.asked, [(NOW, "Related", "tok-rel")])
        Bridge._on_companion_chipped(bridge, NOW, "Related", [card("relrelrel01")])
        self.assertEqual([one["key"] for one in Bridge._get_companion_cards(bridge)],
                         ["yt:relrelrel01"])

    def test_another_artists_from_chip_stands_in_and_anything_else_is_the_mix(self):
        bridge = make(self)
        bridge._companion_video = NOW
        answered(bridge, chips=[{"label": "Mix", "token": ""},
                                {"label": "From Other", "token": "t"}])
        bridge._db.set_state(COMPANION_CHIP_STATE, "From Someone")
        self.assertEqual(Bridge._companion_chip(bridge, NOW), "From Other")
        bridge._db.set_state(COMPANION_CHIP_STATE, "Related")
        self.assertEqual(Bridge._companion_chip(bridge, NOW), "Mix")

    def test_only_while_the_page_is_open(self):
        bridge = make(self)
        bridge._view_kind = "all"
        Bridge._companion_heard(bridge, f"yt:{NOW}", "Long Way North")
        self.assertEqual(bridge.asked, [])
        self.assertEqual(bridge._companion_video, NOW)
        self.assertEqual(bridge._companion_known[NOW]["title"], "Long Way North")
        Bridge._companion_heard(bridge, "twitch:someone", "A stream")
        self.assertEqual(bridge._companion_video, NOW, "Twitch is followed")

    def test_a_failure_is_not_asked_again_at_once(self):
        bridge = make(self)
        bridge._companion_video = NOW
        Bridge._on_companion_failed(bridge, NOW, "HTTP 500")
        Bridge._on_companion_done(bridge)
        self.assertEqual(bridge.asked, [])
        self.assertIn("HTTP 500", Bridge._get_companion_note(bridge))
        Bridge._on_companion_refused(bridge, NOW)
        Bridge._on_companion_done(bridge)
        self.assertEqual(bridge.asked, [])
        self.assertIn("ceiling", Bridge._get_companion_note(bridge))


class WhatIsShown(unittest.TestCase):
    def test_the_tiles_of_the_chosen_chip_say_which_are_in_the_queue(self):
        bridge = make(self)
        bridge._companion_video = NOW
        answered(bridge)
        bridge._mpv_playlist = [{"url": "https://www.youtube.com/watch?v=mixmixmix02",
                                 "current": True, "title": ""}]
        tiles = Bridge._get_companion_cards(bridge)
        self.assertEqual([(one["key"], one["queued"]) for one in tiles],
                         [("yt:mixmixmix01", False), ("yt:mixmixmix02", True)])
        chips = Bridge._get_companion_chips(bridge)
        self.assertEqual([one["label"] for one in chips if one["chosen"]], ["Mix"])

    def test_the_queue_rows_say_what_plays_and_what_has_played(self):
        bridge = make(self)
        bridge._companion_known = {"aaaaaaaaaaa": {"title": "A", "channel": "One"},
                                   "bbbbbbbbbbb": {"title": "B", "duration": "4:00"}}
        bridge._mpv_playlist = [
            {"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "current": False, "title": ""},
            {"url": "https://youtu.be/bbbbbbbbbbb", "current": True, "title": ""},
            {"url": "/home/user/song.flac", "current": False, "title": "A file"}]
        rows = Bridge._get_companion_queue(bridge)
        self.assertEqual([(row["title"], row["played"], row["playing"]) for row in rows],
                         [("A", True, False), ("B", False, True), ("A file", False, False)])
        self.assertEqual(rows[1]["duration"], "4:00")
        self.assertIn("bbbbbbbbbbb/mqdefault.jpg", rows[1]["picture"])
        self.assertEqual(rows[2]["picture"], "")

    def test_titles_come_from_what_is_stored_and_the_rest_are_asked_for(self):
        bridge = make(self)
        bridge._db.set_music_favorite("aaaaaaaaaaa", True, "Kept song", "Someone")
        bridge._mpv_playlist = [
            {"url": f"https://www.youtube.com/watch?v={one}", "current": False, "title": ""}
            for one in ("aaaaaaaaaaa", "bbbbbbbbbbb")]
        Bridge._name_queue(bridge)
        self.assertEqual(bridge._companion_known["aaaaaaaaaaa"]["title"], "Kept song")
        self.assertEqual([type(one).__name__ for one in bridge.launched], ["QueueNamer"])
        Bridge._name_queue(bridge)
        self.assertEqual(len(bridge.launched), 1, "an id was asked about twice")
        Bridge._on_queue_named(bridge, {"bbbbbbbbbbb": {"title": "Named", "channel": "X"}})
        self.assertEqual(bridge._companion_known["bbbbbbbbbbb"]["title"], "Named")

    def test_the_page_is_headed_with_the_name_of_the_one_playing(self):
        bridge = make(self)
        bridge._db.set_music_favorite(NOW, True, "Long Way North", "Someone")
        bridge._mpv_playlist = [{"url": f"https://www.youtube.com/watch?v={NOW}",
                                 "current": True, "title": ""}]
        Bridge._companion_heard(bridge, f"yt:{NOW}", "")
        Bridge._companion_arrive(bridge)
        self.assertEqual(Bridge._get_companion_now(bridge), "Long Way North")

    def test_nothing_playing_and_no_player_are_said(self):
        bridge = make(self, alive=False)
        self.assertIn("Nothing is playing", Bridge._get_companion_note(bridge))
        bridge._companion_video = NOW
        self.assertIn("not running", Bridge._get_companion_note(bridge))


class Presses(unittest.TestCase):
    def setUp(self):
        self.bridge = make(self)
        self.bridge._companion_video = NOW
        answered(self.bridge)

    def test_a_tile_goes_on_the_end_next_or_now(self):
        Bridge.companionAdd(self.bridge, 1)
        Bridge.companionPlayNext(self.bridge, 0)
        Bridge.companionPlayNow(self.bridge, 0)
        url = "https://www.youtube.com/watch?v="
        self.assertEqual(self.bridge._player.said, [
            ("append", (url + "mixmixmix02",), {}),
            ("insert_next", (url + "mixmixmix01",), {"play": False}),
            ("insert_next", (url + "mixmixmix01",), {"play": True})])
        self.assertEqual(self.bridge.handed, [])

    def test_with_no_player_one_is_started_with_it(self):
        self.bridge._player = FakePlayer(alive=False)
        Bridge.companionAdd(self.bridge, 0)
        self.assertEqual(self.bridge.handed[0][:3],
                         ("yt:mixmixmix01", "https://www.youtube.com/watch?v=mixmixmix01",
                          "A song"))

    def test_a_row_put_where_another_is(self):
        Bridge.companionMove(self.bridge, 0, 2)
        Bridge.companionMove(self.bridge, 3, 1)
        Bridge.companionMove(self.bridge, 1, 1)
        self.assertEqual([said[1] for said in self.bridge._player.said], [(0, 3), (3, 1)])

    def test_clear_asks_mpv_to_keep_only_the_one_playing(self):
        Bridge.companionClear(self.bridge)
        self.assertEqual(self.bridge._player.said, [("clear", (), {})])

    def test_the_queue_is_kept_as_a_box_in_its_order(self):
        self.bridge._companion_known["bbbbbbbbbbb"] = {"title": "B", "channel": "Two"}
        self.bridge._mpv_playlist = [
            {"url": "https://www.youtube.com/watch?v=mixmixmix02", "current": True, "title": ""},
            {"url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "current": False, "title": ""}]
        self.bridge.createMusicBox = lambda name: self.bridge._db.create_music_box(name)
        made = Bridge.companionSaveQueue(self.bridge, "Tonight")
        songs = self.bridge._db.music_box_songs(made)
        self.assertEqual([(song["ext_id"], song["title"]) for song in songs],
                         [("mixmixmix02", "A song"), ("bbbbbbbbbbb", "B")])

    def test_an_entry_of_the_queue_can_too_and_says_its_channel(self):
        """An entry put there from the browser was never a tile, and is known
        only by what naming it found."""
        self.bridge._companion_known["bbbbbbbbbbb"] = {"title": "B", "channel": "Two"}
        found = Bridge._companion_card(self.bridge, "yt:bbbbbbbbbbb")
        self.assertEqual((found["title"], found["channel"]), ("B", "Two"))
        self.assertIn("bbbbbbbbbbb/mqdefault.jpg", found["picture"])
        self.assertEqual(Bridge._loose_row(self.bridge, "yt:bbbbbbbbbbb")["title"], "B")
        self.bridge._mpv_playlist = [
            {"url": "https://www.youtube.com/watch?v=mixmixmix01", "current": True, "title": ""}]
        self.assertEqual(Bridge._get_companion_queue(self.bridge)[0]["channelId"],
                         "UC" + "c" * 22)
        self.assertEqual(Bridge._get_companion_cards(self.bridge)[0]["channelId"],
                         "UC" + "c" * 22)

    def test_a_tile_can_go_in_a_box_and_be_shared(self):
        self.assertEqual(Bridge._loose_row(self.bridge, "yt:mixmixmix01")["channel_ext_id"],
                         "UC" + "c" * 22)
        song = Bridge._companion_song(self.bridge, "yt:mixmixmix01")
        self.assertEqual((song["title"], song["duration_s"]), ("A song", 205))
        self.assertIsNone(Bridge._companion_card(self.bridge, "yt:nothingher"))


class TheChipConstant(unittest.TestCase):
    def test_the_mix_is_what_a_first_visit_shows(self):
        bridge = make(self)
        self.assertEqual(Bridge._companion_chip(bridge, NOW), watchnext.MIX)


if __name__ == "__main__":
    unittest.main()
