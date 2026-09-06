#!/usr/bin/env python3
"""Draw the Weave icon, and cut it to the sizes a panel asks for.

The mark is a play triangle woven from four horizontal ribbons, alternate
bands pushed sideways so the shape reads as cloth up close and as a play
button at sixteen pixels. The two middle bands share an offset on purpose,
because the apex sits exactly on their seam and opposite offsets fork the tip.

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

# The triangle before scaling, and the horizontal cuts through it. The seams
# are the band edges, the offsets are how far each band slides sideways.
LEFT, RIGHT, TOP, BOTTOM = 32.0, 102.0, 21.0, 107.0
SEAMS = (42.5, 64.0, 85.5)
OFFSETS = (-4.0, 4.0, 4.0, -4.0)
GAP = 4.0


def scaled(value: float) -> float:
    """A coordinate moved toward the middle of the box by the fill factor."""
    return round(BOX / 2 + (value - BOX / 2) * FILL, 2)


def draw() -> str:
    edges = [TOP, *SEAMS, BOTTOM]
    triangle = (f"M {scaled(LEFT)} {scaled(TOP)} "
                f"L {scaled(LEFT)} {scaled(BOTTOM)} "
                f"L {scaled(RIGHT)} {scaled(BOTTOM - (BOTTOM - TOP) / 2)} Z")

    clips, bands = [], []
    for index, offset in enumerate(OFFSETS):
        first, last = index == 0, index == len(OFFSETS) - 1
        top = 0.0 if first else scaled(edges[index] + GAP / 2)
        bottom = BOX if last else scaled(edges[index + 1] - GAP / 2)
        clips.append(f'<clipPath id="b{index}">'
                     f'<rect x="0" y="{top}" width="{BOX:.0f}" height="{round(bottom - top, 2)}"/>'
                     f'</clipPath>')
        bands.append(f'<g clip-path="url(#b{index})">'
                     f'<path d="{triangle}" transform="translate({round(offset * FILL, 2)},0)"/>'
                     f'</g>')

    tile = scaled(0.0)
    side = round(BOX * FILL, 2)
    gradient = "".join(f'<stop offset="{at}" stop-color="{colour}"/>' for at, colour in STOPS)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX:.0f} {BOX:.0f}" '
            f'width="{BOX:.0f}" height="{BOX:.0f}">\n'
            f'  <defs>\n'
            f'    <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">{gradient}</linearGradient>\n'
            f'    {"".join(clips)}\n'
            f'  </defs>\n'
            f'  <rect x="{tile}" y="{tile}" width="{side}" height="{side}" '
            f'rx="{round(CORNER * FILL, 2)}" fill="url(#tile)"/>\n'
            f'  <g fill="{MARK}">{"".join(bands)}</g>\n'
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
