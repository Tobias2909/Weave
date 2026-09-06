import os
import time
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


class StartTimeText(unittest.TestCase):
    """The clock an announced stream begins on.

    The zone is pinned here, since the point of the function is that it
    answers in whatever zone the machine is set to, and a test that ran in
    the local one would pass anywhere and prove nothing.
    """

    # Friday 15 January 2027, 12:00 UTC.
    NOON = 1_800_014_400

    def setUp(self):
        self._was = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        self.addCleanup(self._restore)

    def _restore(self):
        if self._was is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._was
        time.tzset()

    def starts(self, seconds_from_now):
        return fmt.start_time_text(self.NOON + seconds_from_now, now=self.NOON)

    def test_nothing_scheduled_is_empty(self):
        self.assertEqual(fmt.start_time_text(None), "")

    def test_later_today_and_tomorrow(self):
        self.assertEqual(self.starts(6 * 3600), "today at 18:00")
        self.assertEqual(self.starts(20 * 3600), "tomorrow at 08:00")

    def test_a_day_this_week_is_named(self):
        self.assertEqual(self.starts(3 * 86400), "Monday at 12:00")

    def test_further_off_carries_the_date(self):
        self.assertEqual(self.starts(30 * 86400), "14 Feb at 12:00")

    def test_another_year_carries_the_year(self):
        self.assertEqual(self.starts(400 * 86400), "19 Feb 2028 at 12:00")

    def test_the_hour_is_the_local_one(self):
        # An hour ahead of UTC and no daylight saving anywhere in the year, so
        # the arithmetic is the same whenever this runs.
        os.environ["TZ"] = "Africa/Lagos"
        time.tzset()
        self.assertEqual(self.starts(0), "today at 13:00")

    def test_a_time_already_past_still_reads_as_a_date(self):
        self.assertEqual(self.starts(-10 * 86400), "5 Jan at 12:00")


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
