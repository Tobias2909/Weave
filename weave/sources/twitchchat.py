"""A Twitch channel's chat, read the way the site reads it, anonymously.

Twitch's chat is IRC over TLS. Anybody may join a channel to read it under a
made up `justinfan` name with no password that means anything, so nothing here
needs the login. The tags capability adds what the site shows beside a line:
the name as the person writes it, their colour, their roles, the emotes in the
line by position, bits cheered. The commands capability adds what takes lines
away again: a ban or a timeout clears a person's lines, a moderator deletes one.

Emotes come from two places. Twitch's own are named in the tags by where they
sit in the line. 7TV, BetterTTV and FrankerFaceZ add emotes of their own that
are plain words in the line, so each of them is asked for its global set and
the channel's, by the channel's numeric id, which arrives in the room state
right after joining. One answer per set, a few kilobytes each.

Everything about the shapes of those answers is read in this file and nowhere
else, so when one of them moves there is one place to follow it.
"""

from __future__ import annotations

import json
import random
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

HOST = "irc.chat.twitch.tv"
PORT = 6697

TWITCH_EMOTE = "https://static-cdn.jtvnw.net/emoticons/v2/{id}/default/dark/2.0"

# The roles shown as words beside a name, by the badge that carries them, in
# the order they are shown.
ROLES = (("broadcaster", "broadcaster"), ("moderator", "mod"), ("vip", "VIP"),
         ("subscriber", "sub"), ("founder", "sub"))

_ACTION = re.compile("^\x01ACTION (.*)\x01$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ChatError(RuntimeError):
    pass


@dataclass(frozen=True)
class Emote:
    """One emote: where its picture is."""

    name: str
    url: str


@dataclass(frozen=True)
class Line:
    """Something said in the chat."""

    id: str
    user_id: str
    author: str
    colour: str
    roles: tuple[str, ...]
    text: str
    # Twitch's own emotes in the line: (first, last) character and the emote.
    emotes: tuple[tuple[int, int, Emote], ...] = ()
    bits: int = 0
    # Said with /me: the whole line in the person's colour.
    action: bool = False


@dataclass(frozen=True)
class Notice:
    """A subscription, a gift, a raid, an announcement: what happened, and
    whatever the person said with it."""

    id: str
    kind: str
    said: str
    line: Line | None = None


@dataclass(frozen=True)
class Cleared:
    """A ban or a timeout, which takes that person's lines away, or the whole
    chat cleared, with no one named."""

    user_id: str = ""


@dataclass(frozen=True)
class Deleted:
    id: str


@dataclass(frozen=True)
class Room:
    """The channel's numeric id, which the emote services know it by."""

    id: str


Event = Line | Notice | Cleared | Deleted | Room


def _unescape(value: str) -> str:
    """A tag's value, with IRCv3's escapes turned back into what they stand
    for. A lone backslash at the end means nothing and goes."""
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"s": " ", ":": ";", "\\": "\\", "r": "\r", "n": "\n"}.get(nxt, nxt))
            i += 2
            continue
        if ch != "\\":
            out.append(ch)
        i += 1
    return "".join(out)


def parse_tags(blob: str) -> dict[str, str]:
    out = {}
    for pair in blob.split(";"):
        name, _, value = pair.partition("=")
        if name:
            out[name] = _unescape(value)
    return out


def _split(line: str) -> tuple[dict[str, str], str, str, list[str], str]:
    """Tags, who it came from, the command, its arguments and the trailing
    text of one raw line."""
    tags: dict[str, str] = {}
    if line.startswith("@"):
        blob, _, line = line[1:].partition(" ")
        tags = parse_tags(blob)
    prefix = ""
    if line.startswith(":"):
        prefix, _, line = line[1:].partition(" ")
    head, sep, trailing = line.partition(" :")
    parts = head.split()
    command = parts[0] if parts else ""
    return tags, prefix, command, parts[1:], trailing if sep else ""


def roles_of(badges: str) -> tuple[str, ...]:
    held = {badge.split("/", 1)[0] for badge in badges.split(",") if badge}
    out: list[str] = []
    for badge, word in ROLES:
        if badge in held and word not in out:
            out.append(word)
    return tuple(out)


def emotes_of(tag: str, text: str) -> tuple[tuple[int, int, Emote], ...]:
    """Twitch's own emotes, from `id:first-last,first-last/id:...`.

    The places count characters, not bytes, which is what Python counts too.
    A place that does not land on the emote's own name in the line is left
    out rather than painting a picture over some other word.
    """
    found = []
    for part in tag.split("/"):
        emote_id, _, places = part.partition(":")
        if not emote_id or not places:
            continue
        for place in places.split(","):
            first, _, last = place.partition("-")
            try:
                a, b = int(first), int(last)
            except ValueError:
                continue
            name = text[a:b + 1]
            if not name or b >= len(text) or " " in name:
                continue
            found.append((a, b, Emote(name, TWITCH_EMOTE.format(id=emote_id))))
    found.sort(key=lambda one: one[0])
    return tuple(found)


def _line(tags: dict[str, str], prefix: str, text: str) -> Line:
    whole = text
    action = _ACTION.match(text)
    if action:
        text = action.group(1)
    login = prefix.split("!", 1)[0]
    author = (tags.get("display-name") or login or "?").strip()
    clean = _CONTROL.sub("", text)
    # Twitch is not consistent about whether the places in a /me line count
    # the wrapper, so both are tried, and only a place that lands on the
    # emote's own name counts either way.
    tag = tags.get("emotes") or ""
    emotes = emotes_of(tag, text) or (emotes_of(tag, whole) if action else ())
    try:
        bits = int(tags.get("bits") or 0)
    except ValueError:
        bits = 0
    return Line(tags.get("id") or "", tags.get("user-id") or "", author,
                tags.get("color") or "", roles_of(tags.get("badges") or ""),
                clean.strip(), emotes, bits, bool(action))


def parse_line(raw: str) -> Event | None:
    """One line from the server, as what it means for the chat, or None for
    the many lines that mean nothing to it."""
    tags, prefix, command, _args, trailing = _split(raw)
    if command == "PRIVMSG":
        line = _line(tags, prefix, trailing)
        return line if line.text else None
    if command == "USERNOTICE":
        said = (tags.get("system-msg") or "").strip()
        line = _line(tags, prefix, trailing) if trailing else None
        if not said and line is None:
            return None
        return Notice(tags.get("id") or "", tags.get("msg-id") or "", said, line)
    if command == "CLEARCHAT":
        return Cleared(tags.get("target-user-id") or "")
    if command == "CLEARMSG":
        target = tags.get("target-msg-id") or ""
        return Deleted(target) if target else None
    if command == "ROOMSTATE":
        room = tags.get("room-id") or ""
        return Room(room) if room else None
    return None


# ---- reading it ---------------------------------------------------------------

def read(channel: str, said: Callable[[Event], None], cancel: threading.Event,
         connect: Callable[[], socket.socket] | None = None,
         joined: Callable[[], None] | None = None) -> None:
    """Join the channel and hand every event on to `said` until cancelled.

    A dropped connection is joined again after a pause that doubles up to half
    a minute, so a network that comes back finds the chat again by itself.
    """
    pause = 1.0
    while not cancel.is_set():
        try:
            sock = (connect or _connect)()
        except OSError:
            if cancel.wait(pause):
                return
            pause = min(30.0, pause * 2)
            continue
        try:
            sock.settimeout(1.0)
            nick = f"justinfan{random.randint(10000, 99999)}"
            sock.sendall(b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
            sock.sendall(f"PASS SCHMOOPIIE\r\nNICK {nick}\r\n".encode())
            sock.sendall(f"JOIN #{channel.lower()}\r\n".encode())
            if joined is not None:
                joined()
            pause = 1.0
            buffer = b""
            last_heard = time.monotonic()
            while not cancel.is_set():
                try:
                    data = sock.recv(65536)
                except TimeoutError:
                    # Twitch pings every five minutes or so. Nothing at all for
                    # far longer than that is a connection gone quiet.
                    if time.monotonic() - last_heard > 420:
                        break
                    continue
                if not data:
                    break
                last_heard = time.monotonic()
                buffer += data
                while b"\r\n" in buffer:
                    raw, buffer = buffer.split(b"\r\n", 1)
                    text = raw.decode("utf-8", "replace")
                    if text.startswith("PING"):
                        sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                        continue
                    if text.startswith(":tmi.twitch.tv RECONNECT"):
                        raise ConnectionResetError("asked to reconnect")
                    event = parse_line(text)
                    if event is not None:
                        said(event)
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
        if cancel.wait(pause):
            return
        pause = min(30.0, pause * 2)


def _connect() -> socket.socket:
    raw = socket.create_connection((HOST, PORT), timeout=6)
    return ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)


# ---- the emotes of 7TV, BetterTTV and FrankerFaceZ ----------------------------

@dataclass
class EmoteSet:
    """The extra emotes of one channel, by the word that shows each."""

    by_name: dict[str, Emote] = field(default_factory=dict)

    def add(self, name: str, url: str) -> None:
        if name and url:
            self.by_name[name] = Emote(name, url)


def _json(body: bytes):
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return None


def seventv(body: bytes, into: EmoteSet) -> None:
    found = _json(body)
    if not isinstance(found, dict):
        return
    emotes = found.get("emotes")
    if emotes is None:
        # A channel's answer carries its set inside.
        emotes = (found.get("emote_set") or {}).get("emotes")
    for one in emotes or []:
        if isinstance(one, dict) and one.get("id"):
            into.add(str(one.get("name") or ""), f"https://cdn.7tv.app/emote/{one['id']}/2x.webp")


def bttv(body: bytes, into: EmoteSet) -> None:
    found = _json(body)
    lists = [found] if isinstance(found, list) else (
        [found.get("channelEmotes"), found.get("sharedEmotes")] if isinstance(found, dict)
        else [])
    for emotes in lists:
        for one in emotes or []:
            if isinstance(one, dict) and one.get("id"):
                into.add(str(one.get("code") or ""),
                         f"https://cdn.betterttv.net/emote/{one['id']}/2x")


def ffz(body: bytes, into: EmoteSet) -> None:
    found = _json(body)
    sets = found.get("sets") if isinstance(found, dict) else None
    for one_set in (sets or {}).values():
        for one in (one_set or {}).get("emoticons") or []:
            if not isinstance(one, dict):
                continue
            # The moving picture where there is one, at twice the size.
            urls = one.get("animated") or one.get("urls") or {}
            url = str(urls.get("2") or urls.get("1") or "")
            if url.startswith("//"):
                url = "https:" + url
            into.add(str(one.get("name") or ""), url)


GLOBAL_SETS = (
    ("https://7tv.io/v3/emote-sets/global", seventv),
    ("https://api.betterttv.net/3/cached/emotes/global", bttv),
    ("https://api.frankerfacez.com/v1/set/global", ffz),
)
CHANNEL_SETS = (
    ("https://7tv.io/v3/users/twitch/{room}", seventv),
    ("https://api.betterttv.net/3/cached/users/twitch/{room}", bttv),
    ("https://api.frankerfacez.com/v1/room/id/{room}", ffz),
)


def words_with_emotes(text: str, own: tuple[tuple[int, int, Emote], ...],
                      extra: dict[str, Emote]) -> list[tuple[str, Emote | None]]:
    """The line cut into words, each with the emote it shows or None.

    Twitch's own emotes were placed in the line by Twitch, and a word that is
    one of their names is that emote. The others are found by the whole word,
    never a part of one: an emote named D must not land on the D of a word.
    """
    own_names = {emote.name: emote for _first, _last, emote in own}
    return [(word, own_names.get(word) or extra.get(word))
            for word in text.split(" ") if word]
