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
import unittest

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
            ytdlp.with_js_runtime(["yt-dlp", "--no-warnings", "https://example.invalid"]),
            ["yt-dlp", "--js-runtimes", "node:/usr/bin/node", "--no-warnings",
             "https://example.invalid"])

    def test_a_machine_that_needs_nothing_gets_the_command_it_gave(self):
        ytdlp.js_runtime_args = lambda: []
        command = ["yt-dlp", "--version"]
        self.assertIs(ytdlp.with_js_runtime(command), command)

    def test_every_runner_puts_it_in(self):
        """The three places that build a yt-dlp command line themselves, plus
        the shared runner. One of them forgetting is a machine where half the
        program works."""
        import inspect

        from weave import audio, poller
        from weave.sources import resolve

        for module in (audio, poller, resolve, ytdlp):
            source = inspect.getsource(module)
            for line in source.splitlines():
                if '"yt-dlp", "--no-warnings"' in line:
                    self.assertIn("with_js_runtime", source,
                                  f"{module.__name__} builds a command without it")
