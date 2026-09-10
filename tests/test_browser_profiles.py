"""Which browser's cookies are used, and how that is chosen.

The list yt-dlp can find by itself is the standard Mozilla directories only,
so every Firefox fork is invisible to it. That is the whole reason this
exists: a machine whose only browser is Zen used to fall through to a Firefox
nobody had opened, and the parts past the plain feed came back empty or with
a FileNotFoundError from a profile path that was never there.
"""

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject

from weave import browsers, cookies
from weave.config import Config
from weave.db import Database
from weave.ui.bridge import Bridge

_app = QCoreApplication.instance() or QCoreApplication([])

SIGNED_IN = ("SID", "__Secure-1PSID", "__Secure-1PSIDTS", "__Secure-3PSIDTS", "PREF")
STALE = ("SID", "__Secure-1PSID")


def make_jar(where: Path, names=SIGNED_IN) -> Path:
    """A profile directory with a cookie jar of the real shape in it."""
    where.mkdir(parents=True, exist_ok=True)
    jar = where / browsers.JAR
    conn = sqlite3.connect(jar)
    with conn:
        conn.execute("CREATE TABLE moz_cookies "
                     "(id INTEGER PRIMARY KEY, host TEXT, name TEXT, value TEXT)")
        conn.executemany("INSERT INTO moz_cookies(host, name, value) VALUES(?, ?, ?)",
                         [(".youtube.com", name, "x") for name in names])
        # A jar carries a great deal that is nothing to do with YouTube, and
        # none of it should be counted or looked at.
        conn.execute("INSERT INTO moz_cookies(host, name, value) "
                     "VALUES('.example.com', 'SID', 'x')")
    conn.close()
    return where


class Finding(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def where(self, family="Zen"):
        return [(family, self.root)]

    def test_a_profile_with_a_jar_is_found_by_its_name_in_the_ini(self):
        make_jar(self.root / "abc.Default (release)")
        (self.root / "profiles.ini").write_text(
            "[Profile0]\nName=Default (release)\nIsRelative=1\n"
            "Path=abc.Default (release)\n")
        found = browsers.found(self.where())
        self.assertEqual([p.name for p in found], ["Default (release)"])
        self.assertEqual(found[0].label, "Zen, Default (release)")
        self.assertTrue(found[0].signed_in)
        self.assertTrue(found[0].fresh)
        # Only the YouTube ones, and the named ones are kept whole.
        self.assertEqual(found[0].count, len(SIGNED_IN))

    def test_a_profile_without_a_jar_is_not_offered(self):
        # It would be picked, and then nothing would work, with the list
        # having said the profile was there.
        (self.root / "profiles.ini").write_text(
            "[Profile0]\nName=Fresh\nIsRelative=1\nPath=abc.Fresh\n")
        (self.root / "abc.Fresh").mkdir()
        self.assertEqual(browsers.found(self.where()), [])

    def test_the_installed_default_wins_over_the_ini_flag(self):
        """MEASURED on a real Zen install: profiles.ini flagged a profile the
        browser had never opened, and installs.ini named the one in use. The
        jar's own age agreed with installs.ini."""
        make_jar(self.root / "aaa.Unused")
        make_jar(self.root / "bbb.Used")
        (self.root / "profiles.ini").write_text(
            "[Profile1]\nName=Unused\nIsRelative=1\nPath=aaa.Unused\nDefault=1\n\n"
            "[Profile0]\nName=Used\nIsRelative=1\nPath=bbb.Used\n")
        (self.root / "installs.ini").write_text(
            "[Install15B76BAA26BA15E7]\nDefault=bbb.Used\nLocked=1\n")
        launched = {p.name: p.launched for p in browsers.found(self.where())}
        self.assertEqual(launched, {"Unused": False, "Used": True})

    def test_an_absolute_path_in_the_ini_is_followed(self):
        elsewhere = Path(self._tmp.name) / "somewhere else"
        make_jar(elsewhere)
        (self.root / "profiles.ini").write_text(
            f"[Profile0]\nName=Moved\nIsRelative=0\nPath={elsewhere}\n")
        self.assertEqual([p.path for p in browsers.found(self.where())], [elsewhere])

    def test_without_an_ini_the_directories_are_read(self):
        make_jar(self.root / "xyz.default")
        self.assertEqual([p.name for p in browsers.found(self.where())], ["xyz.default"])

    def test_the_debugger_profile_is_not_a_profile(self):
        """Firefox writes one inside a real profile for the remote debugger.
        It has a jar with nothing in it and is in no ini."""
        make_jar(self.root / "xyz.default")
        make_jar(self.root / "xyz.default" / "chrome_debugger_profile", names=())
        self.assertEqual([p.name for p in browsers.found(self.where())], ["xyz.default"])

    def test_signed_in_comes_first_then_the_freshest(self):
        make_jar(self.root / "a.out", names=())
        make_jar(self.root / "b.old", names=STALE)
        make_jar(self.root / "c.now")
        order = [p.name for p in browsers.found(self.where())]
        self.assertEqual(order[0], "c.now")
        self.assertEqual(order[-1], "a.out")
        self.assertEqual(browsers.best(self.where()).name, "c.now")

    def test_nothing_signed_in_is_no_answer_rather_than_a_bad_one(self):
        make_jar(self.root / "a.out", names=())
        self.assertIsNone(browsers.best(self.where()))

    def test_a_jar_that_is_not_a_jar_is_said_to_be_unreadable(self):
        (self.root / "broken").mkdir()
        (self.root / "broken" / browsers.JAR).write_text("not a database")
        found = browsers.found(self.where())
        self.assertFalse(found[0].readable)
        self.assertIn("could not be read", found[0].state)

    def test_the_state_says_when_the_browser_last_wrote(self):
        make_jar(self.root / "old.default")
        jar = self.root / "old.default" / browsers.JAR
        long_ago = time.time() - 40 * 86400
        import os

        os.utime(jar, (long_ago, long_ago))
        self.assertEqual(browsers.found(self.where())[0].state, "written 40 days ago")

    def test_a_login_nobody_has_refreshed_says_so(self):
        make_jar(self.root / "stale.default", names=STALE)
        state = browsers.found(self.where())[0].state
        self.assertTrue(state.startswith("signed in but stale"), state)

    def test_a_named_directory_is_read_the_same_way(self):
        make_jar(self.root / "named")
        self.assertTrue(browsers.describe(self.root / "named").signed_in)
        # And one that is not there at all is unreadable rather than a crash.
        self.assertFalse(browsers.describe(self.root / "gone").readable)


class Choosing(unittest.TestCase):
    """The order in weave/cookies.py, which is the only place that knows it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # Nothing picked and no state database read, so a test says which
        # step of the order it is exercising rather than inheriting one.
        cookies.remember("")
        self.addCleanup(cookies.forget)
        self.link = cookies.MPV_PROFILE_LINK
        cookies.MPV_PROFILE_LINK = self.root / "no such link"
        self.addCleanup(self._put_the_link_back)

    def _put_the_link_back(self):
        cookies.MPV_PROFILE_LINK = self.link

    def config(self, profile="auto"):
        return Config(raw={"youtube": {"browser_profile": profile}})

    def test_with_nothing_to_go_on_yt_dlp_is_left_to_look(self):
        # Nothing on this machine either, or the answer would be whichever
        # browser the machine running the test happens to have.
        real = browsers.best
        browsers.best = lambda *_: None
        self.addCleanup(setattr, browsers, "best", real)
        cookies.remember("")
        self.assertEqual(cookies.browser_spec(self.config()), "firefox")
        self.assertIsNone(cookies.profile_path(self.config()))

    def test_a_choice_made_in_the_window_wins(self):
        picked = make_jar(self.root / "picked")
        cookies.remember(str(picked))
        source = cookies.resolve(self.config("~/somewhere/else"))
        self.assertEqual(source.spec, f"firefox:{picked}")
        self.assertEqual(source.origin, "picked here")

    def test_a_choice_that_has_gone_says_so_rather_than_moving_on(self):
        cookies.remember(str(self.root / "unplugged"))
        source = cookies.resolve(self.config())
        self.assertIn("now missing", source.origin)

    def test_the_config_path_is_expanded(self):
        # yt-dlp calls abspath on this argument and never expanduser, so a
        # tilde reaches it as a directory called "~".
        written = make_jar(self.root / "from the file")
        source = cookies.resolve(self.config(str(written)))
        self.assertEqual(source.spec, f"firefox:{written}")
        self.assertEqual(source.origin, "config.toml")

    def test_a_browser_name_in_the_config_is_handed_over_as_written(self):
        source = cookies.resolve(self.config("chrome"))
        self.assertEqual(source.spec, "chrome")
        self.assertIsNone(source.path)

    def test_the_mpv_link_is_used_when_it_is_there(self):
        cookies.MPV_PROFILE_LINK = make_jar(self.root / "mpv")
        source = cookies.resolve(self.config())
        self.assertEqual(source.origin, "the mpv profile link")

    def test_otherwise_a_signed_in_profile_on_this_machine_is_found(self):
        found = make_jar(self.root / "zen")
        profile = browsers.describe(found, "Zen")
        real = browsers.best
        browsers.best = lambda *_: profile
        self.addCleanup(setattr, browsers, "best", real)
        cookies.forget()
        cookies.remember("")
        source = cookies.resolve(self.config())
        self.assertEqual(source.path, found)
        self.assertTrue(source.origin.startswith("found, Zen"))

    def test_the_answer_is_worked_out_once(self):
        # Finding profiles copies every jar on the machine, and the argument
        # is built for every yt-dlp call there is.
        counted = []
        real = browsers.best
        browsers.best = lambda *_: counted.append(1)
        self.addCleanup(setattr, browsers, "best", real)
        cfg = self.config()
        for _ in range(5):
            cookies.browser_spec(cfg)
        self.assertEqual(len(counted), 1)
        cookies.remember("")
        cookies.browser_spec(cfg)
        self.assertEqual(len(counted), 2)

    def test_the_argument_is_the_one_yt_dlp_takes(self):
        cookies.remember(str(make_jar(self.root / "p")))
        self.assertEqual(cookies.args(self.config())[0], "--cookies-from-browser")


class Picking(unittest.TestCase):
    """The settings page and the wizard end of it, which is the same slot."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(self.root / "t.db")
        self.addCleanup(self.db.close)
        cookies.remember("")
        self.addCleanup(cookies.forget)
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._db = self.db
        self.bridge._cfg = Config(raw={})
        self.bridge._shelves = ["stale"]
        self.bridge._cookie_profiles = [
            browsers.describe(make_jar(self.root / "zen"), "Zen"),
            browsers.describe(make_jar(self.root / "fox", names=()), "Firefox"),
        ]
        self.said = []
        self.bridge._set_status = self.said.append
        # The window would read this machine's browsers. The two above are
        # the ones this case is about.
        real = browsers.found
        browsers.found = lambda *_: self.bridge._cookie_profiles or []
        self.addCleanup(setattr, browsers, "found", real)

    def test_automatic_is_offered_first_and_is_what_holds(self):
        offered = Bridge.cookieChoices.fget(self.bridge)
        self.assertEqual(offered[0]["path"], "")
        self.assertEqual(offered[0]["label"], "Automatic")
        self.assertTrue(offered[0]["current"])
        self.assertEqual(Bridge.cookieChoice.fget(self.bridge), "Automatic")

    def test_every_profile_found_is_offered_with_what_is_wrong_with_it(self):
        offered = Bridge.cookieChoices.fget(self.bridge)
        self.assertEqual([row["label"] for row in offered[1:]],
                         ["Zen, zen", "Firefox, fox"])
        self.assertEqual(offered[2]["state"], "not signed in to YouTube")

    def test_picking_one_is_stored_and_takes_effect_at_once(self):
        Bridge.setCookieProfile(self.bridge, str(self.root / "zen"))
        self.assertEqual(self.db.browser_profile(), str(self.root / "zen"))
        self.assertEqual(cookies.chosen(), str(self.root / "zen"))
        self.assertEqual(cookies.browser_spec(self.bridge._cfg),
                         f"firefox:{self.root / 'zen'}")
        self.assertEqual(Bridge.cookieChoice.fget(self.bridge), "Zen, zen")
        self.assertTrue(self.said)

    def test_the_shelves_are_dropped_because_they_were_somebody_else_s(self):
        # A different profile can be a different account, and the music view
        # holds what the last one saw.
        Bridge.setCookieProfile(self.bridge, str(self.root / "zen"))
        self.assertEqual(self.bridge._shelves, [])

    def test_picking_automatic_again_undoes_it(self):
        Bridge.setCookieProfile(self.bridge, str(self.root / "zen"))
        Bridge.setCookieProfile(self.bridge, "")
        self.assertEqual(self.db.browser_profile(), "")
        self.assertEqual(cookies.chosen(), "")
        self.assertEqual(Bridge.cookieChoice.fget(self.bridge), "Automatic")

    def test_a_profile_that_is_no_longer_there_is_still_named(self):
        Bridge.setCookieProfile(self.bridge, str(self.root / "gone"))
        self.bridge._cookie_profiles = []
        self.assertEqual(Bridge.cookieChoice.fget(self.bridge), "gone")

    def test_looking_again_drops_what_was_held(self):
        Bridge.refreshCookieProfiles(self.bridge)
        self.assertIsNone(self.bridge._cookie_profiles)
