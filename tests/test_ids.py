"""Tests are stdlib unittest so they need nothing installed. pytest collects
TestCase classes too, so `python -m unittest` and `pytest` both work."""

import unittest

from weave import ids


class YoutubeVideoId(unittest.TestCase):
    def test_bare_id(self):
        self.assertEqual(ids.youtube_video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_watch_url(self):
        self.assertEqual(
            ids.youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_extra_params_are_dropped(self):
        # The case that broke mpv resume. &t= made it a different video, because
        # mpv names its resume file after the exact URL string it was handed.
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90s&list=PLabc&index=3&si=xyz"
        self.assertEqual(ids.youtube_video_id(url), "dQw4w9WgXcQ")

    def test_youtu_be(self):
        self.assertEqual(ids.youtube_video_id("https://youtu.be/dQw4w9WgXcQ?t=12"), "dQw4w9WgXcQ")

    def test_live_embed_shorts_v(self):
        for segment in ("live", "embed", "shorts", "v"):
            with self.subTest(segment=segment):
                url = f"https://www.youtube.com/{segment}/dQw4w9WgXcQ"
                self.assertEqual(ids.youtube_video_id(url), "dQw4w9WgXcQ")

    def test_music_host(self):
        self.assertEqual(
            ids.youtube_video_id("https://music.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_missing_scheme(self):
        self.assertEqual(ids.youtube_video_id("youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_rejects_radio_playlist_id(self):
        # The recommendation feed returns these. They are playlist ids, not videos.
        self.assertIsNone(ids.youtube_video_id("RDor6VC0FkOOw"))

    def test_rejects_channel_url(self):
        self.assertIsNone(ids.youtube_video_id("https://www.youtube.com/@examplechannel"))

    def test_rejects_junk(self):
        for bad in ("", "   ", "not-an-id", "https://example.com/watch?v=dQw4w9WgXcQ"):
            with self.subTest(bad=bad):
                self.assertIsNone(ids.youtube_video_id(bad))


class TwitchLogin(unittest.TestCase):
    def test_url(self):
        self.assertEqual(ids.twitch_login("https://www.twitch.tv/examplechannel"), "examplechannel")

    def test_missing_scheme_and_mixed_case(self):
        self.assertEqual(ids.twitch_login("twitch.tv/ExampleChannel"), "examplechannel")

    def test_bare_login(self):
        self.assertEqual(ids.twitch_login("examplechannel"), "examplechannel")

    def test_rejects_other_host(self):
        self.assertIsNone(ids.twitch_login("https://youtube.com/examplechannel"))


class ParseChannelRef(unittest.TestCase):
    def test_uc_id(self):
        ref = ids.parse_channel_ref("UCabcdefghijklmnopqrstuv")
        self.assertEqual((ref.platform, ref.kind, ref.value),
                         ("youtube", "id", "UCabcdefghijklmnopqrstuv"))

    def test_channel_url(self):
        ref = ids.parse_channel_ref("https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv")
        self.assertEqual(ref.kind, "id")

    def test_handle_url_still_needs_resolving(self):
        ref = ids.parse_channel_ref("https://www.youtube.com/@examplechannel")
        self.assertEqual((ref.platform, ref.kind, ref.value),
                         ("youtube", "handle", "@examplechannel"))

    def test_bare_handle(self):
        self.assertEqual(ids.parse_channel_ref("@examplechannel").kind, "handle")

    def test_legacy_user_url(self):
        ref = ids.parse_channel_ref("https://www.youtube.com/user/somebody")
        self.assertEqual((ref.kind, ref.value), ("handle", "somebody"))

    def test_twitch_url(self):
        ref = ids.parse_channel_ref("https://twitch.tv/ExampleChannel")
        self.assertEqual((ref.platform, ref.kind, ref.value), ("twitch", "id", "examplechannel"))

    def test_bare_word_is_rejected(self):
        # Ambiguous between a Twitch login and a YouTube name, and guessing
        # would turn a typo into a tracked channel. Search resolves names.
        self.assertIsNone(ids.parse_channel_ref("examplechannel"))
        self.assertIsNone(ids.parse_channel_ref("notarealref"))

    def test_junk(self):
        self.assertIsNone(ids.parse_channel_ref(""))
        self.assertIsNone(ids.parse_channel_ref("https://example.com/"))


class KeyForMediaPath(unittest.TestCase):
    def test_youtube(self):
        self.assertEqual(
            ids.key_for_media_path("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "yt:dQw4w9WgXcQ",
        )

    def test_twitch_m3u8_needs_the_hint(self):
        # The resolved playlist names the channel nowhere, so the caller passes
        # the login it handed to mpv itself.
        m3u8 = "https://video-weaver.ham02.hls.ttvnw.net/v1/playlist/blob.m3u8"
        self.assertIsNone(ids.key_for_media_path(m3u8))
        self.assertEqual(ids.key_for_media_path(m3u8, twitch_hint="examplechannel"), "twitch:examplechannel")

    def test_local_file_has_no_key(self):
        self.assertIsNone(ids.key_for_media_path("/home/user/video.mkv"))


if __name__ == "__main__":
    unittest.main()
