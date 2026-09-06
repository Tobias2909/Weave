"""Themes, as files rather than as colours written into the interface.

A theme is a name, a map of colour roles, and an optional gradient. Built in
ones ship beside this module in exactly the same format as any theme dropped
into the config directory, so a copy of one is a working starting point and
there is nothing privileged about the ones that came with the application.

A file that is wrong in some way still loads. Roles it does not mention keep
their default, roles it invents are reported and ignored, and a colour that is
not a colour is reported and skipped rather than passed to the interface where
it would fail silently at paint time.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

# Every colour the interface is allowed to ask for. Adding one here and using
# it is fine. Writing a colour into a QML file is not.
ROLES = (
    "background", "surface", "surfaceRaised", "border",
    "text", "textMuted", "accent", "accentHover",
    "live", "progress", "watchedDim",
    "badgeBackground", "badgeText", "error",
    "twitch", "youtube",
)

# Kept in code as well as in dark.toml, so a broken or missing set of files
# cannot leave the interface with no colours at all.
#
# A colour with eight digits is read as #AARRGGBB, alpha first. Written the
# other way round it is not a translucent black but a transparent blue, which
# is how the badge behind a duration came to be drawn on nothing at all.
FALLBACK: dict[str, str] = {
    "background": "#0f1115", "surface": "#171a21", "surfaceRaised": "#1f2430",
    "border": "#2a3040", "text": "#e7eaf0", "textMuted": "#98a0b3",
    "accent": "#7c5cff", "accentHover": "#9a80ff", "live": "#ff4d4f",
    "progress": "#ff3b30", "watchedDim": "#5a6072", "badgeBackground": "#80000000",
    "badgeText": "#f2f4f8", "error": "#ffb020", "twitch": "#9146ff",
    "youtube": "#ff3d3d",
}

DEFAULT_NAME = "Weave Dark"
COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


@dataclass(frozen=True)
class Loaded:
    name: str
    colors: dict[str, str]
    gradient: dict | None = None
    source: Path | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def builtin(self) -> bool:
        return self.source is not None and self.source.parent == builtin_dir()


def builtin_dir() -> Path:
    return Path(__file__).parent / "themes"


def user_dir() -> Path:
    return paths.THEMES_DIR


def _colours(raw: dict, problems: list[str]) -> dict[str, str]:
    colors = dict(FALLBACK)
    for role, value in (raw or {}).items():
        if role not in ROLES:
            problems.append(f"{role} is not a colour this interface uses")
            continue
        if not isinstance(value, str) or not COLOUR.match(value.strip()):
            problems.append(f"{role} is not a colour")
            continue
        colors[role] = value.strip()
    return colors


def _gradient(raw: dict | None, problems: list[str]) -> dict | None:
    if not raw:
        return None
    stops = raw.get("stops")
    if not isinstance(stops, list) or len(stops) < 2:
        problems.append("a gradient needs at least two stops")
        return None

    cleaned = []
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        position = stop.get("position")
        colour = stop.get("color")
        if not isinstance(position, (int, float)) or not isinstance(colour, str):
            continue
        if not COLOUR.match(colour.strip()):
            problems.append(f"{colour} is not a colour")
            continue
        cleaned.append({"position": max(0.0, min(1.0, float(position))),
                        "color": colour.strip()})
    if len(cleaned) < 2:
        problems.append("a gradient needs at least two usable stops")
        return None

    cleaned.sort(key=lambda stop: stop["position"])

    kind = raw.get("type", "linear")
    if kind not in ("linear", "radial"):
        problems.append(f"{kind} is not a kind of gradient")
        kind = "linear"

    angle = raw.get("angle", 0)
    if not isinstance(angle, (int, float)):
        problems.append("the gradient angle is not a number")
        angle = 0

    def fraction(name: str, fallback: float) -> float:
        value = raw.get(name, fallback)
        if not isinstance(value, (int, float)):
            problems.append(f"the gradient {name} is not a number")
            return fallback
        return float(value)

    # A linear angle of zero runs straight down the window and forty five
    # starts at the top left corner. A radial one is placed by origin, given in
    # fractions of the window, with a radius in fractions of its diagonal, so a
    # theme looks the same whatever size the window is.
    return {
        "type": kind,
        "angle": float(angle) % 360.0,
        "originX": max(-1.0, min(2.0, fraction("origin_x", 0.0))),
        "originY": max(-1.0, min(2.0, fraction("origin_y", 0.0))),
        "radius": max(0.05, min(3.0, fraction("radius", 1.0))),
        "stops": cleaned,
    }


def file_name(name: str) -> str:
    """What a theme called this is stored as.

    Kept to letters, digits and dashes, so a name with a slash or a quote in
    it cannot decide where the file lands.
    """
    kept = [ch.lower() if ch.isalnum() else "-" for ch in name.strip()]
    slug = "".join(kept).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "theme"


def load_file(path: Path) -> Loaded | None:
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return Loaded(name=path.stem, colors=dict(FALLBACK), source=path,
                      problems=[f"could not be read, {exc}"])
    problems: list[str] = []
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        name = path.stem
        problems.append("no name, so the file name is used instead")
    return Loaded(name=name.strip(), colors=_colours(raw.get("colors"), problems),
                  gradient=_gradient(raw.get("gradient"), problems),
                  source=path, problems=problems)


def available() -> list[Loaded]:
    """Built in themes first, then the ones in the config directory. A file there
    with the same name as a built in one replaces it, so any of them can be
    copied out and altered."""
    found: dict[str, Loaded] = {}
    for directory in (builtin_dir(), user_dir()):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.toml")):
            theme = load_file(path)
            if theme is not None:
                found[theme.name] = theme
    return list(found.values())


def find(name: str) -> Loaded:
    """The named theme, or the default, or the built in colours. Always
    returns something, since an interface with no colours is not an option."""
    themes = available()
    for theme in themes:
        if theme.name == name:
            return theme
    for theme in themes:
        if theme.name == DEFAULT_NAME:
            return theme
    return themes[0] if themes else Loaded(name=DEFAULT_NAME, colors=dict(FALLBACK))
