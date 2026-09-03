"""Where yt-dlp reads cookies from.

Only the parts that go past RSS need cookies. The feed itself never does, which
is deliberate, so a rotted login degrades the extras rather than the app.

The "auto" default resolves in two steps. If the mpv setup's browser profile
symlink exists it is used, because that symlink is already maintained to point
at whichever browser is actually being used. Otherwise yt-dlp is handed a bare
browser name and does its own discovery. That second path is what a stranger
gets, and it is also why "auto" alone is not enough here. yt-dlp's Firefox
discovery only looks in the standard Mozilla directories, so a fork such as Zen
or Floorp is never found without an explicit path.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config

MPV_PROFILE_LINK = Path("~/.config/mpv/browser-profile")
DEFAULT_FAMILY = "firefox"


def browser_spec(cfg: Config) -> str:
    """The value for yt-dlp's cookies-from-browser argument."""
    configured = cfg.browser_profile
    if configured and configured != "auto":
        expanded = Path(configured).expanduser()
        if expanded.exists():
            # yt-dlp calls abspath but never expanduser on this argument, so it
            # has to be resolved here.
            return f"{DEFAULT_FAMILY}:{expanded}"
        return configured

    link = MPV_PROFILE_LINK.expanduser()
    if link.exists():
        return f"{DEFAULT_FAMILY}:{link}"
    return DEFAULT_FAMILY


def args(cfg: Config) -> list[str]:
    return ["--cookies-from-browser", browser_spec(cfg)]
