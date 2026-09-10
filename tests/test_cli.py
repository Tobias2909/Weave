"""The command line, run as a person runs it.

What is checked here is what a subprocess can prove and a unit test cannot: a
database that is not one is a sentence with the path in it and an exit code,
not a traceback. Every subcommand opens the database, so the guard sits in
one place and this runs one cheap subcommand through it.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(home: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        env[name] = os.path.join(home, name.lower())
        os.makedirs(env[name], exist_ok=True)
    return subprocess.run([sys.executable, "-m", "weave", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


class TheCommandLine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="weave-cli-")
        self.home = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_music_playback_check_is_reachable(self):
        # It plays a real track, so the test only proves the subcommand is
        # wired and takes its arguments.
        done = _run(self.home, "music", "play", "--help")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--seconds", done.stdout)

    def test_a_fresh_home_lists_no_channels(self):
        done = _run(self.home, "channels")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("no channels yet", done.stdout)

    def test_a_file_that_is_not_a_database_is_a_sentence_not_a_traceback(self):
        state = Path(self.home) / "xdg_state_home" / "weave"
        state.mkdir(parents=True)
        (state / "weave.db").write_bytes(b"this is not a database at all, " * 64)
        done = _run(self.home, "channels")
        self.assertEqual(done.returncode, 1)
        self.assertNotIn("Traceback", done.stderr)
        self.assertIn("could not be opened", done.stderr)
        self.assertIn(str(state / "weave.db"), done.stderr)


if __name__ == "__main__":
    unittest.main()
