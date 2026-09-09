"""Command line entry point.

Running with no arguments opens the window. The other subcommands exist so the
feed can be filled and inspected without a display, which is also what makes
the poller testable.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time

from . import config, desktop, ids, imagecache, paths, themes, tokens
from . import format as fmt
from .budget import Budget
from .db import Database
from .net import Throttle
from .sources import flatlist, history, recommended, search, subs, twitch
from .sources import playlists as playlist_source
from .sources.resolve import ResolveError, resolve


def _cmd_add(args) -> int:
    cfg = config.load()
    db = Database(paths.DB_FILE)
    throttle = Throttle(1, cfg.min_request_interval_s)
    added = 0
    twitch_added = False
    for text in args.reference:
        ref = ids.parse_channel_ref(text)
        if not ref:
            print(f"could not read {text!r} as a channel. Accepted forms are a UC id, "
                  f"an @handle, a youtube.com channel URL and a twitch.tv link",
                  file=sys.stderr)
            continue
        try:
            result = resolve(ref, throttle=throttle)
        except ResolveError as exc:
            print(f"could not add {text!r}, {exc}", file=sys.stderr)
            continue
        db.add_channel(result.key, result.platform, result.ext_id, result.title)
        label = f" {result.title}" if result.title else ""
        print(f"added {result.key}{label}")
        added += 1
        twitch_added = twitch_added or result.platform == "twitch"

    if twitch_added:
        print("Twitch channels show in the live bar while they stream and add no "
              "rows to the feed.")
    if added:
        print("Run `weave poll` or press Refresh in the window to fetch videos.")
    return 0 if added else 1


def _cmd_remove(args) -> int:
    db = Database(paths.DB_FILE)
    known = {row["key"] for row in db.channels()}
    removed = 0
    for key in args.key:
        if key not in known:
            print(f"not tracked {key!r}", file=sys.stderr)
            continue
        db.remove_channel(key)
        print(f"removed {key}")
        removed += 1
    return 0 if removed else 1


def _cmd_channels(_args) -> int:
    db = Database(paths.DB_FILE)
    rows = db.channels()
    if not rows:
        print("no channels yet")
        return 0
    for row in rows:
        error = f"  error: {row['last_error']}" if row["last_error"] else ""
        print(f"{row['key']:<32} {row['title'] or '(unnamed)'}{error}")
    return 0


def _cmd_poll(_args) -> int:
    """Drives the same poller the window uses, so there is one implementation
    rather than a second simplified one that can drift.

    The window takes a small round a minute; here the rounds run back to back
    until either nothing is due or the endpoint budget says that is enough.
    The budget is the thing doing the protecting either way, so running this
    is never worse for the endpoint than leaving the window open.
    """
    from PySide6.QtCore import QCoreApplication

    from .poller import FeedPoller

    cfg = config.load()
    db = Database(paths.DB_FILE)
    _app = QCoreApplication([])                     # signals need one alive
    poller = FeedPoller(db, cfg, force_all=True)

    seen: dict[str, int] = {}

    def on_progress(phase: str, done: int, total: int) -> None:
        # Only redraw on a terminal. Piped into a log, a carriage return does
        # not overwrite and every tick becomes its own line.
        if sys.stdout.isatty():
            print(f"  {phase} {done} of {total}", end="\r", flush=True)
        elif seen.get(phase) != total:
            print(f"  {phase} of {total}")
        seen[phase] = total

    failures: list[str] = []
    poller.progress.connect(on_progress)
    poller.failure.connect(lambda source, message: failures.append(f"{source}, {message}"))
    poller.run()                                    # deliberately not start()

    budget = Budget(db, cfg.budget_limits, cfg.budget_window_s)
    rounds = 1
    while True:
        due = db.channels_due(cfg.feed_tiers, limit=1)
        if not due:
            break
        if budget.allowance("feeds", 1).empty:
            still = len(db.channels_due(cfg.feed_tiers, limit=100000))
            wait = max(0, budget.allowance("feeds", 1).frees_at - int(time.time()))
            print(f"  stopping, the feed budget is spent. {still} channels still due, "
                  f"room again in about {wait // 60 + 1} min")
            break
        poller = FeedPoller(db, cfg, force_all=False)
        poller.progress.connect(on_progress)
        poller.failure.connect(lambda source, message: failures.append(f"{source}, {message}"))
        poller.run()
        rounds += 1

    print(" " * 40, end="\r")
    for line in failures[:10]:
        print(f"  problem {line}", file=sys.stderr)
    if len(failures) > 10:
        print(f"  and {len(failures) - 10} more problems", file=sys.stderr)
    counts = db.counts()
    print(f"done, {counts['channels']} channels, {counts['videos']} videos, "
          f"{len(failures)} problems")
    return 1 if failures else 0


def _cmd_budget(_args) -> int:
    """What has been asked of each endpoint inside the current window.

    Every scraper failure here looks the same from the outside, exit zero with
    no items, so being able to see that an endpoint was refused rather than
    empty is most of the diagnosis.
    """
    cfg = config.load()
    db = Database(paths.DB_FILE)
    budget = Budget(db, cfg.budget_limits, cfg.budget_window_s)
    rows = budget.report()
    minutes = budget.window_s // 60
    if not rows:
        print(f"nothing asked in the last {minutes} min")
        return 0
    print(f"over the last {minutes} min")
    for endpoint, sent, refused, limit in rows:
        ceiling = str(limit) if limit else "no ceiling"
        note = f", {refused} refused" if refused else ""
        print(f"  {endpoint:9} {sent:5} sent of {ceiling}{note}")
    return 0


def _cmd_history(args) -> int:
    """Read the history YouTube keeps, which is the whole of it.

    mpv tells YouTube when it plays something, so YouTube's copy is complete
    and there is nothing to be gained from a second one here. The stored
    videos in it are marked watched as well, which is what the feed's hide
    watched toggle reads, and an existing mark is never overwritten.
    """
    cfg = config.load()
    db = Database(paths.DB_FILE)
    throttle = Throttle(1, cfg.min_request_interval_s)
    Budget(db, cfg.budget_limits, cfg.budget_window_s).spend("browse")
    try:
        found = history.fetch(cfg, args.limit, throttle)
    except history.HistoryError as exc:
        print(exc, file=sys.stderr)
        return 1
    db.replace_cached(db.HISTORY, [flatlist.as_row(item) for item in found])
    marked, _ = db.mark_watched_many(history.keys_of(found), "youtube")
    print(f"{len(found)} in the history, {marked} of them stored here and marked watched")
    for row in db.cached(db.HISTORY, limit=args.limit)[:20]:
        print(f"  {row['ext_id']}  {(row['channel_title'] or ''):<20} {row['title'][:48]}")
    return 0


def _cmd_search(args) -> int:
    """Search YouTube itself, as opposed to what is stored here."""
    cfg = config.load()
    db = Database(paths.DB_FILE)
    throttle = Throttle(1, cfg.min_request_interval_s)
    Budget(db, cfg.budget_limits, cfg.budget_window_s).spend("browse")
    try:
        found = search.fetch(cfg, " ".join(args.words), 1, args.limit, throttle)
    except search.SearchError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not found:
        print("nothing found")
        return 0
    for item in found:
        print(f"  {item.ext_id}  {(item.channel_name or '')[:22]:<22} {item.title[:48]}")
    return 0


def _cmd_recommended(args) -> int:
    """What YouTube suggests, kept in its own table away from the feed."""
    cfg = config.load()
    db = Database(paths.DB_FILE)
    throttle = Throttle(1, cfg.min_request_interval_s)
    Budget(db, cfg.budget_limits, cfg.budget_window_s).spend("browse")
    try:
        found = recommended.fetch(cfg, args.limit, throttle)
    except recommended.RecommendedError as exc:
        print(exc, file=sys.stderr)
        return 1
    # Through the shared builder, so a field added there reaches here too.
    # Writing the dict out by hand is how the view count went missing.
    db.replace_recommended([flatlist.as_row(item) for item in found])
    print(f"{len(found)} suggestions")
    for row in db.recommended(limit=args.limit):
        print(f"  {row['ext_id']}  {(row['channel_title'] or '')[:24]:<24} {row['title'][:52]}")
    return 0


def _cmd_playlists(args) -> int:
    """Read your playlists, and one playlist's videos when asked for.

    Two calls rather than one, because the list is cheap and the contents are
    not, and most playlists are never opened.
    """
    cfg = config.load()
    db = Database(paths.DB_FILE)
    throttle = Throttle(1, cfg.min_request_interval_s)
    budget = Budget(db, cfg.budget_limits, cfg.budget_window_s)

    if args.name:
        found = next((p for p in db.playlists()
                      if args.name.lower() in p["title"].lower()
                      or args.name == p["ext_id"]), None)
        if found is None:
            print(f"no playlist here matching {args.name!r}, run this without a name first",
                  file=sys.stderr)
            return 1
        budget.spend("browse")
        try:
            items, skipped = playlist_source.fetch_items(cfg, found["ext_id"], args.limit,
                                                          throttle)
        except playlist_source.PlaylistError as exc:
            print(exc, file=sys.stderr)
            return 1
        db.replace_playlist_items(found["ext_id"],
                                  [flatlist.as_row(item) for item in items], skipped)
        print(f"{found['title']}, {len(items)} videos"
              + (f", {skipped} private or deleted skipped" if skipped else ""))
        for row in db.playlist_items(found["ext_id"]):
            print(f"  {row['ext_id']}  {(row['channel_title'] or '')[:22]:<22} {row['title'][:48]}")
        return 0

    budget.spend("browse")
    try:
        found = playlist_source.fetch_list(cfg, throttle=throttle)
    except playlist_source.PlaylistError as exc:
        print(exc, file=sys.stderr)
        return 1
    db.replace_playlists([{"ext_id": item.ext_id, "title": item.title} for item in found])
    print(f"{len(found)} playlists")
    for row in db.playlists():
        seen = f"{row['items']} videos read" if row["items_at"] else "not read yet"
        print(f"  {row['ext_id']:<36} {row['title'][:34]:<34} {seen}")
    return 0


_MARKS = {"ok": "  ok  ", "warn": " warn ", "fail": " FAIL "}


def _cmd_doctor(args) -> int:
    """Ask every part whether it is working.

    Worth its length because a scraper that fails looks exactly like one with
    nothing to say. Exits nonzero when something is actually broken, so it can
    be run from a script.
    """
    from . import doctor

    cfg = config.load()
    db = Database(paths.DB_FILE)
    report = doctor.run(cfg, db, network=not args.offline)
    for check in report.checks:
        print(f"[{_MARKS[check.state]}] {check.name:<22} {check.detail}")
        if check.fix and check.state != doctor.OK:
            print(f"{'':>10}{'':<22} {check.fix}")
    counts = report.counts()
    print(f"\n{counts['ok']} fine, {counts['warn']} worth a look, {counts['fail']} broken")
    return 1 if counts["fail"] else 0


def _cmd_schedule(args) -> int:
    """When each channel was last asked and when it is next due, in the order
    the poller will take them."""
    from . import doctor

    cfg = config.load()
    db = Database(paths.DB_FILE)
    rows = doctor.schedule(db, cfg, limit=args.limit)
    if not rows:
        print("no channels tracked")
        return 0
    # Two columns and not one: the first says how often the channel POSTS,
    # which is what the tier is, and the second how often it is ASKED. They
    # part company whenever the subscriptions sweep is covering the channel,
    # and printing only the first read as an interval nothing kept to.
    print(f"{'channel':<34} {'posts':<16} {'asked':<13} {'why':<18} "
          f"{'last asked':<14} {'next':<10} error")
    for row in rows:
        last = ("never" if not row["last_polled_at"]
                else fmt.age_text(row["last_polled_at"]) or "just now")
        due = "now" if not row["due_in_s"] else fmt.duration_text(row["due_in_s"])
        why = "held by the sweep" if row["covered"] else ""
        print(f"{row['title'][:33]:<34} {row['tier']:<16} "
              f"{fmt.every_text(row['interval_s']):<13} {why:<18} {last:<14} {due:<10} "
              f"{row['error'][:40]}")
    return 0


def _cmd_import(_args) -> int:
    cfg = config.load()
    db = Database(paths.DB_FILE)
    try:
        channels = subs.fetch(cfg, Throttle(1, cfg.min_request_interval_s))
    except subs.ImportError_ as exc:
        print(f"could not import the subscriptions, {exc}", file=sys.stderr)
        return 1
    added = sum(1 for c in channels
                if db.add_channel(c.key, "youtube", c.ext_id, c.title, c.avatar_url))
    print(f"{len(channels)} subscriptions found, {added} newly tracked")
    print("Run `weave poll` or press Refresh in the window to fetch videos.")
    return 0


def _resolve_group(db: Database, name: str) -> int | None:
    if name.isdigit():
        return int(name)
    found = db.group_by_name(name)
    return found["id"] if found else None


def _cmd_group(args) -> int:
    db = Database(paths.DB_FILE)

    if args.action == "list":
        rows = db.groups()
        if not rows:
            print("no groups yet")
            return 0
        for row in rows:
            print(f"{row['id']:>3}  {row['name']:<28} {row['members']} channels, "
                  f"{row['unwatched']} unwatched")
            for member in db.group_channels(row["id"]):
                print(f"       {member['key']:<32} {member['title'] or '(unnamed)'}")
        return 0

    if args.action == "create":
        group_id = db.create_group(args.name)
        print(f"group {args.name} is id {group_id}")
        return 0

    group_id = _resolve_group(db, args.name)
    if group_id is None:
        print(f"no group named {args.name!r}", file=sys.stderr)
        return 1

    if args.action == "rename":
        if not db.rename_group(group_id, args.new_name):
            print(f"a group called {args.new_name!r} already exists", file=sys.stderr)
            return 1
        print(f"group {args.name} is now {args.new_name}")
        return 0

    if args.action == "delete":
        db.delete_group(group_id)
        print(f"deleted group {args.name}")
        return 0

    known = {row["key"] for row in db.channels()}
    changed = 0
    for key in args.channel:
        if key not in known:
            print(f"not a tracked channel {key!r}, add it first", file=sys.stderr)
            continue
        if args.action == "add":
            db.add_to_group(group_id, key)
            print(f"added {key} to {args.name}")
        else:
            db.remove_from_group(group_id, key)
            print(f"removed {key} from {args.name}")
        changed += 1
    return 0 if changed else 1


def _video_key(text: str) -> str | None:
    """Accept a video key, a bare id or any watch URL, so a key never has to be
    typed out by hand."""
    if text.startswith(("yt:", "twitch:")):
        return text
    found = ids.youtube_video_id(text)
    return ids.video_key(found) if found else None


def _cmd_box(args) -> int:
    db = Database(paths.DB_FILE)

    if args.action == "list":
        rows = db.boxes()
        if not rows:
            print("no boxes yet")
            return 0
        for row in rows:
            print(f"{row['id']:>3}  {row['name']:<28} {row['items']} videos")
            for video in db.feed(box_id=row["id"], hide_watched=False, limit=500):
                print(f"       {video['key']:<20} {video['title'][:56]}")
        return 0

    if args.action == "create":
        print(f"box {args.name} is id {db.create_box(args.name)}")
        return 0

    found = db.box_by_name(args.name) if not args.name.isdigit() else {"id": int(args.name)}
    if not found:
        print(f"no box named {args.name!r}", file=sys.stderr)
        return 1
    box_id = found["id"]

    if args.action == "rename":
        if not db.rename_box(box_id, args.new_name):
            print(f"a box called {args.new_name!r} already exists", file=sys.stderr)
            return 1
        print(f"renamed to {args.new_name}")
        return 0

    if args.action == "delete":
        db.delete_box(box_id)
        print(f"deleted box {args.name}")
        return 0

    changed = 0
    for text in args.video:
        key = _video_key(text)
        if not key:
            print(f"could not read {text!r} as a video", file=sys.stderr)
            continue
        if args.action == "add":
            if not db.add_to_box(box_id, key):
                print(f"{key} is not a stored video, so it cannot go in a box. "
                      f"Add its channel and refresh first.", file=sys.stderr)
                continue
            print(f"put {key} in {args.name}")
        else:
            db.remove_from_box(box_id, key)
            print(f"took {key} out of {args.name}")
        changed += 1
    return 0 if changed else 1


def _cmd_cache(args) -> int:
    cfg = config.load()
    directory = paths.IMAGE_CACHE
    # The window writes the chosen ceiling to the database, so reading only the
    # config here would report and enforce a different number than the app.
    db = Database(paths.DB_FILE)
    ceiling_mb = db.image_max_mb(cfg.image_max_mb)
    db.close()
    if args.clear:
        removed, freed = imagecache.prune(directory, 0)
        print(f"cleared {removed} files, {freed / 1024 / 1024:.1f} MB")
        return 0
    if args.prune:
        aged, freed = imagecache.prune(directory, cfg.image_days * 86400)
        spilled, more = imagecache.enforce_ceiling(directory, ceiling_mb * 1024 * 1024)
        print(f"removed {aged} files older than {cfg.image_days} days and {spilled} "
              f"over the ceiling, {(freed + more) / 1024 / 1024:.1f} MB")
        return 0

    if args.forget:
        # The record goes back further than any fix does, so a failure that was
        # dealt with days ago still reads as a hundred failures now. Emptying
        # it also drops the markers, which is what gives every picture in it
        # another try rather than waiting out its window.
        gone = imagecache.forget(directory)
        print(f"forgot {gone[0]} recorded failures and {gone[1]} pictures given up on")
        return 0

    if args.problems:
        rows = imagecache.failures(directory)
        if not rows:
            print("no pictures have failed to load")
            return 0
        import collections
        import datetime

        kinds = collections.Counter(reason for _when, reason, _url in rows)
        newest = datetime.datetime.fromtimestamp(rows[-1][0]).strftime("%Y %m %d %H:%M")
        distinct = imagecache.grouped(rows)
        # The count of pictures first, because it is the number that says how
        # much is wrong. A dead address is asked for again on every visit to
        # the view it sits on, so a handful of them reads as hundreds of
        # failures and looks far worse than it is.
        print(f"{len(distinct)} pictures failed to load, {len(rows)} recorded "
              f"attempts, most recent {newest}")
        for reason, count in kinds.most_common():
            print(f"  {count:>5}  {reason}")
        print("\nthe pictures, most recently seen last")
        for when, reason, url, count in distinct[-10:]:
            seen = datetime.datetime.fromtimestamp(when).strftime("%m %d %H:%M")
            print(f"  {seen}  {reason:<18} x{count:<4} {url[:64]}")
        return 0

    total = imagecache.size_bytes(directory)
    files = sum(1 for path in directory.rglob("*") if path.is_file()) if directory.exists() else 0
    print(f"image cache at {directory}")
    print(f"  {files} files, {total / 1024 / 1024:.1f} MB of a "
          f"{imagecache.ceiling_label(ceiling_mb)} ceiling")
    print(f"  images are kept for {cfg.image_days} days")
    return 0


def _cmd_twitch(args) -> int:
    cfg = config.load()
    client_id = cfg.twitch_client_id

    if args.action == "logout":
        print("logged out" if tokens.clear() else "there was nothing stored")
        return 0

    if not client_id:
        # One is shipped, so an empty value is somebody who cleared it on
        # purpose or a config that overrides it with nothing.
        print("the Twitch client id in the config is empty, so there is nothing "
              "to log in with. Leave it unset to use the one Weave ships, or put "
              "your own application's client id there.", file=sys.stderr)
        return 1

    if args.action == "status":
        stored = tokens.load()
        if stored is None:
            print("not connected. Run `weave twitch login`")
            return 1
        try:
            who = twitch.validate(stored.access_token)
        except twitch.NeedsLogin:
            print("the stored login is no longer valid. Run `weave twitch login`",
                  file=sys.stderr)
            return 1
        print(f"connected as {who.get('login')}, scopes {who.get('scopes')}")
        return 0

    # login
    import webbrowser

    try:
        login = twitch.start_login(client_id)
    except twitch.TwitchError as exc:
        print(f"could not start the login, {exc}", file=sys.stderr)
        return 1

    print(f"open {login.verification_uri}")
    print(f"the code {login.user_code} is already filled in on that page")
    webbrowser.open(login.verification_uri)

    deadline = time.monotonic() + login.expires_in
    while time.monotonic() < deadline:
        time.sleep(login.interval)
        try:
            got = twitch.poll_login(client_id, login.device_code)
        except twitch.AuthPending:
            continue
        except twitch.TwitchError as exc:
            print(f"login failed, {exc}", file=sys.stderr)
            return 1
        tokens.save(got)
        client = twitch.Client(client_id, got, on_tokens=tokens.save)
        db = Database(paths.DB_FILE)
        added = 0
        for follow_login, display in client.follows(client.account_id()):
            if db.add_channel(f"twitch:{follow_login}", "twitch", follow_login, display):
                added += 1
        print(f"connected, {added} followed channels added")
        return 0

    print("the login was not approved in time", file=sys.stderr)
    return 1


def _cmd_live(_args) -> int:
    cfg = config.load()
    db = Database(paths.DB_FILE)
    stored = tokens.load()
    if cfg.twitch_client_id and stored is not None:
        try:
            client = twitch.Client(cfg.twitch_client_id, stored, on_tokens=tokens.save)
            streams = client.followed_streams(client.account_id())
            tracked = {row["ext_id"].lower() for row in db.channels(platform="twitch")}
            missing = sorted(tracked - {stream.login for stream in streams})
            if missing:
                streams.extend(client.streams_for(missing))
            known = {row["key"] for row in db.channels(platform="twitch")}
            db.replace_live("twitch", [{
                "channel_key": s.key, "login": s.login, "display_name": s.display_name,
                "title": s.title, "game": s.game, "viewers": s.viewers,
                "started_at": s.started_at, "thumbnail_url": s.thumbnail_url,
            } for s in streams if s.key in known])
        except twitch.NeedsLogin:
            print("not connected to Twitch. Run `weave twitch login`", file=sys.stderr)
        except twitch.TwitchError as exc:
            print(f"could not check Twitch, {exc}", file=sys.stderr)

    rows = db.live_now()
    if not rows:
        print("nobody is live")
        return 0
    for row in rows:
        viewers = f"{row['viewers']:>7}" if row["viewers"] else "       "
        platform = "twitch " if row["platform"] == "twitch" else "youtube"
        name = (row.get("display_name") or row.get("channel_title") or "")[:22]
        print(f"{platform} {viewers}  {name:<22} {(row.get('title') or '')[:52]}")
    return 0


def _cmd_music(_args) -> int:
    from .sources import ytmusic

    cfg = config.load()
    ytmusic.configure(cfg.music_identity)
    identity = ytmusic.page_id(cfg.browser_profile_path, force=True)
    source = "pinned in the config" if cfg.music_identity not in ("", "auto") else "read from the page"
    print(f"identity {identity or 'none, this account has only one'} ({source})")
    try:
        who = ytmusic.client(cfg.browser_profile_path).get_account_info()
        print(f"speaking as {who.get('accountName')}")
        print(f"{len(ytmusic.playlists(cfg.browser_profile_path, limit=200))} playlists visible")
    except Exception as exc:
        print(f"could not reach YouTube Music, {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("\nIf that is the wrong one, sign in to music.youtube.com as the identity you "
          "want and run this again, or put a number in music_identity in the config.")
    return 0


def _cmd_themes(args) -> int:
    if args.action == "export":
        source = next((t for t in themes.available()
                       if t.name.lower() == args.name.lower() and t.source), None)
        if source is None:
            print(f"no theme named {args.name!r}", file=sys.stderr)
            return 1
        themes.user_dir().mkdir(parents=True, exist_ok=True)
        target = themes.user_dir() / source.source.name
        if target.exists():
            print(f"{target} already exists, so nothing was written", file=sys.stderr)
            return 1
        try:
            target.write_text(source.source.read_text())
        except OSError as exc:
            print(f"could not write {target}, {exc}", file=sys.stderr)
            return 1
        print(f"copied to {target}")
        print("edit it and the running window repaints as you save")
        return 0

    db = Database(paths.DB_FILE)
    if args.action == "use":
        found = next((t for t in themes.available()
                      if t.name.lower() == args.name.lower()), None)
        if found is None:
            print(f"no theme named {args.name!r}", file=sys.stderr)
            return 1
        db.set_state("theme", found.name)
        print(f"using {found.name}")
        print("a window that is already open picks this up within a few seconds")
        return 0

    current = db.get_state("theme", themes.DEFAULT_NAME)
    for theme in themes.available():
        mark = "*" if theme.name == current else " "
        where = "built in" if theme.builtin else str(theme.source)
        if not theme.gradient:
            wash = "flat"
        elif theme.gradient["type"] == "radial":
            wash = (f"glow at {theme.gradient['originX']:.2f}, "
                    f"{theme.gradient['originY']:.2f}")
        else:
            wash = f"gradient at {theme.gradient['angle']:.0f} degrees"
        print(f"{mark} {theme.name:<20} {wash:<28} {where}")
        for problem in theme.problems:
            print(f"    problem {problem}")
    print(f"\nyour own themes go in {themes.user_dir()}")
    return 0


def _cmd_gui(_args) -> int:
    from .app import run
    return run(sys.argv[:1])


def _cmd_desktop(args) -> int:
    """Put Weave in the menu, or take it out again.

    Only your own share tree is touched, so this needs no root and
    a second account is unaffected.
    """
    if args.action == "remove":
        gone = desktop.remove()
        if not gone:
            print("nothing was installed")
            return 1
        for path in gone:
            print(f"removed {path}")
        return 0

    if args.action == "status":
        missing = [path for path in desktop.installed() if not path.exists()]
        if not missing:
            print(f"installed, {len(desktop.installed())} files under {paths.data_home()}")
            return 0
        print(f"not installed, {len(missing)} of {len(desktop.installed())} files missing")
        return 1

    written = desktop.install()
    for path in written:
        print(f"wrote {path}")
    exec_line, work_dir = desktop.launcher()
    print(f"the menu entry runs {exec_line}")
    if work_dir:
        print(f"from {work_dir}, the clone it imports Weave from")
    print("A panel may need a moment, or a logout, to notice a new entry.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="weave", description="A personal YouTube and Twitch client")
    subparsers = parser.add_subparsers(dest="command")

    add = subparsers.add_parser("add", help="track a channel")
    add.add_argument("reference", nargs="+", help="a UC channel id or a twitch.tv link")
    add.set_defaults(func=_cmd_add)

    remove = subparsers.add_parser("remove", help="stop tracking a channel")
    remove.add_argument("key", nargs="+", help="a channel key as shown by `weave channels`")
    remove.set_defaults(func=_cmd_remove)

    subparsers.add_parser("channels", help="list tracked channels").set_defaults(func=_cmd_channels)
    subparsers.add_parser(
        "poll", help="refresh due feeds without a window, until the budget stops it"
    ).set_defaults(func=_cmd_poll)
    subparsers.add_parser("import", help="track every channel you subscribe to").set_defaults(func=_cmd_import)

    twitch_parser = subparsers.add_parser("twitch", help="connect this Twitch account")
    twitch_actions = twitch_parser.add_subparsers(dest="action", required=True)
    twitch_actions.add_parser("login", help="approve Weave in the browser, once")
    twitch_actions.add_parser("status", help="check the stored login")
    twitch_actions.add_parser("logout", help="forget the stored login")
    twitch_parser.set_defaults(func=_cmd_twitch)

    subparsers.add_parser("live", help="show who is live right now").set_defaults(func=_cmd_live)

    music = subparsers.add_parser("music", help="check which YouTube identity is in use")
    music.add_subparsers(dest="action")
    music.set_defaults(func=_cmd_music)

    theme_parser = subparsers.add_parser("themes", help="list, choose or copy a theme")
    theme_actions = theme_parser.add_subparsers(dest="action")
    theme_actions.add_parser("list", help="show what is available")
    theme_use = theme_actions.add_parser("use", help="choose one")
    theme_use.add_argument("name")
    theme_copy = theme_actions.add_parser("export", help="copy one into your config to edit")
    theme_copy.add_argument("name")
    theme_parser.set_defaults(func=_cmd_themes, action="list")

    cache = subparsers.add_parser("cache", help="report or clean the image cache")
    cache.add_argument("--prune", action="store_true", help="drop what is past the retention window")
    cache.add_argument("--clear", action="store_true", help="drop everything")
    cache.add_argument("--problems", action="store_true",
                       help="show pictures that failed to load")
    cache.add_argument("--forget", action="store_true",
                       help="empty the record of pictures that failed, and try them again")
    cache.set_defaults(func=_cmd_cache)

    checkup = subparsers.add_parser(
        "doctor", help="ask every part whether it is working")
    checkup.add_argument("--offline", action="store_true",
                         help="skip the two checks that make a request")
    checkup.set_defaults(func=_cmd_doctor)

    when = subparsers.add_parser(
        "schedule", help="when each channel was last asked and when it is next due")
    when.add_argument("--limit", type=int, default=40)
    when.set_defaults(func=_cmd_schedule)

    budget = subparsers.add_parser(
        "budget", help="how much each endpoint has been asked recently")
    budget.set_defaults(func=_cmd_budget)

    watched = subparsers.add_parser(
        "history", help="mark what YouTube says you have already watched")
    watched.add_argument("--limit", type=int, default=200,
                         help="how far back to read, newest first")
    watched.set_defaults(func=_cmd_history)

    lists = subparsers.add_parser(
        "playlists", help="read your YouTube playlists, or one of them")
    lists.add_argument("name", nargs="?", help="a playlist name or id, to read its videos")
    lists.add_argument("--limit", type=int, default=300)
    lists.set_defaults(func=_cmd_playlists)

    finder = subparsers.add_parser("search", help="search YouTube itself")
    finder.add_argument("words", nargs="+")
    finder.add_argument("--limit", type=int, default=12)
    finder.set_defaults(func=_cmd_search)

    suggested = subparsers.add_parser(
        "recommended", help="refresh what YouTube suggests")
    suggested.add_argument("--limit", type=int, default=48)
    suggested.set_defaults(func=_cmd_recommended)

    group = subparsers.add_parser("group", help="organise channels into groups")
    group_actions = group.add_subparsers(dest="action", required=True)
    group_actions.add_parser("list", help="show groups and their channels")
    created = group_actions.add_parser("create", help="make a new group")
    created.add_argument("name")
    group_renamed = group_actions.add_parser("rename", help="change a group name")
    group_renamed.add_argument("name")
    group_renamed.add_argument("new_name")
    dropped = group_actions.add_parser("delete", help="remove a group, the channels stay")
    dropped.add_argument("name")
    joined = group_actions.add_parser("add", help="put channels in a group")
    joined.add_argument("name")
    joined.add_argument("channel", nargs="+", help="channel keys as shown by `weave channels`")
    left = group_actions.add_parser("remove", help="take channels out of a group")
    left.add_argument("name")
    left.add_argument("channel", nargs="+")
    group.set_defaults(func=_cmd_group)

    box = subparsers.add_parser("box", help="collect individual videos into a named box")
    box_actions = box.add_subparsers(dest="action", required=True)
    box_actions.add_parser("list", help="show boxes and what is in them")
    box_new = box_actions.add_parser("create", help="make a new box")
    box_new.add_argument("name")
    box_renamed = box_actions.add_parser("rename", help="change a box name")
    box_renamed.add_argument("name")
    box_renamed.add_argument("new_name")
    box_gone = box_actions.add_parser("delete", help="remove a box, the videos stay")
    box_gone.add_argument("name")
    box_add = box_actions.add_parser("add", help="put videos in a box")
    box_add.add_argument("name")
    box_add.add_argument("video", nargs="+", help="a video key, a bare id or a watch URL")
    box_take = box_actions.add_parser("remove", help="take videos out of a box")
    box_take.add_argument("name")
    box_take.add_argument("video", nargs="+")
    box.set_defaults(func=_cmd_box)

    menu = subparsers.add_parser(
        "desktop", help="put Weave in the application menu, with its icon")
    menu_actions = menu.add_subparsers(dest="action")
    menu_actions.add_parser("install", help="write the entry and the icons")
    menu_actions.add_parser("remove", help="take them out again")
    menu_actions.add_parser("status", help="report whether they are there")
    menu.set_defaults(func=_cmd_desktop, action="install")

    parser.set_defaults(func=_cmd_gui)
    args = parser.parse_args()
    try:
        paths.ensure_dirs()
        return args.func(args)
    except sqlite3.DatabaseError as exc:
        # Every subcommand opens the database, and a file that is not one, or
        # one that is locked by something that never let go, used to be a
        # traceback. The path is the one thing worth knowing about it.
        print(f"the database at {paths.DB_FILE} could not be opened, {exc}. "
              f"Move it aside to start fresh, or wait for whatever holds it.",
              file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
