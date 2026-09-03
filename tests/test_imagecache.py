"""Image cache tests. Pure functions and the on disk layout, no network."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from weave import imagecache


class QmlSource(unittest.TestCase):
    def test_wraps_a_url(self):
        self.assertEqual(imagecache.qml_source("https://i.ytimg.com/x.jpg"),
                         "image://cached/https://i.ytimg.com/x.jpg")

    def test_a_missing_picture_stays_empty(self):
        # An empty source is what QML needs in order to draw nothing, so this
        # must not become a provider url with no address behind it.
        for value in (None, "", "   ", "not a url", "file:///tmp/x.jpg"):
            with self.subTest(value=value):
                self.assertEqual(imagecache.qml_source(value), "")


class PathLayout(unittest.TestCase):
    def setUp(self):
        self.root = Path("/tmp/weave-test-images")

    def test_hashed_and_spread(self):
        first = imagecache.path_for(self.root, "https://a/one.jpg")
        second = imagecache.path_for(self.root, "https://a/two.jpg")
        self.assertNotEqual(first, second)
        # One directory holding thousands of files is worth avoiding.
        self.assertEqual(len(first.parent.name), 2)
        self.assertTrue(first.parent.parent == self.root)

    def test_stable_for_the_same_url(self):
        self.assertEqual(imagecache.path_for(self.root, "https://a/one.jpg"),
                         imagecache.path_for(self.root, "https://a/one.jpg"))

    def test_a_url_is_not_used_as_a_filename(self):
        path = imagecache.path_for(self.root, "https://a/b?c=d&e=/f")
        self.assertNotIn("/", path.name)
        self.assertNotIn("?", path.name)


class Housekeeping(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "images"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, size: int, age_days: float = 0) -> Path:
        path = imagecache.path_for(self.dir, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        if age_days:
            when = time.time() - age_days * 86400
            os.utime(path, (when, when))
        return path

    def test_size_reports_the_total(self):
        self.write("a", 1000)
        self.write("b", 2000)
        self.assertEqual(imagecache.size_bytes(self.dir), 3000)

    def test_size_of_a_missing_directory_is_zero(self):
        self.assertEqual(imagecache.size_bytes(self.dir / "nope"), 0)

    def test_prune_leaves_fresh_pictures_alone(self):
        self.write("a", 1000)
        self.assertEqual(imagecache.prune(self.dir, 7 * 86400), (0, 0))

    def test_prune_removes_what_is_past_the_window(self):
        self.write("fresh", 1000, age_days=1)
        self.write("stale", 2000, age_days=8)
        removed, freed = imagecache.prune(self.dir, 7 * 86400)
        self.assertEqual((removed, freed), (1, 2000))
        self.assertEqual(imagecache.size_bytes(self.dir), 1000)

    def test_prune_of_a_missing_directory_is_harmless(self):
        self.assertEqual(imagecache.prune(self.dir / "nope", 86400), (0, 0))

    def test_the_ceiling_drops_the_oldest_first(self):
        # Age alone cannot bound the size, since a week of heavy use could
        # exceed any ceiling.
        self.write("oldest", 1000, age_days=3)
        self.write("middle", 1000, age_days=2)
        self.write("newest", 1000, age_days=1)
        removed, freed = imagecache.enforce_ceiling(self.dir, 2000)
        self.assertEqual((removed, freed), (1, 1000))
        surviving = {p.name for p in self.dir.rglob("*") if p.is_file()}
        self.assertNotIn(imagecache.path_for(self.dir, "oldest").name, surviving)
        self.assertIn(imagecache.path_for(self.dir, "newest").name, surviving)

    def test_the_ceiling_does_nothing_when_it_fits(self):
        self.write("a", 1000)
        self.assertEqual(imagecache.enforce_ceiling(self.dir, 5000), (0, 0))

    def test_the_ceiling_can_empty_the_cache(self):
        self.write("a", 4000, age_days=1)
        removed, _ = imagecache.enforce_ceiling(self.dir, 100)
        self.assertEqual(removed, 1)


if __name__ == "__main__":
    unittest.main()
