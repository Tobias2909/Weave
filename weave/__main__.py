"""Command line entry point.

Running with no arguments opens the window. The other subcommands exist so the
feed can be filled and inspected without a display, which is also what makes
the poller testable.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, ids, imagecache, paths
from .db import Database
from .net import Fetcher, Throttle
from .classify import classify_channel
from .sources import rss, subs, tabs
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
    """Drives the same three phase poller the window uses, so there is one
    implementation rather than a second simplified one that can drift."""
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

    print(" " * 40, end="\r")
    for line in failures[:10]:
        print(f"  problem {line}", file=sys.stderr)
    if len(failures) > 10:
        print(f"  and {len(failures) - 10} more problems", file=sys.stderr)
    counts = db.counts()
    print(f"done, {counts['channels']} channels, {counts['videos']} videos, "
          f"{len(failures)} problems")
    return 1 if failures else 0


def _cmd_classify(args) -> int:
    """Backfill in one go, rather than waiting for the poller to work through
    a few channels per cycle."""
    cfg = config.load()
    db = Database(paths.DB_FILE)
    throttle = Throttle(cfg.max_concurrency, cfg.min_request_interval_s)

    pending = db.channels_needing_classification(0, limit=999999)
    total = len(pending)
    if not total:
        print(f"nothing to do, {db.unclassified_count()} videos are undecided and "
              f"every channel has been asked recently")
        return 0
    print(f"{total} channels to ask, {db.unclassified_count()} videos undecided")

    marked_short = marked_long = failed = 0
    with ThreadPoolExecutor(max_workers=cfg.max_concurrency) as pool:
        futures = {pool.submit(classify_channel, db, row["key"], row["ext_id"], throttle):
                   row["key"] for row in pending}
        for index, future in enumerate(as_completed(futures), start=1):
            try:
                got_short, got_long = future.result()
            except tabs.TabError as exc:
                failed += 1
                if args.verbose:
                    print(f"  {futures[future]} failed, {exc}", file=sys.stderr)
            else:
                marked_short += got_short
                marked_long += got_long
            if sys.stdout.isatty():
                print(f"  {index} of {total} channels", end="\r", flush=True)
    if sys.stdout.isatty():
        print(" " * 40, end="\r")
    print(f"done, {marked_short} Shorts hidden, {marked_long} settled as long form, "
          f"{failed} channels failed")
    print(f"{db.unclassified_count()} videos are still undecided")
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

    total = imagecache.size_bytes(directory)
    files = sum(1 for path in directory.rglob("*") if path.is_file()) if directory.exists() else 0
    print(f"image cache at {directory}")
    print(f"  {files} files, {total / 1024 / 1024:.1f} MB of a {cfg.image_max_mb} MB ceiling")
    print(f"  images are kept for {cfg.image_days} days")
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
    subparsers.add_parser("poll", help="refresh every feed without a window").set_defaults(func=_cmd_poll)
    subparsers.add_parser("import", help="track every channel you subscribe to").set_defaults(func=_cmd_import)

    cache = subparsers.add_parser("cache", help="report or clean the image cache")
    cache.add_argument("--prune", action="store_true", help="drop what is past the retention window")
    cache.add_argument("--clear", action="store_true", help="drop everything")
    cache.set_defaults(func=_cmd_cache)

    classify = subparsers.add_parser(
        "classify", help="ask every channel which of its videos are Shorts")
    classify.add_argument("-v", "--verbose", action="store_true", help="name each failure")
    classify.set_defaults(func=_cmd_classify)

    group = subparsers.add_parser("group", help="organise channels into groups")
    group_actions = group.add_subparsers(dest="action", required=True)
    group_actions.add_parser("list", help="show groups and their channels")
    created = group_actions.add_parser("create", help="make a new group")
    created.add_argument("name")
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
