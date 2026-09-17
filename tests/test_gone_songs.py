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

import unittest

from tests.support import scratch_db
from weave.audio import reads_as_gone


class WhatReadsAsGone(unittest.TestCase):
    def test_the_words_a_deleted_one_comes_back_with(self):
        # Measured against two real ones he reported.
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
        self.player._on_resolve_failed(
            "yt:aaa", "Video unavailable. This video is not available")
        self.assertEqual(self.said, ["yt:aaa"])
        self.assertEqual([entry["key"] for entry in self.player._queue],
                         ["yt:bbb", "yt:ccc"])
        self.assertEqual(self.player.track["title"], "bbb")

    def test_and_it_is_not_reported_as_a_track_that_would_not_play(self):
        """Nothing went wrong here and there is nothing to try again."""
        self.player._on_resolve_failed(
            "yt:aaa", "Video unavailable. This video is not available")
        self.assertEqual(self.failures, [])

    def test_an_ordinary_failure_still_says_so_and_keeps_the_queue(self):
        self.player._on_resolve_failed("yt:aaa", "the address could not be read")
        self.assertEqual(self.said, [])
        self.assertEqual(self.failures, ["the address could not be read"])
        self.assertEqual(len(self.player._queue), 3)

    def test_a_failure_about_some_other_song_is_dropped(self):
        self.player._on_resolve_failed(
            "yt:ccc", "Video unavailable. This video is not available")
        self.assertEqual(self.said, [])
        self.assertEqual(len(self.player._queue), 3)


if __name__ == "__main__":
    unittest.main()
