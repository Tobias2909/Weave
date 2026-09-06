#!/usr/bin/env python3
"""Draw the Weave icon, and cut it to the sizes a panel asks for.

The mark is a play triangle woven from four horizontal ribbons, alternate
bands pushed sideways so the shape reads as cloth up close and as a play
button at sixteen pixels. The two middle bands share an offset on purpose,
because the apex sits exactly on their seam and opposite offsets fork the tip.

Each band is worked out as its own polygon rather than cut out of one triangle
with a clip. A clip would hide the outline along the horizontal cuts, since a
clipped edge is not part of the shape being stroked, and the ribbons would be
outlined on their slanted sides only.

The whole drawing is scaled inside its square rather than drawn smaller,
because a task bar gives every icon the same box. A tile that fills its box
edge to edge looks bigger than the icons beside it, which almost all carry
some air around them.

Run it from the repository root.

    python tools/make_icon.py

It writes weave/share/weave.svg and a png per size. The pngs need
rsvg-convert, which comes with librsvg. Nothing else here needs it, so the
pictures are committed and this only has to run when the drawing changes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SHARE = Path(__file__).resolve().parent.parent / "weave" / "share"
SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)

BOX = 128.0
FILL = 0.84                      # how much of the box the tile takes
CORNER = 28.0                    # corner radius before scaling
MARK = "#ffeef0"                 # the theme's own text colour
STOPS = (("0", "#ffa250"), ("0.5", "#ff7a3d"), ("1", "#b03a6b"))

# White on orange separates by brightness alone, which a small icon renders as
# a smear. A dark edge gives the ribbons a boundary that survives the shrink.
# The weight is a compromise measured at every shipped size. Below about 0.5 it
# stops reaching the rasteriser at all, and by 1.5 it starts greying the white
# at sixteen pixels, where each ribbon is only a couple of pixels wide.
OUTLINE = "#170d14"              # the theme's own background colour
OUTLINE_WIDTH = 0.75

# The triangle before scaling, and the horizontal cuts through it. The seams
# are the band edges, the offsets are how far each band slides sideways.
LEFT, RIGHT, TOP, BOTTOM = 32.0, 102.0, 21.0, 107.0
SEAMS = (42.5, 64.0, 85.5)
OFFSETS = (-4.0, 4.0, 4.0, -4.0)
GAP = 4.0


def scaled(value: float) -> float:
    """A coordinate moved toward the middle of the box by the fill factor."""
    return round(BOX / 2 + (value - BOX / 2) * FILL, 2)


def right_edge(y: float) -> float:
    """How far the triangle reaches at that height.

    The two slanted sides meet at the apex, so the reach grows to the middle
    and falls away again, which is what the distance from the middle measures.
    """
    middle = (TOP + BOTTOM) / 2
    reach = 1 - abs(y - middle) / ((BOTTOM - TOP) / 2)
    return LEFT + (RIGHT - LEFT) * reach


def band(index: int) -> str:
    """One ribbon, as a closed shape that can carry an outline.

    The first and the last band end in a point, because their far edge is a
    corner of the triangle rather than a cut across it.
    """
    edges = [TOP, *SEAMS, BOTTOM]
    first, last = index == 0, index == len(OFFSETS) - 1
    top = edges[index] + (0 if first else GAP / 2)
    bottom = edges[index + 1] - (0 if last else GAP / 2)
    slide = round(OFFSETS[index] * FILL, 2)

    def point(x: float, y: float) -> str:
        return f"{round(scaled(x) + slide, 2)} {scaled(y)}"

    if first:
        corners = [point(LEFT, top), point(right_edge(bottom), bottom), point(LEFT, bottom)]
    elif last:
        corners = [point(LEFT, top), point(right_edge(top), top), point(LEFT, bottom)]
    else:
        corners = [point(LEFT, top), point(right_edge(top), top),
                   point(right_edge(bottom), bottom), point(LEFT, bottom)]
    return "M " + " L ".join(corners) + " Z"


def draw() -> str:
    bands = "".join(f'<path d="{band(index)}"/>' for index in range(len(OFFSETS)))
    tile = scaled(0.0)
    side = round(BOX * FILL, 2)
    gradient = "".join(f'<stop offset="{at}" stop-color="{colour}"/>' for at, colour in STOPS)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX:.0f} {BOX:.0f}" '
            f'width="{BOX:.0f}" height="{BOX:.0f}">\n'
            f'  <defs>\n'
            f'    <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">{gradient}</linearGradient>\n'
            f'  </defs>\n'
            f'  <rect x="{tile}" y="{tile}" width="{side}" height="{side}" '
            f'rx="{round(CORNER * FILL, 2)}" fill="url(#tile)"/>\n'
            f'  <g fill="{MARK}" stroke="{OUTLINE}" stroke-width="{OUTLINE_WIDTH}" '
            f'stroke-linejoin="round">{bands}</g>\n'
            f'</svg>\n')


def main() -> int:
    drawing = SHARE / "weave.svg"
    SHARE.mkdir(parents=True, exist_ok=True)
    drawing.write_text(draw(), encoding="utf-8")
    print(f"wrote {drawing}")

    renderer = shutil.which("rsvg-convert")
    if not renderer:
        print("rsvg-convert is not installed, so no pngs were cut", file=sys.stderr)
        return 1
    for size in SIZES:
        target = SHARE / f"weave-{size}.png"
        subprocess.run([renderer, "-w", str(size), "-h", str(size),
                        str(drawing), "-o", str(target)], check=True)
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
