"""The chat beside a broadcast played in the window.

Twitch's chat is read anonymously over IRC, and arrives as it is typed.
YouTube's is asked for every ten seconds or so, anonymously as well, and each
answer carries what was posted over the seconds since the last one, so it is
let out again at the pace it was posted: every line is shown the same time
after it was written, which is a little longer than the longest any line took
to reach here. The first answer is what was said before the page opened, and
is shown at once.

A line is held back a moment while its emotes are fetched, so it appears whole
rather than with pictures popping in, and never for long: one that does not
come in time is drawn from the network instead. Every emote is fetched once
and kept on disk.

YouTube is only asked while the chat is on screen. The newest line is at the
bottom, and the last five hundred are kept, more while somebody has scrolled
up to read, so what they are reading is not taken away from under them.

A past broadcast's chat, where YouTube kept it, is played back with the video:
each line comes when the video reaches the moment it was written at, so it
pauses, speeds up and follows a seek with the picture. What is fetched runs a
little ahead of the video, asked for as the video gets near its end.
"""

from __future__ import annotations

import bisect
import collections
import concurrent.futures
import hashlib
import itertools
import queue
import time
import zlib
from pathlib import Path

from PySide6.QtCore import (Property, QAbstractListModel, QByteArray, QModelIndex, QObject, Qt,
                            QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QImageReader

from . import net, paths, trace
from .budget import CHAT, CHAT_REPLAY, EMOTES, Budget
from .config import Config
from .poller import Worker
from .sources import twitchchat, youtubechat
from .sources.watchnext import client_version

# The colours a name is drawn in when it has none of its own: every name on
# YouTube, and a Twitch name whose owner never picked one. Chosen to read on a
# dark ground, and darkened by the page on a light one.
PALETTE = (
    "#FF4C4C", "#FF7F50", "#FFA500", "#DAA520",
    "#9ACD32", "#3CB371", "#2ECC71", "#00CED1",
    "#1E90FF", "#5F9EA0", "#7B9BFF", "#B18CFF",
    "#FF69B4", "#FF8AC7", "#D2691E", "#20B2AA",
)

KEEP = 500
# While somebody has scrolled up to read, nothing is taken off the top until
# this many, so the line being read stays where it is.
KEEP_WHILE_HELD = 2000

TICK_MS = 100
# The longest a line waits for its emotes before it is drawn without the ones
# that have not come.
EMOTE_WAIT_S = 1.5
# How many answers back the time a YouTube line takes to get here is
# remembered, the longest of which every line is held behind its posting.
LAG_ANSWERS = 6
LONGEST_LAG_S = 30.0

EMOTE_DIR = paths.CACHE_DIR / "emotes"
# An emote not drawn for this long is taken off the disk.
EMOTE_KEEP_S = 30 * 86400

# Short, so a request under way at the moment the window closes cannot keep
# a thread alive past the wait for it.
NET_TIMEOUT_S = 6.0

# How the chat shows while the picture fills the screen: not at all, in a
# column beside a smaller picture, or in a panel over it. Kept between runs, as
# is where the panel was put and how big it was made, in shares of the screen.
FULL_MODES = ("full", "beside", "over")
MODE_STATE = "video_chat_mode"
OVER_STATE = "video_chat_over"
# A sixth of the screen wide and a quarter high, near the top, with a sixth of
# the screen left clear on its right: the shape of the panel this replaces.
OVER_DEFAULT = (4 / 6, 0.02, 1 / 6, 1 / 4)
SMALLEST_OVER = (0.08, 0.12)

# A YouTube call that fails is tried again after this, doubling each time.
RETRY_S = 5.0
LONGEST_RETRY_S = 60.0

# A chat replay is fetched this far ahead of the video, and after a seek starts
# this far before the new place, so the column is not empty there. A jump of
# the video backwards by more than the first, or forwards by more than the
# second, is a seek; seeks in a row are waited out for the third.
REPLAY_AHEAD_S = 15.0
REPLAY_HISTORY_S = 10.0
REPLAY_BACK_S = 1.5
REPLAY_JUMP_S = 8.0
REPLAY_SETTLE_S = 0.4
# Which side of the column a past broadcast with a chat opens on: the one
# picked last time, the chat until anything is.
REPLAY_COLUMN_STATE = "video_chat_replay_column"


def colour_for(name: str) -> str:
    """Same name, same colour, every time and in every run. A checksum and
    not hash(), which Python seeds afresh in every process."""
    return PALETTE[zlib.crc32(name.lower().encode("utf-8")) % len(PALETTE)]


def chat_kind(entry: dict) -> str:
    """Which chat a video has, if any: a Twitch channel's, a YouTube
    broadcast's while it is on air, the replay of one that has ended, or
    none."""
    if not entry:
        return ""
    youtube = str(entry.get("key") or "").startswith("yt:")
    if not entry.get("live"):
        return "replay" if youtube and entry.get("chat_replay") else ""
    if entry.get("login"):
        return "twitch"
    return "youtube" if youtube else ""


# ---- the list QML draws ------------------------------------------------------

class ChatModel(QAbstractListModel):
    """The lines, oldest first."""

    NAMES = ("key", "who", "author", "colour", "roles", "pieces", "kind", "amount", "header",
             "sticker", "action")
    ROLES = {Qt.ItemDataRole.UserRole + 1 + place: name for place, name in enumerate(NAMES)}

    countChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def roleNames(self) -> dict:
        return {role: QByteArray(name.encode()) for role, name in self.ROLES.items()}

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        name = self.ROLES.get(role)
        return self._rows[index.row()].get(name) if name else None

    @property
    def rows(self) -> list[dict]:
        return self._rows

    def append(self, rows: list[dict]) -> None:
        if not rows:
            return
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(rows) - 1)
        self._rows.extend(rows)
        self.endInsertRows()
        self.countChanged.emit()

    def trim(self, keep: int) -> int:
        """Take the oldest off until `keep` are left; how many went."""
        extra = len(self._rows) - keep
        if extra <= 0:
            return 0
        self.beginRemoveRows(QModelIndex(), 0, extra - 1)
        del self._rows[:extra]
        self.endRemoveRows()
        self.countChanged.emit()
        return extra

    def remove_where(self, test) -> int:
        """Take out every line `test` says, newest first so the places of the
        ones still to go do not move."""
        gone = 0
        place = len(self._rows) - 1
        while place >= 0:
            if not test(self._rows[place]):
                place -= 1
                continue
            last = place
            while place - 1 >= 0 and test(self._rows[place - 1]):
                place -= 1
            self.beginRemoveRows(QModelIndex(), place, last)
            del self._rows[place:last + 1]
            self.endRemoveRows()
            gone += last - place + 1
            place -= 1
        if gone:
            self.countChanged.emit()
        return gone

    def clear(self) -> None:
        if not self._rows:
            return
        self.beginResetModel()
        self._rows = []
        self.endResetModel()
        self.countChanged.emit()

    count = Property(int, lambda self: len(self._rows), notify=countChanged)


# ---- the emotes on disk -------------------------------------------------------

def _sniffed(body: bytes) -> str:
    """The kind of picture by its first bytes, for the name of its file: the
    addresses rarely say, and the picture reader is surer with a name."""
    if body.startswith(b"GIF8"):
        return ".gif"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return ".webp"
    if body.startswith(b"\x89PNG"):
        return ".png"
    if body[4:12] in (b"ftypavif", b"ftypavis"):
        return ".avif"
    if body.startswith(b"\xff\xd8"):
        return ".jpg"
    return ".img"


def _looked_at(path: Path) -> tuple[bool, float]:
    """Whether a picture moves, and how wide it is for its height."""
    reader = QImageReader(str(path))
    size = reader.size()
    ratio = size.width() / size.height() if size.isValid() and size.height() > 0 else 1.0
    moves = reader.supportsAnimation() and reader.imageCount() != 1
    return moves, max(0.5, min(4.0, ratio))


class _EmoteFetcher(Worker):
    """Fetches emotes onto the disk, a few at a time, as they are asked for."""

    ready = Signal(str, str, bool, float)

    def __init__(self, cfg: Config, directory: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._directory = directory
        self._wanted: queue.Queue[str] = queue.Queue()

    def want(self, url: str) -> None:
        self._wanted.put(url)

    def _prune(self) -> None:
        cutoff = time.time() - EMOTE_KEEP_S
        for path in self._directory.glob("*"):
            try:
                if path.stat().st_atime < cutoff and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    def _one(self, fetcher: net.Fetcher, url: str) -> None:
        stem = hashlib.sha1(url.encode()).hexdigest()
        found = next(iter(self._directory.glob(stem + ".*")), None)
        if found is None:
            try:
                body = fetcher.get_bytes(url)
            except net.Cancelled:
                return
            except Exception as exc:
                trace.mark("emote_failed", url=url, why=f"{type(exc).__name__}: {exc}")
                return
            found = self._directory / (stem + _sniffed(body))
            partial = found.with_suffix(found.suffix + ".part")
            partial.write_bytes(body)
            partial.replace(found)
        moves, ratio = _looked_at(found)
        if not self.cancelled:
            self.ready.emit(url, QUrl.fromLocalFile(str(found)).toString(), moves, ratio)

    def work(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._prune()
        fetcher = net.Fetcher(net.Throttle(4, 0.0), timeout=NET_TIMEOUT_S, attempts=1,
                              cancel=self._cancel)
        # Not waited for on the way out: a download under way finishes or
        # times out on its own, and this thread is free to end at once.
        pool = concurrent.futures.ThreadPoolExecutor(4)
        try:
            while not self.cancelled:
                try:
                    url = self._wanted.get(timeout=0.3)
                except queue.Empty:
                    continue
                pool.submit(self._one, fetcher, url)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


# ---- the readers ---------------------------------------------------------------

class _TwitchReader(Worker):
    """Reads one Twitch channel's chat into the inbox until cancelled."""

    def __init__(self, login: str, inbox: collections.deque, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.login = login
        self._inbox = inbox

    def work(self) -> None:
        twitchchat.read(self.login, self._inbox.append, self._cancel,
                        joined=lambda: self._inbox.append(("joined",)))


class _EmoteSets(Worker):
    """Asks 7TV, BetterTTV and FrankerFaceZ for the emotes of one channel and
    their global ones. A service that does not answer costs only its own."""

    found = Signal(str, dict)

    def __init__(self, db, cfg: Config, room: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self.room = room

    def work(self) -> None:
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        wanted = [(url, read) for url, read in twitchchat.GLOBAL_SETS]
        wanted += [(url.format(room=self.room), read) for url, read in twitchchat.CHANNEL_SETS]
        granted = budget.allowance(EMOTES, len(wanted)).granted
        found = twitchchat.EmoteSet()
        fetcher = net.Fetcher(net.Throttle(3, 0.0), timeout=NET_TIMEOUT_S, attempts=1,
                              cancel=self._cancel)
        try:
            for url, read in wanted[:granted]:
                budget.spend(EMOTES)
                try:
                    read(fetcher.get_bytes(url), found)
                except net.Cancelled:
                    return
                except Exception as exc:
                    # A channel with no emotes on a service is a 404, which
                    # is an answer and no failure.
                    if not (isinstance(exc, net.HttpError) and exc.status == 404):
                        budget.spend(EMOTES, count=0, refused=1)
                        trace.mark("emote_set_failed", url=url, why=f"{type(exc).__name__}")
        finally:
            fetcher.close()
        self.found.emit(self.room, {name: emote.url for name, emote in found.by_name.items()})


class _YouTubeAsker(Worker):
    """What asking YouTube about one video's chat takes, live or played back."""

    LINE = CHAT

    def __init__(self, db, cfg: Config, video_id: str, inbox: collections.deque,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self.video_id = video_id
        self._inbox = inbox

    def _wait(self, seconds: float) -> bool:
        """False once cancelled."""
        return not self._cancel.wait(max(0.0, seconds))

    def _room(self, budget: Budget) -> bool:
        """Whether there is room to ask now, waiting for it if there is not."""
        while True:
            allowed = budget.allowance(self.LINE)
            if not allowed.empty:
                return True
            self._inbox.append(("paused",))
            if not self._wait(max(5.0, allowed.frees_at - time.time())):
                return False


class _YouTubeReader(_YouTubeAsker):
    """Asks one YouTube broadcast's chat for what was said, for as long as it
    is wanted, waiting between answers as long as each answer asks."""

    def work(self) -> None:
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        fetcher = net.Fetcher(net.Throttle(1, 0.0), timeout=NET_TIMEOUT_S, attempts=1,
                              cancel=self._cancel)
        version = client_version()
        ticket = ""
        first = True
        retry = RETRY_S
        try:
            while not self.cancelled:
                if not self._room(budget):
                    return
                budget.spend(CHAT)
                try:
                    if not ticket:
                        ticket = youtubechat.first_ticket(fetcher, self.video_id, version)
                        budget.spend(CHAT)
                    batch = youtubechat.ask(fetcher, ticket, version)
                except youtubechat.NoChat as exc:
                    self._inbox.append(("ended", str(exc)))
                    return
                except net.Cancelled:
                    return
                except Exception as exc:
                    budget.spend(CHAT, count=0, refused=1)
                    trace.mark("chat_failed", video=self.video_id,
                               why=f"{type(exc).__name__}: {exc}")
                    self._inbox.append(("trouble",))
                    # A ticket refused may be one that went stale; the next
                    # try starts from the watch page again.
                    ticket = ""
                    if not self._wait(retry):
                        return
                    retry = min(LONGEST_RETRY_S, retry * 2)
                    continue
                retry = RETRY_S
                self._inbox.append(("youtube", time.time(), time.monotonic(), batch.events, first))
                first = False
                ticket = batch.ticket
                if not self._wait(batch.wait_ms / 1000.0):
                    return
        finally:
            fetcher.close()


class _ReplayReader(_YouTubeAsker):
    """Asks a past broadcast's chat replay for its lines from a moment of the
    video on, whenever the room wants more. Only the newest want is answered:
    one made before a seek is about a place the video has left."""

    LINE = CHAT_REPLAY

    def __init__(self, db, cfg: Config, video_id: str, inbox: collections.deque,
                 parent: QObject | None = None) -> None:
        super().__init__(db, cfg, video_id, inbox, parent)
        self._wants: queue.Queue[tuple[int, int, str]] = queue.Queue()

    def want(self, round_: int, at_ms: int, ticket: str = "") -> None:
        """The lines from `at_ms` on, carrying on from `ticket` when there is
        one. `round_` is handed back, so an answer for a place left is known."""
        self._wants.put((round_, at_ms, ticket))

    def _newest(self) -> tuple[int, int, str] | None:
        try:
            wanted = self._wants.get(timeout=0.3)
        except queue.Empty:
            return None
        while True:
            try:
                wanted = self._wants.get_nowait()
            except queue.Empty:
                return wanted

    def work(self) -> None:
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        fetcher = net.Fetcher(net.Throttle(1, 0.0), timeout=NET_TIMEOUT_S, attempts=1,
                              cancel=self._cancel)
        version = client_version()
        first = ""
        retry = RETRY_S
        try:
            while not self.cancelled:
                wanted = self._newest()
                if wanted is None:
                    continue
                round_, at_ms, ticket = wanted
                if not self._room(budget):
                    return
                budget.spend(CHAT_REPLAY)
                try:
                    if not first:
                        first = youtubechat.first_ticket(fetcher, self.video_id, version)
                        budget.spend(CHAT_REPLAY)
                    batch = youtubechat.ask_replay(fetcher, ticket or first, version, at_ms)
                except youtubechat.NoChat as exc:
                    self._inbox.append(("ended", str(exc)))
                    return
                except net.Cancelled:
                    return
                except Exception as exc:
                    budget.spend(CHAT_REPLAY, count=0, refused=1)
                    trace.mark("chat_failed", video=self.video_id,
                               why=f"{type(exc).__name__}: {exc}")
                    self._inbox.append(("trouble",))
                    # Asked again from the watch page's own ticket, unless a
                    # newer want has come meanwhile.
                    first = ""
                    if not self._wait(retry):
                        return
                    retry = min(LONGEST_RETRY_S, retry * 2)
                    if self._wants.empty():
                        self._wants.put((round_, at_ms, ""))
                    continue
                retry = RETRY_S
                self._inbox.append(("replay", round_, batch))
        finally:
            fetcher.close()


# ---- the room ------------------------------------------------------------------

class ChatRoom(QObject):
    """The chat of the video playing in the window, while there is one."""

    changed = Signal()

    def __init__(self, cfg: Config, db=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._db = db
        self._model = ChatModel(self)
        self._kind = ""
        self._source = ""      # the login or the video id
        self._shown = False
        # Where the video is, which a chat replay follows; which round of
        # asking it is on, a seek starting a new one; how far into the video
        # its lines are fetched, the ticket to carry on with, whether an
        # answer is awaited, whether the replay has run out, and when the
        # video has stood still long enough after a seek to ask.
        self._position = 0.0
        self._round = 0
        self._fetched_to = 0.0
        self._replay_ticket = ""
        self._asking = False
        self._replay_done = False
        self._ask_after = 0.0
        self._held = False
        self._unseen = 0
        self._status = ""
        # What the column beside the picture shows: the queue or the chat.
        self._column = "queue"
        self._inbox: collections.deque = collections.deque()
        self._reader: Worker | None = None
        self._readers: list[Worker] = []
        # Lines waiting for their moment, in the order they are due: (due,
        # order, row, emote addresses).
        self._pending: list[tuple[float, int, dict, tuple[str, ...]]] = []
        self._order = itertools.count()
        self._lags: collections.deque[float] = collections.deque(maxlen=LAG_ANSWERS)
        # The extra emotes of the Twitch channel, by word, once they are known.
        self._extra: dict[str, twitchchat.Emote] = {}
        self._room = ""
        self._sets: dict[str, dict[str, str]] = {}
        # Every emote asked for: its file, whether it moves and its shape, or
        # None while it is on its way.
        self._emotes: dict[str, tuple[str, bool, float] | None] = {}
        self._fetcher: _EmoteFetcher | None = None
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        mode = db.get_state(MODE_STATE, FULL_MODES[0]) if db is not None else FULL_MODES[0]
        self._full_mode = mode if mode in FULL_MODES else FULL_MODES[0]
        self._over = OVER_DEFAULT
        said = db.get_state(OVER_STATE, "") if db is not None else ""
        try:
            numbers = tuple(float(part) for part in (said or "").split(","))
        except ValueError:
            numbers = ()
        if len(numbers) == 4:
            self._over = self._fitted(*numbers)
        picked = db.get_state(REPLAY_COLUMN_STATE, "chat") if db is not None else "chat"
        self._replay_column = picked if picked in ("queue", "chat") else "chat"

    # ---- what QML reads ---------------------------------------------------

    def _get_model(self) -> QObject:
        return self._model

    model = Property(QObject, _get_model, constant=True)
    available = Property(bool, lambda self: bool(self._kind), notify=changed)
    platform = Property(str, lambda self: self._kind, notify=changed)
    status = Property(str, lambda self: self._status, notify=changed)
    unseen = Property(int, lambda self: self._unseen, notify=changed)
    held = Property(bool, lambda self: self._held, notify=changed)
    column = Property(str, lambda self: self._column if self._kind else "queue", notify=changed)

    @Slot(str)
    def setColumn(self, column: str) -> None:
        if column not in ("queue", "chat") or column == self._column:
            return
        self._column = column
        if self._kind == "replay":
            self._replay_column = column
            if self._db is not None:
                self._db.set_state(REPLAY_COLUMN_STATE, column)
        self.changed.emit()

    # ---- how it shows over a filled screen ----------------------------------

    fullModeChanged = Signal()

    fullMode = Property(str, lambda self: self._full_mode, notify=fullModeChanged)
    overBox = Property("QVariantList", lambda self: list(self._over), notify=fullModeChanged)

    @Slot(str)
    def setFullMode(self, mode: str) -> None:
        if mode not in FULL_MODES or mode == self._full_mode:
            return
        self._full_mode = mode
        if self._db is not None:
            self._db.set_state(MODE_STATE, mode)
        self.fullModeChanged.emit()

    @Slot()
    def cycleFullMode(self) -> None:
        self.setFullMode(FULL_MODES[(FULL_MODES.index(self._full_mode) + 1) % len(FULL_MODES)])

    @staticmethod
    def _fitted(x: float, y: float, width: float, height: float) -> tuple:
        width = max(SMALLEST_OVER[0], min(1.0, width))
        height = max(SMALLEST_OVER[1], min(1.0, height))
        return (max(0.0, min(1.0 - width, x)), max(0.0, min(1.0 - height, y)), width, height)

    @Slot(float, float, float, float)
    def setOverBox(self, x: float, y: float, width: float, height: float) -> None:
        """Where the panel over the picture was put, and its size, in shares
        of the screen, so another screen gets the same place."""
        fitted = self._fitted(x, y, width, height)
        if fitted == self._over:
            return
        self._over = fitted
        if self._db is not None:
            self._db.set_state(OVER_STATE, ",".join(f"{one:.4f}" for one in fitted))
        self.fullModeChanged.emit()

    # ---- following the video ------------------------------------------------

    def follow(self, entry: dict) -> None:
        """The video playing changed. A different chat, or none, starts empty."""
        kind = chat_kind(entry)
        source = (str(entry.get("login") or "") if kind == "twitch"
                  else str(entry.get("key") or "").split(":", 1)[-1] if kind else "")
        if kind == self._kind and source == self._source:
            return
        self._stop_reader()
        self._kind, self._source = kind, source
        self._model.clear()
        self._pending.clear()
        self._inbox.clear()
        self._lags.clear()
        self._extra = {}
        self._room = ""
        self._unseen = 0
        self._held = False
        self._status = ""
        # A broadcast opens on its chat, a past one on whichever was picked
        # last for one.
        self._column = (self._replay_column if kind == "replay"
                        else "chat" if kind else "queue")
        self.changed.emit()
        self._arrange()

    @Slot(float)
    def setPosition(self, seconds: float) -> None:
        """Where the video is. A jump is a seek, which a replay follows."""
        seconds = float(seconds)
        last, self._position = self._position, seconds
        if self._kind != "replay" or self._reader is None:
            return
        if seconds < last - REPLAY_BACK_S or seconds > last + REPLAY_JUMP_S:
            self._replay_from(seconds)

    def _replay_from(self, seconds: float) -> None:
        """Start the replay again a little before this moment of the video."""
        self._round += 1
        self._model.clear()
        self._pending.clear()
        self._fetched_to = max(0.0, seconds - REPLAY_HISTORY_S)
        self._replay_ticket = ""
        self._asking = False
        self._replay_done = False
        self._ask_after = time.monotonic() + REPLAY_SETTLE_S
        self._unseen = 0
        self._held = False
        self.changed.emit()

    def _ask_replay(self) -> None:
        """Ask for more of the replay once the video nears the end of what
        has come."""
        reader = self._reader
        if (not isinstance(reader, _ReplayReader) or self._asking or self._replay_done
                or time.monotonic() < self._ask_after
                or self._fetched_to - self._position > REPLAY_AHEAD_S):
            return
        self._asking = True
        reader.want(self._round, int(self._fetched_to * 1000), self._replay_ticket)

    @Slot(bool)
    def setShown(self, shown: bool) -> None:
        """Whether the chat is on screen, which is when it is read."""
        shown = bool(shown)
        if shown == self._shown:
            return
        self._shown = shown
        self._arrange()

    @Slot(bool)
    def setHeld(self, held: bool) -> None:
        """Somebody scrolled up to read, or came back down to the newest."""
        held = bool(held)
        if held == self._held:
            return
        self._held = held
        if not held:
            self._unseen = 0
            self._model.trim(KEEP)
        self.changed.emit()

    def _arrange(self) -> None:
        wanted = bool(self._kind and self._shown)
        if wanted and self._reader is None:
            self._start_reader()
        elif not wanted and self._reader is not None:
            self._stop_reader()
        if wanted or self._pending:
            self._tick.start()

    def _start_reader(self) -> None:
        self._inbox.clear()
        if self._kind == "twitch":
            reader: Worker = _TwitchReader(self._source, self._inbox, self)
            self._set_status("Joining the chat")
        elif self._kind == "replay":
            reader = _ReplayReader(self._db, self._cfg, self._source, self._inbox, self)
            self._replay_from(self._position)
            self._set_status("Reading the chat replay")
        else:
            reader = _YouTubeReader(self._db, self._cfg, self._source, self._inbox, self)
            self._set_status("Reading the chat")
        reader.finished.connect(self._sweep)
        self._reader = reader
        self._readers.append(reader)
        reader.start()
        trace.mark("chat_reading", kind=self._kind, source=self._source)

    def _stop_reader(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None

    def _sweep(self) -> None:
        self._readers = [one for one in self._readers if one.isRunning()]

    def _set_status(self, words: str) -> None:
        if words != self._status:
            self._status = words
            self.changed.emit()

    # ---- what the readers bring -------------------------------------------

    def _on_tick(self) -> None:
        while self._inbox:
            self._take(self._inbox.popleft())
        if self._kind == "replay":
            self._ask_replay()
            # A replay's lines are due at moments of the video.
            self._release(self._position)
        else:
            self._release()
        if not self._shown and not self._pending:
            self._tick.stop()

    def _take(self, event) -> None:
        if isinstance(event, tuple):
            head = event[0]
            if head == "joined":
                self._set_status("")
            elif head == "youtube":
                self._set_status("")
                self._take_youtube(*event[1:])
            elif head == "replay":
                self._take_replay(*event[1:])
            elif head == "paused":
                self._set_status("Chat paused: YouTube has been asked as much as it "
                                 "should be for now")
            elif head == "trouble":
                self._set_status("YouTube did not answer, trying again")
            elif head == "ended":
                self._set_status("This video's chat replay could not be read"
                                 if self._kind == "replay"
                                 else "The chat has ended" if self._model.count
                                 else "This broadcast has no chat")
            return
        if isinstance(event, twitchchat.Room):
            self._on_room(event.id)
        elif isinstance(event, twitchchat.Line):
            self._hold(self._twitch_row(event), time.monotonic())
        elif isinstance(event, twitchchat.Notice):
            self._hold(self._twitch_notice(event), time.monotonic())
        elif isinstance(event, twitchchat.Cleared):
            if event.user_id:
                self._drop(lambda row, who=event.user_id: row["who"] == who)
            else:
                self._drop(lambda _row: True)
        elif isinstance(event, twitchchat.Deleted):
            self._drop(lambda row, key=event.id: row["key"] == key)

    def _drop(self, test) -> None:
        self._model.remove_where(test)
        self._pending = [one for one in self._pending if not test(one[2])]

    def _take_youtube(self, wall: float, mono: float, events, first: bool) -> None:
        saids = [one for one in events if isinstance(one, youtubechat.Said)]
        if saids and not first:
            # How long the slowest line of this answer took to get here, the
            # longest of the last few of which every line is held behind its
            # posting, so they come out at the pace they were written.
            self._lags.append(max(0.0, *(wall - one.posted_us / 1e6 for one in saids)))
        delay = min(LONGEST_LAG_S, max(self._lags)) if self._lags else 0.0
        for one in events:
            if isinstance(one, youtubechat.Removed):
                if one.id:
                    self._drop(lambda row, key=one.id: row["key"] == key)
                else:
                    self._drop(lambda row, who=one.channel_id: row["who"] == who)
                continue
            due = mono if first else mono + (one.posted_us / 1e6 - wall) + delay
            self._hold(self._youtube_row(one), due)

    def _take_replay(self, round_: int, batch: youtubechat.ReplayBatch) -> None:
        if round_ != self._round or self._kind != "replay":
            return
        self._asking = False
        self._set_status("")
        reached = self._fetched_to
        for at_ms, one in batch.events:
            if isinstance(one, youtubechat.Removed):
                if one.id:
                    self._drop(lambda row, key=one.id: row["key"] == key)
                else:
                    self._drop(lambda row, who=one.channel_id: row["who"] == who)
                continue
            at = at_ms / 1000.0
            reached = max(reached, at)
            self._hold(self._youtube_row(one), at)
        self._fetched_to = reached
        self._replay_ticket = batch.ticket
        self._replay_done = not batch.ticket

    def _on_room(self, room: str) -> None:
        if room == self._room:
            return
        self._room = room
        known = self._sets.get(room)
        if known is not None:
            self._extra = {name: twitchchat.Emote(name, url) for name, url in known.items()}
            return
        if self._db is None:
            return
        reader = _EmoteSets(self._db, self._cfg, room, self)
        reader.found.connect(self._on_sets)
        reader.finished.connect(self._sweep)
        self._readers.append(reader)
        reader.start()

    def _on_sets(self, room: str, found: dict) -> None:
        self._sets[room] = dict(found)
        if room == self._room:
            self._extra = {name: twitchchat.Emote(name, url) for name, url in found.items()}
        trace.mark("emote_sets", room=room, emotes=len(found))

    # ---- lines into rows ---------------------------------------------------

    def _twitch_row(self, line: twitchchat.Line, kind: str = "line") -> dict:
        words = twitchchat.words_with_emotes(line.text, line.emotes, self._extra)
        return {"key": line.id, "who": line.user_id, "author": line.author,
                "colour": line.colour or colour_for(line.author), "roles": list(line.roles),
                "words": [(word, emote.url if emote else "") for word, emote in words],
                "kind": "cheer" if line.bits else kind,
                "amount": f"{line.bits} bits" if line.bits else "", "header": "",
                "sticker": "", "action": line.action}

    def _twitch_notice(self, notice: twitchchat.Notice) -> dict:
        if notice.line is not None:
            row = self._twitch_row(notice.line, "notice")
        else:
            row = {"key": notice.id, "who": "", "author": "", "colour": "", "roles": [],
                   "words": [], "kind": "notice", "amount": "", "sticker": "",
                   "action": False}
        row["kind"] = "notice"
        row["header"] = notice.said
        return row

    def _youtube_row(self, said: youtubechat.Said) -> dict:
        return {"key": said.id, "who": said.channel_id, "author": said.author,
                "colour": colour_for(said.author), "roles": list(said.roles),
                "words": [(word, emoji.url if emoji else "") for word, emoji in said.words],
                "kind": said.kind, "amount": said.amount, "header": said.header,
                "sticker": said.sticker, "action": False}

    def _hold(self, row: dict, due: float) -> None:
        """Keep a line until its moment, asking for its emotes meanwhile."""
        wanted = tuple(dict.fromkeys(url for _word, url in row["words"] if url))
        for url in wanted:
            self._want_emote(url)
        if row.get("sticker"):
            self._want_emote(row["sticker"])
        bisect.insort(self._pending, (due, next(self._order), row, wanted))
        if not self._tick.isActive():
            self._tick.start()

    def _want_emote(self, url: str) -> None:
        if url in self._emotes:
            return
        self._emotes[url] = None
        if self._fetcher is None:
            self._fetcher = _EmoteFetcher(self._cfg, EMOTE_DIR, self)
            self._fetcher.ready.connect(self._on_emote)
            self._fetcher.start()
        self._fetcher.want(url)

    def _on_emote(self, url: str, file_url: str, moves: bool, ratio: float) -> None:
        self._emotes[url] = (file_url, moves, ratio)

    def _release(self, now: float | None = None) -> None:
        """Let out every line whose moment has come: on the clock, or for a
        replay at the moment of the video."""
        if now is None:
            now = time.monotonic()
        out = []
        while self._pending:
            due, _order, row, wanted = self._pending[0]
            if due > now:
                break
            waiting = any(self._emotes.get(url) is None for url in wanted)
            if waiting and now - due < EMOTE_WAIT_S:
                break
            self._pending.pop(0)
            out.append(self._finished(row))
        if not out:
            return
        self._model.append(out)
        if self._held:
            self._unseen += len(out)
            self._model.trim(KEEP_WHILE_HELD)
            self.changed.emit()
        else:
            self._model.trim(KEEP)

    def _finished(self, row: dict) -> dict:
        """The row as QML draws it: every word a piece, and an emote's piece
        its picture, from the disk where it has come."""
        pieces = []
        for word, url in row.pop("words"):
            if not url:
                pieces.append({"text": word})
                continue
            known = self._emotes.get(url)
            if known is None:
                pieces.append({"text": word, "picture": url, "moves": False, "ratio": 1.0})
            else:
                pieces.append({"text": word, "picture": known[0], "moves": known[1],
                               "ratio": known[2]})
        row["pieces"] = pieces
        sticker = row.get("sticker") or ""
        if sticker and self._emotes.get(sticker):
            row["sticker"] = self._emotes[sticker][0]
        return row

    def shutdown(self) -> None:
        self._tick.stop()
        running = [*self._readers]
        if self._fetcher is not None:
            running.append(self._fetcher)
        for one in running:
            one.cancel()
        for one in running:
            if one.isRunning():
                one.wait(5000)
