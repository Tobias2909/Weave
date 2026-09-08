"""What a history card can say.

A history row carries an id, a title, a duration and a picture and says nothing
whatsoever about the channel, measured against a real account. So the cards had
no name, no face, no age and no view count, which is most of what a card is.
Two things answer that: what is already stored here, for nothing, and one small
call for the rest.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave.db import Database, VideoRow
from weave.sources import oembed

CHANNEL = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"


def history_row(ext_id: str, **over):
    row = {"ext_id": ext_id, "title": "Something watched", "channel_name": None,
           "channel_ext_id": None, "duration_s": None, "thumbnail_url": None,
           "views": None, "published_at": None, "live_status": None,
           "scheduled_at": None}
    row.update(over)
    return row


class FromWhatIsStored(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "Someone",
                            "https://example.invalid/face.jpg")
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", CHANNEL, "Their video",
                                        published_at=1_700_000_000, duration_s=600,
                                        views=1234, thumbnail_url="a.jpg")])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def card(self, ext_id: str = "aaaaaaaaaaa"):
        return next(row for row in self.db.cached(self.db.HISTORY) if row["ext_id"] == ext_id)

    def test_a_watched_video_that_is_stored_gets_its_channel(self):
        self.db.replace_cached(self.db.HISTORY, [history_row("aaaaaaaaaaa")])
        card = self.card()
        self.assertEqual(card["channel_title"], "Someone")
        self.assertEqual(card["avatar_url"], "https://example.invalid/face.jpg")
        self.assertEqual(card["channel_key"], CHANNEL)

    def test_and_its_age_and_its_views(self):
        self.db.replace_cached(self.db.HISTORY, [history_row("aaaaaaaaaaa")])
        card = self.card()
        self.assertEqual(card["published_at"], 1_700_000_000)
        self.assertEqual(card["views"], 1234)

    def test_what_the_listing_said_still_wins(self):
        # It came from the same reading as the row, so it is about that row.
        self.db.replace_cached(self.db.HISTORY,
                               [history_row("aaaaaaaaaaa", views=99, title="As listed")])
        self.assertEqual(self.card()["views"], 99)

    def test_a_video_nothing_here_knows_stays_blank(self):
        self.db.replace_cached(self.db.HISTORY, [history_row("zzzzzzzzzzz")])
        self.assertIsNone(self.card("zzzzzzzzzzz")["channel_title"])


class FromOneSmallCall(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.replace_cached(self.db.HISTORY, [history_row("zzzzzzzzzzz")])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def card(self):
        return self.db.cached(self.db.HISTORY)[0]

    def test_the_ones_worth_asking_about_are_the_ones_nobody_knows(self):
        self.assertEqual(self.db.videos_without_an_owner(self.db.HISTORY), ["zzzzzzzzzzz"])

    def test_and_an_answer_puts_a_name_on_the_card(self):
        self.db.remember_owner("zzzzzzzzzzz", "A stranger", "stranger")
        self.assertEqual(self.card()["channel_title"], "A stranger")

    def test_a_named_one_is_not_asked_about_again(self):
        self.db.remember_owner("zzzzzzzzzzz", "A stranger", "stranger")
        self.assertEqual(self.db.videos_without_an_owner(self.db.HISTORY), [])

    def test_the_answer_outlives_the_listing_that_needed_it(self):
        # The whole reason it is a table of its own. Reading the history again
        # replaces every row of it.
        self.db.remember_owner("zzzzzzzzzzz", "A stranger", "stranger")
        self.db.replace_cached(self.db.HISTORY, [history_row("zzzzzzzzzzz")])
        self.assertEqual(self.card()["channel_title"], "A stranger")

    def test_a_name_that_matches_a_channel_here_brings_its_face(self):
        # A channel can be followed while a video of theirs from years ago is
        # not stored at all, and that card should look like any other.
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa", "A stranger",
                            "https://example.invalid/face.jpg")
        self.db.remember_owner("zzzzzzzzzzz", "A stranger", "stranger")
        card = self.card()
        self.assertEqual(card["avatar_url"], "https://example.invalid/face.jpg")
        self.assertEqual(card["channel_key"], CHANNEL)


class TheAnswerItself(unittest.TestCase):
    def test_a_handle_is_read_out_of_the_page_address(self):
        owner = oembed.parse(
            b'{"author_name": "Rick Astley", "author_url": '
            b'"https://www.youtube.com/@RickAstleyYT"}')
        self.assertEqual(owner.channel_name, "Rick Astley")
        self.assertEqual(owner.handle, "RickAstleyYT")
        self.assertEqual(owner.channel_ext_id, "")

    def test_an_old_style_address_is_a_channel_id(self):
        owner = oembed.parse(
            b'{"author_name": "Someone", "author_url": '
            b'"https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa"}')
        self.assertEqual(owner.channel_ext_id, "UCaaaaaaaaaaaaaaaaaaaaaa")

    def test_an_answer_with_no_name_is_nothing(self):
        self.assertIsNone(oembed.parse(b'{"author_url": "https://www.youtube.com/@x"}'))

    def test_and_so_is_something_that_is_not_an_answer(self):
        self.assertIsNone(oembed.parse(b"<html>404</html>"))


if __name__ == "__main__":
    unittest.main()
