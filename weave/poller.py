"""Background work.

A refresh runs in three phases, and each one is allowed to fail on its own.
RSS is the only phase the feed truly needs, so a broken login or a missing
yt-dlp costs the duration badges and the Shorts filter while the feed itself
keeps working.

  1  channel RSS, which brings new videos with their publish times
  2  the subscriptions sweep, which joins in durations and live flags
  3  the Shorts redirect test on whatever is still undecided

Concurrency is bounded twice over, by the executor and by the global throttle,
so a few hundred channels cannot become a few hundred simultaneous requests.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, QThread, Signal

from .classify import classify_channel
from .imagecache import qml_source
from .config import Config
from .db import Database
from .net import Cancelled as FetchCancelled
from .net import Fetcher, Throttle
from .process import Cancelled as ProcessCancelled
from .process import run as run_process
from .sources import channel as channel_source
from . import tokens
from .sources import comments as comment_source
from .sources import livecheck
from .sources import dislikes as dislike_source
from .sources import rss, shorts, subs, sweep, tabs, twitch


class FeedPoller(QThread):
    finished_poll = Signal(int, int, int)   # channels polled, rows touched, failures
    progress = Signal(str, int, int)        # phase, done, total
    failure = Signal(str, str)              # source label, error text

    def __init__(self, db: Database, cfg: Config, force_all: bool = False,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._force_all = force_all
        self._throttle = Throttle(cfg.max_concurrency, cfg.min_request_interval_s)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Ask the poll to stop. Qt aborts the whole process if a running
        QThread is destroyed, so every thread needs this."""
        self._cancel.set()

    def run(self) -> None:
        fetcher = Fetcher(self._throttle, cancel=self._cancel)
        polled = touched = failures = 0
        try:
            polled, touched, failures = self._phase_rss(fetcher)
            if not self._cancel.is_set():
                touched += self._phase_sweep()
            if not self._cancel.is_set():
                self._phase_classify()
            if not self._cancel.is_set():
                self._phase_shorts(fetcher)
        except (FetchCancelled, ProcessCancelled):
            pass
        finally:
            fetcher.close()
            self._db.close()
        self.finished_poll.emit(polled, touched, failures)

    # ---- phase 1 ---------------------------------------------------------

    def _phase_rss(self, fetcher: Fetcher) -> tuple[int, int, int]:
        channels = (self._db.channels(platform="youtube") if self._force_all
                    else self._db.channels_due(self._cfg.feed_interval_s))
        total = len(channels)
        if not total:
            return 0, 0, 0

        touched = failures = done = 0
        with ThreadPoolExecutor(max_workers=self._cfg.max_concurrency) as pool:
            futures = {pool.submit(rss.fetch, fetcher, row["ext_id"]): row["key"]
                       for row in channels}
            for future in as_completed(futures):
                if self._cancel.is_set():
                    # Drops what has not started. Anything already in flight
                    # finishes on its own timeout, which is why the request
                    # timeout is kept short.
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                key = futures[future]
                try:
                    result = future.result()
                except (FetchCancelled, ProcessCancelled):
                    break
                except Exception as exc:                            # noqa: BLE001
                    failures += 1
                    message = f"{type(exc).__name__}: {exc}"
                    self._db.mark_polled(key, message)
                    self.failure.emit(key, message)
                else:
                    touched += self._db.upsert_videos(result.videos)
                    if result.channel_title:
                        self._db.add_channel(key, "youtube", key.split(":", 1)[1],
                                             result.channel_title)
                    self._db.mark_polled(key, None)
                    if not result.videos and self._db.channel_has_videos(key):
                        # Zero entries with no error is what a broken source
                        # looks like. But a channel that has never produced a
                        # video is simply empty, and there are plenty of those
                        # in a large subscription list, so only a channel that
                        # used to have videos and now has none is reported.
                        self.failure.emit(key, "returned no entries")
                done += 1
                self.progress.emit("feeds", done, total)
        return total, touched, failures

    # ---- phase 2 ---------------------------------------------------------

    def _phase_sweep(self) -> int:
        if not self._cfg.sweep_limit:
            return 0
        self.progress.emit("durations", 0, 1)
        try:
            videos = sweep.fetch(self._cfg, self._cfg.sweep_limit, self._throttle,
                                 cancel=self._cancel)
        except ProcessCancelled:
            return 0
        except sweep.SweepError as exc:
            self.failure.emit("durations", str(exc))
            return 0
        filled = self._db.fill_details([(v.key, v.duration_s, v.live_status) for v in videos])
        self.progress.emit("durations", 1, 1)
        return filled

    # ---- phase 3 ---------------------------------------------------------

    def _phase_classify(self) -> None:
        limit = self._cfg.classify_per_cycle
        if not limit:
            return
        channels = self._db.channels_needing_classification(
            self._cfg.classify_interval_s, limit)
        total = len(channels)
        if not total:
            return

        done = 0
        with ThreadPoolExecutor(max_workers=self._cfg.max_concurrency) as pool:
            futures = {
                pool.submit(classify_channel, self._db, row["key"], row["ext_id"],
                            self._throttle, self._cancel): row["key"]
                for row in channels
            }
            for future in as_completed(futures):
                if self._cancel.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return
                try:
                    future.result()
                except ProcessCancelled:
                    return
                except tabs.TabError as exc:
                    self.failure.emit(futures[future], f"listing, {exc}")
                except Exception as exc:                            # noqa: BLE001
                    self.failure.emit(futures[future], f"{type(exc).__name__}: {exc}")
                done += 1
                self.progress.emit("kinds", done, total)

    # ---- phase 4 ---------------------------------------------------------

    def _phase_shorts(self, fetcher: Fetcher) -> None:
        limit = self._cfg.shorts_per_cycle
        if not limit:
            return
        candidates = self._db.videos_needing_short_check(limit)
        total = len(candidates)
        for index, row in enumerate(candidates, start=1):
            if self._cancel.is_set():
                return
            try:
                self._db.set_short(row["key"], shorts.classify(fetcher, row["ext_id"]))
            except FetchCancelled:
                return
            except shorts.UndecidedError:
                # Left unclassified on purpose, so it is retried later rather
                # than filed wrongly.
                pass
            except Exception as exc:                                # noqa: BLE001
                self.failure.emit("shorts", f"{type(exc).__name__}: {exc}")
                return
            self.progress.emit("shorts", index, total)


class ChannelAdder(QThread):
    """Resolves a channel reference off the interface thread.

    Resolving costs about half a second, short enough not to need a progress
    bar and long enough to be felt as a freeze on the interface thread.
    """

    added = Signal(str, str, str, str)   # key, platform, ext_id, title
    failed = Signal(str)

    def __init__(self, ref, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ref = ref
        self._throttle = Throttle(1, cfg.min_request_interval_s)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        from .sources.resolve import ResolveError, resolve

        try:
            result = resolve(self._ref, throttle=self._throttle, cancel=self._cancel)
        except ProcessCancelled:
            return
        except ResolveError as exc:
            self.failed.emit(str(exc))
            return
        self.added.emit(result.key, result.platform, result.ext_id, result.title or "")


class SubsImporter(QThread):
    """Imports the subscription list, names and avatars included."""

    imported = Signal(int, int)          # total found, newly added
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._throttle = Throttle(1, cfg.min_request_interval_s)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            channels = subs.fetch(self._cfg, self._throttle, cancel=self._cancel)
        except ProcessCancelled:
            return
        except subs.ImportError_ as exc:
            self.failed.emit(str(exc))
            return
        added = 0
        for channel in channels:
            if self._db.add_channel(channel.key, "youtube", channel.ext_id,
                                    channel.title, channel.avatar_url):
                added += 1
        self._db.close()
        self.imported.emit(len(channels), added)


class ChannelDetailsFetcher(QThread):
    """Fills in a channel's banner and subscriber count the first time its page
    is opened."""

    fetched = Signal(str)
    failed = Signal(str, str)

    def __init__(self, db: Database, cfg: Config, channel_key: str, ext_id: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._key = channel_key
        self._ext_id = ext_id
        self._throttle = Throttle(1, cfg.min_request_interval_s)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            details = channel_source.fetch(self._ext_id, self._throttle, self._cancel)
        except ProcessCancelled:
            return
        except channel_source.DetailsError as exc:
            self.failed.emit(self._key, str(exc))
            return
        self._db.set_channel_details(self._key, details.title, details.avatar_url,
                                     details.banner_url, details.follower_count)
        self._db.close()
        self.fetched.emit(self._key)


class TwitchLogin(QThread):
    """The device code login, and the follow list that comes with it.

    Twitch hands back an address that already contains the code, so the browser
    can be opened straight at a page with nothing to type.
    """

    codeReady = Signal(str, str)          # user code, address to open
    finished_login = Signal(int)          # channels imported
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        client_id = self._cfg.twitch_client_id
        if not client_id:
            self.failed.emit("no Twitch client id is configured")
            return
        try:
            login = twitch.start_login(client_id)
        except twitch.TwitchError as exc:
            self.failed.emit(str(exc))
            return

        self.codeReady.emit(login.user_code, login.verification_uri)
        deadline = time.monotonic() + login.expires_in
        while not self._cancel.is_set() and time.monotonic() < deadline:
            if self._cancel.wait(login.interval):
                return
            try:
                got = twitch.poll_login(client_id, login.device_code)
            except twitch.AuthPending:
                continue
            except twitch.TwitchError as exc:
                self.failed.emit(str(exc))
                return
            tokens.save(got)
            self.finished_login.emit(self._import_follows(client_id, got))
            return
        if not self._cancel.is_set():
            self.failed.emit("the login was not approved in time")

    def _import_follows(self, client_id: str, got: twitch.Tokens) -> int:
        """Track every followed channel, so they appear in the feed and can go
        into groups like any other."""
        try:
            client = twitch.Client(client_id, got, on_tokens=tokens.save)
            follows = client.follows(client.account_id())
        except twitch.TwitchError:
            return 0
        added = 0
        for login, display in follows:
            if self._db.add_channel(f"twitch:{login}", "twitch", login, display):
                added += 1
        self._db.close()
        return added


class LiveWatcher(QThread):
    """Who is live right now. Runs on its own timer, far more often than the
    feed, because a live bar that is fifteen minutes stale is wrong."""

    updated = Signal(int)
    needsLogin = Signal()
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._cancel = threading.Event()
        self._throttle = Throttle(2, cfg.min_request_interval_s)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        client_id = self._cfg.twitch_client_id
        stored = tokens.load()
        if not client_id or stored is None:
            self.needsLogin.emit()
            return
        try:
            client = twitch.Client(client_id, stored, on_tokens=tokens.save)
            streams = client.followed_streams(client.account_id())

            # Channels added by hand are not necessarily followed, so they are
            # asked about separately and merged.
            tracked = {row["ext_id"].lower()
                       for row in self._db.channels(platform="twitch")}
            missing = sorted(tracked - {stream.login for stream in streams})
            if missing and not self._cancel.is_set():
                streams.extend(client.streams_for(missing))
        except twitch.NeedsLogin:
            self.needsLogin.emit()
            return
        except twitch.TwitchError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:                                    # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return

        # A stream says nothing about what its broadcaster looks like, so the
        # icons are fetched once per channel and stored alongside it.
        try:
            self._fetch_missing_avatars(client)
        except twitch.TwitchError:
            pass

        known = {row["key"] for row in self._db.channels(platform="twitch")}
        rows = [{
            "channel_key": stream.key, "login": stream.login,
            "display_name": stream.display_name, "title": stream.title,
            "game": stream.game, "viewers": stream.viewers,
            "started_at": stream.started_at, "thumbnail_url": stream.thumbnail_url,
        } for stream in streams if stream.key in known]
        self._db.replace_live("twitch", rows)
        try:
            youtube = self._check_youtube()
        except Exception as exc:                                    # noqa: BLE001
            # One half failing must not cost the other. Before this, a mistake
            # in here stopped the whole check and the update was never
            # reported, so the Twitch results never reached the bar either.
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            youtube = 0
        self._db.close()
        self.updated.emit(len(rows) + youtube)

    def _check_youtube(self) -> int:
        """Give the YouTube streams a viewer count so they order against the
        Twitch ones, and drop the ones that have finished."""
        found = 0
        for row in self._db.live_youtube():
            if self._cancel.is_set():
                break
            try:
                state = livecheck.check(self._cfg, row["ext_id"], self._throttle, self._cancel)
            except ProcessCancelled:
                break
            except livecheck.LiveCheckError:
                continue
            self._db.set_live_state(row["key"], state.viewers, state.still_live)
            found += 1 if state.still_live else 0
        return found

    def _fetch_missing_avatars(self, client: "twitch.Client") -> None:
        missing = self._db.channels_missing_avatar("twitch")
        if not missing or self._cancel.is_set():
            return
        for login, display, picture in client.users(missing):
            self._db.add_channel(f"twitch:{login}", "twitch", login, display, picture or None)


class DetailFetcher(QThread):
    """Everything the detail panel needs that is not already stored.

    The dislike count and the comments come from different places and take very
    different amounts of time, so each is reported as it lands rather than the
    panel waiting for both.
    """

    votes = Signal(str, int)              # video key, dislikes
    comments = Signal(str, "QVariantList")
    failed = Signal(str, str)

    def __init__(self, db: Database, cfg: Config, video_key: str, ext_id: str,
                 url: str, threads: int = 5, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._key = video_key
        self._ext_id = ext_id
        self._url = url
        self._threads = threads
        self._cancel = threading.Event()
        self._throttle = Throttle(2, cfg.min_request_interval_s)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        fetcher = Fetcher(self._throttle, cancel=self._cancel)
        try:
            if not self._cancel.is_set():
                self._fetch_votes(fetcher)
            if not self._cancel.is_set():
                self._fetch_comments()
        finally:
            fetcher.close()
            self._db.close()

    def _fetch_votes(self, fetcher: Fetcher) -> None:
        try:
            found = dislike_source.fetch(fetcher, self._ext_id)
        except Exception as exc:                                    # noqa: BLE001
            self.failed.emit("dislikes", f"{type(exc).__name__}: {exc}")
            return
        if found.dislikes is not None:
            self._db.set_dislikes(self._key, found.dislikes)
            self.votes.emit(self._key, found.dislikes)

    def _fetch_comments(self) -> None:
        try:
            threads = comment_source.fetch(self._cfg, self._url, self._threads,
                                           self._throttle, self._cancel)
        except ProcessCancelled:
            return
        except comment_source.CommentsError as exc:
            self.failed.emit("comments", str(exc))
            return
        self.comments.emit(self._key, [self._as_map(thread) for thread in threads])

    @staticmethod
    def _as_map(comment) -> dict:
        return {
            "author": comment.author,
            # Through the cache like every other picture.
            "avatar": qml_source(comment.avatar_url),
            "text": comment.text,
            "likes": comment.likes,
            "when": comment.when,
            "pinned": comment.pinned,
            "byUploader": comment.by_uploader,
            "verified": comment.verified,
            "replies": [DetailFetcher._as_map(reply) for reply in comment.replies],
        }


class MusicSearch(QThread):
    """Searching YouTube Music, off the interface thread."""

    results = Signal("QVariantList")
    failed = Signal(str)

    def __init__(self, cfg: Config, query: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._query = query

    def cancel(self) -> None:
        pass                                    # one short call, nothing to stop

    def run(self) -> None:
        from .sources import ytmusic

        try:
            tracks = ytmusic.search(self._cfg.browser_profile_path, self._query)
        except ytmusic.MusicError as exc:
            self.failed.emit(str(exc))
            return
        self.results.emit([{
            "key": track.key, "videoId": track.video_id, "title": track.title,
            "artist": track.artist, "album": track.album, "duration": track.duration,
            "thumbnail": qml_source(track.thumbnail_url),
        } for track in tracks])


class MusicHome(QThread):
    """The shelves YouTube Music opens on, which is what fills the music view
    before anything has been searched for."""

    shelves = Signal("QVariantList")
    failed = Signal(str)

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

    def cancel(self) -> None:
        pass

    def run(self) -> None:
        from .sources import ytmusic

        try:
            found = ytmusic.home(self._cfg.browser_profile_path)
        except ytmusic.MusicError as exc:
            self.failed.emit(str(exc))
            return
        for shelf in found:
            for item in shelf["items"]:
                item["thumbnail"] = qml_source(item["thumbnail"])
        self.shelves.emit(found)


class TrackList(QThread):
    """Tracks for one thing that was chosen. A playlist from YouTube Music, or
    the liked videos from YouTube, which are a different list entirely."""

    tracks = Signal("QVariantList", str)
    failed = Signal(str)

    LIKED = "liked"

    def __init__(self, cfg: Config, what: str, playlist_id: str = "",
                 label: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._what = what
        self._playlist_id = playlist_id
        self._label = label
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        if self._what == self.LIKED:
            self._liked()
        else:
            self._playlist()

    def _playlist(self) -> None:
        from .sources import ytmusic

        try:
            found = ytmusic.playlist_tracks(self._cfg.browser_profile_path, self._playlist_id)
        except ytmusic.MusicError as exc:
            self.failed.emit(str(exc))
            return
        self.tracks.emit([{
            "key": t.key, "videoId": t.video_id, "title": t.title, "artist": t.artist,
            "album": t.album, "duration": t.duration, "thumbnail": qml_source(t.thumbnail_url),
        } for t in found], self._label)

    def _liked(self) -> None:
        """Liked videos come from YouTube rather than YouTube Music. The two
        lists are separate, and this is the one that has anything in it."""
        from .cookies import args as cookie_args

        command = ["yt-dlp", "--no-warnings", "--flat-playlist",
                   *cookie_args(self._cfg), "--playlist-end", "100",
                   "--print", "%(id)s\t%(title)s\t%(channel)s\t%(duration)s", ":ytfav"]
        try:
            result = run_process(command, cancel=self._cancel, timeout=180)
        except ProcessCancelled:
            return
        except Exception as exc:                                    # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return

        rows = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2 or len(parts[0]) != 11:
                continue
            seconds = parts[3] if len(parts) > 3 else ""
            try:
                total = int(float(seconds))
                length = f"{total // 60}:{total % 60:02d}"
            except ValueError:
                length = ""
            rows.append({
                "key": f"yt:{parts[0]}", "videoId": parts[0], "title": parts[1],
                "artist": parts[2] if len(parts) > 2 else "", "album": "",
                "duration": length,
                "thumbnail": qml_source(f"https://i.ytimg.com/vi/{parts[0]}/hqdefault.jpg"),
            })
        if not rows:
            self.failed.emit("no liked videos came back")
            return
        self.tracks.emit(rows, self._label)


class SourceDetails(QThread):
    """A picture and a name for a saved address, so the row is worth looking
    at rather than being a bare string."""

    done = Signal()

    def __init__(self, db: Database, cfg: Config, url: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._url = url
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        from .cookies import args as cookie_args

        command = ["yt-dlp", "--no-warnings", "--simulate", *cookie_args(self._cfg),
                   "--print", "%(title)s\t%(thumbnail)s", self._url]
        try:
            result = run_process(command, cancel=self._cancel, timeout=120)
        except Exception:                                           # noqa: BLE001
            return
        line = next((l for l in result.stdout.splitlines() if l.strip()), "")
        parts = line.split("\t")
        title = parts[0].strip() if parts and parts[0] != "NA" else None
        picture = parts[1].strip() if len(parts) > 1 and parts[1] != "NA" else None
        self._db.set_source_details(self._url, title, picture)
        self._db.close()
        self.done.emit()
