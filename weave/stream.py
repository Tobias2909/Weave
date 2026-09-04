"""Reading a track the way a browser does, in pieces.

The music used to be played by handing the player one signed address and
letting it hold a single connection open for the whole track. Google's media
servers reset long lived connections as a matter of course, and when that
happened there was nothing underneath to try again, so the track stopped. Every
comparable application avoids this without appearing to: FreeTube plays through
shaka, the web player fetches segments, and all of them ask for small ranges and
simply ask again when one fails.

So this asks for ranges too. The player is handed a device rather than an
address, the device fetches a piece at a time, and a reset costs one retried
request instead of the track. The player is never told, because as far as it is
concerned nothing went wrong.

An address is also only signed for a few hours. When one stops being accepted a
fresh one is fetched and reading carries on at the same byte, which the player
likewise never sees.
"""

from __future__ import annotations

import threading

import requests
from PySide6.QtCore import QIODevice

from .net import USER_AGENT

# Big enough that a fetch is rare, small enough that one costs little. Opus at
# about 130 kbit/s makes a megabyte roughly a minute of music.
CHUNK = 1 << 20
ATTEMPTS = 3
TIMEOUT_S = 20.0


class StreamGone(RuntimeError):
    """The bytes could not be had, even with a fresh address."""


class RangeReader:
    """Bytes from a signed address, by range, with the retrying.

    Deliberately free of Qt so it can be tested without a player, and free of
    threads so the caller decides where the waiting happens.
    """

    def __init__(self, url: str, renew=None, session=None) -> None:
        self._url = url
        self._renew = renew
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._size: int | None = None
        self.renewals = 0

    @property
    def size(self) -> int | None:
        return self._size

    def read(self, offset: int, length: int) -> bytes:
        """One range, however many goes it takes.

        A reset is retried on the same address first, since that is usually all
        it is. Only when the address itself has stopped being accepted is a new
        one fetched, because that costs a subprocess.
        """
        last: Exception | None = None
        for attempt in range(ATTEMPTS):
            try:
                return self._once(offset, length)
            except requests.RequestException as exc:
                last = exc                      # a reset, a timeout, a dead socket
            except _Refused as exc:
                last = exc
                if not self._fresh_address():
                    break
        if self._renew and self._fresh_address():
            try:
                return self._once(offset, length)
            except (requests.RequestException, _Refused) as exc:
                last = exc
        raise StreamGone(str(last) if last else "the stream could not be read")

    def _once(self, offset: int, length: int) -> bytes:
        end = offset + max(1, length) - 1
        response = self._session.get(
            self._url, timeout=TIMEOUT_S, stream=False,
            headers={"Range": f"bytes={offset}-{end}"})
        if response.status_code in (403, 404, 410):
            # The address has expired or been withdrawn. A new one is the only
            # thing that helps, and retrying this one never will.
            raise _Refused(f"the address was refused with {response.status_code}")
        if response.status_code not in (200, 206):
            raise _Refused(f"unexpected status {response.status_code}")
        self._note_size(response)
        return response.content

    def _note_size(self, response) -> None:
        if self._size is not None:
            return
        span = response.headers.get("Content-Range", "")
        if "/" in span:
            total = span.rsplit("/", 1)[-1].strip()
            if total.isdigit():
                self._size = int(total)
                return
        length = response.headers.get("Content-Length")
        if response.status_code == 200 and length and length.isdigit():
            self._size = int(length)

    def _fresh_address(self) -> bool:
        if not self._renew:
            return False
        try:
            address = self._renew()
        except Exception:                                           # noqa: BLE001
            return False
        if not address or address == self._url:
            return False
        self._url = address
        self.renewals += 1
        return True


class _Refused(RuntimeError):
    pass


class Prefetcher:
    """Keeps the piece after the one being read already in hand.

    Without this the player waits for the network every time it crosses a
    boundary, and a wait on the thread that draws sound is heard.
    """

    def __init__(self, reader: RangeReader) -> None:
        self._reader = reader
        self._lock = threading.Lock()
        self._cache: dict[int, bytes] = {}
        self._wanted: set[int] = set()

    def chunk(self, index: int) -> bytes:
        with self._lock:
            found = self._cache.get(index)
        if found is None:
            found = self._reader.read(index * CHUNK, CHUNK)
            with self._lock:
                self._cache[index] = found
                # Two is enough to read forwards through. Anything older is a
                # seek away and cheap enough to fetch again.
                for old in [k for k in self._cache if k < index - 1]:
                    del self._cache[old]
        self._ahead(index + 1)
        return found

    def _ahead(self, index: int) -> None:
        with self._lock:
            if index in self._cache or index in self._wanted:
                return
            self._wanted.add(index)
        threading.Thread(target=self._pull, args=(index,), daemon=True).start()

    def _pull(self, index: int) -> None:
        try:
            data = self._reader.read(index * CHUNK, CHUNK)
        except StreamGone:
            data = None
        with self._lock:
            self._wanted.discard(index)
            if data:
                self._cache[index] = data


class RangedSource(QIODevice):
    """The device the player reads from.

    Random access rather than a stream, because the player seeks, and because
    that is what lets a failed piece be fetched again without the player
    knowing anything happened.
    """

    def __init__(self, url: str, renew=None, parent=None) -> None:
        super().__init__(parent)
        self._reader = RangeReader(url, renew)
        self._pieces = Prefetcher(self._reader)
        self._at = 0
        self._size = 0
        self.broke = False

    def start(self) -> bool:
        """Fetch the first piece, which is also how the length is learned.

        Done before the player is handed the device, so a track that cannot be
        read at all fails here rather than as silence.
        """
        try:
            self._pieces.chunk(0)
        except StreamGone:
            return False
        self._size = self._reader.size or 0
        return self._size > 0 and self.open(QIODevice.OpenModeFlag.ReadOnly)

    # ---- what QIODevice asks of us ---------------------------------------

    def isSequential(self) -> bool:
        return False

    def size(self) -> int:
        return self._size

    def bytesAvailable(self) -> int:
        return max(0, self._size - self._at) + super().bytesAvailable()

    def seek(self, pos: int) -> bool:
        self._at = max(0, min(int(pos), self._size))
        return super().seek(self._at)

    def readData(self, maxlen: int) -> bytes:
        if self._at >= self._size:
            return b""
        want = min(int(maxlen), self._size - self._at)
        out = bytearray()
        while want > 0:
            index, offset = divmod(self._at, CHUNK)
            try:
                piece = self._pieces.chunk(index)
            except StreamGone:
                # Nothing more can be done here. Reporting it as the end of the
                # data lets the player finish rather than sit on a dead device,
                # and the player above notices the track ended early.
                self.broke = True
                break
            if not piece:
                self.broke = True
                break
            take = min(want, len(piece) - offset)
            if take <= 0:
                break
            out += piece[offset:offset + take]
            self._at += take
            want -= take
        return bytes(out)

    def writeData(self, _data) -> int:
        return -1
