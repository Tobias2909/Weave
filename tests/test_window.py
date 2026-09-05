"""The real window, booted offscreen and walked.

A clean boot never opens a menu, never commits a popup and never switches a
view, and those are exactly the places a QML binding reaches for an id it
cannot see. The driver in tools/drive.py does all of that against the real
interface with every request and subprocess failing at once, and this test
runs it in its own process against a scratch home, so the suite never touches
the real database and never needs a display.

Its own process, because the rest of the suite holds a QCoreApplication and
a window needs a QGuiApplication, and Qt allows one application per process.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tools" / "drive.py"

# What a QML mistake looks like on stderr. The engine's own warnings arrive
# through the driver; these catch what Qt prints past it.
QML_TROUBLE = ("ReferenceError", "TypeError", "Unable to assign", "is not defined",
               "is not a type", "Cannot assign", "QML Connections")


def _quick_available() -> bool:
    try:
        import PySide6.QtQuick  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_quick_available(), "PySide6 QtQuick is not installed")
class TheWindow(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="weave-window-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_it_boots_and_walks_without_a_qml_warning(self):
        env = dict(os.environ)
        for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            env[name] = os.path.join(self.home, name.lower())
            os.makedirs(env[name], exist_ok=True)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_QUICK_BACKEND"] = "software"
        env.pop("QT_QUICK_CONTROLS_STYLE", None)

        done = subprocess.run([sys.executable, str(DRIVER), "smoke", "--offline", "--json"],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        self.assertTrue(lines, f"no report came back\n{done.stdout}\n{done.stderr}")
        report = json.loads(lines[-1])

        self.assertEqual(report["failed"], [], json.dumps(report["checks"], indent=1))
        self.assertEqual(report["warnings"], [])
        trouble = [line for line in done.stderr.splitlines()
                   if any(mark in line for mark in QML_TROUBLE)]
        self.assertEqual(trouble, [])
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
