import unittest

from weave import format as fmt


class AgeText(unittest.TestCase):
    NOW = 1_800_000_000

    def age(self, seconds_ago):
        return fmt.age_text(self.NOW - seconds_ago, now=self.NOW)

    def test_unknown(self):
        self.assertEqual(fmt.age_text(None), "")

    def test_fresh(self):
        self.assertEqual(self.age(5), "just now")

    def test_singular_and_plural(self):
        self.assertEqual(self.age(60), "1 minute ago")
        self.assertEqual(self.age(120), "2 minutes ago")
        self.assertEqual(self.age(3600), "1 hour ago")
        self.assertEqual(self.age(86400), "1 day ago")
        self.assertEqual(self.age(604800), "1 week ago")

    def test_months_and_years(self):
        self.assertEqual(self.age(2629800), "1 month ago")
        self.assertEqual(self.age(31557600), "1 year ago")
        self.assertEqual(self.age(31557600 * 3), "3 years ago")

    def test_future_date_does_not_produce_negatives(self):
        # A premiere can be dated ahead of now.
        self.assertEqual(fmt.age_text(self.NOW + 7200, now=self.NOW), "just now")


class UpcomingText(unittest.TestCase):
    NOW = 1_800_000_000

    def upcoming(self, seconds_from_now):
        return fmt.upcoming_text(self.NOW + seconds_from_now, now=self.NOW)

    def test_unknown_time_still_says_upcoming(self):
        self.assertEqual(fmt.upcoming_text(None), "Upcoming")

    def test_due_now_or_past_due(self):
        self.assertEqual(self.upcoming(0), "Starting soon")
        self.assertEqual(self.upcoming(-30), "Starting soon")

    def test_singular_and_plural(self):
        self.assertEqual(self.upcoming(30), "Starts in seconds")
        self.assertEqual(self.upcoming(60), "Starts in 1 minute")
        self.assertEqual(self.upcoming(3600), "Starts in 1 hour")
        self.assertEqual(self.upcoming(86400), "Starts in 1 day")


class CountText(unittest.TestCase):
    def test_none_is_empty_not_zero(self):
        self.assertEqual(fmt.count_text(None), "")

    def test_small(self):
        self.assertEqual(fmt.count_text(0), "0")
        self.assertEqual(fmt.count_text(999), "999")

    def test_thousands(self):
        self.assertEqual(fmt.count_text(1000), "1K")
        self.assertEqual(fmt.count_text(1500), "1.5K")
        self.assertEqual(fmt.count_text(39858), "39.9K")

    def test_millions_and_billions(self):
        self.assertEqual(fmt.count_text(2_500_887), "2.5M")
        self.assertEqual(fmt.count_text(1_811_113_398), "1.8B")


class DurationText(unittest.TestCase):
    def test_unknown_is_empty(self):
        # The normal state for a video RSS found but no sweep has reached.
        self.assertEqual(fmt.duration_text(None), "")
        self.assertEqual(fmt.duration_text(0), "")

    def test_minutes(self):
        self.assertEqual(fmt.duration_text(59), "0:59")
        self.assertEqual(fmt.duration_text(605), "10:05")

    def test_hours(self):
        self.assertEqual(fmt.duration_text(3600), "1:00:00")
        self.assertEqual(fmt.duration_text(7325), "2:02:05")


if __name__ == "__main__":
    unittest.main()
