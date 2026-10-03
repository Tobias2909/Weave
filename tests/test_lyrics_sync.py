"""The Lyrics tab following the song.

The words arrive line by line with when each line is sung, the page shows the
line being sung and the one after it, and a music video borrows the words of
the song it is the video of, timed only when the two are the same length.
"""

import unittest
from unittest import mock

from PySide6.QtCore import QObject

from weave.poller import SongSide
from weave.sources import ytmusic
from weave.ui.bridge import REST, Bridge, sung_at


class Line:
    """Shaped as the library's own timed line."""

    def __init__(self, text: str, start: int, end: int) -> None:
        self.text = text
        self.start_time = start
        self.end_time = end
        self.id = start


TIMED = {"lyrics": [Line("♪", 0, 13560), Line("I've been tryna call", 13560, 16280),
                    Line("I've been on my own for long enough", 16280, 20000)],
         "source": "Source: Somebody", "hasTimestamps": True}


class FakeClient:
    def __init__(self, lyrics=None, watch=None, fails=False) -> None:
        self.lyrics = lyrics
        self.watch = watch or {}
        self.fails = fails
        self.asked: list = []

    def get_lyrics(self, browse_id, timestamps=False):
        self.asked.append((browse_id, timestamps))
        if self.fails:
            raise RuntimeError("Server returned HTTP 400: Bad Request.")
        return self.lyrics

    def get_watch_playlist(self, videoId, limit=40):
        self.asked.append(videoId)
        return self.watch


class TheTimedWords(unittest.TestCase):
    def test_timed_words_come_as_lines_in_seconds(self) -> None:
        anonymous = FakeClient(lyrics=TIMED)
        with mock.patch.object(ytmusic, "_anonymous", lambda: anonymous):
            found = ytmusic.lyrics(None, "MPLYt_x", timed=True)
        self.assertEqual(anonymous.asked, [("MPLYt_x", True)])
        self.assertEqual(found["lines"][1], {"at": 13.56, "end": 16.28,
                                             "text": "I've been tryna call"})
        self.assertEqual(found["source"], "Source: Somebody")
        # The block of words leaves the marks for music out.
        self.assertEqual(found["text"], "I've been tryna call\n"
                                        "I've been on my own for long enough")

    def test_a_refused_timed_request_falls_back_to_the_words_signed_in(self) -> None:
        # Signed in, the timed request is refused with a 400. Without the
        # login it answers, and if that fails too the words still come.
        signed = FakeClient(lyrics={"lyrics": "one\ntwo", "source": "S"})
        with mock.patch.object(ytmusic, "_anonymous", lambda: FakeClient(fails=True)), \
                mock.patch.object(ytmusic, "client", lambda _p: signed):
            found = ytmusic.lyrics(None, "MPLYt_x", timed=True)
        self.assertEqual(found, {"text": "one\ntwo", "source": "S", "lines": []})
        self.assertEqual(signed.asked, [("MPLYt_x", False)])

    def test_words_with_no_timing_come_as_one_block_from_the_one_request(self) -> None:
        anonymous = FakeClient(lyrics={"lyrics": "one\ntwo", "source": "S",
                                       "hasTimestamps": False})
        signed = FakeClient()
        with mock.patch.object(ytmusic, "_anonymous", lambda: anonymous), \
                mock.patch.object(ytmusic, "client", lambda _p: signed):
            found = ytmusic.lyrics(None, "MPLYt_x", timed=True)
        self.assertEqual(found["text"], "one\ntwo")
        self.assertEqual(found["lines"], [])
        self.assertEqual(signed.asked, [], "the words were asked for twice")

    def test_untimed_asks_signed_in_as_it_always_did(self) -> None:
        signed = FakeClient(lyrics={"lyrics": "one", "source": "S"})
        with mock.patch.object(ytmusic, "_anonymous",
                               lambda: self.fail("asked without the login")), \
                mock.patch.object(ytmusic, "client", lambda _p: signed):
            found = ytmusic.lyrics(None, "MPLYt_x")
        self.assertEqual(found["text"], "one")


class TheOtherHalf(unittest.TestCase):
    def test_a_station_answer_names_the_song_beside_a_video(self) -> None:
        answer = {"lyrics": None, "tracks": [{
            "videoId": "omv", "title": "A video", "length": "4:23",
            "videoType": "MUSIC_VIDEO_TYPE_OMV",
            "counterpart": {"videoId": "song", "length": "3:22"}}]}
        with mock.patch.object(ytmusic, "client", lambda _p: FakeClient(watch=answer)):
            found = ytmusic.watch(None, "omv", limit=1)
        self.assertEqual(found["counterpart_id"], "song")
        self.assertEqual(found["counterpart_length_s"], 202)
        self.assertEqual(found["length_s"], 263)
        self.assertEqual(found["video_type"], "MUSIC_VIDEO_TYPE_OMV")

    def test_no_counterpart_is_none(self) -> None:
        answer = {"tracks": [{"videoId": "a", "length": "3:00"}]}
        with mock.patch.object(ytmusic, "client", lambda _p: FakeClient(watch=answer)):
            found = ytmusic.watch(None, "a", limit=1)
        self.assertIsNone(found["counterpart_id"])
        self.assertIsNone(found["counterpart_length_s"])
        self.assertEqual(found["video_type"], "")


def station(kind: str, mine: int | None, theirs: int | None, words: str | None = None,
            other: str | None = "song") -> dict:
    return {"tracks": [], "lyrics_id": words, "related_id": None, "video_type": kind,
            "length_s": mine, "counterpart_id": other, "counterpart_length_s": theirs}


class WhenTheTimingFits(unittest.TestCase):
    def test_a_song_is_its_own_timing(self) -> None:
        self.assertTrue(SongSide.in_step(station(SongSide.SONG, 202, 263)))
        self.assertTrue(SongSide.in_step(station("", None, None)))

    def test_a_video_as_long_as_its_song_follows_it(self) -> None:
        # Get Lucky: 4:09 as a video and 4:09 as a song.
        self.assertTrue(SongSide.in_step(station("MUSIC_VIDEO_TYPE_OMV", 249, 249)))
        self.assertTrue(SongSide.in_step(station("MUSIC_VIDEO_TYPE_OMV", 251, 249)))

    def test_a_video_with_an_intro_of_its_own_does_not(self) -> None:
        # Blinding Lights, 4:23 against 3:22, and Bohemian Rhapsody, 6:00
        # against 5:55.
        self.assertFalse(SongSide.in_step(station("MUSIC_VIDEO_TYPE_OMV", 263, 202)))
        self.assertFalse(SongSide.in_step(station("MUSIC_VIDEO_TYPE_OMV", 360, 355)))

    def test_a_video_with_no_song_beside_it_does_not(self) -> None:
        self.assertFalse(SongSide.in_step(station("MUSIC_VIDEO_TYPE_UGC", 200, None,
                                                  other=None)))


class TheMusicVideo(unittest.TestCase):
    def run_side(self, answers: dict, words_id: str = "", synced: bool = True) -> tuple:
        asked = []

        def watch(_profile, video_id, limit=40):
            asked.append(("watch", video_id))
            return answers[video_id]

        def lyrics(_profile, browse_id, timed=False):
            asked.append(("lyrics", browse_id, timed))
            return {"text": "w", "source": "", "lines": [{"at": 0.0, "end": 1.0, "text": "w"}]
                    if timed else []}

        side = SongSide(None, SongSide.WORDS, "omv", words_id, synced)
        got = []
        side.answered.connect(got.append)
        with mock.patch("weave.poller.cookie_profile", lambda _c: None), \
                mock.patch.object(ytmusic, "watch", watch), \
                mock.patch.object(ytmusic, "lyrics", lyrics):
            side.work()
        return asked, got[0]

    def test_a_video_borrows_the_words_of_its_song_untimed_when_longer(self) -> None:
        asked, answer = self.run_side({
            "omv": station("MUSIC_VIDEO_TYPE_OMV", 263, 202),
            "song": station(SongSide.SONG, 202, 263, words="MPLYt_song", other="omv")})
        self.assertEqual(asked, [("watch", "omv"), ("watch", "song"),
                                 ("lyrics", "MPLYt_song", False)])
        self.assertEqual(answer["wordsId"], "MPLYt_song")
        self.assertFalse(answer["synced"])
        self.assertEqual(answer["lines"], [])

    def test_a_video_as_long_as_its_song_is_followed(self) -> None:
        asked, answer = self.run_side({
            "omv": station("MUSIC_VIDEO_TYPE_OMV", 249, 249),
            "song": station(SongSide.SONG, 249, 249, words="MPLYt_song", other="omv")})
        self.assertEqual(asked[-1], ("lyrics", "MPLYt_song", True))
        self.assertTrue(answer["synced"])
        self.assertEqual(len(answer["lines"]), 1)

    def test_a_kept_address_spends_nothing_on_the_station(self) -> None:
        asked, answer = self.run_side({}, words_id="MPLYt_song", synced=False)
        self.assertEqual(asked, [("lyrics", "MPLYt_song", False)])
        self.assertFalse(answer["synced"])


LINES = [{"at": 0.0, "end": 13.56, "text": "♪"},
         {"at": 13.56, "end": 16.28, "text": "I've been tryna call"},
         {"at": 16.28, "end": 20.0, "text": "On my own"}]
STARTS = [line["at"] for line in LINES]


class TheLineBeingSung(unittest.TestCase):
    def test_the_intro_is_music_with_the_first_line_coming(self) -> None:
        self.assertEqual(sung_at(LINES, STARTS, 3.0),
                         {"at": 0, "now": REST, "next": "I've been tryna call"})

    def test_a_line_is_sung_from_its_start(self) -> None:
        self.assertEqual(sung_at(LINES, STARTS, 13.56)["now"], "I've been tryna call")
        self.assertEqual(sung_at(LINES, STARTS, 13.5)["now"], REST)

    def test_the_last_line_has_nothing_after_it(self) -> None:
        self.assertEqual(sung_at(LINES, STARTS, 18.0),
                         {"at": 2, "now": "On my own", "next": ""})

    def test_after_the_last_line_is_music(self) -> None:
        self.assertEqual(sung_at(LINES, STARTS, 25.0), {"at": 3, "now": REST, "next": ""})

    def test_before_a_first_line_that_starts_late(self) -> None:
        late = LINES[1:]
        self.assertEqual(sung_at(late, [line["at"] for line in late], 2.0),
                         {"at": -1, "now": REST, "next": "I've been tryna call"})


class Recorder:
    def __init__(self) -> None:
        self.count = 0

    def emit(self, *_a) -> None:
        self.count += 1


class FakeAudio:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.track = {"key": "yt:a", "videoId": "a"}


def bridge_with(audio) -> Bridge:
    bridge = Bridge.__new__(Bridge)
    QObject.__init__(bridge)
    bridge._audio = audio
    bridge._now_busy = "words"
    bridge._now_read = set()
    bridge._now_ids = {}
    bridge._now_words = {}
    bridge._now_lines = []
    bridge._now_starts = []
    bridge._now_lyric = {}
    bridge.nowChanged = Recorder()
    bridge.nowLyricChanged = Recorder()
    return bridge


class TheBridge(unittest.TestCase):
    def answer(self, lines, synced=True) -> dict:
        return {"what": SongSide.WORDS, "videoId": "a", "wordsId": "W", "synced": synced,
                "text": "words", "source": "S", "lines": lines}

    def test_timed_words_are_followed_from_where_the_song_is(self) -> None:
        audio = FakeAudio()
        audio.seconds = 14.0
        bridge = bridge_with(audio)
        Bridge._on_now_side(bridge, self.answer(LINES))
        self.assertTrue(bridge._now_words["synced"])
        self.assertEqual(Bridge._get_now_lyric(bridge)["now"], "I've been tryna call")
        self.assertEqual(bridge._now_ids["a"], {"words": "W", "synced": True})

    def test_the_line_is_said_only_when_it_changes(self) -> None:
        audio = FakeAudio()
        bridge = bridge_with(audio)
        Bridge._on_now_side(bridge, self.answer(LINES))
        said = bridge.nowLyricChanged.count
        for tenth in range(1, 30):
            audio.seconds = 13.0 + tenth / 10
            Bridge._follow_words(bridge)
        self.assertEqual(bridge.nowLyricChanged.count - said, 1,
                         "the line was said again while it stayed the same")
        self.assertEqual(bridge._now_lyric["at"], 1)

    def test_words_without_timing_are_a_block(self) -> None:
        bridge = bridge_with(FakeAudio())
        Bridge._on_now_side(bridge, self.answer([], synced=False))
        self.assertFalse(bridge._now_words["synced"])
        self.assertEqual(Bridge._get_now_lyric(bridge), {})
        self.assertEqual(bridge._now_ids["a"], {"words": "W", "synced": False})

    def test_a_song_without_timed_words_costs_nothing_per_tick(self) -> None:
        bridge = bridge_with(FakeAudio())
        Bridge._follow_words(bridge)
        self.assertEqual(bridge.nowLyricChanged.count, 0)


if __name__ == "__main__":
    unittest.main()
