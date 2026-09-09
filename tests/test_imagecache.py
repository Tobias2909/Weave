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


# What the negative cache is for. A picture that is gone is gone, and asking
# again on every visit to the view it is on turned one dead thumbnail into
# fifty requests over three days. Driving a response needs a QGuiApplication,
# so this runs in its own process the same way the one above does.
GAVE_UP = """
import os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QImage
app = QGuiApplication([])
from weave import imagecache

image = QImage(4, 4, QImage.Format.Format_RGB32)
image.fill(0x336699)
sink = QBuffer()
sink.open(QIODevice.OpenModeFlag.WriteOnly)
image.save(sink, "PNG")
payload = bytes(sink.data().data())

asked = []


class Missing:
    status_code = 404
    content = b""


class Found:
    status_code = 200
    content = payload


def answering(what):
    def get(url, **kwargs):
        asked.append(url)
        return what()
    return get


def age(path, seconds):
    when = time.time() - seconds - 60
    os.utime(path, (when, when))


gone = "https://i4.ytimg.com/vi/_aaaaaaaaaa/hqdefault.jpg"
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder) / "images"
    reporter = imagecache.Reporter()
    said = []
    reporter.missing.connect(said.append)
    marker = imagecache.path_for(root, gone).with_suffix(imagecache.FAIL_SUFFIX)
    imagecache.requests.get = answering(Missing)

    imagecache._Response(gone, root, 3600, reporter).run()
    print("firstasked", len(asked))
    print("firstsaid", len(said))

    imagecache._Response(gone, root, 3600, reporter).run()
    print("secondasked", len(asked))

    age(marker, imagecache.FAILED_AGAIN_S)
    imagecache._Response(gone, root, 3600, reporter).run()
    print("thirdasked", len(asked))
    print("thirdsaid", ",".join(said))

    imagecache._Response(gone, root, 3600, reporter).run()
    print("fourthasked", len(asked))

    # Past the long window the picture is worth one more try, and one that
    # answers clears the marker rather than leaving it to expire again.
    age(marker, imagecache.MISSING_AGAIN_S)
    imagecache.requests.get = answering(Found)
    imagecache._Response(gone, root, 3600, reporter).run()
    print("fifthasked", len(asked))
    print("marker", marker.exists())

    # A picture that fails some other way is believed for minutes, not a week,
    # and never says anything about the video behind it.
    other = "https://i.ytimg.com/vi/bbbbbbbbbbb/hqdefault.jpg"
    theirs = imagecache.path_for(root, other).with_suffix(imagecache.FAIL_SUFFIX)


    class Broken:
        status_code = 500
        content = b""


    imagecache.requests.get = answering(Broken)
    before = len(asked)
    imagecache._Response(other, root, 3600, reporter).run()
    print("othersaid", len(said))
    age(theirs, imagecache.FAILED_AGAIN_S)
    was = len(asked)
    imagecache._Response(other, root, 3600, reporter).run()
    print("otherretried", len(asked) > was)
"""


class GivingUpOnAPicture(unittest.TestCase):
    """A dead picture is asked for twice and then left alone."""

    @classmethod
    def setUpClass(cls):
        done = subprocess.run([sys.executable, "-c", GAVE_UP],
                              cwd=Path(__file__).resolve().parent.parent,
                              capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr[-2000:]
        cls.out = done.stdout
        cls.said = dict(line.split(" ", 1) for line in done.stdout.splitlines() if " " in line)

    def test_the_first_404_is_not_taken_as_an_answer(self):
        # Measured on a real thumbnail: 404 once, 200 a minute later, on a
        # video that is public and playable. One 404 says nothing.
        self.assertEqual(self.said.get("firstasked"), "1", self.out)
        self.assertEqual(self.said.get("firstsaid"), "0", self.out)

    def test_it_is_not_asked_again_straight_away(self):
        self.assertEqual(self.said.get("secondasked"), "1", self.out)

    def test_the_second_404_is_the_answer(self):
        self.assertEqual(self.said.get("thirdasked"), "2", self.out)
        self.assertEqual(self.said.get("thirdsaid"), "_aaaaaaaaaa", self.out)

    def test_and_then_it_is_left_alone(self):
        # The whole point. One dead thumbnail was fetched fifty times in three
        # days before this.
        self.assertEqual(self.said.get("fourthasked"), "2", self.out)

    def test_past_the_long_window_it_gets_another_try(self):
        self.assertEqual(self.said.get("fifthasked"), "3", self.out)

    def test_a_picture_that_comes_back_clears_its_marker(self):
        self.assertEqual(self.said.get("marker"), "False", self.out)

    def test_another_kind_of_failure_says_nothing_about_the_video(self):
        self.assertEqual(self.said.get("othersaid"), "1", self.out)

    def test_and_is_believed_for_minutes_rather_than_a_week(self):
        self.assertEqual(self.said.get("otherretried"), "True", self.out)


class Normalising(unittest.TestCase):
    """Two addresses that are asked for and refused, fixed on the way out.

    Both are fixed here rather than at each source, so the ones already in the
    database are fixed as they are read and no migration is needed.
    """

    def test_the_sentinel_for_a_gone_entry_is_no_picture(self):
        # YouTube hands this over for a private or deleted playlist entry, and
        # it is a 404 itself, measured. There is nothing to draw.
        self.assertEqual(imagecache.normalise(imagecache.NO_THUMBNAIL), "")
        self.assertEqual(imagecache.qml_source(imagecache.NO_THUMBNAIL), "")

    def test_a_signed_crop_becomes_the_plain_thumbnail(self):
        signed = ("https://i.ytimg.com/vi/ccccccccccc/hqdefault_custom_1.jpg"
                  "?sqp=AAAAAAAA&rs=AOn4nothingreal")
        self.assertEqual(imagecache.normalise(signed),
                         "https://i.ytimg.com/vi/ccccccccccc/hqdefault.jpg")

    def test_a_signature_without_a_crop_goes_too(self):
        # The signature is what expires, whether or not the address names a
        # crop, so it is the query that has to go either way.
        signed = "https://i.ytimg.com/vi/ccccccccccc/hqdefault.jpg?sqp=AAAAAAAA&rs=AOn4"
        self.assertEqual(imagecache.normalise(signed),
                         "https://i.ytimg.com/vi/ccccccccccc/hqdefault.jpg")

    def test_the_size_in_the_name_is_kept(self):
        # hq720 answers without a signature, measured, so downgrading it to
        # hqdefault would throw away the bigger picture for nothing.
        signed = "https://i.ytimg.com/vi/ccccccccccc/hq720_custom_2.jpg?sqp=A&rs=B"
        self.assertEqual(imagecache.normalise(signed),
                         "https://i.ytimg.com/vi/ccccccccccc/hq720.jpg")
        for name in ("default", "mqdefault", "sddefault", "maxresdefault"):
            with self.subTest(name=name):
                plain = f"https://i.ytimg.com/vi/ccccccccccc/{name}.jpg"
                self.assertEqual(imagecache.normalise(plain + "?sqp=A&rs=B"), plain)

    def test_an_ordinary_address_is_left_alone(self):
        for url in ("https://i4.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg",
                    "https://yt3.googleusercontent.com/AbC=s512",
                    "https://static-cdn.jtvnw.net/previews/a-440x248.jpg"):
            with self.subTest(url=url):
                self.assertEqual(imagecache.normalise(url), url)


class TheVideoBehindAPicture(unittest.TestCase):
    def test_every_picture_host_is_read(self):
        # The same pictures are spelled i.ytimg.com and i1 through i4 alike,
        # and a real feed uses all of them.
        for host in ("i", "i1", "i2", "i3", "i4"):
            with self.subTest(host=host):
                self.assertEqual(
                    imagecache.video_id(f"https://{host}.ytimg.com/vi/_aaaaaaaaaa/hqdefault.jpg"),
                    "_aaaaaaaaaa")

    def test_a_picture_with_no_video_behind_it_says_so(self):
        for url in ("https://yt3.googleusercontent.com/AbC=s512",
                    "https://static-cdn.jtvnw.net/previews/a.jpg",
                    "", None):
            with self.subTest(url=url):
                self.assertEqual(imagecache.video_id(url), "")


class GroupingTheFailures(unittest.TestCase):
    def test_one_line_per_picture_with_a_count(self):
        rows = [(10, "HTTP 404", "https://x/a.jpg"),
                (20, "HTTP 404", "https://x/b.jpg"),
                (30, "HTTP 404", "https://x/a.jpg")]
        self.assertEqual(imagecache.grouped(rows),
                         [(20, "HTTP 404", "https://x/b.jpg", 1),
                          (30, "HTTP 404", "https://x/a.jpg", 2)])

    def test_the_same_picture_failing_two_ways_stays_two_lines(self):
        rows = [(10, "HTTP 404", "https://x/a.jpg"),
                (20, "unreadable", "https://x/a.jpg")]
        self.assertEqual(len(imagecache.grouped(rows)), 2)


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

    def test_the_log_is_not_swept_away_with_the_pictures(self):
        # It lives in the cache directory and is not a picture. Before the
        # negative cache it was rewritten often enough to always look fresh;
        # now a quiet week would have let the pruning take the one record of
        # what went wrong.
        imagecache._record(self.dir, "https://x/a.jpg", "HTTP 404")
        log = self.dir / imagecache.FAILURE_LOG
        old = time.time() - 999 * 86400
        os.utime(log, (old, old))
        imagecache.prune(self.dir, 86400)
        self.assertTrue(log.exists())
        imagecache.enforce_ceiling(self.dir, 0)
        self.assertTrue(log.exists())

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

    def test_forgetting_empties_the_log_and_the_markers(self):
        imagecache._record(self.dir, "https://x/a.jpg", "HTTP 404")
        marker = imagecache.path_for(self.dir, "https://x/a.jpg").with_suffix(
            imagecache.FAIL_SUFFIX)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("HTTP 404\t2\n")
        self.assertEqual(imagecache.forget(self.dir), (1, 1))
        self.assertEqual(imagecache.failures(self.dir), [])
        self.assertFalse(marker.exists())

    def test_forgetting_nothing_is_harmless(self):
        self.assertEqual(imagecache.forget(self.dir), (0, 0))
        self.assertEqual(imagecache.forget(self.dir / "never"), (0, 0))

    def test_a_damaged_record_is_not_a_crash(self):
        (self.dir / imagecache.FAILURE_LOG).write_text("nonsense\nalso nonsense\n")
        self.assertEqual(imagecache.failures(self.dir), [])

    def test_recording_into_a_missing_directory_is_harmless(self):
        imagecache._record(self.dir / "gone", "https://x/a.jpg", "HTTP 404")
        self.assertEqual(len(imagecache.failures(self.dir / "gone")), 1)
