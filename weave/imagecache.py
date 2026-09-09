"""On disk caching for thumbnails, avatars and banners.

Without this every picture is downloaded again on every launch and on every
trip back to a view, because Qt's own image cache is memory only and does not
survive the process.

Two things were measured on the way to this design and are worth not repeating.

A QML Image does not use the engine's network manager. Setting a disk cache on
that manager looks right, changes nothing, and fails silently. The picture
loads, the manager sees no request at all, and the cache directory stays empty.
Images are fetched by a manager the engine builds from its network manager
factory, and subclassing that factory from Python crashes inside
QQmlTypeLoader::createNetworkAccessManager. So neither route is usable here.

What works is an image provider, which is also the only one of the three that
puts the retention rule in our hands rather than the server's. A thumbnail
arrives with a cache lifetime of a few minutes, so an HTTP cache would go back
to the network on nearly every visit even though the picture never changes.

Measured sizes on a real subscription list. A thumbnail averages 17.5 KB, so
every visible video would come to about 81 MB, and 456 channel avatars come to
about 5 MB. The default ceiling leaves room for that plus banners.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from pathlib import Path

import requests
from PySide6.QtCore import (QBuffer, QIODevice, QObject, QRunnable, Qt, QThreadPool,
                            Signal)
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQuick import QQuickAsyncImageProvider, QQuickImageResponse, QQuickTextureFactory

from .net import USER_AGENT

PROVIDER_ID = "cached"
SECONDS_PER_DAY = 86400

# Pictures come from an image CDN rather than an endpoint that rate limits, so
# they do not go through the request throttle. This cap is about not opening
# fifty sockets at once while scrolling.
MAX_PARALLEL = 6
REQUEST_TIMEOUT_S = 20.0

# A picture that will not load is a picture that does not appear, which the eye
# already reports. Saying so once per picture as well turns a bad minute on the
# network into hundreds of console lines saying the same thing, so failures are
# counted and written down instead, and read back with the cache subcommand.
FAILURE_LOG = "failures.log"
MAX_LOGGED = 200
RETRY_AFTER_S = 1.5

# A picture that is gone stays gone, and nothing here ever learns otherwise on
# its own, so asking again on every visit to a view is pure waste. One dead
# thumbnail was fetched fifty times in three days that way. A failure leaves a
# marker beside where the picture would have been cached, and the marker is
# read before anything is asked for. It lives in the cache directory, so the
# pruning and the ceiling already sweep it up, and clearing the cache or
# forgetting the failures gives a picture another chance ahead of time.
FAIL_SUFFIX = ".fail"

# How long a marker is believed, by what went wrong. A picture that is really
# gone is trusted for a week; anything else may well be a bad minute, this
# machine's or the CDN's, and is retried soon.
MISSING_AGAIN_S = 7 * SECONDS_PER_DAY
FAILED_AGAIN_S = 600

# How many 404s in a row before a thumbnail counts as gone. ONE IS NOT ENOUGH,
# measured: a thumbnail of a video that is public and playable answered 404
# once and 200 a minute later. Believing that one answer would have blanked a
# live picture for a week and, worse, marked a video nobody can get back as
# gone. So a 404 is retried at the same distance as any other failure, and only
# the second one in a row is an answer. The channel feeds count strikes for
# exactly this reason, and for the same endpoint behaviour.
MISSING_STRIKES = 2

# YouTube's stand in for a playlist entry that is private or deleted. It is a
# 404 itself, measured, so there is nothing to fetch and nothing to draw.
NO_THUMBNAIL = "https://i.ytimg.com/img/no_thumbnail.jpg"

# A listing, a search and the history hand over the thumbnail with a signature
# on the address, and that signature EXPIRES: the same picture 404s some days
# later while the bare address beside it still answers. Often it is a crop as
# well, which is the smaller picture, measured at 336x188 against 480x360; and
# every card is drawn with PreserveAspectCrop, which takes off exactly the
# letterbox the full frame carries. So the bare address is the better picture
# as well as the durable one, and nothing signed is ever kept.
#
# The size in the name is left as it was found. Checked against 131 of the
# signed addresses in a real database, covering every shape in it: all of them
# answer 200 with the signature and the crop taken off, hq720 included.
_SIGNED_CROP = re.compile(
    r"(/vi/[A-Za-z0-9_-]{11}/(?:hq720|(?:hq|mq|sd|maxres|oar)?default))"
    r"(?:_custom_\d+)?\.jpg\?\S*$")

# The video behind a thumbnail address. The picture host is spelled i.ytimg.com
# and i1 through i4 alike, all of them the same pictures.
_VIDEO_ID = re.compile(r"^https://i\d?\.ytimg\.com/vi/([A-Za-z0-9_-]{11})/")

# Qt refuses outright to decode a picture whose pixels would need more than its
# 256 MB allocation limit, and says so on the console once per attempt. Nothing
# here is meant to be that big, but a channel avatar asked for at its original
# size can be: one measured 8334 square, which is 265 MB of pixels for
# something drawn 44 across, so it was rejected, never cached, and downloaded
# again on every single visit to the view. Reading the header first and asking
# for a smaller decode fixes it for good, whatever the source. The jpeg and
# webp readers scale while they decode and never allocate the full frame.
# 2048 is above the widest thing Weave draws, which is a channel banner.
MAX_EDGE = 2048

# What the settings page offers as a ceiling, in megabytes. The default is in
# the config, since it is a number a person may want to read there; these are
# the sizes it can be moved to from the window. The low end is about what a
# full subscription list needs, and the high end is for a machine with room to
# spare that would rather never fetch a picture twice.
CEILING_STEPS_MB: tuple[int, ...] = (200, 300, 500, 1024, 2048, 5120, 10240)


def ceiling_label(megabytes: int) -> str:
    """A size as it is offered and reported. Whole thousands of megabytes read
    as gigabytes, because 10240 MB is not how anybody says ten gigabytes."""
    if megabytes >= 1024 and megabytes % 1024 == 0:
        return f"{megabytes // 1024} GB"
    return f"{megabytes} MB"


def _read(reader: QImageReader) -> QImage:
    """Decode, shrinking anything bigger than Weave has any use for."""
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > MAX_EDGE:
        reader.setScaledSize(size.scaled(MAX_EDGE, MAX_EDGE,
                                         Qt.AspectRatioMode.KeepAspectRatio))
    return reader.read()


def _record(directory: Path, url: str, reason: str) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / FAILURE_LOG
        lines = path.read_text().splitlines() if path.exists() else []
        lines.append(f"{int(time.time())}\t{reason}\t{url}")
        path.write_text("\n".join(lines[-MAX_LOGGED:]) + "\n")
    except OSError:
        pass


def failures(directory: Path) -> list[tuple[int, str, str]]:
    path = directory / FAILURE_LOG
    try:
        rows = []
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].isdigit():
                rows.append((int(parts[0]), parts[1], parts[2]))
        return rows
    except OSError:
        return []


def normalise(url: str | None) -> str:
    """The address a picture is worth keeping under.

    Two rewrites, both of them about a picture that would otherwise be asked
    for and refused. The sentinel for a private or deleted entry becomes no
    picture at all, and a signed address loses its signature and its crop while
    keeping the size it named. Done here rather than at every source, so one
    place knows the rules and the addresses already in the database are fixed
    on the way out without a migration.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if url.split("?")[0] == NO_THUMBNAIL:
        return ""
    return _SIGNED_CROP.sub(r"\1.jpg", url)


def video_id(url: str | None) -> str:
    """The video a thumbnail belongs to, or an empty string when the picture is
    not a thumbnail at all. An avatar and a banner have no video behind them."""
    match = _VIDEO_ID.match((url or "").strip())
    return match.group(1) if match else ""


def qml_source(url: str | None) -> str:
    """Wrap a picture URL so QML fetches it through the cache.

    Built here rather than in QML so there is one place that knows about the
    provider, and so a missing picture stays an empty string.
    """
    url = normalise(url)
    if not url.startswith("http"):
        return ""
    return f"image://{PROVIDER_ID}/{url}"


def plain_source(value: str | None) -> str:
    """The picture address without the wrapper, whether it had one or not.

    Anything read back out of the window has already been wrapped for the
    cache, and wrapping it a second time throws it away, since a wrapped
    address does not begin with http. So whatever is stored is stored plain.
    """
    value = (value or "").strip()
    prefix = f"image://{PROVIDER_ID}/"
    return value[len(prefix):] if value.startswith(prefix) else value


def path_for(directory: Path, url: str) -> Path:
    """Where a picture is kept. Hashed, because a URL is not a filename, and
    spread over a first byte of the digest so no directory holds thousands of
    entries."""
    digest = hashlib.sha1(url.encode()).hexdigest()
    return directory / digest[:2] / digest


class Reporter(QObject):
    """Carries word of a thumbnail that is gone for good out of the pool
    threads the pictures are fetched on.

    A 404 on a thumbnail means the video itself is gone, measured: the one dead
    video in a real database answered 404 on every picture host while yt dlp
    said Video unavailable, and five members only videos, the one thing that
    could be mistaken for it, all answered 200. So this is a free reading of
    something no other part of the app looks for, and it is worth passing on.

    A plain signal rather than a database write, because this runs on a pool
    thread and the window is what owns the writing.
    """

    missing = Signal(str)


class _Response(QQuickImageResponse, QRunnable):
    """Serves one picture, from disk when it is there and from the network
    otherwise."""

    def __init__(self, url: str, directory: Path, ttl_seconds: int,
                 reporter: Reporter | None = None) -> None:
        QQuickImageResponse.__init__(self)
        QRunnable.__init__(self)
        self._url = url
        self._directory = directory
        self._path = path_for(directory, url)
        self._fail_path = self._path.with_suffix(FAIL_SUFFIX)
        self._reporter = reporter
        self._ttl = ttl_seconds
        self._image = QImage()
        self._error = ""
        # The engine owns the response and deletes it once it has finished, so
        # the thread pool must not delete it as well.
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            if not self._load_from_disk() and not self._gave_up_recently():
                self._download()
        except Exception as exc:
            self._remember(type(exc).__name__)
        # No error string on purpose. Qt logs one line per failed picture, and
        # a view full of them during a bad minute buries everything else.
        self.finished.emit()

    def _fresh(self) -> bool:
        try:
            return time.time() - self._path.stat().st_mtime < self._ttl
        except OSError:
            return False

    def _marked(self) -> tuple[str, int]:
        """What was written down last time this picture was asked for, as the
        reason and how many times in a row it has now given that answer."""
        try:
            held = self._fail_path.read_text().strip().split("\t")
        except OSError:
            return "", 0
        strikes = int(held[1]) if len(held) > 1 and held[1].isdigit() else 1
        return held[0], strikes

    def _gave_up_recently(self) -> bool:
        """Whether this picture was already asked for and refused lately.

        A 404 that has struck often enough to be believed is left alone for a
        week. Everything else, a first 404 included, is tried again soon.
        """
        try:
            age = time.time() - self._fail_path.stat().st_mtime
        except OSError:
            return False
        reason, strikes = self._marked()
        settled = reason == "HTTP 404" and strikes >= MISSING_STRIKES
        return age < (MISSING_AGAIN_S if settled else FAILED_AGAIN_S)

    def _remember(self, reason: str) -> None:
        """Write the failure down twice over: once in the log a person reads,
        and once as the marker that stops it being asked for again.

        A run of the same answer is counted, since one 404 is not an answer.
        Any other answer starts the count over, because the two failures have
        nothing to say about each other.
        """
        _record(self._directory, self._url, reason)
        was, strikes = self._marked()
        strikes = strikes + 1 if was == reason else 1
        try:
            self._fail_path.parent.mkdir(parents=True, exist_ok=True)
            self._fail_path.write_text(f"{reason}\t{strikes}\n")
        except OSError:
            pass
        if reason == "HTTP 404" and strikes >= MISSING_STRIKES and self._reporter is not None:
            gone = video_id(self._url)
            if gone:
                self._reporter.missing.emit(gone)

    def _load_from_disk(self) -> bool:
        if not self._fresh():
            return False
        image = _read(QImageReader(str(self._path)))
        if image.isNull():
            return False
        self._image = image
        return True

    def _download(self) -> bool:
        """One retry, because a picture that failed on a bad connection will
        usually load a moment later, and giving up leaves a hole until the view
        is visited again."""
        reason = ""
        for attempt in (0, 1):
            if attempt:
                time.sleep(RETRY_AFTER_S)
            try:
                response = requests.get(self._url, timeout=REQUEST_TIMEOUT_S,
                                        headers={"User-Agent": USER_AGENT})
            except requests.RequestException as exc:
                reason = type(exc).__name__
                continue
            if response.status_code != 200:
                reason = f"HTTP {response.status_code}"
                # Only a server that is struggling is worth asking twice.
                if response.status_code not in (429, 500, 502, 503, 504):
                    break
                continue
            payload = response.content
            # Read through a buffer rather than with loadFromData, so an
            # oversized picture is decoded smaller instead of refused.
            buffer = QBuffer()
            # setData rather than the constructor: a QByteArray handed to
            # QBuffer is not owned by it, so a temporary one is freed while the
            # reader still points at it, and the process dies in bad_alloc on
            # a length read out of freed memory. setData copies.
            buffer.setData(payload)
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            image = _read(QImageReader(buffer))
            if image.isNull():
                reason = "unreadable"
                break
            self._image = image
            # The original bytes are what is kept, so the cache stays a copy
            # of what the server sent and the shrinking happens on the way out.
            self._store(payload)
            return True

        self._remember(reason or "failed")
        return False

    def _store(self, payload: bytes) -> None:
        """Write through a temporary file in the same directory, so a picture
        interrupted halfway never becomes a corrupt cache entry."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fail_path.unlink(missing_ok=True)
            handle, temporary = tempfile.mkstemp(dir=self._path.parent)
            with os.fdopen(handle, "wb") as sink:
                sink.write(payload)
            os.replace(temporary, self._path)
        except OSError:
            # A cache that cannot be written is not a reason to fail the
            # picture, it just means it is fetched again next time.
            pass

    def textureFactory(self) -> QQuickTextureFactory:
        return QQuickTextureFactory.textureFactoryForImage(self._image)

    def errorString(self) -> str:
        return self._error


class CachedImageProvider(QQuickAsyncImageProvider):
    def __init__(self, directory: Path, ttl_seconds: int) -> None:
        super().__init__()
        self._directory = directory
        self._ttl = ttl_seconds
        # An image provider is not itself a QObject, so what the window
        # connects to is this rather than the provider.
        self.reporter = Reporter()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(MAX_PARALLEL)

    def requestImageResponse(self, image_id: str, requested_size):
        response = _Response(image_id, self._directory, self._ttl, self.reporter)
        self._pool.start(response)
        return response


def grouped(rows: list[tuple[int, str, str]]) -> list[tuple[int, str, str, int]]:
    """The failures as one line per picture, newest last.

    A picture that will not load is asked for again on every visit to the view
    it is on, so a handful of dead addresses reads as a hundred failures. The
    count is the thing worth seeing, not the repetition.
    """
    seen: dict[tuple[str, str], list[int]] = {}
    for when, reason, url in rows:
        seen.setdefault((reason, url), [0, when])[0] += 1
        seen[(reason, url)][1] = when
    out = [(when, reason, url, count)
           for (reason, url), (count, when) in seen.items()]
    out.sort(key=lambda row: row[0])
    return out


def forget(directory: Path) -> tuple[int, int]:
    """Empty the failure log and drop every marker, returning how many of each
    there were. What gives a picture another try before its window is up."""
    log = directory / FAILURE_LOG
    counted = len(failures(directory))
    try:
        log.unlink(missing_ok=True)
    except OSError:
        counted = 0
    dropped = 0
    if directory.exists():
        for path in directory.rglob(f"*{FAIL_SUFFIX}"):
            try:
                path.unlink()
                dropped += 1
            except OSError:
                continue
    return counted, dropped


def _sweepable(path: Path, directory: Path) -> bool:
    """The log is kept in the cache directory and is not a picture, so neither
    the pruning nor the ceiling is allowed to take it."""
    return path.is_file() and path != directory / FAILURE_LOG


def size_bytes(directory: Path) -> int:
    if not directory.exists():
        return 0
    total = 0
    for path in directory.rglob("*"):
        try:
            if _sweepable(path, directory):
                total += path.stat().st_size
        except OSError:
            continue
    return total


def prune(directory: Path, ttl_seconds: int) -> tuple[int, int]:
    """Delete pictures past the retention window. Returns the file count and
    the bytes freed."""
    if not directory.exists():
        return 0, 0
    cutoff = time.time() - max(0, ttl_seconds)
    removed = freed = 0
    for path in directory.rglob("*"):
        if not _sweepable(path, directory):
            continue
        try:
            stat = path.stat()
            if stat.st_mtime < cutoff:
                size = stat.st_size
                path.unlink()
                removed += 1
                freed += size
        except OSError:
            continue
    return removed, freed


def enforce_ceiling(directory: Path, max_bytes: int) -> tuple[int, int]:
    """Drop the oldest pictures until the cache fits. Age alone cannot bound
    the size, since a week of heavy use could exceed any ceiling."""
    if not directory.exists():
        return 0, 0
    files = []
    total = 0
    for path in directory.rglob("*"):
        try:
            if _sweepable(path, directory):
                stat = path.stat()
                files.append((stat.st_mtime, stat.st_size, path))
                total += stat.st_size
        except OSError:
            continue
    if total <= max_bytes:
        return 0, 0

    removed = freed = 0
    for _mtime, size, path in sorted(files):
        if total - freed <= max_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
        freed += size
    return removed, freed


def install(engine, directory: Path, max_mb: int, ttl_days: int) -> CachedImageProvider:
    """Register the provider, after clearing out what has aged out or spilled
    over since the last run."""
    ttl_seconds = max(1, ttl_days) * SECONDS_PER_DAY
    directory.mkdir(parents=True, exist_ok=True)
    prune(directory, ttl_seconds)
    enforce_ceiling(directory, max(16, max_mb) * 1024 * 1024)
    provider = CachedImageProvider(directory, ttl_seconds)
    engine.addImageProvider(PROVIDER_ID, provider)
    return provider
