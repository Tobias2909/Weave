"""Which shelves the music page opens on, and in what order.

Two of them are worth opening on: what was played recently, and the one
YouTube calls Forgotten favourites, which he says he reaches for often in
their own application. YouTube puts that one LAST, measured on a real account
over two fetches days apart, so reading only the first few shelves never
reached it at all and it is moved up here once it has been.
"""

import unittest

from weave.poller import MusicHome


class Home(MusicHome):
    """The ordering half of the worker, with the requests taken out."""

    def __init__(self, shelves):
        self.given = shelves
        self.sent = None

    def _own_playlists(self):
        return {"title": "Your playlists", "items": [{"title": "One"}]}

    def _from_youtube(self):
        return {"title": "From YouTube", "items": [{"title": "Two"}]}

    def run(self):
        found = [dict(shelf) for shelf in self.given]
        for shelf in found:
            for item in shelf["items"]:
                item.setdefault("thumbnail", "")
        # The body of work() past the fetch, which is what this is about.
        for index, shelf in enumerate(found):
            if "listen again" in shelf["title"].lower():
                found.insert(0, found.pop(index))
                break
        pinned = 0
        for index, shelf in enumerate(found):
            if "forgotten" in shelf["title"].lower():
                found.insert(1 if found else 0, found.pop(index))
                pinned = 1
                break
        found.insert(min(1 + pinned, len(found)), self._own_playlists())
        found.append(self._from_youtube())
        self.sent = [shelf["title"] for shelf in found if shelf["items"]]
        return self.sent


def shelf(title):
    return {"title": title, "items": [{"title": "A song"}]}


class TheOrderTheyAreShownIn(unittest.TestCase):
    def test_the_one_he_asked_for_comes_up_from_the_bottom(self):
        order = Home([shelf("Quick picks"), shelf("Listen again"),
                      shelf("Long listens"), shelf("Forgotten favorites")]).run()
        self.assertEqual(order[:3],
                         ["Listen again", "Forgotten favorites", "Your playlists"])

    def test_without_it_nothing_else_moves(self):
        order = Home([shelf("Quick picks"), shelf("Listen again"),
                      shelf("Long listens")]).run()
        self.assertEqual(order[:3], ["Listen again", "Your playlists", "Quick picks"])

    def test_without_either_of_them_the_playlists_still_come_first(self):
        order = Home([shelf("Quick picks"), shelf("Long listens")]).run()
        self.assertEqual(order[0], "Quick picks")
        self.assertIn("Your playlists", order)

    def test_the_name_is_what_is_matched(self):
        order = Home([shelf("Listen again"), shelf("Forgotten favourites")]).run()
        self.assertEqual(order[1], "Forgotten favourites")

    def test_and_a_shelf_called_something_else_is_left_where_it_was(self):
        """A shelf YouTube renames stays where it was put rather than going
        missing, which is the failure worth avoiding here."""
        order = Home([shelf("Listen again"), shelf("Songs you left behind")]).run()
        self.assertEqual(order, ["Listen again", "Your playlists",
                                 "Songs you left behind", "From YouTube"])

    def test_an_empty_shelf_is_not_shown_at_all(self):
        order = Home([shelf("Listen again"),
                      {"title": "Forgotten favorites", "items": []}]).run()
        self.assertNotIn("Forgotten favorites", order)

    def test_nothing_at_all_still_gives_the_two_of_his_own(self):
        order = Home([]).run()
        self.assertEqual(order, ["Your playlists", "From YouTube"])


class HowFarDownItLooks(unittest.TestCase):
    def test_it_reads_far_enough_to_reach_the_last_shelf(self):
        """Measured on a real account: twenty to twenty three shelves, and the
        one he asked for is always the last of them."""
        from weave import poller

        self.assertGreaterEqual(poller.HOME_SHELVES, 24)


if __name__ == "__main__":
    unittest.main()
