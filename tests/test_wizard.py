"""The pages a fresh install is walked through, and when they appear.

The rule for showing them is the whole of it. Nagging somebody who is already
set up is the failure worth guarding against, and so is never showing them to
somebody who is not.
"""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject

from weave.config import Config
from weave.db import Database
from weave.ui.bridge import WIZARD_LAST, Bridge

_app = QCoreApplication.instance() or QCoreApplication([])


class _Silence:
    """A stand in for a signal on a bridge built with __new__, which cannot
    emit one: the real thing raises Signal source has been deleted."""

    def emit(self, *_a):
        pass



class WhenTheyAppear(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._db = self.db
        self.bridge._cfg = Config(raw={})
        self.bridge._wizard_open = False
        self.bridge._wizard_step = 0
        self.connected = False
        self.bridge._get_twitch_connected = lambda: self.connected

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def needed(self):
        return Bridge._wizard_is_needed(self.bridge)

    def follow_a_channel(self):
        self.db.add_channel("yt:UC1", "youtube", "UC1", "One")

    def test_a_fresh_install_is_walked_through(self):
        self.assertTrue(self.needed())

    def test_the_box_is_the_way_out_of_them(self):
        Bridge.setWizardHidden(self.bridge, True)
        self.assertFalse(self.needed())

    def test_and_it_can_be_taken_back(self):
        Bridge.setWizardHidden(self.bridge, True)
        Bridge.setWizardHidden(self.bridge, False)
        self.assertTrue(self.needed())

    def test_being_set_up_counts_as_done_on_its_own(self):
        # His ruling. Somebody with channels and Twitch has nothing left to be
        # walked through, and asking every launch would be nagging.
        self.follow_a_channel()
        self.connected = True
        self.assertFalse(self.needed())

    def test_half_way_is_not_done(self):
        self.follow_a_channel()
        self.assertTrue(self.needed())
        self.connected = True
        self.db.remove_channel("yt:UC1")
        self.assertTrue(self.needed())

    def test_a_channel_kept_for_a_saved_video_does_not_count(self):
        # Untracked rows are not channels anybody followed, so a copy that has
        # only those has still imported nothing.
        self.db.remember_channel("yt:UC2", "youtube", "UC2", "Two")
        self.connected = True
        self.assertTrue(self.needed())

    def test_it_opens_only_when_it_is_needed(self):
        self.follow_a_channel()
        self.connected = True
        Bridge.showWizardIfNeeded(self.bridge)
        self.assertFalse(self.bridge._wizard_open)
        self.db.set_state("wizard_hidden", "0")
        self.connected = False
        Bridge.showWizardIfNeeded(self.bridge)
        self.assertTrue(self.bridge._wizard_open)


class WalkingThem(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._db = self.db
        self.bridge._wizard_open = False
        self.bridge._wizard_step = 0

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def step(self):
        return Bridge.wizardStep.fget(self.bridge)

    def test_they_begin_at_the_welcome(self):
        Bridge.openWizard(self.bridge)
        self.assertTrue(Bridge.wizardOpen.fget(self.bridge))
        self.assertEqual(self.step(), 0)

    def test_next_and_back_walk_them(self):
        Bridge.openWizard(self.bridge)
        Bridge.stepWizard(self.bridge, 1)
        Bridge.stepWizard(self.bridge, 1)
        self.assertEqual(self.step(), 2)
        Bridge.stepWizard(self.bridge, -1)
        self.assertEqual(self.step(), 1)

    def test_neither_end_can_be_walked_off(self):
        Bridge.openWizard(self.bridge)
        Bridge.stepWizard(self.bridge, -1)
        self.assertEqual(self.step(), 0)
        for _ in range(10):
            Bridge.stepWizard(self.bridge, 1)
        self.assertEqual(self.step(), WIZARD_LAST)

    def test_opening_them_again_starts_at_the_front(self):
        Bridge.openWizard(self.bridge)
        Bridge.stepWizard(self.bridge, 2)
        Bridge.closeWizard(self.bridge)
        Bridge.openWizard(self.bridge)
        self.assertEqual(self.step(), 0)
        self.assertTrue(Bridge.wizardOpen.fget(self.bridge))

    def test_the_box_is_remembered(self):
        Bridge.setWizardHidden(self.bridge, True)
        self.assertTrue(Bridge.wizardHidden.fget(self.bridge))
        self.assertEqual(self.db.get_state("wizard_hidden"), "1")


class WhatAddingAChannelSays(unittest.TestCase):
    """Typing a channel into a box has to answer.

    The status line said so all along, but it is one truncated line in the
    corner of the toolbar and the window that manages a group is drawn over
    it, so a misspelled reference looked exactly like an accepted one.
    """

    def setUp(self):
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._add_state = ""
        self.bridge._add_message = ""
        self.bridge._add_queue = []
        self.bridge._adder = None
        self.bridge._adding = -1
        self.bridge._set_status = lambda *_a, **_k: None
        self.bridge._start_next_add = lambda: None

    def state(self):
        return (Bridge.addState.fget(self.bridge), Bridge.addMessage.fget(self.bridge))

    def test_nothing_is_said_before_anything_is_typed(self):
        self.assertEqual(self.state(), ("", ""))

    def test_a_reference_that_is_not_one_is_refused_out_loud(self):
        self.assertFalse(Bridge._queue_channel(self.bridge, "definitely not a channel", -1))
        state, message = self.state()
        self.assertEqual(state, "failed")
        self.assertIn("handle", message)

    def test_a_reference_that_reads_says_it_is_looking(self):
        self.assertTrue(Bridge._queue_channel(self.bridge, "@somebody", -1))
        state, message = self.state()
        self.assertEqual(state, "working")
        self.assertIn("somebody", message)

    def test_one_that_comes_back_with_nothing_says_that_too(self):
        Bridge._on_channel_failed(self.bridge, "no such channel")
        state, message = self.state()
        self.assertEqual(state, "failed")
        self.assertIn("no such channel", message)

    def test_typing_again_clears_the_last_answer(self):
        Bridge._on_channel_failed(self.bridge, "no such channel")
        Bridge.clearAddState(self.bridge)
        self.assertEqual(self.state(), ("", ""))


class WhatTheImportPageSays(unittest.TestCase):
    """The step that fails, and the only one that has to explain itself."""

    def setUp(self):
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._import_state = ""
        self.bridge._import_message = ""
        self.bridge._problems = []
        self.bridge.problemsChanged = _Silence()
        self.bridge._set_status = lambda *_a, **_k: None
        self.bridge.reload = lambda: None
        self.bridge.refresh = lambda: None

    def state(self):
        return (Bridge.importState.fget(self.bridge), Bridge.importMessage.fget(self.bridge))

    def test_nothing_is_said_before_it_is_asked(self):
        self.assertEqual(self.state(), ("", ""))

    def test_a_finished_import_says_what_it_found(self):
        Bridge._on_imported(self.bridge, 455, 12)
        state, message = self.state()
        self.assertEqual(state, "done")
        self.assertIn("455", message)
        self.assertIn("12", message)

    def test_a_failure_carries_the_reason_through(self):
        Bridge._on_import_failed(self.bridge, "yt-dlp said: Sign in to confirm you are not a bot")
        state, message = self.state()
        self.assertEqual(state, "failed")
        self.assertIn("Sign in", message)


if __name__ == "__main__":
    unittest.main()
