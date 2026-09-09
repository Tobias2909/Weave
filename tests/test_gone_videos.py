"""A video taken down after it was stored.

Nothing announces this. A row arrives in a feed like any other and the video is
removed, made private or hidden afterwards, and from then on the card cannot be
played and its picture is a 404 for ever. The only part of the app that finds
out is the image cache, because it asks for that picture anyway.

Marked rather than deleted, and the reason is the two things that point at a
video row: a hand picked box, and the watched mark. Deleting the row would
quietly take the video out of a box somebody built and lose the record of
having watched it, so the row stays and every list leaves it out.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave.db import Database, VideoRow

# Synthetic. A channel id is UC and twenty two more characters.
CHANNEL = "UCaaaaaaaaaaaaaaaaaaaaaa"
KEY = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"


def video(ext_id: str) -> VideoRow:
    return VideoRow(platform="youtube", ext_id=ext_id, channel_key=KEY,
                    title=f"Video {ext_id}", published_at=1600000000, duration_s=300,
                    thumbnail_url=f"https://i.ytimg.com/vi/{ext_id}/hqdefault.jpg",
                    is_short=False)


class AVideoThatIsGone(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.db.add_channel(KEY, "youtube", CHANNEL, "A channel")
        self.db.upsert_videos([video("aaaaaaaaaaa"), video("bbbbbbbbbbb")])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def ids(self, rows) -> list[str]:
        return sorted(row["ext_id"] for row in rows)

    def test_it_starts_in_the_feed_like_any_other(self):
        self.assertEqual(self.ids(self.db.feed()), ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_marking_it_takes_it_out_of_the_feed(self):
        self.assertTrue(self.db.mark_unavailable("aaaaaaaaaaa"))
        self.assertEqual(self.ids(self.db.feed()), ["bbbbbbbbbbb"])

    def test_the_row_is_still_there(self):
        # The whole point of marking rather than deleting.
        self.db.mark_unavailable("aaaaaaaaaaa")
        held = self.db.conn.execute(
            "SELECT ext_id, unavailable_at FROM videos WHERE ext_id='aaaaaaaaaaa'").fetchone()
        self.assertIsNotNone(held)
        self.assertIsNotNone(held["unavailable_at"])

    def test_marking_it_twice_is_only_news_once(self):
        # What stops a scroll past the same dead card redrawing the grid on
        # every pass.
        self.assertTrue(self.db.mark_unavailable("aaaaaaaaaaa"))
        self.assertFalse(self.db.mark_unavailable("aaaaaaaaaaa"))

    def test_a_video_nobody_stored_is_not_invented(self):
        self.assertFalse(self.db.mark_unavailable("zzzzzzzzzzz"))
        self.assertFalse(self.db.mark_unavailable(""))
        self.assertEqual(self.db.unavailable_count(), 0)

    def test_it_is_counted_so_a_short_feed_is_explained(self):
        self.db.mark_unavailable("aaaaaaaaaaa")
        self.assertEqual(self.db.unavailable_count(), 1)

    def test_it_is_gone_from_a_box_it_was_put_in(self):
        box = self.db.create_box("Mine")
        self.db.add_to_box(box, "yt:aaaaaaaaaaa")
        self.assertEqual(self.ids(self.db.feed(box_id=box)), ["aaaaaaaaaaa"])
        self.db.mark_unavailable("aaaaaaaaaaa")
        self.assertEqual(self.db.feed(box_id=box), [])

    def test_it_is_gone_from_the_channel_page_and_a_search(self):
        self.db.mark_unavailable("aaaaaaaaaaa")
        self.assertEqual(self.ids(self.db.feed(channel_key=KEY)), ["bbbbbbbbbbb"])
        self.assertEqual(self.ids(self.db.feed(query="Video")), ["bbbbbbbbbbb"])

    def test_it_is_gone_from_a_group_and_its_count(self):
        group = self.db.create_group("Mine")
        self.db.add_to_group(group, KEY)
        self.db.mark_unavailable("aaaaaaaaaaa")
        self.assertEqual(self.ids(self.db.feed(group_id=group)), ["bbbbbbbbbbb"])
        # The badge has to agree with the list, or one of them is lying.
        self.assertEqual([g["unwatched"] for g in self.db.groups()], [1])

    def test_nothing_spends_a_request_on_it_again(self):
        # Both sweeps that pick videos to ask YouTube about. A row nobody can
        # fetch would otherwise be picked for ever, since neither of them ever
        # gets an answer that would take it off the list.
        self.db.upsert_videos([VideoRow(platform="youtube", ext_id="ccccccccccc",
                                        channel_key=KEY, title="No length")])
        self.assertIn("ccccccccccc", self.db.videos_without_a_length(KEY))
        self.db.mark_unavailable("ccccccccccc")
        self.assertNotIn("ccccccccccc", self.db.videos_without_a_length(KEY))
