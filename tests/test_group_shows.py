"""Which half of a group is being looked at.

A group mixes channels who post videos with channels who stream, and those are
not read the same way. The three buttons over a group say which of them is
wanted, and the answer belongs to the group: a group of people who stream and
a group of people who do not are not looked at the same way, so one setting
shared by every group would be wrong in one of them whichever way it was set.

Stored rather than held, so a group is still showing what it was told to show
after a restart. Both readings are of rows that are already here, so pressing
one of the three costs no request.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave.db import (GROUP_SHOWS, GROUP_SHOWS_ALL, GROUP_SHOWS_STREAMS,
                      GROUP_SHOWS_VIDEOS, Database, VideoRow)

CHANNEL = "UCaaaaaaaaaaaaaaaaaaaaaa"
CHANNEL_KEY = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"


def video(ext_id, **fields):
    return VideoRow(platform="youtube", ext_id=ext_id, channel_key=CHANNEL_KEY,
                    title=f"Video {ext_id}", published_at=1600000000,
                    thumbnail_url="https://i/x.jpg", is_short=False, **fields)


def key(ext_id):
    return f"yt:{ext_id}"


class WhatIsStored(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.group = self.db.create_group("Mine")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_a_new_group_shows_all_of_itself(self):
        self.assertEqual(self.db.group_shows(self.group), GROUP_SHOWS_ALL)

    def test_it_is_remembered(self):
        self.assertTrue(self.db.set_group_shows(self.group, GROUP_SHOWS_STREAMS))
        self.assertEqual(self.db.group_shows(self.group), GROUP_SHOWS_STREAMS)

    def test_it_survives_the_database_being_reopened(self):
        self.db.set_group_shows(self.group, GROUP_SHOWS_VIDEOS)
        path = Path(self._tmp.name) / "test.db"
        self.db.close()
        self.db = Database(path)
        self.assertEqual(self.db.group_shows(self.group), GROUP_SHOWS_VIDEOS)

    def test_a_value_nothing_can_read_is_refused(self):
        self.db.set_group_shows(self.group, GROUP_SHOWS_STREAMS)
        self.assertFalse(self.db.set_group_shows(self.group, "sideways"))
        self.assertEqual(self.db.group_shows(self.group), GROUP_SHOWS_STREAMS)

    def test_each_group_keeps_its_own_answer(self):
        other = self.db.create_group("Theirs")
        self.db.set_group_shows(self.group, GROUP_SHOWS_STREAMS)
        self.assertEqual(self.db.group_shows(other), GROUP_SHOWS_ALL)

    def test_a_group_that_has_gone_shows_all(self):
        # A view left pointing at a deleted group asks about it, and answering
        # anything else would filter a feed nobody can unfilter.
        self.assertEqual(self.db.group_shows(self.group + 5000), GROUP_SHOWS_ALL)

    def test_the_list_of_groups_carries_it(self):
        self.db.set_group_shows(self.group, GROUP_SHOWS_VIDEOS)
        found = next(row for row in self.db.groups() if row["id"] == self.group)
        self.assertEqual(found["shows"], GROUP_SHOWS_VIDEOS)

    def test_the_three_are_the_three(self):
        self.assertEqual(GROUP_SHOWS, ("all", "videos", "streams"))


class WhatTheFeedAnswers(unittest.TestCase):
    """The same rows read three ways. A stream is a row with a live status, a
    start time or an announcement still to be settled."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.db.add_channel(CHANNEL_KEY, "youtube", CHANNEL, "Someone")
        self.group = self.db.create_group("Mine")
        self.db.add_to_group(self.group, CHANNEL_KEY)
        self.db.upsert_videos([
            video("videoaaaaaa"),
            video("videobbbbbb"),
            video("streamaaaaa", live_status="was_live"),
            video("streambbbbb", live_status="is_upcoming"),
        ])
        # A start time is filled in by the pass that asks about it, never by
        # the listing, so it is written the way that pass writes it.
        self.db.set_scheduled_at(key("streambbbbb"), 1600001000)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def ids(self, streams):
        return sorted(row["ext_id"] for row in
                      self.db.feed(group_id=self.group, streams=streams))

    def test_all_of_it_is_both(self):
        self.assertEqual(len(self.ids(None)), 4)

    def test_videos_leaves_the_streams_out(self):
        self.assertEqual(self.ids(False), ["videoaaaaaa", "videobbbbbb"])

    def test_streams_leaves_the_videos_out(self):
        self.assertEqual(self.ids(True), ["streamaaaaa", "streambbbbb"])

    def test_an_announcement_not_yet_settled_is_a_stream(self):
        self.db.upsert_videos([video("pendingaaaa")])
        self.db.mark_streams_pending([key("pendingaaaa")])
        self.assertIn("pendingaaaa", self.ids(True))
        self.assertNotIn("pendingaaaa", self.ids(False))


class WhatTheWindowDoes(unittest.TestCase):
    """The bridge side, on a stubbed bridge: which reading the feed is asked
    for, and what the empty page says."""

    def setUp(self):
        from weave.ui.bridge import Bridge

        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.db.add_channel(CHANNEL_KEY, "youtube", CHANNEL, "Someone")
        self.group = self.db.create_group("Mine")
        self.db.add_to_group(self.group, CHANNEL_KEY)

        bridge = Bridge.__new__(Bridge)
        bridge._db = self.db
        bridge._view_kind = "group"
        bridge._view_id = self.group
        bridge._view_channel = ""
        bridge._view_playlist = ""
        bridge._channel_tab = "videos"
        bridge._search_text = ""
        bridge._search_scope = "stored"
        bridge._hide_watched = False
        bridge._history_music = False
        bridge._web_results = []
        self.asked = []
        bridge._model = type("Model", (), {
            "reload": lambda _s, **kw: self.asked.append(kw),
            "show": lambda _s, rows: None,
        })()
        self.told = 0

        def told():
            self.told += 1
        bridge.emptyHintChanged = type("Sig", (), {"emit": staticmethod(lambda: None)})()
        bridge.groupsChanged = type("Sig", (), {"emit": staticmethod(lambda: None)})()
        bridge.boxesChanged = type("Sig", (), {"emit": staticmethod(lambda: None)})()
        bridge.playlistSkippedChanged = type("Sig", (), {"emit": staticmethod(lambda: None)})()
        bridge.groupShowsChanged = type("Sig", (), {"emit": staticmethod(told)})()
        self.bridge = bridge
        self.Bridge = Bridge

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def reload(self):
        self.asked.clear()
        self.Bridge.reload(self.bridge)
        return self.asked[-1]

    def test_all_asks_for_both(self):
        self.assertIsNone(self.reload()["streams"])

    def test_videos_asks_for_the_videos(self):
        self.db.set_group_shows(self.group, GROUP_SHOWS_VIDEOS)
        self.assertIs(self.reload()["streams"], False)

    def test_streams_asks_for_the_streams(self):
        self.db.set_group_shows(self.group, GROUP_SHOWS_STREAMS)
        self.assertIs(self.reload()["streams"], True)

    def test_the_feed_itself_is_never_filtered(self):
        # All is every channel followed, and a stream of a channel you follow
        # belongs in what you follow.
        self.db.set_group_shows(self.group, GROUP_SHOWS_STREAMS)
        self.bridge._view_kind = "all"
        self.bridge._view_id = -1
        self.assertIsNone(self.reload()["streams"])

    def test_a_box_is_never_filtered(self):
        self.db.set_group_shows(self.group, GROUP_SHOWS_STREAMS)
        self.bridge._view_kind = "box"
        self.assertIsNone(self.reload()["streams"])

    def test_pressing_one_stores_it_and_says_so(self):
        self.bridge.reload = lambda: None
        self.Bridge.showInGroup(self.bridge, GROUP_SHOWS_STREAMS)
        self.assertEqual(self.db.group_shows(self.group), GROUP_SHOWS_STREAMS)
        self.assertEqual(self.told, 1)

    def test_pressing_the_one_already_showing_says_nothing(self):
        self.bridge.reload = lambda: None
        self.Bridge.showInGroup(self.bridge, GROUP_SHOWS_ALL)
        self.assertEqual(self.told, 0)

    def test_nothing_can_be_pressed_outside_a_group(self):
        self.bridge.reload = lambda: None
        self.bridge._view_kind = "all"
        self.Bridge.showInGroup(self.bridge, GROUP_SHOWS_STREAMS)
        self.assertEqual(self.db.group_shows(self.group), GROUP_SHOWS_ALL)
        self.assertEqual(self.told, 0)

    def test_a_word_that_is_not_one_of_the_three_does_nothing(self):
        self.bridge.reload = lambda: None
        self.Bridge.showInGroup(self.bridge, "sideways")
        self.assertEqual(self.db.group_shows(self.group), GROUP_SHOWS_ALL)
        self.assertEqual(self.told, 0)

    def test_the_buttons_read_the_group_showing(self):
        self.db.set_group_shows(self.group, GROUP_SHOWS_VIDEOS)
        self.assertEqual(self.Bridge._get_group_shows(self.bridge), GROUP_SHOWS_VIDEOS)
        self.bridge._view_kind = "all"
        self.assertEqual(self.Bridge._get_group_shows(self.bridge), GROUP_SHOWS_ALL)

    def test_a_filtered_group_that_is_empty_says_which_half_is_empty(self):
        self.db.set_group_shows(self.group, GROUP_SHOWS_STREAMS)
        hint = self.Bridge._get_empty_hint(self.bridge)
        self.assertIn("No streams in this group", hint)
        self.assertIn("Press All above", hint)

    def test_an_empty_group_still_says_to_put_channels_in_it(self):
        empty = self.db.create_group("Empty")
        self.bridge._view_id = empty
        self.db.set_group_shows(empty, GROUP_SHOWS_VIDEOS)
        self.assertIn("no channels in it yet", self.Bridge._get_empty_hint(self.bridge))


if __name__ == "__main__":
    unittest.main()
