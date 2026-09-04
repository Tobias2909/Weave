"""Command line entry point.

Running with no arguments opens the window. The other subcommands exist so the
feed can be filled and inspected without a display, which is also what makes
the poller testable.
"""

from __future__ import annotations

import argparse
import sys
import time

from . import config, ids, imagecache, paths, themes, tokens
from .budget import Budget
from .sources import twitch
from .db import Database
from .net import Throttle
from .sources import history, recommended, subs
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
        print("Twitch channels appear in the live bar, which is not built yet, "
              "so they add no rows to the feed.")
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
    app = QCoreApplication([])                      # noqa: F841  signals need one
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
    """Mark what YouTube already knows you have watched.

    Worth running once, so a first day does not look like several thousand
    unwatched videos. After that mpv is the source of truth and an existing
    mark is never overwritten.
    """
    cfg = config.load()
    db = Database(paths.DB_FILE)
    throttle = Throttle(1, cfg.min_request_interval_s)
    Budget(db, cfg.budget_limits, cfg.budget_window_s).spend("browse")
    try:
        keys = history.fetch(cfg, args.limit, throttle)
    except history.HistoryError as exc:
        print(exc, file=sys.stderr)
        return 1
    marked, missing = db.mark_watched_many(keys, "youtube")
    print(f"{len(keys)} in the history, {marked} newly marked as watched")
    if missing:
        print(f"{missing} were from channels not tracked here, so they were skipped")
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
    db.replace_recommended([{
        "ext_id": item.ext_id, "title": item.title, "channel_name": item.channel_name,
        "channel_ext_id": item.channel_ext_id, "duration_s": item.duration_s,
        "thumbnail_url": item.thumbnail_url,
    } for item in found])
    print(f"{len(found)} suggestions")
    for row in db.recommended(limit=args.limit):
        print(f"  {row['ext_id']}  {(row['channel_title'] or '')[:24]:<24} {row['title'][:52]}")
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
            for member in db.group_members(row["id"]):
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
        db.rename_group(group_id, args.new_name)
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
        db.rename_box(box_id, args.new_name)
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
    if args.clear:
        removed, freed = imagecache.prune(directory, 0)
        print(f"cleared {removed} files, {freed / 1024 / 1024:.1f} MB")
        return 0
    if args.prune:
        aged, freed = imagecache.prune(directory, cfg.image_days * 86400)
        spilled, more = imagecache.enforce_ceiling(directory, cfg.image_max_mb * 1024 * 1024)
        print(f"removed {aged} files older than {cfg.image_days} days and {spilled} "
              f"over the ceiling, {(freed + more) / 1024 / 1024:.1f} MB")
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
        print(f"{len(rows)} recorded failures, most recent {newest}")
        for reason, count in kinds.most_common():
            print(f"  {count:>5}  {reason}")
        print("\nthe last few")
        for when, reason, url in rows[-5:]:
            print(f"  {reason:<24} {url[:70]}")
        return 0

    total = imagecache.size_bytes(directory)
    files = sum(1 for path in directory.rglob("*") if path.is_file()) if directory.exists() else 0
    print(f"image cache at {directory}")
    print(f"  {files} files, {total / 1024 / 1024:.1f} MB of a {cfg.image_max_mb} MB ceiling")
    print(f"  images are kept for {cfg.image_days} days")
    return 0


def _cmd_twitch(args) -> int:
    cfg = config.load()
    client_id = cfg.twitch_client_id

    if args.action == "logout":
        print("logged out" if tokens.clear() else "there was nothing stored")
        return 0

    if not client_id:
        print("no Twitch client id is configured. Register an application at "
              "dev.twitch.tv, set its client type to public, and put the client id "
              "in the config file.", file=sys.stderr)
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


def _cmd_music(args) -> int:
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
    except Exception as exc:                                        # noqa: BLE001
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
        target.write_text(source.source.read_text())
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
    cache.set_defaults(func=_cmd_cache)

    budget = subparsers.add_parser(
        "budget", help="how much each endpoint has been asked recently")
    budget.set_defaults(func=_cmd_budget)

    watched = subparsers.add_parser(
        "history", help="mark what YouTube says you have already watched")
    watched.add_argument("--limit", type=int, default=2000,
                         help="how far back to read, newest first")
    watched.set_defaults(func=_cmd_history)

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

    parser.set_defaults(func=_cmd_gui)
    args = parser.parse_args()
    paths.ensure_dirs()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
