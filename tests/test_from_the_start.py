"""Starting a running broadcast at the beginning of its rewind window.

What can be reached is not the beginning of the broadcast. It is the playlist
YouTube hands out, measured at fifteen minutes on one stream and an hour on
four others, and the only thing that reaches it is ffmpeg's live_start_index.
Measured against real broadcasts, a backward seek answers success and moves
nothing, --start=0 and --force-seekable change nothing at all, and yt-dlp's
own --live-from-start hands mpv something it cannot open.

That option has to ride with the file, and the wrapper takes a URL and
forwards nothing else, so this path speaks to mpv itself. These tests pin both
halves of that: what is said to a player already running, and what happens
when there is none.
"""

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from weave.config import Config
from weave.player.mpv import REWIND_OPTION, Player


class FakeMpv:
    """A socket that answers to nothing and remembers what it was told."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.said: list[dict] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(path))
        self._server.listen(4)
        self._server.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except (TimeoutError, OSError):
                continue
            with client:
                client.settimeout(2.0)
                buffer = b""
                try:
                    while b"\n" not in buffer:
                        chunk = client.recv(65536)
                        if not chunk:
                            break
                        buffer += chunk
                except (TimeoutError, OSError):
                    continue
                for line in buffer.split(b"\n"):
                    if line.strip():
                        try:
                            self.said.append(json.loads(line))
                        except ValueError:
                            pass

    def close(self) -> None:
        self._stop.set()
        try:
            self._server.close()
        except OSError:
            pass
        self._thread.join(timeout=3)


class Watched(unittest.TestCase):
    """Whatever else happens, nothing started this way is ever marked."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def player(self, socket_path: Path) -> Player:
        return Player(Config(raw={"player": {"ipc_socket": str(socket_path),
                                             "command": "/nonexistent/player"}}))

    def test_a_player_already_running_is_told_to_load_it(self) -> None:
        mpv = FakeMpv(self.home / "mpv.sock")
        self.addCleanup(mpv.close)
        player = self.player(mpv.path)
        self.assertTrue(player.play_from_start("https://example.test/watch"))
        for _ in range(50):
            if len(mpv.said) >= 3:
                break
            import time

            time.sleep(0.05)
        commands = [message.get("command") for message in mpv.said]
        loads = [one for one in commands if one and one[0] == "loadfile"]
        self.assertEqual(len(loads), 1, f"said {commands}")
        self.assertEqual(loads[0][1], "https://example.test/watch")
        self.assertIn("replace", loads[0])

    def test_the_rewind_option_rides_with_the_file(self) -> None:
        """The whole point. Set globally it would outlive the stream; passed
        with the file it applies to that file and nothing after it."""
        mpv = FakeMpv(self.home / "mpv.sock")
        self.addCleanup(mpv.close)
        player = self.player(mpv.path)
        player.play_from_start("https://example.test/watch")
        for _ in range(50):
            if mpv.said:
                break
            import time

            time.sleep(0.05)
        load = next(message["command"] for message in mpv.said
                    if message.get("command", [""])[0] == "loadfile")
        options = next((part for part in load if isinstance(part, dict)), None)
        self.assertIsNotNone(options, f"no options in {load}")
        self.assertEqual(options.get("demuxer-lavf-o"), REWIND_OPTION)

    def test_it_is_unpaused_and_brought_back_into_view(self) -> None:
        """Both follow every load the wrapper sends, for the same reasons:
        pause is a global property and a minimised window hides the stream."""
        mpv = FakeMpv(self.home / "mpv.sock")
        self.addCleanup(mpv.close)
        player = self.player(mpv.path)
        player.play_from_start("https://example.test/watch")
        for _ in range(60):
            if len(mpv.said) >= 3:
                break
            import time

            time.sleep(0.05)
        said = [message.get("command") for message in mpv.said]
        self.assertIn(["set_property", "pause", False], said, str(said))
        self.assertIn(["set_property", "window-minimized", False], said, str(said))

    def test_with_no_player_at_all_it_says_so_rather_than_failing_quietly(self) -> None:
        from weave.player import mpv as player_module

        player = self.player(self.home / "not-there.sock")
        complaints: list[str] = []
        player.failed.connect(complaints.append)
        real = player_module.shutil.which
        player_module.shutil.which = lambda name: None
        try:
            self.assertFalse(player.play_from_start("https://example.test/watch"))
        finally:
            player_module.shutil.which = real
        self.assertEqual(len(complaints), 1, "nothing said why")
        self.assertIn("mpv", complaints[0])

    def test_nothing_started_this_way_is_ever_marked_watched(self) -> None:
        """A broadcast begun an hour behind its edge reads as most of a video
        played, which is exactly what the watched rule would count."""
        mpv = FakeMpv(self.home / "mpv.sock")
        self.addCleanup(mpv.close)
        player = self.player(mpv.path)
        player.play_from_start("https://example.test/watch")
        self.assertTrue(player._watcher._pending_live)

    def test_a_player_that_is_not_there_does_not_raise(self) -> None:
        """The socket file can be left behind by an mpv that has gone."""
        stale = self.home / "stale.sock"
        stale.write_text("")
        player = self.player(stale)
        from weave.player import mpv as player_module

        real = player_module.shutil.which
        player_module.shutil.which = lambda name: None
        try:
            self.assertFalse(player.play_from_start("https://example.test/watch"))
        finally:
            player_module.shutil.which = real


class TheEntryRefusesWhatCannotBeRewound(unittest.TestCase):
    """The menu draws these refused, and the bridge refuses them again."""

    def bridge(self, rows):
        from weave.ui.bridge import Bridge

        bridge = Bridge.__new__(Bridge)
        bridge._model = _Model(rows)
        bridge._player = _Recorder()
        bridge.notices = []
        bridge._set_notice = lambda text, *_a, **_k: bridge.notices.append(text)
        bridge._set_status = lambda *_a, **_k: None
        bridge.started = []
        bridge._set_starting = lambda key, **_k: bridge.started.append(key)
        bridge._step_aside_for_video = lambda: None
        return bridge

    def test_a_twitch_stream_is_refused_and_said_why(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge([_row("twitch:somebody", live=True)])
        Bridge.playFromStart(bridge, "twitch:somebody")
        self.assertEqual(bridge._player.urls, [])
        self.assertTrue(any("Twitch" in text for text in bridge.notices),
                        str(bridge.notices))

    def test_a_recording_is_refused(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge([_row("yt:aaaaaaaaaaa", live=False)])
        Bridge.playFromStart(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge._player.urls, [])

    def test_a_running_broadcast_is_handed_over(self) -> None:
        from weave.ui.bridge import Bridge

        bridge = self.bridge([_row("yt:bbbbbbbbbbb", live=True)])
        Bridge.playFromStart(bridge, "yt:bbbbbbbbbbb")
        self.assertEqual(bridge._player.urls, ["https://example.test/watch"])
        self.assertEqual(bridge.started, ["yt:bbbbbbbbbbb"])

    def test_the_words_do_not_promise_the_beginning(self) -> None:
        """Fifteen minutes to an hour is not a broadcast, and saying it is
        would be a promise the player cannot keep."""
        from weave.ui.bridge import Bridge

        bridge = self.bridge([_row("yt:bbbbbbbbbbb", live=True)])
        Bridge.playFromStart(bridge, "yt:bbbbbbbbbbb")
        said = " ".join(bridge.notices).lower()
        self.assertNotIn("from the beginning", said)
        self.assertIn("holds", said)


def _row(key, live):
    return {"key": key, "title": "Something", "url": "https://example.test/watch",
            "isLive": live, "isUpcoming": False}


class _Model:
    def __init__(self, rows):
        self._rows = {row["key"]: row for row in rows}

    def row_for_key(self, key):
        return self._rows.get(key)


class _Recorder:
    def __init__(self):
        self.urls = []

    def play_from_start(self, url):
        self.urls.append(url)
        return True


if __name__ == "__main__":
    unittest.main()
