# Weave

A personal YouTube and Twitch client for Linux. Weave shows the newest videos
from the channels you track, sorted into groups you make yourself, and hands
playback to `mpv` instead of embedding a player of its own.

It is built for one user, which is a design choice rather than an apology. There
is no recommendation engine, no autoplay, no infinite feed. You see the channels
you asked for, in the order they published.

## What works today

This is the first milestone. Working right now

* Tracking YouTube channels by id, by handle or by any channel URL, with their
  videos stored in a local SQLite database
* A feed built from channel RSS, which needs no login and carries exact publish
  times together with exact view and like counts
* A one command import of every channel you subscribe to, names and channel
  icons included
* Channel groups, so the feed can be filtered down to the channels you care
  about at that moment, with an unwatched count beside each group
* Boxes, which are named collections of individual videos you pick yourself.
  Right click any video to put it in one or take it out again, and rename a box
  whenever you like
* A channel page, reached by clicking a channel name, showing its banner, its
  subscriber count and everything stored from it
* A grid of cards in a dark window, sized to the space it has
* A duration badge, view and like counts, the channel icon, and a progress line
  showing where you stopped, read out of the resume files `mpv` already writes
* Shorts filtered out of the feed
* Left click plays the video in `mpv`
* Watched state derived by observing `mpv` over its own IPC socket, either when
  a file reaches the end or once 70 percent of it has been seen
* A hide watched toggle that filters rather than deletes, so nothing is ever lost
* A visible banner whenever a source reports a problem, because a scraper that
  returns nothing looks exactly like a quiet day

Coming in later milestones, roughly in this order. A live bar for Twitch and
YouTube streams, a detail panel with comments, the theme system, a YouTube Music
area that plays audio inside Weave, search and playlists and history, and a
diagnostics page.

A box is not a YouTube playlist. It lives only in your own database, holds
whatever you put in it, and keeps the order you put things in rather than the
order they were published. Real YouTube playlists arrive later and are a
separate thing.

## How the feed is built

Two sources, because neither is enough alone.

Channel RSS carries an exact publish time, exact view counts and exact like
counts, and needs no login at all. It carries no duration and no live flag.

The subscriptions feed carries duration and the live flag but no publish time
whatsoever. So the feed is built from RSS and one sweep of the subscriptions
feed joins the missing columns in by video id.

That split is deliberate. RSS is the part that has to keep working, so when the
login rots or the private endpoints change shape, what you lose is duration
badges and the Shorts filter rather than the feed itself.

Shorts are found without a request wherever possible. A known duration past
three minutes settles it for free, and only videos short enough to actually be
one get a lookup.

## Nothing is thrown away

Video rows are inserted and never pruned. A channel feed publishes only its
newest fifteen entries, so each refresh adds whatever is new and only refreshes
the counts on what is already known. A channel's stored history therefore grows
as it publishes, rather than being replaced by the current window, and watched
marks and box membership survive every later refresh.

## What a refresh costs

Measured on a subscription list of 455 channels. The import takes about two
seconds. A full refresh of every channel takes a little over a minute in the
background while the window stays usable, and it found 6054 videos. The Refresh
button always takes every channel, while the timer only takes the channels
actually due, so the usual case is far smaller than a full sweep.

## How playback works

Weave never decodes a video. It resolves nothing and downloads nothing. It hands
a URL to `mpv` and then reads that instance over its JSON IPC socket to learn
what was watched.

When `mpv-ff2mpv-single.sh` is on your PATH, Weave calls it, because that wrapper
already canonicalizes URLs, resolves Twitch through `streamlink`, expands
playlists and reuses a single instance. Without it Weave falls back to plain
`mpv` and everything still works, minus those extras.

Nothing is added to your `mpv` configuration. No Lua script, no config edit. The
only coupling is a command name and a socket path, both of which you can change
in the config file.

## Requirements

Everything here is available from the Arch official repositories, and from the
package manager of most other distributions.

| Needed for | Package |
|---|---|
| The application | `python`, `pyside6`, `python-requests`, `python-platformdirs` |
| Playback | `mpv` |
| Adding a channel, and YouTube data beyond RSS | `yt-dlp`, plus `deno` or `nodejs` for the JS challenges it has to solve |
| Twitch playback | `streamlink` |
| The music area, later | `python-ytmusicapi` |

## Install

Run it straight from a clone, which is the easiest way to follow along while it
is being built.

```sh
git clone https://github.com/Tobias2909/Weave.git
cd Weave
python -m weave
```

Or install it as a normal program.

```sh
pipx install git+https://github.com/Tobias2909/Weave
weave
```

## Use

Add a channel, then refresh.

Import everything you already subscribe to.

```sh
python -m weave import
```

Or track channels one at a time.

```sh
python -m weave add @somechannel
python -m weave add https://www.youtube.com/@somechannel
python -m weave add UCabcdefghijklmnopqrstuv
python -m weave add https://twitch.tv/somechannel
python -m weave channels
python -m weave remove yt:UCabcdefghijklmnopqrstuv
python -m weave poll
python -m weave
```

Any of those forms works, including a legacy URL of the form
`youtube.com/user/name` or `youtube.com/c/name`. A bare word with no `@` and no
URL around it is rejected on purpose, because it could be a Twitch login or a
YouTube name and guessing would turn a typo into a tracked channel.

Every YouTube channel is looked up as it is added, which takes about half a
second. That catches a mistyped id immediately rather than at the next refresh,
and it fills in the channel name straight away. If the lookup itself fails, from
a missing `yt-dlp` or a dead network, a plain id is still stored and only a
definite missing channel is refused.

Twitch channels are accepted but add no rows to the feed yet. They belong to the
live bar, which is a later milestone.

Sort channels into groups. A group can hold both YouTube and Twitch channels,
and a channel can be in as many groups as you like.

```sh
python -m weave group create Gaming
python -m weave group add Gaming yt:UCabcdefghijklmnopqrstuv twitch:somechannel
python -m weave group list
python -m weave group remove Gaming twitch:somechannel
python -m weave group delete Gaming
```

A group collects whole channels. A box collects individual videos. Both show up
in the list down the left.

Collect individual videos into a box. A box takes a video key, a bare id or any
watch URL.

```sh
python -m weave box create "Watch tonight"
python -m weave box add "Watch tonight" https://www.youtube.com/watch?v=dQw4w9WgXcQ
python -m weave box list
python -m weave box rename "Watch tonight" Later
python -m weave box remove Later yt:dQw4w9WgXcQ
python -m weave box delete Later
```

Inside the window, left click a card to play it in `mpv`, click the channel name
to open that channel's page, and right click for a menu that plays, opens the
channel, toggles the watched mark, and puts the video into or out of any box.

A wheel over the grid moves half a card row per notch, which is set by
`scroll_rows_per_notch` in the config if that feels wrong. A wheel over the list
on the left moves the selection instead of scrolling it, so stepping through the
boxes and back to the whole feed is one gesture. The box in the header adds a channel, the button beside it imports
your subscriptions, and the list down the left filters the feed to one group.

## Configuration

Copy `config.example.toml` to `~/.config/weave/config.toml` and edit it. Every
value in that file is already the default, so an empty config is valid and a
missing config is fine.

Cookies are only needed for the parts that go beyond RSS. Weave reads them the
same way `yt-dlp` does, from a browser profile you point it at. Firefox family
browsers work without anything extra because their cookie database is not
encrypted. Chromium family browsers need the desktop keyring and are untested
here.

## Where your data lives

| What | Where |
|---|---|
| Config | `~/.config/weave/config.toml` |
| Themes | `~/.config/weave/themes/` |
| Database | `~/.local/state/weave/weave.db` |
| Caches | `~/.cache/weave/` |

None of it is in the repository, and none of it is ever sent anywhere.

## Tests

The tests are plain `unittest`, so they need nothing installed.

```sh
python -m unittest discover -s tests -t .
```

They cover the parts where a silent mistake would be expensive. Video and
channel identity, the RSS parser, the watched rule, display formatting, the
storage rules, the Shorts decision, resume position lookup, and cancellation.
There are no interface tests, because they cost more than they find.

## A note on how this talks to YouTube

Weave reads. It never writes to your account. No likes, no subscriptions, no
comments, no playlist edits. Reading a public feed and playing a video outside
their player is the same line every external client sits on, and it is the same
line your `mpv` and `yt-dlp` setup already sits on. Writing would mean
impersonating your browser to change your own account, which is not worth the
risk for a feed reader.

## License

MIT. See [LICENSE](LICENSE).
