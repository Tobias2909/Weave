"""How much room the pictures may take, and where that choice lives.

The default is in the config, because it is a number worth being able to read
in a file. The choice made in the window is kept in the database instead, so
config.toml stays something a person wrote. Three readers have to agree on
which of the two is in force: the launch, which prunes before the first
picture is drawn, the settings page, and the cache subcommand.
"""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject

from weave import imagecache
from weave.config import Config
from weave.db import Database
from weave.poller import ImageCacheJob
from weave.ui.bridge import Bridge

_app = QCoreApplication.instance() or QCoreApplication([])


class TheOffer(unittest.TestCase):
    def test_the_sizes_climb(self):
        self.assertEqual(list(imagecache.CEILING_STEPS_MB),
                         sorted(imagecache.CEILING_STEPS_MB))

    def test_the_shipped_default_is_one_of_them(self):
        # Or the page would open showing a size it cannot offer back.
        self.assertIn(Config(raw={}).image_max_mb, imagecache.CEILING_STEPS_MB)

    def test_whole_gigabytes_are_said_as_gigabytes(self):
        self.assertEqual([imagecache.ceiling_label(m) for m in imagecache.CEILING_STEPS_MB],
                         ["200 MB", "300 MB", "500 MB", "1 GB", "2 GB", "5 GB", "10 GB"])


class WhereItIsKept(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_the_config_holds_the_default(self):
        self.assertEqual(self.db.image_max_mb(300), 300)

    def test_a_choice_overrides_it(self):
        self.db.set_image_max_mb(2048)
        self.assertEqual(self.db.image_max_mb(300), 2048)

    def test_nonsense_falls_back_rather_than_raising(self):
        self.db.set_state("image_max_mb", "as much as you like")
        self.assertEqual(self.db.image_max_mb(300), 300)

    def test_a_ceiling_nothing_could_hold_is_lifted_to_something(self):
        # Sixteen megabytes is the floor everywhere else in the cache, and a
        # ceiling of zero would empty it on every launch.
        self.db.set_image_max_mb(0)
        self.assertEqual(self.db.image_max_mb(300), 16)


class ChoosingIt(unittest.TestCase):
    """The settings page's end of it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "t.db")
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._db = self.db
        self.bridge._cfg = Config(raw={})
        self.bridge._cache_held = 0
        self.jobs = []
        self.bridge._run_cache_job = self.jobs.append

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def choose(self, megabytes):
        Bridge.setCacheCeiling(self.bridge, megabytes)

    def test_it_is_stored(self):
        self.choose(1024)
        self.assertEqual(self.db.image_max_mb(300), 1024)
        self.assertEqual(Bridge.cacheCeiling.fget(self.bridge), 1024)

    def test_the_button_reads_the_label(self):
        self.choose(5120)
        self.assertEqual(Bridge.cacheCeilingText.fget(self.bridge), "5 GB")

    def test_every_step_is_offered_with_its_label(self):
        offered = Bridge.cacheChoices.fget(self.bridge)
        self.assertEqual([row["megabytes"] for row in offered],
                         list(imagecache.CEILING_STEPS_MB))
        self.assertEqual(offered[3]["label"], "1 GB")

    def test_raising_it_deletes_nothing(self):
        self.bridge._cache_held = 100 * 1024 * 1024
        self.choose(2048)
        self.assertEqual(self.jobs, [ImageCacheJob.MEASURE])

    def test_lowering_it_past_what_is_held_drops_the_oldest_at_once(self):
        # The reason for choosing a smaller number is usually that the room is
        # wanted now, not at the next launch.
        self.bridge._cache_held = 400 * 1024 * 1024
        self.choose(200)
        self.assertEqual(self.jobs, [ImageCacheJob.PRUNE])

    def test_lowering_it_to_more_than_is_held_only_measures(self):
        self.bridge._cache_held = 10 * 1024 * 1024
        self.choose(200)
        self.assertEqual(self.jobs, [ImageCacheJob.MEASURE])

    def test_a_size_that_is_not_offered_is_refused(self):
        self.choose(777)
        self.assertEqual(self.db.get_state("image_max_mb"), None)
        self.assertEqual(self.jobs, [])

    def test_choosing_the_one_already_in_force_does_nothing(self):
        self.choose(300)
        self.assertEqual(self.jobs, [])


if __name__ == "__main__":
    unittest.main()
