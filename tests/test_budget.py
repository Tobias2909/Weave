"""The per endpoint ceiling.

What makes this worth its own module is that freshness alone cannot do the
job. With more channels than one round covers, the ones a round did not reach
are still legitimately due a second later, so a restart loop sends round after
round and every request in them passes its own freshness check. Counting what
each endpoint has been asked is what closes that, and it only works if the
count survives the restart.
"""

import tempfile
import unittest
from pathlib import Path

from weave.budget import FEEDS, Budget
from weave.db import Database


class BudgetCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "t.db"
        self.db = Database(self.path)
        self.budget = Budget(self.db, {FEEDS: 10}, window_s=900)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()


class Allowance(BudgetCase):
    def test_everything_fits_when_nothing_has_been_spent(self):
        self.assertEqual(self.budget.allowance(FEEDS, 4).granted, 4)

    def test_a_round_is_trimmed_rather_than_skipped(self):
        # Asking about the eight there was room for beats asking about none,
        # and the ones left out stay at the front of the queue.
        self.budget.spend(FEEDS, 8)
        allowance = self.budget.allowance(FEEDS, 5)
        self.assertEqual(allowance.granted, 2)
        self.assertTrue(allowance.full)
        self.assertFalse(allowance.empty)

    def test_a_spent_budget_grants_nothing_and_says_when(self):
        self.budget.spend(FEEDS, 10)
        allowance = self.budget.allowance(FEEDS, 1)
        self.assertTrue(allowance.empty)
        self.assertGreater(allowance.frees_at, 0)

    def test_an_endpoint_without_a_ceiling_is_never_held_back(self):
        budget = Budget(self.db, {}, window_s=900)
        budget.spend("anything", 1000)
        self.assertEqual(budget.allowance("anything", 50).granted, 50)

    def test_endpoints_are_counted_apart(self):
        # Measured: the feed endpoint refused 155 times in a row while sixty
        # image requests in the same minute all succeeded.
        self.budget.spend(FEEDS, 10)
        self.assertEqual(self.budget.allowance("browse", 3).granted, 3)


class Persistence(BudgetCase):
    def test_a_restart_does_not_forget(self):
        # The case this exists for. Six launches in five minutes used to send
        # six full rounds, every request of them passing its own freshness
        # check, because nothing outlived the process.
        self.budget.spend(FEEDS, 9)
        self.db.close()

        again = Database(self.path)
        try:
            budget = Budget(again, {FEEDS: 10}, window_s=900)
            self.assertEqual(budget.allowance(FEEDS, 5).granted, 1)
        finally:
            again.close()

    def test_counts_outside_the_window_do_not_hold_anything_back(self):
        minute = self.db.conn.execute("SELECT 1").fetchone()  # keep the connection warm
        self.db.conn.execute(
            "INSERT INTO request_budget(endpoint, minute, count) VALUES(?,?,?)",
            (FEEDS, 0, 10))
        self.db.conn.commit()
        self.assertEqual(self.budget.allowance(FEEDS, 4).granted, 4)
        self.assertIsNotNone(minute)

    def test_pruning_keeps_the_table_from_growing_forever(self):
        self.db.conn.execute(
            "INSERT INTO request_budget(endpoint, minute, count) VALUES(?,?,?)",
            (FEEDS, 0, 1))
        self.db.conn.commit()
        self.assertEqual(self.db.prune_request_budget(86400), 1)
        self.assertEqual(self.db.requests_in_window(FEEDS, 900), (0, 0))


class Reporting(BudgetCase):
    def test_refusals_are_counted_separately_from_requests(self):
        # Every scraper failure looks the same from outside, exit zero with no
        # items, so telling refused apart from empty is most of the diagnosis.
        self.budget.spend(FEEDS, 5, refused=2)
        self.assertEqual(self.db.requests_in_window(FEEDS, 900), (5, 2))
        self.assertEqual(self.budget.report(), [(FEEDS, 5, 2, 10)])


if __name__ == "__main__":
    unittest.main()
