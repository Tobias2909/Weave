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
* A grid of cards in a dark window, sized to the space it has
* Left click plays the video in `mpv`
* Watched state derived by observing `mpv` over its own IPC socket, either when
  a file reaches the end or once 70 percent of it has been seen
* A hide watched toggle that filters rather than deletes, so nothing is ever lost
* A visible banner whenever a source reports a problem, because a scraper that
  returns nothing looks exactly like a quiet day

Coming in later milestones, roughly in this order. Channel groups and a
subscriptions import, a live bar for Twitch and YouTube streams, a detail panel
with likes and comments, the theme system, a YouTube Music area that plays audio
inside Weave, search and playlists and history, and a diagnostics page.

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

Inside the window, left click plays a video in `mpv` and right click toggles its
watched mark. The box in the header adds a channel.

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
channel identity, the RSS parser, the watched rule, and display formatting. There
are no interface tests, because they cost more than they find.

## A note on how this talks to YouTube

Weave reads. It never writes to your account. No likes, no subscriptions, no
comments, no playlist edits. Reading a public feed and playing a video outside
their player is the same line every external client sits on, and it is the same
line your `mpv` and `yt-dlp` setup already sits on. Writing would mean
impersonating your browser to change your own account, which is not worth the
risk for a feed reader.

## License

MIT. See [LICENSE](LICENSE).
