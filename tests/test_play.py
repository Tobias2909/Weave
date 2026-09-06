"""Handing a video to mpv.

An announced stream sits in the feed like any other video but has nothing
mpv can open yet, so pressing it must never reach the player. This pins that
refusal down, and that a video which is not announced still plays normally.
"""

import unittest


def upcoming_row(key="yt:aaaaaaaaaaa"):
    return {
        "key": key, "title": "An announced stream", "url": "https://example/watch",
        "isLive": False, "isUpcoming": True, "scheduledText": "Starts in 1 hour",
    }


def ordinary_row(key="yt:bbbbbbbbbbb"):
    return {
        "key": key, "title": "A video", "url": "https://example/watch",
        "isLive": False, "isUpcoming": False, "scheduledText": "",
    }


class Model:
    def __init__(self, rows):
        self._rows = {row["key"]: row for row in rows}

    def row_for_key(self, key):
        return self._rows.get(key)


class Player:
    def __init__(self):
        self.calls = []

    def play(self, url, twitch_login=None, live=False):
        self.calls.append((url, twitch_login, live))
        return True


def make_bridge(rows):
    from weave.ui.bridge import Bridge

    bridge = Bridge.__new__(Bridge)
    bridge._model = Model(rows)
    bridge._player = Player()
    bridge._view_kind = "all"
    bridge._view_playlist = ""
    bridge._set_status = lambda *_a, **_k: None
    bridge._set_notice = lambda *_a, **_k: None
    bridge.opened = []
    bridge.openDetail = bridge.opened.append
    return bridge


class PlayRefusesAnAnnouncedVideo(unittest.TestCase):
    def test_an_upcoming_video_never_reaches_mpv(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([upcoming_row()])
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge._player.calls, [],
                          "an announced stream was handed to mpv, which cannot open it")

    def test_it_opens_the_detail_panel_instead(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([upcoming_row()])
        Bridge.play(bridge, "yt:aaaaaaaaaaa")
        self.assertEqual(bridge.opened, ["yt:aaaaaaaaaaa"])

    def test_an_ordinary_video_still_plays(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([ordinary_row()])
        Bridge.play(bridge, "yt:bbbbbbbbbbb")
        self.assertEqual(bridge._player.calls, [("https://example/watch", None, False)])
        self.assertEqual(bridge.opened, [])

    def test_an_unknown_key_does_nothing(self):
        from weave.ui.bridge import Bridge

        bridge = make_bridge([])
        Bridge.play(bridge, "yt:missing")
        self.assertEqual(bridge._player.calls, [])
        self.assertEqual(bridge.opened, [])


if __name__ == "__main__":
    unittest.main()
