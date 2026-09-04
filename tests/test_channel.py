"""Channel details, and which picture is the banner.

This has its own module because getting the choice wrong does not look like an
error. It looks like the banner failing to load, which sends you looking at the
image cache and the network instead of at the eight entries the channel
returned.
"""

import unittest

from weave.sources.channel import parse_output, pick_images

# The shape a live channel actually returns, measured. Six crops of the banner
# as displayed, the raw artwork with no dimensions at all, a square avatar and
# the uncropped avatar.
REAL = [
    {"id": "0", "width": 1060, "height": 175, "url": "crop/1060"},
    {"id": "2", "width": 1707, "height": 283, "url": "crop/1707"},
    {"id": "5", "width": 2560, "height": 424, "url": "crop/2560"},
    {"id": "banner_uncropped", "url": "artwork/s0"},
    {"id": "7", "width": 900, "height": 900, "url": "avatar/900"},
    {"id": "avatar_uncropped", "url": "avatar/s0"},
]


class PickImages(unittest.TestCase):
    def test_the_banner_is_the_widest_crop_not_the_artwork(self):
        # The crops are about six to one and are what a channel page shows.
        # The uncropped entry is 2560 by 1440, of which only a middle strip is
        # ever displayed, so filling a wide band with it shows a magnified
        # slice of mostly nothing.
        self.assertEqual(pick_images(REAL)[1], "crop/2560")

    def test_the_avatar_is_the_uncropped_one(self):
        # Square either way, so the one without crop parameters is fine.
        self.assertEqual(pick_images(REAL)[0], "avatar/s0")

    def test_the_artwork_is_the_fallback_when_there_are_no_crops(self):
        self.assertEqual(
            pick_images([{"id": "banner_uncropped", "url": "artwork/s0"}])[1], "artwork/s0")

    def test_a_landscape_picture_is_not_a_banner(self):
        # Sixteen to nine is some other image. A banner is about six to one.
        self.assertIsNone(pick_images([{"id": "9", "width": 1920, "height": 1080,
                                        "url": "wide"}])[1])

    def test_the_largest_square_stands_in_for_a_missing_avatar(self):
        self.assertEqual(pick_images([{"id": "6", "width": 176, "height": 176, "url": "small"},
                                      {"id": "7", "width": 900, "height": 900, "url": "big"}])[0],
                         "big")

    def test_nothing_at_all_is_not_an_error(self):
        self.assertEqual(pick_images([]), (None, None))


class ParseOutput(unittest.TestCase):
    def test_title_and_follower_count(self):
        text = 'Example Channel|1580000\n[{"id": "5", "width": 2560, "height": 424, "url": "b"}]'
        details = parse_output(text)
        self.assertEqual((details.title, details.follower_count), ("Example Channel", 1580000))
        self.assertEqual(details.banner_url, "b")

    def test_an_unknown_follower_count_is_none_rather_than_zero(self):
        details = parse_output("Example Channel|NA\n[]")
        self.assertIsNone(details.follower_count)


if __name__ == "__main__":
    unittest.main()
