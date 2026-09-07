"""The config file, and what happens to a line in it that cannot be used.

A typo in the file used to reach the window as an exception out of a property,
which is the worst place for it: the window never opened and nothing said why.
Now the line is left out, the default applies, and the doctor lists it.
"""

import tempfile
import unittest
from pathlib import Path

from weave import config, doctor
from weave.config import DEFAULTS, Config

ROOT = Path(__file__).resolve().parent.parent


class WhatFits(unittest.TestCase):
    def test_a_number_for_a_number(self):
        self.assertTrue(config._fits(60, 90))
        self.assertTrue(config._fits(60, 90.0))
        self.assertTrue(config._fits(0.85, 1))

    def test_a_word_is_not_a_number(self):
        self.assertFalse(config._fits(60, "sixty"))

    def test_a_bool_stands_in_for_nothing_but_a_bool(self):
        self.assertFalse(config._fits(60, True))
        self.assertFalse(config._fits("auto", False))
        self.assertTrue(config._fits(True, False))
        self.assertFalse(config._fits(True, 1))

    def test_digits_may_be_written_without_quotes_for_a_text_setting(self):
        # An identity is a number, and a number typed unquoted is a number.
        self.assertTrue(config._fits("auto", 1055661234))
        self.assertTrue(config._fits("auto", "1055661234"))


class CheckingAFile(unittest.TestCase):
    def test_a_word_where_a_number_belongs_is_left_out_and_named(self):
        kept, warnings = config.check({"poll": {"tick_interval_s": "sixty"}})
        self.assertEqual(kept, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("poll.tick_interval_s", warnings[0])
        self.assertIn("sixty", warnings[0])
        self.assertIn("60", warnings[0])

    def test_the_default_then_applies_without_raising(self):
        kept, _ = config.check({"poll": {"tick_interval_s": "sixty"}})
        self.assertEqual(Config(raw=kept).tick_interval_s, DEFAULTS["poll"]["tick_interval_s"])

    def test_a_key_that_is_not_a_setting_is_named(self):
        kept, warnings = config.check({"poll": {"tick_intervall_s": 30}})
        self.assertEqual(kept, {})
        self.assertEqual(warnings, ["poll.tick_intervall_s is not a setting"])

    def test_a_section_that_is_not_read_is_named(self):
        kept, warnings = config.check({"polling": {"tick_interval_s": 30}})
        self.assertEqual(kept, {})
        self.assertEqual(warnings, ["[polling] is not a section this program reads"])

    def test_the_rest_of_the_file_still_applies(self):
        kept, warnings = config.check({"poll": {"tick_interval_s": "sixty",
                                                "channels_per_tick": 7}})
        self.assertEqual(kept, {"poll": {"channels_per_tick": 7}})
        self.assertEqual(len(warnings), 1)
        self.assertEqual(Config(raw=kept).channels_per_tick, 7)

    def test_a_whole_number_written_as_a_float_is_used(self):
        kept, warnings = config.check({"poll": {"tick_interval_s": 45.0}})
        self.assertEqual(warnings, [])
        self.assertEqual(Config(raw=kept).tick_interval_s, 45)

    def test_a_clean_file_has_nothing_to_say(self):
        kept, warnings = config.check({"poll": {"tick_interval_s": 30},
                                       "twitch": {"client_id": "abc"}})
        self.assertEqual(warnings, [])
        self.assertEqual(kept["twitch"]["client_id"], "abc")


class LoadingAFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "config.toml"

    def tearDown(self):
        self._tmp.cleanup()

    def test_warnings_travel_with_the_config(self):
        self.path.write_text('[poll]\ntick_interval_s = "sixty"\nchannels_per_tick = 9\n')
        cfg = config.load(self.path)
        self.assertIsNone(cfg.problem)
        self.assertEqual(len(cfg.warnings), 1)
        self.assertEqual(cfg.channels_per_tick, 9)
        self.assertEqual(cfg.tick_interval_s, DEFAULTS["poll"]["tick_interval_s"])

    def test_a_file_that_is_not_toml_is_a_problem_not_a_warning(self):
        self.path.write_text("this is not toml = = =\n")
        cfg = config.load(self.path)
        self.assertIsNotNone(cfg.problem)
        self.assertEqual(cfg.warnings, ())

    def test_the_shipped_example_is_clean(self):
        # Every line in it is read and understood, or the example teaches a
        # mistake to everyone who copies it.
        cfg = config.load(ROOT / "config.example.toml")
        self.assertIsNone(cfg.problem)
        self.assertEqual(cfg.warnings, ())
        self.assertTrue(cfg.raw, "the example file set nothing at all")

    def test_every_accessor_survives_the_shipped_example(self):
        cfg = config.load(ROOT / "config.example.toml")
        for name in dir(Config):
            if isinstance(getattr(Config, name), property):
                getattr(cfg, name)


class WhatTheDoctorSays(unittest.TestCase):
    def test_ignored_lines_are_worth_a_look(self):
        report = doctor.Report()
        doctor._config(Config(raw={}, warnings=("poll.tick_intervall_s is not a setting",)),
                       report)
        check = report.checks[0]
        self.assertEqual(check.state, doctor.WARN)
        self.assertIn("tick_intervall_s", check.detail)
        self.assertTrue(check.fix)

    def test_many_ignored_lines_are_counted_rather_than_listed(self):
        report = doctor.Report()
        doctor._config(Config(raw={}, warnings=tuple(f"a.b{i} is not a setting"
                                                     for i in range(5))), report)
        self.assertIn("and 2 more", report.checks[0].detail)

    def test_an_unreadable_file_is_broken(self):
        report = doctor.Report()
        doctor._config(Config(raw={}, problem="could not be read"), report)
        self.assertEqual(report.checks[0].state, doctor.FAIL)

    def test_a_clean_file_is_fine(self):
        report = doctor.Report()
        doctor._config(Config(raw={"poll": {"tick_interval_s": 30}}), report)
        self.assertEqual(report.checks[0].state, doctor.OK)


if __name__ == "__main__":
    unittest.main()
