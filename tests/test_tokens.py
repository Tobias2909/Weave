"""The stored Twitch login."""

import os
import stat
import tempfile
import unittest
from pathlib import Path

from weave import tokens
from weave.sources.twitch import Tokens


class Storage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "state" / "twitch.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip(self):
        tokens.save(Tokens("access", "refresh", 1000), self.path)
        restored = tokens.load(self.path)
        self.assertEqual((restored.access_token, restored.refresh_token), ("access", "refresh"))

    def test_written_owner_only(self):
        # These are the only secrets the application holds.
        tokens.save(Tokens("access", "refresh"), self.path)
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)

    def test_missing_file_is_simply_not_logged_in(self):
        self.assertIsNone(tokens.load(self.path))

    def test_a_damaged_file_is_not_a_crash(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ this is not json")
        self.assertIsNone(tokens.load(self.path))

    def test_a_file_missing_half_the_login_is_not_a_login(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"access_token": "a"}')
        self.assertIsNone(tokens.load(self.path))

    def test_clearing(self):
        tokens.save(Tokens("access", "refresh"), self.path)
        self.assertTrue(tokens.clear(self.path))
        self.assertIsNone(tokens.load(self.path))
        self.assertFalse(tokens.clear(self.path))

    def test_saving_twice_replaces(self):
        tokens.save(Tokens("first", "one"), self.path)
        tokens.save(Tokens("second", "two"), self.path)
        self.assertEqual(tokens.load(self.path).access_token, "second")


if __name__ == "__main__":
    unittest.main()
