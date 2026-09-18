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

from weave.audio import (
    STAGE_KEPT,
    STAGE_LOOKING,
    STAGE_OPENING,
    STAGE_SHOWING,
    VIDEO_MAX_S,
    AudioPlayer,
)
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
    # The look ahead sweeps the ones that have ended, so it listens for this.
    finished = _Wire()


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
        self.assertEqual(one._video_addresses.get("yt:somethingelse"),
                         "https://example.invalid/old")

    def test_a_known_address_is_not_fetched_twice(self) -> None:
        one = player()
        one.play_items([song(duration_s=200)])
        one._video_addresses.put("yt:a", "https://example.invalid/v")
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


class TheSongAfterThisOne(unittest.TestCase):
    """The picture for the next song is found while this one is playing.

    The sound has always been done this way, because resolving is the only
    wait in the chain. The picture was not, so every song change showed the
    artwork for the seconds an address takes to find and a frame to arrive,
    however long there had been to do it in.
    """

    def setUp(self):
        self.player = player()
        self.player._queue = [song("yt:a"), song("yt:b"), song("yt:c")]
        self.player._rebuild_order()
        self.player._at = 0
        self.player._idle = False

    def looking_for(self):
        return [r.key for r in self.player._next_video_resolvers if r.isRunning()]

    def test_nothing_is_looked_for_while_no_page_is_open(self):
        self.player._prepare_next()
        self.assertEqual(self.looking_for(), [])

    def test_with_the_page_open_the_next_one_is_looked_for(self):
        self.player.setVideoWanted(True)
        self.player._prepare_next()
        self.assertEqual(self.looking_for(), ["yt:b"])

    def test_opening_the_page_is_itself_the_moment_to_look(self):
        # Rather than waiting for whatever would have called on next.
        self.player.setVideoWanted(True)
        self.assertEqual(self.looking_for(), ["yt:b"])

    def test_one_already_known_is_not_looked_for_again(self):
        self.player._video_addresses.put("yt:b", "https://example/picture")
        self.player.setVideoWanted(True)
        self.assertEqual(self.looking_for(), [])

    def test_nor_is_one_asked_for_twice(self):
        self.player.setVideoWanted(True)
        self.player._prepare_next()
        self.player._prepare_next()
        self.assertEqual(self.looking_for(), ["yt:b"])

    def test_sound_alone_looks_for_nothing(self):
        self.player.setVideoWanted(True)
        self.player.setAudioOnly(True)
        self.player._next_video_resolvers = []
        self.player._prepare_next()
        self.assertEqual(self.looking_for(), [])

    def test_one_that_would_be_refused_a_picture_is_not_looked_for(self):
        """The length rule is the same one the current song is held to."""
        self.player._queue[1] = song("yt:b", duration_s=VIDEO_MAX_S + 60)
        self.player.setVideoWanted(True)
        self.assertEqual(self.looking_for(), [])

    def test_the_end_of_the_queue_has_nothing_after_it(self):
        self.player._at = 2
        self.player.setVideoWanted(True)
        self.assertEqual(self.looking_for(), [])

    def test_what_comes_back_is_kept_for_when_that_song_starts(self):
        """The handler is the one the current song's picture uses. It writes
        the address down and hands it to the player only when it belongs to
        the song playing, which the next one does not yet."""
        self.player.setVideoWanted(True)
        self.player._on_video_resolved("yt:b", "https://example/picture")
        self.assertEqual(self.player._video_addresses.get("yt:b"),
                         "https://example/picture")
        self.assertEqual(self.player._engine.only("add_video"), [])

    def test_and_is_handed_over_the_moment_that_song_is_the_one_playing(self):
        self.player.setVideoWanted(True)
        self.player._on_video_resolved("yt:b", "https://example/picture")
        self.player._engine.calls.clear()
        self.player._at = 1
        self.player._start_video()
        self.assertEqual(self.player._engine.only("add_video"),
                         [("add_video", "https://example/picture")])

    def test_closing_the_page_stops_looking(self):
        self.player.setVideoWanted(True)
        self.assertEqual(self.looking_for(), ["yt:b"])
        self.player.setVideoWanted(False)
        self.assertEqual(self.player._next_video_resolvers, [])


class KeptOnDisk(unittest.TestCase):
    """A song he keeps has its halves on disk, and the player asks for them
    before it looks for an address."""

    def setUp(self):
        self.player = player()
        self.player._queue = [song("yt:a"), song("yt:b")]
        self.player._rebuild_order()
        self.player._at = 0
        self.player._idle = False

    def test_the_sound_is_played_from_the_file(self):
        self.player.local_audio = lambda key: ("/tmp/kept/a.m4a" if key == "yt:a" else "")
        self.player._start_current()
        self.assertEqual(self.player._engine.only("load"),
                         [("load", "/tmp/kept/a.m4a", None)])

    def test_and_nothing_is_resolved_for_it(self):
        self.player.local_audio = lambda key: "/tmp/kept/a.m4a"
        self.player._start_current()
        self.assertFalse(self.player.loading)

    def test_the_song_after_it_is_queued_from_its_file_too(self):
        self.player.local_audio = lambda key: f"/tmp/kept/{key[-1]}.m4a"
        self.player._prepare_next()
        self.assertEqual(self.player._engine.only("append"),
                         [("append", "/tmp/kept/b.m4a")])

    def test_a_broadcast_is_never_read_from_a_file(self):
        """It has no file and no end."""
        self.player._queue = [song("yt:live", live=True)]
        self.player._rebuild_order()
        self.player._at = 0
        asked = []
        self.player.local_audio = lambda key: asked.append(key) or "/tmp/kept/live.m4a"
        self.player._start_current()
        self.assertEqual(asked, [])
        self.assertEqual(self.player._engine.only("load"), [])

    def test_the_picture_is_taken_from_the_file_and_without_a_fade(self):
        self.player.local_video = lambda key: "/tmp/kept/a.webm"
        self.player.setVideoWanted(True)
        self.assertEqual(self.player._engine.only("add_video"),
                         [("add_video", "/tmp/kept/a.webm")])
        self.assertTrue(self.player.videoInstant)

    def test_one_that_has_to_be_found_keeps_its_fade(self):
        self.player.local_video = lambda key: ""
        self.player.setVideoWanted(True)
        self.assertFalse(self.player.videoInstant)


class WhatIsBeingWaitedOn(unittest.TestCase):
    """The line under the button that fills the screen.

    An address has to be found, which is a full extraction and takes seconds,
    the player then has to open that stream, and a frame exists a couple of
    seconds after that. Until this said so there was the artwork sitting
    there, which reads exactly the same whether something is happening or
    nothing is.
    """

    def test_nothing_is_said_while_nothing_is_open_to_show_one(self) -> None:
        one = player()
        one.play_items([song()])
        self.assertEqual(one.videoStage, "")

    def test_looking_for_it_comes_first(self) -> None:
        one = player()
        one.play_items([song()])
        one.setVideoWanted(True)
        self.assertEqual(one.videoStage, STAGE_LOOKING)

    def test_then_opening_it_once_there_is_an_address(self) -> None:
        one = player()
        one.play_items([song()])
        one.setVideoWanted(True)
        one._on_video_resolved("yt:a", "https://example.invalid/v")
        self.assertEqual(one.videoStage, STAGE_OPENING)

    def test_an_address_already_in_hand_is_not_looked_for(self) -> None:
        one = player()
        one.play_items([song()])
        one._video_addresses.put("yt:a", "https://example.invalid/v")
        one.setVideoWanted(True)
        self.assertEqual(one.videoStage, STAGE_OPENING)

    def test_one_kept_on_disk_says_which_it_is(self) -> None:
        one = player()
        one.play_items([song()])
        one.local_video = lambda key: "/somewhere/kept.webm"
        one.setVideoWanted(True)
        self.assertEqual(one.videoStage, STAGE_KEPT)

    def test_and_showing_it_once_a_frame_exists(self) -> None:
        one = player()
        one.play_items([song()])
        one.setVideoWanted(True)
        one._on_video_frame(True)
        self.assertEqual(one.videoStage, STAGE_SHOWING)

    def test_a_song_that_will_never_have_one_says_why_instead(self) -> None:
        """A step that is not being taken is a worse thing to read than the
        reason there will be no picture at all."""
        one = player()
        one.play_items([song(duration_s=VIDEO_MAX_S + 60)])
        one.setVideoWanted(True)
        self.assertEqual(one.videoStage, "")
        self.assertIn("15 minutes", one.videoNote)

    def test_closing_the_page_leaves_nothing_being_waited_on(self) -> None:
        one = player()
        one.play_items([song()])
        one.setVideoWanted(True)
        one.setVideoWanted(False)
        self.assertEqual(one.videoStage, "")

    def test_nor_does_sound_alone(self) -> None:
        one = player()
        one.play_items([song()])
        one.setVideoWanted(True)
        one.setAudioOnly(True)
        self.assertEqual(one.videoStage, "")

    def test_a_new_song_starts_with_nothing_said_about_its_picture(self) -> None:
        one = player()
        one.play_items([song(), song("yt:b")])
        one.setVideoWanted(True)
        one._on_video_frame(True)
        one.jumpTo(1)
        self.assertNotEqual(one.videoStage, STAGE_SHOWING)


class AnAddressThePlayerWillNotTake(unittest.TestCase):
    def test_it_is_forgotten_so_the_next_go_finds_a_fresh_one(self) -> None:
        """Held, every later go at that song is refused in the same silence."""
        one = player()
        one.play_items([song()])
        one._video_addresses.put("yt:a", "https://example.invalid/v")
        one._on_video_refused("https://example.invalid/v", "it would not open")
        self.assertIsNone(one._video_addresses.get("yt:a"))
        self.assertEqual(one.videoNote, "it would not open")
        self.assertEqual(one.videoStage, "")

    def test_an_address_for_another_song_is_left_alone(self) -> None:
        one = player()
        one.play_items([song()])
        one._video_addresses.put("yt:b", "https://example.invalid/other")
        one._on_video_refused("https://example.invalid/other", "it would not open")
        self.assertEqual(one._video_addresses.get("yt:b"),
                         "https://example.invalid/other")

    def test_one_that_has_aged_out_is_never_offered(self) -> None:
        """The picture's addresses are signed exactly as the sound's are, and
        a map that never forgets one hands a dead address to the player, which
        refuses it without a word and leaves the artwork up all evening."""
        import time

        from test_audio import signed

        one = player()
        one._video_addresses.put("yt:a", signed("yt:a", expire=int(time.time()) + 60))
        self.assertIsNone(one._video_addresses.get("yt:a"))
        one._video_addresses.put("yt:a", signed("yt:a"))
        self.assertIsNotNone(one._video_addresses.get("yt:a"))

