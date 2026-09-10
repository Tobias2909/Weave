"""Take the pictures the README shows, on invented data.

Every name, title, number and picture here is made up in this file. The
window is booted on a scratch home of its own, so nothing of anybody's real
database, cookies or cache is opened, and no request is made. Run from the
repository root:

    python tools/shots.py --out docs/shots

One boot per picture, because a theme is chosen before the window comes up.
The pictures are drawn here as well, gradients rather than photographs, and
put straight into the image cache under the address they pretend to have, so
the cards have artwork with nothing to download.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A scratch home, set before anything of Weave is imported, since the paths
# module reads these once at import time. Shader effects need the hardware
# backend even offscreen, or a masked picture is simply absent.
HOME = Path(os.environ.get("WEAVE_SHOT_HOME") or tempfile.mkdtemp(prefix="weave-shots-"))
for name, part in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"),
                   ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "run")):
    (HOME / part).mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(HOME / part)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "rhi")
os.environ.setdefault("QSG_RHI_BACKEND", "opengl")

from PySide6.QtCore import QCoreApplication, QEventLoop, QMetaObject, QObject, QPointF, QTimer  # noqa: E402
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtQml import QQmlProperty  # noqa: E402

from weave import paths  # noqa: E402
from weave.imagecache import path_for, qml_source  # noqa: E402

WIDTH, HEIGHT = 1500, 940


# ---- helpers ----------------------------------------------------------------

def find(window, name: str):
    if QQmlProperty.read(window, "objectName") == name:
        return window
    return window.findChild(QObject, name)


def read(obj, name: str):
    return QQmlProperty.read(obj, name)


def write(obj, name: str, value) -> None:
    QQmlProperty.write(obj, name, value)


def call(obj, method: str) -> None:
    QMetaObject.invokeMethod(obj, method)


def settle(seconds: float) -> None:
    end = time.monotonic() + seconds
    app = QCoreApplication.instance()
    while time.monotonic() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.005)


# ---- the pictures the cards show --------------------------------------------

PALETTES = (
    ((36, 48, 82), (122, 90, 168)), ((18, 62, 66), (86, 168, 140)),
    ((78, 40, 46), (226, 132, 92)), ((28, 34, 54), (92, 128, 196)),
    ((62, 38, 74), (198, 104, 158)), ((24, 52, 46), (128, 176, 96)),
    ((70, 52, 26), (222, 176, 88)), ((32, 40, 44), (120, 148, 160)),
)


def _picture(width: int, height: int, seed: int) -> QImage:
    """One invented thumbnail. A gradient and a few soft shapes, which reads
    as artwork at card size and cannot be mistaken for anybody's video."""
    rng = random.Random(seed)
    top, bottom = PALETTES[seed % len(PALETTES)]
    image = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, width * 0.4, height)
    gradient.setColorAt(0, QColor(*top))
    gradient.setColorAt(1, QColor(*bottom))
    painter.fillRect(0, 0, width, height, QBrush(gradient))
    painter.setPen(QColor(0, 0, 0, 0))
    for _ in range(3):
        colour = QColor(255, 255, 255, rng.randint(14, 40))
        painter.setBrush(colour)
        radius = rng.uniform(0.2, 0.6) * height
        painter.drawEllipse(QPointF(rng.uniform(0, width), rng.uniform(0, height)),
                            radius, radius)
    for step in range(4):
        painter.setBrush(QColor(0, 0, 0, 18 + step * 6))
        band = height / 9
        painter.drawRect(0, int(height - band * (step + 1)), width, int(band * 0.55))
    painter.end()
    return image


def _avatar(seed: int) -> QImage:
    """A channel picture. Shapes rather than a monogram, because asking a
    painter for text opens the font database, and that is fatal before there
    is an application to own it."""
    rng = random.Random(seed * 977)
    top, bottom = PALETTES[(seed + 3) % len(PALETTES)]
    size = 96
    image = QImage(size, size, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0, QColor(*bottom))
    gradient.setColorAt(1, QColor(*top))
    painter.fillRect(0, 0, size, size, QBrush(gradient))
    painter.setPen(QColor(0, 0, 0, 0))
    painter.setBrush(QColor(255, 255, 255, 46))
    painter.drawEllipse(QPointF(size * rng.uniform(0.2, 0.8), size * rng.uniform(0.2, 0.8)),
                        size * 0.34, size * 0.34)
    painter.setBrush(QColor(255, 255, 255, 150))
    painter.drawEllipse(QPointF(size * 0.5, size * 0.5), size * 0.16, size * 0.16)
    painter.end()
    return image


def cache(url: str, image: QImage) -> str:
    """Put a picture where the cache would have put it, so the window finds it
    on disk and asks nobody for it. Returns the address it now answers for."""
    target = path_for(paths.IMAGE_CACHE, url)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(target), "PNG")
    return url


def thumb(name: str, seed: int, width: int = 480, height: int = 270) -> str:
    return cache(f"https://pictures.invalid/{name}.jpg", _picture(width, height, seed))


def face(name: str, seed: int) -> str:
    return cache(f"https://pictures.invalid/face-{name}.jpg", _avatar(seed))


# ---- the invented account ----------------------------------------------------

DAY = 86400
NOW = int(time.time())

CHANNELS = [
    # name, handle, followers, group
    ("Pixel Forge", "pixelforge", 486_000, "Making things"),
    ("Bench Notes", "benchnotes", 121_500, "Making things"),
    ("Northern Trailhead", "northerntrailhead", 92_300, "Long watches"),
    ("Orbital Mechanics Weekly", "orbitalweekly", 754_000, "Long watches"),
    ("The Slow Kitchen", "slowkitchen", 233_900, "Evenings"),
    ("Lantern Studio", "lanternstudio", 61_200, "Evenings"),
    ("Copper & Coil", "copperandcoil", 38_400, "Making things"),
    ("Field Recordings", "fieldrecordings", 15_800, "Evenings"),
]

VIDEOS = [
    # channel index, title, minutes, views, likes, days old
    (0, "Rebuilding a seized lathe, part four", 41, 184_320, 9_412, 0),
    (3, "Why this orbit needs no fuel at all", 22, 1_204_880, 61_204, 0),
    (2, "Three days on the ridge with one bag", 68, 96_412, 4_880, 1),
    (4, "A loaf that takes two days and no kneading", 17, 412_900, 22_140, 1),
    (1, "The cheap oscilloscope, measured honestly", 34, 74_120, 3_902, 2),
    (5, "Painting light in a room with none", 26, 51_740, 3_128, 2),
    (6, "Winding a transformer by hand", 52, 28_940, 1_744, 3),
    (0, "Every mistake in my first weld", 19, 220_400, 12_880, 4),
    (7, "One microphone, an empty church", 12, 18_220, 1_502, 5),
    (2, "Reading a map when the phone dies", 31, 64_010, 3_204, 6),
    (3, "The launch window nobody uses", 44, 588_120, 29_408, 7),
    (4, "Six sauces from one pan", 23, 176_500, 9_020, 8),
    (0, "A vice that cost nothing", 27, 141_800, 7_640, 9),
    (0, "Sharpening, and how far to go", 15, 98_300, 5_120, 11),
    (0, "The tool wall, two years on", 38, 312_600, 16_400, 13),
    (1, "Cheap calipers against a gauge block", 21, 66_400, 3_310, 14),
]

LIVE = [
    ("quietkeys", "quietkeys", "Factory night shift, no talking", "Factorio", 8_412),
    ("bramblecast", "bramblecast", "Map reading and bad jokes", "Just Chatting", 2_106),
]

TRACKS = [
    ("Hollow Coast", "Mireille Vance", 214),
    ("Paper Lantern", "Bright Static", 189),
    ("Long Way North", "Kite and Anchor", 247),
    ("Static Bloom", "Nocturne Drive", 202),
    ("Harbour Lights", "Mireille Vance", 231),
    ("Second Winter", "Field of Aerials", 268),
    ("Copper Rain", "Bright Static", 176),
    ("Slow Ascent", "Ilma Rook", 295),
    ("Night Ferry", "Kite and Anchor", 208),
    ("Glasshouse", "Nocturne Drive", 223),
    ("Blue Hour", "Ilma Rook", 244),
    ("Tidal", "Field of Aerials", 198),
    ("Winter Grain", "Mireille Vance", 236),
    ("Lamplight", "Bright Static", 187),
]

SHELVES = ("Listen again", "Quick picks", "Covers and remixes", "Long listens")


def track_items(offset: int, count: int) -> list[dict]:
    items = []
    for index in range(count):
        title, artist, _ = TRACKS[(offset + index) % len(TRACKS)]
        items.append({
            "title": title, "subtitle": artist,
            "videoId": f"mocktrack{offset + index:03d}",
            "playlistId": f"RDAMVMmocktrack{offset + index:03d}",
            # A shelf carries the address the service gave it, which the tile
            # asks the cache for. Wrapped here for the same reason.
            "thumbnail": qml_source(thumb(f"track{(offset + index) % 24:02d}",
                                          offset + index + 40, 320, 320)),
        })
    return items


def seed(theme: str, height: int = HEIGHT) -> None:
    """Write the whole invented account into the scratch database."""
    from weave.db import Database, VideoRow

    paths.ensure_dirs()
    db = Database(paths.DB_FILE)
    db.set_state("theme", theme)
    db.set_state("win_w", str(WIDTH))
    db.set_state("win_h", str(height))
    db.set_state("panel_width", "400")
    db.set_state("hide_watched", "0")

    keys = []
    for index, (name, handle, followers, _group) in enumerate(CHANNELS):
        key = f"yt:UCmock{index:018d}"
        keys.append(key)
        picture = face(handle, index)
        db.add_channel(key, "youtube", f"UCmock{index:018d}", name, picture)
        db.set_channel_details(key, name, picture,
                               thumb(f"banner{index}", index + 11, 1280, 212), followers)

    rows = []
    for index, (channel, title, minutes, views, likes, days) in enumerate(VIDEOS):
        rows.append(VideoRow(
            "youtube", f"mockvideo{index:03d}", keys[channel], title,
            published_at=NOW - days * DAY - index * 3600,
            thumbnail_url=thumb(f"thumb{index:02d}", index + 1),
            duration_s=minutes * 60 + 12, views=views, likes=likes, is_short=False))
    # One announced stream, which is badged and cannot be handed to a player.
    rows.append(VideoRow("youtube", "mockvideo900", keys[3],
                         "Launch window, live from the pad", published_at=NOW - 3600,
                         thumbnail_url=thumb("thumb90", 90), duration_s=None,
                         views=None, likes=None, live_status="is_upcoming"))
    # One stream that is on now, so the bar mixes both platforms.
    rows.append(VideoRow("youtube", "mockvideo901", keys[0],
                         "Workshop stream, finishing the lathe", published_at=NOW - 7200,
                         thumbnail_url=thumb("thumb91", 91), duration_s=None,
                         views=None, likes=None, live_status="is_live"))
    db.upsert_videos(rows)
    with db.conn as conn:
        conn.execute("UPDATE videos SET scheduled_at=? WHERE ext_id='mockvideo900'",
                     (NOW + 2 * 3600 + 900,))
    db.set_live_state("yt:mockvideo901", 1_284, True)
    db.set_dislikes("yt:mockvideo000", 214)

    # Watched marks and part watched positions, which is what the line under a
    # card is. mpv writes those files, so invented ones go where it writes.
    db.set_watched("yt:mockvideo004", 1.0, "mpv")
    db.set_watched("yt:mockvideo007", 1.0, "mpv")
    later = Path(os.environ["XDG_STATE_HOME"]) / "mpv" / "watch_later"
    later.mkdir(parents=True, exist_ok=True)
    for index, fraction in ((0, 0.34), (2, 0.71), (5, 0.12)):
        url = f"https://www.youtube.com/watch?v=mockvideo{index:03d}"
        name = hashlib.md5(url.encode()).hexdigest().upper()
        seconds = VIDEOS[index][2] * 60 * fraction
        (later / name).write_text(f"start={seconds:.1f}\n")

    groups: dict[str, int] = {}
    for index, (_name, _handle, _followers, group) in enumerate(CHANNELS):
        if group not in groups:
            groups[group] = db.create_group(group)
        db.add_to_group(groups[group], keys[index])
    for name, held in (("Watch tonight", ("yt:mockvideo001", "yt:mockvideo003")),
                       ("Reference", ("yt:mockvideo006",))):
        box = db.create_box(name)
        for key in held:
            db.add_to_box(box, key)

    # Twitch, replaced wholesale by a real check, invented here.
    for index, (login, name, *_rest) in enumerate(LIVE):
        db.add_channel(f"twitch:{login}", "twitch", login, name, face(login, index + 5))
    db.replace_live("twitch", [{
        "channel_key": f"twitch:{login}", "login": login, "display_name": name,
        "title": title, "game": game, "viewers": viewers, "started_at": NOW - 5400,
        "thumbnail_url": thumb(f"live-{login}", 30 + index),
    } for index, (login, name, title, game, viewers) in enumerate(LIVE)])

    # Playlists, one of them marked as music, one with entries gone private.
    db.replace_playlists([{"ext_id": "PLmock000001", "title": "Soldering, start to finish"},
                          {"ext_id": "PLmock000002", "title": "Trail nights"},
                          {"ext_id": "LL", "title": "Liked videos"},
                          {"ext_id": "PLmock000003", "title": "Practice loops"}])
    db.set_playlist_music("PLmock000003", True)
    # What a channel's playlists tab lists, for the half of a channel page that
    # shows them. The pictures come with that listing in reality, so they are
    # seeded the same way here.
    from weave.sources.playlists import Playlist
    channel_lists = ["Rebuilding the lathe, every step",
                     "Soldering, from the first joint",
                     "Shop tours and what is on the bench",
                     "Answering your questions, live",
                     "Everything about flux",
                     "Small repairs nobody asked for"]
    db.replace_channel_playlists(f"yt:UCmock{0:018d}", [
        Playlist(f"PLchannel{index:013d}", title, thumb(f"chanlist{index}", index + 71))
        for index, title in enumerate(channel_lists)])
    for index, title in enumerate(channel_lists):
        db.open_channel_playlist(f"PLchannel{index:013d}", title)
        db.replace_playlist_items(f"PLchannel{index:013d}", [{
            "ext_id": f"mockchan{index}{item:02d}", "title": f"Part {item + 1}",
            "channel_name": CHANNELS[0][0], "channel_ext_id": f"UCmock{0:018d}",
            "duration_s": 600 + item * 120,
            "thumbnail_url": thumb(f"chanitem{index}{item}", index * 7 + item),
            "views": 12_000 + item * 900, "published_at": NOW - (item + 2) * DAY,
        } for item in range(3 + index * 2)])
    db.keep_playlist(f"PLchannel{0:013d}")

    db.replace_playlist_items("PLmock000001", [{
        "ext_id": f"mocklist{index:03d}", "title": title,
        "channel_name": CHANNELS[index % len(CHANNELS)][0],
        "channel_ext_id": f"UCmock{index % len(CHANNELS):018d}",
        "duration_s": 600 + index * 137,
        "thumbnail_url": thumb(f"list{index:02d}", index + 61),
        "views": 41_000 + index * 3_300, "published_at": NOW - (index + 3) * DAY,
    } for index, title in enumerate([
        "Tinning a tip properly", "Flux, and which one", "Through hole in eight minutes",
        "Surface mount without a stencil", "Desoldering without lifting a pad",
    ])], skipped=2)

    # What the service suggests, and the history it keeps, both their own
    # tables so nothing of this reaches the feed.
    # Two of them are streams, since a listing says which and the card badges
    # them the same way a feed row is badged.
    db.replace_cached("recommended", [{
        "ext_id": f"mockrec{index:03d}", "title": title,
        "channel_name": name, "channel_ext_id": None,
        "duration_s": None if index in (1, 4) else 480 + index * 211,
        "views": 88_000 + index * 41_000,
        "published_at": NOW - (index + 1) * DAY,
        "live_status": ("is_live" if index == 1
                        else "is_upcoming" if index == 4 else None),
        "scheduled_at": NOW + 5 * 3600 if index == 4 else None,
        "thumbnail_url": thumb(f"rec{index:02d}", index + 81),
    } for index, (title, name) in enumerate([
        ("A workshop built into a stairwell", "Copper & Coil"),
        ("Soldering along, live for an hour", "Bench Notes"),
        ("Two weeks of bread, one starter", "The Slow Kitchen"),
        ("Mapping a cave with a phone", "Northern Trailhead"),
        ("Launch day, the whole descent", "Orbital Mechanics Weekly"),
        ("Light, and how a lens bends it", "Lantern Studio"),
        ("One shelf, no screws", "Pixel Forge"),
        ("Recording rain properly", "Field Recordings"),
    ])])

    # The listening, ours and the service's, in one table.
    for index, (title, artist, seconds) in enumerate(TRACKS[:9]):
        db.remember_played(f"mocktrack{index:03d}", title, artist,
                           thumb(f"track{index:02d}", index + 40, 320, 320), seconds)
    # Staggered, or every song in the listening says it was played this second.
    with db.conn as conn:
        for index in range(9):
            conn.execute("UPDATE music_history SET played_at=?, plays=? WHERE ext_id=?",
                         (NOW - index * 2_400 - 600, 1 + index % 4, f"mocktrack{index:03d}"))
    for index in (0, 3, 5):
        title, artist, seconds = TRACKS[index]
        db.set_music_favorite(f"mocktrack{index:03d}", True, title, artist,
                              thumb(f"track{index:02d}", index + 40, 320, 320), seconds)

    # A login of its own, which is what the bar and the settings page read
    # to decide whether to ask for one. Invented, and in the scratch home.
    from weave import tokens
    from weave.sources.twitch import Tokens

    tokens.save(Tokens("invented-access-token", "invented-refresh-token", NOW - 3600))

    db.set_state("music_shelves", json.dumps([
        {"title": title, "items": track_items(index * 5, 14)}
        for index, title in enumerate(SHELVES)
    ]))
    db.set_state("music_shelves_at", str(NOW))
    db.add_source("Lofi radio, all night", "https://www.youtube.com/watch?v=mockstream1",
                  live=True)
    db.set_source_details("https://www.youtube.com/watch?v=mockstream1",
                          "Lofi radio, all night", thumb("radio", 7, 320, 320))
    db.close()


# ---- keeping the network out, without emptying the window --------------------

COMMENTS = [
    ("Bench Notes", "Part three answered the question I came here with, and this one "
                    "answers the next. Thanks for taking the time.", 1_842, "2 days ago",
     True, False),
    ("hollowmoon", "The bit at nineteen minutes where you measure the runout twice is "
                   "the whole video for me.", 604, "1 day ago", False, False),
    ("tinsmith", "I have the same lathe and had given up on it. Ordering the bearings "
                 "tonight.", 388, "22 hours ago", False, False),
    ("Pixel Forge", "The bearing part numbers are in the description now, sorry for the "
                    "wait.", 240, "20 hours ago", False, True),
    ("greyharbour", "Please never speed up the machining shots. It is the reason I watch.",
     97, "14 hours ago", False, False),
]


def stub_network() -> None:
    """No request, no subprocess, and invented answers where a blank would
    hide the feature the picture is of."""
    from weave import net, process
    from weave.sources import comments as comment_source
    from weave.sources import dislikes as dislike_source
    from weave.sources import ytmusic

    def no_request(*_a, **_k):
        raise net.Cancelled("no network in a screenshot")

    def no_process(*_a, **_k):
        raise FileNotFoundError("no subprocess in a screenshot")

    def no_music(*_a, **_k):
        raise ytmusic.MusicError("no network in a screenshot")

    def invented_comments(_cfg, _url, *_a, **_k):
        threads = []
        for index, (author, text, likes, when, pinned, uploader) in enumerate(COMMENTS):
            replies = []
            if index == 1:
                replies.append(comment_source.Comment(
                    author="Pixel Forge", avatar_url=face("pixelforge", 0),
                    text="Measured it a third time off camera, same figure.",
                    likes=142, when="20 hours ago", by_uploader=True, verified=True))
            threads.append(comment_source.Comment(
                author=author,
                avatar_url=face(author.lower().replace(" ", ""), index + 2),
                text=text, likes=likes, when=when, pinned=pinned,
                by_uploader=uploader, verified=uploader, replies=replies))
        return threads, comment_source.Details(views=184_320, likes=9_412,
                                               published_at=NOW - 3600, duration_s=2_472)

    def invented_votes(_fetcher, _video_id):
        return dislike_source.Votes(likes=9_412, dislikes=214, views=184_320)

    from weave import browsers, cookies

    invented = cookies.Source(spec="firefox:~/.mozilla/firefox/weave.default",
                              path=Path("~/.mozilla/firefox/weave.default"),
                              origin="picked here")

    def invented_profile(_cfg):
        return invented

    def invented_browsers(*_args):
        # A settled looking machine, and none of his own browsers. The
        # states are the ones the menu draws differently.
        return [
            browsers.Profile(family="Firefox", name="weave.default",
                             path=Path("~/.mozilla/firefox/weave.default"),
                             written_at=int(NOW), cookies=browsers.SESSION_COOKIES
                             | browsers.ROTATING_COOKIES, count=163, launched=True),
            browsers.Profile(family="Zen", name="Default (release)",
                             path=Path("~/.zen/weave.default"),
                             written_at=int(NOW - 40 * 86400)),
        ]

    cookies.resolve = invented_profile
    browsers.found = invented_browsers
    browsers.best = lambda *_: invented_browsers()[0]

    net.Fetcher.get_bytes = no_request
    process.run = no_process
    ytmusic.client = no_music
    comment_source.fetch = invented_comments
    dislike_source.fetch = invented_votes


def playing(bridge, at: int = 2) -> None:
    """Put a track in the player without a player.

    The engine is only started by loading something, so a queue written
    straight in gives the bar everything it draws and starts no process.
    """
    audio = bridge._audio                                          # noqa: SLF001
    audio._queue = [{                                              # noqa: SLF001
        "key": f"yt:mocktrack{index:03d}", "title": title, "artist": artist,
        "thumbnail": qml_source(thumb(f"track{index:02d}", index + 40, 320, 320)),
        "url": f"https://music.youtube.com/watch?v=mocktrack{index:03d}",
        "live": False,
    } for index, (title, artist, _seconds) in enumerate(TRACKS)]
    audio._order = list(range(len(audio._queue)))                  # noqa: SLF001
    audio._at = at                                                 # noqa: SLF001
    audio._dur = float(TRACKS[at][2])                              # noqa: SLF001
    audio._pos = audio._dur * 0.41                                 # noqa: SLF001
    audio._paused = False                                          # noqa: SLF001
    audio._idle = False                                            # noqa: SLF001
    audio.trackChanged.emit()
    audio.queueChanged.emit()
    audio.stateChanged.emit()
    audio.progressChanged.emit()


def quiet(bridge) -> None:
    """Take the window off the state a first launch with no network is in.

    The live bar stays folded until a check answers and nothing answers here,
    a failed sweep leaves a line about what did not arrive, and the refresh
    that runs at startup is still going. None of that is what a picture of a
    feature should be of.
    """
    bridge._live_ready = True
    bridge._live_checking = False
    bridge._twitch_needs_login = False
    bridge._twitch_status = ""
    bridge.liveChanged.emit()
    bridge.twitchChanged.emit()
    bridge._problems = []
    bridge.problemsChanged.emit()
    bridge._set_notice("")
    bridge._set_busy(False)
    bridge._set_status(bridge._idle_status())


# ---- the pictures ------------------------------------------------------------

def shot_feed(_bridge, _window) -> None:
    settle(1.4)


def shot_panel(bridge, _window) -> None:
    bridge.openDetail("yt:mockvideo000")
    settle(2.0)


def shot_music(bridge, _window) -> None:
    bridge.showMusic()
    playing(bridge)
    # The tiles come off the disk but still asynchronously, so too short a
    # wait leaves the second row of a section empty.
    settle(3.0)


def shot_channel(bridge, _window) -> None:
    bridge.openChannel(f"yt:UCmock{0:018d}")
    settle(2.0)


def shot_playlists(bridge, _window) -> None:
    """The other half of a channel page, the playlists it has made."""
    bridge.openChannel(f"yt:UCmock{0:018d}")
    settle(1.2)
    bridge.showChannelTab("playlists")
    settle(2.0)


def shot_playlist(bridge, window) -> None:
    bridge.selectPlaylist("PLmock000001")
    settle(1.4)
    # How many entries are private or gone is a footer, so it is only on
    # screen past the last row.
    grid = find(window, "grid")
    if grid is not None:
        write(grid, "contentY", max(0.0, float(read(grid, "contentHeight"))
                                    - float(read(grid, "height"))))
    settle(1.2)


# What a search of YouTube itself comes back with. Offline nothing arrives, so
# the answer is handed to the bridge the way the worker would hand it over.
SEARCH_RESULTS = [
    ("Turning a taper without a taper attachment", "Pixel Forge", 1_204, 51_200, None, None),
    ("Live from the bench, finishing the lathe", "Pixel Forge", None, 2_180, "is_live", None),
    ("Premiere, the whole rebuild in one cut", "Pixel Forge", None, None, "is_upcoming", 4 * 3600),
    ("Lathe basics for somebody with no lathe", "Bench Notes", 2_311, 88_400, None, None),
    ("Cutting threads, slowly and badly", "Copper & Coil", 940, 12_050, None, None),
    ("A lathe rescued from a barn", "Field Recordings", 3_120, 33_900, None, None),
]


def shot_search(bridge, _window) -> None:
    bridge.search("lathe")
    settle(0.4)
    bridge._search_scope = "youtube"
    rows = [{
        "ext_id": f"mocksearch{index:02d}", "title": title, "channel_name": channel,
        "channel_ext_id": f"UCmock{0:018d}" if channel == "Pixel Forge" else None,
        "duration_s": duration, "views": views,
        "published_at": None if live else NOW - (index + 2) * DAY,
        "live_status": live, "scheduled_at": NOW + starts if starts else None,
        "thumbnail_url": thumb(f"search{index:02d}", index + 101),
    } for index, (title, channel, duration, views, live, starts)
        in enumerate(SEARCH_RESULTS)]
    bridge._on_web_results("lathe", 1, rows)
    settle(1.4)


def shot_suggestions(bridge, _window) -> None:
    bridge.showRecommended()
    settle(1.4)


def shot_history(bridge, _window) -> None:
    bridge.showHistory()
    bridge.showMusicInHistory(True)
    playing(bridge, at=0)
    settle(1.6)


def shot_themes(bridge, window) -> None:
    bridge.showSettings()
    settle(1.0)
    sheet = find(window, "settingsSheet")
    maker = find(window, "themeMaker")
    if sheet is not None and maker is not None:
        write(sheet, "contentY", max(0.0, float(read(maker, "y")) - 200.0))
    settle(1.4)


# Which theme each picture is taken in, what it does before the shutter, and
# how tall the window is. A section of the music page is two rows deep, and a
# row laid out below the fold is never given its pictures, so that one is
# taken in a taller window rather than by scrolling to it.
# A different theme in every picture, and none of them twice, because the
# pictures are also the tour of what ships. Fourteen ship and seven are in the
# readme, so the ones in it are seven that nothing else shows. Only ones that
# ship: a theme somebody wrote for themselves is not in anybody else's copy,
# and the shot would come out in whatever the fallback is.
SHOTS = {
    "feed": ("Aurora", shot_feed, HEIGHT),
    "panel": ("Ultraviolet", shot_panel, HEIGHT),
    "music": ("Bloom", shot_music, 1080),
    "channel": ("Sunset Drive", shot_channel, HEIGHT),
    "playlists": ("Mint Fade", shot_playlists, HEIGHT),
    "playlist": ("Linen", shot_playlist, HEIGHT),
    "suggestions": ("Deep Sea", shot_suggestions, HEIGHT),
    "search": ("Violet Glow", shot_search, HEIGHT),
    "history": ("Paper Dark", shot_history, HEIGHT),
    "themes": ("Frost", shot_themes, 1080),
}


def take(name: str, out: Path) -> bool:
    """One window, one picture. A theme is read at startup, so this is a boot
    of its own for each."""
    theme, walk, height = SHOTS[name]
    for part in ("state", "cache"):
        for path in sorted((HOME / part).rglob("weave.db*")):
            path.unlink()
    seed(theme, height)
    from weave.app import run

    written = {"ok": False, "error": ""}

    def on_ready(engine, bridge, window):
        def go():
            try:
                walk(bridge, window)
                quiet(bridge)
                settle(0.4)
                target = out / f"{name}.png"
                written["ok"] = bool(window.grabWindow().save(str(target)))
            except Exception as exc:                                # noqa: BLE001
                written["error"] = f"{type(exc).__name__}: {exc}"
            QTimer.singleShot(150, QCoreApplication.instance().quit)

        QTimer.singleShot(400, go)
        QTimer.singleShot(40_000, QCoreApplication.instance().quit)

    run([sys.argv[0]], on_ready=on_ready)
    if written["error"]:
        print(f"{name}: {written['error']}", file=sys.stderr)
    return written["ok"]


def main() -> int:
    parser = argparse.ArgumentParser(description="pictures of the window, on invented data")
    parser.add_argument("--out", default="docs/shots", help="where to write them")
    parser.add_argument("--only", nargs="*", choices=sorted(SHOTS), help="a subset")
    parser.add_argument("--one", choices=sorted(SHOTS), help="take this one here")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # One QApplication per process, so each picture is taken by a child with a
    # scratch home of its own rather than by a second window in this one.
    if args.one:
        stub_network()
        return 0 if take(args.one, out) else 1

    failed = []
    for name in (args.only or list(SHOTS)):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--out", str(out),
             "--one", name],
            cwd=str(ROOT), env={**os.environ, "WEAVE_SHOT_HOME": ""}, check=False)
        if result.returncode:
            failed.append(name)
        else:
            print(f"wrote {out / (name + '.png')}  ({SHOTS[name][0]})")
    for name in failed:
        print(f"FAILED {name}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
