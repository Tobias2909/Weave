"""Carrying a row to an edge of its list, and when that scrolls the list.

The first and the last row shown lie inside an edge's reach, and taking one of
them used to set the list racing at once, which looked like dragging the list
rather than the row. The rules are read off the real component.

Making a QtQuick item needs a QGuiApplication, and the rest of the suite holds
a QCoreApplication, so the component is asked in its own process, the way the
window test and the image cache test do it.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ASK = """
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Property, QObject, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
app = QGuiApplication([])

class StubApp(QObject):
    @Slot(str, "QVariantMap")
    def traceMark(self, event, fields):
        pass

class StubTheme(QObject):
    def _colors(self):
        return {"accent": "#4a90d9", "text": "#ffffff", "surfaceRaised": "#222222"}
    colors = Property("QVariantMap", _colors, constant=True)

engine = QQmlEngine()
stub_app, stub_theme = StubApp(), StubTheme()
engine.rootContext().setContextProperty("App", stub_app)
engine.rootContext().setContextProperty("Theme", stub_theme)
component = QQmlComponent(engine, QUrl.fromLocalFile(sys.argv[1]))
order = component.create()
if order is None:
    print(json.dumps({"error": component.errorString()}))
    raise SystemExit(0)
order.setProperty("height", 370)
order.setProperty("width", 500)

def call(text):
    found, _undefined = QQmlExpression(engine.contextForObject(order), order, text).evaluate()
    return found

def taken_at(y):
    order.setProperty("startY", y)
    order.setProperty("scrollArmed", call(f"edgeDepth({y})") == 0)

answers = {"depth": [call(f"edgeDepth({y})") for y in (15, 185, 355)]}
taken_at(345)
answers["bottom_row_held"] = call("armedAt(345)")
answers["bottom_row_moved_away"] = call("armedAt(335)")
answers["bottom_row_pushed"] = call("armedAt(357)")
answers["bottom_row_left_edge"] = call("armedAt(200)")
taken_at(15)
answers["top_row_pushed"] = call("armedAt(3)")
taken_at(185)
answers["middle_row_to_edge"] = call("armedAt(355)")
answers["steps"] = {
    "start": call("edgeStep(40, 0)"), "full": call("edgeStep(40, 10000)"),
    "beyond": call("edgeStep(400, 10000)"), "gentle": call("edgeStep(2, 10000)"),
    "up": call("edgeStep(-40, 10000)"), "none": call("edgeStep(0, 10000)")}
print(json.dumps(answers))
"""


class TheEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(
            [sys.executable, "-c", ASK, str(ROOT / "weave" / "qml" / "DragOrder.qml")],
            capture_output=True, text=True, timeout=60, cwd=ROOT)
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        if not lines:
            raise AssertionError(f"no answer: {done.stdout}\n{done.stderr}")
        cls.said = json.loads(lines[-1])
        if "error" in cls.said:
            raise AssertionError(cls.said["error"])

    def test_the_reach_of_each_edge(self):
        top, middle, bottom = self.said["depth"]
        self.assertLess(top, 0)
        self.assertEqual(middle, 0)
        self.assertGreater(bottom, 0)

    def test_a_row_taken_inside_an_edge_does_not_scroll_at_once(self):
        self.assertFalse(self.said["bottom_row_held"])
        self.assertFalse(self.said["bottom_row_moved_away"], "moving away, still inside the edge")

    def test_pushed_further_into_the_edge_it_does(self):
        self.assertTrue(self.said["bottom_row_pushed"])
        self.assertTrue(self.said["top_row_pushed"])

    def test_and_once_the_pointer_has_left_the_edge(self):
        self.assertTrue(self.said["bottom_row_left_edge"])

    def test_a_row_taken_between_the_edges_scrolls_as_soon_as_it_reaches_one(self):
        self.assertTrue(self.said["middle_row_to_edge"])

    def test_it_builds_up_and_never_races(self):
        steps = self.said["steps"]
        self.assertLessEqual(abs(steps["start"]), 1)
        self.assertEqual(steps["full"], 20)
        self.assertEqual(steps["beyond"], 20, "past the edge is no faster than at it")
        self.assertLess(steps["gentle"], 4)
        self.assertLess(steps["up"], 0)
        self.assertEqual(steps["none"], 0)


if __name__ == "__main__":
    unittest.main()
