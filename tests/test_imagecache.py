"""Image cache tests. Pure functions and the on disk layout, no network."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QImageReader

from weave import imagecache


def encoded(width: int, height: int) -> bytes:
    """A real PNG of that size, so a reader has something to measure."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data().data())


def read_bytes(payload: bytes) -> QImage:
    buffer = QBuffer()
    buffer.setData(payload)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    return imagecache._read(QImageReader(buffer))


class ABigPicture(unittest.TestCase):
    """Anything bigger than Weave draws is decoded smaller, not refused.

    Qt will not decode a picture whose pixels come to more than 256 MB, and it
    says so on the console once per attempt. A channel avatar asked for at its
    original size reached 8334 square, which is 265 MB, so it was refused,
    never cached, and fetched again on every visit to the view. The ceiling
    here is lowered rather than the picture made enormous, since the point is
    the arithmetic and not the allocation.
    """

    def setUp(self):
        self.real = imagecache.MAX_EDGE
        imagecache.MAX_EDGE = 8
        self.addCleanup(setattr, imagecache, "MAX_EDGE", self.real)

    def test_the_ceiling_is_above_anything_weave_draws(self):
        # A channel banner is the widest of them at 2560.
        self.assertGreaterEqual(self.real, 2048)

    def test_it_is_read_and_shrunk_to_the_ceiling(self):
        image = read_bytes(encoded(64, 32))
        self.assertFalse(image.isNull())
        self.assertEqual((image.width(), image.height()), (8, 4))

    def test_the_shape_is_kept(self):
        image = read_bytes(encoded(30, 60))
        self.assertEqual((image.width(), image.height()), (4, 8))

    def test_one_that_fits_is_untouched(self):
        image = read_bytes(encoded(8, 6))
        self.assertEqual((image.width(), image.height()), (8, 6))

    def test_the_same_holds_for_one_already_cached(self):
        # Both ways in have to be guarded. Only the download was, at first,
        # and then the picture came back off disk and was refused there.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "big.png"
            path.write_bytes(encoded(64, 64))
            image = imagecache._read(QImageReader(str(path)))
            self.assertEqual((image.width(), image.height()), (8, 8))

    def test_something_that_is_not_a_picture_is_still_nothing(self):
        self.assertTrue(read_bytes(b"this is not a picture").isNull())


# Driving a response needs a QGuiApplication, and the rest of the suite holds a
# QCoreApplication, so this runs in its own process the way the window test
# does. What it is here to prove is the part the decode tests cannot: that a
# picture too big to read plainly is written to the cache. Before, it was
# refused, nothing was stored, and every visit to the view fetched the same
# 646 KB again and printed another line about it.
SERVED = """
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QImage
app = QGuiApplication([])
from weave import imagecache

image = QImage(64, 64, QImage.Format.Format_RGB32)
image.fill(0x336699)
sink = QBuffer()
sink.open(QIODevice.OpenModeFlag.WriteOnly)
image.save(sink, "PNG")
payload = bytes(sink.data().data())


class Answer:
    status_code = 200
    content = payload


imagecache.requests.get = lambda *a, **k: Answer()
imagecache.MAX_EDGE = 8
url = "https://example.invalid/big.png"
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder) / "images"
    served = imagecache._Response(url, root, 3600)
    served.run()
    stored = imagecache.path_for(root, url)
    print("decoded", served._image.width(), served._image.height())
    print("cached", stored.exists() and stored.stat().st_size == len(payload))
    print("failures", len(imagecache.failures(root)))
"""


class ABigPictureIsServedAndKept(unittest.TestCase):
    def test_it_is_shrunk_stored_and_not_logged_as_a_failure(self):
        done = subprocess.run([sys.executable, "-c", SERVED],
                              cwd=Path(__file__).resolve().parent.parent,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        report = dict(line.split(" ", 1) for line in done.stdout.splitlines() if " " in line)
        self.assertEqual(report.get("decoded"), "8 8", done.stdout)
        self.assertEqual(report.get("cached"), "True", done.stdout)
        self.assertEqual(report.get("failures"), "0", done.stdout)


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


class FailureRecord(unittest.TestCase):
    """A picture that will not load is already visible as a gap. Saying so once
    per picture as well turns a bad minute on the network into hundreds of
    console lines, so they are written down instead."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "images"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_nothing_recorded_at_first(self):
        self.assertEqual(imagecache.failures(self.dir), [])

    def test_a_failure_is_kept_with_its_reason(self):
        imagecache._record(self.dir, "https://x/a.jpg", "HTTP 404")
        rows = imagecache.failures(self.dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][1], rows[0][2]), ("HTTP 404", "https://x/a.jpg"))

    def test_the_record_is_bounded(self):
        # A long outage must not grow a file without end.
        for n in range(imagecache.MAX_LOGGED + 40):
            imagecache._record(self.dir, f"https://x/{n}.jpg", "ConnectionError")
        self.assertEqual(len(imagecache.failures(self.dir)), imagecache.MAX_LOGGED)

    def test_a_damaged_record_is_not_a_crash(self):
        (self.dir / imagecache.FAILURE_LOG).write_text("nonsense\nalso nonsense\n")
        self.assertEqual(imagecache.failures(self.dir), [])

    def test_recording_into_a_missing_directory_is_harmless(self):
        imagecache._record(self.dir / "gone", "https://x/a.jpg", "HTTP 404")
        self.assertEqual(len(imagecache.failures(self.dir / "gone")), 1)
