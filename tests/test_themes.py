"""Theme files. A wrong file still has to load, with what is wrong reported."""

import tempfile
import unittest
from pathlib import Path

from weave import themes

GOOD = '''
name = "Trial"
[colors]
background = "#101010"
accent = "#abcdef"
[gradient]
angle = 45
stops = [
  { position = 0.0, color = "#ffffff" },
  { position = 1.0, color = "#000000" },
]
'''


class Loading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, body, name="trial.toml"):
        path = self.dir / name
        path.write_text(body)
        return themes.load_file(path)

    def test_a_good_file(self):
        got = self.write(GOOD)
        self.assertEqual(got.name, "Trial")
        self.assertEqual(got.colors["background"], "#101010")
        self.assertEqual(got.problems, [])

    def test_roles_it_does_not_mention_keep_their_default(self):
        got = self.write(GOOD)
        self.assertEqual(got.colors["text"], themes.FALLBACK["text"])
        self.assertEqual(set(got.colors), set(themes.ROLES))

    def test_an_invented_role_is_reported_and_ignored(self):
        got = self.write('name = "T"\n[colors]\nsparkle = "#ffffff"\n')
        self.assertNotIn("sparkle", got.colors)
        self.assertTrue(any("sparkle" in p for p in got.problems))

    def test_a_colour_that_is_not_a_colour_is_reported_and_skipped(self):
        # Passing it on would fail silently at paint time instead.
        got = self.write('name = "T"\n[colors]\naccent = "reddish"\n')
        self.assertEqual(got.colors["accent"], themes.FALLBACK["accent"])
        self.assertTrue(any("accent" in p for p in got.problems))

    def test_colour_shapes_that_are_accepted(self):
        for value in ("#fff", "#ffffff", "#ccffffff"):
            with self.subTest(value=value):
                got = self.write(f'name = "T"\n[colors]\naccent = "{value}"\n')
                self.assertEqual(got.colors["accent"], value)

    def test_a_file_with_no_name_uses_its_filename(self):
        got = self.write('[colors]\naccent = "#ffffff"\n', name="sunset.toml")
        self.assertEqual(got.name, "sunset")
        self.assertTrue(got.problems)

    def test_a_file_that_is_not_readable_still_loads(self):
        got = self.write("this is not toml {{{")
        self.assertEqual(got.colors, themes.FALLBACK)
        self.assertTrue(got.problems)

    def test_a_gradient_needs_two_stops(self):
        got = self.write('name = "T"\n[gradient]\nstops = [{ position = 0.0, color = "#fff" }]\n')
        self.assertIsNone(got.gradient)
        self.assertTrue(got.problems)

    def test_a_radial_gradient(self):
        got = self.write('name = "T"\n[gradient]\ntype = "radial"\n'
                         'origin_x = 1.0\norigin_y = 1.0\nradius = 1.3\nstops = ['
                         '{ position = 0.0, color = "#ffffff" },'
                         '{ position = 1.0, color = "#000000" }]\n')
        self.assertEqual(got.gradient["type"], "radial")
        self.assertEqual((got.gradient["originX"], got.gradient["originY"]), (1.0, 1.0))
        self.assertEqual(got.gradient["radius"], 1.3)

    def test_an_unknown_gradient_kind_falls_back_to_linear(self):
        got = self.write('name = "T"\n[gradient]\ntype = "spiral"\nstops = ['
                         '{ position = 0.0, color = "#ffffff" },'
                         '{ position = 1.0, color = "#000000" }]\n')
        self.assertEqual(got.gradient["type"], "linear")
        self.assertTrue(any("spiral" in p for p in got.problems))

    def test_a_gradient_with_no_kind_is_linear(self):
        got = self.write(GOOD)
        self.assertEqual(got.gradient["type"], "linear")

    def test_gradient_stops_are_sorted_and_clamped(self):
        got = self.write('name = "T"\n[gradient]\nangle = 400\nstops = ['
                         '{ position = 2.0, color = "#000000" },'
                         '{ position = -1.0, color = "#ffffff" }]\n')
        self.assertEqual([s["position"] for s in got.gradient["stops"]], [0.0, 1.0])
        self.assertEqual(got.gradient["stops"][0]["color"], "#ffffff")
        self.assertEqual(got.gradient["angle"], 40.0)

    def test_no_gradient_at_all_is_fine(self):
        self.assertIsNone(self.write('name = "T"\n[colors]\naccent = "#ffffff"\n').gradient)


class Discovery(unittest.TestCase):
    def test_the_built_ins_all_load_without_problems(self):
        built = [t for t in themes.available() if t.builtin]
        self.assertGreaterEqual(len(built), 8)
        for theme in built:
            with self.subTest(theme=theme.name):
                self.assertEqual(theme.problems, [])
                self.assertEqual(set(theme.colors), set(themes.ROLES))

    def test_the_default_is_among_them(self):
        self.assertIn(themes.DEFAULT_NAME, [t.name for t in themes.available()])

    def test_an_unknown_name_falls_back_rather_than_failing(self):
        # An interface with no colours is not an option.
        got = themes.find("nothing called this")
        self.assertEqual(got.name, themes.DEFAULT_NAME)
        self.assertEqual(set(got.colors), set(themes.ROLES))


if __name__ == "__main__":
    unittest.main()


class ShelfArrangement(unittest.TestCase):
    """The rule that puts the music sections in the order they were arranged.

    Kept as its own test because the map based version lost a section whenever
    two arrived with the same name, which reads as a row vanishing.
    """

    @staticmethod
    def arrange(shelves, wanted):
        remaining = list(shelves)
        ordered = []
        for title in wanted:
            for index, shelf in enumerate(remaining):
                if shelf["title"] == title:
                    ordered.append(remaining.pop(index))
                    break
        ordered.extend(remaining)
        return [s["title"] for s in ordered]

    def test_it_reorders(self):
        shelves = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
        self.assertEqual(self.arrange(shelves, ["C", "A"]), ["C", "A", "B"])

    def test_two_sections_with_one_name_both_survive(self):
        shelves = [{"title": "A"}, {"title": "Recaps"}, {"title": "Recaps"}, {"title": "B"}]
        self.assertEqual(len(self.arrange(shelves, ["B", "Recaps"])), 4)

    def test_a_name_that_is_gone_is_skipped(self):
        shelves = [{"title": "A"}, {"title": "B"}]
        self.assertEqual(self.arrange(shelves, ["Z", "B"]), ["B", "A"])

    def test_nothing_is_ever_lost(self):
        shelves = [{"title": t} for t in ("A", "B", "B", "C")]
        for wanted in ([], ["C"], ["B", "B"], ["Z"], ["C", "B", "A"]):
            with self.subTest(wanted=wanted):
                self.assertEqual(sorted(self.arrange(shelves, wanted)), ["A", "B", "B", "C"])
