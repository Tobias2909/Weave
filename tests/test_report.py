"""The report somebody sends when nothing is arriving.

It exists to be attached to a message, which is the whole reason it must not
carry the collection: a channel list is a personal thing and a video title says
what somebody watched. What it carries is the checks, the versions, the
settings without their secrets, counts, and every request of the last day.
"""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from weave import config, report
from weave.db import Database, VideoRow

CHANNEL = "yt:UCaaaaaaaaaaaaaaaaaaaaaa"


class TheBundle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = Database(self.root / "t.db")
        self.db.add_channel(CHANNEL, "youtube", "UCaaaaaaaaaaaaaaaaaaaaaa",
                            "A channel nobody should read about")
        self.db.upsert_videos([VideoRow("youtube", "aaaaaaaaaaa", CHANNEL,
                                        "A title nobody should read either",
                                        published_at=1_700_000_000, duration_s=60)])
        self.cfg = config.load(self.root / "config.toml")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def written(self, **over) -> dict[str, str]:
        path = report.write(self.db, self.cfg, self.root / "r.zip", network=False, **over)
        with zipfile.ZipFile(path) as bundle:
            return {name: bundle.read(name).decode() for name in bundle.namelist()}

    def test_it_holds_the_checks_and_the_numbers(self):
        parts = self.written()
        self.assertIn("checks.txt", parts)
        self.assertIn("channels 1", parts["numbers.txt"])

    def test_it_names_no_channel_and_no_video(self):
        whole = "\n".join(self.written().values())
        self.assertNotIn("A channel nobody should read about", whole)
        self.assertNotIn("A title nobody should read either", whole)

    def test_a_secret_is_left_out_rather_than_shortened(self):
        (self.root / "config.toml").write_text(
            '[twitch]\nclient_id = "abcdefghijklmnop"\n')
        self.cfg = config.load(self.root / "config.toml")
        whole = "\n".join(self.written().values())
        self.assertNotIn("abcdefghijklmnop", whole)
        self.assertIn("<left out>", whole)

    def test_the_settings_that_are_not_secret_are_there(self):
        (self.root / "config.toml").write_text('[poll]\nchannels_per_tick = 3\n')
        self.cfg = config.load(self.root / "config.toml")
        self.assertIn("channels_per_tick = 3", self.written()["settings.txt"])

    def test_what_a_failing_channel_said_is_grouped(self):
        self.db.mark_polled(CHANNEL, "HttpError: HTTP 404 for a feed")
        failures = self.written()["failures.txt"]
        self.assertIn("HTTP 404", failures)
        # The id, since whether a feed answers is a question about one, and
        # never the name.
        self.assertIn("UCaaaaaaaaaaaaaaaaaaaaaa", failures)

    def test_the_requests_of_the_last_day_are_there(self):
        self.db.record_requests("feeds", count=3, refused=2)
        rows = self.written()["requests.tsv"]
        self.assertIn("feeds\t3\t2", rows)

    def test_the_problems_the_window_collected_come_along(self):
        self.assertIn("mpv is not installed",
                      self.written(problems=["mpv is not installed"])["problems.txt"])

    def test_it_says_where_it_went(self):
        path = report.write(self.db, self.cfg, self.root / "named.zip", network=False)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "named.zip")

    def test_and_names_itself_by_the_hour_when_nobody_says(self):
        self.assertTrue(report.default_path().name.startswith("weave-report-"))
        self.assertTrue(report.default_path().name.endswith(".zip"))


if __name__ == "__main__":
    unittest.main()
