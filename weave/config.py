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
    "player": {"command": "auto", "ipc_socket": "auto"},
    "poll": {
        "feed_interval_s": 900,
        "live_interval_s": 90,
        "max_concurrency": 4,
        "min_request_interval_ms": 250,
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
