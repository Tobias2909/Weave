import unittest

from weave.sources import subs


class ParseLines(unittest.TestCase):
    def test_plain_line(self):
        got = subs.parse_lines("UCabcdefghijklmnopqrstuv|Example Channel|https://a/av.jpg")
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0].ext_id, got[0].title, got[0].avatar_url),
                         ("UCabcdefghijklmnopqrstuv", "Example Channel", "https://a/av.jpg"))

    def test_channel_name_containing_the_separator(self):
        # Names are free text, so the split has to come from the right.
        got = subs.parse_lines("UCabcdefghijklmnopqrstuv|Name | Extra|https://a/av.jpg")
        self.assertEqual(got[0].title, "Name | Extra")
        self.assertEqual(got[0].avatar_url, "https://a/av.jpg")

    def test_protocol_relative_avatar_is_repaired(self):
        # This is how they actually arrive, and no image loader accepts it.
        got = subs.parse_lines("UCabcdefghijklmnopqrstuv|Example|//yt3.example/av.jpg")
        self.assertEqual(got[0].avatar_url, "https://yt3.example/av.jpg")

    def test_missing_pieces_become_none(self):
        got = subs.parse_lines("UCabcdefghijklmnopqrstuv|NA|NA")
        self.assertIsNone(got[0].title)
        self.assertIsNone(got[0].avatar_url)

    def test_junk_avatar_is_dropped(self):
        got = subs.parse_lines("UCabcdefghijklmnopqrstuv|Example|not a url")
        self.assertIsNone(got[0].avatar_url)

    def test_duplicates_are_collapsed(self):
        text = ("UCabcdefghijklmnopqrstuv|Example|https://a/1.jpg\n"
                "UCabcdefghijklmnopqrstuv|Example|https://a/2.jpg\n")
        self.assertEqual(len(subs.parse_lines(text)), 1)

    def test_non_channel_rows_are_skipped(self):
        text = ("garbage\n"
                "PLabcdefghijklmnopqrstuv|Playlist|https://a/1.jpg\n"
                "UCabcdefghijklmnopqrstuv|Example|https://a/1.jpg\n")
        self.assertEqual([c.ext_id for c in subs.parse_lines(text)],
                         ["UCabcdefghijklmnopqrstuv"])

    def test_key(self):
        got = subs.parse_lines("UCabcdefghijklmnopqrstuv|Example|https://a/av.jpg")
        self.assertEqual(got[0].key, "yt:UCabcdefghijklmnopqrstuv")


if __name__ == "__main__":
    unittest.main()
