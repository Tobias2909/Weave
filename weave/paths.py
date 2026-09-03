"""Filesystem locations.

Everything goes through platformdirs rather than hand rolled XDG lookups, so a
future non Linux port has one place to change instead of a dozen.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import PlatformDirs

_dirs = PlatformDirs(appname="weave", appauthor=False, ensure_exists=False)

CONFIG_DIR = Path(_dirs.user_config_dir)
STATE_DIR = Path(_dirs.user_state_dir)
CACHE_DIR = Path(_dirs.user_cache_dir)

CONFIG_FILE = CONFIG_DIR / "config.toml"
THEMES_DIR = CONFIG_DIR / "themes"
DB_FILE = STATE_DIR / "weave.db"
THUMB_CACHE = CACHE_DIR / "thumbs"
MOVING_CACHE = CACHE_DIR / "moving"


def ensure_dirs() -> None:
    for path in (CONFIG_DIR, THEMES_DIR, STATE_DIR, THUMB_CACHE, MOVING_CACHE):
        path.mkdir(parents=True, exist_ok=True)


def runtime_dir() -> Path:
    """Where mpv puts its IPC socket. Falls back to /tmp when unset."""
    return Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")


def expand(value: str) -> Path:
    """Expand a user written path. Config stores ~ so no home directory ever
    reaches the repository."""
    return Path(value).expanduser()
