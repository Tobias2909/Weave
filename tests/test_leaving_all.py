"""Taking a channel out of All, which is a decision rather than a state.

All is every channel followed on its own account. It is not a group anybody
made, it cannot be renamed or deleted, and until now nothing could be taken
out of it either: the flag was raised by following a channel and never lowered
by anything.

What makes this more than one more flag is what happens next. Every other way
that flag is written raises it, so without a record of the decision the next
subscription import would quietly put back exactly the channels somebody had
just taken out, and a channel with nowhere left to appear would go on being
polled for ever.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave.db import Database, FeedTiers, VideoRow

TIERS = FeedTiers()

ONE = "UCaaaaaaaaaaaaaaaaaaaaaa"
ONE_KEY = f"yt:{ONE}"
TWO = "UCbbbbbbbbbbbbbbbbbbbbbb"
TWO_KEY = f"yt:{TWO}"


def video(ext_id, channel_key=ONE_KEY):
    return VideoRow(platform="youtube", ext_id=ext_id, channel_key=channel_key,
                    title=f"Video {ext_id}", published_at=1600000000, duration_s=300,
                    is_short=False)


class LeavingAll(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(ONE_KEY, "youtube", ONE, "One")
        self.db.upsert_videos([video("aaaaaaaaaaa")])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def in_all(self):
        return [row["key"] for row in self.db.feed()]

    def followed(self):
        return [row["key"] for row in self.db.channels()]

    def test_a_channel_starts_in_all(self):
        self.assertEqual(self.in_all(), ["yt:aaaaaaaaaaa"])

    def test_taking_it_out_takes_its_videos_with_it(self):
        self.db.remove_from_all(ONE_KEY)
        self.assertEqual(self.in_all(), [])

    def test_the_channel_and_its_videos_are_kept(self):
        # Nothing is deleted. The videos are simply not shown in All, which is
        # what somebody asking for that asked for.
        self.db.remove_from_all(ONE_KEY)
        self.assertIsNotNone(self.db.channel(ONE_KEY))
        self.assertTrue(self.db.channel_has_videos(ONE_KEY))

    def test_it_stops_being_polled(self):
        self.assertTrue(self.db.remove_from_all(ONE_KEY))
        self.assertEqual([row["key"] for row in self.db.channels_due(TIERS, force=True)], [])
        self.assertEqual(self.followed(), [])

    def test_unless_a_group_still_holds_it(self):
        group = self.db.create_group("Mine")
        self.db.add_to_group(group, ONE_KEY)
        self.assertFalse(self.db.remove_from_all(ONE_KEY))
        self.assertEqual([row["key"] for row in self.db.channels_due(TIERS, force=True)],
                         [ONE_KEY])

    def test_a_group_still_shows_what_All_no_longer_does(self):
        group = self.db.create_group("Mine")
        self.db.add_to_group(group, ONE_KEY)
        self.db.remove_from_all(ONE_KEY)
        self.assertEqual(self.in_all(), [])
        self.assertEqual([row["key"] for row in self.db.feed(group_id=group)],
                         ["yt:aaaaaaaaaaa"])

    def test_being_put_in_a_group_asks_after_it_again(self):
        self.db.remove_from_all(ONE_KEY)
        group = self.db.create_group("Mine")
        self.db.add_to_group(group, ONE_KEY)
        self.assertEqual([row["key"] for row in self.db.channels_due(TIERS, force=True)],
                         [ONE_KEY])
        # And still not in All, since a group never puts anything there.
        self.assertEqual(self.in_all(), [])


class TheGroupsMenuOnAChannel(unittest.TestCase):
    """All is one of the lists that menu offers, and it answers for it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(ONE_KEY, "youtube", ONE, "One")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_a_followed_channel_is_shown_as_being_in_all(self):
        self.assertIn(-1, self.db.groups_holding(ONE_KEY))

    def test_one_taken_out_of_it_is_not(self):
        self.db.remove_from_all(ONE_KEY)
        self.assertNotIn(-1, self.db.groups_holding(ONE_KEY))

    def test_a_group_only_channel_is_not_either(self):
        group = self.db.create_group("Mine")
        self.db.add_channel(TWO_KEY, "youtube", TWO, "Two", in_all=False)
        self.db.add_to_group(group, TWO_KEY)
        self.assertEqual(self.db.groups_holding(TWO_KEY), [group])

    def test_all_comes_first_so_the_menu_leads_with_it(self):
        group = self.db.create_group("Mine")
        self.db.add_to_group(group, ONE_KEY)
        self.assertEqual(self.db.groups_holding(ONE_KEY), [-1, group])

    def test_a_channel_nobody_follows_is_in_nothing(self):
        self.db.remember_channel(TWO_KEY, "youtube", TWO, "Two")
        self.assertEqual(self.db.groups_holding(TWO_KEY), [])


class WhatCannotUndoIt(unittest.TestCase):
    """The whole point of remembering the decision."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.db.add_channel(ONE_KEY, "youtube", ONE, "One")
        self.db.upsert_videos([video("aaaaaaaaaaa")])
        self.db.remove_from_all(ONE_KEY)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def shown(self):
        return bool(self.db.feed())

    def test_importing_the_subscription_list_does_not_put_it_back(self):
        # This is the import, channel by channel, exactly as it runs.
        self.db.add_channel(ONE_KEY, "youtube", ONE, "One", "https://a/av.jpg")
        self.assertFalse(self.shown())

    def test_nor_does_a_poll_writing_the_name_back(self):
        self.db.add_channel(ONE_KEY, "youtube", ONE, "One from the feed")
        self.assertFalse(self.shown())
        self.assertEqual(self.db.channel(ONE_KEY)["title"], "One from the feed")

    def test_nor_does_a_group_letting_go_of_it(self):
        group = self.db.create_group("Mine")
        self.db.add_to_group(group, ONE_KEY)
        self.db.remove_from_group(group, ONE_KEY)
        self.assertFalse(self.shown())

    def test_following_it_by_name_does(self):
        # The one door back in, and it should be, since it is the same person
        # asking for it in the same words they first used.
        self.db.restore_to_all(ONE_KEY)
        self.assertTrue(self.shown())
        self.assertEqual([row["key"] for row in self.db.channels()], [ONE_KEY])

    def test_and_then_an_import_leaves_it_alone_again(self):
        self.db.restore_to_all(ONE_KEY)
        self.db.add_channel(ONE_KEY, "youtube", ONE, "One")
        self.assertTrue(self.shown())

    def test_a_channel_nobody_removed_is_still_raised_by_an_import(self):
        self.db.add_channel(TWO_KEY, "youtube", TWO, "Two", in_all=False)
        self.db.add_channel(TWO_KEY, "youtube", TWO, "Two")
        self.assertTrue(self.db.channel(TWO_KEY)["in_all"])


if __name__ == "__main__":
    unittest.main()
