"""Suggestions under a search box.

Asked for after every pause in the typing, so the rule that matters is that
only the newest words are ever asked about and only their answer is shown.
"""

import unittest

from PySide6.QtCore import QCoreApplication, QObject, Signal

_app = QCoreApplication.instance() or QCoreApplication([])


class FakeSuggester(QObject):
    answered = Signal(str, str, "QVariantList")
    finished = Signal()
    made: list = []

    def __init__(self, db, cfg, where, words, signed_in, parent=None):
        super().__init__()
        self.where, self.words, self.signed_in = where, words, signed_in
        self.running = True
        FakeSuggester.made.append(self)

    def isRunning(self):
        return self.running

    def answer(self, found):
        self.answered.emit(self.where, self.words, found)
        self.running = False
        self.finished.emit()


class State:
    def __init__(self):
        self.kept = {}

    def get_state(self, key, default=None):
        return self.kept.get(key, default)

    def set_state(self, key, value):
        self.kept[key] = value


def make_bridge():
    from weave.ui import bridge as module
    from weave.ui.bridge import Bridge

    made = Bridge.__new__(Bridge)
    QObject.__init__(made)
    made._db = State()
    made._cfg = None
    made._status = ""
    made._set_status = lambda *a, **k: None
    made._launch = lambda worker: True
    made._suggester = None
    made._suggest_wanted = None
    made._suggest_asked = None
    made._suggestions = []
    made._suggestions_for = ""
    FakeSuggester.made = []
    real = module.Suggester
    module.Suggester = FakeSuggester
    return made, lambda: setattr(module, "Suggester", real)


class OnlyTheNewestWords(unittest.TestCase):
    def setUp(self):
        self.bridge, undo = make_bridge()
        self.addCleanup(undo)

    def test_words_are_asked_about(self):
        self.bridge.suggest("youtube", "lo")
        self.assertEqual([(w.where, w.words) for w in FakeSuggester.made], [("youtube", "lo")])

    def test_and_the_answer_is_shown_for_that_box(self):
        self.bridge.suggest("youtube", "lo")
        FakeSuggester.made[0].answer(["lofi", "love"])
        self.assertEqual(self.bridge.suggestions, ["lofi", "love"])
        self.assertEqual(self.bridge.suggestionsFor, "youtube")

    def test_words_typed_while_one_is_out_wait_and_only_the_last_is_asked(self):
        self.bridge.suggest("youtube", "l")
        self.bridge.suggest("youtube", "lo")
        self.bridge.suggest("youtube", "lof")
        self.assertEqual(len(FakeSuggester.made), 1)
        FakeSuggester.made[0].answer(["lake"])
        self.assertEqual(self.bridge.suggestions, [], "an answer for old words was shown")
        self.assertEqual([w.words for w in FakeSuggester.made], ["l", "lof"])
        FakeSuggester.made[1].answer(["lofi"])
        self.assertEqual(self.bridge.suggestions, ["lofi"])

    def test_sending_the_words_drops_an_answer_still_on_its_way(self):
        self.bridge.suggest("music", "lo")
        self.bridge.clearSuggestions()
        FakeSuggester.made[0].answer(["lofi"])
        self.assertEqual(self.bridge.suggestions, [])
        self.assertEqual(len(FakeSuggester.made), 1, "cleared words were asked again")

    def test_the_same_words_again_after_clearing_are_asked_again(self):
        self.bridge.suggest("youtube", "lo")
        FakeSuggester.made[0].answer(["lofi"])
        self.bridge.clearSuggestions()
        self.bridge.suggest("youtube", "lo")
        self.assertEqual(len(FakeSuggester.made), 2)

    def test_an_empty_box_asks_nothing_and_clears(self):
        self.bridge.suggest("youtube", "lo")
        FakeSuggester.made[0].answer(["lofi"])
        self.bridge.suggest("youtube", "   ")
        self.assertEqual(len(FakeSuggester.made), 1)
        self.assertEqual(self.bridge.suggestions, [])


class WhereTheyComeFrom(unittest.TestCase):
    def setUp(self):
        self.bridge, undo = make_bridge()
        self.addCleanup(undo)

    def test_anonymous_unless_chosen(self):
        self.assertFalse(self.bridge.suggestFromAccount)
        self.bridge.suggest("youtube", "lo")
        self.assertFalse(FakeSuggester.made[0].signed_in)

    def test_the_account_once_chosen(self):
        self.bridge.setSuggestFromAccount(True)
        self.assertTrue(self.bridge.suggestFromAccount)
        self.bridge.suggest("youtube", "lo")
        self.assertTrue(FakeSuggester.made[0].signed_in)


if __name__ == "__main__":
    unittest.main()
