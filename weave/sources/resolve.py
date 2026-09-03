"""Turning a channel handle into a channel id.

Why this goes through yt-dlp rather than a page scrape. The channel page does
carry the id, in the canonical link and in an externalId field, but only when
the request looks like a browser. Sent with an honest user agent, YouTube
answers with a 34 KB stub containing none of it. Spoofing a browser to scrape a
page is a worse dependency than calling a tool that already speaks the private
API properly, and yt-dlp is already needed for everything past RSS.

Worth knowing if anyone ever revisits the scrape. The first "channelId" in that
HTML is NOT the channel's own id, it belongs to something in a shelf on the
page. Only the canonical link and externalId are the channel itself, and they
agree with what yt-dlp returns.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from ..ids import CHANNEL_ID, ChannelRef, channel_key
from ..net import Throttle

# Asking for zero items returns the playlist level fields and downloads no
# entries at all, which is what keeps this to about half a second.
_COMMAND = [
    "yt-dlp", "--no-warnings", "--flat-playlist",
    "--playlist-items", "0",
    "--print", "playlist:%(channel_id)s|%(channel)s",
]


class ResolveError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedChannel:
    platform: str
    ext_id: str
    title: str | None

    @property
    def key(self) -> str:
        return channel_key(self.ext_id, self.platform)


def parse_output(text: str) -> tuple[str, str | None]:
    """Read the printed `id|title` line. Separated out so it can be tested
    without a network call."""
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    ext_id, _, title = line.partition("|")
    ext_id = ext_id.strip()
    if not CHANNEL_ID.match(ext_id):
        raise ResolveError("no channel id in the response")
    title = title.strip()
    return ext_id, (title if title and title != "NA" else None)


def resolve(ref: ChannelRef, throttle: Throttle | None = None,
            timeout: float = 60.0) -> ResolvedChannel:
    """Resolve a reference to something storable.

    A YouTube id is looked up too, not only a handle. The lookup costs the same
    half second either way and buys two things, a mistyped id is caught at the
    moment it is typed instead of failing quietly at the next poll, and the
    channel gets its real name straight away rather than showing as unnamed.

    That lookup is not allowed to be a hard requirement though. A missing
    yt-dlp or a dead network must not stop a perfectly valid id from being
    stored, so those cases fall back to storing it unverified. Only a definite
    "no such channel" is treated as a rejection.

    A Twitch login is already its own id and is accepted as is, until the Helix
    credentials exist to check it.
    """
    if ref.platform != "youtube":
        return ResolvedChannel(ref.platform, ref.value, None)

    def run() -> subprocess.CompletedProcess:
        return subprocess.run([*_COMMAND, ref.url], capture_output=True,
                              text=True, timeout=timeout)

    try:
        if throttle is not None:
            with throttle.slot():
                result = run()
        else:
            result = run()
    except FileNotFoundError as exc:
        return _unverified(ref, "yt-dlp is not installed", exc)
    except subprocess.TimeoutExpired as exc:
        return _unverified(ref, "the lookup timed out", exc)

    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else "unknown error"
        if "404" in detail or "not exist" in detail.lower():
            raise ResolveError("no such channel")
        return _unverified(ref, detail[:120], None)

    try:
        ext_id, title = parse_output(result.stdout)
    except ResolveError as exc:
        return _unverified(ref, str(exc), exc)
    return ResolvedChannel("youtube", ext_id, title)


def _unverified(ref: ChannelRef, reason: str, cause: Exception | None) -> ResolvedChannel:
    """Store a plain id anyway when the lookup itself failed rather than the
    channel being absent. A handle has no such fallback, since without the
    lookup there is nothing to store."""
    if ref.kind == "id":
        return ResolvedChannel("youtube", ref.value, None)
    raise ResolveError(reason) from cause
