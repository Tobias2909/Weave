"""A song pressed and found to be gone from YouTube.

A playlist read from YouTube already arrives without its private and deleted
entries: the listing says which of its rows nobody can resolve, those are
dropped, and the foot of the page says how many were left out. What that
cannot catch is a video that went private or was deleted since the list was
read. Until this, such a row sat in the list looking playable and gave a
failure every time it was pressed.

The discriminator matters as much as the act. A video that cannot be played
HERE is not a video that has gone: a country lock, a membership, an age gate
and a login problem are all about this copy of the application, and YouTube
opens the country lock with the same two words as a deletion.
"""

import tempfile
import unittest
from pathlib import Path

from tests.support import scratch_db
from weave.audio import reads_as_gone
from weave.db import Database, VideoRow

CHANNEL = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"


class WhatReadsAsGone(unittest.TestCase):
    def test_the_words_a_deleted_one_comes_back_with(self):
        # Measured against two real ones.
        self.assertTrue(reads_as_gone("Video unavailable. This video is not available"))

    def test_a_private_one_even_though_it_also_invites_you_to_sign_in(self):
        """Read from yt-dlp's own source: the reason and the subreason are
        joined, so a private video says both things in one sentence and a
        login hint is added on top. Treating the invitation as a reason to
        keep it would throw away exactly the case this exists for."""
        self.assertTrue(reads_as_gone(
            "Private video. Sign in if you've been granted access to this video. "
            "Use --cookies-from-browser or --cookies for the authentication"))

    def test_and_an_account_that_was_taken_down(self):
        self.assertTrue(reads_as_gone(
            "This video is no longer available because the YouTube account "
            "associated with this video has been terminated"))

    def test_and_one_removed_for_breaking_the_rules(self):
        self.assertTrue(reads_as_gone(
            "This video has been removed for violating YouTube's policy on hate speech"))

    def test_one_the_uploader_took_down(self):
        self.assertTrue(reads_as_gone(
            "Video unavailable. This video has been removed by the uploader"))

    def test_a_country_lock_is_not_a_deletion(self):
        """The one that matters: YouTube opens this with the same two words."""
        self.assertFalse(reads_as_gone(
            "Video unavailable. The uploader has not made this video available "
            "in your country"))

    def test_nor_is_a_membership_or_an_age_gate_or_a_login(self):
        for said in ("Join this channel to get access to members only content",
                     "Sign in to confirm your age. This video may be inappropriate",
                     "Sign in to confirm you are not a bot",
                     "The following content is not available on this app",
                     "This video is available to Premium members"):
            self.assertFalse(reads_as_gone(said), said)

    def test_an_ordinary_failure_says_nothing_about_the_video(self):
        for said in ("", "the track could not be played", "Unable to download webpage",
                     "the connection was lost"):
            self.assertFalse(reads_as_gone(said), said)


class ItLeavesEveryListThatHeldIt(unittest.TestCase):
    def setUp(self):
        self.db = scratch_db(self)
        self.db.replace_playlists([
            {"ext_id": "PL1", "title": "One"},
            {"ext_id": "PL2", "title": "Two"},
        ])
        rows = [{"ext_id": "aaaaaaaaaaa", "title": "A song"},
                {"ext_id": "bbbbbbbbbbb", "title": "Another"}]
        self.db.replace_playlist_items("PL1", rows, skipped=2)
        self.db.replace_playlist_items("PL2", [rows[0]], skipped=0)

    def keys(self, playlist):
        return [row["key"] for row in self.db.playlist_items(playlist)]

    def test_it_goes_from_all_of_them(self):
        self.assertEqual(self.db.forget_playlist_item("aaaaaaaaaaa"), 2)
        self.assertEqual(self.keys("PL1"), ["yt:bbbbbbbbbbb"])
        self.assertEqual(self.keys("PL2"), [])

    def test_and_is_counted_as_one_more_left_out(self):
        """The same count the fetch itself keeps, since that is what it is."""
        self.db.forget_playlist_item("aaaaaaaaaaa")
        self.assertEqual(self.db.playlist("PL1")["skipped"], 3)
        self.assertEqual(self.db.playlist("PL2")["skipped"], 1)

    def test_one_that_is_in_no_list_changes_nothing(self):
        self.assertEqual(self.db.forget_playlist_item("ccccccccccc"), 0)
        self.assertEqual(self.db.playlist("PL1")["skipped"], 2)

    def test_nothing_at_all_is_harmless(self):
        self.assertEqual(self.db.forget_playlist_item(""), 0)

    def test_a_fresh_read_replaces_the_count_with_youtubes_own(self):
        """Which by then counts this one, so the two cannot drift apart."""
        self.db.forget_playlist_item("aaaaaaaaaaa")
        self.db.replace_playlist_items("PL1", [{"ext_id": "bbbbbbbbbbb",
                                                "title": "Another"}], skipped=3)
        self.assertEqual(self.db.playlist("PL1")["skipped"], 3)


class AndItStaysGoneWhenTheListIsReadAgain(unittest.TestCase):
    """The half that was missing.

    A playlist is read again every so often, and the reading came back with
    the song still in it, looking playable. The finding was written to the
    videos row, and a song in a playlist usually has no videos row, so nothing
    was kept and the song was discovered all over again the next time the list
    reached it.
    """

    def setUp(self):
        self.db = scratch_db(self)
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.rows = [{"ext_id": "aaaaaaaaaaa", "title": "A song"},
                     {"ext_id": "bbbbbbbbbbb", "title": "Another"}]
        self.db.replace_playlist_items("PL1", self.rows, skipped=0)

    def keys(self):
        return [row["key"] for row in self.db.playlist_items("PL1")]

    def test_a_song_found_gone_is_left_out_of_the_next_reading(self):
        self.db.mark_unavailable("aaaaaaaaaaa")
        self.db.forget_playlist_item("aaaaaaaaaaa")
        # YouTube hands the whole list back, this song among it.
        self.db.replace_playlist_items("PL1", self.rows, skipped=0)
        self.assertEqual(self.keys(), ["yt:bbbbbbbbbbb"])

    def test_and_is_counted_with_the_ones_the_listing_itself_left_out(self):
        self.db.mark_unavailable("aaaaaaaaaaa")
        self.db.replace_playlist_items("PL1", self.rows, skipped=2)
        self.assertEqual(self.db.playlist("PL1")["skipped"], 3)

    def test_it_holds_for_a_song_that_was_never_in_the_feed(self):
        """Which is nearly all of them. Measured on a real collection, 94 of
        1039 songs sitting in playlists had a videos row."""
        self.assertIsNone(self.db.conn.execute(
            "SELECT 1 FROM videos WHERE ext_id='aaaaaaaaaaa'").fetchone())
        self.db.mark_unavailable("aaaaaaaaaaa")
        self.db.replace_playlist_items("PL1", self.rows, skipped=0)
        self.assertEqual(self.keys(), ["yt:bbbbbbbbbbb"])

    def test_a_list_of_nothing_but_gone_songs_comes_out_empty(self):
        for row in self.rows:
            self.db.mark_unavailable(row["ext_id"])
        self.db.replace_playlist_items("PL1", self.rows, skipped=0)
        self.assertEqual(self.keys(), [])
        self.assertEqual(self.db.playlist("PL1")["skipped"], 2)

    def test_and_a_list_with_none_of_them_is_untouched(self):
        self.db.replace_playlist_items("PL1", self.rows, skipped=1)
        self.assertEqual(self.keys(), ["yt:aaaaaaaaaaa", "yt:bbbbbbbbbbb"])
        self.assertEqual(self.db.playlist("PL1")["skipped"], 1)


class AndThereIsAWayBack(unittest.TestCase):
    """A finding never expires, so a wrong one would last for ever."""

    def setUp(self):
        self.db = scratch_db(self)
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.rows = [{"ext_id": "aaaaaaaaaaa", "title": "A song"}]
        self.db.replace_playlist_items("PL1", self.rows, skipped=0)
        self.db.mark_unavailable("aaaaaaaaaaa")

    def test_taking_it_back_lets_the_next_reading_hold_it_again(self):
        self.assertEqual(self.db.forget_gone("aaaaaaaaaaa"), 1)
        self.assertFalse(self.db.is_gone("aaaaaaaaaaa"))
        self.db.replace_playlist_items("PL1", self.rows, skipped=0)
        self.assertEqual([row["key"] for row in self.db.playlist_items("PL1")],
                         ["yt:aaaaaaaaaaa"])

    def test_taking_back_one_that_is_not_there_says_so(self):
        self.assertEqual(self.db.forget_gone("zzzzzzzzzzz"), 0)

    def test_and_all_of_them_at_once(self):
        self.db.mark_unavailable("bbbbbbbbbbb")
        self.assertEqual(self.db.forget_gone(), 2)
        self.assertEqual(self.db.gone_count(), 0)

    def test_the_feed_gets_it_back_too(self):
        """Both marks go, or the feed would still be hiding a video that is
        back in the playlists."""
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "A channel")
        self.db.upsert_videos([VideoRow("youtube", "ccccccccccc", CHANNEL, "A video")])
        self.db.mark_unavailable("ccccccccccc")
        self.assertEqual(self.db.unavailable_count(), 1)
        self.db.forget_gone("ccccccccccc")
        self.assertEqual(self.db.unavailable_count(), 0)
        self.assertEqual([row["ext_id"] for row in self.db.feed()], ["ccccccccccc"])


class WhatAnOlderDatabaseKnew(unittest.TestCase):
    """The upgrade carries the findings that were only in the videos table."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "old.db"
        self.addCleanup(self._tmp.cleanup)

    def make_old(self):
        db = Database(self.path)
        db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "A channel")
        db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", CHANNEL, "A song")])
        db.mark_unavailable("aaaaaaaaaaa")
        with db.conn as conn:
            conn.execute("DROP TABLE gone_videos")
            conn.execute("UPDATE meta SET value='45' WHERE key='schema_version'")
        db.close()

    def test_a_video_marked_before_the_table_existed_is_in_it_after(self):
        self.make_old()
        db = Database(self.path)
        self.addCleanup(db.close)
        self.assertTrue(db.is_gone("aaaaaaaaaaa"))

    def test_and_a_playlist_read_after_the_upgrade_leaves_it_out(self):
        self.make_old()
        db = Database(self.path)
        self.addCleanup(db.close)
        db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        db.replace_playlist_items("PL1", [{"ext_id": "aaaaaaaaaaa", "title": "A song"}],
                                  skipped=0)
        self.assertEqual(db.playlist_items("PL1"), [])


class ItLeavesTheQueue(unittest.TestCase):
    def setUp(self):
        from tests.test_audio import FakeEngine, FakeResolver, track
        from weave.audio import AudioPlayer
        from weave.config import Config

        self.engine = FakeEngine()
        self.player = AudioPlayer(Config(raw={}), engine=self.engine)
        self.player.setShuffle(False)
        self.player.setRepeat(0)
        self.player._make_resolver = lambda entry: FakeResolver(entry["key"])
        self.player._queue = [track(n) for n in ("aaa", "bbb", "ccc")]
        self.player._rebuild_order()
        self.player._at = 0
        self.said = []
        self.player.gone.connect(self.said.append)
        self.failures = []
        self.player.failed.connect(self.failures.append)

    def test_a_song_that_is_gone_leaves_the_queue_and_the_next_one_starts(self):
        self.player._on_resolve_gone("yt:aaa")
        self.assertEqual(self.said, ["yt:aaa"])
        self.assertEqual([entry["key"] for entry in self.player._queue],
                         ["yt:bbb", "yt:ccc"])
        self.assertEqual(self.player.track["title"], "bbb")

    def test_and_it_is_not_reported_as_a_track_that_would_not_play(self):
        """Nothing went wrong here and there is nothing to try again."""
        self.player._on_resolve_gone("yt:aaa")
        self.assertEqual(self.failures, [])

    def test_an_ordinary_failure_still_says_so_and_keeps_the_queue(self):
        self.player._on_resolve_failed("yt:aaa", "the address could not be read")
        self.assertEqual(self.said, [])
        self.assertEqual(self.failures, ["the address could not be read"])
        self.assertEqual(len(self.player._queue), 3)

    def test_a_report_about_some_other_song_is_dropped(self):
        self.player._on_resolve_gone("yt:ccc")
        self.assertEqual(self.said, [])
        self.assertEqual(len(self.player._queue), 3)


class ItIsCaughtBeforeItIsReached(unittest.TestCase):
    """The case that matters in practice.

    A song is seldom pressed. It comes round in the queue, and until this the
    answer arrived with nobody listening: nothing was handed to mpv for it, so
    the listening ended on the song before, saying nothing, and the dead one
    stayed in the queue and in the playlist it came from.
    """

    def setUp(self):
        from tests.test_audio import FakeEngine, FakeResolver, track
        from weave.audio import AudioPlayer
        from weave.config import Config

        self.engine = FakeEngine()
        self.player = AudioPlayer(Config(raw={}), engine=self.engine)
        self.player.setShuffle(False)
        self.player.setRepeat(0)
        self.made = []

        def resolver(entry):
            made = FakeResolver(entry["key"])
            self.made.append(made)
            return made

        self.player._make_resolver = resolver
        self.player._queue = [track(n) for n in ("aaa", "bbb", "ccc")]
        self.player._rebuild_order()
        self.player._at = 0
        self.player._idle = False
        self.said = []
        self.player.gone.connect(self.said.append)
        self.failures = []
        self.player.failed.connect(self.failures.append)

    def look_ahead(self):
        """Resolve the song after this one, the way playing one does."""
        self.player._arrange_next()
        return self.made[-1]

    def test_the_look_ahead_listens_to_the_answer_at_all(self):
        ahead = self.look_ahead()
        self.assertEqual(ahead.key, "yt:bbb")
        ahead.gone.emit("yt:bbb")
        self.assertEqual(self.said, ["yt:bbb"])

    def test_and_it_leaves_the_queue_without_the_listening_stopping(self):
        ahead = self.look_ahead()
        ahead.gone.emit("yt:bbb")
        self.assertEqual([entry["key"] for entry in self.player._queue],
                         ["yt:aaa", "yt:ccc"])
        # The one playing is untouched, and what follows it is the live one.
        self.assertEqual(self.player.track["title"], "aaa")
        self.assertEqual(self.player._next_index(), 1)

    def test_it_is_not_reported_as_a_track_that_would_not_play(self):
        self.look_ahead().gone.emit("yt:bbb")
        self.assertEqual(self.failures, [])

    def test_every_copy_of_it_goes(self):
        """A song that is gone is gone wherever it sits in the queue, and
        leaving the later ones would stop the listening again further on."""
        from tests.test_audio import track

        self.player._queue.append(track("bbb"))
        self.player._rebuild_order()
        self.look_ahead().gone.emit("yt:bbb")
        self.assertEqual([entry["key"] for entry in self.player._queue],
                         ["yt:aaa", "yt:ccc"])

    def test_one_that_arrives_after_the_queue_moved_past_it_still_goes(self):
        """The answer takes seconds and the queue can move in them. It is
        looked up by key rather than by where it was."""
        ahead = self.look_ahead()
        self.player._at = 2
        ahead.gone.emit("yt:bbb")
        self.assertEqual([entry["key"] for entry in self.player._queue],
                         ["yt:aaa", "yt:ccc"])
        self.assertEqual(self.player.track["title"], "ccc")

    def test_one_about_a_song_that_is_no_longer_in_the_queue_is_harmless(self):
        ahead = self.look_ahead()
        self.player._queue = [track_key for track_key in self.player._queue
                              if track_key["key"] != "yt:bbb"]
        self.player._rebuild_order()
        ahead.gone.emit("yt:bbb")
        self.assertEqual(self.said, ["yt:bbb"])
        self.assertEqual(len(self.player._queue), 2)


class WhatTheWindowSaysAboutIt(unittest.TestCase):
    """Which song the notice is about.

    A press is about the song in front of you and "that one" is clear. The
    look-ahead is about a song nobody has reached yet, while the one playing
    carries on without trouble, and "that one" there points at the wrong song
    and reads as a complaint about what is being heard.
    """

    class Nothing:
        def emit(self, *_a):
            pass

    class Lists:
        def forget_playlist_item(self, _ext_id):
            return 1

        def mark_unavailable(self, _ext_id):
            pass

    class Player:
        def __init__(self, playing):
            self.track = {"key": playing}

    def notice_for(self, gone, playing):
        from weave.ui.bridge import Bridge

        bridge = Bridge.__new__(Bridge)
        bridge._db = self.Lists()
        bridge._audio = self.Player(playing)
        said = []
        bridge._set_notice = lambda text, **_k: said.append(text)
        bridge._set_status = lambda *_a, **_k: None
        bridge.playlistSkippedChanged = self.Nothing()
        bridge.playlistsChanged = self.Nothing()
        bridge.reload = lambda: None
        Bridge._on_song_gone(bridge, gone)
        return said[-1]

    def test_the_one_he_pressed_is_that_one(self):
        self.assertTrue(self.notice_for("yt:aaa", playing="yt:aaa")
                        .startswith("That one is private"))

    def test_one_found_ahead_of_him_is_the_next_one(self):
        self.assertTrue(self.notice_for("yt:bbb", playing="yt:aaa")
                        .startswith("The next one is private"))

    def test_and_both_say_what_became_of_it(self):
        for notice in (self.notice_for("yt:aaa", playing="yt:aaa"),
                       self.notice_for("yt:bbb", playing="yt:aaa")):
            self.assertIn("deleted", notice)
            self.assertIn("out of the list", notice)


class AskingWhetherThereIsAnythingToPlay(unittest.TestCase):
    """The sentence a failed resolve comes back with is not enough to decide
    on, so a second question is asked.

    MEASURED against two real ones: asking for an address answers
    "Video unavailable" and nothing else, no reason and no second line, and a
    video blocked in this country opens with those same two words. Asking for
    the extraction instead answers in full, and both came back rc 0,
    availability "unlisted", a title, a channel, a length, an upload date and
    ZERO formats. They are not deleted. They exist and YouTube offers nothing
    to play, which from here is the same thing.
    """

    def answer(self, stdout="", stderr="", returncode=0):
        from weave import audio
        from weave.config import Config

        class Result:
            pass

        result = Result()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        was = audio.run_process
        audio.run_process = lambda *a, **k: result
        try:
            return audio.nothing_to_play(Config(raw={}), "https://example/watch")
        finally:
            audio.run_process = was

    def test_an_extraction_that_offers_no_format_at_all(self):
        self.assertTrue(self.answer(stdout="unlisted|not_live|NA\n"))

    def test_one_that_offers_a_format_is_playable(self):
        self.assertFalse(self.answer(stdout="public|not_live|251\n"))

    def test_a_run_that_did_not_finish_says_nothing(self):
        """The one that matters most. A broken solver or a stale cookie makes
        every video in the library fail, and reading that as every video being
        gone would empty a whole playlist."""
        self.assertFalse(self.answer(stdout="", returncode=1))
        self.assertFalse(self.answer(stdout="", stderr="ERROR: no", returncode=1))

    def test_nor_does_one_yt_dlp_complained_about_the_challenge_on(self):
        said = ("WARNING: [youtube] Signature solving failed. Ensure you have a "
                "supported JavaScript runtime and challenge solver script "
                "distribution installed")
        self.assertFalse(self.answer(stdout="public|not_live|NA\n", stderr=said))

    def test_behind_a_membership_is_not_gone(self):
        self.assertFalse(self.answer(stdout="subscriber_only|not_live|NA\n"))

    def test_nor_is_one_that_has_not_started(self):
        self.assertFalse(self.answer(stdout="public|is_upcoming|NA\n"))

    def test_nor_is_one_on_the_air(self):
        self.assertFalse(self.answer(stdout="public|is_live|NA\n"))


if __name__ == "__main__":
    unittest.main()
