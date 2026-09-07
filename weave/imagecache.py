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
import tempfile
import time
from pathlib import Path

import requests
from PySide6.QtCore import QBuffer, QIODevice, QRunnable, Qt, QThreadPool
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQuick import QQuickAsyncImageProvider, QQuickImageResponse, QQuickTextureFactory

from . import __version__

PROVIDER_ID = "cached"
SECONDS_PER_DAY = 86400
USER_AGENT = f"Weave/{__version__} (+https://github.com/Tobias2909/Weave)"

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


def qml_source(url: str | None) -> str:
    """Wrap a picture URL so QML fetches it through the cache.

    Built here rather than in QML so there is one place that knows about the
    provider, and so a missing picture stays an empty string.
    """
    url = (url or "").strip()
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


class _Response(QQuickImageResponse, QRunnable):
    """Serves one picture, from disk when it is there and from the network
    otherwise."""

    def __init__(self, url: str, directory: Path, ttl_seconds: int) -> None:
        QQuickImageResponse.__init__(self)
        QRunnable.__init__(self)
        self._url = url
        self._path = path_for(directory, url)
        self._ttl = ttl_seconds
        self._image = QImage()
        self._error = ""
        # The engine owns the response and deletes it once it has finished, so
        # the thread pool must not delete it as well.
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            self._load_from_disk() or self._download()
        except Exception as exc:
            _record(self._path.parent.parent, self._url, type(exc).__name__)
        # No error string on purpose. Qt logs one line per failed picture, and
        # a view full of them during a bad minute buries everything else.
        self.finished.emit()

    def _fresh(self) -> bool:
        try:
            return time.time() - self._path.stat().st_mtime < self._ttl
        except OSError:
            return False

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

        _record(self._path.parent.parent, self._url, reason or "failed")
        return False

    def _store(self, payload: bytes) -> None:
        """Write through a temporary file in the same directory, so a picture
        interrupted halfway never becomes a corrupt cache entry."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
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
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(MAX_PARALLEL)

    def requestImageResponse(self, image_id: str, requested_size):
        response = _Response(image_id, self._directory, self._ttl)
        self._pool.start(response)
        return response


def size_bytes(directory: Path) -> int:
    if not directory.exists():
        return 0
    total = 0
    for path in directory.rglob("*"):
        try:
            if path.is_file():
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
        if not path.is_file():
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
            if path.is_file():
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
