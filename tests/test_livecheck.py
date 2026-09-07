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

    def test_an_announced_stream_carries_when_it_is_due(self):
        # The one thing the subscriptions sweep never says. It reports the
        # time as NA for every announced stream there is.
        got = livecheck.parse_line("aaaaaaaaaaa", "NA|is_upcoming|1788825600\n")
        self.assertEqual((got.starts_at, got.upcoming, got.still_live),
                         (1788825600, True, False))

    def test_an_announcement_with_no_time_is_not_a_zero(self):
        got = livecheck.parse_line("aaaaaaaaaaa", "NA|is_upcoming|NA\n")
        self.assertIsNone(got.starts_at)
        self.assertTrue(got.upcoming)

    def test_a_running_stream_is_not_an_announcement(self):
        got = livecheck.parse_line("aaaaaaaaaaa", "12|is_live|NA")
        self.assertFalse(got.upcoming)
        self.assertIsNone(got.starts_at)

    def test_the_old_two_field_answer_still_reads(self):
        # The print format gained a field. A line from before it must not
        # start claiming a start time it never carried.
        got = livecheck.parse_line("aaaaaaaaaaa", "3707|is_live")
        self.assertEqual((got.viewers, got.still_live, got.starts_at), (3707, True, None))

    def test_the_flag_that_makes_an_announcement_answer_at_all(self):
        # Without it yt-dlp calls having no formats an error, prints nothing
        # and the start time is lost. Measured against a real announcement.
        import inspect
        self.assertIn("--ignore-no-formats-error", inspect.getsource(livecheck.check))

    def test_the_id_is_carried_through(self):
        self.assertEqual(livecheck.parse_line("aaaaaaaaaaa", "1|is_live").ext_id,
                         "aaaaaaaaaaa")


if __name__ == "__main__":
    unittest.main()
