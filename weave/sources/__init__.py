"""Data sources.

Each module here talks to one place, parses what came back into plain
dataclasses or dicts, and knows nothing about the interface or the database.
The feed's spine is `rss`; everything that needs a login goes through
`ytdlp`, the one yt-dlp runner, or `ytmusic`. Parsers are kept apart from
their fetch so the tests never touch the network.
"""
