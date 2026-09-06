"""Editing the queue.

The queue holds the whole play order, what has been heard as well as what is
still to come, so anything in it can be moved or taken out. A song already
heard, moved ahead of what is still to come, is heard again when it is
reached, and that is the point of being allowed to move it.
"""

import unittest


def player(titles="abcdef", at=0, order=None, shuffle=False):
    from weave.audio import AudioPlayer

    class Quiet:
        def emit(self, *_a):
            pass

    made = AudioPlayer.__new__(AudioPlayer)
    made._queue = [{"title": c, "key": f"yt:{c}", "url": "u"} for c in titles]
    made._order = list(order) if order else list(range(len(titles)))
    made._at = at
    made._idle = True
    made._shuffle = shuffle
    made._repeat_mode = 0
    made.queueChanged = Quiet()
    made.trackChanged = Quiet()
    made.stateChanged = Quiet()
    return made


def shown(made):
    return [made._queue[i]["title"] for i in made._order]


class MovingASong(unittest.TestCase):
    def test_a_song_still_to_come_can_be_brought_forward(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=0)
        AudioPlayer.moveInQueue(made, 4, 1)
        self.assertEqual(shown(made), ["a", "e", "b", "c", "d", "f"])
        self.assertEqual(made._queue[made._at]["title"], "a")

    def test_a_song_already_heard_can_be_put_back_ahead(self) -> None:
        """Which is what makes hearing it again possible."""
        from weave.audio import AudioPlayer

        made = player(at=3)
        AudioPlayer.moveInQueue(made, 0, 5)
        self.assertEqual(shown(made), ["b", "c", "d", "e", "f", "a"])
        self.assertEqual(made._queue[made._at]["title"], "d")

    def test_what_is_playing_does_not_change_because_of_a_move(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=2)
        AudioPlayer.moveInQueue(made, 5, 0)
        self.assertEqual(made._queue[made._at]["title"], "c")

    def test_the_next_song_follows_the_new_order(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=0)
        AudioPlayer.moveInQueue(made, 5, 1)
        self.assertEqual(made._queue[made._next_index()]["title"], "f")

    def test_it_holds_under_shuffle_because_places_are_places_shown(self) -> None:
        from weave.audio import AudioPlayer

        made = player(order=[3, 1, 4, 0, 5, 2], at=1, shuffle=True)
        self.assertEqual(shown(made), ["d", "b", "e", "a", "f", "c"])
        AudioPlayer.moveInQueue(made, 0, 5)
        self.assertEqual(shown(made), ["b", "e", "a", "f", "c", "d"])

    def test_a_move_to_where_it_already_is_changes_nothing(self) -> None:
        from weave.audio import AudioPlayer

        made = player()
        AudioPlayer.moveInQueue(made, 2, 2)
        self.assertEqual(shown(made), list("abcdef"))

    def test_a_place_that_is_not_there_is_refused(self) -> None:
        from weave.audio import AudioPlayer

        made = player()
        AudioPlayer.moveInQueue(made, 9, 0)
        AudioPlayer.moveInQueue(made, 0, 9)
        AudioPlayer.moveInQueue(made, -1, 0)
        self.assertEqual(shown(made), list("abcdef"))


class TakingASongOut(unittest.TestCase):
    def test_one_still_to_come_just_goes(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=0)
        AudioPlayer.removeFromQueue(made, 3)
        self.assertEqual(shown(made), ["a", "b", "c", "e", "f"])
        self.assertEqual(made._queue[made._at]["title"], "a")

    def test_one_already_heard_goes_without_moving_what_plays(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=3)
        AudioPlayer.removeFromQueue(made, 0)
        self.assertEqual(shown(made), ["b", "c", "d", "e", "f"])
        self.assertEqual(made._queue[made._at]["title"], "d")

    def test_taking_out_the_one_playing_moves_on(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=2)
        made.started = []
        made._forget_recovery = lambda: None
        made._start_current = lambda: made.started.append(
            made._queue[made._at]["title"])
        AudioPlayer.removeFromQueue(made, 2)
        self.assertEqual(shown(made), ["a", "b", "d", "e", "f"])
        self.assertEqual(made.started, ["d"])

    def test_taking_out_the_last_one_playing_stops(self) -> None:
        from weave.audio import AudioPlayer

        made = player(titles="a", at=0)
        made.stopped = []
        made.stop = lambda: made.stopped.append(True)
        AudioPlayer.removeFromQueue(made, 0)
        self.assertEqual(made.stopped, [True])

    def test_a_row_that_is_not_there_is_refused(self) -> None:
        from weave.audio import AudioPlayer

        made = player()
        AudioPlayer.removeFromQueue(made, 9)
        AudioPlayer.removeFromQueue(made, -1)
        self.assertEqual(shown(made), list("abcdef"))

    def test_the_play_order_keeps_pointing_at_the_right_songs(self) -> None:
        """Rows are addressed by where they sit in the queue, so taking one
        out has to shift every later index down or the order names the wrong
        songs."""
        from weave.audio import AudioPlayer

        made = player(order=[5, 0, 3, 1, 4, 2], at=5, shuffle=True)
        AudioPlayer.removeFromQueue(made, 0)
        self.assertEqual(shown(made), ["f", "d", "b", "e", "c"])
        self.assertEqual(made._queue[made._at]["title"], "f")


class AddingOneMoreSong(unittest.TestCase):
    """One song, either behind everything or straight after this one.

    Neither starts anything playing, because the point is to decide what
    happens after what is playing now. An empty queue is the exception, since
    adding to nothing and hearing nothing is not what was asked for.
    """

    def song(self, title="z"):
        return {"key": f"yt:{title}", "title": title, "artist": "An artist",
                "thumbnail": "", "live": False, "url": "https://example/watch"}

    def test_it_goes_behind_everything_by_default(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=0)
        made._prepare_next = lambda: None
        self.assertTrue(AudioPlayer.add_item(made, self.song()))
        self.assertEqual(shown(made), ["a", "b", "c", "d", "e", "f", "z"])

    def test_played_next_goes_straight_after_this_one(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=2)
        made._prepare_next = lambda: None
        AudioPlayer.add_item(made, self.song(), play_next=True)
        self.assertEqual(shown(made), ["a", "b", "c", "z", "d", "e", "f"])
        self.assertEqual(made._queue[made._next_index()]["title"], "z")

    def test_nothing_starts_playing_because_of_it(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=2)
        made._prepare_next = lambda: None
        made.started = []
        made._start_current = lambda: made.started.append(True)
        AudioPlayer.add_item(made, self.song())
        AudioPlayer.add_item(made, self.song("y"), play_next=True)
        self.assertEqual(made.started, [])
        self.assertEqual(made._queue[made._at]["title"], "c")

    def test_it_holds_under_shuffle(self) -> None:
        from weave.audio import AudioPlayer

        made = player(order=[3, 1, 4, 0, 5, 2], at=1, shuffle=True)
        made._prepare_next = lambda: None
        AudioPlayer.add_item(made, self.song(), play_next=True)
        self.assertEqual(shown(made), ["d", "b", "z", "e", "a", "f", "c"])

    def test_an_empty_queue_simply_starts_it(self) -> None:
        from weave.audio import AudioPlayer

        made = player(titles="", at=-1)
        made.given = []
        made.play_items = lambda items, start=0: made.given.append(
            [i["title"] for i in items])
        AudioPlayer.add_item(made, self.song())
        self.assertEqual(made.given, [["z"]])

    def test_a_song_with_no_address_is_refused(self) -> None:
        from weave.audio import AudioPlayer

        made = player(at=0)
        self.assertFalse(AudioPlayer.add_item(made, {"title": "no address"}))
        self.assertEqual(shown(made), list("abcdef"))


class TheBridgeQueuesOne(unittest.TestCase):
    def bridge(self):
        from weave.ui.bridge import Bridge

        class Player:
            def __init__(self):
                self.taken = []

            def add_item(self, item, play_next=False):
                self.taken.append((item["title"], play_next))
                return True

        bridge = Bridge.__new__(Bridge)
        bridge._audio = Player()
        bridge._shelves = [{"title": "A section", "kind": "songs", "items": [
            {"title": "A song", "subtitle": "An artist", "thumbnail": "",
             "videoId": "aaaaaaaaaaa", "playlistId": "RDAMVMaaa"},
            {"title": "A list", "subtitle": "", "thumbnail": "",
             "videoId": "", "playlistId": "PL1"}]}]
        bridge._results = [{"key": "yt:bbbbbbbbbbb", "videoId": "bbbbbbbbbbb",
                            "title": "A row", "artist": "An artist",
                            "thumbnail": ""}]
        bridge._get_shelves = lambda: bridge._shelves
        bridge.notices = []
        bridge._set_notice = lambda *a, **k: bridge.notices.append(a[0])
        bridge._set_status = lambda *a, **k: None
        return bridge

    def test_a_tile_can_be_queued_and_played_next(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge.queueShelfItem(bridge, 0, 0, False)
        Bridge.queueShelfItem(bridge, 0, 0, True)
        self.assertEqual(bridge._audio.taken,
                         [("A song", False), ("A song", True)])
        self.assertEqual(bridge.notices,
                         ["Added to the queue", "Playing it next"])

    def test_a_row_can_be_queued(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge.queueResult(bridge, 0, True)
        self.assertEqual(bridge._audio.taken, [("A row", True)])

    def test_a_whole_list_is_not_one_song(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge.queueShelfItem(bridge, 0, 1, False)
        self.assertEqual(bridge._audio.taken, [])
        self.assertIn("Only a song", bridge.notices[-1])

    def test_something_that_is_not_there_is_no_error(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge.queueShelfItem(bridge, 9, 9, False)
        Bridge.queueResult(bridge, 9, False)
        self.assertEqual(bridge._audio.taken, [])


if __name__ == "__main__":
    unittest.main()
