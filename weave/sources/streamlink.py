"""A Twitch stream through streamlink, for the window's player.

streamlink is used when the machine has it, because it is what a Twitch viewer
on this kind of setup has usually made their own: its plugins and its config
apply to every call made here, which is how somebody's own way of watching
reaches Weave without Weave knowing anything about it. Without it, yt-dlp
plays the stream instead.

One call answers everything: every quality the stream is offered in, each with
its own address, and what the stream is called. MEASURED 2026-10-04 on six
live channels, 1.1 to 1.6 seconds a call, offered from 160p30 up to 1080p60
(one 936p60), the same list signed in as not.

streamlink asks Twitch for h264 alone unless told otherwise, and yt-dlp already
asks for av1, h265 and h264, so it is told the same.

The browser's Twitch login goes along, so whatever that account is entitled to,
fewer adverts with Turbo or a subscription, is what plays here too. It is
written into a config file of its own that only this user can read, rather than
onto the command line, where every process on the machine can read it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..process import run as run_process

CODECS = "av1,h265,h264"

# A stream name that is a picture: 1080p60, 720p, 936p60.
_NAMED = re.compile(r"^(\d+)p(\d+)?$")


class StreamlinkError(RuntimeError):
    pass


class Offline(StreamlinkError):
    """The channel is not streaming, which is an answer and not a failure."""


@dataclass(frozen=True)
class Offered:
    """One quality of a stream."""

    name: str
    height: int
    fps: int
    url: str


@dataclass(frozen=True)
class Answer:
    offered: tuple[Offered, ...]
    title: str = ""
    author: str = ""
    category: str = ""
    # Every height on offer, tallest first, for the quality menu.
    heights: tuple[int, ...] = field(default=())


def available() -> bool:
    return shutil.which("streamlink") is not None


def _own_config() -> Path:
    """streamlink's own config on this machine, where it keeps one. Naming a
    config file of ours on the command line stops streamlink reading its own,
    so it is named first and ours goes on top."""
    home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return home / "streamlink" / "config"


def command(login: str, config_file: str | None = None) -> list[str]:
    configs: list[str] = []
    if config_file:
        own = _own_config()
        if own.is_file():
            configs += ["--config", str(own)]
        configs += ["--config", config_file]
    return ["streamlink", *configs, "--json", "--twitch-supported-codecs", CODECS,
            f"https://www.twitch.tv/{login}"]


def parse(text: str) -> Answer:
    """What one call printed."""
    try:
        found = json.loads(text or "")
    except ValueError as exc:
        raise StreamlinkError("streamlink answered with something that is not JSON") from exc
    if not isinstance(found, dict):
        raise StreamlinkError("streamlink answered with something unexpected")
    if found.get("error"):
        said = str(found["error"])
        if "No playable streams" in said:
            raise Offline("the stream is offline")
        raise StreamlinkError(said)
    offered = []
    for name, stream in (found.get("streams") or {}).items():
        matched = _NAMED.match(str(name))
        if not matched or not isinstance(stream, dict) or not stream.get("url"):
            continue
        offered.append(Offered(str(name), int(matched.group(1)), int(matched.group(2) or 30),
                               str(stream["url"])))
    if not offered:
        raise Offline("the stream is offline")
    offered.sort(key=lambda one: (one.height, one.fps), reverse=True)
    meta = found.get("metadata") or {}

    def said(name: str) -> str:
        value = meta.get(name)
        return value.strip() if isinstance(value, str) else ""

    return Answer(tuple(offered), said("title"), said("author"), said("category"),
                  tuple(sorted({one.height for one in offered}, reverse=True)))


def pick(answer: Answer, height: int) -> Offered:
    """The tallest quality that fits under the ceiling, the smoother of two
    the same height, or the smallest there is when nothing fits."""
    fitting = [one for one in answer.offered if one.height <= int(height)]
    if fitting:
        return fitting[0]
    return answer.offered[-1]


def ask(login: str, token: str = "", cancel: threading.Event | None = None,
        timeout: float = 60.0) -> Answer:
    """Every quality the stream is offered in, blocking. About a second."""
    config_file = None
    try:
        if token:
            # Made readable by this user alone before anything is written, and
            # gone again as soon as streamlink has read it.
            handle, config_file = tempfile.mkstemp(prefix="weave-streamlink-", suffix=".conf")
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                out.write(f"twitch-api-header=Authorization=OAuth {token}\n")
        result = run_process(command(login, config_file), cancel=cancel, timeout=timeout)
    finally:
        if config_file:
            try:
                os.unlink(config_file)
            except OSError:
                pass
    return parse(result.stdout)
