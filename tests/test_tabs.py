import unittest

from weave.sources import tabs


class ParseIds(unittest.TestCase):
    def test_keeps_only_video_ids(self):
        # A video id is eleven characters of that alphabet, so the filter is a
        # shape check. A radio playlist id is thirteen and is what actually
        # turns up in these listings.
        text = "aaaaaaaaaaa\nRDor6VC0FkOOw\n\nbbbbbbbbbbb\ngarbage\n"
        self.assertEqual(tabs.parse_ids(text), {"aaaaaaaaaaa", "bbbbbbbbbbb"})

    def test_an_empty_listing_is_an_empty_set(self):
        # A real answer. Plenty of channels post no Shorts at all.
        self.assertEqual(tabs.parse_ids(""), set())

    def test_duplicates_collapse(self):
        self.assertEqual(tabs.parse_ids("aaaaaaaaaaa\naaaaaaaaaaa\n"), {"aaaaaaaaaaa"})


class MissingTab(unittest.TestCase):
    """A channel with no Shorts has no Shorts tab, and yt-dlp calls that an
    error. Reading it as a failure left 181 of 424 channels permanently
    unclassified, so it has to be understood as an answer."""

    def setUp(self):
        self.real_run = tabs.run_process

    def tearDown(self):
        tabs.run_process = self.real_run

    def stub(self, returncode, stdout="", stderr=""):
        from weave.process import Result
        tabs.run_process = lambda *a, **k: Result(returncode, stdout, stderr)

    def test_no_shorts_tab_is_an_empty_answer(self):
        self.stub(1, stderr="ERROR: [youtube:tab] UCx/shorts: This channel does not "
                            "have a shorts tab")
        self.assertEqual(tabs.fetch_ids("UCabcdefghijklmnopqrstuv", tabs.SHORTS), set())

    def test_no_videos_tab_is_an_empty_answer(self):
        self.stub(1, stderr="ERROR: [youtube:tab] UCx/videos: This channel does not "
                            "have a videos tab")
        self.assertEqual(tabs.fetch_ids("UCabcdefghijklmnopqrstuv", tabs.VIDEOS), set())

    def test_a_real_failure_is_still_a_failure(self):
        # A connection problem must not be mistaken for an empty channel, or a
        # video would be settled as long form on no evidence.
        self.stub(1, stderr="ERROR: [youtube:tab] UCx/shorts: Unable to download API page")
        with self.assertRaises(tabs.TabError):
            tabs.fetch_ids("UCabcdefghijklmnopqrstuv", tabs.SHORTS)

    def test_a_clean_empty_listing_is_an_answer(self):
        self.stub(0, stdout="")
        self.assertEqual(tabs.fetch_ids("UCabcdefghijklmnopqrstuv", tabs.SHORTS), set())


class TabUrls(unittest.TestCase):
    def test_built_from_the_channel_id(self):
        self.assertEqual(
            tabs.CHANNEL_TAB.format(channel_id="UCabcdefghijklmnopqrstuv", tab=tabs.SHORTS),
            "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv/shorts")


if __name__ == "__main__":
    unittest.main()
