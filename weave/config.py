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
from .db import FeedTiers

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
        # A small round, often, rather than a large round rarely. What the
        # feed endpoint objects to is a burst, not a day's worth of requests,
        # so the same hourly volume spread evenly is far safer and reaches
        # every channel sooner.
        "tick_interval_s": 60,
        "channels_per_tick": 15,
        # How often a channel is asked, by how recently it published. The
        # shortest is a quarter of an hour because the feed itself answers
        # with Cache-Control max-age=900, so asking sooner returns the same
        # cached body. Over half of a large subscription list has not posted
        # in three months, and polling those at the same rate as the rest is
        # what made a full lap take over an hour.
        "feed_interval_s": 900,          # posted within active_days
        "warm_interval_s": 3600,         # within warm_days
        "cold_interval_s": 21600,        # within cold_days
        "frozen_interval_s": 86400,      # longer ago than that, or never
        "active_days": 7,
        "warm_days": 30,
        "cold_days": 90,
        "live_interval_s": 90,
        # The gap is global, so a round costs channels times the gap whatever
        # the concurrency is. Gentler than it was: the feed endpoint pushes
        # back on a burst by answering 404 or 500 rather than saying it is
        # busy, which looks like a few hundred channels having vanished.
        "max_concurrency": 4,
        "min_request_interval_ms": 220,
        # How deep the subscriptions sweep goes, and how often it runs. It
        # paginates at roughly 77 ids a second, so a thousand costs about
        # thirteen seconds. One sweep names every subscribed channel with
        # something new, which is what lets the per channel feeds be asked
        # only when there is a reason to.
        "sweep_limit": 1000,
        "sweep_interval_s": 900,
        # Ask a channel's live feed as well as its videos feed. Only channels
        # that have been seen streaming are asked, so this is a handful of
        # extra requests rather than a second one per channel.
        "poll_live_feeds": True,
    },
    # Ceilings on how much each endpoint may be asked inside one window,
    # counted in the database so a restart cannot forget them. These are well
    # above what idle use spends, so they bite on a restart loop or a held
    # down refresh button rather than on ordinary polling. Zero means no
    # ceiling and no counting.
    "budget": {
        "window_s": 900,
        "feeds": 300,
        "browse": 40,
        "player": 60,
        "dislikes": 60,
        "twitch": 120,
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
    def channels_per_tick(self) -> int:
        return max(1, int(self.get("poll", "channels_per_tick")))

    @property
    def tick_interval_s(self) -> int:
        return max(5, int(self.get("poll", "tick_interval_s")))

    @property
    def sweep_interval_s(self) -> int:
        return max(0, int(self.get("poll", "sweep_interval_s")))

    @property
    def poll_live_feeds(self) -> bool:
        return bool(self.get("poll", "poll_live_feeds"))

    @property
    def feed_tiers(self) -> FeedTiers:
        return FeedTiers(
            hot_days=max(1, int(self.get("poll", "active_days"))),
            warm_days=max(1, int(self.get("poll", "warm_days"))),
            cold_days=max(1, int(self.get("poll", "cold_days"))),
            hot_s=max(60, int(self.get("poll", "feed_interval_s"))),
            warm_s=max(60, int(self.get("poll", "warm_interval_s"))),
            cold_s=max(60, int(self.get("poll", "cold_interval_s"))),
            frozen_s=max(60, int(self.get("poll", "frozen_interval_s"))),
        )

    @property
    def budget_window_s(self) -> int:
        return max(60, int(self.get("budget", "window_s")))

    @property
    def budget_limits(self) -> dict[str, int]:
        keys = ("feeds", "browse", "player", "dislikes", "twitch")
        return {key: max(0, int(self.get("budget", key))) for key in keys}

    @property
    def sweep_limit(self) -> int:
        return max(0, int(self.get("poll", "sweep_limit")))



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
