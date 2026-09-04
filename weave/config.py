"""Human authored configuration.

config.toml is read only from the application's point of view. Mutable UI state
such as window geometry or the panel width lives in the database instead, which
keeps this module free of a TOML writer dependency and keeps the file readable
after the app has touched it.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

DEFAULTS: dict[str, dict[str, Any]] = {
    "youtube": {
        "browser_profile": "auto",
        # Which YouTube identity to speak as. A Google account can carry more
        # than one, and "auto" follows whichever the browser is using, which is
        # whichever was last used there. Set a numeric page id to pin one.
        "music_identity": "auto",
    },
    "player": {"command": "auto", "ipc_socket": "auto", "watch_later_dir": "auto"},
    "poll": {
        "feed_interval_s": 900,
        "live_interval_s": 90,
        # The gap is global, so a full sweep costs channels times the gap
        # whatever the concurrency is. At 100 ms, several hundred channels take
        # under a minute, which is fine off the interface thread. Raising the
        # gap makes a large subscription list crawl.
        "max_concurrency": 8,
        "min_request_interval_ms": 100,
        # How deep the subscriptions sweep goes when filling in durations.
        # It paginates at roughly 77 ids a second, so a thousand costs about
        # thirteen seconds and covers far more than what is on screen.
        "sweep_limit": 1000,
        # How many undecided videos get the Shorts redirect test per cycle.
        # That test is only the fallback for a video in neither channel
        # listing, so it stays small.
        "shorts_per_cycle": 20,
        # How many channels get their listings read per cycle, and how long a
        # channel's answer is trusted before asking again. A channel whose
        # videos are all decided is never asked, so in the steady state this is
        # only the channels that just gained a video.
        "classify_per_cycle": 40,
        "classify_interval_s": 21600,
    },
    "watched": {"threshold": 0.85},
    "twitch": {
        # From a Twitch application you register once at dev.twitch.tv. A
        # client id is public by design, it ships inside every browser
        # extension that talks to Twitch, but it identifies your developer
        # account so it stays out of the repository.
        "client_id": "",
    },
    "cache": {
        # Images live on disk this long. The server asks for five minutes,
        # which would mean going back to the network on nearly every visit, so
        # the stored copy is kept for this instead.
        "image_days": 7,
        # Ceiling for the image cache. Measured, a thumbnail averages 17.5 KB,
        # so several thousand videos plus avatars and banners fit in this.
        "image_max_mb": 300,
    },
    "ui": {
        # How far one wheel notch moves the grid, counted in card rows. A
        # Flickable on its own moves about sixty pixels, which is a fifth of a
        # row here and made scrolling feel stuck. Taste, so it lives here.
        "scroll_rows_per_notch": 0.5,
    },
}


@dataclass(frozen=True)
class Config:
    raw: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, section: str, key: str) -> Any:
        try:
            return self.raw[section][key]
        except KeyError:
            return DEFAULTS[section][key]

    # Convenience accessors for the values read on hot paths.
    @property
    def browser_profile(self) -> str:
        return str(self.get("youtube", "browser_profile"))

    @property
    def feed_interval_s(self) -> int:
        return int(self.get("poll", "feed_interval_s"))

    @property
    def live_interval_s(self) -> int:
        return int(self.get("poll", "live_interval_s"))

    @property
    def max_concurrency(self) -> int:
        return max(1, int(self.get("poll", "max_concurrency")))

    @property
    def min_request_interval_s(self) -> float:
        return max(0.0, int(self.get("poll", "min_request_interval_ms")) / 1000.0)

    @property
    def music_identity(self) -> str:
        return str(self.get("youtube", "music_identity")).strip()

    @property
    def browser_profile_path(self) -> str:
        """Where the cookies live, as a path. Falls back to the symlink the mpv
        setup maintains, which is what auto resolves to elsewhere."""
        configured = self.browser_profile
        if configured and configured != "auto":
            return configured
        return "~/.config/mpv/browser-profile"

    @property
    def twitch_client_id(self) -> str:
        return str(self.get("twitch", "client_id")).strip()

    @property
    def image_days(self) -> int:
        return max(1, int(self.get("cache", "image_days")))

    @property
    def image_max_mb(self) -> int:
        return max(16, int(self.get("cache", "image_max_mb")))

    @property
    def scroll_rows_per_notch(self) -> float:
        return min(3.0, max(0.05, float(self.get("ui", "scroll_rows_per_notch"))))

    @property
    def watched_threshold(self) -> float:
        return min(1.0, max(0.05, float(self.get("watched", "threshold"))))

    @property
    def player_command(self) -> str:
        return str(self.get("player", "command"))

    @property
    def ipc_socket(self) -> str:
        return str(self.get("player", "ipc_socket"))

    @property
    def watch_later_dir(self) -> str:
        return str(self.get("player", "watch_later_dir"))

    @property
    def sweep_limit(self) -> int:
        return max(0, int(self.get("poll", "sweep_limit")))

    @property
    def shorts_per_cycle(self) -> int:
        return max(0, int(self.get("poll", "shorts_per_cycle")))

    @property
    def classify_per_cycle(self) -> int:
        return max(0, int(self.get("poll", "classify_per_cycle")))

    @property
    def classify_interval_s(self) -> int:
        return max(0, int(self.get("poll", "classify_interval_s")))


def load(path: Path | None = None) -> Config:
    """Read the config file. A missing or unreadable file yields defaults, so a
    fresh install and a broken edit both still start."""
    target = path or paths.CONFIG_FILE
    try:
        with open(target, "rb") as handle:
            return Config(raw=tomllib.load(handle))
    except FileNotFoundError:
        return Config(raw={})
    except (tomllib.TOMLDecodeError, OSError):
        # Deliberately non fatal. The Settings debug page reports it later.
        return Config(raw={})
