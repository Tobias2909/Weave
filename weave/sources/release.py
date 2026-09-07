"""Whether the repository has a newer release than the copy that is running.

The releases endpoint rather than the tags one, for two reasons. It leaves out
drafts and prereleases on its own, so a version that is not meant for anybody
yet cannot be announced here, and it carries the address of the release page,
which is where somebody told about a new version wants to end up.

Unauthenticated, which is sixty requests an hour from one address, against the
one request a day this makes. Nothing is sent but the request itself, and the
answer is a version string, so there is nothing here to keep private beyond the
fact that a copy of the program was started.
"""

from __future__ import annotations

import json
import re

from ..net import Fetcher

LATEST = "https://api.github.com/repos/Tobias2909/Weave/releases/latest"

# A version as the tags carry it, with or without the v. Anything after the
# numbers is ignored rather than ranked, since a prerelease never reaches this
# endpoint in the first place.
NUMBERS = re.compile(r"v?(\d+(?:\.\d+)*)")


class ReleaseError(RuntimeError):
    pass


def numbers_of(tag: str) -> tuple[int, ...] | None:
    """The numbers in a tag, or nothing if it carries none."""
    found = NUMBERS.match((tag or "").strip())
    if not found:
        return None
    return tuple(int(part) for part in found.group(1).split("."))


def is_newer(offered: str, running: str) -> bool:
    """Whether the offered version is above the running one.

    Missing parts count as zero, so 1.1 is above 1.0.3 and equal to 1.1.0.
    A tag nobody can read is never newer, because announcing an update that
    cannot be compared is worse than saying nothing.
    """
    there, here = numbers_of(offered), numbers_of(running)
    if there is None or here is None:
        return False
    length = max(len(there), len(here))
    padded = there + (0,) * (length - len(there))
    mine = here + (0,) * (length - len(here))
    return padded > mine


def numbers_text(tag: str) -> str:
    """A tag as a version to show, so a v or anything after the numbers does
    not reach the window."""
    numbers = numbers_of(tag)
    return ".".join(str(part) for part in numbers) if numbers else ""


def parse(payload: bytes) -> tuple[str, str]:
    """The tag and the address of the release page."""
    try:
        found = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ReleaseError(f"the answer was not readable, {exc}") from exc
    if not isinstance(found, dict):
        raise ReleaseError("the answer was not a release")
    tag = str(found.get("tag_name") or "").strip()
    if not tag:
        raise ReleaseError("the release carries no tag")
    return tag, str(found.get("html_url") or "").strip()


def fetch(fetcher: Fetcher) -> tuple[str, str]:
    return parse(fetcher.get_bytes(LATEST))
