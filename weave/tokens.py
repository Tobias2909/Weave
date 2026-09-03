"""Where the Twitch login is kept.

The access token and the refresh token are the only secrets Weave holds, so the
file is written with owner only permissions and lives in the state directory
rather than anywhere near the repository.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from . import paths
from .sources.twitch import Tokens

TOKEN_FILE = paths.STATE_DIR / "twitch.json"
OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR


def load(path: Path | None = None) -> Tokens | None:
    target = path or TOKEN_FILE
    try:
        return Tokens.from_dict(json.loads(target.read_text()))
    except (OSError, ValueError):
        return None


def save(tokens: Tokens, path: Path | None = None) -> None:
    """Written through a temporary file so an interrupted write cannot leave a
    half a login behind, and created with owner only permissions so the tokens
    are never briefly readable by anyone else."""
    target = path or TOKEN_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent)
    try:
        os.fchmod(handle, OWNER_ONLY)
        with os.fdopen(handle, "w") as sink:
            json.dump(tokens.as_dict(), sink)
        os.replace(temporary, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def clear(path: Path | None = None) -> bool:
    target = path or TOKEN_FILE
    try:
        target.unlink()
        return True
    except OSError:
        return False
