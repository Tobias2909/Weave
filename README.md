<h1><img src="weave/share/weave-128.png" width="40" height="40" align="absmiddle" alt=""> Weave</h1>

[![tests](https://github.com/Tobias2909/Weave/actions/workflows/tests.yml/badge.svg)](https://github.com/Tobias2909/Weave/actions/workflows/tests.yml)
[![release](https://img.shields.io/github/v/release/Tobias2909/Weave)](https://github.com/Tobias2909/Weave/releases/latest)

A personal YouTube and Twitch client for Linux. Weave shows what the channels
you track have posted, sorted into groups you make yourself, and hands playback
to `mpv` instead of embedding a player of its own. Music plays inside the
window, from a bar at the foot of it, and a page of its own shows the song.

Your channels, your groups, your window. Nothing recommends anything in the
feed, nothing autoplays, and there is no endless scroll of things you never
asked for. Everything Weave knows sits in one SQLite file in your own home
directory, and it never writes to your account.

https://github.com/user-attachments/assets/cc89faf0-0ee0-4dc1-bbb0-d89526c3ddd2

## What it does

* A feed built from each channel's own RSS, which needs no login and carries
  exact publish times with exact view and like counts
* Lengths are filled in behind the feed, since RSS carries none, so a library
  read in from a long backlog fills its gaps over the following hours
* One command imports every channel you already subscribe to, names and pictures
  included, and any channel can be tracked without subscribing to it
* **Groups** hold whole channels, **boxes** hold individual videos, both made and
  named by you, both mixing YouTube and Twitch
* A live bar across the top, Twitch and YouTube in one row ordered by how many
  are watching, on its own faster timer
* Left click plays in `mpv`, and Weave watches that `mpv` over its IPC socket to
  learn what was watched, so hide watched means something without a second
  history to keep, and a line under a card shows where you stopped
* Shorts stay out of the feed, because Weave asks each channel for its long form
  tab, and reads the Shorts tab of a channel that has none so its rows are still
  known for what they are
* An announced premiere is badged with when it starts and is refused by the
  player rather than handed over to fail
* Members only videos live in a feed of their own, read by a button on that
  channel's page, badged wherever they appear and never poured into the feed
* Search everything stored as you type, or press enter to search YouTube itself
* What YouTube suggests, the history it keeps and your own playlists, each in its
  own place and never poured into the feed
* A track that is really a whole record has its songs marked on the player bar,
  and the line under the title names the one playing. Hovering names the song
  under the pointer, and a press with the right button lands on the start of one
* A detail panel that follows what `mpv` is playing, with views, likes, an
  estimated dislike count and the top comment threads
* A music area with its own player bar, a queue you can reorder, favourites, the
  listening it remembers, and media keys through MPRIS
* Themes are files, fourteen come with it, and there is an editor with a colour
  wheel that derives a whole palette from two dots
* A channel page in three parts, the videos, the streams it has made and the
  playlists, and a playlist you keep sits in the sidebar under your own
* A report written to one file from the How things are page, holding the checks,
  the versions, the counts and every request of the last day, and no channel
  names, no titles and nothing secret
* Its own window frame, mouse back and forward buttons, and a remembered shape

## What is playing

![The detail panel beside the feed](docs/shots/panel.png)

*Ultraviolet. The panel mirrors `mpv` rather than the grid, so it follows an
`mpv` side track change too. Views and likes are already stored and appear at
once, while the dislike estimate and the comments are fetched only for a video
somebody is actually looking at.*

Closing the panel closes it until the next video starts, and closing `mpv`
closes it as well, since there is then nothing to mirror. A Twitch stream shows
what a stream has instead, who is on, what they are playing, how many are
watching and how long it has been going.

## A channel on its own

![A channel page with its banner](docs/shots/channel.png)

*Sunset Drive. Clicking a channel name opens everything stored from it, watched
ones dimmed rather than hidden, since asking for a channel means asking for all
of it.*

A channel that streams gets a half of its own for the recordings, since the
videos tab and the streams tab are separate lists at the source and past streams
used to appear nowhere. A recording is badged as one wherever it turns up.

## The playlists a channel has made

![A channel's playlists, drawn as stacks of videos](docs/shots/playlists.png)

*Mint Fade. A playlist is drawn as the stack of videos it is. The pictures come
with the listing, so a page of them costs the one request that read the tab
rather than a request each.*

Opening one reads what is in it. Keeping a playlist puts it in a section of
its own in the sidebar, under your own, since it belongs to somebody else.

## Music

![The music area with the player bar](docs/shots/music.png)

*Bloom. The shelves YouTube Music itself opens on, favourites, saved
addresses for a round the clock stream, and a bar that survives switching views.*

A song is a stream at both ends. `yt-dlp` resolves an address and the player
reads it, at the same quality the rest of your setup gets, and Weave holds only
the track playing and the one after it. The next address is resolved as the
current track starts, so a changeover is a millisecond and going back a track
costs nothing.

Favourites are the exception, and they are kept on disk. Your favourites are a
short list you mark yourself and play over and over, and streaming one means
paying for the address and the wait every time. Both halves are kept, the
sound and the picture, written the first time the song is played rather than
fetched ahead of it. There is a ceiling on the settings page, and a song that stops
being a favourite drops what was kept for it.

The page behind the chevron on the bar shows the song itself, the video where
there is one and the artwork where there is not, with the words, the comments
and what is next beside it. Nothing is fetched and nothing decoded for that
page while it is closed.

Starting a video pauses the music, fading out over about a second rather than
cutting off mid note. There is a switch in the bar if you disagree. Repeat has
three settings rather than two, off, the whole queue, and the one track.

## Your playlists

![A playlist, with the count of entries that are gone](docs/shots/playlist.png)

*Linen, one of the four light ones. A playlist keeps the order somebody gave
it, and entries that have gone private are counted at the foot of the list
rather than quietly making it shorter.*

Nothing is read at launch. The menu beside **Playlists** reads the list, which
carries no contents, and opening one reads that playlist. Each playlist can be
hidden on its own and the order is yours. Clicking a video hands `mpv` the whole
playlist starting there. A playlist can also be marked as music, after which a
press on one of its videos goes to the player bar instead.

## Themes

![The settings page with the theme editor](docs/shots/themes.png)

*Frost, another of them. Every theme in the list is a file in the same format
as one you write, and the window repaints as you save it.*

Move two or three dots on the wheel and all sixteen colour roles follow, with
text moved until it clears a contrast ratio. Save it and it lands in
`~/.config/weave/themes` as ordinary TOML, ready to hand to somebody else.

```sh
python -m weave themes
python -m weave themes use Frost
python -m weave themes export Frost
```

## Requirements

Everything here is in the Arch official repositories, and in the package manager
of most other distributions.

| Needed for | Package |
|---|---|
| The application | `python`, `pyside6`, `python-requests`, `python-platformdirs` |
| Playback | `mpv` |
| Adding a channel, and anything beyond RSS | `yt-dlp` and `yt-dlp-ejs`, plus `deno` for the challenges it has to solve. `nodejs` or `bun` also work and Weave names them for yt-dlp, which reaches for `deno` on its own |
| Twitch playback | `streamlink` |
| The music area | `python-ytmusicapi` 1.12.2 or newer |

`yt-dlp-ejs` is the script that answers YouTube's challenge, and it has to live
in the same place as the `yt-dlp` that reads it. Where your distribution does
not package it, `python3 -m pip install --user yt-dlp-ejs` puts it where
`yt-dlp` will look. Without it everything signed in fails while the plain feed
keeps working. `weave doctor` says which pieces are missing, in those words.

## Install

Run it straight from a clone.

```sh
git clone https://github.com/Tobias2909/Weave.git
cd Weave
python -m weave
```

Or install it as a normal program.

```sh
pipx install --system-site-packages "weave[music] @ git+https://github.com/Tobias2909/Weave"
weave-app
```

The music extra pins the library the music area needs, and the system site
packages flag lets the large Qt package come from your distribution rather than
being downloaded again. TeX Live ships a program called weave as well, which is
why this one also installs as `weave-app`.

Weave draws its own window frame, so a panel takes the name and the icon from a
desktop entry. This writes that entry and the icons into your own share tree.

```sh
python -m weave desktop install
```

## Use

Everything is done in the window. The first start opens a few pages that walk
you through it, and the **Getting started** button on the settings page opens
them again whenever you want. **Import subscriptions** sits on that page and
tracks every channel in your subscription list. One at a time goes through the
plus beside **Channels**, which takes a handle, a channel id, a channel address
or a `twitch.tv` address.

The plus beside **Channels** makes a group, the plus beside **Boxes** makes a
box, and either can be renamed, moved or deleted by right clicking its row.
Right click a card for the same sort of menu, which plays it, opens its channel,
marks it watched or puts it in a box. Deleting a group keeps its channels and
deleting a box keeps its videos.

For Twitch, press **Connect Twitch** in the live bar and approve the page it
opens, which already has the code filled in. Every channel you follow is tracked
from that moment.

There is a command behind most of it as well, and it can list itself.

```sh
python -m weave --help
```

## How playback works

A video you press goes to `mpv`. Weave hands it a URL, decodes nothing itself
and reads that instance over its JSON IPC socket to learn what was watched,
either at the end of a file or once 85 percent of it has been seen.

Music is the other half and works the other way. It plays through libmpv inside
Weave's own process, which is what lets the page draw the video of a song in
the window rather than opening a second one somewhere else.

When `mpv-ff2mpv-single.sh` is on your path Weave calls it, because that wrapper
already canonicalizes URLs, resolves Twitch through `streamlink`, expands
playlists and reuses one instance. Without it Weave falls back to plain `mpv`
and everything still works. Nothing is added to your `mpv` configuration, no Lua
script and no config edit. That wrapper comes from the setup Weave was built
beside, at [`Tobias2909/mpv-config`](https://github.com/Tobias2909/mpv-config),
and Weave needs none of it.

## How often it asks

Weave takes a small round every minute rather than a large one every quarter of
an hour, because what the feed endpoint objects to is a burst rather than a day
of requests. Each channel carries its own interval, from a quarter of an hour
for one that posted this week down to once a day for one silent for a year, and
most are not asked on that schedule at all. Every quarter of an hour one call
reads your subscriptions feed, and any channel it names with something new is
asked in the same minute. Underneath sits a ceiling per endpoint, counted in the
database so restarting cannot forget it.

```sh
python -m weave budget
python -m weave schedule
```

## When nothing is arriving

Every way this can fail looks the same from outside, so one place asks each part
whether it is working and prints the answer. It checks the tools, the browser
profile and whether it still holds a login, the database, the schedule, the
picture cache, Twitch, and the feed endpoint itself. Only the last two make a
request. **How things are** in the sidebar is the same list in the window.

```sh
python -m weave doctor
python -m weave doctor --offline
```

## Configuration and where things live

Copy `config.example.toml` to `~/.config/weave/config.toml` and edit it. Every
value in that file is already the default, so an empty config is valid and a
missing one is fine.

| What | Where |
|---|---|
| Config | `~/.config/weave/config.toml` |
| Themes | `~/.config/weave/themes/` |
| Database | `~/.local/state/weave/weave.db` |
| Pictures | `~/.cache/weave/images/` |

Cookies are only needed for the parts that go beyond RSS, and Weave reads them
the way `yt-dlp` does, from a browser profile. Settings lists the Firefox family
profiles found on this machine and says which of them is signed in, so a fork
such as Zen or Floorp can be chosen.

## Tests

The tests are plain `unittest`, so they need nothing installed. The window is
tested too, walked through every view, menu and popup with every request failing
at once, since a clean boot proves almost nothing about an interface.

```sh
python -m unittest discover -s tests -t .
ruff check .
python tools/drive.py smoke --offline
python tools/shots.py --out docs/shots
```

The last one takes the pictures in this file. Every name, title, number and
thumbnail in them is invented, so a picture of the application never carries
anybody's account.

## Not an official anything

Weave is one person's own program, not made by, endorsed by or connected to
YouTube, Google or Twitch in any way.

It reads and never writes to your account, no likes, no subscriptions, no
comments, no playlist edits. Reading a public feed and playing a video outside
their player is the line every external client sits on, and the same line your
`mpv` and `yt-dlp` setup already sits on.

## License

MIT. See [LICENSE](LICENSE).
