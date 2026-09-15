"""The Now playing page: the ways in and out, and what is beside the song.

The page itself is verified by driving the window and looking at the picture.
What is here is the part that has no picture, which is when the page opens at
all, what closing it does to the view you were on, and what a new song does to
everything drawn beside it.
"""

import unittest
from pathlib import Path

from PySide6.QtCore import QObject

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
    bridge._view_kind = view
    bridge._nav = FakeNav(has_previous)
    bridge._now_side = None
    bridge._now_detail = None
    bridge._now_words = {}
    bridge._now_related = []
    bridge._now_comments = []
    bridge._now_threads = 5
    bridge._now_busy = ""
    bridge._now_ids = {}
    bridge.nowChanged = Recorder()
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
        bridge._now_related = [{"title": "a"}]
        bridge._now_comments = [{"text": "a"}]
        bridge._now_threads = 15
        bridge._now_busy = "words"
        Bridge._forget_now(bridge)
        self.assertEqual(bridge._now_words, {})
        self.assertEqual(bridge._now_related, [])
        self.assertEqual(bridge._now_comments, [])
        self.assertEqual(bridge._now_threads, 5)
        self.assertEqual(bridge._now_busy, "")
        self.assertTrue(bridge.nowChanged.count)

    def test_the_two_addresses_are_kept_so_the_other_tab_costs_nothing(self) -> None:
        # One answer carries the tracks, the address of the words and the
        # address of what is like the song. Asking again for either would be a
        # second request for something already in hand.
        bridge = bridge_with(audio=FakeAudio())
        Bridge._on_now_side(bridge, {
            "what": SongSide.WORDS, "videoId": "a", "wordsId": "W", "likeId": "L",
            "text": "the words", "source": "somewhere", "tracks": [],
        })
        self.assertEqual(bridge._now_ids["a"], ("W", "L"))
        self.assertEqual(bridge._now_words["source"], "somewhere")
        self.assertTrue(bridge._now_words["read"])
        self.assertEqual(bridge._now_busy, "")

    def test_a_song_with_no_words_is_an_answer_and_not_a_failure(self) -> None:
        bridge = bridge_with(audio=FakeAudio())
        Bridge._on_now_side(bridge, {
            "what": SongSide.WORDS, "videoId": "a", "wordsId": "", "likeId": "",
            "text": "", "source": "", "tracks": [],
        })
        # Read, and empty. The page needs both facts to tell "none of them"
        # from "not asked yet".
        self.assertTrue(bridge._now_words["read"])
        self.assertEqual(bridge._now_words["text"], "")

    def test_nothing_is_asked_for_twice(self) -> None:
        bridge = bridge_with(audio=FakeAudio())
        bridge._now_words = {"text": "held", "read": True}
        started = []
        bridge._launch = lambda worker: started.append(worker) or True
        Bridge.readNowSide(bridge, SongSide.WORDS)
        self.assertEqual(started, [], "the words were asked for a second time")

    def test_a_song_with_no_video_id_asks_for_nothing(self) -> None:
        bridge = bridge_with(audio=FakeAudio(track={"key": "yt:a"}))
        started = []
        bridge._launch = lambda worker: started.append(worker) or True
        Bridge.readNowSide(bridge, SongSide.WORDS)
        self.assertEqual(started, [])


class TheRelatedRows(unittest.TestCase):
    def test_play_next_and_the_end_of_the_queue_are_different_places(self) -> None:
        audio = FakeAudio()
        bridge = bridge_with(audio=audio)
        bridge._now_related = [
            {"key": "yt:b", "videoId": "b", "title": "One", "artist": "Somebody",
             "thumbnail": ""},
        ]
        bridge._set_status = lambda *_a, **_k: None
        Bridge.queueNowRelated(bridge, 0, True)
        Bridge.queueNowRelated(bridge, 0, False)
        self.assertEqual([next_ for _item, next_ in audio.added], [True, False])
        # The player is handed an address, not a row, whichever list the row
        # came from.
        self.assertTrue(audio.added[0][0]["url"].endswith("b"))

    def test_a_row_that_is_not_there_does_nothing(self) -> None:
        audio = FakeAudio()
        bridge = bridge_with(audio=audio)
        bridge._now_related = []
        Bridge.queueNowRelated(bridge, 3, True)
        self.assertEqual(audio.added, [])


class OneQueueDrawnOneWay(unittest.TestCase):
    def test_both_places_use_the_shared_list(self) -> None:
        # The bar's popup and the page show the same queue with the same
        # handles on it. Two copies of that drifted apart the moment either
        # grew a feature, so there is only the one component.
        qml = Path(__file__).resolve().parent.parent / "weave" / "qml"
        shared = (qml / "QueueList.qml").read_text()
        self.assertIn("Audio.moveInQueue", shared)
        self.assertIn("Audio.removeFromQueue", shared)
        for name in ("MiniPlayer.qml", "NowPlaying.qml"):
            body = (qml / name).read_text()
            self.assertIn("QueueList {", body, name)
            self.assertNotIn("Audio.moveInQueue", body,
                             f"{name} carries its own copy of the queue")


if __name__ == "__main__":
    unittest.main()
