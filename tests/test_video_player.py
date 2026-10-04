"""Videos played in the window rather than in mpv.

The player's own logic, against an engine that records what it was told and
lets a test say what mpv reported back, the way the music's tests do it. What
the picture really does was measured in a real window before this was written.
"""

import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, Signal

from tests.support import scratch_db
from tests import test_audio as music
from weave.config import Config
from weave.engine_libmpv import CURRENT
from weave.sources.sponsorblock import Segment
from weave.video import (CAPTION_LANGUAGE_STATE, CAPTIONS_STATE, QUALITY_STATE, RESUME_FROM_S,
                         SPONSOR_STATE, VideoPlayer, ceiling_for, choose_caption, parse_extras,
                         watch_format)

_app = QCoreApplication.instance() or QCoreApplication([])


def video(name, live=False):
    return {"key": f"yt:{name}", "title": name, "channel": "somebody",
            "url": f"https://www.youtube.com/watch?v={name}", "live": live,
            "thumbnail": "", "channelId": "", "channelKey": ""}


class FakeEngine(QObject):
    positionChanged = Signal(float)
    durationChanged = Signal(float)
    pausedChanged = Signal(bool)
    idleChanged = Signal(bool)
    bufferingChanged = Signal(bool)
    started = Signal(str)
    ended = Signal(str)
    gone = Signal(str)
    videoChanged = Signal(bool)
    eofChanged = Signal(bool)
    surfaceWanted = Signal()

    def __init__(self):
        super().__init__()
        self.calls = []

    def only(self, kind):
        return [call for call in self.calls if call[0] == kind]

    def set_volume(self, volume):
        self.calls.append(("volume", volume))

    def set_video(self, wanted):
        self.calls.append(("video", wanted))

    def load(self, url, start=None, video=None, subtitle=""):
        self.calls.append(("load", url, start, video))
        if subtitle:
            self.calls.append(("caption", subtitle))

    def show_subtitle(self, url, title="", lang=""):
        self.calls.append(("caption", url))

    def set_subtitle_place(self, percent):
        self.calls.append(("caption place", percent))

    def set_pause(self, paused):
        self.calls.append(("pause", paused))

    def set_speed(self, speed):
        self.calls.append(("speed", speed))

    def seek(self, seconds):
        self.calls.append(("seek", seconds))

    def stop(self):
        self.calls.append(("stop",))

    def quit(self):
        self.calls.append(("quit",))


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = scratch_db(self)
        self.engine = FakeEngine()
        self.player = VideoPlayer(Config(raw={}), self.db, engine=self.engine)
        self.finding = []
        # Finding a video is a subprocess. Every test here answers for it, by
        # putting what it would have found where a second look finds it.
        original = self.player._start_current

        def start(again=False):
            entry = self.player._current()
            self.finding.append(entry.get("key"))
            # Everything up to the finder, which is not started.
            self.player._addresses.put(f"{entry.get('key')}@{self.player._height()}",
                                       f"https://picture.example/{entry.get('key')} "
                                       f"https://sound.example/{entry.get('key')}")
            original(again)
        self.player._start_current = start
        self.watched = []
        self.player.watched.connect(lambda key, progress: self.watched.append((key, progress)))
        self.stops = []
        self.player.stopped.connect(lambda: self.stops.append(True))

    def keys(self):
        return [entry["key"] for entry in self.player.queue]

    def playing(self):
        return self.player.track.get("key")


class TheQueue(_Base):
    def test_the_first_press_plays_it(self):
        self.player.play_now(video("a"))
        self.assertEqual(self.keys(), ["yt:a"])
        self.assertEqual(self.playing(), "yt:a")
        self.assertEqual(self.engine.only("load")[-1][1:],
                         ("https://sound.example/yt:a", None, "https://picture.example/yt:a"))

    def test_a_press_while_one_plays_goes_in_straight_after_it_and_plays(self):
        """What was playing stays above it as played, and is not played again
        once the new one ends."""
        self.player.play_now(video("a"))
        self.player.add_item(video("c"))
        self.player.play_now(video("b"))
        self.assertEqual(self.keys(), ["yt:a", "yt:b", "yt:c"])
        self.assertEqual(self.playing(), "yt:b")
        self.assertEqual(self.player.queueIndex, 1)

    def test_a_playlist_is_played_from_the_one_pressed_with_the_rest_after_it(self):
        self.player.play_now(video("x"))
        self.player.play_list([video("a"), video("b"), video("c")])
        self.assertEqual(self.keys(), ["yt:x", "yt:a", "yt:b", "yt:c"])
        self.assertEqual(self.playing(), "yt:a")

    def test_play_next_and_add_to_queue(self):
        self.player.play_now(video("a"))
        self.player.add_item(video("z"))
        self.player.add_item(video("b"), play_next=True)
        self.assertEqual(self.keys(), ["yt:a", "yt:b", "yt:z"])
        self.assertEqual(self.playing(), "yt:a")

    def test_adding_to_nothing_plays_it(self):
        self.player.add_item(video("a"))
        self.assertEqual(self.playing(), "yt:a")

    def test_moving_and_taking_out_keep_the_one_playing(self):
        self.player.play_list([video("a"), video("b"), video("c"), video("d")])
        self.player.jumpTo(2)
        self.player.moveInQueue(3, 0)
        self.assertEqual(self.keys(), ["yt:d", "yt:a", "yt:b", "yt:c"])
        self.assertEqual(self.playing(), "yt:c")
        self.player.removeFromQueue(0)
        self.assertEqual(self.playing(), "yt:c")
        self.assertEqual(self.player.queueIndex, 2)

    def test_clear_keeps_only_the_one_playing(self):
        self.player.play_list([video("a"), video("b"), video("c")])
        self.player.next()
        self.player.clearQueue()
        self.assertEqual(self.keys(), ["yt:b"])
        self.assertEqual(self.playing(), "yt:b")

    def test_stop_empties_it_and_says_so(self):
        self.player.play_now(video("a"))
        self.player.stop()
        self.assertEqual(self.keys(), [])
        self.assertEqual(self.stops, [True])
        self.assertIn(("stop",), self.engine.calls)


class TheEnd(_Base):
    def test_the_end_of_one_plays_the_next(self):
        self.player.play_list([video("a"), video("b")])
        self.player._dur = 100.0
        self.engine.eofChanged.emit(True)
        self.assertEqual(self.playing(), "yt:b")
        self.assertEqual(self.stops, [])
        self.assertIn(("yt:a", 1.0), self.watched)

    def test_the_end_of_the_last_holds_its_frame_and_says_it_has_stopped(self):
        """The music comes back here, and nothing else plays."""
        self.player.play_now(video("a"))
        self.player._dur = 100.0
        self.engine.eofChanged.emit(True)
        self.assertTrue(self.player.ended)
        self.assertEqual(self.stops, [True])
        self.assertEqual(self.keys(), ["yt:a"], "the queue is kept to look at")

    def test_play_again_starts_it_over(self):
        self.player.play_now(video("a"))
        self.engine.eofChanged.emit(True)
        self.player.replay()
        self.assertFalse(self.player.ended)
        self.assertEqual(self.engine.only("seek")[-1], ("seek", 0.0))


class Watched(_Base):
    def test_watched_at_the_share_mpv_uses_and_only_once(self):
        self.player.play_now(video("a"))
        self.engine.durationChanged.emit(100.0)
        self.engine.positionChanged.emit(84.0)
        self.assertEqual(self.watched, [])
        self.engine.positionChanged.emit(85.0)
        self.engine.positionChanged.emit(90.0)
        self.assertEqual(self.watched, [("yt:a", 0.85)])

    def test_a_broadcast_is_never_watched(self):
        self.player.play_now(video("live", live=True))
        self.engine.durationChanged.emit(100.0)
        self.engine.positionChanged.emit(99.0)
        self.engine.eofChanged.emit(True)
        self.assertEqual(self.watched, [])


class WhereItWasLeft(_Base):
    def test_it_starts_again_where_it_was_left(self):
        self.db.set_video_position("yt:a", 300.0, 1200.0)
        self.player.play_now(video("a"))
        self.assertEqual(self.engine.only("load")[-1][2], 300.0)

    def test_a_look_is_not_a_watch(self):
        self.db.set_video_position("yt:a", RESUME_FROM_S - 1, 1200.0)
        self.player.play_now(video("a"))
        self.assertIsNone(self.engine.only("load")[-1][2])

    def test_one_nearly_finished_starts_from_the_top(self):
        self.db.set_video_position("yt:a", 1100.0, 1200.0)
        self.player.play_now(video("a"))
        self.assertIsNone(self.engine.only("load")[-1][2])

    def test_where_it_is_is_kept_when_another_is_pressed(self):
        self.player.play_now(video("a"))
        self.player._dur = 1200.0
        self.player._pos = 400.0
        self.player.play_now(video("b"))
        self.assertEqual(self.db.video_position("yt:a"), (400.0, 1200.0))

    def test_watching_it_through_forgets_where_it_was(self):
        self.db.set_video_position("yt:a", 300.0, 100.0)
        self.player.play_now(video("a"))
        self.player._dur = 100.0
        self.engine.eofChanged.emit(True)
        self.assertIsNone(self.db.video_position("yt:a"))

    def test_a_time_asked_for_wins(self):
        """A link's own time, or the second the page was left at."""
        self.db.set_video_position("yt:a", 300.0, 1200.0)
        self.player.play_now(video("a"), at_s=42.0)
        self.assertEqual(self.engine.only("load")[-1][2], 42.0)


class TheControls(_Base):
    def test_the_volume_is_its_own_and_is_kept(self):
        self.player.setVolume(35)
        self.assertEqual(self.db.get_int("video_volume", 0), 35)
        again = VideoPlayer(Config(raw={}), self.db, engine=FakeEngine())
        self.assertEqual(again.volume, 35)

    def test_mute_gives_the_level_back(self):
        self.player.setVolume(40)
        self.player.toggleMute()
        self.assertEqual(self.player.volume, 0)
        self.player.toggleMute()
        self.assertEqual(self.player.volume, 40)

    def test_a_started_report_says_which(self):
        heard = []
        self.player.started.connect(heard.append)
        self.player.play_now(video("a"))
        self.engine.started.emit(CURRENT)
        self.assertEqual(heard, ["yt:a"])


def caption(code, auto=False, name=None):
    return {"code": code, "name": name or code, "auto": auto,
            "url": f"https://captions.example/{code}{'-auto' if auto else ''}.vtt"}


# The tagged lines of one resolve, shaped as yt-dlp prints them for a video
# offered up to 1440p with a storyboard, two uploaded captions and YouTube's
# own in English, translated into another language too.
RESOLVED = "\n".join([
    "https://picture.example/a", "https://sound.example/a", "NA", "{}",
    "weave-height:1080",
    'weave-formats:[{"format_id": "sb1", "height": 90, "vcodec": "none", "width": 160,'
    ' "rows": 5, "columns": 5, "fps": 0.2, "fragments": [{"url": "https://sb.example/L2/M0"}]},'
    ' {"format_id": "sb0", "height": 180, "vcodec": "none", "width": 320, "rows": 3,'
    ' "columns": 3, "fps": 0.2, "fragments": [{"url": "https://sb.example/L3/M0"},'
    ' {"url": "https://sb.example/L3/M1"}]},'
    ' {"format_id": "251", "vcodec": "none"},'
    ' {"format_id": "247", "height": 720, "vcodec": "vp9", "width": 1280},'
    ' {"format_id": "136", "height": 720, "vcodec": "avc1", "width": 1280},'
    ' {"format_id": "271", "height": 1440, "vcodec": "vp9", "width": 2560}]',
    'weave-captions:[{"ext": "vtt", "name": "German",'
    ' "url": "https://www.youtube.com/api/timedtext?v=a&lang=de&fmt=vtt"},'
    ' {"ext": "vtt", "name": "English (United Kingdom)",'
    ' "url": "https://www.youtube.com/api/timedtext?v=a&lang=en-GB&fmt=vtt"}]',
    'weave-auto:[{"ext": "vtt", "name": "English (Original)",'
    ' "url": "https://www.youtube.com/api/timedtext?v=a&kind=asr&lang=en&fmt=vtt"},'
    ' {"ext": "vtt", "name": "English",'
    ' "url": "https://www.youtube.com/api/timedtext?v=a&kind=asr&lang=en&fmt=vtt"},'
    ' {"ext": "vtt", "name": "French",'
    ' "url": "https://www.youtube.com/api/timedtext?v=a&kind=asr&lang=en&tlang=fr&fmt=vtt"}]',
])


class WhatRidesAlong(unittest.TestCase):
    def test_heights_storyboard_and_captions_come_out_of_the_one_call(self):
        found = parse_extras(RESOLVED)
        self.assertEqual(found["height"], 1080)
        self.assertEqual(found["heights"], [1440, 720])
        board = found["storyboard"]
        self.assertEqual((board["width"], board["columns"], board["rows"]), (320, 3, 3))
        self.assertEqual(board["sheets"], ["https://sb.example/L3/M0", "https://sb.example/L3/M1"])
        self.assertEqual([(one["code"], one["name"], one["auto"]) for one in found["captions"]],
                         [("en-GB", "English (United Kingdom)", False), ("de", "German", False),
                          ("en", "English", True)])

    def test_a_video_with_none_of_it_plays_without_it(self):
        found = parse_extras("https://picture.example/a\nNA\n{}\nweave-height:NA\n"
                             "weave-formats:NA\nweave-captions:NA\nweave-auto:NA")
        self.assertEqual(found, {"heights": [], "captions": []})

    def test_the_tagged_lines_are_not_taken_for_chapters_or_facts(self):
        from weave.audio import parse_chapters, parse_facts
        self.assertEqual(parse_chapters(RESOLVED), ())
        self.assertEqual(parse_facts(RESOLVED), {})


class WhichCaption(unittest.TestCase):
    TRACKS = [caption("de"), caption("en-GB"), caption("en", auto=True)]

    def test_the_language_picked_last_and_the_uploaders_first(self):
        self.assertEqual(choose_caption(self.TRACKS, "de")["code"], "de")
        self.assertEqual(choose_caption(self.TRACKS, "en")["code"], "en-GB")
        self.assertEqual(choose_caption([caption("en", auto=True), caption("en-GB")], "en")["code"],
                         "en-GB", "the uploader's before YouTube's, even an exact one")

    def test_otherwise_the_videos_own_language(self):
        self.assertEqual(choose_caption(self.TRACKS, "")["code"], "en-GB")
        self.assertEqual(choose_caption(self.TRACKS, "ja")["code"], "en-GB")
        self.assertEqual(choose_caption([caption("en", auto=True)], "de")["auto"], True)

    def test_never_a_strangers_language(self):
        self.assertIsNone(choose_caption([caption("es")], "de"))
        self.assertIsNone(choose_caption([], "de"))


class TheMenusOnThePicture(_Base):
    def playing_with(self, extras, name="a", height=1440):
        self.player.setScreenHeight(height)
        self.player._extras[f"yt:{name}"] = extras
        self.player.play_now(video(name))
        self.engine.idleChanged.emit(False)

    def test_a_height_picked_fetches_the_one_playing_again_where_it_is(self):
        heard = []
        self.player.started.connect(heard.append)
        tracks = []
        self.player.trackChanged.connect(lambda: tracks.append(True))
        self.playing_with({"heights": [1440, 1080, 720]})
        self.player._fetched["yt:a@1440"] = 1440
        self.engine.started.emit(CURRENT)
        self.player._dur = 600.0
        self.player._pos = 123.0
        self.player.setPaused(True)
        tracks.clear()
        self.player.setQuality(720)
        load = self.engine.only("load")[-1]
        self.assertEqual(load[2], 123.0)
        self.assertEqual(self.engine.only("pause")[-1], ("pause", True), "paused stays paused")
        self.assertEqual(self.finding[-2:], ["yt:a", "yt:a"])
        self.engine.started.emit(CURRENT)
        self.assertEqual(heard, ["yt:a"], "the second start is not news")
        self.assertEqual(tracks, [], "the page about it stays as it is")
        self.assertEqual(self.db.get_state(QUALITY_STATE), "720")
        self.assertEqual(self.player.qualityText, "720p")

    def test_a_height_that_would_come_back_the_same_is_not_fetched_again(self):
        self.playing_with({"heights": [720, 480]})
        self.player._fetched["yt:a@1440"] = 720
        loads = len(self.engine.only("load"))
        self.player.setQuality(1080)
        self.assertEqual(len(self.engine.only("load")), loads)
        self.assertEqual(self.player._height(), 1080, "but it holds for the next video")

    def test_auto_says_what_the_screen_makes_it_and_a_pick_is_kept(self):
        self.player.setScreenHeight(1600)
        self.assertEqual(self.player.qualityText, "Auto (1440p)")
        self.player.setQuality(1080)
        again = VideoPlayer(Config(raw={}), self.db, engine=FakeEngine())
        self.assertEqual(again.quality, 1080)
        self.player.setQuality(0)
        self.assertEqual(self.db.get_state(QUALITY_STATE), "auto")

    def test_the_menu_lists_the_videos_own_heights_and_which_plays(self):
        self.playing_with({"heights": [1440, 720]})
        self.player._fetched["yt:a@1440"] = 1440
        menu = [(one["label"], one["chosen"], one["playing"]) for one in self.player.qualities]
        self.assertEqual(menu, [("Auto (1440p)", True, False), ("1440p", False, True),
                                ("720p", False, False)])

    def test_a_caption_picked_shows_and_the_next_video_has_it_too(self):
        self.playing_with({"captions": [caption("en", auto=True), caption("de")]})
        self.assertEqual(self.engine.only("caption"), [], "off by default")
        self.player.setCaption(1)
        self.assertEqual(self.engine.only("caption")[-1], ("caption", caption("de")["url"]))
        self.assertTrue(self.player.captionShowing)
        self.assertEqual(self.db.get_state(CAPTIONS_STATE), "on")
        self.assertEqual(self.db.get_state(CAPTION_LANGUAGE_STATE), "de")
        self.player._extras["yt:b"] = {"captions": [caption("de-AT"), caption("fr")]}
        self.player.play_now(video("b"))
        self.assertEqual(self.engine.only("caption")[-1], ("caption", caption("de-AT")["url"]),
                         "handed over with the file")
        self.player.setCaption(-1)
        self.assertEqual(self.engine.only("caption")[-1], ("caption", ""))
        self.assertFalse(self.player.captionShowing)
        self.assertEqual(self.db.get_state(CAPTIONS_STATE), "off")
        self.assertEqual(self.db.get_state(CAPTION_LANGUAGE_STATE), "de", "the language stays")

    def test_captions_on_from_the_settings(self):
        self.playing_with({"captions": [caption("en", auto=True)]})
        self.player.setCaptionsOn(True)
        self.assertEqual(self.engine.only("caption")[-1], ("caption", caption("en", True)["url"]))
        self.assertEqual([one["chosen"] for one in self.player.captions], [True])

    def test_the_frame_under_the_pointer(self):
        self.playing_with({"storyboard": {"sheets": ["s0", "s1"], "width": 320, "height": 180,
                                          "columns": 3, "rows": 3, "fps": 0.2}})
        self.player._dur = 100.0
        # One frame every five seconds, nine to a sheet.
        self.assertEqual(self.player.previewAt(0.0), {"sheet": "s0", "column": 0, "row": 0})
        self.assertEqual(self.player.previewAt(0.24), {"sheet": "s0", "column": 1, "row": 1})
        self.assertEqual(self.player.previewAt(0.5), {"sheet": "s1", "column": 1, "row": 0})
        self.assertEqual(self.player.previewAt(1.0), {"sheet": "s1", "column": 2, "row": 2})


class SponsorBlock(_Base):
    SEGMENTS = (Segment("intro", 0.0, 10.0, "intro-1", 300.0),
                Segment("sponsor", 60.0, 90.0, "sponsor-1", 300.0),
                Segment("filler", 200.0, 220.0, "filler-1", 300.0))

    def playing(self, name="a", on=True, segments=SEGMENTS):
        if on:
            self.player._sponsor_on = True
        self.player._segments[f"yt:{name}"] = segments
        self.player.play_now(video(name))
        self.engine.idleChanged.emit(False)
        self.engine.durationChanged.emit(300.0)

    def at(self, seconds):
        self.engine.positionChanged.emit(float(seconds))

    def seeks(self):
        return [call[1] for call in self.engine.only("seek")]

    def test_off_until_switched_on_and_nothing_is_asked(self):
        with mock.patch("weave.video._SegmentFinder") as finder:
            self.player.play_now(video("a"))
        finder.assert_not_called()
        self.assertEqual(self.player.segments, [])

    def test_on_it_asks_once_per_video(self):
        self.player.setSponsorBlock(True)
        self.assertEqual(self.db.get_state(SPONSOR_STATE), "on")
        with mock.patch("weave.video._SegmentFinder") as finder:
            finder.return_value.isRunning.return_value = True
            finder.return_value.key = "yt:a"
            self.player.play_now(video("a"))
            self.player.play_now(video("a"))
            self.player.play_now(video("live", live=True))
        self.assertEqual([call.args[2] for call in finder.call_args_list], ["yt:a"])

    def test_a_sponsor_is_skipped_once_with_an_undo(self):
        self.playing()
        self.at(61.0)
        self.assertEqual(self.seeks(), [90.0])
        self.assertEqual(self.player.skipNotice, "Skipped sponsor")
        self.at(61.2)
        self.assertEqual(self.seeks(), [90.0], "a late report from inside is not a second skip")
        self.player.undoSkip()
        self.assertEqual(self.seeks()[-1], 60.0)
        self.assertEqual(self.player.skipNotice, "")
        self.at(61.0)
        self.assertEqual(self.seeks()[-1], 60.0, "let play after an undo")

    def test_the_others_are_offered_with_a_button(self):
        self.playing()
        self.at(2.0)
        self.assertEqual(self.seeks(), [], "an intro is only offered")
        self.assertEqual(self.player.segmentButton, "Skip intro")
        self.player.skipSegment()
        self.assertEqual(self.seeks(), [10.0])
        self.assertEqual(self.player.skipNotice, "", "a skip pressed for is not announced")
        self.at(12.0)
        self.assertEqual(self.player.segmentButton, "")

    def test_a_kind_left_alone_is_neither_marked_nor_offered(self):
        self.player.setSegmentAction("filler", "ignore")
        self.playing()
        self.at(205.0)
        self.assertEqual(self.player.segmentButton, "")
        self.assertEqual([one["label"] for one in self.player.segments], ["Intro", "Sponsor"])
        again = VideoPlayer(Config(raw={}), self.db, engine=FakeEngine())
        self.assertEqual({one["key"]: one["action"] for one in again.sponsorCategories}["filler"],
                         "ignore")

    def test_the_bar_marks_where_they_are(self):
        self.playing()
        marks = self.player.segments
        self.assertEqual([(one["at"], one["to"]) for one in marks][1], (0.2, 0.3))
        self.assertEqual(marks[1]["colour"], "#00d400")
        self.assertEqual(self.player.segmentAt(0.25), "Sponsor")
        self.assertEqual(self.player.segmentAt(0.5), "")

    def test_marked_on_another_cut_it_is_left_out(self):
        self.playing(segments=(Segment("sponsor", 60.0, 90.0, "old", 340.0),))
        self.at(61.0)
        self.assertEqual(self.seeks(), [])
        self.assertEqual(self.player.segments, [])

    def test_a_new_video_starts_with_nothing_let_play(self):
        self.playing()
        self.at(61.0)
        self.player.undoSkip()
        self.player._segments["yt:b"] = self.SEGMENTS
        self.player.play_now(video("b"))
        self.engine.idleChanged.emit(False)
        self.engine.durationChanged.emit(300.0)
        self.player.jumpTo(0)
        self.engine.idleChanged.emit(False)
        self.engine.durationChanged.emit(300.0)
        self.at(61.0)
        self.assertEqual(self.seeks()[-1], 90.0)

    def test_switched_off_it_stops(self):
        self.playing()
        self.player.setSponsorBlock(False)
        self.at(61.0)
        self.assertEqual(self.seeks(), [])
        self.assertEqual(self.player.segments, [])


class HowBig(unittest.TestCase):
    def test_never_bigger_than_the_screen(self):
        self.assertEqual(ceiling_for(1440), 1440)
        self.assertEqual(ceiling_for(1600), 1440)
        self.assertEqual(ceiling_for(1080), 1080)
        self.assertEqual(ceiling_for(2160), 2160)
        self.assertEqual(ceiling_for(200), 360)

    def test_picture_and_sound_apart_and_vp9_first(self):
        asked = watch_format(1440, live=False)
        self.assertTrue(asked.startswith("bestvideo[height<=1440][vcodec^=vp9]+bestaudio/"))
        self.assertIn("best[height<=1440]", asked)

    def test_a_broadcast_is_only_offered_joined(self):
        self.assertEqual(watch_format(1080, live=True), "best[height<=1080]/best")


class TheMusicComesBack(music._Base):
    """A video starting paused the music, and the music comes back when the
    video is over, unless anything was done to the music by hand between."""

    def setUp(self):
        super().setUp()
        self.player.setVolume(60)
        self.queue("aaa")
        self.cache("aaa")
        self.player._start_current()

    def finish_fade(self):
        loop = QEventLoop()
        self.player._fade.finished.connect(loop.quit)
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        self.player._fade.finished.disconnect(loop.quit)

    def test_music_the_video_paused_comes_back(self):
        self.player._auto_pause = True
        self.player.pause_for_video()
        self.finish_fade()
        self.assertTrue(self.player.paused_for_video)
        self.player.resume_after_video()
        self.assertEqual(self.engine.only("pause")[-1], ("pause", False))
        self.assertFalse(self.player.paused_for_video)

    def test_music_paused_by_hand_stays_paused(self):
        self.player.toggle()
        self.finish_fade()
        self.player._auto_pause = True
        self.player.pause_for_video()
        self.engine.calls.clear()
        self.player.resume_after_video()
        self.assertEqual(self.engine.only("pause"), [])

    def test_music_played_by_hand_during_the_video_is_not_given_back_twice(self):
        self.player._auto_pause = True
        self.player.pause_for_video()
        self.finish_fade()
        self.player.toggle()
        self.assertFalse(self.player.paused_for_video)
        self.engine.calls.clear()
        self.player.resume_after_video()
        self.assertEqual(self.engine.only("pause"), [])

    def test_with_the_button_off_nothing_is_owed(self):
        self.player._auto_pause = False
        self.player.pause_for_video()
        self.assertFalse(self.player.paused_for_video)


class TheVideoPageTabs(unittest.TestCase):
    """Recommended and Comments beside the video playing in the window."""

    KEY = "yt:aaaaaaaaaaa"

    def make(self, key=KEY):
        from weave.ui.bridge import WATCHING, Bridge

        class Video:
            def __init__(self):
                self.track = {"key": key}
                self.queue = [{"key": key}]
                self.length = 300
                self.played = []

            def play_now(self, item, at_s=None):
                self.played.append(item)

        bridge = Bridge.__new__(Bridge)
        QObject.__init__(bridge)
        bridge._db = scratch_db(self)
        # Held by the worker and never read here.
        bridge._cfg = None
        bridge._video = Video()
        bridge._audio = None
        bridge._view_kind = WATCHING
        bridge._watch_tab = "video"
        bridge._watch_rec_open = False
        bridge._watch_on = key
        bridge._watch_comments = []
        bridge._watch_threads = 5
        bridge._watch_busy = ""
        bridge._watch_detail = None
        bridge._detail_key = ""
        bridge._detail_closed = False
        bridge._detail_loading = False
        bridge._detail_comments = []
        bridge._detail_threads = 5
        bridge._web_results = [{"key": key}]
        bridge._companion_cache = {}
        bridge.launched = []
        bridge._launch = lambda worker: bridge.launched.append(worker) or True
        bridge._set_status = lambda words: None
        return bridge

    def test_recommended_follows_the_video_playing_here(self):
        from weave.ui.bridge import Bridge

        bridge = self.make()
        self.assertEqual(Bridge._rec_video(bridge), "", "not while the tab is shut")
        followed = []
        bridge._companion_follow = lambda: followed.append(Bridge._rec_video(bridge))
        Bridge.setWatchTab(bridge, "recommended")
        self.assertEqual(followed, ["aaaaaaaaaaa"])
        self.assertEqual(Bridge._rec_video(self.make("twitch:somebody")), "",
                         "YouTube recommends nothing beside a Twitch stream")

    def test_a_tile_pressed_plays_it_now(self):
        from weave.ui.bridge import Bridge

        bridge = self.make()
        bridge._db.set_state("companion_chip", "Mix")
        bridge._companion_cache["aaaaaaaaaaa"] = {
            "chips": [{"label": "Mix", "token": ""}],
            "cards": {"Mix": [{"video_id": "bbbbbbbbbbb", "title": "B", "channel": "Chan",
                               "channel_id": "UC" + "c" * 22, "duration": "2:05",
                               "picture": ""}]}}
        Bridge.playWatchRecommended(bridge, 0)
        item = bridge._video.played[0]
        self.assertEqual((item["key"], item["channelKey"], item["duration_s"]),
                         ("yt:bbbbbbbbbbb", "yt:UC" + "c" * 22, 125))
        self.assertEqual(item["url"], "https://www.youtube.com/watch?v=bbbbbbbbbbb")

    def test_comments_the_panel_is_reading_are_waited_for_not_asked_twice(self):
        from weave.ui.bridge import Bridge

        bridge = self.make()
        bridge._detail_key = self.KEY
        bridge._detail_loading = True
        Bridge.readWatchComments(bridge)
        self.assertEqual((bridge.launched, bridge._watch_busy), ([], "comments"))
        Bridge._on_comments(bridge, self.KEY, [{"text": "one"}])
        self.assertEqual((bridge._watch_comments, bridge._watch_busy), ([{"text": "one"}], ""))

    def test_comments_the_panel_has_read_are_taken(self):
        from weave.ui.bridge import Bridge

        bridge = self.make()
        bridge._detail_key = self.KEY
        bridge._detail_comments = [{"text": "kept"}]
        Bridge.readWatchComments(bridge)
        self.assertEqual((bridge.launched, bridge._watch_comments), ([], [{"text": "kept"}]))

    def test_comments_are_read_here_when_the_panel_is_on_another_video(self):
        from weave.ui.bridge import Bridge

        bridge = self.make()
        bridge._detail_key = "yt:ccccccccccc"
        with mock.patch("weave.ui.bridge.DetailFetcher") as fetcher:
            Bridge.readWatchComments(bridge)
        self.assertEqual(len(bridge.launched), 1)
        self.assertEqual(fetcher.call_args.args[2:5],
                         (self.KEY, "aaaaaaaaaaa",
                          "https://www.youtube.com/watch?v=aaaaaaaaaaa"))
        self.assertEqual(bridge._watch_busy, "comments")

    def test_a_new_video_starts_its_tabs_afresh(self):
        from weave.ui.bridge import Bridge

        bridge = self.make()
        bridge._watch_comments = [{"text": "old"}]
        Bridge._on_watch_track(bridge)
        self.assertEqual(bridge._watch_comments, [{"text": "old"}], "the same video")
        bridge._video.track = {"key": "yt:ddddddddddd"}
        Bridge._on_watch_track(bridge)
        self.assertEqual(bridge._watch_comments, [])

    def test_times_in_its_comments_go_to_that_point(self):
        from weave.ui.bridge import Bridge

        bridge = self.make()
        bridge._watch_comments = [{"text": "at 1:00 and 9:00", "replies": []}]
        markup = Bridge._get_watch_comments(bridge)[0]["markup"]
        self.assertIn("weave-seek:60", markup)
        self.assertNotIn("weave-seek:540", markup, "past the end of the video")

    def test_the_panel_follows_the_video_that_starts(self):
        from weave.ui.bridge import Bridge

        bridge = self.make()
        opened = []
        bridge._set_starting = lambda key, clear_after_s=0: None
        bridge.openDetail = opened.append
        Bridge._on_video_started(bridge, self.KEY)
        self.assertEqual(opened, [self.KEY])


class AnUpgradedCopy(unittest.TestCase):
    """A copy from before the choice keeps mpv; a fresh one is asked."""

    def test_an_older_database_keeps_mpv(self):
        import tempfile
        from pathlib import Path

        from weave.db import Database

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            db = Database(path)
            self.assertIsNone(db.get_state("videos_in"), "a fresh copy has not chosen")
            with db.conn as conn:
                conn.execute("UPDATE meta SET value='51' WHERE key='schema_version'")
            db.close()
            again = Database(path)
            self.assertEqual(again.get_state("videos_in"), "mpv")
            again.close()

    def test_a_choice_already_made_is_kept(self):
        import tempfile
        from pathlib import Path

        from weave.db import Database

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            db = Database(path)
            db.set_state("videos_in", "weave")
            with db.conn as conn:
                conn.execute("UPDATE meta SET value='51' WHERE key='schema_version'")
            db.close()
            again = Database(path)
            self.assertEqual(again.get_state("videos_in"), "weave")
            again.close()


class Positions(unittest.TestCase):
    def test_kept_and_forgotten(self):
        db = scratch_db(self)
        self.assertIsNone(db.video_position("yt:a"))
        db.set_video_position("yt:a", 12.5, 300.0)
        db.set_video_position("yt:a", 20.0, 300.0)
        self.assertEqual(db.video_position("yt:a"), (20.0, 300.0))
        db.forget_video_position("yt:a")
        self.assertIsNone(db.video_position("yt:a"))


class WherePressesGo(unittest.TestCase):
    """The setting, and the card asked once to go the other way."""

    WRAPPER = ("/usr/local/bin/mpv-ff2mpv-single.sh",)

    def make(self, chosen, command=WRAPPER, configured="auto"):
        from weave.ui.bridge import Bridge

        class Player:
            pass

        class Settings:
            player_command = configured

        bridge = Bridge.__new__(Bridge)
        bridge._db = scratch_db(self)
        bridge._cfg = Settings()
        bridge._player = Player()
        bridge._player.command = list(command) if command else None
        bridge._video = object()
        bridge._elsewhere_key = ""
        if chosen:
            bridge._db.set_state("videos_in", chosen)
        return bridge

    def test_never_chosen_is_mpv_where_one_was_set_up_for_it(self):
        from weave.ui.bridge import Bridge

        self.assertFalse(Bridge._plays_here(self.make(None), "yt:a"), "the wrapper")
        self.assertFalse(Bridge._plays_here(
            self.make(None, command=("/usr/bin/mpv", "--fs"), configured="mpv --fs"), "yt:a"),
            "a player written into the config")
        self.assertTrue(Bridge._plays_here(self.make(None, command=("/usr/bin/mpv",)), "yt:a"),
                        "mpv only installed")
        self.assertTrue(Bridge._plays_here(self.make(None, command=None), "yt:a"), "no mpv")

    def test_with_no_mpv_at_all_it_is_the_window_whatever_was_chosen(self):
        from weave.ui.bridge import Bridge

        bridge = self.make("mpv", command=None)
        self.assertTrue(Bridge._plays_here(bridge, "yt:a"))
        self.assertFalse(Bridge.mpvFound.fget(bridge))
        self.assertTrue(Bridge.mpvFound.fget(self.make("mpv")))

    def test_chosen_is_chosen(self):
        from weave.ui.bridge import Bridge

        self.assertTrue(Bridge._plays_here(self.make("weave"), "yt:a"))
        self.assertFalse(Bridge._plays_here(self.make("mpv"), "yt:a"))

    def test_the_other_way_once(self):
        from weave.ui.bridge import Bridge

        bridge = self.make("weave")
        bridge._elsewhere_key = "yt:a"
        self.assertTrue(Bridge._plays_here(bridge, "yt:b"), "another card is not asked")
        self.assertFalse(Bridge._plays_here(bridge, "yt:a"))
        self.assertTrue(Bridge._plays_here(bridge, "yt:a"), "only once")


def card(name, **marks):
    ext_id = (name * 11)[:11]
    row = {"key": f"yt:{ext_id}", "url": f"https://www.youtube.com/watch?v={ext_id}",
           "title": name.upper(), "isLive": False, "isUpcoming": False, "isLocked": False}
    row.update(marks)
    return row


class QueuedFromTheWindow(unittest.TestCase):
    """The card menu's Play next and Add to queue, a box's Play all, and a
    song watched as a video, in either place videos play."""

    def make(self, chosen, rows=(), queued=False):
        from weave.ui.bridge import BOX, Bridge

        class Player:
            command = ["mpv"]

            def __init__(self):
                self.played = []

            def play(self, url, twitch_login=None, live=False):
                self.played.append(url)
                return True

        class Video:
            def __init__(self):
                self.hasQueue = queued
                self.calls = []

            def add_item(self, item, play_next=False):
                self.calls.append(("add", item["key"], play_next))

            def play_list(self, items, at_s=None):
                self.calls.append(("play", [item["key"] for item in items]))
                self.items = items
                self.hasQueue = True

        class Model:
            def __init__(self, rows):
                self.rows = list(rows)

            def row_for_key(self, key):
                return next((row for row in self.rows if row["key"] == key), None)

            def row_at(self, index):
                return self.rows[index] if 0 <= index < len(self.rows) else None

            def rowCount(self):
                return len(self.rows)

        bridge = Bridge.__new__(Bridge)
        bridge._db = scratch_db(self)
        bridge._db.set_state("videos_in", chosen)
        bridge._player = Player()
        bridge._video = Video()
        bridge._model = Model(rows)
        bridge._elsewhere_key = ""
        bridge._view_kind = BOX
        bridge._view_playlist = ""
        bridge._queue_on_start = None
        bridge.views, bridge.notices = [], []
        bridge._set_view = lambda kind, view_id=-1, *rest: bridge.views.append(kind)
        bridge._set_notice = lambda words, clear_after_s=0: bridge.notices.append(words)
        bridge._set_status = lambda words: None
        bridge._set_starting = lambda key, clear_after_s=0: None
        return bridge

    def test_into_an_empty_queue_it_plays_at_once(self):
        bridge = self.make("weave", [card("a")])
        bridge.queueVideo(card("a")["key"], False)
        self.assertEqual(bridge._video.calls, [("play", [card("a")["key"]])])
        self.assertEqual(bridge.views, ["watching"])

    def test_into_a_queue_it_waits_its_turn(self):
        bridge = self.make("weave", [card("a"), card("b")], queued=True)
        bridge.queueVideo(card("a")["key"], True)
        bridge.queueVideo(card("b")["key"], False)
        self.assertEqual(bridge._video.calls, [("add", card("a")["key"], True),
                                               ("add", card("b")["key"], False)])
        self.assertEqual(bridge.notices, ["Playing it next", "Added to the video queue"])
        self.assertEqual(bridge.views, [], "the page is not opened over what is open")

    def test_a_stream_not_on_air_is_not_queued(self):
        bridge = self.make("weave", [card("a", isUpcoming=True)], queued=True)
        bridge.queueVideo(card("a")["key"], False)
        self.assertEqual(bridge._video.calls, [])

    def test_play_all_fills_the_window_queue_in_order(self):
        rows = [card("a"), card("b", isUpcoming=True), card("c", isLocked=True), card("d"),
                {**card("e"), "key": "twitch:somebody"}, card("f")]
        bridge = self.make("weave", rows)
        bridge.playBox()
        self.assertEqual(bridge._video.calls,
                         [("play", [card("a")["key"], card("d")["key"], card("f")["key"]])])
        self.assertEqual(bridge._player.played, [])

    def test_play_all_hands_mpv_the_first_and_the_rest_after(self):
        bridge = self.make("mpv", [card("a"), card("b"), card("c")])
        bridge.playBox()
        self.assertEqual(bridge._player.played, [card("a")["url"]])
        self.assertEqual(bridge._queue_on_start[0], card("a")["key"])
        self.assertEqual(bridge._queue_on_start[1], [card("b")["url"], card("c")["url"]])
        self.assertEqual(bridge._video.calls, [])

    def test_play_all_is_only_a_box_s(self):
        from weave.ui.bridge import ALL

        bridge = self.make("weave", [card("a")])
        bridge._view_kind = ALL
        bridge.playBox()
        self.assertEqual(bridge._video.calls, [])

    def test_a_music_box_fills_the_window_queue_from_the_song_pressed(self):
        bridge = self.make("weave")
        songs = [{"key": f"yt:{(name * 11)[:11]}", "videoId": (name * 11)[:11],
                  "title": name.upper(), "artist": "Band", "artistId": "", "album": "",
                  "thumbnail": "", "duration": "3:05"} for name in "xyz"]
        bridge._music_tab = 7
        bridge._box_rows = lambda box_id: songs
        bridge.watchSong("tab", 1, -1)
        self.assertEqual(bridge._video.calls, [("play", [songs[1]["key"], songs[2]["key"]])])
        entry = bridge._video.items[0]
        self.assertEqual(entry["channel"], "Band", "the artist where a channel would be")
        self.assertEqual(entry["duration_s"], 185)
        self.assertEqual(entry["url"], "https://www.youtube.com/watch?v=yyyyyyyyyyy")
        self.assertEqual(bridge._player.played, [])

    def test_a_music_box_in_mpv_is_handed_over_as_before(self):
        bridge = self.make("mpv")
        songs = [{"key": f"yt:{(name * 11)[:11]}", "videoId": (name * 11)[:11],
                  "title": name.upper(), "artist": "Band", "artistId": "", "album": "",
                  "thumbnail": "", "duration": "3:05"} for name in "xyz"]
        bridge._music_tab = 7
        bridge._box_rows = lambda box_id: songs
        bridge._hand_over = lambda key, url, title, login, live: bridge._player.play(url)
        bridge.watchSong("tab", 1, -1)
        self.assertEqual(bridge._player.played, ["https://www.youtube.com/watch?v=yyyyyyyyyyy"])
        self.assertEqual(bridge._queue_on_start[1],
                         ["https://www.youtube.com/watch?v=zzzzzzzzzzz"])
        self.assertEqual(bridge._video.calls, [])


if __name__ == "__main__":
    unittest.main()
