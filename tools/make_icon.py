#!/usr/bin/env python3
"""Draw the Weave icon, and cut it to the sizes a panel asks for.

The mark is a whole play triangle on a rounded tile. It was four ribbons woven
into that triangle before, which read as cloth up close and as very little at
sixteen pixels, and almost nobody saw a play button in it. The triangle is one
shape now, and the weave lives on in the four colours running down it rather
than in four pieces the eye has to assemble.

The colours hold their own quarter and turn over inside a short seam, so the
four can still be counted at the sizes where anybody looks closely, and there
is no hard line anywhere. Below about forty eight pixels the seams are thinner
than a pixel and it reads as one warm sweep, which is the same thing a full
blend would do there anyway.

The tile is the theme's own wash taken at its deep end, so the mark separates
from it at every size. That wash was tried on the tile at full strength as
well, and its orange corner sits exactly where the triangle's top band does,
which takes the top edge off the mark on that corner.

The edge is the theme's background colour. It draws the triangle's shape at
the sizes where the colours alone would smear, and by sixteen pixels it is
thinner than a pixel and gone, which is why the bands are lifted rather than
left at the colours the video uses.

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

# The tile, which is the theme's own wash held at its deep end.
TILE = (("0", "#8f2f5e"), ("0.45", "#4a1a38"), ("1", "#140a12"))

# The four colours the mark carries, each lifted far enough to stay apart
# from the tile under it once the icon is small.
BANDS = ("#ffc266", "#ff8f52", "#ff5f7a", "#e0507f")
# How much of a colour's own quarter is given to turning into the next one.
# Nothing at all is the hard cut this replaced, and a half is a plain blend
# with no colour of its own left anywhere.
SEAM = 0.15

OUTLINE = "#170d14"              # the theme's own background colour
OUTLINE_WIDTH = 2.0

# How much of the tile the triangle takes, and its proportions. Much wider
# than it is tall reads as an arrow and much taller reads as a pointer, so it
# sits near the ratio a play button has everywhere else.
MARK = 0.78
MARK_HEIGHT = 0.86
MARK_WIDTH = 0.80
# A triangle centred on its bounding box looks as though it is sliding left,
# because its weight is all down the flat side. This is that correction.
MARK_NUDGE = 0.30


def corners() -> list[tuple[float, float]]:
    """The three points of the triangle, in the box's own coordinates."""
    side = BOX * FILL * MARK
    height = side * MARK_HEIGHT
    middle = BOX / 2
    left = middle - side * MARK_NUDGE
    return [(left, middle - height / 2),
            (left + side * MARK_WIDTH, middle),
            (left, middle + height / 2)]


def triangle() -> str:
    return "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in corners()) + " Z"


def stops() -> str:
    """The four colours as one run down the mark, each holding its quarter.

    Two stops per colour, at the ends of the part of its quarter it keeps, so
    the turn happens in the seam between them rather than across the whole
    quarter. The first and the last reach the ends of the triangle, or the
    point and the foot would fade into something they were never given.
    """
    out = []
    share = 1 / len(BANDS)
    for index, colour in enumerate(BANDS):
        low = index * share
        high = low + share
        first = low if index == 0 else low + share * SEAM
        last = high if index == len(BANDS) - 1 else high - share * SEAM
        out.append(f'<stop offset="{first:.4f}" stop-color="{colour}"/>')
        out.append(f'<stop offset="{last:.4f}" stop-color="{colour}"/>')
    return "".join(out)


def draw() -> str:
    tile = round(BOX / 2 - BOX * FILL / 2, 2)
    side = round(BOX * FILL, 2)
    gradient = "".join(f'<stop offset="{at}" stop-color="{colour}"/>' for at, colour in TILE)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX:.0f} {BOX:.0f}" '
            f'width="{BOX:.0f}" height="{BOX:.0f}">\n'
            f'  <defs>\n'
            f'    <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">{gradient}</linearGradient>\n'
            f'    <linearGradient id="mark" x1="0" y1="0" x2="0" y2="1">{stops()}</linearGradient>\n'
            f'  </defs>\n'
            f'  <rect x="{tile}" y="{tile}" width="{side}" height="{side}" '
            f'rx="{round(CORNER * FILL, 2)}" fill="url(#tile)"/>\n'
            f'  <path d="{triangle()}" fill="url(#mark)"/>\n'
            f'  <path d="{triangle()}" fill="none" stroke="{OUTLINE}" '
            f'stroke-width="{OUTLINE_WIDTH}" stroke-linejoin="round"/>\n'
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
