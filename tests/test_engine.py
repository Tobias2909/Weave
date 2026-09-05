"""The headless mpv, driven for real.

Everything else in the suite runs with nothing installed. This one needs mpv,
and is skipped without it, because the whole point is that the entry ids mpv
reports line up with the roles Weave gave them. A fake would only prove the
fake. Two short generated tones stand in for tracks, so no network is touched.
"""

import math
import os
import shutil
import struct
import tempfile
import time
import unittest
import wave

from PySide6.QtCore import QCoreApplication, QEventLoop

from weave.engine import CURRENT, NEXT, MusicEngine, mpv_command

_app = QCoreApplication.instance() or QCoreApplication([])


def _tone(path, seconds):
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(i / 10)))
                                 for i in range(8000 * seconds)))


def _spin(seconds, until=None):
    """Run the event loop for a while, or until a condition holds."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until() if until is not None else False


class TheCommand(unittest.TestCase):
    @unittest.skipUnless(shutil.which("mpv"), "mpv is not installed")
    def test_it_is_plain_mpv_with_nothing_of_the_users_loaded(self):
        command = mpv_command(55, "/run/x.sock")
        self.assertTrue(command[0].endswith("mpv"))
        self.assertIn("--no-config", command)
        self.assertIn("--no-video", command)
        self.assertIn("--prefetch-playlist=yes", command)
        self.assertIn("--volume=55", command)
        self.assertIn("--input-ipc-server=/run/x.sock", command)


@unittest.skipUnless(shutil.which("mpv"), "mpv is not installed")
class Playing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.a = os.path.join(self.dir, "a.wav")
        self.b = os.path.join(self.dir, "b.wav")
        _tone(self.a, 4)
        _tone(self.b, 4)
        self.engine = MusicEngine(socket_path=os.path.join(self.dir, "m.sock"))
        self.engine.set_volume(0)
        self.started = []
        self.ended = []
        self.positions = []
        self.durations = []
        self.idle = []
        self.engine.started.connect(self.started.append)
        self.engine.ended.connect(self.ended.append)
        self.engine.positionChanged.connect(self.positions.append)
        self.engine.durationChanged.connect(self.durations.append)
        self.engine.idleChanged.connect(self.idle.append)

    def tearDown(self):
        self.engine.quit()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_load_starts_as_current_and_reports_duration_and_position(self):
        self.engine.load(self.a)
        self.assertTrue(_spin(5, lambda: self.started and self.positions))
        self.assertEqual(self.started[0], CURRENT)
        self.assertTrue(any(abs(d - 4.0) < 0.2 for d in self.durations))

    def test_a_start_position_goes_with_the_load(self):
        self.engine.load(self.a, start=2.5)
        self.assertTrue(_spin(5, lambda: len(self.positions) >= 1))
        self.assertGreaterEqual(self.positions[0], 2.4)

    def test_the_next_entry_is_told_apart_from_the_current_one(self):
        self.engine.load(self.a)
        self.assertTrue(_spin(5, lambda: self.started))
        self.engine.append(self.b)
        _spin(0.3)
        self.engine.seek(3.8)
        self.assertTrue(_spin(5, lambda: NEXT in self.started))
        self.assertEqual(self.started, [CURRENT, NEXT])
        self.assertEqual(self.ended, ["eof"])

    def test_a_replaced_track_does_not_report_an_ending(self):
        self.engine.load(self.a)
        self.assertTrue(_spin(5, lambda: self.started))
        self.engine.load(self.b)
        self.assertTrue(_spin(5, lambda: self.started.count(CURRENT) == 2))
        _spin(0.3)
        # The old one was stopped, not finished, and nobody needs telling.
        self.assertEqual(self.ended, [])

    def test_something_unplayable_ends_with_an_error(self):
        self.engine.load(os.path.join(self.dir, "missing.wav"))
        self.assertTrue(_spin(5, lambda: self.ended))
        self.assertEqual(self.ended, ["error"])

    def test_reaching_the_end_with_nothing_queued_goes_idle(self):
        self.engine.load(self.a)
        self.assertTrue(_spin(5, lambda: self.started))
        self.engine.seek(3.9)
        self.assertTrue(_spin(5, lambda: self.ended and True in self.idle))
        self.assertEqual(self.ended, ["eof"])

    def test_clearing_after_forgets_the_queued_entry(self):
        self.engine.load(self.a)
        self.assertTrue(_spin(5, lambda: self.started))
        self.engine.append(self.b)
        _spin(0.3)
        self.engine.clear_after()
        self.engine.seek(3.9)
        self.assertTrue(_spin(5, lambda: True in self.idle))
        self.assertNotIn(NEXT, self.started)

    def test_pause_is_reported_back(self):
        paused = []
        self.engine.pausedChanged.connect(paused.append)
        self.engine.load(self.a)
        self.assertTrue(_spin(5, lambda: self.started))
        self.engine.set_pause(True)
        self.assertTrue(_spin(3, lambda: True in paused))
        self.engine.set_pause(False)
        self.assertTrue(_spin(3, lambda: paused and paused[-1] is False))

    def test_the_player_dies_with_a_weave_that_was_killed(self):
        """A window can be killed. A headless mpv that outlived it would keep
        playing with nothing to stop it."""
        import signal
        import subprocess
        import sys
        script = (
            "import sys, time\n"
            "from PySide6.QtCore import QCoreApplication\n"
            "from weave.engine import MusicEngine\n"
            "app = QCoreApplication([])\n"
            f"engine = MusicEngine(socket_path={os.path.join(self.dir, 'k.sock')!r})\n"
            "engine.set_volume(0)\n"
            f"engine.load({self.a!r})\n"
            "print(engine._process.pid, flush=True)\n"
            "time.sleep(30)\n")
        child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True,
                                 cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        mpv_pid = int(child.stdout.readline().strip())
        self.assertTrue(os.path.exists(f"/proc/{mpv_pid}"))
        child.kill()
        child.wait()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and os.path.exists(f"/proc/{mpv_pid}") \
                and "zombie" not in open(f"/proc/{mpv_pid}/status").read():
            time.sleep(0.05)
        alive = os.path.exists(f"/proc/{mpv_pid}") and \
            "zombie" not in open(f"/proc/{mpv_pid}/status").read()
        if alive:
            os.kill(mpv_pid, signal.SIGKILL)
        self.assertFalse(alive, "mpv outlived the process that started it")

    def test_quitting_leaves_no_process_and_no_socket(self):
        self.engine.load(self.a)
        self.assertTrue(_spin(5, lambda: self.started))
        process = self.engine._process
        self.engine.quit()
        self.assertIsNotNone(process.poll())
        self.assertFalse(os.path.exists(os.path.join(self.dir, "m.sock")))


if __name__ == "__main__":
    unittest.main()
