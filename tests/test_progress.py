import tempfile
import unittest
from pathlib import Path

from weave.sources import progress

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
# The uppercase MD5 of that exact string. Pinned rather than recomputed, so a
# change to the naming scheme fails here instead of silently finding nothing.
EXPECTED_NAME = "75170FC230CD88F32E475FF4087F81D9"


class FilenameScheme(unittest.TestCase):
    def test_uppercase_md5_of_the_exact_url(self):
        self.assertEqual(progress.filename_for(URL), EXPECTED_NAME)

    def test_a_different_url_string_is_a_different_file(self):
        # Which is exactly why Weave hands out canonical URLs. An added &t=
        # parameter would point at a resume file that does not exist.
        self.assertNotEqual(progress.filename_for(URL), progress.filename_for(URL + "&t=90s"))


class ReadPosition(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, body: str, name: str = EXPECTED_NAME):
        (self.dir / name).write_text(body)

    def test_reads_the_start_position(self):
        self.write("# " + URL + "\nstart=612.500000\nvolume=44.000000\n")
        self.assertAlmostEqual(progress.position_for(URL, self.dir), 612.5)

    def test_a_file_without_a_url_comment_still_works(self):
        # Most existing files predate that option and hold only the settings.
        self.write("start=100.000000\n")
        self.assertAlmostEqual(progress.position_for(URL, self.dir), 100.0)

    def test_no_file_means_no_position(self):
        self.assertIsNone(progress.position_for(URL, self.dir))

    def test_a_file_with_no_start_line_means_no_position(self):
        self.write("volume=44.000000\n")
        self.assertIsNone(progress.position_for(URL, self.dir))

    def test_zero_is_treated_as_no_position(self):
        self.write("start=0.000000\n")
        self.assertIsNone(progress.position_for(URL, self.dir))

    def test_unreadable_value_is_ignored(self):
        self.write("start=notanumber\n")
        self.assertIsNone(progress.position_for(URL, self.dir))

    def test_bulk_lookup_returns_only_what_exists(self):
        self.write("start=42.000000\n")
        other = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
        found = progress.positions_for([URL, other], self.dir)
        self.assertEqual(list(found), [URL])
        self.assertAlmostEqual(found[URL], 42.0)


if __name__ == "__main__":
    unittest.main()
