import threading
import time
import unittest

from weave import process


class Run(unittest.TestCase):
    def test_captures_output(self):
        got = process.run(["printf", "hello"])
        self.assertEqual((got.returncode, got.stdout), (0, "hello"))

    def test_reports_a_failing_command(self):
        got = process.run(["false"])
        self.assertNotEqual(got.returncode, 0)

    def test_timeout_raises_its_own_type(self):
        # Not the builtin TimeoutError and not subprocess.TimeoutExpired, so
        # callers have exactly one thing to catch.
        with self.assertRaises(process.Timeout):
            process.run(["sleep", "10"], timeout=0.3)

    def test_cancel_stops_a_long_command_quickly(self):
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(process.Cancelled):
            process.run(["sleep", "30"], cancel=cancel, timeout=60)
        # The point of the whole module. Quitting must not wait for the child.
        self.assertLess(time.monotonic() - started, 5.0)

    def test_an_already_cancelled_event_stops_immediately(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(process.Cancelled):
            process.run(["sleep", "30"], cancel=cancel, timeout=60)


if __name__ == "__main__":
    unittest.main()
