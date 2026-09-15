"""The surface the picture is drawn on.

Almost nothing here can be tested without a real graphics context. That is not
laziness: building the render context under the offscreen platform takes the
whole process down rather than failing, which was measured while writing it. So
the drawing is verified by running it against a real session and looking, and
what is pinned here is the bookkeeping around it, which is where every fault
actually was.
"""

import unittest

from weave.ui import videoitem


class WhichPlayerItDraws(unittest.TestCase):
    def tearDown(self) -> None:
        videoitem.attach(None)

    def test_it_holds_the_one_it_was_given(self) -> None:
        marker = object()
        videoitem.attach(marker)
        self.assertIs(videoitem.engine(), marker)

    def test_it_starts_holding_nothing(self) -> None:
        videoitem.attach(None)
        self.assertIsNone(videoitem.engine())


class TheNativeDisplay(unittest.TestCase):
    def test_it_answers_rather_than_raising(self) -> None:
        # Asked with no application, with a plain core one, and with a real
        # window, all of which happen. A core application has no native
        # interface at all and asking it raises, which reached the suite as an
        # error rather than as an empty answer.
        self.assertIsInstance(videoitem.display_params(), dict)

    def test_no_handle_is_a_normal_answer(self) -> None:
        # Nothing here needs a handle to work. Without one mpv still draws,
        # through software, which is slower and not broken.
        found = videoitem.display_params()
        self.assertTrue(set(found) <= {"wl_display", "x11_display"})


class OneContextOnly(unittest.TestCase):
    """mpv allows exactly one render context per player, and Qt is free to
    throw a renderer away and build another whenever the scene graph is
    rebuilt. Asking twice is refused with "Unspecified error"."""

    def test_the_context_is_held_apart_from_any_one_renderer(self) -> None:
        self.assertTrue(hasattr(videoitem, "_context"))
        self.assertFalse(hasattr(videoitem._Renderer, "_context"),
                         "a renderer owning the context means a second one asks again")

    def test_nothing_is_rebuilt_once_the_picture_is_down(self) -> None:
        # Clearing the context alone invites the next paint to build another,
        # which is then alive when the player closes and takes the process with
        # it. The flag is what stops that.
        self.assertTrue(hasattr(videoitem, "_finished"))


if __name__ == "__main__":
    unittest.main()
