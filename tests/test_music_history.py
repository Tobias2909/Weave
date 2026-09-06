"""What has been listened to.

Two sources meet in one list. Weave writes a row as it plays a song and knows
exactly when that was, while the music service remembers older listening and
offers only a phrase for when it happened. A song in both is ours.
"""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QObject

from weave.db import Database


class Recording(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "weave.db")

    def test_a_song_is_remembered_as_it_plays(self) -> None:
        self.db.remember_played("aaaaaaaaaaa", "A song", "An artist", "https://x/t.jpg", 203)
        rows = self.db.music_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "A song")
        self.assertEqual(rows[0]["channel_title"], "An artist")
        self.assertEqual(rows[0]["key"], "yt:aaaaaaaaaaa")
        self.assertIsNotNone(rows[0]["published_at"])

    def test_playing_it_again_counts_rather_than_repeats(self) -> None:
        for _ in range(3):
            self.db.remember_played("aaaaaaaaaaa", "A song", "An artist", None)
        self.assertEqual(self.db.music_history_count(), 1)
        plays = self.db.conn.execute(
            "SELECT plays FROM music_history WHERE ext_id='aaaaaaaaaaa'").fetchone()[0]
        self.assertEqual(plays, 3)

    def test_the_service_fills_in_older_listening(self) -> None:
        written = self.db.replace_service_music_history([
            {"ext_id": "bbbbbbbbbbb", "title": "Older", "artist": "Someone",
             "played_text": "Last week"}])
        self.assertEqual(written, 1)
        row = self.db.music_history()[0]
        self.assertEqual(row["played_text"], "Last week")
        self.assertIsNone(row["published_at"])

    def test_a_song_played_here_beats_the_service_copy(self) -> None:
        """Our time is exact and the phrase is not, so ours stays."""
        self.db.remember_played("aaaaaaaaaaa", "A song", "An artist", None)
        self.db.replace_service_music_history([
            {"ext_id": "aaaaaaaaaaa", "title": "A song", "artist": "An artist",
             "played_text": "Today"}])
        rows = self.db.music_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "weave")
        self.assertIsNotNone(rows[0]["published_at"])

    def test_reading_the_service_again_replaces_only_its_own_rows(self) -> None:
        self.db.remember_played("aaaaaaaaaaa", "A song", "An artist", None)
        self.db.replace_service_music_history([
            {"ext_id": "bbbbbbbbbbb", "title": "Older", "artist": "Someone"}])
        self.db.replace_service_music_history([
            {"ext_id": "ccccccccccc", "title": "Another", "artist": "Someone"}])
        keys = [row["key"] for row in self.db.music_history()]
        self.assertIn("yt:aaaaaaaaaaa", keys)
        self.assertIn("yt:ccccccccccc", keys)
        self.assertNotIn("yt:bbbbbbbbbbb", keys)

    def test_what_was_played_here_comes_first(self) -> None:
        self.db.replace_service_music_history([
            {"ext_id": "bbbbbbbbbbb", "title": "Older", "artist": "Someone"}])
        self.db.remember_played("aaaaaaaaaaa", "A song", "An artist", None)
        self.assertEqual([row["key"] for row in self.db.music_history()],
                         ["yt:aaaaaaaaaaa", "yt:bbbbbbbbbbb"])

    def test_a_row_without_an_id_is_dropped_rather_than_stored(self) -> None:
        self.assertEqual(self.db.replace_service_music_history(
            [{"ext_id": "", "title": "Nameless"}]), 0)
        self.assertEqual(self.db.music_history_count(), 0)


class PlayingRecordsIt(unittest.TestCase):
    """The player writes the row itself, as the song starts."""

    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "weave.db")

    def player(self):
        from weave.audio import AudioPlayer

        player = AudioPlayer.__new__(AudioPlayer)
        player._db = self.db
        return player

    def test_a_song_starting_is_written(self) -> None:
        from weave.audio import AudioPlayer

        AudioPlayer._remember(self.player(), {
            "key": "yt:aaaaaaaaaaa", "title": "A song", "artist": "An artist",
            "thumbnail": "https://x/t.jpg", "live": False})
        self.assertEqual(self.db.music_history_count(), 1)

    def test_a_stream_is_not_a_song(self) -> None:
        from weave.audio import AudioPlayer

        AudioPlayer._remember(self.player(), {
            "key": "yt:aaaaaaaaaaa", "title": "A radio", "live": True})
        self.assertEqual(self.db.music_history_count(), 0)

    def test_something_with_no_youtube_id_is_left_out(self) -> None:
        from weave.audio import AudioPlayer

        AudioPlayer._remember(self.player(), {
            "key": "https://example/stream.mp3", "title": "A file", "live": False})
        self.assertEqual(self.db.music_history_count(), 0)


class TheHistoryView(unittest.TestCase):
    """The one view answers whichever question it was asked."""

    def bridge(self, music: bool):
        from weave.ui.bridge import Bridge

        db = Database(Path(tempfile.mkdtemp()) / "weave.db")
        db.remember_played("aaaaaaaaaaa", "A song", "An artist", None)

        class Model:
            def __init__(self):
                self.shown = None

            def show(self, rows):
                self.shown = list(rows)

            def row_for_key(self, key):
                return {"key": key, "title": "A song", "url": "https://example/watch",
                        "isLive": False, "isUpcoming": False}

        class Player:
            def __init__(self):
                self.calls = []

            def play(self, url, twitch_login=None, live=False):
                self.calls.append(url)
                return True

        # The C++ half has to exist before a signal can be emitted on it,
        # and the constructor proper wants a window's worth of arguments.
        bridge = Bridge.__new__(Bridge)
        QObject.__init__(bridge)
        bridge._db = db
        bridge._model = Model()
        bridge._player = Player()
        bridge._view_kind = "history"
        bridge._view_playlist = ""
        bridge._history_music = music
        bridge._set_status = lambda *a, **k: None
        bridge._set_notice = lambda *a, **k: None
        bridge.listened = []
        bridge.playAudio = bridge.listened.append
        return bridge

    def test_the_music_side_draws_what_was_listened_to(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(True)
        Bridge.reload(bridge)
        self.assertEqual(len(bridge._model.shown), 1)
        self.assertEqual(bridge._model.shown[0]["title"], "A song")

    def test_a_song_in_the_history_is_listened_to_not_watched(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(True)
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.listened, ["yt:aaaaaaaaaaa"])
        self.assertEqual(bridge._player.calls, [])

    def test_a_video_in_the_history_still_goes_to_mpv(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge(False)
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.listened, [])
        self.assertEqual(len(bridge._player.calls), 1)


if __name__ == "__main__":
    unittest.main()
