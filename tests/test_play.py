"""Handing a video to mpv.

An announced stream sits in the feed like any other video but has nothing
mpv can open yet, so pressing it must never reach the player. This pins that
refusal down, and that a video which is not announced still plays normally.

A live one is asked about first. A card says live because something said so
when it was last asked, and a broadcast that ended hours ago goes on saying it
until the next round reaches that video, which leaves mpv with nothing to play
and the press looking like it did nothing.
"""

import unittest


def upcoming_row(key="yt:aaaaaaaaaaa"):
    return {
        "key": key, "title": "An announced stream", "url": "https://example/watch",
        "isLive": False, "isUpcoming": True, "scheduledText": "Starts in 1 hour",
    }


def live_row(key="yt:ccccccccccc"):
    return {
        "key": key, "title": "A broadcast", "url": "https://example/watch",
        "isLive": True, "isUpcoming": False, "scheduledText": "",
    }


def twitch_row(key="twitch:somebody"):
    return {
        "key": key, "title": "Somebody", "url": "https://www.twitch.tv/somebody",
        "isLive": True, "isUpcoming": False, "scheduledText": "",
    }


def ordinary_row(key="yt:bbbbbbbbbbb"):
    return {
        "key": key, "title": "A video", "url": "https://example/watch",
        "isLive": False, "isUpcoming": False, "scheduledText": "",
    }


class Model:
    def __init__(self, rows):
        self._rows = {row["key"]: row for row in rows}

    def row_for_key(self, key):
        return self._rows.get(key)


class Music:
    def __init__(self):
        self.paused = 0

    def pause_for_video(self):
        self.paused += 1


class Player:
    def __init__(self):
        self.calls = []

    def play(self, url, twitch_login=None, live=False):
        self.calls.append((url, twitch_login, live))
        return True


def make_bridge(rows):
    from weave.ui.bridge import Bridge

    bridge = Bridge.__new__(Bridge)
    bridge._model = Model(rows)
    bridge._player = Player()
    bridge._view_kind = "all"
    bridge._view_playlist = ""
    bridge._set_status = lambda *_a, **_k: None
    bridge._set_notice = lambda *_a, **_k: None
    # What the card that was pressed is told to say. Stubbed like the notice,
    # since the timer behind it belongs to a real bridge.
    bridge.started = []
    bridge._set_starting = lambda key, **_k: bridge.started.append(key)
    bridge.opened = []
    bridge.openDetail = bridge.opened.append
    # The question a live press asks. Nothing here runs a real one, so what is
    # recorded is that it was asked and what the press did with the answer.
    bridge._stream_check = None
    bridge._pending_play = None
    # The question a press on a card marked for members asks. Recorded, not
    # asked, like the live one.
    bridge._members_check = None
    bridge._pending_members = None
    bridge._members_cleared = ""
    bridge._web_results = []
    bridge.launched = []
    bridge._launch = lambda worker: bridge.launched.append(worker) or True
    bridge.card_notes = []
    bridge._card_note_key = ""
    bridge._set_card_note = lambda key, text, **_k: (
        bridge.card_notes.append((key, text)), setattr(bridge, "_card_note_key", key))
    # The music, which steps aside for anything handed to mpv. Recorded here
    # rather than played.
    bridge._audio = Music()
    bridge.asked = []
    bridge._db = None
    bridge._cfg = None
    bridge.reloaded = []
    bridge.reload = lambda: bridge.reloaded.append(True)
    bridge.liveChanged = Signal()
    return bridge


class Signal:
    """Enough of one to be emitted. A bridge built with __new__ has no Qt
    object behind it, so a real signal cannot be."""

    def __init__(self):
        self.count = 0

    def emit(self, *_a):
        self.count += 1


def asking_bridge(rows):
    """A bridge whose live check records the question instead of asking it."""
    from weave.ui.bridge import Bridge

    bridge = make_bridge(rows)
    bridge._ask_whether_it_is_still_live = (
        lambda key, url, title: bool(bridge.asked.append((key, url, title)) or True))
    bridge.play = lambda key: Bridge.play(bridge, key)
    return bridge


class PlayRefusesAnAnnouncedVideo(unittest.TestCase):
    def test_an_upcoming_video_never_reaches_mpv(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([upcoming_row()])
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge._player.calls, [],
                          "an announced stream was handed to mpv, which cannot open it")

    def test_it_opens_the_detail_panel_instead(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([upcoming_row()])
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.opened, ["yt:aaaaaaaaaaa"])

    def test_the_music_steps_aside_the_moment_it_is_handed_over(self):
        """Said here rather than waited for. The watcher says it too, when it
        sees mpv open a file, but a broadcast is resolved before mpv opens
        anything and one that has already finished opens nothing at all."""
        from weave.ui.bridge import Bridge

        bridge = make_bridge([ordinary_row()])
        Bridge.play(bridge, "yt:bbbbbbbbbbb")
        self.assertEqual(bridge._audio.paused, 1)

    def test_the_music_stays_where_it_is_when_nothing_was_handed_over(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([upcoming_row()])
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge._audio.paused, 0)

    def test_an_ordinary_video_still_plays(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([ordinary_row()])
        Bridge.play(bridge, "yt:bbbbbbbbbbb")
        self.assertEqual(bridge._player.calls, [("https://example/watch", None, False)])
        self.assertEqual(bridge.opened, [])

    def test_the_card_that_was_pressed_says_it_is_starting(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([ordinary_row()])
        Bridge.play(bridge, "yt:bbbbbbbbbbb")
        self.assertEqual(bridge.started, ["yt:bbbbbbbbbbb"])

    def test_an_announced_one_says_nothing_since_nothing_starts(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([upcoming_row()])
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.started, [])

    def test_a_live_one_is_asked_about_before_mpv_is_given_it(self):
        from weave.ui.bridge import Bridge

        bridge = asking_bridge([live_row()])
        Bridge.play(bridge, "yt:ccccccccccc")
        self.assertEqual(bridge.asked,
                         [("yt:ccccccccccc", "https://example/watch", "A broadcast")])
        self.assertEqual(bridge._player.calls, [],
                          "the address went to mpv before the answer came back")

    def test_a_twitch_channel_is_never_asked(self):
        """Twitch says who is live through its own interface every ninety
        seconds, and the check is a yt-dlp call about a YouTube video."""
        from weave.ui.bridge import Bridge

        bridge = asking_bridge([twitch_row()])
        Bridge.play(bridge, "twitch:somebody")
        self.assertEqual(bridge.asked, [])
        self.assertEqual(bridge._player.calls,
                         [("https://www.twitch.tv/somebody", "somebody", True)])

    def test_an_ordinary_video_is_never_asked_either(self):
        from weave.ui.bridge import Bridge

        bridge = asking_bridge([ordinary_row()])
        Bridge.play(bridge, "yt:bbbbbbbbbbb")
        self.assertEqual(bridge.asked, [])
        self.assertEqual(len(bridge._player.calls), 1)


    def test_an_unknown_key_does_nothing(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([])
        Bridge.play(bridge, "yt:missing")
        self.assertEqual(bridge._player.calls, [])
        self.assertEqual(bridge.opened, [])


class WhatTheAnswerDoes(unittest.TestCase):
    def bridge(self):
        made = make_bridge([live_row()])
        made._pending_play = ("yt:ccccccccccc", "https://example/watch", "A broadcast")
        return made

    def test_still_live_is_handed_over(self):
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge._on_stream_checked(bridge, "yt:ccccccccccc", True, False)
        self.assertEqual(bridge._player.calls, [("https://example/watch", None, True)])
        self.assertEqual(bridge.reloaded, [])

    def test_one_that_has_ended_is_not_played_and_the_card_is_read_again(self):
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge._on_stream_checked(bridge, "yt:ccccccccccc", False, False)
        self.assertEqual(bridge._player.calls, [])
        self.assertEqual(bridge.reloaded, [True])
        self.assertEqual(bridge.started, [""])

    def test_one_that_has_not_started_is_not_played_either(self):
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge._on_stream_checked(bridge, "yt:ccccccccccc", False, True)
        self.assertEqual(bridge._player.calls, [])
        # Nothing about the row changed, so there is nothing to read again.
        self.assertEqual(bridge.reloaded, [])

    def test_an_answer_about_something_else_is_dropped(self):
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge._on_stream_checked(bridge, "yt:somethingels", True, False)
        self.assertEqual(bridge._player.calls, [])

    def test_a_question_that_could_not_be_asked_plays_anyway(self):
        """A check is a safety net rather than a gate. Refusing to play
        because a question about it went unanswered would make a network
        hiccup look like a broken press."""
        from weave.ui.bridge import Bridge

        bridge = self.bridge()
        Bridge._on_stream_check_failed(bridge, "yt:ccccccccccc", "yt-dlp said: no")
        self.assertEqual(bridge._player.calls, [("https://example/watch", None, True)])

if __name__ == "__main__":
    unittest.main()
