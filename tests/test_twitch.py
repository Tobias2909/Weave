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


class _Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = ""

    def json(self):
        return self._body


class _Session:
    """Answers the two addresses the client uses, and counts what was asked."""

    def __init__(self, answers):
        self.answers = answers          # url fragment -> list of responses
        self.asked = []

    def _take(self, url):
        self.asked.append(url)
        for fragment, queue in self.answers.items():
            if fragment in url:
                return queue.pop(0) if len(queue) > 1 else queue[0]
        raise AssertionError(f"nothing set up for {url}")

    def get(self, url, **_kwargs):
        return self._take(url)

    def post(self, url, **_kwargs):
        return self._take(url)


class ExpiredAccessToken(unittest.TestCase):
    """An access token lasts hours and a refresh token lasts months, so an
    expired one has to be renewed rather than turned into a fresh login.

    This is the whole difference between logging in twice a day and twice a
    year, and it went wrong because the first call a live check makes did not
    go through the path that knows how to refresh.
    """

    def client(self, session, saved):
        return twitch.Client("cid", twitch.Tokens("old-access", "the-refresh"),
                             on_tokens=saved.append, session=session)

    def test_account_id_renews_an_expired_token_rather_than_asking_to_log_in(self):
        saved = []
        session = _Session({
            "validate": [_Response(401, {"message": "invalid access token"}),
                         _Response(200, {"user_id": "12345"})],
            "oauth2/token": [_Response(200, {"access_token": "new-access",
                                             "refresh_token": "new-refresh"})],
        })
        client = self.client(session, saved)
        self.assertEqual(client.account_id(), "12345")
        self.assertEqual(client.tokens.access_token, "new-access")

    def test_and_the_renewed_pair_is_stored(self):
        # Twitch hands back a new refresh token as well. Losing it would mean
        # the next renewal fails and the login really is gone.
        saved = []
        session = _Session({
            "validate": [_Response(401, {}), _Response(200, {"user_id": "1"})],
            "oauth2/token": [_Response(200, {"access_token": "new-access",
                                             "refresh_token": "new-refresh"})],
        })
        self.client(session, saved).account_id()
        self.assertEqual([(t.access_token, t.refresh_token) for t in saved],
                         [("new-access", "new-refresh")])

    def test_a_refresh_that_is_also_refused_does_ask_for_a_login(self):
        session = _Session({
            "validate": [_Response(401, {})],
            "oauth2/token": [_Response(400, {"message": "invalid refresh token"})],
        })
        with self.assertRaises(twitch.NeedsLogin):
            self.client(session, []).account_id()

    def test_it_does_not_loop_when_the_new_token_is_refused_too(self):
        session = _Session({
            "validate": [_Response(401, {}), _Response(401, {})],
            "oauth2/token": [_Response(200, {"access_token": "new", "refresh_token": "r"})],
        })
        with self.assertRaises(twitch.NeedsLogin):
            self.client(session, []).account_id()
        self.assertEqual(sum(1 for url in session.asked if "oauth2/token" in url), 1)

    def test_with_no_refresh_token_there_is_nothing_to_renew(self):
        session = _Session({"validate": [_Response(401, {})]})
        client = twitch.Client("cid", twitch.Tokens("old", ""), session=session)
        with self.assertRaises(twitch.NeedsLogin):
            client.account_id()


class _Refusing:
    """A session with no network behind it."""

    def __init__(self, exc):
        self._exc = exc

    def get(self, *_a, **_k):
        raise self._exc

    def post(self, *_a, **_k):
        raise self._exc


class _Garbled(_Response):
    def json(self):
        raise ValueError("not json")


class WhenTheNetworkIsAway(unittest.TestCase):
    """A connection that is refused or that times out used to escape as the
    requests library's own exception, which nothing above here catches by
    name, so a login attempted while offline took the whole worker with it.
    Every call names its failure as this module's own now."""

    def setUp(self):
        import requests

        self.gone = _Refusing(requests.ConnectionError("no route"))

    def test_starting_the_login(self):
        with self.assertRaises(twitch.TwitchError) as caught:
            twitch.start_login("cid", session=self.gone)
        self.assertIn("could not reach Twitch", str(caught.exception))

    def test_waiting_for_the_approval(self):
        with self.assertRaises(twitch.TwitchError):
            twitch.poll_login("cid", "code", session=self.gone)

    def test_renewing(self):
        with self.assertRaises(twitch.TwitchError):
            twitch.refresh("cid", "refresh", session=self.gone)

    def test_checking_the_login(self):
        with self.assertRaises(twitch.TwitchError):
            twitch.validate("token", session=self.gone)

    def test_a_helix_call(self):
        client = twitch.Client("cid", twitch.Tokens("a", "r"), session=self.gone)
        with self.assertRaises(twitch.TwitchError):
            client.followed_streams("1")

    def test_but_it_is_never_mistaken_for_a_lost_login(self):
        # Offline is not logged out. Asking to log in again would throw away a
        # login that is perfectly good the moment the network is back.
        client = twitch.Client("cid", twitch.Tokens("a", "r"), session=self.gone)
        with self.assertRaises(twitch.TwitchError) as caught:
            client.account_id()
        self.assertNotIsInstance(caught.exception, twitch.NeedsLogin)


class WhenTwitchAnswersNonsense(unittest.TestCase):
    def test_a_body_that_is_not_json(self):
        session = _Session({"device": [_Garbled(200)]})
        with self.assertRaises(twitch.TwitchError):
            twitch.start_login("cid", session=session)

    def test_a_login_answer_with_no_code_in_it(self):
        session = _Session({"device": [_Response(200, {"interval": 5})]})
        with self.assertRaises(twitch.TwitchError) as caught:
            twitch.start_login("cid", session=session)
        self.assertNotIsInstance(caught.exception, KeyError)

    def test_an_approval_with_no_token_in_it(self):
        session = _Session({"oauth2/token": [_Response(200, {"scope": []})]})
        with self.assertRaises(twitch.TwitchError):
            twitch.poll_login("cid", "code", session=session)

    def test_a_body_that_is_a_list(self):
        session = _Session({"validate": [_Response(200, ["not", "a", "map"])]})
        with self.assertRaises(twitch.TwitchError):
            twitch.validate("token", session=session)

    def test_a_good_answer_still_goes_through(self):
        session = _Session({"device": [_Response(200, {
            "device_code": "d", "user_code": "U", "verification_uri": "https://t/x"})]})
        login = twitch.start_login("cid", session=session)
        self.assertEqual((login.device_code, login.user_code), ("d", "U"))


class Scopes(unittest.TestCase):
    def test_only_what_is_needed(self):
        # Reading the follow list is the only thing Weave asks permission for.
        self.assertEqual(twitch.SCOPES, "user:read:follows")

    def test_the_device_grant_string(self):
        self.assertEqual(twitch.DEVICE_GRANT,
                         "urn:ietf:params:oauth:grant-type:device_code")


if __name__ == "__main__":
    unittest.main()
