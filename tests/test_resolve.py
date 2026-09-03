import unittest

from weave.ids import ChannelRef
from weave.sources import resolve


class ParseOutput(unittest.TestCase):
    def test_id_and_title(self):
        got = resolve.parse_output("UCabcdefghijklmnopqrstuv|Example Channel\n")
        self.assertEqual(got, ("UCabcdefghijklmnopqrstuv", "Example Channel"))

    def test_title_with_a_pipe_in_it(self):
        got = resolve.parse_output("UCabcdefghijklmnopqrstuv|Name | Extra\n")
        self.assertEqual(got[1], "Name | Extra")

    def test_missing_title_is_none(self):
        self.assertIsNone(resolve.parse_output("UCabcdefghijklmnopqrstuv|\n")[1])

    def test_na_title_is_none(self):
        # yt-dlp prints NA rather than an empty field when it has nothing.
        self.assertIsNone(resolve.parse_output("UCabcdefghijklmnopqrstuv|NA\n")[1])

    def test_skips_leading_blank_lines(self):
        got = resolve.parse_output("\n\nUCabcdefghijklmnopqrstuv|Example\n")
        self.assertEqual(got[0], "UCabcdefghijklmnopqrstuv")

    def test_rejects_anything_that_is_not_a_channel_id(self):
        for bad in ("", "\n", "NA|NA\n", "not-an-id|Example\n",
                    "UCtooshort|Example\n", "PLabcdefghijklmnopqrstuv|Example\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(resolve.ResolveError):
                    resolve.parse_output(bad)


class ResolveWithoutNetwork(unittest.TestCase):
    def test_a_twitch_login_is_already_its_own_id(self):
        # The only path that touches no lookup at all.
        got = resolve.resolve(ChannelRef("twitch", "id", "examplechannel"))
        self.assertEqual(got.key, "twitch:examplechannel")


class LookupFailureHandling(unittest.TestCase):
    """A failed lookup and an absent channel are different things."""

    def test_a_plain_id_survives_a_broken_lookup(self):
        ref = ChannelRef("youtube", "id", "UCabcdefghijklmnopqrstuv")
        got = resolve._unverified(ref, "yt-dlp is not installed", None)
        self.assertEqual(got.key, "yt:UCabcdefghijklmnopqrstuv")
        self.assertIsNone(got.title)

    def test_a_handle_cannot_survive_a_broken_lookup(self):
        # Without the lookup there is no id, so there is nothing to store.
        ref = ChannelRef("youtube", "handle", "@examplechannel")
        with self.assertRaises(resolve.ResolveError):
            resolve._unverified(ref, "the lookup timed out", None)


if __name__ == "__main__":
    unittest.main()
