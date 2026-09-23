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


if __name__ == "__main__":
    unittest.main()
