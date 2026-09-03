"""RSS parser tests.

The fixture is synthetic on purpose. It exercises the shapes that actually vary
in the wild, including entries with missing pieces, without committing a
capture of anyone's real feed.
"""

import unittest

from weave.sources import rss

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <yt:channelId>UCabcdefghijklmnopqrstuv</yt:channelId>
  <title>Example Channel</title>
  <published>2019-12-31T00:00:00+00:00</published>
  <entry>
    <id>yt:video:aaaaaaaaaaa</id>
    <yt:videoId>aaaaaaaaaaa</yt:videoId>
    <yt:channelId>UCabcdefghijklmnopqrstuv</yt:channelId>
    <title>Complete entry</title>
    <published>2020-01-02T03:04:05+00:00</published>
    <media:group>
      <media:thumbnail url="https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg" width="480" height="360"/>
      <media:community>
        <media:starRating count="39858" average="5.00" min="1" max="5"/>
        <media:statistics views="2500887"/>
      </media:community>
    </media:group>
  </entry>
  <entry>
    <yt:videoId>bbbbbbbbbbb</yt:videoId>
    <title>No statistics yet, freshly published</title>
    <published>2020-01-03T00:00:00+00:00</published>
    <media:group>
      <media:thumbnail url="https://i.ytimg.com/vi/bbbbbbbbbbb/hqdefault.jpg"/>
    </media:group>
  </entry>
  <entry>
    <yt:videoId>ccccccccccc</yt:videoId>
    <title>No thumbnail and no publish date</title>
  </entry>
  <entry>
    <yt:videoId>RDnotavideoid</yt:videoId>
    <title>Not an eleven character id, must be skipped</title>
  </entry>
  <entry>
    <yt:videoId>ddddddddddd</yt:videoId>
    <title>   </title>
  </entry>
</feed>
"""


class Parse(unittest.TestCase):
    def setUp(self):
        self.result = rss.parse(FEED)

    def test_channel_identity(self):
        self.assertEqual(self.result.channel_id, "UCabcdefghijklmnopqrstuv")
        self.assertEqual(self.result.channel_title, "Example Channel")

    def test_skips_bad_entries(self):
        # The invalid id and the blank title are dropped, the rest survive.
        self.assertEqual([v.ext_id for v in self.result.videos],
                         ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])

    def test_complete_entry(self):
        video = self.result.videos[0]
        self.assertEqual(video.key, "yt:aaaaaaaaaaa")
        self.assertEqual(video.channel_key, "yt:UCabcdefghijklmnopqrstuv")
        self.assertEqual(video.title, "Complete entry")
        self.assertEqual(video.views, 2500887)
        self.assertEqual(video.likes, 39858)      # starRating count, not average
        self.assertTrue(video.thumbnail_url.endswith("hqdefault.jpg"))
        self.assertEqual(video.published_at, 1577934245)

    def test_rss_never_supplies_duration_or_live_status(self):
        # Both come from the subscriptions sweep instead. Asserted so a future
        # change to the parser cannot quietly pretend otherwise.
        for video in self.result.videos:
            self.assertIsNone(video.duration_s)
            self.assertIsNone(video.live_status)

    def test_missing_statistics_are_none_not_zero(self):
        video = self.result.videos[1]
        self.assertIsNone(video.views)
        self.assertIsNone(video.likes)
        self.assertIsNotNone(video.published_at)

    def test_missing_thumbnail_and_date(self):
        video = self.result.videos[2]
        self.assertIsNone(video.thumbnail_url)
        self.assertIsNone(video.published_at)

    def test_channel_inherited_from_feed_level(self):
        # The second entry carries no yt:channelId of its own.
        self.assertEqual(self.result.videos[1].channel_key, "yt:UCabcdefghijklmnopqrstuv")


class Malformed(unittest.TestCase):
    def test_empty_feed_yields_nothing(self):
        xml = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>'
        self.assertEqual(rss.parse(xml).videos, [])


if __name__ == "__main__":
    unittest.main()
