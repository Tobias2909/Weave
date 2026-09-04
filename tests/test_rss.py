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
  <yt:playlistId>UULFabcdefghijklmnopqrstuv</yt:playlistId>
  <yt:channelId>UCabcdefghijklmnopqrstuv</yt:channelId>
  <title>Videos</title>
  <author>
    <name>Example Channel</name>
    <uri>https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv</uri>
  </author>
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


# The mixed channel feed, which publishes its own channel id with the UC
# prefix stripped off and has no playlist id. Measured against the live
# endpoint, and the reason identity is read from the author block instead.
CHANNEL_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <yt:channelId>abcdefghijklmnopqrstuv</yt:channelId>
  <title>Example Channel</title>
  <author>
    <name>Example Channel</name>
    <uri>https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv</uri>
  </author>
  <entry>
    <yt:videoId>aaaaaaaaaaa</yt:videoId>
    <yt:channelId>UCabcdefghijklmnopqrstuv</yt:channelId>
    <title>Mixed feed entry</title>
    <published>2020-01-02T03:04:05+00:00</published>
  </entry>
</feed>
"""


class Addresses(unittest.TestCase):
    """A channel has one feed per tab, reached by rewriting the UC prefix of
    its id into the playlist behind that tab."""

    def test_one_playlist_per_tab(self):
        channel = "UCabcdefghijklmnopqrstuv"
        self.assertEqual(rss.playlist_id(channel, rss.VIDEOS), "UULFabcdefghijklmnopqrstuv")
        self.assertEqual(rss.playlist_id(channel, rss.SHORTS), "UUSHabcdefghijklmnopqrstuv")
        self.assertEqual(rss.playlist_id(channel, rss.LIVE), "UULVabcdefghijklmnopqrstuv")

    def test_the_videos_tab_is_the_default_address(self):
        self.assertEqual(
            rss.feed_url("UCabcdefghijklmnopqrstuv"),
            "https://www.youtube.com/feeds/videos.xml?playlist_id=UULFabcdefghijklmnopqrstuv")

    def test_the_mixed_feed_is_addressed_by_channel(self):
        self.assertEqual(
            rss.feed_url("UCabcdefghijklmnopqrstuv", rss.CHANNEL),
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv")


class Kinds(unittest.TestCase):
    """Which tab a feed came from is what a video's kind is, so nothing has to
    be classified after the fact."""

    def test_the_videos_feed_yields_long_form(self):
        self.assertEqual(rss.parse(FEED, rss.VIDEOS).videos[0].is_short, False)

    def test_the_shorts_feed_yields_shorts(self):
        self.assertEqual(rss.parse(FEED, rss.SHORTS).videos[0].is_short, True)

    def test_the_mixed_feed_says_nothing(self):
        self.assertIsNone(rss.parse(CHANNEL_FEED, rss.CHANNEL).videos[0].is_short)


class Identity(unittest.TestCase):
    def test_the_playlist_feed_titles_the_tab_not_the_channel(self):
        # <title> here is "Videos". Taking it would rename every channel.
        result = rss.parse(FEED, rss.VIDEOS)
        self.assertEqual(result.channel_title, "Example Channel")

    def test_the_mixed_feed_publishes_a_truncated_channel_id(self):
        # Its root yt:channelId has no UC prefix. Using it would key every
        # video to a channel that does not exist.
        result = rss.parse(CHANNEL_FEED, rss.CHANNEL)
        self.assertEqual(result.channel_id, "UCabcdefghijklmnopqrstuv")
        self.assertEqual(result.videos[0].channel_key, "yt:UCabcdefghijklmnopqrstuv")


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
