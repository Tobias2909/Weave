"""Broadcasts played in the window: a Twitch channel through streamlink or
yt-dlp, and what the page says about a stream that is on air.

What streamlink prints was MEASURED against live channels before this was
written; the answers here are that shape with the addresses made up.
"""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication

from tests.test_video_player import FakeEngine, _Base, video
from weave import audio
from weave import video as video_module
from weave.config import Config
from weave.sources import streamlink
from weave.video import OFF_AIR, Found, NoAddress, resolve_twitch

_app = QCoreApplication.instance() or QCoreApplication([])


def answer(*names, title="Playing a game", author="Alpha", category="Chess"):
    streams = {name: {"type": "hls", "url": f"https://playlist.example/{name}.m3u8",
                      "master": "https://usher.example/alpha.m3u8", "headers": {}}
               for name in names}
    return json.dumps({"plugin": "twitch", "streams": streams,
                       "metadata": {"id": "1", "author": author, "category": category,
                                    "title": title}})


LIST = answer("audio_only", "160p30", "360p30", "480p30", "720p60", "1080p60", "worst",
              "best")


class WhatStreamlinkSays(unittest.TestCase):
    def test_every_picture_quality_tallest_first(self):
        found = streamlink.parse(LIST)
        self.assertEqual([one.name for one in found.offered],
                         ["1080p60", "720p60", "480p30", "360p30", "160p30"])
        self.assertEqual(found.heights, (1080, 720, 480, 360, 160))
        self.assertEqual((found.title, found.author, found.category),
                         ("Playing a game", "Alpha", "Chess"))

    def test_the_tallest_that_fits_under_the_ceiling(self):
        found = streamlink.parse(LIST)
        self.assertEqual(streamlink.pick(found, 1440).name, "1080p60")
        self.assertEqual(streamlink.pick(found, 1080).name, "1080p60")
        self.assertEqual(streamlink.pick(found, 900).name, "720p60")
        self.assertEqual(streamlink.pick(found, 100).name, "160p30",
                         "nothing fits, so the smallest there is")

    def test_an_odd_height_is_a_height_like_any_other(self):
        found = streamlink.parse(answer("720p60", "936p60"))
        self.assertEqual(streamlink.pick(found, 1080).name, "936p60")

    def test_a_channel_not_on_air_is_an_answer(self):
        said = json.dumps({"error": "No playable streams found on this URL: https://x"})
        with self.assertRaises(streamlink.Offline):
            streamlink.parse(said)
        with self.assertRaises(streamlink.Offline):
            streamlink.parse(answer("audio_only"))

    def test_anything_else_is_a_failure(self):
        with self.assertRaises(streamlink.StreamlinkError):
            streamlink.parse("Traceback (most recent call last):")
        with self.assertRaises(streamlink.StreamlinkError):
            streamlink.parse(json.dumps({"error": "Unable to open URL"}))

    def test_it_asks_for_every_codec_yt_dlp_does(self):
        line = streamlink.command("alpha")
        self.assertIn("--twitch-supported-codecs", line)
        self.assertEqual(line[line.index("--twitch-supported-codecs") + 1], "av1,h265,h264")
        self.assertEqual(line[-1], "https://www.twitch.tv/alpha")
        self.assertNotIn("--config", line, "nothing of ours, so its own config applies")


class TheLogin(unittest.TestCase):
    def test_the_login_goes_in_a_file_only_this_user_reads_and_never_on_the_line(self):
        seen = {}

        def run(command, cancel=None, timeout=0):
            config = [command[i + 1] for i, part in enumerate(command)
                      if part == "--config"][-1]
            seen["command"] = command
            seen["mode"] = stat.S_IMODE(os.stat(config).st_mode)
            seen["text"] = Path(config).read_text()
            seen["path"] = config
            return mock.Mock(stdout=LIST, stderr="", returncode=0)

        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home}), \
                mock.patch.object(streamlink, "run_process", run):
            streamlink.ask("alpha", token="secret-token")
        self.assertEqual(seen["mode"], 0o600)
        self.assertIn("Authorization=OAuth secret-token", seen["text"])
        self.assertFalse(any("secret-token" in part for part in seen["command"]))
        self.assertFalse(os.path.exists(seen["path"]), "gone once streamlink has read it")

    def test_its_own_config_is_read_first_and_ours_on_top(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home}):
            own = Path(home) / "streamlink" / "config"
            own.parent.mkdir()
            own.write_text("twitch-low-latency\n")
            line = streamlink.command("alpha", "/run/ours.conf")
        configs = [line[i + 1] for i, part in enumerate(line) if part == "--config"]
        self.assertEqual(configs, [str(own), "/run/ours.conf"])

    def test_no_login_no_file(self):
        seen = {}

        def run(command, cancel=None, timeout=0):
            seen["command"] = command
            return mock.Mock(stdout=LIST, stderr="", returncode=0)

        with mock.patch.object(streamlink, "run_process", run):
            streamlink.ask("alpha")
        self.assertNotIn("--config", seen["command"])


class ResolvingAChannel(unittest.TestCase):
    cfg = Config(raw={})

    def test_streamlink_where_there_is_one(self):
        with mock.patch.object(streamlink, "available", return_value=True), \
                mock.patch.object(streamlink, "ask", return_value=streamlink.parse(LIST)), \
                mock.patch.object(video_module, "twitch_token", return_value=""), \
                mock.patch.object(video_module, "resolve_watch") as ytdlp:
            found = resolve_twitch(self.cfg, "alpha", "https://www.twitch.tv/alpha", 720)
        ytdlp.assert_not_called()
        self.assertEqual(found.picture, "https://playlist.example/720p60.m3u8")
        self.assertEqual(found.sound, "")
        self.assertEqual(found.extras["heights"], [1080, 720, 480, 360, 160])
        self.assertEqual(found.extras["height"], 720)
        self.assertEqual(found.facts["category"], "Chess")

    def test_yt_dlp_without_streamlink(self):
        fetched = Found("https://picture.example/a", "", (), {}, {"height": 720})
        with mock.patch.object(streamlink, "available", return_value=False), \
                mock.patch.object(video_module, "resolve_watch",
                                  return_value=fetched) as ytdlp:
            found = resolve_twitch(self.cfg, "alpha", "https://www.twitch.tv/alpha", 720)
        self.assertEqual(ytdlp.call_args.args[3], True, "asked as a broadcast")
        self.assertEqual(found.picture, "https://picture.example/a")

    def test_yt_dlp_when_streamlink_cannot(self):
        fetched = Found("https://picture.example/a", "", (), {}, {})
        with mock.patch.object(streamlink, "available", return_value=True), \
                mock.patch.object(streamlink, "ask",
                                  side_effect=streamlink.StreamlinkError("plugin broke")), \
                mock.patch.object(video_module, "twitch_token", return_value=""), \
                mock.patch.object(video_module, "resolve_watch", return_value=fetched):
            found = resolve_twitch(self.cfg, "alpha", "https://www.twitch.tv/alpha", 720)
        self.assertEqual(found.picture, "https://picture.example/a")

    def test_not_on_air_is_said_and_yt_dlp_is_not_asked_as_well(self):
        with mock.patch.object(streamlink, "available", return_value=True), \
                mock.patch.object(streamlink, "ask", side_effect=streamlink.Offline("x")), \
                mock.patch.object(video_module, "twitch_token", return_value=""), \
                mock.patch.object(video_module, "resolve_watch") as ytdlp, \
                self.assertRaises(NoAddress) as caught:
            resolve_twitch(self.cfg, "alpha", "https://www.twitch.tv/alpha", 720)
        ytdlp.assert_not_called()
        self.assertEqual(str(caught.exception), OFF_AIR)


class ABroadcastInThePlayer(_Base):
    def test_a_twitch_channel_is_found_by_its_login(self):
        made = []

        class Finder:
            def __init__(self, cfg, key, url, height, live, parent=None, login=""):
                made.append((key, live, login))
                self.found = self.failed = self.gone = self.finished = mock.Mock()

            def start(self):
                pass

            def cancel(self):
                pass

        player = video_module.VideoPlayer(Config(raw={}), self.db, engine=FakeEngine())
        with mock.patch.object(video_module, "_Finder", Finder):
            player.play_now({"key": "twitch:alpha", "title": "Alpha", "live": True,
                             "login": "alpha", "url": "https://www.twitch.tv/alpha"})
        self.assertEqual(made, [("twitch:alpha", True, "alpha")])

    def test_a_broadcast_that_ran_out_is_asked_for_again_rather_than_rewound(self):
        self.player.play_now(video("a", live=True))
        self.engine.eofChanged.emit(True)
        self.assertTrue(self.player.ended)
        before = len(self.finding)
        self.player.replay()
        self.assertEqual(len(self.finding), before + 1)
        self.assertFalse(self.engine.only("seek"), "nothing to go back to")


class WhatABroadcastSays(unittest.TestCase):
    def test_watching_and_on_air_since_come_with_the_resolve(self):
        found = audio.parse_facts(json.dumps({"concurrent_view_count": 5739,
                                              "release_timestamp": 1791140000}))
        self.assertEqual(found["watching"], 5739)
        self.assertEqual(found["aired_at"], 1791140000)

    def test_the_page_is_given_both(self):
        from weave.ui.bridge import Bridge

        bridge = Bridge.__new__(Bridge)
        detail = {"key": "yt:a"}
        Bridge._with_air(bridge, detail, {"watching": 5739, "aired_at": 1791140000}, "yt:a")
        self.assertEqual(detail["watchingText"], "5.7K")
        self.assertEqual(detail["watchingExact"], "5,739")
        self.assertEqual(detail["liveSince"], 1791140000)
        self.assertNotIn("gameText", detail)

        detail = {"watchingText": "12K", "liveSince": 5}
        Bridge._with_air(bridge, detail, {"watching": 1, "aired_at": 9, "category": "Chess"},
                         "twitch:alpha")
        self.assertEqual((detail["watchingText"], detail["liveSince"]), ("12K", 5),
                         "the live bar's count is the newer one")
        self.assertEqual(detail["gameText"], "Chess")


if __name__ == "__main__":
    unittest.main()
