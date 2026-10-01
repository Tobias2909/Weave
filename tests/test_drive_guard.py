"""The driver refuses to walk or seed anything but a scratch collection.

On 2026-10-01 a probe imported the driver and called boot() and seed()
directly, past the check in main(), and its sample playlists replaced every
real one. Nothing here opens a database: the guard is checked on its own, and
seed() and boot() are read to make sure it is the first thing either does.
"""

import ast
import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tools" / "drive.py"


def load_driver():
    spec = importlib.util.spec_from_file_location("weave_drive_guard", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheGuard(unittest.TestCase):
    def setUp(self):
        self.drive = load_driver()

    def scratch(self, **override):
        env = {"XDG_STATE_HOME": "/tmp/w/s", "XDG_CONFIG_HOME": "/tmp/w/c",
               "XDG_CACHE_HOME": "/tmp/w/k"}
        env.update(override)
        return {key: value for key, value in env.items() if value is not None}

    def test_scratch_homes_pass(self):
        with mock.patch.dict(os.environ, self.scratch(), clear=False):
            self.assertEqual(self.drive.scratch_missing(), [])

    def test_an_unset_home_is_missing(self):
        env = dict(os.environ)
        env.update(self.scratch())
        env.pop("XDG_STATE_HOME")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.drive.scratch_missing(), ["XDG_STATE_HOME"])
            with self.assertRaises(SystemExit):
                self.drive.refuse_the_real_collection()

    def test_the_real_place_named_outright_is_missing_too(self):
        real = str(Path.home() / ".local" / "state")
        with mock.patch.dict(os.environ, self.scratch(XDG_STATE_HOME=real), clear=False):
            self.assertEqual(self.drive.scratch_missing(), ["XDG_STATE_HOME"])


class ItComesFirst(unittest.TestCase):
    def first_call(self, name):
        tree = ast.parse(DRIVER.read_text())
        found = next(node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == name)
        body = [node for node in found.body
                if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        call = body[0].value
        return call.func.id if isinstance(call, ast.Call) else None

    def test_before_seed_opens_anything(self):
        self.assertEqual(self.first_call("seed"), "refuse_the_real_collection")

    def test_before_boot_starts_anything(self):
        self.assertEqual(self.first_call("boot"), "refuse_the_real_collection")


if __name__ == "__main__":
    unittest.main()
