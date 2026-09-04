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
* Search across everything stored, as you type, over the local database and
  with no request at all, and a search of YouTube itself on the same box
* What YouTube suggests, in its own view, kept out of the feed
* Your real YouTube playlists, read on request, each one opening as its own
  page in the order somebody put it in
* The history YouTube keeps, which is the whole of it, since mpv tells YouTube
  what it plays
* A live bar across the top showing who is streaming right now, Twitch and
  YouTube together in one row ordered by how many are watching, on its own
  faster timer
* A detail panel beside the feed showing what is playing, with views, likes,
  an estimated dislike count and the top comment threads, resizable and
  remembered
* Themes as files you can write yourself, several built in, some with a
  gradient that washes across the window
* A music area that plays audio inside Weave rather than handing it to `mpv`,
  with search, saved addresses, and a player bar that survives switching views
* A grid of cards in a dark window, sized to the space it has
* A duration badge, view and like counts, the channel icon, and a progress line
  showing where you stopped, read out of the resume files `mpv` already writes
* Shorts filtered out of the feed
* Left click plays the video in `mpv`
* Watched state derived by observing `mpv` over its own IPC socket, either when
  a file reaches the end or once 85 percent of it has been seen
* A hide watched toggle that filters rather than deletes, so nothing is ever lost
* A visible banner whenever a source reports a problem, because a scraper that
  returns nothing looks exactly like a quiet day

Coming in later milestones, roughly in this order. Recommendations, search over
your feed, playlists and history, and a diagnostics page.

The detail panel follows `mpv` rather than the grid, so it shows whatever is on
screen even when `mpv` moved to the next thing by itself. Closing it closes it
until the next video starts, and closing `mpv` closes it too, since there is then
nothing for it to mirror. Views and likes are already stored, so they appear
at once, while the dislike count and the comments are fetched when a video is
actually being looked at, since comments cost several seconds each time. The
dislike count is an estimate published by returnyoutubedislike rather than a
number from YouTube, and it says so.

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
badges rather than the feed itself.

A channel has one feed per tab rather than only the one address, reached by
rewriting the `UC` prefix of its id into the playlist behind that tab. `UULF`
is long form video, `UUSH` is Shorts and `UULV` is streams, and they are
disjoint. Weave asks for the videos feed, so **Shorts never enter the database
at all** and nothing has to classify anything afterwards. It asks for the live
feed as well, but only of channels it has seen streaming, since a stream lives
in its own tab and would otherwise appear only once it had ended.

## How often it asks

Weave takes a small round every minute rather than a large one every quarter of
an hour. What the feed endpoint objects to is a burst, not a day of requests,
and it says so by refusing rather than by asking you to wait, so the same
volume spread evenly is both safer and quicker to come round.

Each channel carries its own interval, worked out from how recently it
published. A channel that posted this week is asked every quarter of an hour, a
channel silent for three months every six hours, and one silent for a year once
a day. Over half of a large subscription list is in that last group, and asking
those as often as the rest is what makes a full lap take hours.

A quarter of an hour is the floor because the feed itself answers with
`Cache-Control: max-age=900`. Asking again sooner returns the same cached body.

None of that would catch a dormant channel posting again quickly, so the
subscriptions sweep does. It is one paginated call covering every subscription,
it runs once a quarter of an hour, and any video in it that Weave has never
seen puts its channel at the front of the queue. So a new video reaches the
grid within one sweep whoever posted it.

Underneath all of it sits a ceiling per endpoint, counted in the database so
that restarting cannot forget it. Freshness alone cannot prevent a flood. With
more channels than one round covers, the ones a round did not reach are still
legitimately due a second later, so six launches in five minutes send six full
rounds and every request in them passes its own freshness check. The ceilings
sit well above what ordinary polling spends, so they bite on a restart loop or
a held down refresh button rather than on normal use.

```sh
python -m weave budget
```

## Playlists

These are YouTube's own, as opposed to boxes, which are this application's. The
two were deliberately never given the same name.

Nothing is read at launch. The menu beside **Playlists** in the sidebar reads
the list, which is one cheap call and carries no contents, and opening one then
reads that playlist. Most playlists are never opened, so paying for them all
up front would be paying for nothing. Contents are kept for six hours, and
**Read it again** in the bar asks straight away.

A long list of playlists would bury everything under it, so the section sits at
the bottom of the sidebar and each playlist can be hidden on its own. Right
click one to put it away, or open **Choose which to show** from the section
menu for a filterable list of all of them. Hiding is not forgetting. A hidden
playlist keeps its contents and comes back the moment it is shown again.

A playlist keeps the order it was given rather than being sorted by date, since
that order is the point of somebody having made it. As with recommendations,
nothing here is written into the feed, because a playlist is full of channels
you may not track at all.

```sh
python -m weave playlists
python -m weave playlists Holidays
```

## Recommendations, kept where they belong

What YouTube suggests lives in its own view and its own table. It is never
written into the feed, because the feed is the channels you chose and keeping
those two apart is most of the point of this. A suggestion from a channel you
already track picks up that channel's name and icon. One from a stranger keeps
the bare name and has no channel page, which is a quiet nothing rather than an
error.

A set is kept for six hours and then asked for again on the next visit, or
straight away with **Ask again** in the bar. Scrolling to the bottom asks for
more, and gets genuinely different ones, since the feed pages. More is added to
the end rather than replacing what is there, so loading it does not send you
back to the top.

A suggestion carries a view count and a duration. It carries no upload date and
no like count, measured, and asking for those would be one request per card, so
they stay empty on the card and arrive in the panel when you open it.

```sh
python -m weave recommended
```

## Searching, twice over

The search box in the bar filters everything stored, by video title and by
channel name, as you type. It is one query over the local database, so it costs
nothing and needs no login. It searches everything rather than only whatever is
on screen, because searching is asking for one particular video and having to
remember which group it was in first would defeat that. Watched videos are
included, for the same reason. Emptying the box goes back to wherever the
search started.

Pressing return searches YouTube itself, for something that was never in your
feed. That costs a request, which is why it happens on a key rather than while
typing. Results are not stored anywhere. One from a channel you already follow
picks up its name and icon, and scrolling to the bottom loads the next page.

```sh
python -m weave search some words
```

## History

This is the history YouTube keeps, which is the whole of it. mpv already tells
YouTube what it plays, so there is nothing to be gained from Weave keeping a
second and poorer list of what it happened to see.

Videos in it that are also stored here are marked watched, since that is what
the hide watched toggle reads, and an existing mark is never overwritten, so
reading the history cannot undo what mpv observed.

One measured limitation. A history entry carries an id, a title, a duration and
a thumbnail, and says nothing at all about the channel. So an entry from a
channel you track picks up its name by being joined to it, and one from
anywhere else simply has no channel name. Asking per video would cost a request
each, which is not worth it for a name.

```sh
python -m weave history
```

## What is on screen while something is loading

Handing a video to mpv takes a few seconds, and so does a search or another
helping of recommendations. A short line appears over the grid saying which of
those is happening, and goes when it is done. It also gives up on its own after
a while, because the thing being waited for can fail to arrive at all and a
line that never leaves is worse than no line.

## Connecting Twitch

Twitch needs an application of your own, which takes a minute and is done once.
At `dev.twitch.tv` create an application, set its **client type to public**, and
copy the client id into `~/.config/weave/config.toml`. The console insists on a
redirect address but the login used here never touches it, so `http://localhost`
is fine.

A client id is public by design and ships inside every browser extension that
talks to Twitch. There is no client secret anywhere in this, and the only
secrets stored are your tokens, which are written to the state directory readable
by nobody but you.

```sh
python -m weave twitch login
python -m weave twitch status
python -m weave live
python -m weave twitch logout
```

The login opens a Twitch page that already has the code filled in, so there is
nothing to type. It is approved once and then remembered, and every channel you
follow is tracked from that moment on, so they show up in the feed and can go
into groups like anything else. There is also a Connect button in the live bar
itself if you would rather not use the terminal.

## Music

Video goes to `mpv` because that is the point of the application. Audio does not,
because a separate window for a song makes no sense, so it plays here instead.

Nothing is downloaded. `yt-dlp` resolves a stream address and Qt plays it, which
reaches the same Premium quality the rest of the setup gets. A live stream has no
audio only form at all, so one of its combined variants is played with the
picture discarded, which is how a round the clock radio stream works here.

Signing in costs nothing extra. The library uses the same browser cookies
everything else does. It opens on the shelves YouTube Music itself opens on,
laid out as pictures to pick from, and search, station radio and playlists all
work. The headphone on any video card plays that video as sound with no window.
Addresses worth returning to can be saved, which is what a round the clock
stream wants, and they keep their own picture.

One thing is worth knowing if your library ever looks like somebody else's. A
Google account can carry more than one YouTube identity, and the cookies alone
do not say which one is in use. The account index does not select it and neither
does the channel id, which is answered with a server error. What selects it is a
numeric page id the web client reads out of the page it was served, so Weave
reads the same page once and sends the same value. Without it, an account whose
music lives on a second identity looks like a brand new listener.

Starting a video in `mpv` pauses the music, since two things playing at once is
never wanted. It fades out over about a second rather than cutting off mid note,
and fades back in when it resumes. There is a switch in the player bar if you
disagree.

Repeat has three settings rather than two, off, the whole queue, and the one
track, since repeating a queue and repeating a song are different wants and one
switch cannot say which.

Sections are arranged by hand with the arrows beside each heading, saved
addresses included, and the arrangement is kept. Pressing a song plays that song
and then things like it, the way the music application does, while pressing a
playlist opens it to look at and starts nothing until something in it is chosen.

The shelves are remembered, so the view has something the moment it opens
rather than a blank page while several requests are gathered. A fresh copy is
fetched behind that, and there is a refresh button for when it is wanted sooner.

## Themes

A theme is a file. It has a name, a set of named colours, and an optional
gradient. The ones that ship with Weave are in exactly the same format as one
you write, so any of them is a working starting point and none of them is
privileged.

```sh
python -m weave themes
python -m weave themes use Ember
python -m weave themes export Ember
```

Exporting copies a theme into `~/.config/weave/themes`, where you can edit it.
The running window repaints as you save, which is the only time anyone is
editing a palette. There is a picker in the toolbar as well.

A file that is wrong in some way still loads. Colours it leaves out keep their
default, colours it invents are reported and ignored, and a value that is not a
colour is reported and skipped rather than handed to the interface where it
would fail quietly at paint time.

The gradient takes an angle and a list of stops. Zero runs straight down the
window and forty five starts at the top left corner, so a corner glow is one
line. Whichever bars sit over a gradient go slightly translucent, otherwise they
would cover the very corner the light comes from.

## Pictures are kept on disk

Thumbnails, channel icons and banners are cached in `~/.cache/weave/images` and
served from there, so going back to a view costs nothing and a restart does not
download the feed again. A thumbnail averages about 17 KB, so a few thousand
videos come to well under a hundred megabytes.

Pictures are kept for a week and the cache has a ceiling, both set in the
config. Whatever has aged out or spilled over is cleared at startup, oldest
first. To look or to clean up by hand.

```sh
python -m weave cache
python -m weave cache --prune
python -m weave cache --clear
```

The retention is ours rather than the server's on purpose. A thumbnail is served
with a lifetime of a few minutes, so anything following that would go back to
the network on nearly every visit for a picture that never changes.

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
| The music area | `python-ytmusicapi` |

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
and a channel can be in as many groups as you like. Selecting one shows only
the videos from the channels in it, and **All** at the top is every channel you
track.

Groups are made in the window. The plus beside **Channels** makes one, right
clicking a group renames it, moves it or deletes it, and either the **Groups**
button on a channel page or the **Groups for this channel** entry in a video's
right click menu files a channel into one. That menu ticks the groups the
channel is already in, so the same entry both files and unfiles.

Deleting a group keeps its channels, exactly as deleting a box keeps its
videos.

The same thing from the command line.

```sh
python -m weave group create Gaming
python -m weave group add Gaming yt:UCabcdefghijklmnopqrstuv twitch:somechannel
python -m weave group list
python -m weave group rename Gaming Games
python -m weave group remove Games twitch:somechannel
python -m weave group delete Games
```

A group collects whole channels. A box collects individual videos. Both show up
in the list down the left and both are managed the same way.

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

A wheel over the grid glides half a card row per notch, which is set by
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
storage rules, the polling schedule, the endpoint budget, resume position
lookup, and cancellation.
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
