"""Parsing what ytmusicapi hands back.

A station spells its picture list and its length differently from everything
else the library returns. A song from a search, a playlist or a home shelf
carries `thumbnails` and `duration`; a song from a station carries the same
two things under `thumbnail` and `length`. Missing the second spelling is
what left a station with no pictures and no length anywhere it was shown.
"""

import unittest

from weave.sources.ytmusic import _thumb, to_track

PICTURES = [{"url": "https://i/small.jpg"}, {"url": "https://i/large.jpg"}]

# Shaped as a search result, a playlist entry, or a home shelf entry: the
# picture list is `thumbnails` and the length is `duration`.
SEARCH_SHAPED = {
    "videoId": "abc123", "title": "A song", "artists": [{"name": "Someone"}],
    "album": {"name": "An album"}, "duration": "3:07", "thumbnails": PICTURES,
}

# Shaped as a row of a station built from `get_watch_playlist`: the same
# picture list under `thumbnail`, and the length under `length`.
STATION_SHAPED = {
    "videoId": "xyz789", "title": "Another song", "artists": [{"name": "Someone else"}],
    "album": {"name": "Another album"}, "length": "4:12", "thumbnail": PICTURES,
}


class ThePicture(unittest.TestCase):
    def test_a_search_shaped_entry_reads_thumbnails(self):
        self.assertEqual(_thumb(SEARCH_SHAPED), "https://i/large.jpg")

    def test_a_station_shaped_entry_reads_thumbnail(self):
        self.assertEqual(_thumb(STATION_SHAPED), "https://i/large.jpg")

    def test_neither_spelling_is_an_empty_picture(self):
        self.assertEqual(_thumb({"videoId": "v"}), "")

    def test_an_empty_list_under_either_spelling_is_no_picture(self):
        self.assertEqual(_thumb({"thumbnails": []}), "")
        self.assertEqual(_thumb({"thumbnail": []}), "")

    def test_a_picture_list_that_is_not_a_list_is_no_picture(self):
        self.assertEqual(_thumb({"thumbnail": "not a list"}), "")

    def test_an_entry_in_the_list_that_is_not_a_mapping_is_no_picture(self):
        self.assertEqual(_thumb({"thumbnail": ["not a mapping"]}), "")


class TheLength(unittest.TestCase):
    def test_a_search_shaped_entry_reads_duration(self):
        self.assertEqual(to_track(SEARCH_SHAPED).duration, "3:07")

    def test_a_station_shaped_entry_reads_length(self):
        self.assertEqual(to_track(STATION_SHAPED).duration, "4:12")

    def test_duration_is_read_before_length_when_both_are_there(self):
        both = dict(STATION_SHAPED, duration="9:99")
        self.assertEqual(to_track(both).duration, "9:99")

    def test_neither_spelling_is_an_empty_length(self):
        self.assertEqual(to_track({"videoId": "v"}).duration, "")


class TheWholeTrack(unittest.TestCase):
    def test_a_station_shaped_entry_carries_its_picture_and_length_together(self):
        track = to_track(STATION_SHAPED)
        self.assertEqual(track.video_id, "xyz789")
        self.assertEqual(track.title, "Another song")
        self.assertEqual(track.artist, "Someone else")
        self.assertEqual(track.album, "Another album")
        self.assertEqual(track.duration, "4:12")
        self.assertEqual(track.thumbnail_url, "https://i/large.jpg")

    def test_a_search_shaped_entry_carries_its_picture_and_length_together(self):
        track = to_track(SEARCH_SHAPED)
        self.assertEqual(track.duration, "3:07")
        self.assertEqual(track.thumbnail_url, "https://i/large.jpg")

    def test_an_entry_without_a_video_id_is_not_a_track(self):
        self.assertIsNone(to_track({"title": "No id"}))


if __name__ == "__main__":
    unittest.main()
