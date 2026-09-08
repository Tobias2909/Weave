"""Background work.

A refresh runs in two phases, and each one is allowed to fail on its own. RSS
is the only phase the feed truly needs, so a broken login or a missing yt-dlp
costs the duration badges while the feed itself keeps working.

  1  the subscriptions sweep, one paginated call that names every subscribed
     channel with something new and joins in durations and live flags
  2  channel RSS, which brings those videos in with their exact publish times

That order is the point. The sweep is one call covering every subscription, so
the feeds only have to be asked where there is a reason to, and a new video
reaches the grid within one sweep interval instead of within a full lap of
several hundred channels.

Rounds are small and frequent rather than large and rare. What the feed
endpoint objects to is a burst; the same hourly volume spread evenly is both
safer and quicker to come round. Each channel carries its own interval, from
how recently it published, so a channel that has not posted in years does not
cost the same as one that posts daily.

Concurrency is bounded three times over, by the executor, by the global
throttle, and by a persistent per endpoint budget that a restart cannot
forget.
"""

from __future__ import annotations

import random
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from . import backoff, imagecache, tokens
from .budget import BROWSE, DISLIKES, FEEDS, OEMBED, PLAYER, TWITCH, Budget
from .config import Config
from .db import Database
from .ids import channel_key
from .imagecache import qml_source
from .net import Cancelled as FetchCancelled
from .net import Fetcher, HttpError, Throttle
from .process import Cancelled as ProcessCancelled
from .process import run as run_process
from .sources import channel as channel_source
from .sources import comments as comment_source
from .sources import dislikes as dislike_source
from .sources import flatlist, lengths, livecheck, oembed, rss, subs, sweep, twitch
from .sources import history as history_source
from .sources import playlists as playlist_source
from .sources import recommended as recommended_source
from .sources import release as release_source
from .sources import search as search_source


def _spend(db: Database, cfg: Config, endpoint: str, count: int = 1, refused: int = 0) -> None:
    """Count what a one shot worker asked for.

    These paths cannot burst, since each is one deliberate click, so they are
    counted but never refused. Counting them anyway is what makes the report
    the whole truth rather than only the polling half of it.
    """
    Budget(db, cfg.budget_limits, cfg.budget_window_s).spend(endpoint, count, refused)


class Worker(QThread):
    """What every background worker here is built on.

    Qt aborts the whole process if a running QThread is destroyed, so every
    worker has to be stoppable, and the bridge cancels and waits for all of
    them on the way out. Each worker used to declare its own cancel event and
    its own cancel method, and twice a worker reached the person using the
    application with an attribute its constructor had never set. What they all
    need is here, once, so a new worker cannot forget it.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Ask the work to stop. Honoured at the next check, and by every
        subprocess and request underneath through the same event."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @staticmethod
    def _throttle_for(cfg: Config, slots: int = 1) -> Throttle:
        """A throttle sized for one worker, with the configured gap."""
        return Throttle(slots, cfg.min_request_interval_s)

    # The work stopped on an exception nobody expected. Carries the
    # exception's name and message, so the window can say what happened and
    # put down whatever flag it raised while it waited.
    crashed = Signal(str)

    def run(self) -> None:
        """Do the work, and never let an exception leave the thread.

        An exception that escapes a QThread's run ends the thread quietly.
        No signal the worker promised is emitted, so a flag the window raised
        while it waited stays raised for the rest of the session, and the
        only trace is a traceback on a terminal nobody is watching. A poll
        died that way once and the window never refreshed again. So every
        worker does its work in `work`, and this is the one place an
        unexpected exception is caught, printed, and turned into a signal.

        A cancel is not a failure and says nothing. The database connection
        this thread opened belongs to this thread, so it is closed here on
        every way out rather than by each worker on each of its exits.
        """
        try:
            self.work()
        except (FetchCancelled, ProcessCancelled):
            pass
        except Exception as exc:
            traceback.print_exc()
            self.crashed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            db = getattr(self, "_db", None)
            if db is not None:
                db.close()

    def work(self) -> None:
        raise NotImplementedError(f"{type(self).__name__} defines no work")


# How many channels whose streams tab has never been asked get asked in one
# tick. A round of 15 channels a minute spends 225 feed requests in a fifteen
# minute window against a ceiling of 300, so there is room for about 60 more.
# Four a tick is 60 a window, which fits, and it settles a list of several
# hundred channels over a couple of hours without the feed itself slowing down.
LIVE_PROBES_PER_TICK = 4

# How many announced streams are asked about their start time in one live
# check. One request each, the answer is kept for good, and the live bar's own
# calls come first, so this is deliberately a trickle.
UPCOMING_PER_CHECK = 3

# How many freshly published streams are asked about in one live check. Same
# arithmetic as above, and the same trickle: this only has anything to do at
# all in the minutes after a channel announces something.
NEW_STREAMS_PER_CHECK = 3

# How many rounds in a row the long form feed has to answer 404 before that is
# believed. The endpoint refuses a burst with a 404 rather than with a busy
# signal, and a refusal lasts minutes while a missing tab lasts for ever, so
# one round says nothing. Two rounds are a quarter of an hour apart at the
# fastest tier, which no burst measured here has outlived.
LONG_FORM_STRIKES = 2

# How long a channel stays on the mixed feed before the long form tab is
# offered another chance. A channel that had no long form videos when it was
# first asked can post one at any time, and nothing else would ever notice.
VARIANT_RECHECK_S = 7 * 86400

# How many channels on the mixed feed have their Shorts tab read in one tick.
# The mixed feed says nothing about the kind of what it carries, so this is
# what tells its rows apart, and it is paced for the same reason the streams
# probes are: a one off cost across a long list must not arrive as a burst.
SHORTS_SWEEPS_PER_TICK = 2

# What a 404 on the long form feed leaves behind, since the caller rather than
# the fetch decides what it meant.
MISSING_LONG_FORM = "missing-long-form"


def _column(row, name: str, default=None):
    """Read a column that an older row or a hand built one may not carry."""
    try:
        value = row[name]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _on_mixed_feed(row) -> bool:
    return (_column(row, "feed_variant", "") or "") == rss.CHANNEL


def _worth_a_streams_probe(row, tiers) -> bool:
    """Whether to spend the one request that says if this channel streams.

    Only a channel that is still publishing, or one nothing is stored from at
    all, which is a first look rather than a dormant one.

    MEASURED on a real list of 466 channels: 301 of the 307 never asked had
    published nothing in ninety days, and the probes were a fifth of the whole
    feed ceiling. A dormant channel that starts up again publishes something,
    which moves it into a faster tier by itself, and it is asked then.
    """
    if _column(row, "last_published_at") is None:
        return True
    return int(_column(row, "interval_s", tiers.warm_s)) <= tiers.warm_s


def _wants_shorts_sweep(row, now: int) -> bool:
    """Whether this channel's Shorts tab is owed a look.

    Only a channel on the mixed feed is: every other channel is asked for the
    long form tab, which carries no Shorts at all. Paced by the channel's own
    interval, so a busy channel is sorted out as often as it is polled and a
    dormant one is not asked about a tab it barely uses.
    """
    if not _on_mixed_feed(row):
        return False
    swept = _column(row, "shorts_sweep_at")
    return not swept or swept <= now - int(_column(row, "interval_s", 0))


def _wants_variant_retest(row, now: int) -> bool:
    """Whether to ask the long form tab of a channel that fell back to the
    mixed one.

    Not before that channel's Shorts tab has been read once. The rows it
    stored while it was on the mixed feed are of unknown kind, and the Shorts
    tab is the only thing that says which of them are Shorts, so they have to
    be sorted out while it is still known that this channel was ever there.
    """
    if not _on_mixed_feed(row) or not _column(row, "shorts_sweep_at"):
        return False
    checked = _column(row, "variant_checked_at")
    return not checked or checked <= now - VARIANT_RECHECK_S


class FeedPoller(Worker):
    finished_poll = Signal(int, int, int)   # channels polled, rows touched, failures
    progress = Signal(str, int, int)        # phase, done, total
    failure = Signal(str, str)              # source label, error text

    def __init__(self, db: Database, cfg: Config, force_all: bool = False,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._force_all = force_all
        self._throttle = self._throttle_for(cfg, cfg.max_concurrency)
        # What the sweep learned about videos that were not stored yet. Applied
        # again once the feeds have run, see _phase_details_again.
        self._late_details: list[tuple[str, int | None, str | None, int | None]] = []

    def work(self) -> None:
        fetcher = Fetcher(self._throttle, cancel=self._cancel)
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        polled = touched = failures = 0
        try:
            # The sweep first, because what it finds decides which feeds are
            # worth asking in the same tick.
            touched += self._phase_sweep(budget)
            if not self._cancel.is_set():
                polled, rss_touched, failures = self._phase_rss(fetcher, budget)
                touched += rss_touched
            touched += self._phase_details_again()
        except (FetchCancelled, ProcessCancelled):
            pass
        except Exception as exc:
            # Nothing may escape here. The interface holds a flag while a poll
            # is in flight and clears it on finished_poll, so a poll that dies
            # on the way out leaves that flag raised and nothing refreshes
            # again for the rest of the session. One that says what happened
            # and then finishes is recoverable; a dead thread is not.
            traceback.print_exc()
            failures += 1
            self.failure.emit("feeds", f"the refresh stopped, {type(exc).__name__}: {exc}")
        finally:
            fetcher.close()
        self.finished_poll.emit(polled, touched, failures)

    def _budget_notice(self, endpoint: str, allowance) -> None:
        """Say when a ceiling is what stopped work, but not on every tick.

        A silent no-op is the worst possible behaviour here, because it is
        indistinguishable from the app being broken. Repeating it once a
        minute would be almost as bad.
        """
        stamp = self._db.get_int(f"budget_notice.{endpoint}", 0)
        now = int(time.time())
        if now - stamp < 300:
            return
        self._db.set_state(f"budget_notice.{endpoint}", str(now))
        wait = max(0, allowance.frees_at - now)
        self.failure.emit(
            endpoint,
            f"asked as much as it should for now, {wait // 60 + 1} min until there is room")

    def _resting(self) -> bool:
        """Whether the feed endpoint is being left alone at the moment.

        A forced refresh goes anyway. That is somebody asking, in front of the
        window, and an application that ignores a button is worse than one
        that asks too often.
        """
        left = self._db.resting_until(FEEDS) - int(time.time())
        if left <= 0:
            return False
        if self._force_all:
            self._db.rest_endpoint(FEEDS, 0, self._db.rest_step(FEEDS))
            return False
        self._rest_notice(left)
        return True

    def _rest_notice(self, left: int) -> None:
        """Say it, but not once a minute for half an hour."""
        stamp = self._db.get_int(f"rest_notice.{FEEDS}", 0)
        now = int(time.time())
        if now - stamp < 300:
            return
        self._db.set_state(f"rest_notice.{FEEDS}", str(now))
        self.failure.emit(FEEDS, backoff.said("feed", left))

    def _weigh_refusals(self) -> None:
        """Decide, after a round, whether the endpoint is pushing back.

        Read from what was recorded rather than from this round alone, so a
        small round lands against the same few minutes a large one does, and
        so a restart's first round sees what the last one ran into.
        """
        sent, refused = self._db.requests_in_window(FEEDS, backoff.WINDOW_S)
        rest = backoff.next_rest(sent, refused, self._db.rest_step(FEEDS))
        if not rest.resting:
            if self._db.resting_until(FEEDS) or self._db.rest_step(FEEDS):
                self._db.rest_endpoint(FEEDS, 0, 0)
            return
        self._db.rest_endpoint(FEEDS, int(time.time()) + rest.seconds, rest.step)
        self._db.set_state(f"rest_notice.{FEEDS}", "0")
        self._rest_notice(rest.seconds)

    # ---- phase 1 ---------------------------------------------------------

    def _phase_sweep(self, budget: Budget) -> int:
        """One call over every subscription. Fills in durations and live
        flags, and names the channels that have something new."""
        if not self._cfg.sweep_limit:
            return 0
        interval = self._cfg.sweep_interval_s
        last = self._db.get_int("sweep_at", 0)
        if not self._force_all and interval and time.time() - last < interval:
            return 0
        allowance = budget.allowance(BROWSE, 1, background=True)
        if allowance.empty:
            self._budget_notice(BROWSE, allowance)
            return 0

        self.progress.emit("durations", 0, 1)
        budget.spend(BROWSE, 1)
        try:
            videos = sweep.fetch(self._cfg, self._cfg.sweep_limit, self._throttle,
                                 cancel=self._cancel)
        except ProcessCancelled:
            return 0
        except sweep.SweepError as exc:
            budget.spend(BROWSE, 0, refused=1)
            # Said plainly, because more rides on this call now than the
            # durations: while it does not answer, anything new is found by
            # the per channel feeds again, slower and at the old cost.
            self.failure.emit(
                "sweep",
                f"the subscriptions sweep did not answer, {exc}. Until it does, every "
                f"channel is asked on its own interval and new videos take longer to show")
            return 0

        # Stamped only on an answer, so a failure is retried on the next tick
        # rather than waiting out the interval.
        self._db.set_state("sweep_at", str(int(time.time())))
        # Every channel the sweep lists is one it watches, and one that is
        # therefore asked on its own only now and then. And the views it
        # carries keep the counts of the newest videos fresh for nothing.
        self._db.mark_sweep_seen({channel_key(v.channel_id) for v in videos if v.channel_id})
        self._db.raise_views([(v.key, v.views) for v in videos if v.views])
        filled = self._db.fill_details(
            [(v.key, v.duration_s, v.live_status, v.scheduled_at) for v in videos])

        unknown = self._db.unknown_video_keys([v.key for v in videos])
        # fill_details is an update, so what it was told about a video the
        # feeds have not stored yet went nowhere. Kept for after the feeds.
        self._late_details = [(v.key, v.duration_s, v.live_status, v.scheduled_at)
                              for v in videos if v.key in unknown]
        if unknown:
            owners = {channel_key(v.channel_id) for v in videos
                      if v.key in unknown and v.channel_id}
            promoted = self._db.promote_channels(owners)
            if promoted:
                self.progress.emit("new", promoted, promoted)
        self.progress.emit("durations", 1, 1)
        return filled

    def _sweep_fresh(self) -> bool:
        """Whether the sweep can be leaned on for finding what is new.

        While it answers, a channel it covers is asked on its own only every
        few hours, since anything new from it arrives through the sweep and a
        promotion. The moment it has been silent longer than sweep_stale_s,
        because yt-dlp broke or the cookies died, every channel is back on its
        tiered interval, so the feed keeps moving with nothing to notice but
        the doctor saying so.
        """
        if not self._cfg.sweep_limit or not self._cfg.sweep_stale_s:
            return False
        return time.time() - self._db.get_int("sweep_at", 0) < self._cfg.sweep_stale_s

    def _phase_details_again(self) -> int:
        """Apply the sweep's durations and live flags a second time.

        The sweep runs first, so anything it named that the feeds went on to
        store in the same round was not there to be updated when it spoke.
        A stream is the case that matters: RSS carries no live flag at all, so
        without this the badge and the live bar wait for the next sweep, which
        is a quarter of an hour away. It costs no request, since this is the
        answer the sweep already gave.
        """
        late, self._late_details = self._late_details, []
        return self._db.fill_details(late) if late else 0

    # ---- phase 2 ---------------------------------------------------------

    def _feed_jobs(self, rows: list) -> list[tuple[str, str, str]]:
        """One job per feed to fetch, as key, channel id and which tab.

        Streams live in their own tab, so a channel not asked for that tab
        shows a stream only once it has ended. Every channel known to stream
        is asked for it every round, which is cheap because most channels do
        not stream.

        The ones nobody has looked at are asked a few at a time, and only if
        they are still publishing. Nothing else reveals that a channel
        streams, so they have to be asked, but asking all of them at once
        would double a round and press against the request ceiling, and there
        is no hurry about a question that is answered once and then remembered
        for good.

        MEASURED on a real list: 301 of the 307 channels that had never been
        asked had published nothing in ninety days, and those probes were a
        fifth of the whole feed ceiling, spent on channels with nothing to
        stream. A channel that publishes anything climbs back into a faster
        tier by that alone, and is asked then.
        """
        now = int(time.time())
        # A channel that fell back to the mixed feed is asked for the long
        # form tab again now and then, rather than being left there for good
        # on the strength of one 404.
        jobs = [(row["key"], row["ext_id"],
                 rss.VIDEOS if _wants_variant_retest(row, now)
                 else (row["feed_variant"] or rss.VIDEOS))
                for row in rows]
        # The mixed feed says nothing about the kind of what it carries, so
        # the Shorts tab of a channel on it is read as well. A few a tick:
        # this is a one off cost for most channels and must not burst.
        jobs += [(row["key"], row["ext_id"], rss.SHORTS) for row in rows
                 if _wants_shorts_sweep(row, now)
                 and not _wants_variant_retest(row, now)][:SHORTS_SWEEPS_PER_TICK]
        if not self._cfg.poll_live_feeds:
            return jobs
        streamers = self._db.channels_that_stream()
        unasked = self._db.channels_not_asked_for_streams()
        tiers = self._cfg.feed_tiers
        wanted = [row for row in rows if row["key"] in streamers]
        wanted += [row for row in rows if row["key"] in unasked
                   and _worth_a_streams_probe(row, tiers)][:LIVE_PROBES_PER_TICK]
        jobs += [(row["key"], row["ext_id"], rss.LIVE) for row in wanted
                 if (row["feed_variant"] or "") != rss.CHANNEL]
        return jobs

    def _fetch_one(self, fetcher: Fetcher, ext_id: str, kind: str) -> tuple[object, int, str | None]:
        """Fetch one feed, returning the result, how many requests it cost and
        a variant to remember.

        A 404 on a tab feed is ambiguous. It means the channel has no such tab,
        and it also means the endpoint is refusing us, which it does with a 404
        rather than with a busy signal, in bursts, and for channels that are
        perfectly fine. Asking the mixed feed there and then does not tell the
        two apart: measured on this endpoint, a burst refuses the per tab
        playlist feeds while the mixed channel feed keeps answering, which is
        how a hundred healthy channels ended up on the mixed feed for good,
        and Shorts with them.

        So nothing is decided here. A 404 on the long form tab returns no
        result and says what happened, and the caller counts it against the
        channel; only a channel that answers 404 in several rounds in a row
        falls back. Nothing is fetched in its place in the meantime, which
        costs that channel one round and costs a burst nothing at all.

        The streams and Shorts tabs are the cases with nothing to fall back
        to, since a channel that has never streamed or never posted a Short
        genuinely has no such tab. A 404 there returns no result as well, and
        the caller decides what it meant.
        """
        try:
            return rss.fetch(fetcher, ext_id, kind), 1, None
        except HttpError as exc:
            if exc.status != 404 or kind == rss.CHANNEL:
                raise
            if kind == rss.VIDEOS:
                return None, 1, MISSING_LONG_FORM
            return None, 1, None

    def _phase_rss(self, fetcher: Fetcher, budget: Budget) -> tuple[int, int, int]:
        if self._resting():
            return 0, 0, 0
        rows = self._db.channels_due(self._cfg.feed_tiers,
                                     limit=self._cfg.channels_per_tick,
                                     force=self._force_all,
                                     sweep_fresh=self._sweep_fresh())
        if not rows:
            return 0, 0, 0
        jobs = self._feed_jobs(rows)
        now = int(time.time())
        # Channels being offered the long form tab again after having fallen
        # back to the mixed one. A stamp goes on whatever the answer is, so a
        # channel that really has no such tab is not asked every round.
        retests = {row["key"] for row in rows if _wants_variant_retest(row, now)}
        # Channels carrying a 404 from an earlier round. An answer clears it.
        struck = {row["key"] for row in rows if _column(row, "long_form_404s", 0)}

        allowance = budget.allowance(FEEDS, len(jobs), background=True)
        if allowance.empty:
            self._budget_notice(FEEDS, allowance)
            return 0, 0, 0
        jobs = jobs[:allowance.granted]
        # Shuffled so the same order is not sent every time. NewPipe does the
        # same thing and says why: a fixed order over a large subscription list
        # is itself identifying.
        random.shuffle(jobs)

        touched = failures = done = 0
        spent = 0
        wire_before = fetcher.sent if fetcher is not None else 0
        refused: list[str] = []
        polled: set[str] = set()
        # Channels whose streams tab answered 404. Whether that means they have
        # no such tab is decided after the round, since the endpoint refuses
        # with a 404 as well.
        no_streams: set[str] = set()
        total = len(jobs)
        with ThreadPoolExecutor(max_workers=self._cfg.max_concurrency) as pool:
            futures = {pool.submit(self._fetch_one, fetcher, ext_id, kind): (key, kind)
                       for key, ext_id, kind in jobs}
            for future in as_completed(futures):
                if self._cancel.is_set():
                    # Drops what has not started. Anything already in flight
                    # finishes on its own timeout, which is why the request
                    # timeout is kept short.
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                key, kind = futures[future]
                try:
                    result, cost, note = future.result()
                except (FetchCancelled, ProcessCancelled):
                    break
                except Exception as exc:
                    failures += 1
                    spent += 1
                    message = f"{type(exc).__name__}: {exc}"
                    self._db.mark_polled(key, message)
                    # Not one report per channel. The endpoint answers a burst
                    # with a refusal per channel, and a few hundred of those
                    # say one thing, not a few hundred things.
                    refused.append(key)
                else:
                    spent += cost
                    pending: list[str] = []
                    if note == MISSING_LONG_FORM:
                        # Ambiguous on its own. Counted against the channel,
                        # and believed only once it has happened in several
                        # rounds in a row. Counted as a refusal as well, since
                        # a 404 is what this endpoint says when it is pushing
                        # back and a round full of them is what the rest is
                        # there to answer. Except for a channel already on
                        # the mixed feed being offered the tab again: it has
                        # answered that way in several rounds already, so a
                        # Shorts only channel saying so once more a week is
                        # an answer, not the endpoint refusing.
                        if key not in retests:
                            refused.append(key)
                        if self._db.note_long_form_missing(key) >= LONG_FORM_STRIKES:
                            self._db.set_feed_variant(key, rss.CHANNEL)
                        if key in retests:
                            self._db.stamp_variant_checked(key)
                        # Stamped, though nothing was stored: the channel is
                        # one round late, and that is the price of not letting
                        # a refusal rewrite where it is read from. It is not
                        # one of the channels that answered, since a 404 is
                        # exactly what the endpoint refusing us looks like and
                        # the streams verdict below leans on that set.
                        self._db.mark_polled(key, None)
                        done += 1
                        self.progress.emit("feeds", done, total)
                        continue
                    if kind == rss.SHORTS:
                        # Whatever the tab said, the question has been asked.
                        # A channel with no Shorts tab answers 404, which is
                        # an answer like any other.
                        self._db.stamp_shorts_sweep(key)
                        if result is not None:
                            # Stored as Shorts, which is what keeps them out
                            # of the feed. A row already here from the mixed
                            # feed carries no kind at all, and this is what
                            # fills that in.
                            touched += self._db.upsert_videos(result.videos)
                        done += 1
                        self.progress.emit("feeds", done, total)
                        continue
                    if kind == rss.VIDEOS:
                        if key in retests:
                            # The long form tab answers again, so the fallback
                            # goes and this channel is back to a feed that
                            # carries no Shorts.
                            self._db.set_feed_variant(key, None)
                            self._db.stamp_variant_checked(key)
                        elif key in struck:
                            self._db.clear_long_form_strikes(key)
                    if kind == rss.LIVE:
                        if result is None:
                            no_streams.add(key)
                            done += 1
                            self.progress.emit("feeds", done, total)
                            continue
                        self._db.set_channel_streams(key, True)
                        # An announcement is published with nothing watching
                        # it, and in a streams tab that is the one thing an
                        # ordinary entry never looks like: every real stream
                        # in there has been watched by somebody. Measured on
                        # a live feed, the announced one was the only entry of
                        # fifteen with no views. The ones that look like that
                        # and are new here are asked about once, since the
                        # feed itself never says which is which and a card
                        # that cannot be played must not look like one that
                        # can.
                        fresh = self._db.unknown_video_keys([v.key for v in result.videos])
                        pending = [v.key for v in result.videos
                                   if v.key in fresh and not v.views]
                    touched += self._db.upsert_videos(result.videos)
                    if kind == rss.LIVE and pending:
                        self._db.mark_streams_pending(pending)
                    if result.channel_title:
                        self._db.add_channel(key, "youtube", key.split(":", 1)[1],
                                             result.channel_title)
                    self._db.mark_polled(key, None)
                    polled.add(key)
                    if (kind != rss.LIVE and not result.videos
                            and self._db.channel_has_videos(key)):
                        # Zero entries with no error is what a broken source
                        # looks like. But a channel that has never produced a
                        # video is simply empty, and there are plenty of those
                        # in a large subscription list, so only a channel that
                        # used to have videos and now has none is reported.
                        self.failure.emit(key, "returned no entries")
                done += 1
                self.progress.emit("feeds", done, total)

        # A streams tab that 404s while the same channel's videos feed
        # answered is a channel that does not stream, and it is not asked
        # again. One that 404s in a round where that channel answered nothing
        # is the endpoint pushing back, so no verdict is stored and it is
        # asked again later.
        for key in no_streams & polled:
            self._db.set_channel_streams(key, False)

        if fetcher is not None:
            # What went over the wire, retries included, rather than what was
            # asked for. The endpoint counts it that way.
            spent = max(spent, fetcher.sent - wire_before)
        budget.spend(FEEDS, spent, refused=len(refused))
        # After the spend, so this round's refusals count towards the decision
        # rather than only the rounds before it.
        self._weigh_refusals()
        if (backoff.pushing_back(total, len(refused))
                and not self._db.resting_until(FEEDS)):
            # Said only when the round looks like the endpoint pushing back.
            # One channel in thirty not answering is a Shorts only channel
            # without a long form tab, or one bad connection, and a banner
            # about the endpoint for that read as the application being
            # throttled every time it was not. What one channel said is kept
            # on the channel and shown by the doctor.
            self.failure.emit(
                "feeds",
                f"{len(refused)} of {total} feeds did not answer. The feed endpoint "
                f"replies to a burst with a refusal rather than saying it is busy, so "
                f"this usually clears on its own")
        return len(polled), touched, failures


class ChannelAdder(Worker):
    """Resolves a channel reference off the interface thread.

    Resolving costs about half a second, short enough not to need a progress
    bar and long enough to be felt as a freeze on the interface thread.
    """

    added = Signal(str, str, str, str)   # key, platform, ext_id, title
    failed = Signal(str)

    def __init__(self, ref, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ref = ref
        self._throttle = self._throttle_for(cfg)

    def work(self) -> None:
        from .sources.resolve import ResolveError, resolve

        try:
            result = resolve(self._ref, throttle=self._throttle, cancel=self._cancel)
        except ProcessCancelled:
            return
        except ResolveError as exc:
            self.failed.emit(str(exc))
            return
        self.added.emit(result.key, result.platform, result.ext_id, result.title or "")


class SubsImporter(Worker):
    """Imports the subscription list, names and avatars included."""

    imported = Signal(int, int)          # total found, newly added
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._throttle = self._throttle_for(cfg)

    def work(self) -> None:
        _spend(self._db, self._cfg, BROWSE)
        try:
            channels = subs.fetch(self._cfg, self._throttle, cancel=self._cancel)
        except ProcessCancelled:
            return
        except subs.ImportError_ as exc:
            _spend(self._db, self._cfg, BROWSE, count=0, refused=1)
            self.failed.emit(str(exc))
            return
        added = 0
        for channel in channels:
            if self._db.add_channel(channel.key, "youtube", channel.ext_id,
                                    channel.title, channel.avatar_url):
                added += 1
        self.imported.emit(len(channels), added)


class HistoryImporter(Worker):
    """Reads the history YouTube keeps, which is the whole of it.

    mpv already tells YouTube when it plays something, so YouTube's copy is
    the complete one. It is kept as its own list, and the stored videos in it
    are marked watched as well, since that is what the feed's hide watched
    toggle reads.
    """

    imported = Signal(int, int)          # entries read, newly marked as watched
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, limit: int = 200,
                 start: int = 1, append: bool = False,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._limit = limit
        self._start = start
        self._append = append
        self._throttle = self._throttle_for(cfg)

    def work(self) -> None:
        _spend(self._db, self._cfg, BROWSE)
        try:
            found = history_source.fetch(self._cfg, self._limit, self._throttle,
                                         cancel=self._cancel, start=self._start)
        except ProcessCancelled:
            return
        except history_source.HistoryError as exc:
            _spend(self._db, self._cfg, BROWSE, count=0, refused=1)
            self.failed.emit(str(exc))
            return
        rows = [flatlist.as_row(item) for item in found]
        kind = self._db.HISTORY
        added = (self._db.append_cached(kind, rows) if self._append
                 else self._db.replace_cached(kind, rows))
        marked, _ = self._db.mark_watched_many(history_source.keys_of(found), "youtube")
        self.imported.emit(added, marked)


class RecommendationsFetcher(Worker):
    """What YouTube suggests, fetched on demand.

    Kept out of the feed and out of the videos table, so a suggestion never
    looks like something followed.
    """

    ready = Signal(int)
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, limit: int = 48,
                 start: int = 1, append: bool = False,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._limit = limit
        self._start = start
        self._append = append
        self._throttle = self._throttle_for(cfg)

    def work(self) -> None:
        _spend(self._db, self._cfg, BROWSE)
        try:
            found = recommended_source.fetch(self._cfg, self._limit, self._throttle,
                                             cancel=self._cancel, start=self._start)
        except ProcessCancelled:
            return
        except recommended_source.RecommendedError as exc:
            _spend(self._db, self._cfg, BROWSE, count=0, refused=1)
            self.failed.emit(str(exc))
            return
        rows = [flatlist.as_row(item) for item in found]
        count = (self._db.append_recommended(rows) if self._append
                 else self._db.replace_recommended(rows))
        self.ready.emit(count)


class PlaylistsFetcher(Worker):
    """The list of your playlists, without their contents.

    Two calls rather than one, because the list is cheap and the contents are
    not, and most playlists are never opened.
    """

    ready = Signal(int)
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._throttle = self._throttle_for(cfg)

    def work(self) -> None:
        _spend(self._db, self._cfg, BROWSE)
        try:
            found = playlist_source.fetch_list(self._cfg, throttle=self._throttle,
                                               cancel=self._cancel)
        except ProcessCancelled:
            return
        except playlist_source.PlaylistError as exc:
            _spend(self._db, self._cfg, BROWSE, count=0, refused=1)
            self.failed.emit(str(exc))
            return
        count = self._db.replace_playlists(
            [{"ext_id": item.ext_id, "title": item.title} for item in found])
        self.ready.emit(count)


class PlaylistItemsFetcher(Worker):
    """One playlist's videos, read when it is first opened."""

    ready = Signal(str, int)
    failed = Signal(str, str)

    def __init__(self, db: Database, cfg: Config, playlist_id: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._playlist_id = playlist_id
        self._throttle = self._throttle_for(cfg)

    def work(self) -> None:
        _spend(self._db, self._cfg, BROWSE)
        try:
            items, skipped = playlist_source.fetch_items(self._cfg, self._playlist_id,
                                                         throttle=self._throttle,
                                                         cancel=self._cancel)
        except ProcessCancelled:
            return
        except playlist_source.PlaylistError as exc:
            _spend(self._db, self._cfg, BROWSE, count=0, refused=1)
            self.failed.emit(self._playlist_id, str(exc))
            return
        count = self._db.replace_playlist_items(
            self._playlist_id, [flatlist.as_row(item) for item in items], skipped)
        self.ready.emit(self._playlist_id, count)


class SearchFetcher(Worker):
    """Searching YouTube itself, one page at a time.

    Weave's own search is a query over the stored database and costs nothing.
    This one costs a request, so it runs when asked for rather than while
    typing.
    """

    results = Signal(str, int, "QVariantList")     # query, page start, results
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, query: str, start: int = 1,
                 count: int = 24, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._query = query
        self._start = start
        self._count = count
        self._throttle = self._throttle_for(cfg)

    def work(self) -> None:
        _spend(self._db, self._cfg, BROWSE)
        try:
            found = search_source.fetch(self._cfg, self._query, self._start, self._count,
                                        self._throttle, cancel=self._cancel)
        except ProcessCancelled:
            return
        except search_source.SearchError as exc:
            _spend(self._db, self._cfg, BROWSE, count=0, refused=1)
            self.failed.emit(str(exc))
            return
        self.results.emit(self._query, self._start,
                          [flatlist.as_row(item) | {"views": item.views} for item in found])


class Checkup(Worker):
    """The doctor's checks, off the interface thread.

    Two of them make a request, and all of them touch the disk, so this does
    not belong on the thread that draws.
    """

    ready = Signal("QVariantList")

    def __init__(self, db: Database, cfg: Config, network: bool = True,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._network = network

    def work(self) -> None:
        from . import doctor

        report = doctor.run(self._cfg, self._db, network=self._network)
        self.ready.emit([{"name": check.name, "state": check.state,
                          "detail": check.detail, "fix": check.fix}
                         for check in report.checks])


class UpdateCheck(Worker):
    """Whether a newer release than this one has been published.

    One request, at most once a day, and the answer is remembered so a
    restart does not ask again. The stamp is written only when the answer
    arrives, so being offline at launch means asking again next time rather
    than going quiet for a day.
    """

    # tag, address of the release page
    found = Signal(str, str)

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._throttle = self._throttle_for(cfg, 1)

    def work(self) -> None:
        fetcher = Fetcher(self._throttle, cancel=self._cancel)
        try:
            tag, address = release_source.fetch(fetcher)
        except Exception:
            # Nothing is said and nothing is remembered. A version check is
            # the least important thing here and not worth a line in the
            # problems list when the network is unhappy, and the day only
            # begins counting once an answer has actually arrived.
            return
        finally:
            fetcher.close()
        self.found.emit(tag, address)


class ImageCacheJob(Worker):
    """The picture cache measured, tidied or emptied, off the interface thread.

    All three walk the whole cache directory, which on a full one is tens of
    thousands of files, so none of them belongs on the thread that draws. The
    rules stay in imagecache, where the launch and the cache subcommand read
    them too, so the three cannot come to mean different things.
    """

    MEASURE = "measure"
    PRUNE = "prune"
    CLEAR = "clear"

    # what was asked for, bytes held afterwards, pictures dropped
    done = Signal(str, int, int)

    def __init__(self, directory: Path, what: str = MEASURE, ttl_seconds: int = 0,
                 max_bytes: int = 0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._directory = directory
        self._what = what
        self._ttl = ttl_seconds
        self._max_bytes = max_bytes

    def work(self) -> None:
        dropped = 0
        if self._what == self.CLEAR:
            # Everything is past its window when the window is nothing, so
            # emptying is the same call rather than a second way to delete.
            dropped, _freed = imagecache.prune(self._directory, 0)
        elif self._what == self.PRUNE:
            aged, _freed = imagecache.prune(self._directory, self._ttl)
            spilled, _over = imagecache.enforce_ceiling(self._directory, self._max_bytes)
            dropped = aged + spilled
        self.done.emit(self._what, imagecache.size_bytes(self._directory), dropped)


class ChannelDetailsFetcher(Worker):
    """Fills in a channel's banner and subscriber count the first time its page
    is opened."""

    fetched = Signal(str)
    failed = Signal(str, str)

    def __init__(self, db: Database, cfg: Config, channel_key: str, ext_id: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._key = channel_key
        self._ext_id = ext_id
        self._throttle = self._throttle_for(cfg)

    def work(self) -> None:
        _spend(self._db, self._cfg, BROWSE)
        try:
            details = channel_source.fetch(self._ext_id, self._throttle, self._cancel)
        except ProcessCancelled:
            return
        except channel_source.DetailsError as exc:
            _spend(self._db, self._cfg, BROWSE, count=0, refused=1)
            self.failed.emit(self._key, str(exc))
            return
        self._db.set_channel_details(self._key, details.title, details.avatar_url,
                                     details.banner_url, details.follower_count)
        self.fetched.emit(self._key)


class ChannelFeedFetcher(Worker):
    """One channel's own feed, asked for because its page was opened.

    The feed poller asks after the channels somebody follows, in an order and
    at a pace of its own. A channel page opened off a card is often neither
    followed nor due, and until this it showed whatever happened to be stored,
    which for a stranger is nothing at all.

    One request, against the same ceiling as the poller's, and the same
    fallback: a channel with no long form tab answers on the mixed feed.
    """

    fetched = Signal(str, int)            # channel key, rows touched
    failed = Signal(str, str)

    def __init__(self, db: Database, cfg: Config, channel_key: str, ext_id: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._key = channel_key
        self._ext_id = ext_id
        self._throttle = self._throttle_for(cfg, 1)

    def work(self) -> None:
        fetcher = Fetcher(self._throttle, cancel=self._cancel)
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        if budget.allowance(FEEDS, 1).empty:
            fetcher.close()
            self.failed.emit(self._key, "asked as much as it should for now")
            return
        variant = self._db.channel(self._key)
        variant = (variant or {}).get("feed_variant") or rss.VIDEOS
        try:
            budget.spend(FEEDS)
            try:
                result = rss.fetch(fetcher, self._ext_id, variant)
            except HttpError as exc:
                if exc.status != 404 or variant == rss.CHANNEL:
                    raise
                # Either there is no long form tab or the endpoint is refusing
                # us, and one call cannot tell those apart. The page is opened
                # either way, from the mixed feed, but nothing is remembered
                # from it: which feed answers for a channel is decided by the
                # poller, which sees the same channel round after round.
                budget.spend(FEEDS)
                result = rss.fetch(fetcher, self._ext_id, rss.CHANNEL)
        except (FetchCancelled, ProcessCancelled):
            fetcher.close()
            return
        except Exception as exc:
            budget.spend(FEEDS, count=0, refused=1)
            fetcher.close()
            self.failed.emit(self._key, f"{type(exc).__name__}: {exc}")
            return
        touched = self._db.upsert_videos(result.videos)
        if result.channel_title:
            # remember rather than add. Opening a stranger's page is not
            # following them, and add_channel would do exactly that.
            self._db.remember_channel(self._key, "youtube", self._ext_id, result.channel_title)
        self._db.mark_polled(self._key, None)
        touched += self._read_streams_once(fetcher, budget, variant)
        fetcher.close()
        self.fetched.emit(self._key, touched)

    def _read_streams_once(self, fetcher, budget, variant: str) -> int:
        """The streams tab, the first time this channel's page is opened.

        The page offers a streams half only for a channel with a stream stored,
        so a channel nobody has asked about would never grow one: the poller
        asks after the channels somebody follows, a few unasked ones a round,
        and a stranger opened from a search is in neither list.

        Once. The answer is remembered either way, so this is one request in
        the life of a channel rather than one per visit. A channel with no
        long form tab is skipped, the same way the poller skips it: what it
        has is a mixed feed, which the videos half already read.
        """
        if variant == rss.CHANNEL or not self._cfg.poll_live_feeds:
            return 0
        if (self._db.channel(self._key) or {}).get("streams") is not None:
            return 0
        if budget.allowance(FEEDS, 1).empty:
            return 0
        try:
            budget.spend(FEEDS)
            streams = rss.fetch(fetcher, self._ext_id, rss.LIVE)
        except HttpError as exc:
            if exc.status == 404:
                self._db.set_channel_streams(self._key, False)
            return 0
        except (FetchCancelled, ProcessCancelled):
            return 0
        except Exception:
            budget.spend(FEEDS, count=0, refused=1)
            return 0
        self._db.set_channel_streams(self._key, bool(streams.videos))
        return self._db.upsert_videos(streams.videos)


class ChannelPlaylistsFetcher(Worker):
    """What one channel's playlists tab lists.

    One call for the whole tab, and only names: the listing carries no video
    count and a real one is a call per playlist, so a count arrives later and
    free, from opening one.
    """

    fetched = Signal(str, int)            # channel key, how many
    failed = Signal(str, str)

    def __init__(self, db: Database, cfg: Config, channel_key: str, ext_id: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._key = channel_key
        self._ext_id = ext_id
        self._throttle = self._throttle_for(cfg)

    def work(self) -> None:
        _spend(self._db, self._cfg, BROWSE)
        try:
            found = playlist_source.fetch_channel_lists(
                self._cfg, self._ext_id, throttle=self._throttle, cancel=self._cancel)
        except ProcessCancelled:
            return
        except playlist_source.PlaylistError as exc:
            _spend(self._db, self._cfg, BROWSE, count=0, refused=1)
            self.failed.emit(self._key, str(exc))
            return
        self._db.replace_channel_playlists(self._key, found)
        self.fetched.emit(self._key, len(found))


class OwnerFetcher(Worker):
    """Who made the videos in a listing that nothing here knows the owner of.

    The history is what this is for. A row there carries an id, a title, a
    duration and a picture and says nothing whatsoever about the channel, so
    a card from a channel nobody follows had no name, no face and nothing to
    press. Most of them answer from the videos table; these are the rest.

    One small call each, 868 bytes measured, and once in the life of a video,
    because a video does not change hands. A few at a time so a page of
    history costs a trickle rather than a burst.
    """

    fetched = Signal(int)                 # how many were named
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, kind: str, limit: int = 12,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._kind = kind
        self._limit = limit
        self._throttle = self._throttle_for(cfg, 1)

    def work(self) -> None:
        wanted = self._db.videos_without_an_owner(self._kind, self._limit)
        if not wanted:
            return
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        allowance = budget.allowance(OEMBED, len(wanted), background=True)
        if allowance.empty:
            return
        fetcher = Fetcher(self._throttle, cancel=self._cancel)
        named = 0
        try:
            for ext_id in wanted[:allowance.granted]:
                if self._cancel.is_set():
                    break
                try:
                    budget.spend(OEMBED)
                    owner = oembed.fetch(fetcher, ext_id)
                except (FetchCancelled, ProcessCancelled):
                    break
                except Exception:
                    # A private or removed video answers with an error rather
                    # than a name. That is one card keeping the blank it had,
                    # not a failure worth reporting.
                    budget.spend(OEMBED, count=0, refused=1)
                    continue
                if owner is None:
                    continue
                self._db.remember_owner(ext_id, owner.channel_name, owner.handle,
                                        owner.channel_ext_id)
                named += 1
        finally:
            fetcher.close()
        if named:
            self.fetched.emit(named)


class LengthFiller(Worker):
    """The lengths RSS could not carry, filled in a channel at a time.

    RSS carries no duration, and the only thing that fills one in is the
    subscriptions sweep, which reaches the newest thousand videos across every
    subscription. Everything older arrived through a channel feed's fifteen
    entry window or through somebody opening a channel page, and was already
    past the sweep's reach when it was stored. Nothing asked a second time, so
    the durations simply stopped partway down a feed, which is exactly how it
    was reported.

    One call answers a whole channel, so this is ordered by how many rows a
    channel is owed rather than by anything about the channel. Two calls at
    most: the long form tab, and the streams tab for a channel known to
    stream, because a stream that came in through RSS carries no live state
    either and sits in the videos half of a group being a stream.

    Stamped whatever comes back. A channel whose remaining rows are private,
    deleted, or members only can never be answered, and asking again every
    poll would spend a request a minute for ever on nothing.
    """

    filled = Signal(int, int)             # rows filled, channels looked at
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, channels: int = 1,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._channels = max(1, channels)
        self._throttle = self._throttle_for(cfg, 1)

    def work(self) -> None:
        wanted = self._db.channels_missing_lengths(
            self._channels, older_than_s=self._cfg.length_recheck_s)
        if not wanted:
            return
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        filled = looked = 0
        for row in wanted:
            if self._cancel.is_set():
                break
            # Two at most, and both are wanted together or neither: a channel
            # stamped after only half its tabs were read would keep the other
            # half's gap until the recheck came round.
            #
            # channels.streams has three states and NULL is a question, not a
            # no, so the streams tab is read for anything but a definite no.
            # Measured on a copy of a real library: skipping the NULL ones left
            # exactly half of each of those channels' rows owed, because the
            # half that was left were the streams. The answer is kept while we
            # are here, so this also settles that question for free.
            tabs = [rss.VIDEOS] + ([rss.LIVE] if row["streams"] != 0 else [])
            allowance = budget.allowance(BROWSE, len(tabs), background=True)
            if allowance.granted < len(tabs):
                break
            owed = self._db.videos_without_a_length(row["key"])
            if not owed:
                self._db.mark_lengths_read(row["key"])
                continue
            found: list[tuple[str, int | None, str | None]] = []
            trouble = ""
            for kind in tabs:
                try:
                    budget.spend(BROWSE)
                    answer = lengths.fetch(row["ext_id"], kind, throttle=self._throttle,
                                           cancel=self._cancel)
                except (FetchCancelled, ProcessCancelled):
                    return
                except lengths.NoSuchTab:
                    # An answer rather than a refusal: there is no such tab, so
                    # there is nothing there to owe a length and the channel is
                    # settled. Not counted as refused, because the far side
                    # answered perfectly well.
                    if kind == rss.LIVE and row["streams"] is None:
                        self._db.set_channel_streams(row["key"], False)
                    continue
                except Exception as exc:
                    budget.spend(BROWSE, count=0, refused=1)
                    trouble = f"{type(exc).__name__}: {exc}"
                    break
                if kind == rss.LIVE and row["streams"] is None:
                    self._db.set_channel_streams(row["key"], bool(answer))
                found.extend((f"yt:{item.ext_id}", item.duration_s, item.live_status)
                             for item in answer if item.ext_id in owed)
            if trouble:
                # Left unstamped, so it is tried again rather than written off
                # on one bad answer.
                self.failed.emit(f"could not read a channel's tabs, {trouble}")
                break
            filled += self._db.fill_lengths(found)
            self._db.mark_lengths_read(row["key"])
            looked += 1
        if filled or looked:
            self.filled.emit(filled, looked)


class TwitchLogin(Worker):
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

    def work(self) -> None:
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
            try:
                tokens.save(got)
            except OSError as exc:
                # The login worked and the file did not. Said as what it is,
                # since a login that has to be done again next launch looks
                # like Twitch refusing rather than a disk refusing.
                self.failed.emit(f"the login could not be stored, {exc}")
                return
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
        return added


class LiveWatcher(Worker):
    """Who is live right now. Runs on its own timer, far more often than the
    feed, because a live bar that is fifteen minutes stale is wrong."""

    updated = Signal(int)
    needsLogin = Signal()
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._throttle = self._throttle_for(cfg, 2)

    def work(self) -> None:
        client_id = self._cfg.twitch_client_id
        stored = tokens.load()
        if not client_id or stored is None:
            self.needsLogin.emit()
            return
        try:
            client = twitch.Client(client_id, stored, on_tokens=tokens.save)
            # Two calls, the identity and the follow list. Twitch publishes a
            # generous points per minute limit and answers with a real 429, so
            # this is counted for the report rather than to hold anything back.
            _spend(self._db, self._cfg, TWITCH, 2)
            streams = client.followed_streams(client.account_id())

            # Channels added by hand are not necessarily followed, so they are
            # asked about separately and merged.
            tracked = {row["ext_id"].lower()
                       for row in self._db.channels(platform="twitch")}
            missing = sorted(tracked - {stream.login for stream in streams})
            if missing and not self._cancel.is_set():
                _spend(self._db, self._cfg, TWITCH)
                streams.extend(client.streams_for(missing))
        except twitch.NeedsLogin:
            self.needsLogin.emit()
            return
        except twitch.TwitchError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return

        # A stream says nothing about what its broadcaster looks like, so the
        # icons are fetched once per channel and stored alongside it. A
        # picture that cannot be fetched is not a reason to lose the streams
        # that were, so this failing is said and then set aside.
        try:
            self._fetch_missing_avatars(client)
        except Exception as exc:
            self.failed.emit(f"channel pictures, {type(exc).__name__}: {exc}")

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
        except Exception as exc:
            # One half failing must not cost the other. Before this, a mistake
            # in here stopped the whole check and the update was never
            # reported, so the Twitch results never reached the bar either.
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            youtube = 0
        self.updated.emit(len(rows) + youtube)

    def _settle_streams(self, budget: Budget) -> None:
        """Ask what a freshly published stream actually is.

        The feeds carry no live state at all and the subscriptions sweep only
        reaches the newest entries across a whole list, so an announcement
        arrived looking exactly like an ordinary video for as long as it took
        the sweep to notice it. It is one question per stream and the answer
        is kept, so this only ever runs on what has just appeared.
        """
        rows = self._db.streams_to_settle(NEW_STREAMS_PER_CHECK)
        rows = rows[:budget.allowance(PLAYER, len(rows), background=True).granted]
        for row in rows:
            if self._cancel.is_set():
                return
            budget.spend(PLAYER)
            try:
                state = livecheck.check(self._cfg, row["ext_id"], self._throttle, self._cancel)
            except ProcessCancelled:
                return
            except livecheck.LiveCheckError:
                budget.spend(PLAYER, count=0, refused=1)
                # Left pending. A refusal is not an answer, and asking again
                # in a minute and a half costs one request.
                continue
            if state.upcoming:
                self._db.set_upcoming(row["key"], state.starts_at)
            else:
                self._db.set_live_state(row["key"], state.viewers, state.still_live)
                self._db.settle_stream(row["key"])

    def _check_upcoming(self, budget: Budget) -> None:
        """Learn when an announced stream is actually due.

        The subscriptions sweep reports the time as NA for every one of them,
        so the card could say a stream was announced and never when. It is one
        request per video and the answer never changes, so a few are asked
        each round and that is the end of it. What comes back also says
        whether it is still announced, which is what keeps one that has since
        gone live or been cancelled from being asked about for ever.
        """
        rows = self._db.upcoming_without_start(UPCOMING_PER_CHECK)
        rows = rows[:budget.allowance(PLAYER, len(rows), background=True).granted]
        for row in rows:
            if self._cancel.is_set():
                return
            budget.spend(PLAYER)
            try:
                state = livecheck.check(self._cfg, row["ext_id"], self._throttle, self._cancel)
            except ProcessCancelled:
                return
            except livecheck.LiveCheckError:
                budget.spend(PLAYER, count=0, refused=1)
                continue
            if state.starts_at is not None:
                self._db.set_scheduled_at(row["key"], state.starts_at)
            elif not state.upcoming:
                # It began, or it was called off. Either way it is not an
                # announcement any more, so it stops being asked about.
                self._db.set_live_state(row["key"], state.viewers, state.still_live)

    def _check_youtube(self) -> int:
        """Give the YouTube streams a viewer count so they order against the
        Twitch ones, and drop the ones that have finished."""
        found = 0
        rows = self._db.live_youtube()
        # One call per stream, every ninety seconds, is the busiest thing here
        # after the feeds, so it is held to a ceiling like they are. Trimmed
        # rather than skipped: the ones left out keep their old count for one
        # more cycle instead of the whole bar going stale.
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        rows = rows[:budget.allowance(PLAYER, len(rows), background=True).granted]
        for row in rows:
            if self._cancel.is_set():
                break
            budget.spend(PLAYER)
            try:
                state = livecheck.check(self._cfg, row["ext_id"], self._throttle, self._cancel)
            except ProcessCancelled:
                break
            except livecheck.LiveCheckError:
                budget.spend(PLAYER, count=0, refused=1)
                continue
            self._db.set_live_state(row["key"], state.viewers, state.still_live)
            found += 1 if state.still_live else 0
        # After the streams that are on, since a viewer count going stale is
        # felt and a start time is not. The freshly published ones come first
        # of those two, because until one is settled its card looks like a
        # video that can be played and is not.
        self._settle_streams(budget)
        self._check_upcoming(budget)
        return found

    def _fetch_missing_avatars(self, client: twitch.Client) -> None:
        missing = self._db.channels_missing_avatar("twitch")
        if not missing or self._cancel.is_set():
            return
        for login, display, picture in client.users(missing):
            self._db.add_channel(f"twitch:{login}", "twitch", login, display, picture or None)


class DetailFetcher(Worker):
    """Everything the detail panel needs that is not already stored.

    The dislike count and the comments come from different places and take very
    different amounts of time, so each is reported as it lands rather than the
    panel waiting for both.
    """

    votes = Signal(str, int)              # video key, dislikes
    comments = Signal(str, "QVariantList", "QVariantMap")
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
        self._throttle = self._throttle_for(cfg, 2)

    def work(self) -> None:
        fetcher = Fetcher(self._throttle, cancel=self._cancel)
        try:
            if not self._cancel.is_set():
                self._fetch_votes(fetcher)
            if not self._cancel.is_set():
                self._fetch_comments()
        finally:
            fetcher.close()

    def _fetch_votes(self, fetcher: Fetcher) -> None:
        _spend(self._db, self._cfg, DISLIKES)
        try:
            found = dislike_source.fetch(fetcher, self._ext_id)
        except Exception as exc:
            _spend(self._db, self._cfg, DISLIKES, count=0, refused=1)
            self.failed.emit("dislikes", f"{type(exc).__name__}: {exc}")
            return
        if found.dislikes is not None:
            self._db.set_dislikes(self._key, found.dislikes)
            self.votes.emit(self._key, found.dislikes)

    def _fetch_comments(self) -> None:
        _spend(self._db, self._cfg, PLAYER)
        try:
            threads, details = comment_source.fetch(self._cfg, self._url, self._threads,
                                                    self._throttle, self._cancel)
        except ProcessCancelled:
            return
        except comment_source.CommentsError as exc:
            _spend(self._db, self._cfg, PLAYER, count=0, refused=1)
            self.failed.emit("comments", str(exc))
            return
        # The metadata file the same call writes carries the like count and
        # the publish date, which no cheap listing does. So they come along
        # rather than costing a second request.
        self.comments.emit(self._key, [self._as_map(thread) for thread in threads], {
            "views": details.views, "likes": details.likes,
            "published_at": details.published_at, "duration_s": details.duration_s,
        })

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


class MusicSearch(Worker):
    """Searching YouTube Music, off the interface thread."""

    results = Signal("QVariantList")
    failed = Signal(str)

    def __init__(self, cfg: Config, query: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._query = query

    def work(self) -> None:
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


class MusicHome(Worker):
    """The shelves YouTube Music opens on, which is what fills the music view
    before anything has been searched for."""

    shelves = Signal("QVariantList")
    failed = Signal(str)

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg

    def work(self) -> None:
        from .sources import ytmusic

        try:
            found = ytmusic.home(self._cfg.browser_profile_path)
        except ytmusic.MusicError as exc:
            self.failed.emit(str(exc))
            return
        for shelf in found:
            for item in shelf["items"]:
                item["thumbnail"] = qml_source(item["thumbnail"])
        # What was played recently is the most useful thing to open on.
        for index, shelf in enumerate(found):
            if "listen again" in shelf["title"].lower():
                found.insert(0, found.pop(index))
                break
        found.insert(1 if found else 0, self._own_playlists())
        # Kept, but after the music ones, since those are the real thing now.
        found.append(self._from_youtube())
        self.shelves.emit([shelf for shelf in found if shelf["items"]])

    def _own_playlists(self) -> dict:
        from .sources import ytmusic

        try:
            found = ytmusic.playlists(self._cfg.browser_profile_path, limit=40)
        except ytmusic.MusicError:
            return {"title": "Your playlists", "items": []}
        return {"title": "Your playlists", "items": [{
            "title": entry["title"], "subtitle": (f"{entry['count']} tracks"
                                                  if entry.get("count") else ""),
            "videoId": "", "playlistId": entry["id"],
            "thumbnail": qml_source(entry["thumbnail"]),
        } for entry in found]}

    def _from_youtube(self) -> dict:
        """A shelf of what YouTube itself suggests.

        The music side of the account has never been used, so its own shelves
        are what a new listener sees. This one is built from the account that
        does have a history behind it.
        """
        from .cookies import args as cookie_args

        command = ["yt-dlp", "--no-warnings", "--flat-playlist", "--playlist-end", "24",
                   *cookie_args(self._cfg),
                   "--print", "%(id)s\t%(title)s\t%(channel)s", ":ytrec"]
        try:
            result = run_process(command, timeout=120)
        except Exception:
            return {"title": "From your YouTube", "items": []}

        items = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            # The feed mixes in radio playlist rows, which are not videos.
            if len(parts) < 2 or len(parts[0]) != 11:
                continue
            items.append({
                "title": parts[1], "subtitle": parts[2] if len(parts) > 2 else "",
                "videoId": parts[0], "playlistId": "",
                "thumbnail": qml_source(f"https://i.ytimg.com/vi/{parts[0]}/hqdefault.jpg"),
            })
        return {"title": "From your YouTube", "items": items}


class MusicHistoryReader(Worker):
    """What the music service remembers having listened to.

    A snapshot, like the other lists that come from outside, so it replaces
    the last one. Songs played in Weave itself are written as they play and
    are not touched by this.
    """

    ready = Signal(int)
    failed = Signal(str)

    def __init__(self, db: Database, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg

    def work(self) -> None:
        # Imported here like every other use of it in this file, so a machine
        # without the music library still runs everything else.
        from .sources import ytmusic

        try:
            rows = ytmusic.history(self._cfg.browser_profile_path)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if self.cancelled:
            return
        self._db.replace_service_music_history(rows)
        self.ready.emit(len(rows))


class TrackList(Worker):
    """Tracks for one thing that was chosen. A playlist from YouTube Music, or
    the liked videos from YouTube, which are a different list entirely."""

    tracks = Signal("QVariantList", str)
    failed = Signal(str)

    LIKED = "liked"
    RADIO = "radio"

    def __init__(self, cfg: Config, what: str, playlist_id: str = "",
                 label: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._what = what
        self._playlist_id = playlist_id
        self._label = label

    def work(self) -> None:
        if self._what == self.LIKED:
            self._liked()
        elif self._what == self.RADIO:
            self._radio()
        else:
            self._playlist()

    def _radio(self) -> None:
        """A station built from one song, which is what a recently played tile
        stands for. The song itself comes back first, with things like it after
        it, which is what pressing one in the music application does."""
        from .sources import ytmusic

        try:
            found = ytmusic.radio(self._cfg.browser_profile_path, self._playlist_id)
        except ytmusic.MusicError as exc:
            self.failed.emit(str(exc))
            return
        self.tracks.emit([{
            "key": t.key, "videoId": t.video_id, "title": t.title, "artist": t.artist,
            "album": t.album, "duration": t.duration, "thumbnail": qml_source(t.thumbnail_url),
        } for t in found], self._label)

    def _playlist(self) -> None:
        from .sources import ytmusic

        try:
            found, offered = ytmusic.playlist_tracks(self._cfg.browser_profile_path,
                                                     self._playlist_id)
        except ytmusic.MusicError as exc:
            self.failed.emit(str(exc))
            return
        label = self._label
        if offered and len(found) < offered:
            # Otherwise a playlist of mostly removed videos looks like a
            # failure rather than what it is.
            label = f"{label}, {len(found)} of {offered} still playable"
        self.tracks.emit([{
            "key": t.key, "videoId": t.video_id, "title": t.title, "artist": t.artist,
            "album": t.album, "duration": t.duration, "thumbnail": qml_source(t.thumbnail_url),
        } for t in found], label)

    def _liked(self) -> None:
        """Liked music, which is a playlist like any other."""
        self._playlist_id = "LIKED"
        self._playlist()


class SourceDetails(Worker):
    """A picture and a name for a saved address, so the row is worth looking
    at rather than being a bare string."""

    done = Signal()

    def __init__(self, db: Database, cfg: Config, url: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._url = url

    def work(self) -> None:
        from .cookies import args as cookie_args

        command = ["yt-dlp", "--no-warnings", "--simulate", *cookie_args(self._cfg),
                   "--print", "%(title)s\t%(thumbnail)s", self._url]
        try:
            result = run_process(command, cancel=self._cancel, timeout=120)
        except Exception:
            return
        line = next((row for row in result.stdout.splitlines() if row.strip()), "")
        parts = line.split("\t")
        title = parts[0].strip() if parts and parts[0] != "NA" else None
        picture = parts[1].strip() if len(parts) > 1 and parts[1] != "NA" else None
        self._db.set_source_details(self._url, title, picture)
        self.done.emit()


class ChannelAvatarsFetcher(Worker):
    """Fills in a picture for the channels behind a list of suggestions.

    A suggestion names its channel, but yt-dlp's flat listing of them never
    carries a picture, only a channel's own page does, and that page costs
    about six tenths of a second. Fetched here for a whole batch at once with
    several requests in flight, rather than on the interface thread or as a
    swarm of unrelated workers, and stopped by the same request budget every
    other browse call answers to. A channel that fails is asked about again
    on the next batch that names it, since a permanent memory of the failure
    would need its own bookkeeping and the budget is already the backstop
    against asking too often.
    """

    ready = Signal(int)   # channels that now have a picture

    def __init__(self, db: Database, cfg: Config, channel_keys: list[str],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = cfg
        self._keys = channel_keys
        self._throttle = self._throttle_for(cfg, cfg.max_concurrency)

    def work(self) -> None:
        budget = Budget(self._db, self._cfg.budget_limits, self._cfg.budget_window_s)
        allowance = budget.allowance(BROWSE, len(self._keys), background=True)
        keys = self._keys[:allowance.granted]
        found = spent = refused = 0
        if keys:
            with ThreadPoolExecutor(max_workers=self._cfg.max_concurrency) as pool:
                futures = {pool.submit(channel_source.fetch, key.split(":", 1)[1],
                                       self._throttle, self._cancel): key for key in keys}
                for future in as_completed(futures):
                    if self._cancel.is_set():
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    key = futures[future]
                    try:
                        details = future.result()
                    except (FetchCancelled, ProcessCancelled):
                        break
                    except channel_source.DetailsError:
                        spent += 1
                        refused += 1
                        continue
                    spent += 1
                    self._db.set_channel_details(key, details.title, details.avatar_url,
                                                 details.banner_url, details.follower_count)
                    if details.avatar_url:
                        found += 1
        budget.spend(BROWSE, spent, refused=refused)
        self.ready.emit(found)
