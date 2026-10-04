"""SponsorBlock: what is asked, and what of the answer is kept. Nothing here
reaches the network; the answer is shaped as the API was MEASURED to give it,
one entry per video whose hash shares the four characters asked about."""

import hashlib
import unittest
from urllib.parse import parse_qs, urlparse

from weave.net import HttpError
from weave.sources import sponsorblock

VIDEO = "abcdefghijk"


def segment(category, start, end, uuid="u", length=600.0):
    return {"category": category, "actionType": "skip", "segment": [start, end],
            "UUID": uuid, "videoDuration": length, "locked": 0, "votes": 3,
            "description": ""}


ANSWER = [
    {"videoID": "someoneelse", "segments": [segment("sponsor", 1, 2, "theirs")]},
    {"videoID": VIDEO, "segments": [
        segment("intro", 0.0, 12.5, "b"),
        segment("sponsor", 60.0, 90.0, "a"),
        segment("sponsor", 0.0, 0.0, "whole"),
        segment("music_offtopic", 100, 200, "unknown"),
        {"category": "outro", "segment": "broken"},
    ]},
]


class WhatIsAsked(unittest.TestCase):
    def test_only_four_characters_of_a_hash_go_out(self):
        expected = hashlib.sha256(VIDEO.encode()).hexdigest()[:4]
        self.assertEqual(sponsorblock.prefix(VIDEO), expected)
        address = sponsorblock.address(VIDEO)
        self.assertNotIn(VIDEO, address)
        self.assertTrue(urlparse(address).path.endswith("/api/skipSegments/" + expected))
        asked = parse_qs(urlparse(address).query)
        self.assertEqual(asked["service"], ["YouTube"])
        self.assertEqual(asked["actionTypes"], ['["skip"]'])
        self.assertIn('"sponsor"', asked["categories"][0])


class WhatIsKept(unittest.TestCase):
    def test_the_one_video_out_of_an_answer_about_many_in_order(self):
        found = sponsorblock.parse(ANSWER, VIDEO)
        self.assertEqual([(one.category, one.start, one.end, one.uuid) for one in found],
                         [("intro", 0.0, 12.5, "b"), ("sponsor", 60.0, 90.0, "a")])

    def test_nothing_for_a_video_not_in_it(self):
        self.assertEqual(sponsorblock.parse(ANSWER, "notthereatall"), ())
        self.assertEqual(sponsorblock.parse({"not": "a list"}, VIDEO), ())

    def test_marked_on_another_cut_of_the_video_is_dropped(self):
        marked = sponsorblock.Segment("sponsor", 60.0, 90.0, "a", length=600.0)
        self.assertTrue(sponsorblock.fits(marked, 600.4))
        self.assertTrue(sponsorblock.fits(marked, 601.2), "a little off, on a long segment")
        self.assertFalse(sponsorblock.fits(marked, 630.0))
        self.assertTrue(sponsorblock.fits(sponsorblock.Segment("sponsor", 1, 2, "a"), 630.0),
                        "a length nobody gave is no reason to doubt it")


class TheRequest(unittest.TestCase):
    class Fetcher:
        def __init__(self, answer=None, error=None):
            self.answer, self.error, self.asked = answer, error, []

        def get_bytes(self, url):
            self.asked.append(url)
            if self.error is not None:
                raise self.error
            return self.answer

    def test_a_hash_nobody_marked_anything_under_is_none(self):
        fetcher = self.Fetcher(error=HttpError(404, "x"))
        self.assertEqual(sponsorblock.fetch(fetcher, VIDEO), ())

    def test_any_other_refusal_is_a_failure(self):
        with self.assertRaises(HttpError):
            sponsorblock.fetch(self.Fetcher(error=HttpError(500, "x")), VIDEO)
        with self.assertRaises(RuntimeError):
            sponsorblock.fetch(self.Fetcher(answer=b"<html>"), VIDEO)

    def test_an_answer(self):
        import json
        fetcher = self.Fetcher(answer=json.dumps(ANSWER).encode())
        self.assertEqual(len(sponsorblock.fetch(fetcher, VIDEO)), 2)
        self.assertEqual(len(fetcher.asked), 1)


if __name__ == "__main__":
    unittest.main()
