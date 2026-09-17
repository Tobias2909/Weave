"""What is kept on disk for the songs he keeps, sound and picture alike.

A song is a stream at both ends: yt-dlp finds an address, mpv reads it, and
nothing is written down. That is right for a song played once and wrong for
the handful played over and over, which pay the whole cost every time. The
address takes a few seconds to find, the picture a couple more to arrive, and
all of it happens again on the next play of the same song tomorrow.

So the favourites, and only the favourites, keep theirs. A favourite is a
short list somebody curated by hand, which is what makes this bounded: on a
real library it is eighteen songs, and at the default ceiling a three and a
half minute video measured 29 MiB against 3.3 MiB for its sound, so the whole
set is about half a gigabyte against a ceiling offered in gigabytes.

Both halves, because keeping one and streaming the other leaves the wait in
place. The sound is the cheaper of the two by a factor of nine and is the half
that has to arrive before anything can be heard at all.

A kept file is better than a kept address as well as faster. A signed address
expires within hours, and a file does not expire at all.

What this does NOT do is fetch anything by itself. Something is kept because
it was played, so the first play of a favourite costs one extra download in
the background and every play after it costs nothing. Fetching all of them up
front would be half a gigabyte nobody asked for.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

# What the settings page offers as a ceiling, in megabytes. Shaped like the
# picture cache's own list, and starting higher because one video is worth more
# than a thousand thumbnails. Powers of 1024 rather than round decimal numbers,
# because these are read back as gigabytes and 10000 MB is nine and three
# quarters of one, which is what the button said.
CEILING_STEPS_MB: tuple[int, ...] = (512, 1024, 2048, 5120, 10240, 20480)
DEFAULT_CEILING_MB = 2048

# A part file yt-dlp is still writing. Never counted and never handed to the
# player, or a half written video would be played as a whole one.
PARTIAL_SUFFIXES = (".part", ".ytdl", ".tmp")


# The sound of a song, as opposed to a height, which is what a picture is filed
# under. One word rather than a number, so the two can never collide.
SOUND = "sound"


def _stem(key: str, mark: str | int) -> str:
    """What one file of a song is filed under.

    The key is hashed rather than used, the way the picture cache does it: a
    video id is safe in a filename but a Twitch key is not, and one rule for
    both is one rule to get wrong. The mark rides along because the sound and
    the picture of the same song are two files, and because a picture kept at
    one ceiling and asked for at another is a different file rather than a
    wrong one.
    """
    digest = hashlib.sha1(f"{key}@{mark}".encode()).hexdigest()
    return f"{digest[:2]}/{digest}"


def held(directory: Path, key: str, mark: str | int) -> Path | None:
    """The file kept for this song, or None.

    Found by pattern rather than by name, since what yt-dlp writes ends in
    whatever container the format came in and that is not known in advance.
    """
    stem = _stem(key, mark)
    folder = directory / Path(stem).parent
    name = Path(stem).name
    try:
        found = sorted(folder.glob(f"{name}.*"))
    except OSError:
        return None
    for path in found:
        if path.suffix in PARTIAL_SUFFIXES or not path.is_file():
            continue
        try:
            if path.stat().st_size > 0:
                return path
        except OSError:
            continue
    return None


def target(directory: Path, key: str, mark: str | int) -> Path:
    """Where to tell yt-dlp to write, extension left to it."""
    path = directory / _stem(key, mark)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def touch(path: Path) -> None:
    """Note that this one was played, so the oldest unplayed goes first when
    room is needed. The file's own modified time is the record, which survives
    a restart and needs no table of its own."""
    try:
        os.utime(path, None)
    except OSError:
        pass


@dataclass(frozen=True)
class Kept:
    path: Path
    bytes: int
    used_at: float


def contents(directory: Path) -> list[Kept]:
    """Every whole video kept, oldest use first."""
    out: list[Kept] = []
    if not directory.exists():
        return out
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix in PARTIAL_SUFFIXES:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append(Kept(path, stat.st_size, stat.st_mtime))
    out.sort(key=lambda one: one.used_at)
    return out


def held_bytes(directory: Path) -> int:
    return sum(one.bytes for one in contents(directory))


def prune(directory: Path, ceiling_bytes: int, keep: set[str] | None = None) -> tuple[int, int]:
    """Bring the directory under its ceiling, and drop what is no longer kept.

    Two rules, in that order. A video whose song is no longer a favourite goes
    whatever the ceiling says, because the only reason it was written down has
    gone. Then, while the rest is over the ceiling, the one played longest ago
    goes first, which is the ordinary way round: the one not reached for in
    months is the one least worth the room.

    Answers how many files went and how many bytes that freed.
    """
    gone = held = 0
    wanted = None if keep is None else {path.resolve() for path in keep}
    for one in contents(directory):
        if wanted is not None and one.path.resolve() not in wanted:
            if _drop(one.path):
                gone += 1
                held += one.bytes
    if ceiling_bytes <= 0:
        return gone, held
    left = contents(directory)
    total = sum(one.bytes for one in left)
    for one in left:
        if total <= ceiling_bytes:
            break
        if _drop(one.path):
            gone += 1
            held += one.bytes
            total -= one.bytes
    return gone, held


def _drop(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


def forget_all(directory: Path) -> tuple[int, int]:
    """Everything, for the button that says so."""
    files = contents(directory)
    total = sum(one.bytes for one in files)
    try:
        shutil.rmtree(directory)
    except OSError:
        return 0, 0
    directory.mkdir(parents=True, exist_ok=True)
    return len(files), total
