"""A YouTube broadcast's chat, asked for the way the watch page asks.

The watch page's own next call carries a ticket for the chat beside the
picture, and that ticket asked of live_chat/get_live_chat answers with what
was said since and the next ticket, with how long to wait before using it.
Asked anonymously, with no cookies at all: reading a chat needs no account,
and none of this should ever be done in somebody's name.

MEASURED 2026-10-04 on a stream with 4.5k watching: the first answer carried
75 lines, the last few minutes of the chat, and every answer after it said to
wait ten seconds and carried one to six lines posted over up to nine of them.
The ticket the page starts on is Top chat, YouTube's own choice of lines; the
ticket for every line answered HTTP 400.

A broadcast that has ended keeps its chat as a replay when its owner let it,
and the same ticket from the watch page asked of live_chat/get_live_chat_replay
answers with the lines from a given point of the video on, each with the
moment of the video it was written at, and the ticket that carries on after
the last of them. MEASURED 2026-10-05, anonymously, on Top chat replay: one
answer covers 40 to 100 lines, which is minutes of a quiet chat and only two or
three seconds of a busy one, and the next ticket carries on exactly after the
last line with no line twice. Any ticket asked with a point of the video starts
there, which is how a seek is followed. At the end the answer carries no
lines and no ticket to carry on with.

Everything about the shapes of these answers is read in this file and nowhere
else, so when YouTube moves one there is one place to follow it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..net import Fetcher

ORIGIN = "https://www.youtube.com"
NEXT = ORIGIN + "/youtubei/v1/next?prettyPrint=false"
LIVE = ORIGIN + "/youtubei/v1/live_chat/get_live_chat?prettyPrint=false"
REPLAY = ORIGIN + "/youtubei/v1/live_chat/get_live_chat_replay?prettyPrint=false"

# How long to wait when an answer does not say, and the bounds put on what it
# does say, so a strange answer can neither hammer YouTube nor stall the chat.
DEFAULT_WAIT_MS = 10000
SHORTEST_WAIT_MS = 2000
LONGEST_WAIT_MS = 30000


class NoChat(RuntimeError):
    """The video has no chat to read, or it has ended."""


@dataclass(frozen=True)
class Emoji:
    name: str
    url: str


@dataclass(frozen=True)
class Said:
    """One line, or one paid or celebrated thing, in the chat."""

    id: str
    channel_id: str
    author: str
    roles: tuple[str, ...]
    # The words in order, each with the picture it is when it is an emoji.
    words: tuple[tuple[str, Emoji | None], ...]
    posted_us: int
    # "line", "paid" for a Super Chat or a Super Sticker, "notice" for a new
    # member, a milestone or a gift.
    kind: str = "line"
    amount: str = ""
    # What a notice says happened.
    header: str = ""
    # A Super Sticker's picture.
    sticker: str = ""


@dataclass(frozen=True)
class Removed:
    """A line taken down, or every line of one person."""

    id: str = ""
    channel_id: str = ""


@dataclass(frozen=True)
class Batch:
    events: tuple[Said | Removed, ...]
    ticket: str
    wait_ms: int


@dataclass(frozen=True)
class ReplayBatch:
    """Part of a replay: what was said, each with the moment of the video it
    was said at in milliseconds, and the ticket for what comes after, or none
    at the end."""

    events: tuple[tuple[int, Said | Removed], ...]
    ticket: str


def _context(client_version: str) -> dict:
    return {"client": {"clientName": "WEB", "clientVersion": client_version,
                       "hl": "en", "gl": "US"}}


def _get(found, *path):
    for step in path:
        if isinstance(step, int):
            if not isinstance(found, list) or not -len(found) <= step < len(found):
                return None
            found = found[step]
        else:
            if not isinstance(found, dict):
                return None
            found = found.get(step)
    return found


def _first_value(found) -> dict:
    """The one value of a single-keyed object, which is how YouTube wraps
    every kind of ticket and every kind of item."""
    if isinstance(found, dict):
        for name, value in found.items():
            if name != "clickTrackingParams" and isinstance(value, dict):
                return value
    return {}


def ticket_of(next_answer: dict) -> str:
    """The ticket the watch page starts its chat with, or NoChat."""
    chat = _get(next_answer, "contents", "twoColumnWatchNextResults", "conversationBar",
                "liveChatRenderer")
    ticket = _get(_first_value(_get(chat, "continuations", 0)), "continuation")
    if not isinstance(ticket, str) or not ticket:
        raise NoChat("this video has no chat")
    return ticket


def first_ticket(fetcher: Fetcher, video_id: str, client_version: str) -> str:
    return ticket_of(fetcher.post_json(NEXT, {"videoId": video_id,
                                              "context": _context(client_version)}))


def _text(found) -> str:
    if not isinstance(found, dict):
        return ""
    if isinstance(found.get("simpleText"), str):
        return found["simpleText"]
    return "".join(str(run.get("text") or "") for run in found.get("runs") or []
                   if isinstance(run, dict))


def words_of(message) -> tuple[tuple[str, Emoji | None], ...]:
    """A message's runs as words, an emoji as a word of its own with its
    picture. Every emoji is a picture, YouTube's own as well as a channel's,
    since the font may not have the one written."""
    out: list[tuple[str, Emoji | None]] = []
    for run in (message or {}).get("runs") or []:
        if not isinstance(run, dict):
            continue
        if "emoji" in run:
            emoji = run["emoji"] or {}
            shortcuts = emoji.get("shortcuts") or []
            name = str(shortcuts[0] if shortcuts else emoji.get("emojiId") or "")
            thumbnails = _get(emoji, "image", "thumbnails") or []
            url = str(_get(thumbnails, -1, "url") or "")
            if name:
                out.append((name, Emoji(name, url) if url else None))
            continue
        for word in str(run.get("text") or "").split(" "):
            if word:
                out.append((word, None))
    return tuple(out)


def roles_of(badges) -> tuple[str, ...]:
    out: list[str] = []
    for badge in badges or []:
        found = _get(badge, "liveChatAuthorBadgeRenderer") or {}
        icon = _get(found, "icon", "iconType")
        if icon == "OWNER":
            out.append("broadcaster")
        elif icon == "MODERATOR":
            out.append("mod")
        elif found.get("customThumbnail") is not None:
            out.append("member")
    return tuple(dict.fromkeys(out))


def _posted(item: dict) -> int:
    try:
        return int(item.get("timestampUsec") or 0)
    except (TypeError, ValueError):
        return 0


def said_of(wrapped: dict) -> Said | None:
    """One chat item, or None for what is not something said: a placeholder
    for a line being looked at, YouTube's own reminders, the mode changing."""
    for kind, item in (wrapped or {}).items():
        if not isinstance(item, dict):
            continue
        common = (str(item.get("id") or ""), str(item.get("authorExternalChannelId") or ""),
                  _text(item.get("authorName")).lstrip("@").strip() or "?",
                  roles_of(item.get("authorBadges")))
        if kind == "liveChatTextMessageRenderer":
            words = words_of(item.get("message"))
            return Said(*common, words, _posted(item)) if words else None
        if kind == "liveChatPaidMessageRenderer":
            return Said(*common, words_of(item.get("message")), _posted(item), "paid",
                        _text(item.get("purchaseAmountText")))
        if kind == "liveChatPaidStickerRenderer":
            sticker = str(_get(item, "sticker", "thumbnails", -1, "url") or "")
            if sticker.startswith("//"):
                sticker = "https:" + sticker
            return Said(*common, (), _posted(item), "paid",
                        _text(item.get("purchaseAmountText")), sticker=sticker)
        if kind == "liveChatMembershipItemRenderer":
            # A new member says "Welcome to ..."; a milestone says how long,
            # with whatever the member wrote.
            header = (_text(item.get("headerPrimaryText"))
                      or _text(item.get("headerSubtext")) or "New member")
            return Said(*common, words_of(item.get("message")), _posted(item), "notice",
                        header=header)
        if kind == "liveChatSponsorshipsGiftPurchaseAnnouncementRenderer":
            head = _get(item, "header", "liveChatSponsorshipsHeaderRenderer") or {}
            author = _text(head.get("authorName")).lstrip("@").strip() or "?"
            return Said(common[0], common[1], author, roles_of(head.get("authorBadges")), (),
                        _posted(item), "notice", header=_text(head.get("primaryText")))
        if kind == "liveChatSponsorshipsGiftRedemptionAnnouncementRenderer":
            return Said(*common, (), _posted(item), "notice", header=_text(item.get("message")))
        return None
    return None


def _events_of(actions) -> list[Said | Removed]:
    """What a list of chat actions says happened, in order."""
    events: list[Said | Removed] = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        if "addChatItemAction" in action:
            found = said_of(_get(action, "addChatItemAction", "item"))
            if found is not None:
                events.append(found)
        elif "replaceChatItemAction" in action:
            replaced = action["replaceChatItemAction"] or {}
            found = said_of(replaced.get("replacementItem"))
            if found is not None:
                events.append(found)
        elif "markChatItemAsDeletedAction" in action or "removeChatItemAction" in action:
            target = _first_value(action).get("targetItemId")
            if target:
                events.append(Removed(id=str(target)))
        elif ("markChatItemsByAuthorAsDeletedAction" in action
              or "removeChatItemByAuthorAction" in action):
            target = _first_value(action).get("externalChannelId")
            if target:
                events.append(Removed(channel_id=str(target)))
    return events


def parse(answer: dict) -> Batch:
    """One answer of get_live_chat: what it carries, the next ticket and how
    long to wait before asking with it. NoChat once there is no next ticket,
    which is how YouTube says the broadcast and its chat are over."""
    chat = _get(answer, "continuationContents", "liveChatContinuation")
    if not isinstance(chat, dict):
        raise NoChat("the chat has ended")
    events = _events_of(chat.get("actions"))
    following = _first_value(_get(chat, "continuations", 0))
    ticket = following.get("continuation")
    if not isinstance(ticket, str) or not ticket:
        raise NoChat("the chat has ended")
    try:
        wait = int(following.get("timeoutMs") or DEFAULT_WAIT_MS)
    except (TypeError, ValueError):
        wait = DEFAULT_WAIT_MS
    return Batch(tuple(events), ticket, max(SHORTEST_WAIT_MS, min(LONGEST_WAIT_MS, wait)))


def ask(fetcher: Fetcher, ticket: str, client_version: str) -> Batch:
    return parse(fetcher.post_json(LIVE, {"continuation": ticket,
                                          "context": _context(client_version)}))


def parse_replay(answer: dict) -> ReplayBatch:
    """One answer of get_live_chat_replay. The ticket to carry on with is the
    replay's own; the one beside it is for a seek, which any ticket does as
    well when asked with the new point."""
    chat = _get(answer, "continuationContents", "liveChatContinuation")
    if not isinstance(chat, dict):
        raise NoChat("this video has no chat replay")
    events: list[tuple[int, Said | Removed]] = []
    for action in chat.get("actions") or []:
        replayed = _get(action, "replayChatItemAction")
        if not isinstance(replayed, dict):
            continue
        try:
            at = int(replayed.get("videoOffsetTimeMsec") or 0)
        except (TypeError, ValueError):
            continue
        events.extend((at, one) for one in _events_of(replayed.get("actions")))
    ticket = ""
    for wrapped in chat.get("continuations") or []:
        found = _get(wrapped, "liveChatReplayContinuationData", "continuation")
        if isinstance(found, str) and found:
            ticket = found
            break
    return ReplayBatch(tuple(events), ticket)


def ask_replay(fetcher: Fetcher, ticket: str, client_version: str, at_ms: int) -> ReplayBatch:
    """The replay's lines from this moment of the video on."""
    return parse_replay(fetcher.post_json(REPLAY, {
        "continuation": ticket, "context": _context(client_version),
        "currentPlayerState": {"playerOffsetMs": str(max(0, int(at_ms)))}}))
