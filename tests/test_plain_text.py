"""Words from elsewhere are drawn as words.

A Label or a Text left to decide for itself reads anything that looks like
markup as markup. MEASURED with Qt 6.11: a title holding <img src="..."> made
the window fetch that address, which tells whoever wrote the title that the
window is open and from where, and the same words on a button took the whole
process down. Titles, names and stream titles are written by other people, so
every Label and Text says outright what it draws: plain text, or the markup
Weave built itself, which escapes everything it did not make.
"""

import re
import unittest
from pathlib import Path

QML = Path(__file__).resolve().parent.parent / "weave" / "qml"
OPENING = re.compile(r"^\s*(?:[\w.]+\s*:\s*)?(?:Label|Text)\s*\{\s*$")


def _code(line: str) -> str:
    """A line with its strings emptied and its comment gone, so a brace in
    either is not counted."""
    return re.sub(r"//.*$", "", re.sub(r'"(?:[^"\\]|\\.)*"', '""', line))


def undeclared(text: str) -> list[int]:
    """The lines on which a Label or a Text opens without saying its format."""
    lines = text.splitlines()
    missing = []
    for start, line in enumerate(lines):
        if not OPENING.match(line):
            continue
        depth, declared = 0, False
        for at in range(start, len(lines)):
            if at > start and depth == 1 and re.match(r"\s*textFormat\s*:", lines[at]):
                declared = True
            code = _code(lines[at])
            depth += code.count("{") - code.count("}")
            if depth == 0:
                break
        if not declared:
            missing.append(start + 1)
    return missing


class EveryLabelSaysWhatItDraws(unittest.TestCase):
    def test_every_label_and_text_in_the_window(self):
        found = {path.name: undeclared(path.read_text()) for path in sorted(QML.glob("*.qml"))}
        self.assertTrue(found, "no QML was read")
        self.assertEqual({name: lines for name, lines in found.items() if lines}, {})

    def test_one_that_does_not_is_found(self):
        self.assertEqual(undeclared("Item {\n    Label {\n        text: title\n    }\n}\n"), [2])

    def test_one_inside_another_is_its_own_question(self):
        sample = ("Label {\n    textFormat: Text.PlainText\n"
                  "    contentItem: Text {\n        text: title\n    }\n}\n")
        self.assertEqual(undeclared(sample), [3])

    def test_a_brace_in_its_words_is_not_its_end(self):
        sample = ('Label {\n    text: "}"\n    textFormat: Text.PlainText\n}\n')
        self.assertEqual(undeclared(sample), [])


if __name__ == "__main__":
    unittest.main()
