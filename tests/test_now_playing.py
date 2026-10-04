"""The Now playing page: the ways in and out, and what is beside the song.

The page itself is verified by driving the window and looking at the picture.
What is here is the part that has no picture, which is when the page opens at
all, what closing it does to the view you were on, and what a new song does to
everything drawn beside it.
"""

import sys
import unittest
from pathlib import Path

from PySide6.QtCore import QObject

sys.path.insert(0, str(Path(__file__).resolve().parent))

from weave.poller import SongSide
from weave.ui.bridge import ALL, MUSIC, NOWPLAYING, Bridge


class Recorder:
    def __init__(self) -> None:
        self.count = 0

    def emit(self, *_a) -> None:
        self.count += 1


class FakeAudio:
    def __init__(self, queued: bool = True, track: dict | None = None) -> None:
        self.hasQueue = queued
        self.track = track if track is not None else {"key": "yt:a", "videoId": "a"}
        self.added: list = []

    def add_item(self, item, play_next=False) -> bool:
        self.added.append((item, play_next))
        return True

    def play_item_now(self, item) -> bool:
        self.added.append((item, "now"))
        return True

    def queue_entries(self) -> list:
        return [item for item, _how in self.added if isinstance(item, dict)]

    def play_items(self, items, start=0) -> None:
        self.added.append((items, start))


class FakeNav:
    def __init__(self, has_previous: bool) -> None:
        self._has_previous = has_previous

    def previous(self):
        return object() if self._has_previous else None


def bridge_with(audio=None, view=ALL, has_previous=True) -> Bridge:
    bridge = Bridge.__new__(Bridge)
    QObject.__init__(bridge)
    bridge._audio = audio
    # The videos played in the window, which a hand-built bridge has none of.
    bridge._video = None
    bridge._view_kind = view
    bridge._nav = FakeNav(has_previous)
    bridge._now_side = None
    bridge._now_detail = None
    bridge._now_words = {}
    bridge._now_comments = []
    bridge._now_rec_open = False
    bridge._now_tab = "video"
    bridge._now_threads = 5
    bridge._now_busy = ""
    bridge._now_read = set()
    # Held by the worker and never read here, so None is enough.
    bridge._cfg = None
    bridge._now_song = ""
    bridge._now_ids = {}
    bridge._now_lines = []
    bridge._now_starts = []
    bridge._now_lyric = {}
    bridge.nowChanged = Recorder()
    bridge.nowLyricChanged = Recorder()
    bridge._status = ""
    bridge.statusChanged = Recorder()
    return bridge


class TheWayIn(unittest.TestCase):
    def test_it_refuses_to_open_with_nothing_playing(self) -> None:
        # The button that opens it lives on the music bar, and the bar is not
        # there when nothing is queued, but the page is a view like any other
        # and can be asked for from elsewhere.
        bridge = bridge_with(audio=None)
        went = []
        bridge._set_view = lambda *a, **k: went.append(a)
        Bridge.showNowPlaying(bridge)
        self.assertEqual(went, [], "the page opened with no music at all")

        bridge = bridge_with(audio=FakeAudio(queued=False))
        bridge._set_view = lambda *a, **k: went.append(a)
        Bridge.showNowPlaying(bridge)
        self.assertEqual(went, [], "the page opened with an empty queue")

    def test_it_opens_when_something_is_queued(self) -> None:
        bridge = bridge_with(audio=FakeAudio())
        went = []
        bridge._set_view = lambda *a, **k: went.append(a)
        Bridge.showNowPlaying(bridge)
        self.assertEqual(went, [(NOWPLAYING, -1)])


class TheWayOut(unittest.TestCase):
    def test_closing_walks_back_to_where_you_were(self) -> None:
        bridge = bridge_with(audio=FakeAudio(), view=NOWPLAYING)
        walked = []
        bridge.goBack = lambda: walked.append(True)
        bridge._set_view = lambda *a, **k: walked.append(a)
        Bridge.closeNowPlaying(bridge)
        self.assertEqual(walked, [True])

    def test_closing_with_nowhere_behind_it_lands_on_the_feed(self) -> None:
        # Walking back needs somewhere to walk back to. Opened as the very
        # first view, there is none, and stepping back would go nowhere at all.
        bridge = bridge_with(audio=FakeAudio(), view=NOWPLAYING, has_previous=False)
        went = []
        bridge.goBack = lambda: went.append("back")
        bridge._set_view = lambda *a, **k: went.append(a)
        Bridge.closeNowPlaying(bridge)
        self.assertEqual(went, [(ALL, -1)])

    def test_closing_does_nothing_from_another_view(self) -> None:
        bridge = bridge_with(audio=FakeAudio(), view=MUSIC)
        walked = []
        bridge.goBack = lambda: walked.append(True)
        bridge._set_view = lambda *a, **k: walked.append(a)
        Bridge.closeNowPlaying(bridge)
        self.assertEqual(walked, [], "leaving one view closed another")

    def test_stopping_the_music_takes_the_page_with_it(self) -> None:
        # The bar goes when the queue empties, and the page is about what the
        # bar is playing, so it cannot outlive it.
        bridge = bridge_with(audio=FakeAudio(queued=False), view=NOWPLAYING)
        closed = []
        bridge.closeNowPlaying = lambda: closed.append(True)
        Bridge._close_now_playing_if_silent(bridge)
        self.assertEqual(closed, [True])

    def test_a_song_ending_into_the_next_one_leaves_the_page_open(self) -> None:
        bridge = bridge_with(audio=FakeAudio(queued=True), view=NOWPLAYING)
        closed = []
        bridge.closeNowPlaying = lambda: closed.append(True)
        Bridge._close_now_playing_if_silent(bridge)
        self.assertEqual(closed, [], "the page closed between two songs")


class WhatSitsBesideTheSong(unittest.TestCase):
    def test_a_new_song_empties_all_of_it(self) -> None:
        # Otherwise an open tab shows the last song's answer until the new one
        # lands, which reads as the page simply being wrong.
        bridge = bridge_with(audio=FakeAudio())
        bridge._now_words = {"text": "something", "read": True}
        bridge._now_comments = [{"text": "a"}]
        bridge._now_threads = 15
        bridge._now_busy = "words"
        Bridge._forget_now(bridge)
        self.assertEqual(bridge._now_words, {})
        self.assertEqual(bridge._now_comments, [])
        self.assertEqual(bridge._now_threads, 5)
        self.assertEqual(bridge._now_busy, "")
        self.assertTrue(bridge.nowChanged.count)

    def test_adding_to_the_queue_keeps_what_is_beside_the_song(self) -> None:
        # The player raises the same signal for a song added to the queue as
        # for a song starting, and reading that as a new song threw away what
        # was beside the song it had just been queued from.
        audio = FakeAudio(track={"key": "yt:a", "url": ""})
        bridge = bridge_with(audio=audio)
        bridge._now_song = "yt:a"
        bridge._now_words = {"text": "One", "read": True}
        Bridge._forget_now(bridge)
        self.assertEqual(bridge._now_words, {"text": "One", "read": True},
                         "queueing a song emptied what was beside the song")

    def test_the_next_song_still_empties_it(self) -> None:
        audio = FakeAudio(track={"key": "yt:b", "url": ""})
        bridge = bridge_with(audio=audio)
        bridge._now_song = "yt:a"
        bridge._now_words = {"text": "One", "read": True}
        Bridge._forget_now(bridge)
        self.assertEqual(bridge._now_words, {})
        self.assertEqual(bridge._now_song, "yt:b")

    def test_a_new_song_asks_for_the_words_of_the_tab_left_open(self) -> None:
        # The page used to ask on hearing of the new song, before the last
        # song's words were put away. They still counted as read, so nothing
        # was asked, and then they were cleared: an empty tab on every other
        # song until it was pressed again.
        audio = FakeAudio(track={"key": "yt:b", "videoId": "b"})
        bridge = bridge_with(audio=audio, view=NOWPLAYING)
        bridge._now_tab = SongSide.WORDS
        bridge._now_song = "yt:a"
        bridge._now_read = {SongSide.WORDS}
        bridge._now_words = {"text": "the words of a", "read": True}
        started = []
        bridge._launch = lambda worker: started.append(worker) or True
        Bridge._forget_now(bridge)
        self.assertEqual(len(started), 1, "the new song's words were never asked for")
        self.assertEqual(started[0]._video_id, "b")
        self.assertEqual(bridge._now_busy, SongSide.WORDS)

    def test_nothing_is_asked_for_while_the_page_is_closed(self) -> None:
        audio = FakeAudio(track={"key": "yt:b", "videoId": "b"})
        bridge = bridge_with(audio=audio, view=ALL)
        bridge._now_tab = SongSide.WORDS
        bridge._now_song = "yt:a"
        started = []
        bridge._launch = lambda worker: started.append(worker) or True
        Bridge._forget_now(bridge)
        self.assertEqual(started, [], "words were fetched for a closed page")
        # And opening it asks then.
        bridge._view_kind = NOWPLAYING
        Bridge._read_now_tab(bridge)
        self.assertEqual(len(started), 1, "opening the page asked for nothing")

    def test_the_video_tab_asks_for_nothing(self) -> None:
        bridge = bridge_with(audio=FakeAudio(), view=NOWPLAYING)
        started = []
        bridge._launch = lambda worker: started.append(worker) or True
        Bridge._read_now_tab(bridge)
        self.assertEqual(started, [])

    def test_the_words_of_a_song_skipped_are_not_shown_under_the_next(self) -> None:
        # Skipped while its words were on their way: they arrive while the
        # next song plays and its own words are being read.
        bridge = bridge_with(audio=FakeAudio(track={"key": "yt:b", "videoId": "b"}))
        bridge._now_busy = SongSide.WORDS
        Bridge._on_now_side(bridge, {
            "what": SongSide.WORDS, "videoId": "a", "wordsId": "W", "synced": True,
            "text": "the words of a", "source": "", "lines": [],
        })
        self.assertEqual(bridge._now_words, {}, "one song's words were shown for another")
        self.assertEqual(bridge._now_busy, SongSide.WORDS,
                         "the next song's words stopped being waited for")
        self.assertEqual(bridge._now_ids["a"], {"words": "W", "synced": True},
                         "where the skipped song's words are was not kept")

    def test_the_comments_of_a_song_skipped_are_not_shown_under_the_next(self) -> None:
        bridge = bridge_with(audio=FakeAudio(track={"key": "yt:b", "videoId": "b"}))
        bridge._now_busy = "comments"
        bridge._keep_extra = lambda *_a: None
        Bridge._on_now_comments(bridge, "yt:a", [{"text": "about a"}], {})
        self.assertEqual(bridge._now_comments, [])
        self.assertEqual(bridge._now_busy, "comments")

    def test_the_address_of_the_words_is_kept_so_asking_again_costs_less(self) -> None:
        # The station answer carries the address of the words. Asking for it
        # again would be a second request for something already in hand.
        bridge = bridge_with(audio=FakeAudio())
        Bridge._on_now_side(bridge, {
            "what": SongSide.WORDS, "videoId": "a", "wordsId": "W", "synced": True,
            "text": "the words", "source": "somewhere",
        })
        self.assertEqual(bridge._now_ids["a"], {"words": "W", "synced": True})
        self.assertEqual(bridge._now_words["source"], "somewhere")
        self.assertTrue(bridge._now_words["read"])
        self.assertEqual(bridge._now_busy, "")

    def test_a_song_with_no_words_is_an_answer_and_not_a_failure(self) -> None:
        bridge = bridge_with(audio=FakeAudio())
        Bridge._on_now_side(bridge, {
            "what": SongSide.WORDS, "videoId": "a", "wordsId": "", "synced": True,
            "text": "", "source": "",
        })
        # Read, and empty. The page needs both facts to tell "none of them"
        # from "not asked yet".
        self.assertTrue(bridge._now_words["read"])
        self.assertEqual(bridge._now_words["text"], "")

    def test_nothing_is_asked_for_twice(self) -> None:
        bridge = bridge_with(audio=FakeAudio())
        bridge._now_read = {SongSide.WORDS}
        started = []
        bridge._launch = lambda worker: started.append(worker) or True
        Bridge.readNowSide(bridge, SongSide.WORDS)
        self.assertEqual(started, [], "the words were asked for a second time")

    def test_a_press_turned_away_is_not_remembered_as_asked(self) -> None:
        # Pressing one tab while another is still loading used to be recorded
        # as asked by the window and refused by this side, which left that tab
        # empty until the song changed.
        bridge = bridge_with(audio=FakeAudio())
        bridge._now_busy = "comments"
        started = []
        bridge._launch = lambda worker: started.append(worker) or True
        Bridge.readNowSide(bridge, SongSide.WORDS)
        self.assertEqual(started, [], "two were fetched at once")
        self.assertNotIn(SongSide.WORDS, bridge._now_read,
                         "a press that fetched nothing counted as answered")

        # And it works on the next press, once the other has landed.
        bridge._now_busy = ""
        Bridge.readNowSide(bridge, SongSide.WORDS)
        self.assertEqual(len(started), 1, "the second press was refused too")

    def test_an_empty_answer_still_counts_as_answered(self) -> None:
        bridge = bridge_with(audio=FakeAudio())
        Bridge._on_now_side(bridge, {
            "what": SongSide.WORDS, "videoId": "a", "wordsId": "", "synced": True,
            "text": "", "source": "",
        })
        self.assertIn(SongSide.WORDS, bridge._now_read)

    def test_more_comments_are_offered_until_an_answer_falls_short(self) -> None:
        bridge = bridge_with(audio=FakeAudio())
        self.assertFalse(Bridge._get_now_comments_more(bridge), "nothing read yet")
        bridge._now_comments = [{"text": str(i)} for i in range(5)]
        self.assertTrue(Bridge._get_now_comments_more(bridge))
        asked = []
        bridge.readNowComments = lambda: asked.append(bridge._now_threads)
        Bridge.loadMoreNowComments(bridge)
        self.assertEqual(asked, [15], "a press asks for ten more threads")
        bridge._now_comments = [{"text": str(i)} for i in range(12)]
        self.assertFalse(Bridge._get_now_comments_more(bridge),
                         "twelve of fifteen is every thread there is")

    def test_the_id_is_read_out_of_the_address(self) -> None:
        # The entries the player is handed are built in several places and most
        # keep only what the player needs, which is a title, a picture and an
        # address. No videoId field among them. Reading one was why both tabs
        # asked for nothing at all and sat empty.
        real = {"key": "yt:dQw4w9WgXcQ", "title": "One", "artist": "Somebody",
                "thumbnail": "", "live": False,
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
        bridge = bridge_with(audio=FakeAudio(track=real))
        self.assertEqual(Bridge._now_video_id(bridge), "dQw4w9WgXcQ")

        started = []
        bridge._launch = lambda worker: started.append(worker) or True
        Bridge.readNowSide(bridge, SongSide.WORDS)
        self.assertEqual(len(started), 1, "the words were never asked for")
        self.assertEqual(bridge._now_busy, SongSide.WORDS)

    def test_a_named_id_wins_over_the_address(self) -> None:
        bridge = bridge_with(audio=FakeAudio(track={"key": "yt:a", "videoId": "named",
                                                    "url": "https://youtu.be/other"}))
        self.assertEqual(Bridge._now_video_id(bridge), "named")

    def test_an_entry_with_no_address_at_all_asks_for_nothing(self) -> None:
        bridge = bridge_with(audio=FakeAudio(track={"key": "yt:a"}))
        started = []
        bridge._launch = lambda worker: started.append(worker) or True
        Bridge.readNowSide(bridge, SongSide.WORDS)
        self.assertEqual(started, [])


def with_tiles(bridge: Bridge, video_id: str = "dQw4w9WgXcQ") -> Bridge:
    """What YouTube put beside the song playing, kept the way an answer is."""
    bridge._companion_cache = {video_id: {
        "chips": [{"label": "Mix", "token": ""}],
        "cards": {"Mix": [{
            "video_id": "bbbbbbbbbbb", "title": "One", "channel": "Somebody",
            "channel_id": "UCaaaaaaaaaaaaaaaaaaaaaa", "duration": "3:21",
            "views": "", "age": "", "picture": "https://i.ytimg.com/vi/bbbbbbbbbbb/hq720.jpg"}]},
    }}
    bridge._db = type("Db", (), {"get_state": lambda self, *_a: "Mix"})()
    bridge._set_notice = lambda *_a, **_k: None
    return bridge


class TheRecommendedTiles(unittest.TestCase):
    TRACK = {"key": "yt:dQw4w9WgXcQ", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}

    def test_play_next_and_the_end_of_the_queue_are_different_places(self) -> None:
        audio = FakeAudio(track=dict(self.TRACK))
        bridge = with_tiles(bridge_with(audio=audio))
        Bridge.queueNowRecommended(bridge, 0, True)
        Bridge.queueNowRecommended(bridge, 0, False)
        Bridge.playNowRecommended(bridge, 0)
        self.assertEqual([how for _item, how in audio.added], [True, False, "now"])
        song = audio.added[0][0]
        # The player is handed an address, and the channel stands for whoever
        # made it, as a channel rather than an artist of the music service.
        self.assertTrue(song["url"].endswith("bbbbbbbbbbb"))
        self.assertEqual(song["key"], "yt:bbbbbbbbbbb")
        self.assertEqual(song["artistId"], "")
        self.assertEqual(song["channelId"], "UCaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(song["duration_s"], 201)

    def test_a_tile_that_is_not_there_does_nothing(self) -> None:
        audio = FakeAudio(track=dict(self.TRACK))
        bridge = with_tiles(bridge_with(audio=audio))
        Bridge.queueNowRecommended(bridge, 3, True)
        Bridge.playNowRecommended(bridge, -1)
        self.assertEqual(audio.added, [])

    def test_a_tile_in_the_queue_says_so(self) -> None:
        audio = FakeAudio(track=dict(self.TRACK))
        bridge = with_tiles(bridge_with(audio=audio))
        self.assertFalse(Bridge._get_now_recommended(bridge)[0]["queued"])
        Bridge.queueNowRecommended(bridge, 0, False)
        self.assertTrue(Bridge._get_now_recommended(bridge)[0]["queued"])

    def test_a_song_that_is_no_youtube_video_says_why_there_is_nothing(self) -> None:
        bridge = with_tiles(bridge_with(audio=FakeAudio(track={"key": "source:1",
                                                               "url": "http://radio.test"})))
        bridge._companion_state = ""
        self.assertIn("not a YouTube song", Bridge._get_now_recommended_note(bridge))
        self.assertEqual(Bridge._get_now_recommended(bridge), [])

    def test_a_song_in_the_queue_can_go_in_a_box_like_a_tile(self) -> None:
        # Its right press offers the boxes and the address, which look a
        # video up by its key the way they look up a tile.
        audio = FakeAudio(track=dict(self.TRACK))
        audio.added = [({"key": "yt:ccccccccccc", "title": "Queued", "artist": "Somebody",
                         "artistId": "UC" + "s" * 22, "duration": "2:10",
                         "thumbnail": "", "url": "u"}, False)]
        bridge = with_tiles(bridge_with(audio=audio))
        card = Bridge._queued_song_card(bridge, "ccccccccccc")
        self.assertEqual((card["title"], card["channel"], card["channel_id"], card["duration"]),
                         ("Queued", "Somebody", "UC" + "s" * 22, "2:10"))
        self.assertIn("ccccccccccc", card["picture"])
        self.assertIsNone(Bridge._queued_song_card(bridge, "notqueued00"))

    def test_only_the_open_tab_follows_the_song(self) -> None:
        # The answers are asked for while the tab is on screen and never
        # otherwise, since each one is a request against the companion's
        # ceiling.
        bridge = with_tiles(bridge_with(audio=FakeAudio(track=dict(self.TRACK)),
                                        view=NOWPLAYING), video_id="other")
        asked = []
        bridge._companion_ask = lambda video_id, *_a: asked.append(video_id)
        bridge.companionChanged = Recorder()
        Bridge.setNowTab(bridge, "words")
        self.assertEqual(asked, [])
        Bridge.setNowTab(bridge, "recommended")
        self.assertEqual(asked, ["dQw4w9WgXcQ"])
        # Off the page, nothing follows it, whatever tab it was left on.
        bridge._view_kind = MUSIC
        Bridge._companion_follow(bridge)
        self.assertEqual(asked, ["dQw4w9WgXcQ"])


class OneQueueDrawnOneWay(unittest.TestCase):
    def test_both_places_use_the_shared_list(self) -> None:
        # The bar's popup and the page show the same queue with the same
        # handles on it. Two copies of that drifted apart the moment either
        # grew a feature, so there is only the one component.
        qml = Path(__file__).resolve().parent.parent / "weave" / "qml"
        shared = (qml / "QueueList.qml").read_text()
        # Whose queue it is, handed in: the music's unless told otherwise, so
        # the videos played in the window are drawn by the same list.
        self.assertIn("property var player: Audio", shared)
        self.assertIn("player.moveInQueue", shared)
        self.assertIn("player.removeFromQueue", shared)
        for name in ("MiniPlayer.qml", "NowPlaying.qml", "WatchPage.qml"):
            body = (qml / name).read_text()
            self.assertIn("QueueList {", body, name)
            self.assertNotIn(".moveInQueue", body,
                             f"{name} carries its own copy of the queue")


if __name__ == "__main__":
    unittest.main()


class ALargerPicture(unittest.TestCase):
    def test_a_music_address_is_asked_for_at_a_size_worth_drawing(self) -> None:
        from weave.sources import ytmusic

        small = "https://lh3.googleusercontent.com/abc=w60-h60-l90-rj"
        self.assertEqual(ytmusic.bigger(small),
                         "https://lh3.googleusercontent.com/abc=w544-h544-l90-rj")

    def test_an_ordinary_video_thumbnail_is_left_alone(self) -> None:
        from weave.sources import ytmusic

        # These carry no size in the address, and rewriting one would be
        # inventing a form the picture service was never asked about.
        plain = "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg?sqp=x&rs=y"
        self.assertEqual(ytmusic.bigger(plain), plain)
        self.assertEqual(ytmusic.bigger(""), "")


class AFreshList(unittest.TestCase):
    def test_putting_a_list_on_says_so_separately(self) -> None:
        # Adding one song raises the queue signal too, so the page cannot tell
        # a fresh list from a longer one by that alone.
        from test_audio import FakeEngine, FakeResolver

        from weave.audio import AudioPlayer
        from weave.config import Config

        told = []
        player = AudioPlayer(Config(raw={}), engine=FakeEngine())
        player._make_resolver = lambda entry: FakeResolver(entry["key"])
        player.queueReplaced.connect(lambda: told.append(True))
        player.play_items([{"key": "k", "title": "One", "artist": "",
                            "thumbnail": "", "live": False,
                            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"}])
        self.assertEqual(told, [True])
        player.add_item({"key": "k2", "title": "Two", "artist": "",
                         "thumbnail": "", "live": False,
                         "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb"})
        self.assertEqual(told, [True], "adding a song read as a fresh list")


def _opening_brace(source: str, at: int) -> int:
    """Where the dict enclosing this position opens, or -1 outside one."""
    depth = 0
    for index in range(at - 1, -1, -1):
        letter = source[index]
        if letter == "}":
            depth += 1
        elif letter == "{":
            if depth == 0:
                return index
            depth -= 1
    return -1


class EveryQueueEntryCarriesItsArtist(unittest.TestCase):
    """A name is pressable only where the entry behind it carries an address.

    This is a guard rather than one case, because the fault has been the same
    twice: the entries handed to the player are built in several places, and a
    builder that forgets the field leaves the name dead in the bar and in the
    queue while looking exactly like every other name. Nothing in the window
    can tell the difference, so it is caught here instead.
    """

    def test_no_builder_forgets_it(self) -> None:
        source = (Path(__file__).resolve().parent.parent
                  / "weave" / "ui" / "bridge.py").read_text()
        # Every entry handed to the player has an address built this way, which
        # is what makes it findable without parsing the whole file.
        marker = 'ids.watch_url("youtube"'
        missing = []
        at = source.find(marker)
        while at >= 0:
            # The dict this address is written inside, found by walking back
            # over balanced braces. The nearest brace of any kind is not the
            # same thing: an address passed as an argument rather than built
            # into a dict has no dict around it at all, and reading back to
            # the last brace reached into whatever method happened to sit
            # above it and read a builder there instead. A handoff written
            # exactly that way is what showed it.
            start = _opening_brace(source, at)
            if start >= 0:
                entry = source[start:at + 200]
                if '"key"' in entry and '"artistId"' not in entry:
                    missing.append(entry.strip().splitlines()[0].strip())
            at = source.find(marker, at + 1)
        self.assertEqual(missing, [], "a queue entry was built with no artist address")


class WhatTheWindowActuallyReceives(unittest.TestCase):
    """A field can be carried faithfully the whole way down and still never
    arrive, because the properties the window reads rebuild each row from a
    fixed set of fields. Anything left out of that set is dropped there, with
    nothing upstream able to tell. That is what kept every name in the queue
    dead while the entries behind them carried the address perfectly well.
    """

    def player(self):
        from test_audio import FakeEngine, FakeResolver

        from weave.audio import AudioPlayer
        from weave.config import Config

        one = AudioPlayer(Config(raw={}), engine=FakeEngine())
        one._make_resolver = lambda entry: FakeResolver(entry["key"])
        return one

    def test_the_queue_hands_over_the_artist_address(self) -> None:
        player = self.player()
        player.play_items([{
            "key": "yt:a", "title": "One", "artist": "Somebody", "thumbnail": "",
            "artistId": "UC" + "a" * 22, "live": False,
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"}])
        rows = player.queue
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("artistId"), "UC" + "a" * 22,
                         "the queue rebuilt the row without the address")

    def test_the_playing_track_hands_it_over_too(self) -> None:
        player = self.player()
        player.play_items([{
            "key": "yt:a", "title": "One", "artist": "Somebody", "thumbnail": "",
            "artistId": "UC" + "b" * 22, "live": False,
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"}])
        self.assertEqual(player.track.get("artistId"), "UC" + "b" * 22)

    def test_the_queue_hands_over_what_its_rows_show(self) -> None:
        # The big rows show a length, and a right press on one needs the key;
        # a video queued from the recommendations names its channel instead of
        # an artist.
        player = self.player()
        player.play_items([
            {"key": "yt:a", "title": "One", "artist": "A channel", "thumbnail": "",
             "artistId": "", "channelId": "UC" + "c" * 22, "duration_s": 201,
             "live": False, "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"},
            {"key": "yt:b", "title": "Two", "artist": "Somebody", "thumbnail": "",
             "artistId": "UC" + "a" * 22, "duration": "4:00",
             "live": False, "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb"}])
        rows = player.queue
        self.assertEqual([row["key"] for row in rows], ["yt:a", "yt:b"])
        self.assertEqual([row["duration"] for row in rows], ["3:21", "4:00"])
        self.assertEqual([row["channelId"] for row in rows], ["UC" + "c" * 22, ""])

    def test_an_entry_without_one_is_not_invented(self) -> None:
        player = self.player()
        player.play_items([{
            "key": "yt:a", "title": "One", "artist": "Somebody", "thumbnail": "",
            "live": False, "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"}])
        self.assertEqual(player.queue[0].get("artistId"), "")


class APressIsHeardAtOnce(unittest.TestCase):
    """Fetching a station takes two to three seconds, measured. Waiting for it
    before anything appeared meant a press did nothing visible for that whole
    time: no bar, no song, no sign it had been heard."""

    def player(self):
        from test_audio import FakeEngine, FakeResolver

        from weave.audio import AudioPlayer
        from weave.config import Config

        one = AudioPlayer(Config(raw={}), engine=FakeEngine())
        one._make_resolver = lambda entry: FakeResolver(entry["key"])
        return one

    def song(self, i):
        return {"key": f"yt:k{i}", "videoId": f"vid{i:08d}", "title": f"Song {i}",
                "artist": "Somebody", "album": "", "duration": "3:00",
                "thumbnail": "", "artistId": ""}

    def bridge_for(self, audio):
        bridge = Bridge.__new__(Bridge)
        QObject.__init__(bridge)
        bridge._audio = audio
        # The videos played in the window, which a hand-built bridge has none of.
        bridge._video = None
        bridge._searching = True
        bridge._station_seed = ""
        bridge.musicChanged = Recorder()
        return bridge

    def test_the_song_starts_before_the_station_is_asked_for(self) -> None:
        audio = self.player()
        bridge = self.bridge_for(audio)
        bridge._station = None
        bridge._set_status = lambda *_a, **_k: None
        bridge._launch = lambda worker: True
        bridge._cfg = None
        Bridge._play_station(bridge, "vid00000001", "Song 1",
                             {"title": "Song 1", "subtitle": "Somebody",
                              "thumbnail": "", "artistId": ""})
        self.assertTrue(audio.hasQueue, "the press was silent until the station came")
        self.assertEqual(audio.track["key"], "yt:vid00000001")

    def test_the_rest_joins_behind_it_rather_than_replacing_it(self) -> None:
        audio = self.player()
        bridge = self.bridge_for(audio)
        seed = {"key": "yt:vid00000001", "title": "Song 1", "artist": "",
                "thumbnail": "", "live": False,
                "url": "https://www.youtube.com/watch?v=vid00000001"}
        audio.play_items([seed])
        bridge._station_seed = "yt:vid00000001"
        rows = [{"key": "yt:vid00000001", "videoId": "vid00000001", "title": "Song 1",
                 "artist": "", "album": "", "duration": "", "thumbnail": "",
                 "artistId": ""},
                self.song(2), self.song(3)]
        Bridge._on_station(bridge, rows)
        self.assertEqual(len(audio.queue), 3, "the station did not join the queue")
        self.assertEqual(audio.track["key"], "yt:vid00000001",
                         "the song restarted when the rest arrived")

    def test_a_station_nobody_is_waiting_on_replaces_the_queue(self) -> None:
        # The press may have been overtaken, and then the station is just a
        # list to play rather than something to append to.
        audio = self.player()
        bridge = self.bridge_for(audio)
        bridge._station_seed = "yt:somethingelse"
        Bridge._on_station(bridge, [self.song(2), self.song(3)])
        self.assertEqual(len(audio.queue), 2)

    def test_extending_does_not_restart_what_is_playing(self) -> None:
        audio = self.player()
        audio.play_items([{"key": "yt:a", "title": "One", "artist": "",
                           "thumbnail": "", "live": False,
                           "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"}])
        was = audio.track["key"]
        audio.extend([{"key": "yt:b", "title": "Two", "artist": "", "thumbnail": "",
                       "live": False,
                       "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb"}])
        self.assertEqual(audio.track["key"], was)
        self.assertEqual(len(audio.queue), 2)
