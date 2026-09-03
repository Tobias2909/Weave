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
    "youtube": {"browser_profile": "auto"},
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
    "watched": {"threshold": 0.7},
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
