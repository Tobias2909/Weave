"""The headless mpv, driven for real.

Everything else in the suite runs with nothing installed. This one needs mpv,
and is skipped without it, because the whole point is that the entry ids mpv
reports line up with the roles Weave gave them. A fake would only prove the
fake. Two short generated tones stand in for tracks, so no network is touched.

The player is told to play to nowhere. What is under test is what mpv reports
back over its socket, never the sound, and a machine with no sound card cannot
open an audio output at all: mpv then ends every entry with error rather than
eof, which is not the module failing but the machine having no speakers. That
is what a build runner is.
"""

import math
import os
import shutil
import struct
import tempfile
from pathlib import Path
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

    def test_a_start_position_is_shaped_for_the_mpv_in_front_of_it(self):
        """Where loadfile's options go moved in mpv 0.38.

        Handing the wrong shape to a player is not a start position quietly
        lost, it is a load that never happens: nothing plays and nothing says
        why. Debian and Ubuntu still ship 0.37, and a build runner on 0.37 is
        what found this.
        """
        from unittest import mock

        from weave import engine as engine_module

        sent = []

        class Ipc:
            def send(self, command, role=None):
                sent.append(command)

        made = MusicEngine()
        made._ipc = Ipc()
        made.ensure = lambda: True
        for takes_index, want in ((True, [-1, "start=+2.500"]), (False, ["start=+2.500"])):
            sent.clear()
            with mock.patch.object(engine_module, "loadfile_takes_an_index",
                                   return_value=takes_index):
                made.load("/tmp/a.wav", start=2.5)
            self.assertEqual(sent, [["loadfile", "/tmp/a.wav", "replace", *want]],
                             f"loadfile_takes_an_index={takes_index}")

    def test_and_a_load_with_no_start_is_the_same_either_way(self):
        from unittest import mock

        from weave import engine as engine_module

        sent = []

        class Ipc:
            def send(self, command, role=None):
                sent.append(command)

        made = MusicEngine()
        made._ipc = Ipc()
        made.ensure = lambda: True
        for takes_index in (True, False):
            sent.clear()
            with mock.patch.object(engine_module, "loadfile_takes_an_index",
                                   return_value=takes_index):
                made.load("/tmp/a.wav")
            self.assertEqual(sent, [["loadfile", "/tmp/a.wav", "replace"]])

    @unittest.skipUnless(shutil.which("mpv"), "mpv is not installed")
    def test_the_installed_mpv_answers_which_shape_it_wants(self):
        from weave.engine import loadfile_takes_an_index

        self.assertIsInstance(loadfile_takes_an_index(), bool)

    @unittest.skipUnless(shutil.which("mpv"), "mpv is not installed")
    def test_it_lets_mpv_find_its_own_audio_output(self):
        # The tests name one so they can run on a machine with no sound card.
        # The application must never name one: sound that has gone should say
        # so rather than be played to nowhere.
        self.assertFalse([one for one in mpv_command(55, "/run/x.sock")
                          if one.startswith("--ao")])
        self.assertIn("--ao=null", mpv_command(55, "/run/x.sock", ao="null"))


class WhenItWillNotStart(unittest.TestCase):
    """What a player that refuses says. It runs with no terminal, so unless
    its own words are kept the window can only report the silence, and a
    build that does not know one of the options Weave passes looks exactly
    like a machine with no sound."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.engine = MusicEngine(socket_path=os.path.join(self.dir, "m.sock"))
        self.engine._log = Path(self.dir) / "mpv.log"       # noqa: SLF001
        self.addCleanup(self.engine.quit)
        self.said = []
        self.engine.gone.connect(self.said.append)

    def test_an_option_this_mpv_does_not_know_is_quoted_back(self):
        import weave.engine as engine_module

        real = engine_module.mpv_command
        self.addCleanup(setattr, engine_module, "mpv_command", real)
        engine_module.mpv_command = lambda *a, **k: [*real(*a, **k), "--weave-not-an-option"]
        self.assertFalse(self.engine.ensure())
        self.assertTrue(self.said, "nothing was said about a player that never started")
        self.assertIn("weave-not-an-option", self.said[0])

    def test_a_player_that_says_nothing_leaves_the_sentence_alone(self):
        self.engine._log.write_text("")                     # noqa: SLF001
        self.assertEqual(self.engine.complaint(), "")


class Reaping(unittest.TestCase):
    """Every way of letting go of the player waits on it, so a player that
    dies, or is quit, never sits in the process table as a zombie."""

    def child(self, seconds: float):
        import subprocess
        import sys

        return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])

    def test_one_that_has_gone_is_collected(self):
        from weave.engine import _reap

        child = self.child(0)
        _reap(child)
        self.assertIsNotNone(child.returncode)

    def test_one_that_will_not_go_is_ended(self):
        from weave.engine import _reap

        child = self.child(60)
        _reap(child, grace_s=0.2)
        self.assertIsNotNone(child.returncode)

    def test_losing_the_socket_collects_the_process(self):
        engine = MusicEngine()
        engine._ipc = object()
        engine._process = self.child(60)
        gone = []
        engine.gone.connect(gone.append)
        engine._on_lost("mpv went away")
        self.assertEqual(gone, ["mpv went away"])
        self.assertIsNone(engine._process)


@unittest.skipUnless(shutil.which("mpv"), "mpv is not installed")
class Playing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.a = os.path.join(self.dir, "a.wav")
        self.b = os.path.join(self.dir, "b.wav")
        _tone(self.a, 4)
        _tone(self.b, 4)
        self.engine = MusicEngine(socket_path=os.path.join(self.dir, "m.sock"), ao="null")
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
        # Against the real player, so it proves the shape as well as the
        # intent. This is the one that went red on a runner carrying mpv 0.37.
        self.engine.load(self.a, start=2.5)
        self.assertTrue(_spin(5, lambda: len(self.positions) >= 1),
                        "nothing played at all, which is what the wrong "
                        "loadfile shape looks like")
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
            f"engine = MusicEngine(socket_path={os.path.join(self.dir, 'k.sock')!r}, ao='null')\n"
            "engine.set_volume(0)\n"
            f"engine.load({self.a!r})\n"
            "print(engine._process.pid, flush=True)\n"
            "time.sleep(30)\n")
        with subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                              text=True, cwd=os.path.dirname(os.path.dirname(
                                  os.path.abspath(__file__)))) as child:
            mpv_pid = int(child.stdout.readline().strip())
            self.assertTrue(os.path.exists(f"/proc/{mpv_pid}"))
            child.kill()
            child.wait()

        def running() -> bool:
            try:
                with open(f"/proc/{mpv_pid}/status") as status:
                    return "zombie" not in status.read()
            except OSError:
                return False

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and running():
            time.sleep(0.05)
        alive = running()
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
