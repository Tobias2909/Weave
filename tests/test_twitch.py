"""Twitch parsing and token handling. No network."""

import unittest

from weave.sources import twitch

PAYLOAD = {
    "data": [
        {"user_login": "Alpha", "user_name": "Alpha", "title": "A stream",
         "game_name": "Chess", "viewer_count": 1234, "started_at": "2020-01-02T03:04:05Z",
         "thumbnail_url": "https://x/{width}x{height}.jpg"},
        {"user_login": "beta", "user_name": "Beta"},
        {"user_name": "no login here"},
    ],
    "pagination": {"cursor": "abc"},
}


class ParseStreams(unittest.TestCase):
    def setUp(self):
        self.streams = twitch.parse_streams(PAYLOAD)

    def test_a_row_without_a_login_is_dropped(self):
        # The login is the only field that identifies a channel.
        self.assertEqual([s.login for s in self.streams], ["alpha", "beta"])

    def test_logins_are_lowercased(self):
        # They are used as keys, so case must not create a second channel.
        self.assertEqual(self.streams[0].login, "alpha")
        self.assertEqual(self.streams[0].key, "twitch:alpha")

    def test_fields(self):
        stream = self.streams[0]
        self.assertEqual((stream.display_name, stream.title, stream.game, stream.viewers),
                         ("Alpha", "A stream", "Chess", 1234))

    def test_missing_fields_do_not_drop_the_stream(self):
        stream = self.streams[1]
        self.assertEqual((stream.title, stream.game, stream.viewers), ("", "", 0))

    def test_thumbnail_placeholders_are_filled_in(self):
        # The address comes back with size placeholders and is useless as is.
        self.assertNotIn("{width}", self.streams[0].thumbnail_url)
        self.assertTrue(self.streams[0].thumbnail_url.endswith("440x248.jpg"))

    def test_a_missing_thumbnail_stays_empty(self):
        self.assertEqual(self.streams[1].thumbnail_url, "")

    def test_an_empty_payload_is_no_streams(self):
        self.assertEqual(twitch.parse_streams({}), [])
        self.assertEqual(twitch.parse_streams({"data": []}), [])


class TokenShape(unittest.TestCase):
    def test_round_trip(self):
        original = twitch.Tokens("access", "refresh", 1000)
        restored = twitch.Tokens.from_dict(original.as_dict())
        self.assertEqual((restored.access_token, restored.refresh_token, restored.obtained_at),
                         ("access", "refresh", 1000))

    def test_half_a_login_is_not_a_login(self):
        # A refresh token alone cannot be used, and an access token alone
        # cannot be renewed, so neither counts as being logged in.
        self.assertIsNone(twitch.Tokens.from_dict({"access_token": "a"}))
        self.assertIsNone(twitch.Tokens.from_dict({"refresh_token": "r"}))
        self.assertIsNone(twitch.Tokens.from_dict({}))


class Scopes(unittest.TestCase):
    def test_only_what_is_needed(self):
        # Reading the follow list is the only thing Weave asks permission for.
        self.assertEqual(twitch.SCOPES, "user:read:follows")

    def test_the_device_grant_string(self):
        self.assertEqual(twitch.DEVICE_GRANT,
                         "urn:ietf:params:oauth:grant-type:device_code")


if __name__ == "__main__":
    unittest.main()
