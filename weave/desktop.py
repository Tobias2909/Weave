"""Putting Weave in the desktop menu.

Installing the program gives a command, not an entry a panel can show. This
writes that entry and the icons into your own share tree, so
nothing outside the home directory is touched and nothing needs root.

The icon name is `weave` rather than a path, because a panel looks a name up
in the icon theme and picks the size it wants. That is why the same picture is
shipped at nine sizes plus the drawing it was rendered from.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from . import paths

SHARE_DIR = Path(__file__).parent / "share"
TEMPLATE = SHARE_DIR / "weave.desktop"
ENTRY_NAME = "weave.desktop"
ICON_NAME = "weave"

# The sizes a panel, a menu and a task switcher actually ask for. A theme falls
# back to the nearest one, but a scaled picture is soft at the small end, which
# is exactly where the icon spends most of its life.
PNG_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


def _share(data_home: Path | None = None) -> Path:
    return data_home if data_home is not None else paths.data_home()


def _apps_dir(data_home: Path | None = None) -> Path:
    return _share(data_home) / "applications"


def _icons_dir(part: str, data_home: Path | None = None) -> Path:
    return _share(data_home) / "icons" / "hicolor" / part / "apps"


def launcher() -> tuple[str, str | None]:
    """The Exec line to write, and a working directory when one is needed.

    The interpreter is named rather than a bare `weave` command, because that
    name is taken. TeX Live ships `/usr/bin/weave`, its literate programming
    tool, so a menu entry trusting the path can start something else entirely.
    The interpreter that runs this is by definition one that can import Weave.

    A clone is not on that interpreter's import path, so the entry also names
    the clone as its working directory. Running a module puts the working
    directory first on the import path, which is what makes that work, and an
    installed copy needs no directory at all.
    """
    command = sys.executable
    if " " in command:
        command = f'"{command}"'
    root = SHARE_DIR.parent.parent
    if (root / "pyproject.toml").is_file():
        return f"{command} -m weave", str(root)
    return f"{command} -m weave", None


def entry_text(exec_line: str | None = None, work_dir: str | None = None) -> str:
    """The desktop entry as it will be written."""
    if exec_line is None:
        exec_line, work_dir = launcher()
    lines = []
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        if line.startswith("Exec="):
            line = f"Exec={exec_line}"
        lines.append(line)
        if line.startswith("Terminal=") and work_dir:
            lines.append(f"Path={work_dir}")
    return "\n".join(lines) + "\n"


def installed(data_home: Path | None = None) -> list[Path]:
    """Every file an install writes, whether it is there or not."""
    files = [_apps_dir(data_home) / ENTRY_NAME,
             _icons_dir("scalable", data_home) / f"{ICON_NAME}.svg"]
    files += [_icons_dir(f"{size}x{size}", data_home) / f"{ICON_NAME}.png"
              for size in PNG_SIZES]
    return files


def install(data_home: Path | None = None) -> list[Path]:
    written = []

    entry = _apps_dir(data_home) / ENTRY_NAME
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(entry_text(), encoding="utf-8")
    written.append(entry)

    drawing = _icons_dir("scalable", data_home) / f"{ICON_NAME}.svg"
    drawing.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SHARE_DIR / "weave.svg", drawing)
    written.append(drawing)

    for size in PNG_SIZES:
        source = SHARE_DIR / f"weave-{size}.png"
        if not source.exists():
            continue
        target = _icons_dir(f"{size}x{size}", data_home) / f"{ICON_NAME}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        written.append(target)

    return written


def remove(data_home: Path | None = None) -> list[Path]:
    gone = []
    for path in installed(data_home):
        if path.exists():
            path.unlink()
            gone.append(path)
    return gone
