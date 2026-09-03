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
from .sources import rss


def _cmd_add(args) -> int:
    db = Database(paths.DB_FILE)
    added = 0
    for text in args.reference:
        ref = ids.parse_channel_ref(text)
        if not ref:
            print(f"could not read {text!r}", file=sys.stderr)
            continue
        if ref.kind != "id":
            print(f"{text!r} is a handle and needs resolving, which arrives with "
                  f"the subscriptions import", file=sys.stderr)
            continue
        db.add_channel(ids.channel_key(ref.value, ref.platform), ref.platform, ref.value)
        print(f"added {ref.platform} {ref.value}")
        added += 1
    return 0 if added else 1


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
    cfg = config.load()
    db = Database(paths.DB_FILE)
    fetcher = Fetcher(Throttle(cfg.max_concurrency, cfg.min_request_interval_s))
    touched = failed = 0
    try:
        for row in db.channels(platform="youtube"):
            try:
                result = rss.fetch(fetcher, row["ext_id"])
            except Exception as exc:                               # noqa: BLE001
                failed += 1
                db.mark_polled(row["key"], f"{type(exc).__name__}: {exc}")
                print(f"{row['key']}: FAILED {exc}", file=sys.stderr)
                continue
            count = db.upsert_videos(result.videos)
            touched += count
            if result.channel_title:
                db.add_channel(row["key"], "youtube", row["ext_id"], result.channel_title)
            db.mark_polled(row["key"], None)
            print(f"{result.channel_title or row['key']}: {len(result.videos)} entries, "
                  f"{count} rows touched")
    finally:
        fetcher.close()
    print(f"done, {touched} rows touched, {failed} channels failed")
    return 1 if failed else 0


def _cmd_gui(_args) -> int:
    from .app import run
    return run(sys.argv[:1])


def main() -> int:
    parser = argparse.ArgumentParser(prog="weave", description="A personal YouTube and Twitch client")
    subparsers = parser.add_subparsers(dest="command")

    add = subparsers.add_parser("add", help="track a channel")
    add.add_argument("reference", nargs="+", help="a UC channel id or a twitch.tv link")
    add.set_defaults(func=_cmd_add)

    subparsers.add_parser("channels", help="list tracked channels").set_defaults(func=_cmd_channels)
    subparsers.add_parser("poll", help="refresh every feed without a window").set_defaults(func=_cmd_poll)

    parser.set_defaults(func=_cmd_gui)
    args = parser.parse_args()
    paths.ensure_dirs()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
