"""Everything the window calls on App has to be there to call.

A slot is only reachable from QML because of its decorator, and a decorator
sits on the line above the method it belongs to. An edit that lands between
the two silently moves it onto the wrong method, and the only sign is a
TypeError in the console when somebody presses the thing. This walks the QML
and checks every name it uses actually exists on the bridge.
"""

import re
import unittest
from pathlib import Path

QML_DIR = Path("weave/qml")
CALL = re.compile(r"\bApp\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
READ = re.compile(r"\bApp\.([A-Za-z_][A-Za-z0-9_]*)\b")
AUDIO_CALL = re.compile(r"\bAudio\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
AUDIO_READ = re.compile(r"\bAudio\.([A-Za-z_][A-Za-z0-9_]*)\b")


def names_of(cls):
    meta = cls.staticMetaObject
    methods = {bytes(meta.method(i).name()).decode()
               for i in range(meta.methodCount())}
    # A property's name comes back as a plain string here, unlike a method's.
    properties = {meta.property(i).name() for i in range(meta.propertyCount())}
    return methods, properties


def bridge_names():
    from weave.ui.bridge import Bridge

    return names_of(Bridge)


def audio_names():
    from weave.audio import AudioPlayer

    return names_of(AudioPlayer)


class TheWindowCanReachWhatItCalls(unittest.TestCase):
    def setUp(self) -> None:
        self.methods, self.properties = bridge_names()
        self.files = sorted(QML_DIR.glob("*.qml"))
        self.assertTrue(self.files, "no window files were found")

    def test_every_call_is_a_slot(self) -> None:
        missing = []
        for path in self.files:
            for line_no, line in enumerate(path.read_text().splitlines(), 1):
                for name in CALL.findall(line):
                    if name not in self.methods:
                        missing.append(f"{path.name}:{line_no} App.{name}()")
        self.assertEqual(missing, [], "not reachable from the window")

    def test_every_value_read_is_a_property_or_a_slot(self) -> None:
        missing = []
        for path in self.files:
            for line_no, line in enumerate(path.read_text().splitlines(), 1):
                for name in READ.findall(line):
                    if name not in self.properties and name not in self.methods:
                        missing.append(f"{path.name}:{line_no} App.{name}")
        self.assertEqual(missing, [], "not exposed by the bridge")

    def test_every_call_on_the_player_is_a_slot(self) -> None:
        """The player is reached from the window the same way, so it is worth
        the same check. The queue is edited through it."""
        methods, properties = audio_names()
        missing = []
        for path in self.files:
            for line_no, line in enumerate(path.read_text().splitlines(), 1):
                for name in AUDIO_CALL.findall(line):
                    if name not in methods:
                        missing.append(f"{path.name}:{line_no} Audio.{name}()")
                for name in AUDIO_READ.findall(line):
                    if name not in properties and name not in methods:
                        missing.append(f"{path.name}:{line_no} Audio.{name}")
        self.assertEqual(missing, [], "not reachable from the window")

    def test_the_check_would_notice_a_lost_decorator(self) -> None:
        """A method that is not a slot must not pass as one."""
        from weave.ui.bridge import Bridge

        self.assertIn("playShelfItem", self.methods)
        self.assertNotIn("_mark_favorite", self.methods)
        self.assertTrue(hasattr(Bridge, "_mark_favorite"))


if __name__ == "__main__":
    unittest.main()
