import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

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


class MovingABox(DatabaseCase):
    """Boxes are ordered by hand the way groups are."""

    def three(self):
        return [self.db.create_box(name) for name in ("One", "Two", "Three")]

    def names(self):
        return [box["name"] for box in self.db.boxes()]

    def test_they_start_in_the_order_they_were_made(self):
        self.three()
        self.assertEqual(self.names(), ["One", "Two", "Three"])

    def test_one_can_be_moved_up(self):
        _, two, _ = self.three()
        self.assertTrue(self.db.move_box(two, -1))
        self.assertEqual(self.names(), ["Two", "One", "Three"])

    def test_and_down(self):
        _, two, _ = self.three()
        self.assertTrue(self.db.move_box(two, 1))
        self.assertEqual(self.names(), ["One", "Three", "Two"])

    def test_neither_end_moves_past_itself(self):
        one, _, three = self.three()
        self.assertFalse(self.db.move_box(one, -1))
        self.assertFalse(self.db.move_box(three, 1))
        self.assertEqual(self.names(), ["One", "Two", "Three"])

    def test_a_box_that_is_not_there_moves_nothing(self):
        self.three()
        self.assertFalse(self.db.move_box(999, 1))
        self.assertEqual(self.names(), ["One", "Two", "Three"])

    def test_a_gap_left_by_a_deletion_is_closed(self):
        # Positions are rewritten from the resulting order rather than
        # swapped, which is what makes a list with gaps in it come out
        # consecutive.
        one, two, three = self.three()
        self.db.delete_box(two)
        self.assertTrue(self.db.move_box(three, -1))
        self.assertEqual(self.names(), ["Three", "One"])
        self.assertEqual([box["position"] for box in self.db.boxes()], [0, 1])


class AVideoWhoseChannelIsUnknown(DatabaseCase):
    """A video always brings a channel row with it.

    A feed hands over entries owned by channels other than the one it belongs
    to. Refusing those on the foreign key threw out the whole batch, and the
    exception travelled far enough to stop the poll for good, so the missing
    channel is created instead.
    """

    def test_the_channel_is_created(self):
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", "yt:UCnew", "A video",
                                        channel_title="A stranger")])
        row = self.db.channel("yt:UCnew")
        self.assertEqual((row["title"], row["ext_id"]), ("A stranger", "UCnew"))

    def test_it_is_neither_polled_nor_in_all(self):
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", "yt:UCnew", "A video")])
        row = self.db.channel("yt:UCnew")
        self.assertEqual((row["tracked"], row["in_all"]), (0, 0))
        self.assertEqual(self.db.channels(), [])
        self.assertEqual(self.db.feed(), [])

    def test_a_nameless_stranger_is_still_stored(self):
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", "yt:UCnew", "A video")])
        self.assertIsNone(self.db.channel("yt:UCnew")["title"])
        self.assertTrue(self.db.channel_has_videos("yt:UCnew"))

    def test_a_channel_already_followed_is_left_exactly_as_it_was(self):
        # The dangerous direction. Writing a channel row here on every poll
        # could demote a followed channel or rename it after a feed entry.
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One", "https://a/av.jpg")
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", "yt:UC1", "A video",
                                        channel_title="Something else")])
        row = self.db.channel("yt:UC1")
        self.assertEqual((row["title"], row["avatar_url"], row["tracked"], row["in_all"]),
                         ("One", "https://a/av.jpg", 1, 1))

    def test_the_count_of_rows_touched_still_counts_videos_only(self):
        touched = self.db.upsert_videos([
            VideoRow("youtube", "aaaaaaaaaaa", "yt:UCnew", "A video"),
            VideoRow("youtube", "bbbbbbbbbbb", "yt:UCother", "Another"),
        ])
        self.assertEqual(touched, 2)


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

    def test_a_channel_nobody_has_looked_at_is_a_question_not_a_no(self):
        # The bug this replaces: whether a channel streams was inferred from
        # having stored a stream of theirs already, and the only thing that
        # stores one is either that very tab or a sweep of the subscriptions.
        # A channel the sweep never reaches was therefore never asked at all.
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.assertEqual(self.db.channels_that_stream(), set())
        self.assertEqual(self.db.channels_not_asked_for_streams(), {"yt:UC1"})

    def test_an_answer_either_way_settles_it(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.db.set_channel_streams("yt:UC1", True)
        self.assertEqual(self.db.channels_not_asked_for_streams(), set())
        self.assertEqual(self.db.channels_that_stream(), {"yt:UC1"})
        self.db.set_channel_streams("yt:UC1", False)
        self.assertEqual(self.db.channels_not_asked_for_streams(), set())
        self.assertEqual(self.db.channels_that_stream(), set())

    def test_one_looked_at_and_found_without_a_streams_tab_is_left_alone(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.db.add_channel("yt:UC2", "youtube", "UC2")
        self.db.set_channel_streams("yt:UC1", False)
        self.db.set_channel_streams("yt:UC2", True)
        self.assertEqual(self.db.channels_that_stream(), {"yt:UC2"})

    def test_a_stream_from_anywhere_else_puts_it_back(self):
        # The sweep reports a live video without the tab being asked, and that
        # outranks an older verdict of no.
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.db.set_channel_streams("yt:UC1", False)
        self.db.upsert_videos([self.video("aaaaaaaaaaa", channel="yt:UC1",
                                          live_status="was_live")])
        self.assertEqual(self.db.channels_that_stream(), {"yt:UC1"})

    def test_a_channel_that_is_not_polled_is_not_asked(self):
        self.db.remember_channel("yt:UC9", "youtube", "UC9", "Kept for a video")
        self.assertNotIn("yt:UC9", self.db.channels_that_stream())
        self.assertNotIn("yt:UC9", self.db.channels_not_asked_for_streams())

    def test_the_feed_variant_is_remembered(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.assertIsNone(self.db.channels()[0]["feed_variant"])
        self.db.set_feed_variant("yt:UC1", "channel")
        self.assertEqual(self.db.channels()[0]["feed_variant"], "channel")

    def test_and_it_can_be_taken_back(self):
        # A fallback taken while the endpoint was refusing is simply wrong,
        # so there has to be a way back to the tab feed.
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.db.set_feed_variant("yt:UC1", "channel")
        self.db.set_feed_variant("yt:UC1", None)
        self.assertIsNone(self.db.channels()[0]["feed_variant"])

    def test_a_404_on_the_long_form_tab_is_counted_rather_than_believed(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.assertEqual(self.db.channels()[0]["long_form_404s"], 0)
        self.assertEqual(self.db.note_long_form_missing("yt:UC1"), 1)
        self.assertEqual(self.db.note_long_form_missing("yt:UC1"), 2)

    def test_the_count_is_wiped_by_an_answer(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.db.note_long_form_missing("yt:UC1")
        self.db.clear_long_form_strikes("yt:UC1")
        self.assertEqual(self.db.channels()[0]["long_form_404s"], 0)

    def test_clearing_the_variant_clears_the_count_with_it(self):
        # One decision: the tab answered, so nothing is held against it.
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.db.note_long_form_missing("yt:UC1")
        self.db.set_feed_variant("yt:UC1", None)
        self.assertEqual(self.db.channels()[0]["long_form_404s"], 0)

    def test_the_stamps_say_when_each_question_was_last_asked(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        row = self.db.channels()[0]
        self.assertIsNone(row["variant_checked_at"])
        self.assertIsNone(row["shorts_sweep_at"])
        self.db.stamp_variant_checked("yt:UC1")
        self.db.stamp_shorts_sweep("yt:UC1")
        row = self.db.channels()[0]
        self.assertTrue(row["variant_checked_at"])
        self.assertTrue(row["shorts_sweep_at"])

    def test_a_row_of_unknown_kind_can_still_be_named(self):
        # The mixed feed stores rows that say nothing about their kind, and
        # the Shorts tab is what fills that in later. A kind already known
        # wins, since it came from a feed that carries one thing only.
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.db.upsert_videos([self.video("aaaaaaaaaaa")])
        self.db.upsert_videos([replace(self.video("aaaaaaaaaaa"), is_short=True)])
        kind = self.db.conn.execute(
            "SELECT is_short FROM videos WHERE key='yt:aaaaaaaaaaa'").fetchone()[0]
        self.assertEqual(kind, 1)

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
        self.db.fill_details([("yt:aaaaaaaaaaa", SHORTS_CEILING_S + 1, None, None)])
        row = next(r for r in self.db.feed() if r["ext_id"] == "aaaaaaaaaaa")
        self.assertEqual(row["is_short"], 0)

    def test_an_announced_stream_is_stored_with_its_start_time(self):
        self.db.upsert_videos([self.video("aaaaaaaaaaa")])
        self.db.fill_details([("yt:aaaaaaaaaaa", None, "is_upcoming", 1_900_000_000)])
        row = next(r for r in self.db.feed() if r["ext_id"] == "aaaaaaaaaaa")
        self.assertEqual(row["live_status"], "is_upcoming")
        self.assertEqual(row["scheduled_at"], 1_900_000_000)

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
        self.assertEqual(len(self.db.group_channels(self.group)), 2)

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
        # What the tick beside each entry in the channel menu reads. All
        # answers as -1, since that menu asks one question of every list a
        # channel can be shown in and All is one of them.
        second = self.db.create_group("Second")
        self.db.add_to_group(self.group, "yt:UC1")
        self.assertEqual(self.db.groups_holding("yt:UC1"), [-1, self.group])
        self.db.add_to_group(second, "yt:UC1")
        self.assertEqual(sorted(self.db.groups_holding("yt:UC1")),
                         sorted([-1, self.group, second]))
        self.db.remove_from_group(self.group, "yt:UC1")
        self.assertEqual(self.db.groups_holding("yt:UC1"), [-1, second])
        self.db.remove_from_all("yt:UC1")
        self.assertEqual(self.db.groups_holding("yt:UC1"), [second])

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

    def test_renaming_onto_another_group_is_refused_not_raised(self):
        other = self.db.create_group("Music")
        self.assertFalse(self.db.rename_group(other, "Gaming"))
        self.assertEqual(self.db.group_by_name("Music")["id"], other)

    def test_renaming_to_a_free_name_works(self):
        self.assertTrue(self.db.rename_group(self.group, "Games"))
        self.assertEqual(self.db.group_by_name("Games")["id"], self.group)
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


class SearchAndHistory(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC1", "youtube", "UC1", "Example Channel")
        self.db.add_channel("yt:UC2", "youtube", "UC2", "Somebody else")
        self.db.upsert_videos([
            self.video("aaaaaaaaaaa", title="A hundred % of nothing", published_at=300),
            self.video("bbbbbbbbbbb", channel="yt:UC2", title="under_score", published_at=200),
            self.video("ccccccccccc", channel="yt:UC2", title="Plain", published_at=100),
        ])

    def found(self, text, hide_watched=False):
        # Searching is asking for one particular video, so the view that runs
        # a search turns the hide watched toggle off. Storage still honours it
        # when asked to, which is what the pair of tests below pin down.
        return sorted(row["ext_id"] for row in
                      self.db.feed(query=text, hide_watched=hide_watched))

    def test_a_search_matches_the_title(self):
        self.assertEqual(self.found("hundred"), ["aaaaaaaaaaa"])

    def test_a_search_matches_the_channel_name(self):
        self.assertEqual(self.found("example"), ["aaaaaaaaaaa"])

    def test_a_wildcard_in_the_words_is_a_wildcard_no_longer(self):
        # A title really can contain one, and treating it as a pattern would
        # make searching for it match everything instead.
        self.assertEqual(self.found("%"), ["aaaaaaaaaaa"])
        self.assertEqual(self.found("under_"), ["bbbbbbbbbbb"])

    def test_a_search_finds_watched_videos_too(self):
        # How the search view asks, since hiding the watched ones would hide
        # the answer.
        self.db.set_watched("yt:aaaaaaaaaaa", 1.0, "mpv")
        self.assertEqual(self.found("hundred"), ["aaaaaaaaaaa"])

    def test_but_storage_still_hides_them_when_asked_to(self):
        self.db.set_watched("yt:aaaaaaaaaaa", 1.0, "mpv")
        self.assertEqual(self.found("hundred", hide_watched=True), [])

    def test_a_short_never_turns_up_in_a_search(self):
        self.db.upsert_videos([self.video("ddddddddddd", title="hundred", is_short=True)])
        self.assertEqual(self.found("hundred"), ["aaaaaaaaaaa"])

    def test_history_is_what_was_watched_most_recently_first(self):
        self.db.set_watched("yt:ccccccccccc", 1.0, "mpv")
        self.db.set_watched("yt:aaaaaaaaaaa", 1.0, "mpv")
        rows = self.db.feed(watched_only=True, hide_watched=False)
        self.assertEqual([r["ext_id"] for r in rows], ["aaaaaaaaaaa", "ccccccccccc"])

    def test_importing_a_history_marks_what_is_stored(self):
        marked, missing = self.db.mark_watched_many(
            ["yt:aaaaaaaaaaa", "yt:zzzzzzzzzzz"], "youtube")
        self.assertEqual((marked, missing), (1, 1))

    def test_an_import_never_overwrites_what_mpv_saw(self):
        self.db.set_watched("yt:aaaaaaaaaaa", 0.9, "mpv")
        self.db.mark_watched_many(["yt:aaaaaaaaaaa"], "youtube")
        row = self.db.conn.execute(
            "SELECT source, progress FROM watched WHERE video_key='yt:aaaaaaaaaaa'").fetchone()
        self.assertEqual((row["source"], row["progress"]), ("mpv", 0.9))

    def test_importing_nothing_is_not_an_error(self):
        self.assertEqual(self.db.mark_watched_many([], "youtube"), (0, 0))


class Recommendations(DatabaseCase):
    """Kept apart from the feed on purpose, and shaped like it anyway."""

    def rows(self, *ids):
        return [{"ext_id": i, "title": f"Video {i}", "channel_name": "Someone",
                 "channel_ext_id": "UC9", "duration_s": 60, "thumbnail_url": "t"}
                for i in ids]

    def test_nothing_is_written_into_the_feed(self):
        # The whole point. A suggestion must never look like a channel followed.
        self.db.replace_recommended(self.rows("aaaaaaaaaaa"))
        self.assertEqual(self.db.feed(), [])
        self.assertEqual(self.db.channels(), [])

    def test_a_refresh_replaces_rather_than_accumulates(self):
        self.db.replace_recommended(self.rows("aaaaaaaaaaa", "bbbbbbbbbbb"))
        self.db.replace_recommended(self.rows("ccccccccccc"))
        self.assertEqual([r["ext_id"] for r in self.db.recommended()], ["ccccccccccc"])

    def test_the_order_it_came_in_is_the_order_shown(self):
        self.db.replace_recommended(self.rows("bbbbbbbbbbb", "aaaaaaaaaaa"))
        self.assertEqual([r["ext_id"] for r in self.db.recommended()],
                         ["bbbbbbbbbbb", "aaaaaaaaaaa"])

    def test_a_suggestion_from_a_tracked_channel_gets_its_icon(self):
        self.db.add_channel("yt:UC9", "youtube", "UC9", "Real name", "http://a/av.jpg")
        self.db.replace_recommended(self.rows("aaaaaaaaaaa"))
        row = self.db.recommended()[0]
        self.assertEqual((row["channel_title"], row["avatar_url"], row["channel_key"]),
                         ("Real name", "http://a/av.jpg", "yt:UC9"))

    def test_a_suggestion_from_a_stranger_keeps_the_bare_name(self):
        self.db.replace_recommended(self.rows("aaaaaaaaaaa"))
        row = self.db.recommended()[0]
        self.assertEqual(row["channel_title"], "Someone")
        self.assertIsNone(row["avatar_url"])

    def test_and_still_has_a_key_to_address_that_channel_by(self):
        # Worked out from the channel id rather than read off a row, since
        # there is no row. Without it a suggestion's channel could not be put
        # in a group, because the menu has nothing but this key to go on.
        self.db.replace_recommended(self.rows("aaaaaaaaaaa"))
        self.assertEqual(self.db.recommended()[0]["channel_key"], "yt:UC9")

    def test_watched_is_carried_across(self):
        self.db.add_channel("yt:UC9", "youtube", "UC9", "Real name")
        self.db.upsert_videos([self.video("aaaaaaaaaaa", channel="yt:UC9")])
        self.db.set_watched("yt:aaaaaaaaaaa", 1.0, "mpv")
        self.db.replace_recommended(self.rows("aaaaaaaaaaa"))
        self.assertTrue(self.db.recommended()[0]["watched"])

    def test_how_old_the_set_is(self):
        self.assertIsNone(self.db.recommended_age_s())
        self.db.replace_recommended(self.rows("aaaaaaaaaaa"))
        self.assertLess(self.db.recommended_age_s(), 5)


class CachedLists(DatabaseCase):
    """What YouTube suggests and what it says you watched. Same shape, same
    table, kept apart from the feed."""

    def rows(self, *ids):
        return [{"ext_id": i, "title": f"Video {i}", "channel_name": "Someone",
                 "channel_ext_id": "UC9", "duration_s": 60, "thumbnail_url": "t"}
                for i in ids]

    def test_the_two_kinds_do_not_see_each_other(self):
        self.db.replace_cached(self.db.RECOMMENDED, self.rows("aaaaaaaaaaa"))
        self.db.replace_cached(self.db.HISTORY, self.rows("bbbbbbbbbbb"))
        self.assertEqual([r["ext_id"] for r in self.db.cached(self.db.RECOMMENDED)],
                         ["aaaaaaaaaaa"])
        self.assertEqual([r["ext_id"] for r in self.db.cached(self.db.HISTORY)],
                         ["bbbbbbbbbbb"])

    def test_more_is_added_on_the_end(self):
        # What scrolling to the bottom does. The order has to hold, or the
        # grid would reshuffle itself under the reader.
        self.db.replace_cached(self.db.HISTORY, self.rows("aaaaaaaaaaa", "bbbbbbbbbbb"))
        added = self.db.append_cached(self.db.HISTORY, self.rows("ccccccccccc"))
        self.assertEqual(added, 1)
        self.assertEqual([r["ext_id"] for r in self.db.cached(self.db.HISTORY)],
                         ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])

    def test_a_page_that_repeats_itself_adds_nothing(self):
        # Which is how the end of a list is recognised.
        self.db.replace_cached(self.db.HISTORY, self.rows("aaaaaaaaaaa"))
        self.assertEqual(self.db.append_cached(self.db.HISTORY, self.rows("aaaaaaaaaaa")), 0)

    def test_counting_one_kind(self):
        self.db.replace_cached(self.db.HISTORY, self.rows("aaaaaaaaaaa", "bbbbbbbbbbb"))
        self.db.replace_cached(self.db.RECOMMENDED, self.rows("ccccccccccc"))
        self.assertEqual(self.db.cached_count(self.db.HISTORY), 2)
        self.assertEqual(self.db.cached_count(self.db.RECOMMENDED), 1)

    def test_each_kind_ages_on_its_own(self):
        self.assertIsNone(self.db.cached_age_s(self.db.HISTORY))
        self.db.replace_cached(self.db.HISTORY, self.rows("aaaaaaaaaaa"))
        self.assertLess(self.db.cached_age_s(self.db.HISTORY), 5)
        self.assertIsNone(self.db.cached_age_s(self.db.RECOMMENDED))

    def test_a_history_entry_with_no_channel_still_shows(self):
        # Measured: a history row says nothing at all about the channel.
        self.db.replace_cached(self.db.HISTORY, [
            {"ext_id": "aaaaaaaaaaa", "title": "No channel named", "channel_name": None,
             "channel_ext_id": None, "duration_s": 10, "thumbnail_url": "t"}])
        row = self.db.cached(self.db.HISTORY)[0]
        self.assertEqual((row["title"], row["channel_title"], row["channel_key"]),
                         ("No channel named", None, ""))


class LiveStreamDetail(DatabaseCase):
    """A stream is not a video and has no row among them, so the panel has to
    find it where it does live."""

    def setUp(self):
        super().setUp()
        self.db.add_channel("twitch:alpha", "twitch", "alpha", "Alpha", "http://a/av.jpg")
        self.db.replace_live("twitch", [{
            "channel_key": "twitch:alpha", "login": "alpha", "display_name": "Alpha",
            "title": "Playing something", "game": "Chess", "viewers": 42,
            "started_at": "2026-01-01T10:00:00Z", "thumbnail_url": "http://a/t.jpg"}])

    def test_a_stream_that_is_on_can_be_looked_up(self):
        row = self.db.live_stream("twitch:alpha")
        self.assertEqual((row["title"], row["game"], row["viewers"]),
                         ("Playing something", "Chess", 42))

    def test_it_brings_the_channel_picture_with_it(self):
        self.assertEqual(self.db.live_stream("twitch:alpha")["avatar_url"], "http://a/av.jpg")

    def test_a_channel_that_is_not_on_has_nothing_to_show(self):
        self.assertIsNone(self.db.live_stream("twitch:nobody"))

    def test_and_neither_does_one_whose_check_stopped_working(self):
        import time as clock
        self.db.conn.execute("UPDATE live_streams SET seen_at = ?",
                             (int(clock.time()) - self.db.LIVE_STALE_S - 1,))
        self.db.conn.commit()
        self.assertIsNone(self.db.live_stream("twitch:alpha"))


class SearchDecoration(DatabaseCase):
    """Search results are never stored, so they are joined to what is known
    here on the way to the grid."""

    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC9", "youtube", "UC9", "Tracked", "http://a/av.jpg")
        self.db.upsert_videos([self.video("aaaaaaaaaaa", channel="yt:UC9")])
        self.db.set_watched("yt:aaaaaaaaaaa", 1.0, "mpv")

    def flat(self, ext_id, channel_ext_id):
        return {"ext_id": ext_id, "title": "A result", "channel_name": "Whatever YouTube said",
                "channel_ext_id": channel_ext_id, "duration_s": 10, "thumbnail_url": "t",
                "views": 5}

    def test_a_result_from_a_tracked_channel_gets_its_name_and_icon(self):
        row = self.db.decorate([self.flat("bbbbbbbbbbb", "UC9")])[0]
        self.assertEqual((row["channel_title"], row["channel_key"], row["avatar_url"]),
                         ("Tracked", "yt:UC9", "http://a/av.jpg"))

    def test_a_result_from_a_stranger_keeps_what_youtube_said(self):
        row = self.db.decorate([self.flat("bbbbbbbbbbb", None)])[0]
        self.assertEqual((row["channel_title"], row["channel_key"]),
                         ("Whatever YouTube said", ""))

    def test_a_result_already_watched_says_so(self):
        row = self.db.decorate([self.flat("aaaaaaaaaaa", "UC9")])[0]
        self.assertTrue(row["watched"])

    def test_nothing_is_stored_by_decorating(self):
        self.db.decorate([self.flat("bbbbbbbbbbb", "UC9")])
        self.assertEqual(len(self.db.feed(hide_watched=False)), 1)

    def test_nothing_at_all(self):
        self.assertEqual(self.db.decorate([]), [])


class Playlists(DatabaseCase):
    """YouTube's own lists. Their videos are kept out of the feed for the same
    reason recommendations are."""

    def items(self, *ids):
        return [{"ext_id": i, "title": f"Video {i}", "channel_name": "Someone",
                 "channel_ext_id": "UC9", "duration_s": 60, "thumbnail_url": "t"}
                for i in ids]

    def test_the_list_replaces_rather_than_accumulates(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"},
                                   {"ext_id": "PL2", "title": "Two"}])
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One renamed"}])
        self.assertEqual([(p["ext_id"], p["title"]) for p in self.db.playlists()],
                         [("PL1", "One renamed")])

    def test_a_playlist_that_is_gone_takes_its_videos_with_it(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.db.replace_playlist_items("PL1", self.items("aaaaaaaaaaa"))
        self.db.replace_playlists([])
        self.assertEqual(self.db.playlist_items("PL1"), [])

    def test_contents_survive_the_list_being_read_again(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.db.replace_playlist_items("PL1", self.items("aaaaaaaaaaa"))
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.assertEqual(len(self.db.playlist_items("PL1")), 1)

    def test_nothing_reaches_the_feed(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.db.replace_playlist_items("PL1", self.items("aaaaaaaaaaa"))
        self.assertEqual(self.db.feed(), [])
        self.assertEqual(self.db.channels(), [])

    def test_a_playlist_keeps_the_order_it_was_given(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.db.replace_playlist_items("PL1", self.items("bbbbbbbbbbb", "aaaaaaaaaaa"))
        self.assertEqual([r["ext_id"] for r in self.db.playlist_items("PL1")],
                         ["bbbbbbbbbbb", "aaaaaaaaaaa"])

    def test_a_video_from_a_tracked_channel_gets_its_icon(self):
        self.db.add_channel("yt:UC9", "youtube", "UC9", "Real name", "http://a/av.jpg")
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.db.replace_playlist_items("PL1", self.items("aaaaaaaaaaa"))
        row = self.db.playlist_items("PL1")[0]
        self.assertEqual((row["channel_title"], row["channel_key"]), ("Real name", "yt:UC9"))

    def test_the_order_can_be_changed_by_hand(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"},
                                   {"ext_id": "PL2", "title": "Two"},
                                   {"ext_id": "PL3", "title": "Three"}])
        order = lambda: [p["ext_id"] for p in self.db.playlists()]
        self.assertTrue(self.db.move_playlist("PL3", -1))
        self.assertEqual(order(), ["PL1", "PL3", "PL2"])
        self.assertTrue(self.db.move_playlist("PL3", 1))
        self.assertEqual(order(), ["PL1", "PL2", "PL3"])

    def test_moving_past_either_end_is_not_a_move(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"},
                                   {"ext_id": "PL2", "title": "Two"}])
        self.assertFalse(self.db.move_playlist("PL1", -1))
        self.assertFalse(self.db.move_playlist("PL2", 1))
        self.assertFalse(self.db.move_playlist("nope", 1))

    def test_reading_the_list_again_keeps_the_order_chosen_here(self):
        # A refresh is not a reason to undo an order somebody set.
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"},
                                   {"ext_id": "PL2", "title": "Two"}])
        self.db.move_playlist("PL2", -1)
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"},
                                   {"ext_id": "PL2", "title": "Two"}])
        self.assertEqual([p["ext_id"] for p in self.db.playlists()], ["PL2", "PL1"])

    def test_a_new_playlist_goes_on_the_end(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.db.replace_playlists([{"ext_id": "PL9", "title": "New"},
                                   {"ext_id": "PL1", "title": "One"}])
        self.assertEqual([p["ext_id"] for p in self.db.playlists()], ["PL1", "PL9"])

    def test_a_hidden_one_moves_with_the_rest(self):
        # It is out of sight, not out of the order.
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"},
                                   {"ext_id": "PL2", "title": "Two"}])
        self.db.set_playlist_hidden("PL1", True)
        self.assertTrue(self.db.move_playlist("PL2", -1))
        self.assertEqual([p["ext_id"] for p in self.db.playlists(include_hidden=True)],
                         ["PL2", "PL1"])

    def test_reading_the_contents_is_stamped(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.assertIsNone(self.db.playlist("PL1")["items_at"])
        self.db.replace_playlist_items("PL1", self.items("aaaaaaaaaaa"))
        self.assertIsNotNone(self.db.playlist("PL1")["items_at"])

    def test_the_count_beside_the_name(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.db.replace_playlist_items("PL1", self.items("aaaaaaaaaaa", "bbbbbbbbbbb"))
        self.assertEqual(self.db.playlists()[0]["items"], 2)

    def test_a_playlist_starts_with_nothing_skipped(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.assertEqual(self.db.playlist("PL1")["skipped"], 0)

    def test_the_skipped_count_is_kept_with_the_playlist(self):
        # A private or a deleted entry never becomes a row at all, so the
        # count travels alongside the fetch rather than being derivable from
        # the items table afterwards.
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.db.replace_playlist_items("PL1", self.items("aaaaaaaaaaa"), skipped=3)
        self.assertEqual(self.db.playlist("PL1")["skipped"], 3)

    def test_reading_the_contents_again_replaces_the_skipped_count(self):
        self.db.replace_playlists([{"ext_id": "PL1", "title": "One"}])
        self.db.replace_playlist_items("PL1", self.items("aaaaaaaaaaa"), skipped=2)
        self.db.replace_playlist_items("PL1", self.items("aaaaaaaaaaa"), skipped=0)
        self.assertEqual(self.db.playlist("PL1")["skipped"], 0)


class LiveFreshness(DatabaseCase):
    """A live bar that lies is worse than an empty one."""

    def setUp(self):
        super().setUp()
        self.db.add_channel("twitch:alpha", "twitch", "alpha", "Alpha")
        self.db.replace_live("twitch", [{"channel_key": "twitch:alpha", "login": "alpha",
                                         "display_name": "Alpha", "viewers": 10}])

    def test_a_fresh_check_shows(self):
        self.assertEqual(len(self.db.live_now()), 1)

    def test_rows_from_a_check_that_stopped_working_go_away(self):
        # Rows are only replaced by a check that succeeded, so a login that
        # has expired would otherwise leave yesterday's streams on screen
        # looking current.
        import time as clock
        self.db.conn.execute("UPDATE live_streams SET seen_at = ?",
                             (int(clock.time()) - self.db.LIVE_STALE_S - 1,))
        self.db.conn.commit()
        self.assertEqual(self.db.live_now(), [])


class AppState(DatabaseCase):
    def test_a_stored_number_reads_back_as_one(self):
        self.db.set_state("panel_width", "412")
        self.assertEqual(self.db.get_int("panel_width", 380), 412)

    def test_nothing_stored_is_the_default(self):
        self.assertEqual(self.db.get_int("panel_width", 380), 380)

    def test_a_row_that_is_not_a_number_is_the_default_rather_than_a_crash(self):
        # A row this program never wrote, or wrote in another spelling once.
        for text in ("wide", "", "12px", "nan"):
            with self.subTest(text=text):
                self.db.set_state("panel_width", text)
                self.assertEqual(self.db.get_int("panel_width", 380), 380)

    def test_a_number_written_as_a_float_is_read_whole(self):
        self.db.set_state("panel_width", "412.0")
        self.assertEqual(self.db.get_int("panel_width", 380), 412)

    def test_round_trip_with_a_default(self):
        self.assertEqual(self.db.get_state("missing", "fallback"), "fallback")
        self.db.set_state("panel_width", "380")
        self.assertEqual(self.db.get_state("panel_width"), "380")


if __name__ == "__main__":
    unittest.main()
