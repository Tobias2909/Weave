"""Which JavaScript runtime yt-dlp is told to use.

YouTube answers a signed in request with a challenge that is solved in
JavaScript. yt-dlp enables deno and nothing else by default, so a machine
with node alone has a runtime yt-dlp will not touch, and the failure names
neither of them: MEASURED 2026-09-10 against the live site, the same call
answers "ERROR: [youtube] <id>: The page needs to be reloaded." with the
runtimes cleared and returns an address with node named. Without cookies it
works either way, which is what made it look like a cookie problem.
"""

import shutil
import sys
import unittest
from pathlib import Path

from weave.sources import ytdlp


class Choosing(unittest.TestCase):
    def setUp(self):
        # Both are cached, and one of them shells out to yt-dlp --help, so
        # they are put back the way they were and the cache emptied either
        # side of every case.
        self.addCleanup(setattr, shutil, "which", shutil.which)
        self.addCleanup(setattr, ytdlp, "_takes_js_runtimes",
                        ytdlp._takes_js_runtimes)                 # noqa: SLF001
        self.addCleanup(ytdlp.js_runtime_args.cache_clear)
        ytdlp._takes_js_runtimes = lambda: True                   # noqa: SLF001
        ytdlp.js_runtime_args.cache_clear()

    def only(self, *present):
        shutil.which = lambda name: f"/usr/bin/{name}" if name in present else None
        ytdlp.js_runtime_args.cache_clear()

    def test_deno_needs_nothing_said(self):
        # It is the default, so naming it again buys nothing.
        self.only("deno", "node")
        self.assertEqual(ytdlp.js_runtime_args(), [])

    def test_node_is_named_with_its_path(self):
        # By name it would be looked for on yt-dlp's path, which is not
        # necessarily the one it was found on.
        self.only("node")
        self.assertEqual(ytdlp.js_runtime_args(), ["--js-runtimes", "node:/usr/bin/node"])

    def test_the_debian_spelling_is_still_node_to_yt_dlp(self):
        self.only("nodejs")
        self.assertEqual(ytdlp.js_runtime_args(), ["--js-runtimes", "node:/usr/bin/nodejs"])

    def test_bun_counts_too(self):
        self.only("bun")
        self.assertEqual(ytdlp.js_runtime_args(), ["--js-runtimes", "bun:/usr/bin/bun"])

    def test_nothing_installed_says_nothing(self):
        self.only()
        self.assertEqual(ytdlp.js_runtime_args(), [])

    def test_a_yt_dlp_without_the_option_is_left_alone(self):
        # An option it does not know is not a warning, it is a run that never
        # happens, so an old one is worse off for being helped.
        self.only("node")
        ytdlp._takes_js_runtimes = lambda: False                  # noqa: SLF001
        ytdlp.js_runtime_args.cache_clear()
        self.assertEqual(ytdlp.js_runtime_args(), [])


class InTheCommand(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, ytdlp, "js_runtime_args", ytdlp.js_runtime_args)

    def test_it_goes_straight_after_the_binary(self):
        # Before the URL, and before anything that takes a value.
        ytdlp.js_runtime_args = lambda: ["--js-runtimes", "node:/usr/bin/node"]
        self.assertEqual(
            ytdlp.prepare(["yt-dlp", "--no-warnings", "https://example.invalid"]),
            ["yt-dlp", "--js-runtimes", "node:/usr/bin/node", "--no-warnings",
             "https://example.invalid"])

    def test_a_machine_that_needs_nothing_gets_the_same_command_back(self):
        ytdlp.js_runtime_args = lambda: []
        self.assertEqual(ytdlp.prepare(["yt-dlp", "--version"]), ["yt-dlp", "--version"])

    def test_the_machine_s_own_yt_dlp_is_the_one_that_runs(self):
        # Weave carrying a second copy was tried and taken back out.
        ytdlp.js_runtime_args = lambda: []
        self.assertEqual(ytdlp.prepare(["yt-dlp", "--version"])[0], "yt-dlp")

    def test_every_runner_goes_through_it(self):
        """The places that build a yt-dlp command line themselves, plus the
        shared runner. One of them forgetting is a machine where half the
        program works."""
        import inspect

        from weave import audio, poller
        from weave.sources import resolve

        for module in (audio, poller, resolve, ytdlp):
            source = inspect.getsource(module)
            for line in source.splitlines():
                if '"yt-dlp", "--no-warnings"' in line:
                    self.assertIn("prepare(", source,
                                  f"{module.__name__} builds a command without it")


class TheShebang(unittest.TestCase):
    """Which python yt-dlp runs on.

    MEASURED on a real Fedora machine 2026-09-10: `#!/usr/bin/python3 -sP`.
    Reading the LAST word off that line runs `-sP` as a program, the probe
    fails with an OSError and the answer comes back "could not tell", so the
    wrong end of this line is enough to leave a machine with no solver
    showing no banner and no advice at all.
    """

    def test_fedora_writes_flags_after_the_interpreter(self):
        self.assertEqual(ytdlp._interpreter("#!/usr/bin/python3 -sP"),      # noqa: SLF001
                         "/usr/bin/python3")

    def test_a_bare_one_is_itself(self):
        self.assertEqual(ytdlp._interpreter("#!/usr/bin/python"),           # noqa: SLF001
                         "/usr/bin/python")

    def test_env_names_the_program_second(self):
        self.assertEqual(ytdlp._interpreter("#!/usr/bin/env python3"),      # noqa: SLF001
                         "python3")

    def test_env_with_flags_of_its_own(self):
        self.assertEqual(ytdlp._interpreter("#!/usr/bin/env -S python3 -u"),  # noqa: SLF001
                         "python3")

    def test_nothing_at_all_is_not_a_crash(self):
        self.assertEqual(ytdlp._interpreter("#!"), "")                      # noqa: SLF001


class TheSolver(unittest.TestCase):
    """Whether yt-dlp has the script that answers YouTube's challenge. A
    runtime with nothing to run is the same as no runtime."""

    def setUp(self):
        self.addCleanup(setattr, shutil, "which", shutil.which)
        self.addCleanup(ytdlp.solver.cache_clear)
        ytdlp.solver.cache_clear()

    def script(self, first_line, body="import yt_dlp\n"):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake = Path(tmp.name) / "yt-dlp"
        fake.write_text(first_line + "\n" + body)
        shutil.which = lambda name: str(fake) if name == "yt-dlp" else None
        ytdlp.solver.cache_clear()
        return fake

    def test_it_asks_yt_dlp_s_own_python_and_not_ours(self):
        # They are the same only by accident. yt-dlp can be a distribution
        # package while Weave runs from an environment of its own.
        self.script(f"#!{sys.executable}")
        have, said = ytdlp.solver()
        # This interpreter is the one running the tests, so the answer is
        # whatever it holds, and either way it is a real answer.
        self.assertIn(have, (True, False))
        self.assertIn("yt-dlp-ejs", said)

    def test_a_python_that_cannot_be_run_counts_as_missing(self):
        """Unknown is said out loud rather than swallowed. Naming a package
        that turns out to be present costs one line that can be ignored,
        and staying quiet leaves a machine that explains nothing."""
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake = Path(tmp.name) / "yt-dlp"
        fake.write_text("#!/does/not/exist/python3 -sP\n")
        shutil.which = lambda name: str(fake) if name == "yt-dlp" else None
        ytdlp.solver.cache_clear()
        have, said = ytdlp.solver()
        self.assertIs(have, False)
        self.assertIn("could not be read", said)

    def test_an_unproven_solver_still_names_the_package(self):
        ytdlp.solver.cache_clear()
        self.addCleanup(setattr, ytdlp, "solver", ytdlp.solver)
        ytdlp.solver = lambda: (None, "not a script, so it carries its own")
        self.assertIn("pip install --user yt-dlp-ejs", ytdlp.challenge_advice())

    def test_a_python_without_the_package_is_a_missing_solver(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # An interpreter that refuses every import of it.
        stub = Path(tmp.name) / "python"
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(0o755)
        fake = Path(tmp.name) / "yt-dlp"
        fake.write_text(f"#!{stub}\n")
        shutil.which = lambda name: str(fake) if name == "yt-dlp" else None
        ytdlp.solver.cache_clear()
        self.assertEqual(ytdlp.solver()[0], False)

    def test_a_frozen_build_is_not_asked(self):
        self.script("this is not a shebang")
        self.assertIsNone(ytdlp.solver()[0])

    def test_no_yt_dlp_at_all(self):
        shutil.which = lambda _name: None
        ytdlp.solver.cache_clear()
        self.assertIsNone(ytdlp.solver()[0])


class WhatTheChecksSay(unittest.TestCase):
    def setUp(self):
        from weave import doctor

        self.doctor = doctor
        self.addCleanup(setattr, ytdlp, "solver", ytdlp.solver)

    def line(self):
        report = self.doctor.Report()
        self.doctor._solver(report)                               # noqa: SLF001
        return report.checks[0]

    def test_a_machine_with_neither_is_told_what_to_install(self):
        ytdlp.solver = lambda: (False, "yt-dlp-ejs is not installed")
        said = self.line()
        self.assertEqual(said.state, self.doctor.FAIL)
        self.assertIn("pip install --user yt-dlp-ejs", said.fix)

    def test_a_machine_with_a_solver_says_which(self):
        ytdlp.solver = lambda: (True, "yt-dlp-ejs 0.8.0")
        said = self.line()
        self.assertEqual(said.state, self.doctor.OK)
        self.assertIn("0.8.0", said.detail)


class WhatTheFailureSays(unittest.TestCase):
    """The error YouTube sends names nothing that can be acted on, and it
    reads as a cookie problem when it is not one. What replaces it has to be
    typeable."""

    def setUp(self):
        self.addCleanup(setattr, ytdlp, "solver", ytdlp.solver)
        self.addCleanup(setattr, ytdlp, "js_runtime_args", ytdlp.js_runtime_args)

    def test_a_missing_solver_is_named_with_the_line_that_installs_it(self):
        ytdlp.solver = lambda: (False, "yt-dlp-ejs is not installed")
        said = ytdlp.challenge_advice()
        self.assertIn("yt-dlp-ejs", said)
        self.assertIn("pip install --user yt-dlp-ejs", said)

    def test_the_command_comes_before_the_explaining(self):
        # The banner elides, and what must survive it is the line a person
        # types, not the reason they are typing it.
        said = ytdlp.INSTALL_SOLVER
        self.assertLess(said.index("pip install"), said.index("distribution"))

    def test_a_missing_runtime_is_named_too(self):
        ytdlp.solver = lambda: (True, "yt-dlp-ejs 0.8.0")
        ytdlp.js_runtime_args = lambda: []
        self.addCleanup(setattr, shutil, "which", shutil.which)
        shutil.which = lambda _name: None
        said = ytdlp.challenge_advice()
        self.assertIn("deno", said)

    def test_a_machine_with_both_is_told_only_what_happened(self):
        ytdlp.solver = lambda: (True, "yt-dlp-ejs 0.8.0")
        ytdlp.js_runtime_args = lambda: ["--js-runtimes", "node:/usr/bin/node"]
        self.assertEqual(ytdlp.challenge_advice(), "YouTube's challenge went unanswered")

    def test_the_advice_rides_on_the_error_that_needs_it(self):
        from weave.process import Result

        result = Result(returncode=1, stdout="",
                        stderr="ERROR: [youtube] abc: The page needs to be reloaded.")
        ytdlp.solver = lambda: (False, "yt-dlp-ejs is not installed")
        raised = ytdlp.blame(result, RuntimeError, "the address")
        self.assertIn("pip install --user yt-dlp-ejs", str(raised))

    def test_the_advice_is_never_what_gets_cut(self):
        """A flat cap on the whole sentence cut yt-dlp's quote mid word and
        would cut the advice too once it grew. The quote is what gives way."""
        ytdlp.solver = lambda: (False, "yt-dlp-ejs is not installed")
        long_line = "ERROR: [youtube] abc: Requested format is not available. " + "x" * 400
        said = ytdlp.explain(long_line, long_line)
        self.assertTrue(said.startswith(ytdlp.challenge_advice()), said[:80])
        self.assertIn(". yt-dlp said ", said)
        # Both halves whole: all of the advice, and a real quote after it.
        self.assertEqual(len(said),
                         len(ytdlp.challenge_advice()) + len(". yt-dlp said ") + ytdlp.QUOTED)

    def test_one_sentence_serves_both_callers(self):
        """It was written twice with two different caps, and the shorter one
        was in the path every source uses."""
        from weave.audio import _why
        from weave.process import Result

        ytdlp.solver = lambda: (False, "yt-dlp-ejs is not installed")
        stderr = ("WARNING: [youtube] [jsc] Remote components challenge solver script "
                  "(deno) were skipped\n"
                  "ERROR: [youtube] abc: Requested format is not available. Use "
                  "--list-formats for a list of available formats")
        through_audio = _why(stderr)
        through_blame = str(ytdlp.blame(Result(returncode=1, stdout="", stderr=stderr),
                                       RuntimeError, "the address"))
        self.assertEqual(through_audio, through_blame)
        # And the whole of yt-dlp's line survives, which is the point of it.
        self.assertTrue(through_audio.endswith("for a list of available formats"))
