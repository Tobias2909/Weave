import unittest

from weave.sources import shorts


class FakeFetcher:
    """Stands in for the real fetcher so the decision logic can be tested
    without a request."""

    def __init__(self, status, location=""):
        self.status = status
        self.location = location
        self.cookies_seen = None

    def head_status(self, url, cookies=None):
        self.cookies_seen = cookies
        return self.status, self.location


class Classify(unittest.TestCase):
    def test_direct_answer_is_a_short(self):
        self.assertTrue(shorts.classify(FakeFetcher(200), "aaaaaaaaaaa"))

    def test_redirect_to_a_watch_page_is_long_form(self):
        fetcher = FakeFetcher(303, "https://www.youtube.com/watch?v=aaaaaaaaaaa&pp=xyz")
        self.assertFalse(shorts.classify(fetcher, "aaaaaaaaaaa"))

    def test_a_consent_redirect_is_not_an_answer(self):
        # Without the consent cookie every request lands here, which would
        # otherwise make both cases look like long form.
        fetcher = FakeFetcher(302, "https://consent.youtube.com/m?continue=x")
        with self.assertRaises(shorts.UndecidedError):
            shorts.classify(fetcher, "aaaaaaaaaaa")

    def test_an_unexpected_redirect_is_not_an_answer(self):
        with self.assertRaises(shorts.UndecidedError):
            shorts.classify(FakeFetcher(302, "https://example.com/"), "aaaaaaaaaaa")

    def test_an_error_status_is_not_an_answer(self):
        for status in (404, 429, 500):
            with self.subTest(status=status):
                with self.assertRaises(shorts.UndecidedError):
                    shorts.classify(FakeFetcher(status), "aaaaaaaaaaa")

    def test_the_consent_choice_is_sent(self):
        fetcher = FakeFetcher(200)
        shorts.classify(fetcher, "aaaaaaaaaaa")
        self.assertEqual(fetcher.cookies_seen, {"SOCS": "CAI"})


if __name__ == "__main__":
    unittest.main()
