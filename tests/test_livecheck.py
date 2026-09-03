import unittest

from weave.sources import livecheck


class ParseLine(unittest.TestCase):
    def test_a_running_stream(self):
        got = livecheck.parse_line("aaaaaaaaaaa", "3707|is_live\n")
        self.assertEqual((got.viewers, got.still_live), (3707, True))

    def test_a_finished_stream(self):
        # It leaves the live bar and stays in the feed as an ordinary video.
        got = livecheck.parse_line("aaaaaaaaaaa", "NA|was_live\n")
        self.assertEqual((got.viewers, got.still_live), (None, False))

    def test_a_missing_count_on_a_running_stream(self):
        got = livecheck.parse_line("aaaaaaaaaaa", "NA|is_live\n")
        self.assertEqual((got.viewers, got.still_live), (None, True))

    def test_nothing_at_all(self):
        got = livecheck.parse_line("aaaaaaaaaaa", "")
        self.assertEqual((got.viewers, got.still_live), (None, False))

    def test_the_id_is_carried_through(self):
        self.assertEqual(livecheck.parse_line("aaaaaaaaaaa", "1|is_live").ext_id,
                         "aaaaaaaaaaa")


if __name__ == "__main__":
    unittest.main()
