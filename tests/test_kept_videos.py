"""Music videos kept on disk for the songs he keeps.

A song's picture is a stream like its sound, which is right for a song played
once and wrong for the handful played over and over: the address takes a
couple of seconds to find, the picture a couple more to arrive, and both
happen again on every play. A kept file has no address to find and cannot
expire, which a signed address does within hours.

Bounded by being about favourites only. On a real library that is eighteen
songs, and a three and a half minute video at the default ceiling measured
29 MiB.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from weave import videocache


class TheDirectory(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="weave-videos-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, key, height=1080, suffix=".webm", size=1024, age=0.0):
        path = videocache.target(self.dir, key, height)
        whole = path.with_suffix(suffix)
        whole.write_bytes(b"x" * size)
        if age:
            os.utime(whole, (whole.stat().st_atime - age, whole.stat().st_mtime - age))
        return whole

    def test_nothing_is_kept_to_begin_with(self):
        self.assertIsNone(videocache.held(self.dir, "yt:a", 1080))
        self.assertEqual(videocache.held_bytes(self.dir), 0)

    def test_what_was_written_is_found_again(self):
        whole = self.write("yt:a")
        self.assertEqual(videocache.held(self.dir, "yt:a", 1080), whole)

    def test_whatever_container_it_came_in(self):
        whole = self.write("yt:a", suffix=".mp4")
        self.assertEqual(videocache.held(self.dir, "yt:a", 1080), whole)

    def test_a_different_ceiling_is_a_different_file(self):
        self.write("yt:a", height=1080)
        self.assertIsNone(videocache.held(self.dir, "yt:a", 720))

    def test_a_key_that_is_not_a_filename_is_still_fine(self):
        whole = self.write("twitch:somebody/with a slash")
        self.assertEqual(videocache.held(self.dir, "twitch:somebody/with a slash", 1080),
                         whole)

    def test_half_a_download_is_not_a_video(self):
        self.write("yt:a", suffix=".webm.part")
        self.assertIsNone(videocache.held(self.dir, "yt:a", 1080))
        self.assertEqual(videocache.held_bytes(self.dir), 0)

    def test_an_empty_file_is_not_one_either(self):
        self.write("yt:a", size=0)
        self.assertIsNone(videocache.held(self.dir, "yt:a", 1080))


class MakingRoom(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="weave-videos-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.old = self.write("yt:old", age=10_000)
        self.middle = self.write("yt:middle", age=5_000)
        self.fresh = self.write("yt:fresh", age=0)

    def write(self, key, size=1_000_000, age=0.0):
        path = videocache.target(self.dir, key, 1080).with_suffix(".webm")
        path.write_bytes(b"x" * size)
        if age:
            os.utime(path, (path.stat().st_atime - age, path.stat().st_mtime - age))
        return path

    def test_under_the_ceiling_nothing_goes(self):
        self.assertEqual(videocache.prune(self.dir, 10_000_000), (0, 0))
        self.assertEqual(len(videocache.contents(self.dir)), 3)

    def test_over_it_the_one_played_longest_ago_goes_first(self):
        gone, freed = videocache.prune(self.dir, 2_500_000)
        self.assertEqual(gone, 1)
        self.assertEqual(freed, 1_000_000)
        self.assertFalse(self.old.exists())
        self.assertTrue(self.fresh.exists())

    def test_playing_one_again_moves_it_to_the_back_of_the_queue(self):
        videocache.touch(self.old)
        videocache.prune(self.dir, 2_500_000)
        self.assertTrue(self.old.exists())
        self.assertFalse(self.middle.exists())

    def test_one_that_is_no_longer_kept_goes_whatever_the_ceiling_says(self):
        """The only reason it was written down has gone."""
        gone, _ = videocache.prune(self.dir, 10_000_000, keep={self.fresh})
        self.assertEqual(gone, 2)
        self.assertEqual([one.path for one in videocache.contents(self.dir)], [self.fresh])

    def test_no_ceiling_at_all_still_drops_what_is_not_kept(self):
        videocache.prune(self.dir, 0, keep={self.fresh, self.middle})
        self.assertEqual(len(videocache.contents(self.dir)), 2)

    def test_dropping_the_lot(self):
        gone, freed = videocache.forget_all(self.dir)
        self.assertEqual((gone, freed), (3, 3_000_000))
        self.assertEqual(videocache.contents(self.dir), [])
        # And the directory is still there to write into.
        self.assertTrue(self.dir.exists())

    def test_dropping_the_lot_of_nothing(self):
        videocache.forget_all(self.dir)
        self.assertEqual(videocache.forget_all(self.dir), (0, 0))


class TheCeilingOffered(unittest.TestCase):
    def test_the_default_is_one_of_the_steps(self):
        self.assertIn(videocache.DEFAULT_CEILING_MB, videocache.CEILING_STEPS_MB)

    def test_and_holds_a_real_library_of_them(self):
        """Eighteen favourites at 29 MiB apiece is about half a gigabyte, so
        the default has to be comfortably past that or it would be pruning the
        set it exists to keep."""
        self.assertGreater(videocache.DEFAULT_CEILING_MB, 18 * 29 * 2)


if __name__ == "__main__":
    unittest.main()
