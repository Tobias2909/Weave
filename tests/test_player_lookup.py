"""Which mpv a video is handed to.

The single instance wrapper lives in ~/.local/bin. A shell has read a profile
and has that on PATH; a desktop session has the bare system PATH and has not,
so started from the start menu Weave found no wrapper and fell back to plain
mpv without a word. Every video then opened a window of its own instead of
being handed to the one already playing, and since the fallback carries no IPC
socket, nothing was ever reported as watched either.
"""

import os
import tempfile
import unittest
from pathlib import Path

from weave import paths
from weave.config import Config
from weave.player import mpv


class FindingTheWrapper(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(raw={})
        self._path = os.environ.get("PATH", "")
        self._bin = os.environ.get("XDG_BIN_HOME")
        self.addCleanup(self._restore)

    def _restore(self):
        os.environ["PATH"] = self._path
        if self._bin is None:
            os.environ.pop("XDG_BIN_HOME", None)
        else:
            os.environ["XDG_BIN_HOME"] = self._bin

    def make_wrapper(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        wrapper = directory / mpv.WRAPPER_NAME
        wrapper.write_text("#!/bin/sh\nexit 0\n")
        wrapper.chmod(0o755)
        return wrapper

    def test_it_is_found_on_path(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wrapper = self.make_wrapper(Path(tmp.name))
        os.environ["PATH"] = tmp.name
        self.assertEqual(mpv.find_wrapper(), str(wrapper))

    def test_it_is_found_in_the_usual_place_when_path_says_nothing(self):
        # The case that was broken. PATH here is what a desktop entry gets.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wrapper = self.make_wrapper(Path(tmp.name))
        os.environ["PATH"] = "/usr/bin:/bin"
        os.environ["XDG_BIN_HOME"] = tmp.name
        self.assertEqual(paths.bin_home(), Path(tmp.name))
        self.assertEqual(mpv.find_wrapper(), str(wrapper))
        self.assertEqual(mpv.resolve_command(self.cfg), [str(wrapper)])

    def test_a_directory_of_that_name_is_not_a_player(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / mpv.WRAPPER_NAME).mkdir()
        os.environ["PATH"] = "/usr/bin:/bin"
        os.environ["XDG_BIN_HOME"] = tmp.name
        self.assertIsNone(mpv.find_wrapper())

    def test_without_it_plain_mpv_still_answers(self):
        # What a machine that has never seen the mpv config repository gets.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["PATH"] = "/usr/bin:/bin"
        os.environ["XDG_BIN_HOME"] = tmp.name
        command = mpv.resolve_command(self.cfg)
        self.assertEqual(Path(command[0]).name, "mpv")

    def test_a_configured_player_still_wins(self):
        cfg = Config(raw={"player": {"command": "/usr/bin/mpv --no-config"}})
        self.assertEqual(mpv.resolve_command(cfg), ["/usr/bin/mpv", "--no-config"])


if __name__ == "__main__":
    unittest.main()
