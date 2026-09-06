"""A whole theme worked out from two or three chosen colours.

A theme here is sixteen named roles, and choosing sixteen colours by hand is
nobody's idea of an evening. So a theme is described by dots instead: one for
the ground the window is built on, one for the colour it is accented with, and
an optional third that only the gradient uses. Everything else is derived from
those.

Three roles are deliberately left out of the derivation. `live`, `twitch` and
`youtube` are marks that mean something outside this application, and tinting
the Twitch mark green to match a green theme would make it stop meaning
Twitch. `error` is left alone for the same reason, and `badgeBackground` is a
plate of plain black at half strength, which is a measured choice rather than
a taste one.

Contrast is the whole difficulty. Any two colours can be picked, and most
pairs make text that cannot be read, so text is not taken from the dots at
all. It is lifted or dropped until it clears a contrast ratio against the
ground it sits on, by the same measure a browser uses.
"""

from __future__ import annotations

import colorsys
import re

HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Marks that mean something outside this window, and one plate that was tuned
# by eye. None of these follow the dots.
FIXED = {
    "live": "#ff4d4f",
    "twitch": "#9146ff",
    "youtube": "#ff3d3d",
    "error": "#ffb020",
    "badgeBackground": "#80000000",
}

# What a reader needs. The first is what ordinary text clears against the
# ground it sits on, the second what quieter text clears, the third what a
# coloured mark clears to still read as a mark.
TEXT_CONTRAST = 7.0
MUTED_CONTRAST = 3.2
ACCENT_CONTRAST = 3.0


def _clean(value: str) -> str:
    value = (value or "").strip()
    if not HEX.match(value):
        return "#000000"
    if len(value) == 4:
        return "#" + "".join(ch * 2 for ch in value[1:])
    return value.lower()


def to_rgb(value: str) -> tuple[float, float, float]:
    value = _clean(value)
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, part)) * 255):02x}"
                         for part in rgb)


def _luminance(value: str) -> float:
    """How bright a colour reads, the way a contrast ratio measures it."""
    def channel(part: float) -> float:
        return part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(part) for part in to_rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: str, other: str) -> float:
    """The ratio between two colours, from 1 for the same to 21 for black on
    white. This is the measure that decides whether text can be read."""
    first, second = _luminance(one), _luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def mix(one: str, other: str, amount: float) -> str:
    """Somewhere between two colours. Nothing more than that."""
    amount = max(0.0, min(1.0, amount))
    first, second = to_rgb(one), to_rgb(other)
    return to_hex(tuple(a + (b - a) * amount for a, b in zip(first, second)))


def lift(value: str, amount: float) -> str:
    """Lighter by an amount, or darker when the amount is negative, keeping
    the colour it is rather than washing it out."""
    hue, lightness, saturation = colorsys.rgb_to_hls(*to_rgb(value))
    lightness = max(0.0, min(1.0, lightness + amount))
    return to_hex(colorsys.hls_to_rgb(hue, lightness, saturation))


def readable(colour: str, against: str, ratio: float) -> str:
    """The same colour, moved until it can be read against the other one.

    Moved rather than replaced with a fixed white or black, so a theme keeps
    its own cast instead of every theme ending in the same two text colours.

    Both directions are tried, and this is not fussiness. Against a mid grey
    ground, going lighter reaches about four to one and going darker reaches
    over five, so a rule that only ever lightens picks the worse of the two
    exactly where the choice matters most. Whichever arrives first wins, and
    if neither does, the best either reached is returned, since nothing clears
    seven to one against mid grey.
    """
    if contrast(colour, against) >= ratio:
        return colour
    best, best_ratio = colour, contrast(colour, against)
    reached: list[tuple[int, str]] = []
    for step in (0.02, -0.02):
        moved = colour
        for taken in range(1, 51):
            moved = lift(moved, step)
            found = contrast(moved, against)
            if found > best_ratio:
                best, best_ratio = moved, found
            if found >= ratio:
                reached.append((taken, moved))
                break
    if reached:
        # The one that needed the least moving keeps most of the colour asked
        # for.
        return min(reached)[1]
    return best


def from_dots(ground: str, accent: str, second: str | None = None) -> dict:
    """The whole theme, from the dots that were moved.

    The ground dot decides what the window is built on and every surface above
    it. The accent dot decides what is pressed and what is pointed at. The
    third is only the far end of the gradient, and without it the accent
    stands in for it, which is what leaving one dot alone amounts to.
    """
    ground = _clean(ground)
    accent = _clean(accent)
    second = _clean(second) if second else accent

    dark = _luminance(ground) < 0.5
    step = 1 if dark else -1
    surface = lift(ground, 0.045 * step)
    raised = lift(ground, 0.085 * step)
    border = lift(ground, 0.15 * step)

    # Text keeps a little of the ground's own cast rather than being white.
    text = readable(lift(ground, 0.9 * step), ground, TEXT_CONTRAST)
    muted = readable(mix(text, ground, 0.42), ground, MUTED_CONTRAST)
    watched = mix(muted, ground, 0.45)

    accent_seen = readable(accent, ground, ACCENT_CONTRAST)
    colours = {
        "background": ground,
        "surface": surface,
        "surfaceRaised": raised,
        "border": border,
        "text": text,
        "textMuted": muted,
        "accent": accent_seen,
        "accentHover": lift(accent_seen, 0.09 * step),
        "progress": lift(accent_seen, 0.06 * step),
        "watchedDim": watched,
        "badgeText": readable("#ffffff", "#202020", 5.0),
    }
    colours.update(FIXED)

    # The light comes from one corner and falls away to the ground, which is
    # the shape every theme that ships uses.
    #
    # How much of it there is depends on the ground. A dark window can take a
    # good deal of colour in the corner, since it only lifts a nearly black
    # surface. A pale window cannot: the same mix there is a slab of colour
    # rather than a glow, and the bars that go translucent over a gradient
    # turn dark under text meant for a pale ground. So on a light ground the
    # colour is both weaker and lifted towards the ground first.
    if dark:
        corner = mix(ground, second, 0.55)
        middle = mix(ground, accent_seen, 0.14)
    else:
        # Measured against the ground it sits on: lifting the colour as far
        # as a quarter leaves a corner that cannot be told from the ground at
        # all, which is a gradient nobody can see. This much is a tint rather
        # than a slab, and a bar over it still carries text at fifteen to one.
        corner = mix(ground, lift(second, 0.10), 0.34)
        middle = mix(ground, lift(accent_seen, 0.20), 0.10)
    gradient = {
        "angle": 45,
        "stops": [
            {"position": 0.0, "color": corner},
            {"position": 0.55, "color": middle},
            {"position": 1.0, "color": ground},
        ],
    }
    return {"colors": colours, "gradient": gradient}


def as_toml(name: str, made: dict) -> str:
    """The theme as a file, in the shape the ones that ship are written in."""
    lines = [f'name = "{name}"', "", "[colors]"]
    lines += [f'{role} = "{value}"' for role, value in made["colors"].items()]
    gradient = made.get("gradient")
    if gradient:
        lines += ["", "[gradient]", f"angle = {gradient['angle']}", "stops = ["]
        lines += [f'  {{ position = {stop["position"]}, color = "{stop["color"]}" }},'
                  for stop in gradient["stops"]]
        lines += ["]"]
    return "\n".join(lines) + "\n"
