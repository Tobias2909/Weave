"""A whole theme worked out from two or three colours.

The difficulty is not the colours, it is that any two can be chosen and most
pairs make text nobody can read. So what is asserted here is mostly contrast.
"""

import unittest

from weave import palette

# A spread of grounds and accents, including the pairs that are hardest: a
# mid grey ground, which nothing contrasts well against, and a pale accent on
# a pale ground.
PAIRS = [
    ("#0f1115", "#7c5cff"), ("#120f1c", "#c264ff"), ("#f4f1ea", "#1f6feb"),
    ("#2b2b2b", "#7a7a7a"), ("#ffffff", "#ffff00"), ("#000000", "#101010"),
    ("#0a1a0d", "#3ad16a"), ("#fff8f0", "#ffd0a0"), ("#808080", "#818181"),
]


class WhatIsDerived(unittest.TestCase):
    def test_every_role_is_filled_in(self) -> None:
        from weave import themes

        made = palette.from_dots("#101216", "#7c5cff")
        self.assertEqual(set(made["colors"]), set(themes.ROLES))

    def test_the_marks_that_mean_something_are_left_alone(self) -> None:
        """A Twitch mark tinted to match the theme stops meaning Twitch."""
        for ground, accent in PAIRS:
            made = palette.from_dots(ground, accent)["colors"]
            for role, value in palette.FIXED.items():
                self.assertEqual(made[role], value, f"{role} followed the dots")

    def test_text_can_be_read_on_every_pair(self) -> None:
        for ground, accent in PAIRS:
            with self.subTest(ground=ground, accent=accent):
                made = palette.from_dots(ground, accent)["colors"]
                self.assertGreaterEqual(
                    palette.contrast(made["text"], made["background"]), 4.5,
                    "ordinary text cannot be read")
                self.assertGreaterEqual(
                    palette.contrast(made["textMuted"], made["background"]), 2.8,
                    "quieter text cannot be read")

    def test_the_surfaces_step_away_from_the_ground(self) -> None:
        """Each surface has to be told apart from the one under it, in a light
        window as well as a dark one."""
        for ground in ("#101216", "#f4f1ea"):
            made = palette.from_dots(ground, "#7c5cff")["colors"]
            steps = [made["background"], made["surface"],
                     made["surfaceRaised"], made["border"]]
            brightness = [palette._luminance(step) for step in steps]
            self.assertEqual(brightness, sorted(brightness, reverse=ground == "#f4f1ea"))

    def test_the_same_dots_always_give_the_same_theme(self) -> None:
        self.assertEqual(palette.from_dots("#101216", "#7c5cff"),
                         palette.from_dots("#101216", "#7c5cff"))

    def test_one_dot_left_alone_still_makes_a_gradient(self) -> None:
        """Wanting only an accent means leaving the third dot where it is."""
        made = palette.from_dots("#101216", "#7c5cff")
        stops = made["gradient"]["stops"]
        self.assertEqual(len(stops), 3)
        self.assertEqual(stops[-1]["color"], made["colors"]["background"])
        self.assertNotEqual(stops[0]["color"], stops[-1]["color"])

    def test_nonsense_is_not_an_error(self) -> None:
        made = palette.from_dots("not a colour", "")["colors"]
        self.assertEqual(made["background"], "#000000")
        self.assertGreaterEqual(palette.contrast(made["text"], made["background"]), 4.5)


class TheMeasure(unittest.TestCase):
    def test_black_on_white_is_the_widest_it_goes(self) -> None:
        self.assertAlmostEqual(palette.contrast("#000000", "#ffffff"), 21.0, places=1)

    def test_a_colour_against_itself_is_the_narrowest(self) -> None:
        self.assertAlmostEqual(palette.contrast("#3a7bd5", "#3a7bd5"), 1.0, places=6)

    def test_short_hex_is_read_the_same_as_long(self) -> None:
        self.assertEqual(palette.to_hex(palette.to_rgb("#abc")), "#aabbcc")


class WritingItOut(unittest.TestCase):
    def test_it_reads_back_as_the_same_theme(self) -> None:
        import tempfile
        from pathlib import Path

        from weave import themes

        made = palette.from_dots("#101216", "#7c5cff")
        path = Path(tempfile.mkdtemp()) / "made.toml"
        path.write_text(palette.as_toml("Made Up", made), encoding="utf-8")
        loaded = themes.load_file(path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "Made Up")
        self.assertEqual(loaded.colors, made["colors"])
        self.assertEqual(len(loaded.gradient["stops"]), 3)
        self.assertEqual(loaded.problems, [])

    def test_a_name_cannot_decide_where_the_file_lands(self) -> None:
        from weave import themes

        self.assertEqual(themes.file_name("../../etc/passwd"), "etc-passwd")
        self.assertEqual(themes.file_name("My Own Theme!"), "my-own-theme")
        self.assertEqual(themes.file_name("   "), "theme")


if __name__ == "__main__":
    unittest.main()


class KeepingAndThrowingAway(unittest.TestCase):
    """A theme made here is a file like any other, and only the ones made here
    can be thrown away."""

    def bridge(self, home):
        from weave.ui.bridge import Bridge

        class Quiet:
            def emit(self, *_a):
                pass

        class Themes:
            def __init__(self):
                self.drafts = []
                self.chosen = ""
                self.reloads = 0

            def show_draft(self, made):
                self.drafts.append(made)

            def reload(self):
                self.reloads += 1

            def select(self, name):
                self.chosen = name

        made = Bridge.__new__(Bridge)
        made._theme = Themes()
        made.notices = []
        made._set_notice = lambda *a, **k: made.notices.append(a[0])
        made.themesChanged = Quiet()
        return made

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        from weave import themes

        self.home = Path(tempfile.mkdtemp())
        self._was = themes.user_dir
        themes.user_dir = lambda: self.home / "themes"

    def tearDown(self) -> None:
        from weave import themes

        themes.user_dir = self._was

    def test_saving_writes_a_theme_and_wears_it(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(self.home)
        self.assertTrue(Bridge.saveTheme(bridge, "Mine", "#101216", "#7c5cff", ""))
        written = list((self.home / "themes").glob("*.toml"))
        self.assertEqual([path.name for path in written], ["mine.toml"])
        self.assertEqual(bridge._theme.chosen, "Mine")
        self.assertEqual(bridge._theme.drafts[-1], None, "the draft was not put down")

    def test_a_theme_needs_a_name(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(self.home)
        self.assertFalse(Bridge.saveTheme(bridge, "   ", "#101216", "#7c5cff", ""))
        self.assertIn("needs a name", bridge.notices[-1])

    def test_only_a_theme_made_here_can_be_thrown_away(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(self.home)
        self.assertFalse(Bridge.deleteTheme(bridge, "Weave Dark"))
        self.assertIn("not one of yours", bridge.notices[-1])

    def test_what_was_made_here_is_offered_by_its_name(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(self.home)
        Bridge.saveTheme(bridge, "Mine Alone", "#101216", "#7c5cff", "")
        self.assertEqual(Bridge._get_own_themes(bridge), ["Mine Alone"])
        self.assertTrue(Bridge.deleteTheme(bridge, "Mine Alone"))
        self.assertEqual(Bridge._get_own_themes(bridge), [])
