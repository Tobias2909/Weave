"""How tall Auto takes the screen the window is on to be.

A 1080 line screen scaled to 125 % fetched 1440p, because Wayland gives a
screen's scale in whole numbers and the screen's own ratio was counted. The
window is told the fraction. The screens here are told the way a nested KWin
told them when it was measured.

A window needs a QGuiApplication, and the rest of the suite holds a
QCoreApplication, so this is asked in its own process, the way the window test
and the image cache test do it.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ASK = """
import json, os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication, QWindow
app = QGuiApplication([])
from weave.video import ScreenWatch

def screen(lines, ratio, name):
    return SimpleNamespace(size=lambda: SimpleNamespace(height=lambda: lines),
                           devicePixelRatio=lambda: ratio, name=lambda: name)

class Window(QWindow):
    on = screen(864, 2.0, "laptop at 125 %")
    ratio = 1.25
    def screen(self):
        return self.on
    def devicePixelRatio(self):
        return self.ratio

class Player:
    def __init__(self):
        self.heard = []
    def setScreenHeight(self, pixels):
        self.heard.append(pixels)

window, player = Window(), Player()
watch = ScreenWatch(window, player)
answers = {"laptop": player.heard[-1]}

# Moved to a 1080 line screen at 100 %. The move is told first, while the
# window still says 1.5, and the ratio after it.
window.on, window.ratio = screen(720, 2.0, "laptop at 150 %"), 1.5
QCoreApplication.sendEvent(window, QEvent(QEvent.Type.DevicePixelRatioChange))
answers["laptop_at_150"] = player.heard[-1]
window.on = screen(1080, 1.0, "monitor")
window.screenChanged.emit(app.primaryScreen())
answers["moved_before_the_ratio"] = player.heard[-1]
window.ratio = 1.0
QCoreApplication.sendEvent(window, QEvent(QEvent.Type.DevicePixelRatioChange))
answers["moved"] = player.heard[-1]
print(json.dumps(answers))
"""


class TheScreenItIsOn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run([sys.executable, "-c", ASK],
                              capture_output=True, text=True, timeout=60, cwd=ROOT)
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise AssertionError(f"no answer: {done.stdout}\n{done.stderr}")
        cls.said = json.loads(lines[-1])

    def test_a_screen_scaled_by_a_fraction_counts_its_real_lines(self):
        # 864 lines at the screen's 2.0 would be 1728, and a 1440p ceiling.
        self.assertEqual(self.said["laptop"], 1080)
        self.assertEqual(self.said["laptop_at_150"], 1080)

    def test_a_new_ratio_is_measured_when_it_comes(self):
        # Between the two, the window says the old ratio over the new screen.
        self.assertEqual(self.said["moved_before_the_ratio"], 1620)
        self.assertEqual(self.said["moved"], 1080)


if __name__ == "__main__":
    unittest.main()
