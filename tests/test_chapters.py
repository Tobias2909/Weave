"""Chapters on a music track.

A YouTube video is often an album, with its songs marked as chapters rather
than published one by one. Without them the player bar is one long block with
nothing to say that it is six songs, and the name above it is the name of the
whole upload.

They cost nothing. yt-dlp prints them in the same call that resolves the
address, which is the call that has to happen anyway before a track can play,
and asking separately would be another few seconds per song.
"""

import json
import unittest

from weave.audio import parse_chapters

# What yt-dlp actually printed for a real album upload, shortened. Measured
# rather than invented, since the shape of this is the whole contract.
REAL = json.dumps([
    {"start_time": 0, "title": "k.m.", "end_time": 312},
    {"start_time": 312, "title": "Sebastian", "end_time": 637},
    {"start_time": 637, "title": "silhouetted", "end_time": 904},
])


class ReadingThem(unittest.TestCase):
    def test_a_real_answer_reads(self):
        found = parse_chapters(REAL)
        self.assertEqual([one["title"] for one in found],
                         ["k.m.", "Sebastian", "silhouetted"])
        self.assertEqual(found[1]["start"], 312.0)
        self.assertEqual(found[1]["end"], 637.0)

    def test_a_video_with_none_says_NA_and_that_is_not_an_error(self):
        self.assertEqual(parse_chapters("NA"), ())

    def test_the_address_shares_the_output_and_is_not_mistaken_for_one(self):
        # Both come from the same call, so the whole output is looked at
        # rather than a line counted off.
        mixed = f"{REAL}\nhttps://rr3---sn-x.googlevideo.com/videoplayback?expire=1\n"
        self.assertEqual(len(parse_chapters(mixed)), 3)
        self.assertEqual(parse_chapters("https://only-an-address/x"), ())

    def test_nothing_that_cannot_be_named_or_placed_is_kept(self):
        # A mark on the bar that cannot be named is worse than no mark.
        found = parse_chapters(json.dumps([
            {"start_time": 0, "title": "Real"},
            {"start_time": 10},
            {"title": "No start"},
            {"start_time": "x", "title": "Not a number"},
            "not even a row",
        ]))
        self.assertEqual([one["title"] for one in found], ["Real"])
        self.assertEqual(found[0]["end"], 0.0)

    def test_rubbish_is_not_a_crash(self):
        for text in ("", "[", "[not json", "{}", "null", "[1, 2, 3]"):
            self.assertEqual(parse_chapters(text), (), text)


class SnappingToASong(unittest.TestCase):
    """The right button seeks to a song start rather than between two."""

    def setUp(self):
        from tests.test_audio import FakeEngine
        from weave.audio import AudioPlayer
        from weave.config import Config

        self.engine = FakeEngine()
        self.player = AudioPlayer(Config(raw={}), engine=self.engine)
        self.player._queue = [{"key": "yt:aaaaaaaaaaa", "title": "An album",
                               "url": "https://example/watch"}]
        self.player._order = [0]
        self.player._at = 0
        self.player._chapters["yt:aaaaaaaaaaa"] = parse_chapters(REAL)
        self.player._dur = 904.0
        self.player._idle = False

    def sought(self):
        return [where for what, where in self.engine.calls if what == "seek"]

    def test_a_press_before_a_song_lands_on_it(self):
        self.player.seekToTick(100 / 904)
        self.assertEqual(self.sought(), [312.0])

    def test_a_press_on_the_very_start_stays_there(self):
        self.player.seekToTick(0.0)
        self.assertEqual(self.sought(), [0.0])

    def test_a_press_just_past_a_mark_does_not_skip_to_the_one_after(self):
        # A press that lands a pixel late is still a press on that mark.
        self.player.seekToTick((312 + 0.2) / 904)
        self.assertEqual(self.sought(), [312.0])

    def test_a_press_past_the_last_of_them_lands_on_the_last(self):
        # There is nothing further to snap to, and answering with nothing
        # reads as a press that did not work.
        self.player.seekToTick(1.0)
        self.assertEqual(self.sought(), [637.0])

    def test_a_track_with_no_songs_is_seeked_to_plainly(self):
        self.player._chapters.clear()
        self.player.seekToTick(0.5)
        self.assertEqual(self.sought(), [452.0])

    def test_nothing_happens_with_no_length_or_nothing_playing(self):
        self.player._dur = 0.0
        self.player.seekToTick(0.5)
        self.player._dur = 904.0
        self.player._idle = True
        self.player.seekToTick(0.5)
        self.assertEqual(self.sought(), [])


class OnThePlayer(unittest.TestCase):
    """What the bar and the line under the title are given."""

    def setUp(self):
        from tests.test_audio import FakeEngine
        from weave.audio import AudioPlayer
        from weave.config import Config

        self.player = AudioPlayer(Config(raw={}), engine=FakeEngine())
        self.player._queue = [{"key": "yt:aaaaaaaaaaa", "title": "An album",
                               "url": "https://example/watch"}]
        self.player._order = [0]
        self.player._at = 0
        self.player._chapters["yt:aaaaaaaaaaa"] = parse_chapters(REAL)

    def at(self, seconds, length=904.0):
        self.player._pos = seconds
        self.player._dur = length

    def test_nothing_is_marked_before_a_length_is_known(self):
        # mpv reports the length after the track starts, and a fraction of
        # nothing cannot be placed on a bar.
        self.at(0, length=0)
        self.assertEqual(self.player._get_chapters(), [])

    def test_each_one_arrives_as_a_fraction_of_the_whole(self):
        self.at(0)
        found = self.player._get_chapters()
        self.assertEqual([one["title"] for one in found],
                         ["k.m.", "Sebastian", "silhouetted"])
        self.assertAlmostEqual(found[1]["at"], 312 / 904, places=6)

    def test_the_one_playing_is_the_last_that_has_begun(self):
        self.at(0)
        self.assertEqual(self.player._get_current_chapter(), "k.m.")
        self.at(400)
        self.assertEqual(self.player._get_current_chapter(), "Sebastian")
        self.at(900)
        self.assertEqual(self.player._get_current_chapter(), "silhouetted")

    def test_the_pointer_over_the_bar_asks_the_same_rule(self):
        # The name under the pointer and the name under the title come from
        # one rule, or the two would disagree about the same second.
        self.at(0)
        self.assertEqual(self.player.songAt(0.0), "k.m.")
        self.assertEqual(self.player.songAt(312 / 904 + 0.001), "Sebastian")
        self.assertEqual(self.player.songAt(1.0), "silhouetted")

    def test_a_fraction_off_either_end_is_pulled_back_onto_the_bar(self):
        self.at(0)
        self.assertEqual(self.player.songAt(-4.0), "k.m.")
        self.assertEqual(self.player.songAt(9.0), "silhouetted")

    def test_and_it_says_nothing_before_a_length_is_known(self):
        self.at(0, length=0)
        self.assertEqual(self.player.songAt(0.5), "")

    def test_a_track_with_none_names_none(self):
        self.player._chapters.clear()
        self.at(400)
        self.assertEqual(self.player._get_current_chapter(), "")
        self.assertEqual(self.player._get_chapters(), [])
        self.assertEqual(self.player.songAt(0.5), "")

    def test_one_that_starts_past_the_end_is_left_off(self):
        # A length that disagrees with the chapters is a live stream's sliding
        # window or a bad answer, and either way a mark past the end of the bar
        # would be drawn on top of the last pixel.
        self.at(10, length=300)
        self.assertEqual([one["title"] for one in self.player._get_chapters()], ["k.m."])

    def test_they_are_remembered_for_whoever_they_were_resolved_for(self):
        # A resolve that lands after the choice has moved on still learned
        # where that track's songs are, and going back to it must not have to
        # ask again.
        self.player._chapters.clear()
        self.player._on_resolved("yt:bbbbbbbbbbb", "https://example/stream",
                                 [{"title": "One", "start": 0.0, "end": 5.0}])
        self.assertIn("yt:bbbbbbbbbbb", self.player._chapters)


if __name__ == "__main__":
    unittest.main()
