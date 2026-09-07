"""A channel wanted in a group and nowhere else.

A group is a question about a few channels. Answering it by also pouring them
into All makes the group the only place they are not, which is the opposite of
what was asked for, so being put in a group follows a channel without adding it
to All. Following one by name is the other door and that one does add it, and
it also brings back a channel a group had been keeping on its own.

The flag is only ever raised, never lowered by any of that, so no order of
adding can take a channel out of All behind the back of the person who put it
there. Taking one out by hand is the single exception and lives in
test_leaving_all, along with what must not undo it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave.db import Database, FeedTiers, VideoRow

TIERS = FeedTiers()

# Synthetic. A channel id is UC and twenty two more characters.
ONE = "UCaaaaaaaaaaaaaaaaaaaaaa"
ONE_KEY = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"
TWO = "UCbbbbbbbbbbbbbbbbbbbbbb"
TWO_KEY = "yt:UCbbbbbbbbbbbbbbbbbbbbbb"


def video(ext_id, channel_key=ONE_KEY):
    return VideoRow(platform="youtube", ext_id=ext_id, channel_key=channel_key,
                    title=f"Video {ext_id}", published_at=1600000000, duration_s=300,
                    thumbnail_url="https://i/x.jpg", is_short=False)


class GroupOnly(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.group = self.db.create_group("Mine")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def keys(self, rows):
        return [row["key"] for row in rows]

    def store(self, channel_key=ONE_KEY, ext_id="aaaaaaaaaaa"):
        self.db.upsert_videos([video(ext_id, channel_key)])

    # ---- put in a group only --------------------------------------------

    def test_a_group_follows_the_channel_but_leaves_all_alone(self):
        self.db.add_to_group(self.group, ONE_KEY)
        self.store()
        self.assertEqual(self.keys(self.db.feed(group_id=self.group)), ["yt:aaaaaaaaaaa"])
        self.assertEqual(self.db.feed(), [])

    def test_and_it_is_still_polled(self):
        # The point of following it. A group of channels nothing asks after
        # would sit empty for good.
        self.db.add_to_group(self.group, ONE_KEY)
        self.assertEqual(self.keys(self.db.channels_due(TIERS)), [ONE_KEY])

    def test_it_is_counted_as_followed_and_named_as_group_only(self):
        self.db.add_to_group(self.group, ONE_KEY)
        counts = self.db.counts()
        self.assertEqual((counts["channels"], counts["group_only"], counts["loose"]),
                         (1, 1, 0))

    def test_but_it_is_not_one_of_the_channels_all_is_made_of(self):
        self.db.add_to_group(self.group, ONE_KEY)
        self.assertEqual(self.keys(self.db.channels()), [ONE_KEY])
        self.assertEqual(self.db.channels(in_all_only=True), [])

    def test_nor_does_it_count_towards_what_all_has_unwatched(self):
        self.db.add_to_group(self.group, ONE_KEY)
        self.store()
        self.assertEqual(self.db.unwatched_total(), 0)

    def test_its_own_page_still_shows_its_videos(self):
        # Asking for something particular answers with it whatever the channel
        # is, which is how a box behaves too.
        self.db.add_to_group(self.group, ONE_KEY)
        self.store()
        self.assertEqual(self.keys(self.db.feed(channel_key=ONE_KEY)), ["yt:aaaaaaaaaaa"])

    def test_a_search_finds_them_too(self):
        self.db.add_to_group(self.group, ONE_KEY)
        self.store()
        self.assertEqual(self.keys(self.db.feed(query="Video")), ["yt:aaaaaaaaaaa"])

    # ---- the flag is only ever raised -----------------------------------

    def test_a_channel_followed_by_name_stays_in_all_when_grouped(self):
        self.db.add_channel(ONE_KEY, "youtube", ONE, "Followed")
        self.db.add_to_group(self.group, ONE_KEY)
        self.store()
        self.assertEqual(self.keys(self.db.feed()), ["yt:aaaaaaaaaaa"])
        self.assertEqual(self.keys(self.db.channels(in_all_only=True)), [ONE_KEY])

    def test_two_groups_cannot_take_it_out_of_all_either(self):
        self.db.add_channel(ONE_KEY, "youtube", ONE, "Followed")
        other = self.db.create_group("Also")
        self.db.add_to_group(self.group, ONE_KEY)
        self.db.add_to_group(other, ONE_KEY)
        self.assertEqual(self.keys(self.db.channels(in_all_only=True)), [ONE_KEY])

    def test_following_it_by_name_afterwards_brings_it_into_all(self):
        self.db.add_to_group(self.group, ONE_KEY)
        self.store()
        self.assertEqual(self.db.feed(), [])
        self.db.add_channel(ONE_KEY, "youtube", ONE, "Followed")
        self.assertEqual(self.keys(self.db.feed()), ["yt:aaaaaaaaaaa"])
        self.assertEqual(self.db.counts()["group_only"], 0)

    def test_a_channel_kept_for_a_saved_video_is_not_promoted_by_a_group(self):
        # The row a saved video leaves behind is not in All, and a group must
        # not be the thing that puts it there.
        self.db.remember_channel(ONE_KEY, "youtube", ONE, "A stranger")
        self.db.add_to_group(self.group, ONE_KEY)
        self.store()
        self.assertEqual(self.db.feed(), [])
        self.assertEqual(self.keys(self.db.feed(group_id=self.group)), ["yt:aaaaaaaaaaa"])

    # ---- taking it back out ---------------------------------------------

    def test_the_last_group_letting_go_stops_it_being_followed(self):
        self.db.add_to_group(self.group, ONE_KEY)
        self.store()
        self.assertTrue(self.db.remove_from_group(self.group, ONE_KEY))
        self.assertEqual(self.db.channels(), [])
        self.assertEqual(self.db.channels_due(TIERS), [])
        # The row itself stays, so a card that names it still has a name.
        self.assertEqual(self.db.channel(ONE_KEY)["title"], None)
        self.assertEqual(self.db.counts()["loose"], 1)

    def test_a_second_group_still_holding_it_keeps_it_followed(self):
        other = self.db.create_group("Also")
        self.db.add_to_group(self.group, ONE_KEY)
        self.db.add_to_group(other, ONE_KEY)
        self.assertFalse(self.db.remove_from_group(self.group, ONE_KEY))
        self.assertEqual(self.keys(self.db.channels()), [ONE_KEY])

    def test_one_that_is_in_all_stays_followed_when_a_group_drops_it(self):
        self.db.add_channel(ONE_KEY, "youtube", ONE, "Followed")
        self.db.add_to_group(self.group, ONE_KEY)
        self.assertFalse(self.db.remove_from_group(self.group, ONE_KEY))
        self.assertEqual(self.keys(self.db.channels()), [ONE_KEY])

    def test_deleting_the_group_is_not_the_same_as_emptying_it(self):
        # Deleting a group keeps its channels, as with a box and its videos,
        # so a channel it was keeping on its own is still followed and still
        # reachable from its own page.
        self.db.add_to_group(self.group, ONE_KEY)
        self.db.delete_group(self.group)
        self.assertEqual(self.keys(self.db.channels()), [ONE_KEY])

    # ---- the window that manages one ------------------------------------

    def test_the_window_lists_who_is_in_it_by_name(self):
        self.db.add_channel(ONE_KEY, "youtube", ONE, "Zebra")
        self.db.add_channel(TWO_KEY, "youtube", TWO, "Antelope")
        self.db.add_to_group(self.group, ONE_KEY)
        self.db.add_to_group(self.group, TWO_KEY)
        self.assertEqual([row["title"] for row in self.db.group_channels(self.group)],
                         ["Antelope", "Zebra"])

    def test_and_a_channel_with_no_name_yet_sorts_last(self):
        self.db.add_channel(ONE_KEY, "youtube", ONE, "Zebra")
        self.db.add_to_group(self.group, ONE_KEY)
        self.db.add_to_group(self.group, TWO_KEY)
        self.assertEqual([row["key"] for row in self.db.group_channels(self.group)],
                         [ONE_KEY, TWO_KEY])

    def test_it_lists_nobody_for_a_group_that_holds_nobody(self):
        self.assertEqual(self.db.group_channels(self.group), [])


if __name__ == "__main__":
    unittest.main()
