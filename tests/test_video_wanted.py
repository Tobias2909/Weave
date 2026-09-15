"""When a song gets a picture, and when it is told why it does not.

Nothing is fetched and nothing decoded until something is open to show it,
measured at 0 KiB and 0.2 % of a core against 2411 kbit/s and 9.2 % with it on.
So the rules about when to ask are the whole cost of the feature.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_audio import FakeEngine, FakeResolver  # noqa: E402

from weave.audio import VIDEO_MAX_S, AudioPlayer
from weave.config import Config


class FakeVideoResolver:
    """Never starts, so no test here reaches for yt-dlp. Whether a picture was
    asked for is the thing being checked, not the asking itself."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.started = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.started = False

    def isRunning(self) -> bool:
        return self.started

    class _Wire:
        @staticmethod
        def connect(_slot) -> None:
            pass

    resolved = _Wire()
    failed = _Wire()


def player() -> AudioPlayer:
    one = AudioPlayer(Config(raw={}), engine=FakeEngine())
    one._make_resolver = lambda entry: FakeResolver(entry["key"])
    one._make_video_resolver = lambda entry: FakeVideoResolver(entry["key"])
    return one


def song(key="yt:a", **extra) -> dict:
    row = {"key": key, "title": "One", "artist": "Somebody", "thumbnail": "",
           "live": False, "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"}
    row.update(extra)
    return row


class WhenNobodyIsLooking(unittest.TestCase):
    def test_nothing_is_asked_for(self) -> None:
        one = player()
        one.play_items([song()])
        one._video_resolver = None
        self.assertFalse(one.videoWanted)
        self.assertIsNone(one._video_resolver, "a picture was fetched for nobody")

    def test_closing_the_page_says_nothing_to_the_player(self) -> None:
        # The picture keeps running behind the closed page, so opening it
        # again within the song shows the video at once rather than the
        # artwork for the seconds a frame takes to exist again.
        one = player()
        one.play_items([song()])
        one._video_wanted = True
        one._engine.calls.clear()
        one.setVideoWanted(False)
        self.assertFalse(one.videoWanted)
        self.assertEqual(one._engine.calls, [], "closing the page reached for the player")

    def test_the_next_song_is_where_it_actually_stops(self) -> None:
        # Which is where the fetching and the decoding end, without a command
        # against a song already playing.
        one = player()
        one.play_items([song(duration_s=200)])
        one._video_wanted = True
        one.setVideoWanted(False)
        one._engine.calls.clear()
        one.play_items([song(key="yt:b", duration_s=200)])
        self.assertNotIn(("add_video", "https://example.invalid/v"),
                         one._engine.calls)


class WhatDeservesAPicture(unittest.TestCase):
    def test_a_long_one_is_refused_and_says_why(self) -> None:
        # An hour of pictures nobody looks at, for a mix or a talk played as
        # music. The artwork stays and the reason is on the page.
        one = player()
        one.play_items([song(duration_s=VIDEO_MAX_S + 1)])
        one.setVideoWanted(True)
        self.assertIn("minutes", one.videoNote)
        self.assertIsNone(one._video_resolver, "a refused picture was fetched anyway")

    def test_a_short_one_is_fetched(self) -> None:
        one = player()
        one.play_items([song(duration_s=200)])
        one.setVideoWanted(True)
        self.assertEqual(one.videoNote, "")
        self.assertIsNotNone(one._video_resolver)

    def test_a_broadcast_is_exempt_from_the_length_rule(self) -> None:
        # It reports no length worth comparing, and its picture is being
        # fetched whatever happens: a livestream is offered in no sound only
        # shape at all.
        one = player()
        one.play_items([song(live=True, duration_s=99999)])
        one.setVideoWanted(True)
        self.assertEqual(one.videoNote, "")


class OnceTheAddressIsKnown(unittest.TestCase):
    def test_it_is_attached_to_what_is_playing(self) -> None:
        one = player()
        one.play_items([song()])
        one._video_wanted = True
        one._on_video_resolved("yt:a", "https://example.invalid/v")
        self.assertIn(("add_video", "https://example.invalid/v"), one._engine.calls)

    def test_an_answer_for_a_song_already_left_is_kept_not_shown(self) -> None:
        one = player()
        one.play_items([song()])
        one._video_wanted = True
        one._on_video_resolved("yt:somethingelse", "https://example.invalid/old")
        self.assertNotIn(("add_video", "https://example.invalid/old"),
                         one._engine.calls)
        # Kept all the same, since going back to it should cost nothing.
        self.assertEqual(one._video_addresses["yt:somethingelse"],
                         "https://example.invalid/old")

    def test_a_known_address_is_not_fetched_twice(self) -> None:
        one = player()
        one.play_items([song(duration_s=200)])
        one._video_addresses["yt:a"] = "https://example.invalid/v"
        one.setVideoWanted(True)
        self.assertIsNone(one._video_resolver, "a picture already in hand was fetched")
        self.assertIn(("add_video", "https://example.invalid/v"), one._engine.calls)

    def test_a_song_with_none_says_so(self) -> None:
        one = player()
        one.play_items([song()])
        one._video_wanted = True
        one._on_video_failed("yt:a", "this one has no picture")
        self.assertEqual(one.videoNote, "this one has no picture")


class WhetherAFrameExists(unittest.TestCase):
    def test_the_artwork_stays_until_one_does(self) -> None:
        one = player()
        self.assertFalse(one.videoShowing)
        one._engine.videoChanged.emit(True)
        self.assertTrue(one.videoShowing)
        one._engine.videoChanged.emit(False)
        self.assertFalse(one.videoShowing)


if __name__ == "__main__":
    unittest.main()


class TheCommandItself(unittest.TestCase):
    """Run for real, with only the subprocess stubbed.

    Every other test here replaces the whole resolver, which is what let a
    wrong call sit in it unexecuted: the command line was never built once in
    the entire suite, and the first thing to run it was a person opening the
    page.
    """

    def run_it(self):
        from unittest import mock

        from weave import audio

        class Result:
            stdout = "https://example.invalid/video\n"
            stderr = ""
            returncode = 0

        with mock.patch.object(audio, "run_process", return_value=Result()) as ran:
            found = audio.resolve_video(Config(raw={}),
                                        "https://www.youtube.com/watch?v=x")
        return found, list(ran.call_args[0][0])

    def test_it_asks_yt_dlp_for_a_capped_picture(self) -> None:
        found, command = self.run_it()
        self.assertEqual(found, "https://example.invalid/video")
        self.assertEqual(command[0], "yt-dlp")
        self.assertIn("--get-url", command)
        self.assertIn("-f", command)
        # Capped rather than best. The largest a music video comes in is
        # several times the bytes for a pane a few hundred pixels wide.
        self.assertIn("1080", command[command.index("-f") + 1])

    def test_it_goes_through_the_shared_preparation(self) -> None:
        # Which is what puts the JavaScript runtime on the line. Without it the
        # signed address cannot be worked out and nothing plays at all.
        _found, command = self.run_it()
        self.assertTrue(any("cookies" in part for part in command),
                        "the picture was asked for as a stranger")

    def test_no_address_is_an_empty_answer(self) -> None:
        from unittest import mock

        from weave import audio

        class Nothing:
            stdout = ""
            stderr = "ERROR: Requested format is not available"
            returncode = 1

        with mock.patch.object(audio, "run_process", return_value=Nothing()):
            self.assertEqual(
                audio.resolve_video(Config(raw={}), "https://example.invalid/x"),
                "")
