import tempfile
import unittest
from pathlib import Path

from weave.db import SHORTS_CEILING_S, Database, VideoRow


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

    def test_only_channels_past_the_interval_are_due(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1")
        self.assertEqual(len(self.db.channels_due(900)), 1)   # never polled
        self.db.mark_polled("yt:UC1")
        self.assertEqual(len(self.db.channels_due(900)), 0)   # just polled
        self.assertEqual(len(self.db.channels_due(0)), 1)     # everything is due

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


class ShortsClassification(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.upsert_videos([self.video("aaaaaaaaaaa"),      # long, once known
                               self.video("bbbbbbbbbbb"),      # short enough to test
                               self.video("ccccccccccc")])     # duration still unknown

    def test_unknown_duration_is_still_a_candidate(self):
        # It has to be. Most stored videos never get a duration, because the
        # subscriptions sweep only reaches the newest entries, so excluding
        # them left the whole feed unclassified and hid nothing.
        self.assertIn("ccccccccccc",
                      [r["ext_id"] for r in self.db.videos_needing_short_check()])

    def test_a_long_duration_settles_it_with_no_request(self):
        self.db.fill_details([("yt:aaaaaaaaaaa", SHORTS_CEILING_S + 1, None)])
        row = next(r for r in self.db.feed() if r["ext_id"] == "aaaaaaaaaaa")
        self.assertEqual(row["is_short"], 0)

    def test_a_settled_long_video_stops_being_a_candidate(self):
        self.db.fill_details([("yt:aaaaaaaaaaa", 3600, None), ("yt:bbbbbbbbbbb", 45, None)])
        self.assertNotIn("aaaaaaaaaaa",
                         [r["ext_id"] for r in self.db.videos_needing_short_check()])

    def test_a_confirmed_short_leaves_the_feed(self):
        self.db.set_short("yt:bbbbbbbbbbb", True)
        self.assertNotIn("bbbbbbbbbbb", [r["ext_id"] for r in self.db.feed()])

    def test_an_unclassified_video_still_shows(self):
        self.assertIn("ccccccccccc", [r["ext_id"] for r in self.db.feed()])


class TabClassification(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")
        self.db.upsert_videos([self.video("aaaaaaaaaaa"), self.video("bbbbbbbbbbb"),
                               self.video("ccccccccccc")])

    def test_marking_from_the_tabs(self):
        self.assertEqual(self.db.set_kind("yt:UC1", {"aaaaaaaaaaa"}, is_short=True), 1)
        self.assertEqual(self.db.set_kind("yt:UC1", {"bbbbbbbbbbb"}, is_short=False), 1)
        kinds = {r["ext_id"]: r["is_short"] for r in
                 self.db.conn.execute("SELECT ext_id, is_short FROM videos")}
        self.assertEqual(kinds, {"aaaaaaaaaaa": 1, "bbbbbbbbbbb": 0, "ccccccccccc": None})

    def test_a_video_in_neither_tab_stays_undecided_and_keeps_showing(self):
        self.db.set_kind("yt:UC1", {"aaaaaaaaaaa"}, is_short=True)
        self.db.set_kind("yt:UC1", {"bbbbbbbbbbb"}, is_short=False)
        self.assertIn("ccccccccccc", [r["ext_id"] for r in self.db.feed()])

    def test_a_decision_is_never_overwritten(self):
        self.db.set_kind("yt:UC1", {"aaaaaaaaaaa"}, is_short=True)
        self.assertEqual(self.db.set_kind("yt:UC1", {"aaaaaaaaaaa"}, is_short=False), 0)

    def test_ids_from_another_channel_are_ignored(self):
        self.db.add_channel("yt:UC2", "youtube", "UC2", "Two")
        self.assertEqual(self.db.set_kind("yt:UC2", {"aaaaaaaaaaa"}, is_short=True), 0)

    def test_only_channels_with_undecided_videos_need_a_request(self):
        self.assertEqual([c["key"] for c in self.db.channels_needing_classification(0)],
                         ["yt:UC1"])
        self.db.set_kind("yt:UC1", {"aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"},
                         is_short=False)
        self.assertEqual(self.db.channels_needing_classification(0), [])

    def test_a_recent_check_is_not_repeated(self):
        self.db.mark_classified("yt:UC1")
        self.assertEqual(self.db.channels_needing_classification(21600), [])
        self.assertEqual(len(self.db.channels_needing_classification(0)), 1)

    def test_unclassified_counts(self):
        self.assertEqual(self.db.unclassified_count(), 3)
        self.db.set_kind("yt:UC1", {"aaaaaaaaaaa"}, is_short=True)
        self.assertEqual(self.db.unclassified_count("yt:UC1"), 2)


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
        self.db.upsert_videos([self.video("bbbbbbbbbbb"), self.video("ccccccccccc")])
        self.db.set_watched("yt:bbbbbbbbbbb", 1.0, "mpv")
        self.db.set_short("yt:ccccccccccc", True)
        self.assertEqual(self.db.groups()[0]["unwatched"], 1)
        self.assertEqual(self.db.unwatched_total(), 1)

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


class AppState(DatabaseCase):
    def test_round_trip_with_a_default(self):
        self.assertEqual(self.db.get_state("missing", "fallback"), "fallback")
        self.db.set_state("panel_width", "380")
        self.assertEqual(self.db.get_state("panel_width"), "380")


if __name__ == "__main__":
    unittest.main()
