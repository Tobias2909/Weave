import tempfile
import unittest
from pathlib import Path

import time

from weave.db import SHORTS_CEILING_S, Database, FeedTiers, VideoRow

# The shipped defaults, so a test failure means the behaviour changed and
# not that a test invented its own numbers.
TIERS = FeedTiers()


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def video(self, ext_id, channel="yt:UC1", **kwargs):
        return VideoRow("youtube", ext_id, channel, kwargs.pop("title", ext_id), **kwargs)


class Channels(DatabaseCase):
    def test_add_reports_whether_it_was_new(self):
        self.assertTrue(self.db.add_channel("yt:UC1", "youtube", "UC1", "One"))
        self.assertFalse(self.db.add_channel("yt:UC1", "youtube", "UC1", "One"))

    def test_a_later_source_with_less_detail_cannot_erase_more(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One", "https://a/av.jpg")
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        row = self.db.channels()[0]
        self.assertEqual((row["title"], row["avatar_url"]), ("One", "https://a/av.jpg"))

    def test_only_channels_past_their_interval_are_due(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.assertEqual(len(self.db.channels_due(TIERS)), 1)          # never polled
        self.db.mark_polled("yt:UC1")
        self.assertEqual(len(self.db.channels_due(TIERS)), 0)          # just polled
        self.assertEqual(len(self.db.channels_due(TIERS, force=True)), 1)

    def test_only_a_slice_is_taken_at_a_time(self):
        # Asking about several hundred feeds at once is what provokes the
        # endpoint into refusing, so a round takes the most overdue few. The
        # limit holds even when the round was asked for by hand, because the
        # same endpoint is on the other end either way.
        for n in range(10):
            self.db.add_channel(f"yt:UC{n}", "youtube", f"UC{n}")
        self.assertEqual(len(self.db.channels_due(TIERS, limit=4)), 4)
        self.assertEqual(len(self.db.channels_due(TIERS, force=True, limit=4)), 4)
        self.assertEqual(len(self.db.channels_due(TIERS)), 10)

    def test_the_most_overdue_is_taken_first(self):
        self.db.add_channel("yt:UCa", "youtube", "UCa")
        self.db.add_channel("yt:UCb", "youtube", "UCb")
        self.db.mark_polled("yt:UCa")
        first = self.db.channels_due(TIERS, limit=1)[0]["key"]
        self.assertEqual(first, "yt:UCb")

    def test_a_channel_is_asked_as_often_as_it_posts(self):
        # The whole point of the tiers. Polling a channel that has not posted
        # in years as often as one that posts daily is what made a full lap
        # over several hundred channels take well over an hour.
        now = int(time.time())
        for name, published in (("hot", now - 2 * 86400),
                                ("warm", now - 20 * 86400),
                                ("cold", now - 60 * 86400),
                                ("frozen", now - 400 * 86400)):
            key = f"yt:UC{name}"
            self.db.add_channel(key, "youtube", f"UC{name}")
            self.db.upsert_videos([self.video(name.ljust(11, "z"), channel=key,
                                              published_at=published)])
        self.db.conn.execute("UPDATE channels SET last_polled_at=?", (now - 1800,))
        self.db.conn.commit()
        # Half an hour after the last poll, only the channel that posts often
        # is due again.
        self.assertEqual([r["key"] for r in self.db.channels_due(TIERS)], ["yt:UChot"])

    def test_a_channel_with_nothing_stored_is_treated_as_dormant(self):
        now = int(time.time())
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.db.conn.execute("UPDATE channels SET last_polled_at=?", (now - 3600,))
        self.db.conn.commit()
        self.assertEqual(self.db.channels_due(TIERS), [])

    def test_a_promoted_channel_goes_to_the_front(self):
        # A single cheap call over every subscription can establish that a
        # channel has something new. Promoting it is how that turns into its
        # feed being asked in the same round rather than in an hour.
        now = int(time.time())
        for key in ("yt:UCa", "yt:UCb"):
            self.db.add_channel(key, "youtube", key.split(":")[1])
        self.db.conn.execute("UPDATE channels SET last_polled_at=?", (now - 60,))
        self.db.conn.commit()
        self.assertEqual(self.db.channels_due(TIERS), [])
        self.assertEqual(self.db.promote_channels(["yt:UCb"]), 1)
        self.assertEqual([r["key"] for r in self.db.channels_due(TIERS)], ["yt:UCb"])
        # Promoting twice is not a second promotion.
        self.assertEqual(self.db.promote_channels(["yt:UCb"]), 0)

    def test_only_channels_that_have_streamed_are_asked_for_live(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.db.add_channel("yt:UC2", "youtube", "UC2")
        self.db.upsert_videos([self.video("aaaaaaaaaaa", channel="yt:UC1"),
                               self.video("bbbbbbbbbbb", channel="yt:UC2",
                                          live_status="was_live")])
        self.assertEqual(self.db.channels_that_stream(), {"yt:UC2"})

    def test_the_feed_variant_is_remembered(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.assertIsNone(self.db.channels()[0]["feed_variant"])
        self.db.set_feed_variant("yt:UC1", "channel")
        self.assertEqual(self.db.channels()[0]["feed_variant"], "channel")

    def test_knows_whether_a_channel_ever_produced_a_video(self):
        # This is what separates a broken feed from a channel that is simply
        # empty, of which a large subscription list has plenty.
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.assertFalse(self.db.channel_has_videos("yt:UC1"))
        self.db.upsert_videos([self.video("aaaaaaaaaaa")])
        self.assertTrue(self.db.channel_has_videos("yt:UC1"))


class Videos(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")

    def test_upsert_keeps_first_seen_and_refreshes_the_volatile_numbers(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa", views=10, likes=1)])
        first = self.db.feed()[0]["first_seen_at"]
        self.db.upsert_videos([self.video("aaaaaaaaaaa", title="Renamed", views=99, likes=9)])
        row = self.db.feed()[0]
        self.assertEqual((row["title"], row["views"], row["likes"]), ("Renamed", 99, 9))
        self.assertEqual(row["first_seen_at"], first)

    def test_a_source_with_no_duration_cannot_erase_a_known_one(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa", duration_s=600)])
        self.db.upsert_videos([self.video("aaaaaaaaaaa")])
        self.assertEqual(self.db.feed()[0]["duration_s"], 600)

    def test_newest_first(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa", published_at=100),
                               self.video("bbbbbbbbbbb", published_at=200)])
        self.assertEqual([r["ext_id"] for r in self.db.feed()], ["bbbbbbbbbbb", "aaaaaaaaaaa"])

    def test_watched_is_filtered_not_deleted(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa")])
        self.db.set_watched("yt:aaaaaaaaaaa", 0.9, "mpv")
        self.assertEqual(self.db.feed(), [])
        self.assertEqual(len(self.db.feed(hide_watched=False)), 1)
        self.db.clear_watched("yt:aaaaaaaaaaa")
        self.assertEqual(len(self.db.feed()), 1)


class Accumulation(DatabaseCase):
    """A channel feed publishes only its newest fifteen entries, so the stored
    history has to grow across polls rather than being replaced by each one."""

    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")

    def test_a_later_poll_adds_rather_than_replaces(self):
        first_window = [self.video(f"aaaaaaaaaa{n}", published_at=100 + n) for n in range(3)]
        self.db.upsert_videos(first_window)
        # A later poll sees two new videos, and the oldest has dropped out of
        # the window entirely.
        second_window = [self.video(f"aaaaaaaaaa{n}", published_at=100 + n) for n in (1, 2)]
        second_window += [self.video(f"bbbbbbbbbb{n}", published_at=200 + n) for n in range(2)]
        self.db.upsert_videos(second_window)
        stored = {r["ext_id"] for r in self.db.feed(hide_watched=False)}
        self.assertEqual(len(stored), 5)
        self.assertIn("aaaaaaaaaa0", stored)     # gone from the window, still stored

    def test_a_video_that_left_the_window_is_never_pruned(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa", published_at=100)])
        for _ in range(5):
            self.db.upsert_videos([self.video("bbbbbbbbbbb", published_at=200)])
        self.assertIn("aaaaaaaaaaa", {r["ext_id"] for r in self.db.feed(hide_watched=False)})

    def test_watched_state_survives_later_polls(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa", published_at=100)])
        self.db.set_watched("yt:aaaaaaaaaaa", 1.0, "mpv")
        self.db.upsert_videos([self.video("aaaaaaaaaaa", title="Renamed", published_at=100)])
        self.assertTrue(self.db.is_watched("yt:aaaaaaaaaaa"))

    def test_box_membership_survives_later_polls(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa", published_at=100)])
        box = self.db.create_box("Keep")
        self.db.add_to_box(box, "yt:aaaaaaaaaaa")
        self.db.upsert_videos([self.video("aaaaaaaaaaa", title="Renamed", published_at=100)])
        self.assertEqual(self.db.boxes()[0]["items"], 1)


class VideoKind(DatabaseCase):
    """Each tab has its own feed, so the kind arrives with the video instead of
    being worked out afterwards by asking more questions about it."""

    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")

    def test_a_video_from_the_shorts_feed_never_shows(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa", is_short=True),
                               self.video("bbbbbbbbbbb", is_short=False)])
        self.assertEqual([r["ext_id"] for r in self.db.feed()], ["bbbbbbbbbbb"])

    def test_a_video_of_unknown_kind_still_shows(self):
        # Only the mixed channel feed produces these, and it is the fallback
        # for a channel with no videos tab. Hiding them would hide it.
        self.db.upsert_videos([self.video("ccccccccccc")])
        self.assertIn("ccccccccccc", [r["ext_id"] for r in self.db.feed()])

    def test_a_long_duration_settles_it_with_no_request(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa")])
        self.db.fill_details([("yt:aaaaaaaaaaa", SHORTS_CEILING_S + 1, None)])
        row = next(r for r in self.db.feed() if r["ext_id"] == "aaaaaaaaaaa")
        self.assertEqual(row["is_short"], 0)

    def test_a_stored_decision_is_never_overwritten(self):
        # A Short that later turns up in the mixed feed, which says nothing
        # about kind, must not become undecided again.
        self.db.upsert_videos([self.video("aaaaaaaaaaa", is_short=True)])
        self.db.upsert_videos([self.video("aaaaaaaaaaa", is_short=None)])
        row = self.db.conn.execute(
            "SELECT is_short FROM videos WHERE ext_id='aaaaaaaaaaa'").fetchone()
        self.assertEqual(row["is_short"], 1)

    def test_unknown_ids_are_what_the_sweep_reports(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa")])
        self.assertEqual(self.db.unknown_video_keys(["yt:aaaaaaaaaaa", "yt:zzzzzzzzzzz"]),
                         {"yt:zzzzzzzzzzz"})
        self.assertEqual(self.db.unknown_video_keys([]), set())


class Groups(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.add_channel("twitch:someone", "twitch", "someone", "Someone")
        self.db.upsert_videos([self.video("aaaaaaaaaaa")])
        self.group = self.db.create_group("Gaming")

    def test_creating_the_same_name_twice_returns_the_same_group(self):
        self.assertEqual(self.db.create_group("Gaming"), self.group)

    def test_a_group_can_mix_platforms(self):
        self.db.add_to_group(self.group, "yt:UC1")
        self.db.add_to_group(self.group, "twitch:someone")
        self.assertEqual(len(self.db.group_members(self.group)), 2)

    def test_a_channel_can_be_in_several_groups(self):
        other = self.db.create_group("Tech")
        self.db.add_to_group(self.group, "yt:UC1")
        self.db.add_to_group(other, "yt:UC1")
        self.assertEqual([g["members"] for g in self.db.groups()], [1, 1])

    def test_the_feed_filters_to_the_group(self):
        self.db.add_channel("yt:UC2", "youtube", "UC2", "Two")
        self.db.upsert_videos([self.video("bbbbbbbbbbb", channel="yt:UC2")])
        self.db.add_to_group(self.group, "yt:UC1")
        self.assertEqual([r["ext_id"] for r in self.db.feed(group_id=self.group)],
                         ["aaaaaaaaaaa"])

    def test_unwatched_counts_exclude_watched_and_shorts(self):
        self.db.add_to_group(self.group, "yt:UC1")
        self.db.upsert_videos([self.video("bbbbbbbbbbb"),
                               self.video("ccccccccccc", is_short=True)])
        self.db.set_watched("yt:bbbbbbbbbbb", 1.0, "mpv")
        self.assertEqual(self.db.groups()[0]["unwatched"], 1)
        self.assertEqual(self.db.unwatched_total(), 1)

    def test_which_groups_hold_a_channel(self):
        # What the tick beside each entry in the channel menu reads.
        second = self.db.create_group("Second")
        self.db.add_to_group(self.group, "yt:UC1")
        self.assertEqual(self.db.groups_holding("yt:UC1"), [self.group])
        self.db.add_to_group(second, "yt:UC1")
        self.assertEqual(sorted(self.db.groups_holding("yt:UC1")), sorted([self.group, second]))
        self.db.remove_from_group(self.group, "yt:UC1")
        self.assertEqual(self.db.groups_holding("yt:UC1"), [second])

    def test_a_channel_can_be_in_several_groups(self):
        second = self.db.create_group("Second")
        self.db.add_to_group(self.group, "yt:UC1")
        self.db.add_to_group(second, "yt:UC1")
        self.assertEqual([g["members"] for g in self.db.groups()], [1, 1])

    def test_adding_the_same_channel_twice_changes_nothing(self):
        self.db.add_to_group(self.group, "yt:UC1")
        self.db.add_to_group(self.group, "yt:UC1")
        self.assertEqual(self.db.groups()[0]["members"], 1)

    def test_moving_a_group_up_and_down(self):
        second = self.db.create_group("Second")
        third = self.db.create_group("Third")
        order = lambda: [g["id"] for g in self.db.groups()]
        self.assertEqual(order(), [self.group, second, third])
        self.assertTrue(self.db.move_group(third, -1))
        self.assertEqual(order(), [self.group, third, second])
        self.assertTrue(self.db.move_group(third, 1))
        self.assertEqual(order(), [self.group, second, third])

    def test_moving_past_either_end_is_not_a_move(self):
        second = self.db.create_group("Second")
        self.assertFalse(self.db.move_group(self.group, -1))
        self.assertFalse(self.db.move_group(second, 1))
        self.assertFalse(self.db.move_group(9999, 1))
        self.assertEqual([g["id"] for g in self.db.groups()], [self.group, second])

    def test_deleting_a_group_keeps_the_channels(self):
        self.db.add_to_group(self.group, "yt:UC1")
        self.db.delete_group(self.group)
        self.assertEqual(self.db.groups(), [])
        self.assertEqual(len(self.db.channels()), 2)

    def test_lookup_by_name_ignores_case(self):
        self.assertEqual(self.db.group_by_name("gaming")["id"], self.group)
        self.assertIsNone(self.db.group_by_name("nope"))

    def test_order_is_settable(self):
        second = self.db.create_group("Tech")
        self.db.set_group_order([second, self.group])
        self.assertEqual([g["name"] for g in self.db.groups()], ["Tech", "Gaming"])


class Boxes(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.upsert_videos([self.video("aaaaaaaaaaa", published_at=100),
                               self.video("bbbbbbbbbbb", published_at=200),
                               self.video("ccccccccccc", published_at=300)])
        self.box = self.db.create_box("Watch tonight")

    def test_creating_the_same_name_twice_returns_the_same_box(self):
        self.assertEqual(self.db.create_box("Watch tonight"), self.box)

    def test_order_is_the_order_things_were_put_in(self):
        # Not publish order. Hand picking is the whole point of a box.
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.add_to_box(self.box, "yt:ccccccccccc")
        self.db.add_to_box(self.box, "yt:bbbbbbbbbbb")
        self.assertEqual([r["ext_id"] for r in self.db.feed(box_id=self.box)],
                         ["aaaaaaaaaaa", "ccccccccccc", "bbbbbbbbbbb"])

    def test_adding_twice_is_harmless(self):
        self.assertTrue(self.db.add_to_box(self.box, "yt:aaaaaaaaaaa"))
        self.assertTrue(self.db.add_to_box(self.box, "yt:aaaaaaaaaaa"))
        self.assertEqual(self.db.boxes()[0]["items"], 1)

    def test_an_unknown_video_is_reported_not_raised(self):
        # Reachable from the command line, where a URL can name a video this
        # install has never seen.
        self.assertFalse(self.db.add_to_box(self.box, "yt:zzzzzzzzzzz"))
        self.assertEqual(self.db.boxes()[0]["items"], 0)

    def test_removing(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.remove_from_box(self.box, "yt:aaaaaaaaaaa")
        self.assertEqual(self.db.feed(box_id=self.box), [])

    def test_which_boxes_hold_a_video(self):
        other = self.db.create_box("Music")
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.add_to_box(other, "yt:aaaaaaaaaaa")
        self.assertEqual(sorted(self.db.boxes_holding("yt:aaaaaaaaaaa")), sorted([self.box, other]))
        self.assertEqual(self.db.boxes_holding("yt:bbbbbbbbbbb"), [])

    def test_a_watched_video_stays_in_a_box(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.set_watched("yt:aaaaaaaaaaa", 1.0, "mpv")
        self.assertEqual(len(self.db.feed(box_id=self.box, hide_watched=False)), 1)

    def test_a_short_never_appears_even_in_a_box(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.upsert_videos([self.video("aaaaaaaaaaa", is_short=True)])
        self.assertEqual(self.db.feed(box_id=self.box, hide_watched=False), [])

    def test_deleting_a_box_keeps_the_videos(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.delete_box(self.box)
        self.assertEqual(self.db.boxes(), [])
        self.assertEqual(len(self.db.feed(hide_watched=False)), 3)

    def test_deleting_a_video_drops_it_from_its_boxes(self):
        self.db.add_to_box(self.box, "yt:aaaaaaaaaaa")
        self.db.remove_channel("yt:UC1")
        self.assertEqual(self.db.boxes()[0]["items"], 0)

    def test_rename_and_lookup(self):
        self.db.rename_box(self.box, "Later")
        self.assertEqual(self.db.box_by_name("later")["id"], self.box)

    def test_order_is_settable(self):
        second = self.db.create_box("Music")
        self.db.set_box_order([second, self.box])
        self.assertEqual([b["name"] for b in self.db.boxes()], ["Music", "Watch tonight"])


class ChannelPage(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.add_channel("yt:UC2", "youtube", "UC2", "Two")
        self.db.upsert_videos([self.video("aaaaaaaaaaa"),
                               self.video("bbbbbbbbbbb", channel="yt:UC2")])

    def test_details_round_trip(self):
        self.db.set_channel_details("yt:UC1", "One", "https://a/av.jpg",
                                    "https://a/ban.jpg", 1580000)
        found = self.db.channel("yt:UC1")
        self.assertEqual((found["banner_url"], found["follower_count"], found["video_count"]),
                         ("https://a/ban.jpg", 1580000, 1))

    def test_a_later_lookup_with_less_detail_cannot_erase_more(self):
        self.db.set_channel_details("yt:UC1", "One", "https://a/av.jpg", "https://a/ban.jpg", 10)
        self.db.set_channel_details("yt:UC1", None, None, None, None)
        found = self.db.channel("yt:UC1")
        self.assertEqual((found["banner_url"], found["follower_count"]), ("https://a/ban.jpg", 10))

    def test_details_are_stale_until_fetched(self):
        self.assertTrue(self.db.channel_details_are_stale("yt:UC1"))
        self.db.set_channel_details("yt:UC1", "One", None, None, None)
        self.assertFalse(self.db.channel_details_are_stale("yt:UC1"))
        self.assertTrue(self.db.channel_details_are_stale("yt:UC1", interval_s=0))

    def test_an_unknown_channel_is_not_stale_it_is_absent(self):
        self.assertFalse(self.db.channel_details_are_stale("yt:UC9"))
        self.assertIsNone(self.db.channel("yt:UC9"))

    def test_the_page_lists_only_that_channel(self):
        self.assertEqual([r["ext_id"] for r in self.db.feed(channel_key="yt:UC1")],
                         ["aaaaaaaaaaa"])

    def test_the_video_count_excludes_shorts(self):
        self.db.upsert_videos([self.video("ccccccccccc", is_short=True)])
        self.assertEqual(self.db.channel("yt:UC1")["video_count"], 1)


class AppState(DatabaseCase):
    def test_round_trip_with_a_default(self):
        self.assertEqual(self.db.get_state("missing", "fallback"), "fallback")
        self.db.set_state("panel_width", "380")
        self.assertEqual(self.db.get_state("panel_width"), "380")


if __name__ == "__main__":
    unittest.main()
