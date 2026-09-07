"""Whether a newer release exists, and how that is said.

The check is worth exactly one request a day, so most of what matters here is
what happens when the answer is odd, absent or stale rather than when it is
good. An update announced for a version that is already running would be worse
than no check at all.
"""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject

from weave import __version__, poller
from weave.config import Config
from weave.db import Database
from weave import doctor
from weave.sources import release
from weave.ui.bridge import UPDATE_INTERVAL_S, Bridge

_app = QCoreApplication.instance() or QCoreApplication([])


class ReadingATag(unittest.TestCase):
    def test_the_v_is_not_part_of_the_version(self):
        self.assertEqual(release.numbers_of("v1.2.3"), (1, 2, 3))
        self.assertEqual(release.numbers_text("v1.2.3"), "1.2.3")

    def test_anything_after_the_numbers_is_ignored(self):
        self.assertEqual(release.numbers_of("v2.0.0-rc1"), (2, 0, 0))

    def test_a_tag_with_no_numbers_is_nothing(self):
        self.assertIsNone(release.numbers_of("release"))
        self.assertEqual(release.numbers_text("release"), "")

    def test_missing_parts_count_as_zero(self):
        self.assertTrue(release.is_newer("1.1", "1.0.3"))
        self.assertFalse(release.is_newer("1.1", "1.1.0"))

    def test_a_version_nobody_can_read_is_never_newer(self):
        # Saying an update exists on the strength of a tag that cannot be
        # compared is worse than saying nothing.
        self.assertFalse(release.is_newer("latest", "1.0.0"))
        self.assertFalse(release.is_newer("1.1.0", "not a version"))

    def test_older_and_equal_are_not_newer(self):
        self.assertFalse(release.is_newer("1.0.0", "1.0.1"))
        self.assertFalse(release.is_newer("1.0.0", "1.0.0"))


class ReadingTheAnswer(unittest.TestCase):
    def test_the_tag_and_the_page(self):
        payload = b'{"tag_name": "v1.2.0", "html_url": "https://example.invalid/r/1.2.0"}'
        self.assertEqual(release.parse(payload),
                         ("v1.2.0", "https://example.invalid/r/1.2.0"))

    def test_a_release_with_no_page_still_carries_its_tag(self):
        self.assertEqual(release.parse(b'{"tag_name": "v1.2.0"}'), ("v1.2.0", ""))

    def test_nonsense_is_an_error_rather_than_a_crash(self):
        for payload in (b"", b"<html>rate limited</html>", b"[]", b'{"message": "Not Found"}'):
            with self.subTest(payload=payload):
                with self.assertRaises(release.ReleaseError):
                    release.parse(payload)


class TheWorker(unittest.TestCase):
    """It must report nothing at all when the network is unhappy, since a
    version check is the least important thing here."""

    def setUp(self):
        self.cfg = Config(raw={})
        self._real = release.fetch
        self.addCleanup(setattr, poller.release_source, "fetch", self._real)

    def run_it(self, answer):
        def fake(_fetcher):
            if isinstance(answer, Exception):
                raise answer
            return answer
        poller.release_source.fetch = fake
        worker = poller.UpdateCheck(self.cfg)
        found = []
        worker.found.connect(lambda tag, url: found.append((tag, url)))
        worker.run()
        return found

    def test_an_answer_is_reported(self):
        self.assertEqual(self.run_it(("v9.9.9", "https://example.invalid/r")),
                         [("v9.9.9", "https://example.invalid/r")])

    def test_a_failure_is_silent(self):
        self.assertEqual(self.run_it(release.ReleaseError("no")), [])

    def test_even_an_unexpected_failure_is_silent(self):
        self.assertEqual(self.run_it(RuntimeError("something else entirely")), [])


class WhatTheDoctorSays(unittest.TestCase):
    """The versions of every other tool are in that report, so this one has to
    be too, or a report from that page cannot say what produced it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def line(self):
        report = doctor.Report()
        doctor._weave(self.db, report)
        return report.checks[0]

    def test_it_names_the_running_version(self):
        self.assertEqual(self.line().name, "Weave")
        self.assertIn(__version__, self.line().detail)

    def test_before_the_first_check_it_says_so(self):
        self.assertIn("not asked yet", self.line().detail)

    def test_a_newer_release_is_named_with_where_to_go(self):
        self.db.set_state("update_tag", "v99.0.0")
        self.assertIn("newest 99.0.0", self.line().detail)
        self.assertIn("newer release", self.line().fix)

    def test_being_current_is_stated_plainly(self):
        self.db.set_state("update_tag", f"v{__version__}")
        self.assertIn("the newest", self.line().detail)
        self.assertEqual(self.line().fix, "")

    def test_it_is_never_a_warning(self):
        # Being a version behind is not a fault, and the foot of the panel
        # already says so where it can be acted on.
        for tag in ("", "v99.0.0", f"v{__version__}", "nonsense"):
            with self.subTest(tag=tag):
                self.db.set_state("update_tag", tag)
                self.assertEqual(self.line().state, doctor.OK)

    def test_the_report_leads_with_it(self):
        report = doctor.run(Config(raw={}), self.db, network=False)
        self.assertEqual(report.checks[0].name, "Weave")


class WhatTheWindowIsTold(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._db = self.db
        self.bridge._cfg = Config(raw={})
        self.bridge._update = None
        self.bridge._update_tag = ""
        self.bridge._update_address = ""
        self.launched = []
        self.bridge._launch = lambda worker: self.launched.append(worker) or True

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def newer(self):
        return Bridge._newer_version(self.bridge)

    def test_nothing_is_said_before_anything_is_known(self):
        self.assertEqual(self.newer(), "")

    def test_a_newer_release_is_named_without_its_v(self):
        Bridge._on_update_found(self.bridge, "v99.0.0", "https://example.invalid/r")
        self.assertEqual(self.newer(), "99.0.0")

    def test_the_running_version_is_never_announced(self):
        # The case that matters after an update: the answer is still stored,
        # and it has to stop being news the moment this copy catches up.
        Bridge._on_update_found(self.bridge, f"v{__version__}", "")
        self.assertEqual(self.newer(), "")

    def test_the_answer_is_remembered_for_the_next_launch(self):
        Bridge._on_update_found(self.bridge, "v99.0.0", "https://example.invalid/r")
        self.assertEqual(self.db.get_state("update_tag"), "v99.0.0")
        self.assertEqual(self.db.get_state("update_address"), "https://example.invalid/r")
        self.assertNotEqual(self.db.get_state("update_checked_at"), None)

    def test_the_settings_page_is_told_the_newest_either_way(self):
        # The banner only speaks when there is something newer. The page
        # states the newest whatever it is, which is how somebody checks the
        # version they are running without a terminal.
        self.assertEqual(Bridge.latestVersion.fget(self.bridge), "")
        Bridge._on_update_found(self.bridge, f"v{__version__}", "https://example.invalid/r")
        self.assertEqual(Bridge.latestVersion.fget(self.bridge), __version__)
        self.assertEqual(self.newer(), "")

    def test_the_release_page_is_offered_only_once_there_is_one(self):
        self.assertFalse(Bridge.hasRelease.fget(self.bridge))
        Bridge._on_update_found(self.bridge, "v99.0.0", "https://example.invalid/r")
        self.assertTrue(Bridge.hasRelease.fget(self.bridge))

    def test_a_release_with_no_page_offers_nothing_to_open(self):
        Bridge._on_update_found(self.bridge, "v99.0.0", "")
        self.assertFalse(Bridge.hasRelease.fget(self.bridge))

    def test_it_asks_when_it_has_never_asked(self):
        Bridge.checkForUpdate(self.bridge)
        self.assertEqual(len(self.launched), 1)
        self.assertIsInstance(self.launched[0], poller.UpdateCheck)

    def test_it_does_not_ask_twice_in_a_day(self):
        Bridge._on_update_found(self.bridge, "v99.0.0", "")
        Bridge.checkForUpdate(self.bridge)
        self.assertEqual(self.launched, [])

    def test_it_asks_again_the_next_day(self):
        Bridge._on_update_found(self.bridge, "v99.0.0", "")
        stale = int(self.db.get_state("update_checked_at")) - UPDATE_INTERVAL_S - 1
        self.db.set_state("update_checked_at", str(stale))
        Bridge.checkForUpdate(self.bridge)
        self.assertEqual(len(self.launched), 1)

    def test_a_failed_check_leaves_the_day_uncounted(self):
        # The worker reports nothing on a failure, so nothing is stamped and
        # the next launch asks again rather than going quiet for a day.
        Bridge.checkForUpdate(self.bridge)
        self.assertEqual(self.db.get_state("update_checked_at"), None)


if __name__ == "__main__":
    unittest.main()
