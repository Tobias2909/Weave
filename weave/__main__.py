"""Command line entry point.

Running with no arguments opens the window. The other subcommands exist so the
feed can be filled and inspected without a display, which is also what makes
the poller testable.
"""

from __future__ import annotations

import argparse
import sys

from . import config, ids, paths
from .db import Database
from .net import Fetcher, Throttle
from .sources import rss, subs
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
        if seen.get(phase) != total or done == total:
            print(f"  {phase} {done} of {total}", end="\r", flush=True)
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

    parser.set_defaults(func=_cmd_gui)
    args = parser.parse_args()
    paths.ensure_dirs()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
