"""A stream in a search, in the suggestions or in the history.

The feed has badged streams and announced premieres since they were built,
because a feed row says which it is. A listing says the same thing and it was
being thrown away, so the same video looked like an ordinary one the moment it
was reached from somewhere else, and an announced premiere could be handed to
a player that has nothing to open yet.
"""

import tempfile
import time
import unittest
from pathlib import Path

from weave.db import Database
from weave.ui.feed_model import FeedModel


def listing_row(ext_id="aaaaaaaaaaa", **over):
    row = {"ext_id": ext_id, "title": "A video", "channel_name": "Someone",
           "channel_ext_id": None, "duration_s": None, "thumbnail_url": None,
           "views": None, "published_at": None, "live_status": None,
           "scheduled_at": None}
    row.update(over)
    return row


class StoredWithTheSuggestions(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "weave.db")

    def cards(self, kind):
        return [FeedModel._build(row) for row in self.db.cached(kind)]

    def test_a_stream_that_is_on_is_marked_live(self) -> None:
        self.db.replace_cached(self.db.RECOMMENDED,
                               [listing_row(live_status="is_live")])
        card = self.cards(self.db.RECOMMENDED)[0]
        self.assertTrue(card["isLive"])
        self.assertFalse(card["isUpcoming"])

    def test_an_announced_stream_carries_both_ways_of_saying_when(self) -> None:
        # An hour off, so the badge counts in hours rather than saying it is
        # too far away to phrase.
        soon = int(time.time()) + 3600
        self.db.replace_cached(self.db.RECOMMENDED, [listing_row(
            live_status="is_upcoming", scheduled_at=soon)])
        card = self.cards(self.db.RECOMMENDED)[0]
        self.assertTrue(card["isUpcoming"])
        # The badge counts down, the line under the channel says the hour.
        self.assertTrue(card["scheduledText"].startswith("Starts in"))
        self.assertIn(" at ", card["startsText"])

    def test_an_ordinary_suggestion_is_neither(self) -> None:
        self.db.replace_cached(self.db.RECOMMENDED, [listing_row()])
        card = self.cards(self.db.RECOMMENDED)[0]
        self.assertFalse(card["isLive"] or card["isUpcoming"])

    def test_a_later_page_keeps_it_too(self) -> None:
        self.db.replace_cached(self.db.RECOMMENDED, [listing_row()])
        self.db.append_cached(self.db.RECOMMENDED,
                              [listing_row("bbbbbbbbbbb", live_status="is_live")])
        self.assertTrue(self.cards(self.db.RECOMMENDED)[1]["isLive"])

    def test_the_history_side_carries_it_as_well(self) -> None:
        self.db.replace_cached(self.db.HISTORY, [listing_row(live_status="is_live")])
        self.assertTrue(self.cards(self.db.HISTORY)[0]["isLive"])


class ResultsThatAreNotStored(unittest.TestCase):
    """A search result lives in memory and is joined to what is known here."""

    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "weave.db")

    def test_a_live_result_reaches_the_card(self) -> None:
        row = self.db.decorate([listing_row(live_status="is_live")])[0]
        self.assertTrue(FeedModel._build(row)["isLive"])

    def test_an_announced_result_reaches_the_card(self) -> None:
        row = self.db.decorate([listing_row(live_status="is_upcoming",
                                            scheduled_at=int(time.time()) + 3600)])[0]
        card = FeedModel._build(row)
        self.assertTrue(card["isUpcoming"])
        self.assertIn(" at ", card["startsText"])
