"""Telling YouTube Music which songs were heard.

The one write Weave can make to an account, so it is off until it is switched
on, and a copy that has never been told otherwise writes nothing at all.
"""

import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QObject

from tests.support import scratch_db
from weave.config import Config
from weave.sources import ytmusic
from weave.ui.bridge import Bridge

_app = QCoreApplication.instance() or QCoreApplication([])


def bridge_for(case):
    made = Bridge.__new__(Bridge)
    QObject.__init__(made)
    made._db = scratch_db(case)
    made._cfg = Config(raw={})
    made._listen_reporter = None
    made._heard_waiting = []
    made.launched = []
    made._launch = lambda worker: made.launched.append(worker) or True
    made.statuses = []
    made._set_status = lambda text, *_a, **_k: made.statuses.append(text)
    return made


class TheSwitch(unittest.TestCase):
    def test_it_is_off_until_switched_on(self):
        made = bridge_for(self)
        self.assertFalse(Bridge._get_report_listens(made))
        Bridge._on_song_heard(made, {"key": "yt:aaaaaaaaaaa"})
        self.assertEqual(made.launched, [], "a song was told with the switch off")

    def test_on_a_heard_song_is_told(self):
        from weave.poller import ListenReporter

        made = bridge_for(self)
        Bridge.setReportListens(made, True)
        Bridge._on_song_heard(made, {"key": "yt:aaaaaaaaaaa"})
        self.assertEqual([type(one) for one in made.launched], [ListenReporter])
        self.assertEqual(made.launched[0]._ext_id, "aaaaaaaaaaa")

    def test_one_at_a_time_and_the_rest_wait(self):
        made = bridge_for(self)
        Bridge.setReportListens(made, True)

        class Running:
            def isRunning(self):
                return True

        made._listen_reporter = Running()
        Bridge._on_song_heard(made, {"key": "yt:aaaaaaaaaaa"})
        Bridge._on_song_heard(made, {"key": "yt:bbbbbbbbbbb"})
        self.assertEqual(made.launched, [])
        self.assertEqual(made._heard_waiting, ["aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_switching_it_off_forgets_what_was_waiting(self):
        made = bridge_for(self)
        Bridge.setReportListens(made, True)
        made._heard_waiting = ["aaaaaaaaaaa"]
        Bridge.setReportListens(made, False)
        self.assertEqual(made._heard_waiting, [])

    def test_a_stream_or_a_twitch_key_is_not_a_song(self):
        made = bridge_for(self)
        Bridge.setReportListens(made, True)
        Bridge._on_song_heard(made, {"key": "twitch:someone"})
        self.assertEqual(made.launched, [])


class TheNoteItself(unittest.TestCase):
    """The song is asked for, which hands back an address for exactly this,
    and that address is visited once, through the same client."""

    def fake(self, tracking=True, status=204):
        calls = []

        class Answer:
            status_code = status

        class Client:
            def get_song(self, video_id):
                calls.append(("song", video_id))
                return {"playbackTracking": {"videostatsPlaybackUrl": {
                    "baseUrl": "https://s.youtube.test/api/stats/playback?docid=x"}}
                        } if tracking else {}

            def add_history_item(self, song):
                calls.append(("history", bool(song)))
                return Answer()

        return Client(), calls

    def test_the_song_and_then_the_history(self):
        client, calls = self.fake()
        with mock.patch.object(ytmusic, "client", lambda _profile: client):
            ytmusic.report_heard(None, "aaaaaaaaaaa")
        self.assertEqual(calls, [("song", "aaaaaaaaaaa"), ("history", True)])

    def test_nothing_to_note_it_with_is_said(self):
        client, calls = self.fake(tracking=False)
        with mock.patch.object(ytmusic, "client", lambda _profile: client), \
                self.assertRaises(ytmusic.MusicError):
            ytmusic.report_heard(None, "aaaaaaaaaaa")
        self.assertEqual(calls, [("song", "aaaaaaaaaaa")], "visited with nothing to visit")

    def test_a_refusal_is_said(self):
        client, _calls = self.fake(status=403)
        with mock.patch.object(ytmusic, "client", lambda _profile: client), \
                self.assertRaises(ytmusic.MusicError):
            ytmusic.report_heard(None, "aaaaaaaaaaa")


if __name__ == "__main__":
    unittest.main()
