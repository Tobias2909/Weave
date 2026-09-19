#!/usr/bin/env python3
"""Draw the social preview card, the picture a link to the repository unfurls.

GitHub has no per repository icon, so this card is what a link to Weave looks
like in a message, and it is the only place the icon appears at any size worth
looking at. It is drawn here rather than kept as a picture nobody can redo,
because the icon it carries changes.

The card is 1280 by 640, which is what GitHub asks for, and it holds the icon,
the name and the two lines the README opens with. The ground is the theme's
own wash, darkened, so the card reads as the application rather than as a
slide.

Run it from the repository root.

    python tools/make_social.py

It needs the icon to have been cut already, so run tools/make_icon.py first
when the drawing has changed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "weave" / "share" / "weave-512.png"
CARD = ROOT / "docs" / "social-preview.png"

WIDTH, HEIGHT = 1280, 640
GROUND = "#170d14"
TEXT = "#ffeef0"
MUTED = "#d7aab5"

NAME = "Weave"
LINES = ("A personal YouTube and Twitch client for Linux",
         "Your channels, your groups, played in mpv")


def main() -> int:
    from PySide6.QtCore import QPointF, QRect, Qt
    from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter,
                               QRadialGradient)

    QGuiApplication(sys.argv[:1])
    if not ICON.exists():
        print(f"{ICON} is missing, run tools/make_icon.py first", file=sys.stderr)
        return 1

    card = QImage(WIDTH, HEIGHT, QImage.Format_RGB32)
    card.fill(QColor(GROUND))
    painter = QPainter(card)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    # Two washes rather than one gradient across the card, because a straight
    # sweep puts its brightest corner behind the words.
    for centre, radius, colour in (((0.10, 0.10), 0.95, "#b03a6b"),
                                   ((0.92, 1.05), 0.85, "#7a3a2a")):
        glow = QRadialGradient(QPointF(WIDTH * centre[0], HEIGHT * centre[1]), WIDTH * radius)
        warm = QColor(colour)
        warm.setAlpha(150)
        glow.setColorAt(0.0, warm)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(card.rect(), glow)

    side = 250
    painter.drawImage(QRect(145, (HEIGHT - side) // 2, side, side), QImage(str(ICON)))

    left = 483
    title = QFont("Noto Sans")
    title.setPixelSize(92)
    title.setWeight(QFont.Bold)
    painter.setFont(title)
    painter.setPen(QColor(TEXT))
    painter.drawText(QRect(left, 218, WIDTH - left - 60, 110), Qt.AlignVCenter | Qt.AlignLeft, NAME)

    first = QFont("Noto Sans")
    first.setPixelSize(30)
    painter.setFont(first)
    painter.drawText(QRect(left, 352, WIDTH - left - 60, 46), Qt.AlignVCenter | Qt.AlignLeft,
                     LINES[0])

    second = QFont("Noto Sans")
    second.setPixelSize(27)
    painter.setFont(second)
    painter.setPen(QColor(MUTED))
    painter.drawText(QRect(left, 404, WIDTH - left - 60, 42), Qt.AlignVCenter | Qt.AlignLeft,
                     LINES[1])
    painter.end()

    CARD.parent.mkdir(parents=True, exist_ok=True)
    card.save(str(CARD))
    print(f"wrote {CARD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
