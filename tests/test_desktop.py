"""The menu entry and the icons that go with it."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weave import desktop


class Shipped(unittest.TestCase):
    def test_the_drawing_and_every_size_are_in_the_package(self):
        self.assertTrue((desktop.SHARE_DIR / "weave.svg").exists())
        for size in desktop.PNG_SIZES:
            picture = desktop.SHARE_DIR / f"weave-{size}.png"
            self.assertTrue(picture.exists(), f"missing weave-{size}.png")
            self.assertGreater(picture.stat().st_size, 0)

    def test_the_entry_names_the_icon_by_name_and_not_by_path(self):
        text = desktop.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("Icon=weave\n", text)
        self.assertIn("StartupWMClass=Weave", text)

    def test_a_clone_gets_an_entry_that_runs_the_module_from_the_clone(self):
        text = desktop.entry_text("/usr/bin/python -m weave", "/somewhere/weave")
        self.assertIn("Exec=/usr/bin/python -m weave\n", text)
        self.assertIn("Path=/somewhere/weave\n", text)

    def test_an_installed_copy_needs_no_working_directory(self):
        text = desktop.entry_text("/opt/venv/bin/python -m weave", None)
        self.assertIn("Exec=/opt/venv/bin/python -m weave\n", text)
        self.assertNotIn("Path=", text)

    def test_the_entry_never_trusts_a_bare_weave_command(self):
        """TeX Live owns /usr/bin/weave, so the name on the path is not ours."""
        exec_line, _ = desktop.launcher()
        self.assertIn("-m weave", exec_line)
        self.assertNotEqual(exec_line.strip(), "weave")

    def test_a_clone_is_launched_from_the_clone(self):
        exec_line, work_dir = desktop.launcher()
        root = desktop.SHARE_DIR.parent.parent
        if not (root / "pyproject.toml").is_file():
            self.skipTest("not running from a clone")
        self.assertEqual(work_dir, str(root))


class TheCommandName(unittest.TestCase):
    """TeX Live owns a program called weave, so the name is not ours alone."""

    def test_the_package_offers_a_name_that_cannot_collide(self):
        import tomllib

        root = desktop.SHARE_DIR.parent.parent
        if not (root / "pyproject.toml").is_file():
            self.skipTest("not running from a clone")
        scripts = tomllib.loads((root / "pyproject.toml").read_text())["project"]["scripts"]
        self.assertEqual(scripts["weave"], "weave.__main__:main")
        self.assertEqual(scripts["weave-app"], "weave.__main__:main")


class Installing(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.share = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def test_install_writes_the_entry_and_one_picture_per_size(self):
        written = desktop.install(self.share)
        self.assertEqual(set(written), set(desktop.installed(self.share)))
        entry = self.share / "applications" / "weave.desktop"
        self.assertIn("Icon=weave", entry.read_text(encoding="utf-8"))
        for size in desktop.PNG_SIZES:
            target = self.share / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "weave.png"
            self.assertTrue(target.exists())
        self.assertTrue((self.share / "icons" / "hicolor" / "scalable" / "apps" / "weave.svg").exists())

    def test_installing_twice_is_harmless(self):
        desktop.install(self.share)
        again = desktop.install(self.share)
        self.assertEqual(set(again), set(desktop.installed(self.share)))

    def test_remove_takes_back_everything_it_wrote(self):
        desktop.install(self.share)
        gone = desktop.remove(self.share)
        self.assertEqual(set(gone), set(desktop.installed(self.share)))
        for path in desktop.installed(self.share):
            self.assertFalse(path.exists())

    def test_remove_reports_nothing_when_there_was_nothing(self):
        self.assertEqual(desktop.remove(self.share), [])


if __name__ == "__main__":
    unittest.main()
