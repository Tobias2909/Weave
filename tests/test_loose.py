"""Videos saved out of the lists that are not the feed.

The suggestions, the watch history and a search of YouTube are snapshots. They
live in their own tables, or for a search in nothing at all, and they are
replaced wholesale, so a box could not point at one of them: the video simply
was not stored. Putting one in a box stores it for good.

The channel it brings with it is the delicate part. It exists so the card has a
name and somewhere for a picture to live, and it must not turn into a channel
that is followed, because All is the channels chosen by hand and one saved
video is not that choice. Putting the channel itself in a group is the opposite
case and does follow it, since a group fills itself from what a channel posts
and a group of strangers would sit empty for good.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from weave.db import Database, FeedTiers, VideoRow

TIERS = FeedTiers()

# Synthetic throughout. A channel id is UC and twenty two more characters, so
# the ones here are shaped like the real thing without being anybody's.
STRANGER = "UCaaaaaaaaaaaaaaaaaaaaaa"
STRANGER_KEY = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"
FOLLOWED = "UCbbbbbbbbbbbbbbbbbbbbbb"
FOLLOWED_KEY = "yt:UCbbbbbbbbbbbbbbbbbbbbbb"


def flat(ext_id, channel_ext_id=STRANGER, channel_name="A stranger"):
    """One row in the shape every flat list produces."""
    return {"ext_id": ext_id, "title": f"Video {ext_id}", "channel_name": channel_name,
            "channel_ext_id": channel_ext_id, "duration_s": 300,
            "thumbnail_url": "https://i/x.jpg", "views": 12, "published_at": 1600000000}


class LooseCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.box = self.db.create_box("Keep")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def keys(self, rows):
        return [row["key"] for row in rows]


class SavingASuggestion(LooseCase):
    def setUp(self):
        super().setUp()
        self.db.replace_recommended([flat("aaaaaaaaaaa")])

    def test_it_goes_in_and_comes_back_out(self):
        self.assertTrue(self.db.add_to_box(self.box, "yt:aaaaaaaaaaa"))
        self.assertEqual(self.keys(self.db.feed(box_id=self.box)), ["yt:aaaaaaaaaaa"])
        self.db.remove_from_box(self.box, "yt:aaaaaaaaaaa")
        self.assertEqual(self.db.feed(box_id=self.box), [])

    def test_the_box_says_it_holds_it(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.assertEqual(self.db.boxes_holding("yt:aaaaaaaaaaa"), [self.box])
        self.assertEqual(self.db.boxes()[0]["items"], 1)

    def test_what_the_card_showed_is_what_was_kept(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        row = self.db.feed(box_id=self.box)[0]
        self.assertEqual(
            (row["title"], row["duration_s"], row["views"], row["published_at"],
             row["thumbnail_url"], row["channel_title"]),
            ("Video aaaaaaaaaaa", 300, 12, 1600000000, "https://i/x.jpg", "A stranger"))

    def test_the_next_set_of_suggestions_cannot_take_it_away(self):
        # The whole point of storing it. The suggestions are replaced
        # wholesale, and what was saved has to survive that.
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.replace_recommended([flat("bbbbbbbbbbb")])
        self.assertEqual(self.keys(self.db.feed(box_id=self.box)), ["yt:aaaaaaaaaaa"])

    def test_saving_it_twice_is_one_entry(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.assertEqual(len(self.db.feed(box_id=self.box)), 1)

    def test_a_key_nothing_has_ever_seen_is_refused(self):
        self.assertFalse(self.db.add_to_box(self.box, "yt:zzzzzzzzzzz"))
        self.assertEqual(self.db.feed(box_id=self.box), [])


class SavingAHistoryEntry(LooseCase):
    """A history row carries an id, a title, a duration and a thumbnail, and
    says nothing at all about the channel, measured."""

    def setUp(self):
        super().setUp()
        self.db.replace_cached(self.db.HISTORY, [
            {"ext_id": "ccccccccccc", "title": "Watched once", "channel_name": None,
             "channel_ext_id": None, "duration_s": 61, "thumbnail_url": "https://i/h.jpg"}])

    def test_it_goes_in_and_comes_back_out(self):
        self.assertTrue(self.db.add_to_box(self.box, "yt:ccccccccccc"))
        self.assertEqual(self.keys(self.db.feed(box_id=self.box)), ["yt:ccccccccccc"])
        self.db.remove_from_box(self.box, "yt:ccccccccccc")
        self.assertEqual(self.db.feed(box_id=self.box), [])

    def test_it_still_has_no_channel_afterwards(self):
        # Nothing was invented for it. The card shows what it showed before,
        # which is a title and no channel line.
        self.db.add_to_box(self.box, "yt:ccccccccccc")
        row = self.db.feed(box_id=self.box)[0]
        self.assertEqual((row["channel_key"], row["channel_title"]), ("", None))

    def test_the_row_that_stands_for_no_channel_is_not_one_of_them(self):
        self.db.add_to_box(self.box, "yt:ccccccccccc")
        self.assertEqual(self.db.channels(), [])
        self.assertEqual(self.db.counts()["channels"], 0)
        self.assertEqual(self.db.channels_due(TIERS), [])

    def test_two_entries_with_no_channel_share_that_one_row(self):
        self.db.replace_cached(self.db.HISTORY, [
            {"ext_id": "ccccccccccc", "title": "One", "channel_name": None,
             "channel_ext_id": None, "duration_s": 61, "thumbnail_url": "t"},
            {"ext_id": "ddddddddddd", "title": "Two", "channel_name": None,
             "channel_ext_id": None, "duration_s": 62, "thumbnail_url": "t"}])
        self.db.add_to_box(self.box, "yt:ccccccccccc")
        self.db.add_to_box(self.box, "yt:ddddddddddd")
        self.assertEqual(len(self.db.channels(include_untracked=True)), 1)


class SavingASearchResult(LooseCase):
    """A search is the one list stored nowhere at all, so the row travels with
    the request to save it."""

    def row(self, ext_id):
        return self.db.decorate([flat(ext_id)])[0]

    def test_the_result_carries_what_storing_it_needs(self):
        row = self.row("eeeeeeeeeee")
        self.assertEqual((row["channel_ext_id"], row["channel_name"], row["published_at"]),
                         (STRANGER, "A stranger", 1600000000))

    def test_it_goes_in_and_comes_back_out(self):
        self.assertTrue(self.db.add_to_box(self.box, "yt:eeeeeeeeeee", self.row("eeeeeeeeeee")))
        self.assertEqual(self.keys(self.db.feed(box_id=self.box)), ["yt:eeeeeeeeeee"])
        self.db.remove_from_box(self.box, "yt:eeeeeeeeeee")
        self.assertEqual(self.db.feed(box_id=self.box), [])

    def test_without_the_row_there_is_nothing_to_store(self):
        # Nothing has ever seen this id, so there is nowhere to read it from.
        self.assertFalse(self.db.add_to_box(self.box, "yt:eeeeeeeeeee"))

    def test_a_result_already_stored_needs_no_row(self):
        self.db.add_channel(FOLLOWED_KEY, "youtube", FOLLOWED, "Followed")
        self.db.upsert_videos([VideoRow("youtube", "fffffffffff", FOLLOWED_KEY, "Known")])
        self.assertTrue(self.db.add_to_box(self.box, "yt:fffffffffff"))


class TheChannelThatCameAlong(LooseCase):
    """It carries a name and a picture and nothing else. Everything that says
    how many channels there are, and everything that spends a request, has to
    leave it out."""

    def setUp(self):
        super().setUp()
        self.db.replace_recommended([flat("aaaaaaaaaaa")])
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")

    def test_it_is_never_asked_after(self):
        self.assertEqual(self.db.channels_due(TIERS), [])
        self.assertEqual(self.db.channels_due(TIERS, force=True), [])

    def test_not_even_after_something_says_it_has_news(self):
        self.db.promote_channels([STRANGER_KEY])
        self.assertEqual(self.db.channels_due(TIERS), [])

    def test_it_is_not_one_of_the_channels_followed(self):
        self.assertEqual(self.db.channels(), [])
        self.assertEqual(self.db.channels(platform="youtube"), [])
        self.assertEqual(self.db.counts()["channels"], 0)

    def test_but_the_row_is_there_to_be_found(self):
        self.assertEqual([row["key"] for row in self.db.channels(include_untracked=True)],
                         [STRANGER_KEY])
        self.assertEqual(self.db.counts()["loose"], 1)
        self.assertEqual(self.db.channel(STRANGER_KEY)["title"], "A stranger")

    def test_its_video_stays_out_of_the_all_feed(self):
        self.assertEqual(self.db.feed(), [])
        self.assertEqual(self.db.feed(hide_watched=False), [])
        self.assertEqual(self.db.unwatched_total(), 0)

    def test_and_out_of_a_group_it_was_never_put_in(self):
        group = self.db.create_group("Mine")
        self.assertEqual(self.db.feed(group_id=group), [])
        self.assertEqual(self.db.groups()[0]["unwatched"], 0)

    def test_the_feed_still_shows_the_channels_that_are_followed(self):
        self.db.add_channel(FOLLOWED_KEY, "youtube", FOLLOWED, "Followed")
        self.db.upsert_videos([VideoRow("youtube", "fffffffffff", FOLLOWED_KEY, "Known")])
        self.assertEqual(self.keys(self.db.feed()), ["yt:fffffffffff"])
        self.assertEqual(self.db.unwatched_total(), 1)

    def test_it_is_never_asked_for_a_live_check(self):
        self.db.conn.execute("UPDATE videos SET live_status='is_live'")
        self.db.conn.commit()
        self.assertEqual(self.db.channels_that_stream(), set())

    def test_the_box_and_the_channel_page_still_show_the_video(self):
        self.assertEqual(self.keys(self.db.feed(box_id=self.box)), ["yt:aaaaaaaaaaa"])
        self.assertEqual(self.keys(self.db.feed(channel_key=STRANGER_KEY)),
                         ["yt:aaaaaaaaaaa"])

    def test_and_so_does_a_search_of_what_is_stored(self):
        # Searching is asking for one particular video, and a video saved by
        # hand is exactly the kind of thing that gets looked for.
        self.assertEqual(self.keys(self.db.feed(query="Video aaa")), ["yt:aaaaaaaaaaa"])


class PuttingTheChannelInAGroup(LooseCase):
    """The other half of the rule. A group holds channels and fills itself from
    what they post, so putting one in a group follows it. Following it is all
    it does, though: the channel is polled and shows inside that group, and
    All is left exactly as it was."""

    def setUp(self):
        super().setUp()
        self.db.replace_recommended([flat("aaaaaaaaaaa")])
        self.group = self.db.create_group("Mine")

    def test_a_suggestion_names_the_channel_it_came_from(self):
        # Without a key there is nothing for the menu to address, which is why
        # nothing happened when a suggestion's channel was put in a group.
        self.assertEqual(self.db.recommended()[0]["channel_key"], STRANGER_KEY)

    def test_a_stranger_can_be_put_in_one_before_anything_else_knows_it(self):
        self.assertTrue(self.db.add_to_group(self.group, STRANGER_KEY))
        self.assertEqual([row["key"] for row in self.db.group_channels(self.group)],
                         [STRANGER_KEY])
        self.assertEqual(self.db.groups_holding(STRANGER_KEY), [self.group])

    def test_and_that_does_follow_it(self):
        self.db.add_to_group(self.group, STRANGER_KEY)
        self.assertEqual([row["key"] for row in self.db.channels()], [STRANGER_KEY])
        self.assertEqual(self.db.counts()["channels"], 1)
        self.assertEqual([row["key"] for row in self.db.channels_due(TIERS)], [STRANGER_KEY])

    def test_it_brings_the_name_the_suggestion_gave_with_it(self):
        self.db.add_to_group(self.group, STRANGER_KEY)
        self.assertEqual(self.db.channel(STRANGER_KEY)["title"], "A stranger")

    def test_a_channel_saved_loose_first_is_promoted_rather_than_doubled(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.add_to_group(self.group, STRANGER_KEY)
        self.assertEqual(len(self.db.channels(include_untracked=True)), 1)
        self.assertEqual(self.db.counts()["loose"], 0)

    def test_and_its_saved_video_reaches_the_group_and_not_the_feed(self):
        # Following it is what fills the group. All is a separate question and
        # a group does not answer it, so the video shows in the group it was
        # asked for and All is exactly as it was.
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.add_to_group(self.group, STRANGER_KEY)
        self.assertEqual(self.keys(self.db.feed(group_id=self.group)), ["yt:aaaaaaaaaaa"])
        self.assertEqual(self.db.feed(), [])

    def test_the_row_that_stands_for_no_channel_cannot_be_put_in_one(self):
        self.assertFalse(self.db.add_to_group(self.group, ""))
        self.assertEqual(self.db.group_channels(self.group), [])

    def test_following_a_channel_by_hand_reports_it_as_newly_followed(self):
        self.db.remember_channel(STRANGER_KEY, "youtube", STRANGER, "A stranger")
        self.assertTrue(self.db.add_channel(STRANGER_KEY, "youtube", STRANGER, "A stranger"))
        self.assertFalse(self.db.add_channel(STRANGER_KEY, "youtube", STRANGER, "A stranger"))


class TheChannelPicture(LooseCase):
    """Why a suggestion's card has no channel icon, and where one would go."""

    def setUp(self):
        super().setUp()
        self.db.replace_recommended([flat("aaaaaaaaaaa")])

    def test_a_suggestion_from_a_followed_channel_has_always_had_one(self):
        # So the join, the row and the card are all fine. What is missing is
        # the picture itself.
        self.db.add_channel(STRANGER_KEY, "youtube", STRANGER, "Followed", "https://a/av.jpg")
        self.assertEqual(self.db.recommended()[0]["avatar_url"], "https://a/av.jpg")

    def test_from_a_stranger_there_is_no_picture_to_join_to(self):
        self.assertIsNone(self.db.recommended()[0]["avatar_url"])

    def test_the_kept_channel_row_is_where_one_lands(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.set_channel_details(STRANGER_KEY, None, "https://a/av.jpg", None, None)
        self.assertEqual(self.db.recommended()[0]["avatar_url"], "https://a/av.jpg")
        self.assertEqual(self.db.feed(box_id=self.box)[0]["avatar_url"], "https://a/av.jpg")

    def test_and_storing_one_does_not_follow_the_channel(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.set_channel_details(STRANGER_KEY, "A stranger", "https://a/av.jpg", None, 5)
        self.assertEqual(self.db.channels(), [])
        self.assertEqual(self.db.channels_due(TIERS), [])

    def test_a_suggestion_keeps_a_bare_row_for_the_lookup_to_land_on(self):
        # Nothing has put the video in a box, so nothing else would have
        # created this row. The fetch is what has to create it.
        self.assertEqual(self.db.channels(include_untracked=True), [])
        self.assertEqual(self.db.channels_named_in(self.db.RECOMMENDED), [STRANGER_KEY])
        self.assertEqual(self.db.channel(STRANGER_KEY)["title"], "A stranger")
        self.assertEqual(self.db.counts()["loose"], 1)

    def test_a_channel_with_no_picture_is_named_as_needing_one(self):
        self.assertEqual(self.db.channels_missing_picture([STRANGER_KEY]), [STRANGER_KEY])

    def test_a_channel_that_already_has_a_picture_is_left_out(self):
        self.db.remember_channel(STRANGER_KEY, "youtube", STRANGER, "A stranger",
                                 "https://a/av.jpg")
        self.assertEqual(self.db.channels_missing_picture([STRANGER_KEY]), [])

    def test_a_channel_followed_is_the_same_either_way(self):
        self.db.add_channel(FOLLOWED_KEY, "youtube", FOLLOWED, "Followed")
        self.assertEqual(self.db.channels_missing_picture([FOLLOWED_KEY]), [FOLLOWED_KEY])
        self.db.add_channel(FOLLOWED_KEY, "youtube", FOLLOWED, "Followed", "https://a/av.jpg")
        self.assertEqual(self.db.channels_missing_picture([FOLLOWED_KEY]), [])

    def test_the_history_names_no_channel_to_look_up(self):
        # Measured: a history row carries no channel at all, so there is
        # nothing here for a lookup to work through.
        self.db.replace_cached(self.db.HISTORY, [
            {"ext_id": "ccccccccccc", "title": "Watched once", "channel_name": None,
             "channel_ext_id": None, "duration_s": 61, "thumbnail_url": "t"}])
        self.assertEqual(self.db.channels_named_in(self.db.HISTORY), [])


class Migration(unittest.TestCase):
    """A database written by the schema before this one has to open, keep every
    channel it already had, and gain the flag."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "old.db"

    def tearDown(self):
        self._tmp.cleanup()

    def make_old(self):
        """A database in the shape the previous version left behind: the flag
        does not exist and the version says so."""
        db = Database(self.path)
        db.add_channel(FOLLOWED_KEY, "youtube", FOLLOWED, "Followed")
        db.upsert_videos([VideoRow("youtube", "fffffffffff", FOLLOWED_KEY, "Known")])
        with db.conn as conn:
            conn.execute("ALTER TABLE channels DROP COLUMN tracked")
            conn.execute("UPDATE meta SET value='18' WHERE key='schema_version'")
        db.close()

    def columns(self):
        conn = sqlite3.connect(self.path)
        try:
            return {row[1] for row in conn.execute("PRAGMA table_info(channels)")}
        finally:
            conn.close()

    def test_the_flag_is_missing_to_begin_with(self):
        self.make_old()
        self.assertNotIn("tracked", self.columns())

    def test_opening_it_adds_the_flag(self):
        self.make_old()
        db = Database(self.path)
        self.addCleanup(db.close)
        self.assertIn("tracked", self.columns())

    def test_and_everything_it_held_is_still_followed(self):
        self.make_old()
        db = Database(self.path)
        self.addCleanup(db.close)
        self.assertEqual([row["key"] for row in db.channels()], [FOLLOWED_KEY])
        self.assertEqual([row["key"] for row in db.channels_due(TIERS)], [FOLLOWED_KEY])
        self.assertEqual([row["key"] for row in db.feed()], ["yt:fffffffffff"])
        self.assertEqual(db.counts(), {"channels": 1, "loose": 0, "group_only": 0,
                                       "videos": 1, "watched": 0})

    def test_opening_it_twice_changes_nothing(self):
        self.make_old()
        Database(self.path).close()
        db = Database(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.counts()["channels"], 1)


if __name__ == "__main__":
    unittest.main()
