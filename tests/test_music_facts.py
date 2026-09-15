"""What is known about a song, and what the picture is allowed to cost.

The resolve that finds a song's address is a full extraction whatever is
printed, measured against the live endpoint at 1.9 s either way, so the views,
the likes, the date and the album ride along in it for nothing. A listing
cannot answer for any of them: a flat one carries no like count at all and no
date without an extractor argument, which is why the page said so little for a
song that exists only in the music service.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support import scratch_db  # noqa: E402
from test_audio import FakeEngine, FakeResolver  # noqa: E402
from test_video_wanted import FakeVideoResolver, song  # noqa: E402

from weave import audio  # noqa: E402
from weave.config import Config  # noqa: E402
from weave.ui.bridge import Bridge  # noqa: E402

# One resolve's output, in the order yt-dlp printed it here: the chapters, the
# facts, then the address.
OUTPUT = (
    'NA\n'
    '{"view_count": 1816080435, "like_count": 19393303, "comment_count": 2400000, '
    '"channel": "Somebody", "channel_follower_count": 4540000, '
    '"timestamp": 1256453853, "upload_date": "20091025", "track": null, '
    '"artists": ["Somebody", "A Guest"], "album": "An Album", '
    '"release_year": 2009, "categories": ["Music"]}\n'
    'https://example.invalid/audio\n'
)


class WhatTheResolveSays(unittest.TestCase):
    def test_the_facts_are_read_out_of_the_same_output(self) -> None:
        found = audio.parse_facts(OUTPUT)
        self.assertEqual(found["views"], 1816080435)
        self.assertEqual(found["likes"], 19393303)
        self.assertEqual(found["comments"], 2400000)
        self.assertEqual(found["followers"], 4540000)
        self.assertEqual(found["channel"], "Somebody")
        self.assertEqual(found["album"], "An Album")
        self.assertEqual(found["year"], 2009)
        self.assertEqual(found["category"], "Music")
        self.assertEqual(found["published_at"], 1256453853)

    def test_several_names_become_one_line(self) -> None:
        self.assertEqual(audio.parse_facts(OUTPUT)["artist"], "Somebody, A Guest")

    def test_what_was_not_answered_is_absent_rather_than_empty(self) -> None:
        # A None the window has to test for is a None the window will forget
        # to test for. Here `track` came back null.
        self.assertNotIn("track", audio.parse_facts(OUTPUT))

    def test_a_date_with_no_hour_in_it_is_read_as_utc(self) -> None:
        # The fallback for an extraction that carries the day and not the
        # moment. Africa/Lagos in the clock test says nothing about where
        # anybody is, and neither does this.
        found = audio.parse_facts('{"upload_date": "20091025"}')
        self.assertEqual(found["published_at"], 1256428800)

    def test_nothing_in_the_output_is_no_facts_rather_than_a_fault(self) -> None:
        self.assertEqual(audio.parse_facts("https://example.invalid/a\n"), {})
        self.assertEqual(audio.parse_facts("{not json}"), {})


class TheCommandThatAsksForThem(unittest.TestCase):
    def run_it(self):
        class Result:
            stdout = OUTPUT
            stderr = ""
            returncode = 0

        with mock.patch.object(audio, "run_process", return_value=Result()) as ran:
            found = audio.resolve_address(Config(raw={}),
                                          "https://www.youtube.com/watch?v=x",
                                          live=False)
        return found, list(ran.call_args[0][0]), ran.call_count

    def test_they_cost_no_second_call(self) -> None:
        found, command, calls = self.run_it()
        self.assertEqual(calls, 1, "the facts were asked for in a call of their own")
        self.assertIn(audio.FACT_SPEC, command)
        self.assertEqual(found.address, "https://example.invalid/audio")
        self.assertEqual(found.facts["views"], 1816080435)

    def test_the_warnings_are_still_not_suppressed(self) -> None:
        # yt-dlp says why the challenge went unanswered in warnings, and that
        # is the only account of it there is.
        _found, command, _calls = self.run_it()
        self.assertNotIn("--no-warnings", command)


class WhatThePlayerKeeps(unittest.TestCase):
    def player(self) -> audio.AudioPlayer:
        one = audio.AudioPlayer(Config(raw={}), engine=FakeEngine())
        one._make_resolver = lambda entry: FakeResolver(entry["key"])
        one._make_video_resolver = lambda entry: FakeVideoResolver(entry["key"])
        return one

    def test_they_are_read_back_for_the_song_playing(self) -> None:
        one = self.player()
        one.play_items([song()])
        one._on_resolved("yt:a", "https://example.invalid/a", [], {"views": 12})
        self.assertEqual(one.trackFacts["views"], 12)

    def test_and_not_for_a_different_one(self) -> None:
        one = self.player()
        one.play_items([song()])
        one._on_resolved("yt:elsewhere", "https://example.invalid/b", [], {"views": 12})
        self.assertEqual(one.trackFacts, {})

    def test_their_arrival_is_not_a_new_song(self) -> None:
        # The page asks for the words, the related songs and the comments
        # again on trackChanged, and those cost requests. Facts arriving must
        # not read as a different song.
        one = self.player()
        one.play_items([song()])
        said = []
        one.trackChanged.connect(lambda: said.append("track"))
        one.factsChanged.connect(lambda: said.append("facts"))
        one._on_resolved("yt:a", "https://example.invalid/a", [], {"views": 12})
        self.assertEqual(said, ["facts"])


class WhatTheWindowDrawsFromThem(unittest.TestCase):
    class Player:
        def __init__(self, facts):
            self.trackFacts = facts

    def filled(self, detail, facts):
        bridge = Bridge.__new__(Bridge)
        bridge._audio = self.Player(facts)
        return Bridge._with_player_facts(bridge, dict(detail))

    def test_a_song_with_no_row_of_its_own_still_says_something(self) -> None:
        out = self.filled({}, {"views": 1500, "likes": 90, "channel": "Somebody",
                               "published_at": 1256453853})
        self.assertEqual(out["channelTitle"], "Somebody")
        self.assertEqual(out["viewsText"], "1.5K")
        self.assertEqual(out["likesText"], "90")
        self.assertTrue(out["ageText"])

    def test_what_is_stored_wins(self) -> None:
        # A stored row is the more exact of the two, and a number that flickers
        # between two accounts of itself reads as a fault.
        out = self.filled({"viewsText": "9"}, {"views": 1500})
        self.assertEqual(out["viewsText"], "9")

    def test_a_player_with_nothing_to_add_changes_nothing(self) -> None:
        self.assertEqual(self.filled({"viewsText": "9"}, {}), {"viewsText": "9"})


class SoundAlone(unittest.TestCase):
    def player(self, db=None) -> audio.AudioPlayer:
        one = audio.AudioPlayer(Config(raw={}), db=db, engine=FakeEngine())
        one._make_resolver = lambda entry: FakeResolver(entry["key"])
        one._make_video_resolver = lambda entry: FakeVideoResolver(entry["key"])
        return one

    def test_no_picture_is_fetched_for_an_open_page(self) -> None:
        one = self.player()
        one.setAudioOnly(True)
        one.play_items([song(duration_s=200)])
        one.setVideoWanted(True)
        self.assertIsNone(one._video_resolver, "a picture was fetched for sound alone")

    def test_turning_it_on_stops_the_one_already_running(self) -> None:
        # Waiting for the next song would be ignoring what was asked for: the
        # picture is decoding now.
        one = self.player()
        one.play_items([song(duration_s=200)])
        one.setVideoWanted(True)
        one._engine.calls.clear()
        one.setAudioOnly(True)
        self.assertIn(("drop_video",), one._engine.calls)

    def test_turning_it_off_starts_one_where_a_page_is_open(self) -> None:
        one = self.player()
        one.play_items([song(duration_s=200)])
        one.setVideoWanted(True)
        one.setAudioOnly(True)
        one.setAudioOnly(False)
        self.assertIsNotNone(one._video_resolver)

    def test_an_answer_arriving_late_is_not_shown(self) -> None:
        one = self.player()
        one.play_items([song(duration_s=200)])
        one.setVideoWanted(True)
        one.setAudioOnly(True)
        one._engine.calls.clear()
        one._on_video_resolved("yt:a", "https://example.invalid/v")
        self.assertNotIn(("add_video", "https://example.invalid/v"), one._engine.calls)

    def test_it_is_remembered(self) -> None:
        db = scratch_db(self)
        one = self.player(db)
        one.setAudioOnly(True)
        self.assertTrue(self.player(db).audioOnly)


class HowLargeThePictureMayBe(unittest.TestCase):
    def test_the_format_is_capped_at_the_chosen_height(self) -> None:
        self.assertIn("height<=720", audio.video_format(720))
        self.assertIn("vp9", audio.video_format(720))

    def test_the_default_is_what_the_config_says(self) -> None:
        self.assertEqual(Config(raw={}).music_video_height, audio.VIDEO_HEIGHT)

    def test_a_choice_overrides_the_config(self) -> None:
        db = scratch_db(self)
        db.set_video_height(480)
        one = audio.AudioPlayer(Config(raw={}), db=db, engine=FakeEngine())
        self.assertEqual(one.video_height(), 480)

    def test_the_resolver_is_given_it(self) -> None:
        db = scratch_db(self)
        db.set_video_height(1440)
        one = audio.AudioPlayer(Config(raw={}), db=db, engine=FakeEngine())
        made = one._make_video_resolver(song())
        self.assertEqual(made._height, 1440)

    def test_a_height_nobody_offers_is_refused(self) -> None:
        # The window's list is the window's business, but a slot that takes a
        # number off a menu has no reason to accept one that was never on it.
        db = scratch_db(self)
        bridge = Bridge.__new__(Bridge)
        bridge._db = db
        bridge._cfg = Config(raw={})
        Bridge.setVideoCeiling(bridge, 137)
        self.assertEqual(Bridge._video_ceiling(bridge), audio.VIDEO_HEIGHT)


if __name__ == "__main__":
    unittest.main()
