"""A YouTube address pressed in a description, answered inside the window.

A video comes up on a card beside the press, a channel opens on its videos, a
playlist opens as one, and a time in a link to the very video being played
goes to that time.
"""

import unittest

from PySide6.QtCore import QCoreApplication, QObject

from tests.support import scratch_db
from weave.config import Config
from weave.ids import start_seconds, youtube_link
from weave.ui.bridge import Bridge

_app = QCoreApplication.instance() or QCoreApplication([])

VIDEO = "aaaaaaaaaaa"
CHANNEL = "UC" + "c" * 22


class ReadingTheAddress(unittest.TestCase):
    def test_a_video_and_its_time(self):
        found = youtube_link(f"https://www.youtube.com/watch?v={VIDEO}&t=1m30s")
        self.assertEqual((found.kind, found.video_id, found.start_s), ("video", VIDEO, 90))

    def test_every_shape_a_video_is_written_in(self):
        for url in (f"https://youtu.be/{VIDEO}?t=90", f"https://m.youtube.com/watch?v={VIDEO}",
                    f"https://www.youtube.com/shorts/{VIDEO}",
                    f"https://music.youtube.com/watch?v={VIDEO}"):
            self.assertEqual(youtube_link(url).video_id, VIDEO, url)

    def test_a_playlist_and_a_channel(self):
        self.assertEqual(youtube_link("https://www.youtube.com/playlist?list=PL1").playlist_id,
                         "PL1")
        self.assertEqual(youtube_link("https://www.youtube.com/@someone").channel.value,
                         "@someone")
        self.assertEqual(youtube_link(f"https://www.youtube.com/channel/{CHANNEL}")
                         .channel.kind, "id")

    def test_anything_else_is_not_youtube(self):
        self.assertIsNone(youtube_link("https://example.com/watch?v=aaaaaaaaaaa"))

    def test_times_as_links_write_them(self):
        self.assertEqual([start_seconds(t) for t in ("90", "90s", "1m30s", "1h2m3s", "", "x")],
                         [90, 90, 90, 3723, None, None])


def bridge_for(case, mpv_key=""):
    made = Bridge.__new__(Bridge)
    QObject.__init__(made)
    made._db = scratch_db(case)
    made._cfg = Config(raw={})
    made._mpv_key = mpv_key
    made._audio = None
    made._preview = {}
    made._link_facts = None
    made._link_target = None
    made._seek_on_start = None
    made.launched = []
    made._launch = lambda worker: made.launched.append(worker) or True
    made._set_status = lambda *_a, **_k: None
    made.opened = []
    made.openChannel = made.opened.append
    made._video_for_detail = lambda key: None

    class Player:
        def __init__(self):
            self.sought = []
            self.handed = []

        def seek(self, seconds):
            self.sought.append(seconds)
            return True

        def play(self, url, twitch_login=None, live=False):
            self.handed.append(url)
            return True

    made._player = Player()
    return made


# What the music service answers about the video behind a link.
ANSWER = {"title": "Theirs", "channel": "Somebody", "channel_id": CHANNEL,
          "duration_s": 600, "views": 1234, "published_at": 1256453853, "live": False}


def stored(made):
    """The harness with the real lookup of what is stored, rather than none."""
    del made._video_for_detail
    made._web_results = []
    return made


class WhereAPressGoes(unittest.TestCase):
    def test_an_address_as_the_description_hands_it_over_keeps_its_time(self):
        """The markup escapes the ampersand and the label hands the address
        back escaped, which hid the time behind a parameter called amp;t."""
        made = bridge_for(self)
        Bridge.openLink(made, f"https://www.youtube.com/watch?v={VIDEO}&amp;t=1146s")
        self.assertEqual(Bridge._get_link_preview(made)["startText"], "19:06")

    def test_a_video_comes_up_on_a_card(self):
        from weave.poller import LinkFacts

        made = bridge_for(self)
        self.assertTrue(Bridge._open_youtube_link(
            made, youtube_link(f"https://youtu.be/{VIDEO}?t=90")))
        card = Bridge._get_link_preview(made)
        self.assertEqual(card["key"], f"yt:{VIDEO}")
        self.assertEqual(card["startText"], "1:30")
        self.assertTrue(card["loading"])
        self.assertEqual([type(one) for one in made.launched], [LinkFacts])

    def test_the_answer_fills_the_card_and_places_the_mark(self):
        made = bridge_for(self)
        Bridge._open_youtube_link(made, youtube_link(f"https://youtu.be/{VIDEO}?t=150"))
        Bridge._on_link_facts(made, VIDEO, {"title": "Theirs", "channel": "Somebody",
                                            "channel_id": CHANNEL, "duration_s": 600})
        card = Bridge._get_link_preview(made)
        self.assertEqual((card["title"], card["channel"], card["loading"]),
                         ("Theirs", "Somebody", False))
        self.assertAlmostEqual(card["startAt"], 0.25)
        self.assertEqual(card["channelKey"], f"yt:{CHANNEL}")

    def test_pressed_again_the_card_is_filled_without_asking(self):
        """Closed and pressed again, the card asked the music service all
        over again and showed itself loading every time."""
        made = stored(bridge_for(self))
        link = youtube_link(f"https://youtu.be/{VIDEO}?t=150")
        Bridge._open_youtube_link(made, link)
        Bridge._on_link_facts(made, VIDEO, ANSWER)
        Bridge.closePreview(made)
        made.launched.clear()
        Bridge._open_youtube_link(made, link)
        card = Bridge._get_link_preview(made)
        self.assertEqual((card["title"], card["channel"], card["loading"]),
                         ("Theirs", "Somebody", False))
        self.assertAlmostEqual(card["startAt"], 0.25)
        self.assertEqual(made.launched, [], "the same video was asked about twice")

    def test_an_answer_that_arrives_after_the_card_closed_is_still_kept(self):
        made = stored(bridge_for(self))
        Bridge._open_youtube_link(made, youtube_link(f"https://youtu.be/{VIDEO}"))
        Bridge.closePreview(made)
        Bridge._on_link_facts(made, VIDEO, ANSWER)
        self.assertIsNotNone(made._db.conn.execute(
            "SELECT 1 FROM videos WHERE key=?", (f"yt:{VIDEO}",)).fetchone())

    def test_a_search_of_what_is_stored_finds_it_and_all_does_not(self):
        made = stored(bridge_for(self))
        Bridge._on_link_facts(made, VIDEO, ANSWER)
        found = [row["key"] for row in made._db.feed(query="Theirs", hide_watched=False)]
        self.assertEqual(found, [f"yt:{VIDEO}"])
        self.assertEqual(made._db.feed(hide_watched=False), [],
                         "a video behind a link poured into All")
        channel = made._db.channel(f"yt:{CHANNEL}")
        self.assertEqual((channel["tracked"], channel["in_all"]), (0, 0))

    def test_it_is_stored_with_its_date_views_and_picture(self):
        made = stored(bridge_for(self))
        Bridge._on_link_facts(made, VIDEO, ANSWER)
        row = made._db.conn.execute(
            "SELECT * FROM videos WHERE key=?", (f"yt:{VIDEO}",)).fetchone()
        self.assertEqual((row["duration_s"], row["views"], row["published_at"]),
                         (600, 1234, 1256453853))
        self.assertIn(VIDEO, row["thumbnail_url"])

    def test_a_video_already_stored_only_gains_the_length_it_lacked(self):
        from weave.db import VideoRow

        made = stored(bridge_for(self))
        made._db.add_channel(f"yt:{CHANNEL}", "youtube", CHANNEL, "Followed")
        made._db.upsert_videos([VideoRow("youtube", VIDEO, f"yt:{CHANNEL}", "Ours",
                                         published_at=1_700_000_000)])
        Bridge._on_link_facts(made, VIDEO, ANSWER)
        row = made._db.conn.execute(
            "SELECT * FROM videos WHERE key=?", (f"yt:{VIDEO}",)).fetchone()
        self.assertEqual((row["title"], row["published_at"], row["duration_s"]),
                         ("Ours", 1_700_000_000, 600))

    def test_a_broadcast_is_not_stored(self):
        made = stored(bridge_for(self))
        Bridge._on_link_facts(made, VIDEO, dict(ANSWER, live=True))
        self.assertIsNone(made._db.conn.execute(
            "SELECT 1 FROM videos WHERE key=?", (f"yt:{VIDEO}",)).fetchone())

    def test_a_time_in_a_link_to_the_video_playing_goes_to_that_time(self):
        made = bridge_for(self, mpv_key=f"yt:{VIDEO}")
        Bridge._open_youtube_link(made, youtube_link(f"https://youtu.be/{VIDEO}?t=90"))
        self.assertEqual(made._player.sought, [90])
        self.assertEqual(made._preview, {}, "a card came up for the video already playing")

    def test_a_channel_named_by_its_id_opens_straight_away(self):
        made = bridge_for(self)
        Bridge._open_youtube_link(made, youtube_link(f"https://www.youtube.com/channel/{CHANNEL}"))
        self.assertEqual(made.opened, [f"yt:{CHANNEL}"])

    def test_playing_from_the_card_starts_at_the_links_time(self):
        """The wrapper drops a time written into the address, so the time is
        sent to mpv once it reports the video instead."""
        made = bridge_for(self)
        made._set_starting = lambda *_a, **_k: None
        made._step_aside_for_video = lambda: None
        Bridge._open_youtube_link(made, youtube_link(f"https://youtu.be/{VIDEO}?t=90"))
        Bridge.previewPlay(made)
        self.assertEqual(made._player.handed, [f"https://www.youtube.com/watch?v={VIDEO}"])
        self.assertEqual(made._seek_on_start[:2], (f"yt:{VIDEO}", 90))
        self.assertEqual(made._preview, {}, "the card stayed up after it was acted on")


class WhatTheMusicServiceSays(unittest.TestCase):
    def facts(self, shown):
        from unittest import mock

        from weave.sources import ytmusic

        song = {"videoDetails": {"title": "Theirs", "lengthSeconds": "600"},
                "microformat": {"microformatDataRenderer": shown}}
        with mock.patch.object(ytmusic, "client") as made:
            made.return_value.get_song.return_value = song
            return ytmusic.video_facts(None, VIDEO)

    def test_when_it_was_published_in_the_shape_it_arrives_in(self):
        said = self.facts({"publishDate": "2009-10-24T23:57:33-07:00"})
        self.assertEqual(said["published_at"], 1256453853)

    def test_the_upload_date_stands_in_for_a_missing_one(self):
        said = self.facts({"uploadDate": "2009-10-24T23:57:33-07:00"})
        self.assertEqual(said["published_at"], 1256453853)

    def test_none_given_is_none_rather_than_a_fault(self):
        self.assertIsNone(self.facts({})["published_at"])
        self.assertIsNone(self.facts({"publishDate": "soon"})["published_at"])


if __name__ == "__main__":
    unittest.main()
