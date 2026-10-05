"""The chat beside a broadcast: Twitch's lines, YouTube's answers, the
emotes of both, and the pace lines are let out at.

The shapes here are the ones read off the live services when this was built,
with every name, id and line made up.
"""

import json
import threading
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication

from weave import chat
from weave.config import Config
from weave.sources import twitchchat, youtubechat

_app = QCoreApplication.instance() or QCoreApplication([])


def privmsg(text, **tags):
    base = {"badge-info": "", "badges": "", "color": "", "display-name": "Someone",
            "emotes": "", "id": "m1", "user-id": "11", "room-id": "99"}
    base.update(tags)
    blob = ";".join(f"{name}={value}" for name, value in base.items())
    return f"@{blob} :someone!someone@someone.tmi.twitch.tv PRIVMSG #alpha :{text}"


class TwitchLines(unittest.TestCase):
    def test_a_line_with_its_name_colour_and_roles(self):
        line = twitchchat.parse_line(privmsg(
            "hello there", **{"display-name": "SomeOne", "color": "#1E90FF",
                              "badges": "moderator/1,subscriber/12,premium/1"}))
        self.assertIsInstance(line, twitchchat.Line)
        self.assertEqual((line.author, line.colour, line.text), ("SomeOne", "#1E90FF",
                                                                 "hello there"))
        self.assertEqual(line.roles, ("mod", "sub"))
        self.assertEqual((line.id, line.user_id), ("m1", "11"))

    def test_the_streamer_comes_first_and_a_founder_is_a_sub(self):
        line = twitchchat.parse_line(privmsg("hi", badges="founder/0,broadcaster/1,vip/1"))
        self.assertEqual(line.roles, ("broadcaster", "VIP", "sub"))

    def test_twitchs_own_emotes_by_place(self):
        line = twitchchat.parse_line(privmsg("Kappa hi Kappa PogChamp",
                                             emotes="25:0-4,9-13/88:15-22"))
        names = [(first, last, emote.name) for first, last, emote in line.emotes]
        self.assertEqual(names, [(0, 4, "Kappa"), (9, 13, "Kappa"), (15, 22, "PogChamp")])
        self.assertTrue(line.emotes[0][2].url.endswith("/emoticons/v2/25/default/dark/2.0"))

    def test_a_place_that_misses_its_name_is_left_out(self):
        line = twitchchat.parse_line(privmsg("hi Kappa", emotes="25:0-4"))
        self.assertEqual(line.emotes, ())

    def test_a_me_line_and_its_emotes(self):
        line = twitchchat.parse_line(privmsg("\x01ACTION waves Kappa\x01", emotes="25:6-10"))
        self.assertTrue(line.action)
        self.assertEqual(line.text, "waves Kappa")
        self.assertEqual([emote.name for _a, _b, emote in line.emotes], ["Kappa"])

    def test_cheered_bits(self):
        line = twitchchat.parse_line(privmsg("Cheer100 nice", bits="100"))
        self.assertEqual(line.bits, 100)

    def test_escaped_tags_read_as_written(self):
        self.assertEqual(twitchchat.parse_tags(r"system-msg=Somebody\ssubscribed\:\stwo\\one"),
                         {"system-msg": "Somebody subscribed; two\\one"})

    def test_a_subscription_with_what_was_said(self):
        raw = ("@badges=subscriber/6;display-name=Someone;id=n1;msg-id=resub;"
               r"system-msg=Someone\ssubscribed\sfor\s6\smonths!;user-id=11 "
               ":tmi.twitch.tv USERNOTICE #alpha :still here")
        notice = twitchchat.parse_line(raw)
        self.assertIsInstance(notice, twitchchat.Notice)
        self.assertEqual((notice.kind, notice.said), ("resub", "Someone subscribed for 6 months!"))
        self.assertEqual(notice.line.text, "still here")

    def test_a_gift_with_nothing_said(self):
        raw = (r"@id=n2;msg-id=subgift;system-msg=Someone\sgifted\sa\ssub!;user-id=11 "
               ":tmi.twitch.tv USERNOTICE #alpha")
        notice = twitchchat.parse_line(raw)
        self.assertEqual(notice.said, "Someone gifted a sub!")
        self.assertIsNone(notice.line)

    def test_what_takes_lines_away(self):
        ban = twitchchat.parse_line("@room-id=99;target-user-id=11 :tmi.twitch.tv CLEARCHAT "
                                    "#alpha :someone")
        self.assertEqual(ban, twitchchat.Cleared("11"))
        everything = twitchchat.parse_line("@room-id=99 :tmi.twitch.tv CLEARCHAT #alpha")
        self.assertEqual(everything, twitchchat.Cleared(""))
        deleted = twitchchat.parse_line("@login=someone;target-msg-id=m1 :tmi.twitch.tv "
                                        "CLEARMSG #alpha :oops")
        self.assertEqual(deleted, twitchchat.Deleted("m1"))

    def test_the_room_says_its_id(self):
        room = twitchchat.parse_line("@emote-only=0;room-id=99;slow=0 :tmi.twitch.tv "
                                     "ROOMSTATE #alpha")
        self.assertEqual(room, twitchchat.Room("99"))

    def test_lines_that_mean_nothing_to_the_chat(self):
        for raw in (":tmi.twitch.tv 001 justinfan1 :Welcome, GLHF!",
                    ":justinfan1!justinfan1@justinfan1.tmi.twitch.tv JOIN #alpha",
                    "@msg-id=slow_on :tmi.twitch.tv NOTICE #alpha :This room is now in slow mode.",
                    privmsg("   ")):
            self.assertIsNone(twitchchat.parse_line(raw), raw)


class TwitchWords(unittest.TestCase):
    def test_own_and_extra_emotes_by_the_whole_word(self):
        own = ((0, 4, twitchchat.Emote("Kappa", "https://own/25")),)
        extra = {"OMEGALUL": twitchchat.Emote("OMEGALUL", "https://7tv/1"),
                 "D": twitchchat.Emote("D", "https://bttv/2")}
        words = twitchchat.words_with_emotes("Kappa OMEGALUL DD D", own, extra)
        self.assertEqual([(word, emote.url if emote else None) for word, emote in words],
                         [("Kappa", "https://own/25"), ("OMEGALUL", "https://7tv/1"),
                          ("DD", None), ("D", "https://bttv/2")])


class TheEmoteServices(unittest.TestCase):
    def test_7tv_global_and_a_channel(self):
        found = twitchchat.EmoteSet()
        twitchchat.seventv(json.dumps({"emotes": [{"id": "a1", "name": "Wave"}]}).encode(), found)
        twitchchat.seventv(json.dumps({"emote_set": {"emotes": [{"id": "b2", "name": "Hop"}]}})
                           .encode(), found)
        self.assertEqual(found.by_name["Wave"].url, "https://cdn.7tv.app/emote/a1/2x.webp")
        self.assertEqual(found.by_name["Hop"].url, "https://cdn.7tv.app/emote/b2/2x.webp")

    def test_bttv_global_and_a_channel(self):
        found = twitchchat.EmoteSet()
        twitchchat.bttv(json.dumps([{"id": "c3", "code": "Cat"}]).encode(), found)
        twitchchat.bttv(json.dumps({"channelEmotes": [{"id": "d4", "code": "Dog"}],
                                    "sharedEmotes": [{"id": "e5", "code": "Elk"}]}).encode(),
                        found)
        self.assertEqual(sorted(found.by_name), ["Cat", "Dog", "Elk"])
        self.assertEqual(found.by_name["Dog"].url, "https://cdn.betterttv.net/emote/d4/2x")

    def test_ffz_takes_the_moving_picture_where_there_is_one(self):
        found = twitchchat.EmoteSet()
        twitchchat.ffz(json.dumps({"sets": {"1": {"emoticons": [
            {"name": "Still", "urls": {"1": "//cdn.ffz/1/1", "2": "//cdn.ffz/1/2"}},
            {"name": "Moves", "urls": {"1": "//cdn.ffz/2/1"},
             "animated": {"1": "https://cdn.ffz/2/a1", "2": "https://cdn.ffz/2/a2"}},
        ]}}}).encode(), found)
        self.assertEqual(found.by_name["Still"].url, "https://cdn.ffz/1/2")
        self.assertEqual(found.by_name["Moves"].url, "https://cdn.ffz/2/a2")

    def test_an_answer_of_the_wrong_shape_adds_nothing(self):
        found = twitchchat.EmoteSet()
        for read in (twitchchat.seventv, twitchchat.bttv, twitchchat.ffz):
            read(b"<html>", found)
            read(b"null", found)
        self.assertEqual(found.by_name, {})


class FakeSocket:
    def __init__(self, lines, closed):
        self.sent = []
        self._lines = list(lines)
        self._closed = closed

    def settimeout(self, _s):
        pass

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _n):
        if self._lines:
            return self._lines.pop(0)
        self._closed.set()
        return b""

    def close(self):
        pass


class ReadingTwitch(unittest.TestCase):
    def test_it_joins_anonymously_answers_pings_and_hands_on_what_it_reads(self):
        cancel = threading.Event()
        heard = []
        closed = threading.Event()
        sock = FakeSocket([b"PING :tmi.twitch.tv\r\n" + privmsg("hi").encode() + b"\r\n"],
                          closed)

        def said(event):
            heard.append(event)

        def connect():
            if closed.is_set():
                cancel.set()
                raise OSError("no more")
            return sock

        twitchchat.read("Alpha", said, cancel, connect=connect)
        sent = b"".join(sock.sent).decode()
        self.assertIn("CAP REQ :twitch.tv/tags twitch.tv/commands", sent)
        self.assertIn("NICK justinfan", sent)
        self.assertIn("JOIN #alpha", sent)
        self.assertIn("PONG :tmi.twitch.tv", sent)
        self.assertEqual([event.text for event in heard], ["hi"])


def yt_text(text, **extra):
    item = {"id": extra.pop("id", "y1"), "timestampUsec": str(extra.pop("posted", 1_000_000_000)),
            "authorName": {"simpleText": "@somebody"},
            "authorExternalChannelId": "UCsomebody",
            "message": {"runs": [{"text": text}]}}
    item.update(extra)
    return {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": item}}}


def yt_answer(*actions, wait=10000, ticket="next"):
    return {"continuationContents": {"liveChatContinuation": {
        "actions": list(actions),
        "continuations": [{"invalidationContinuationData": {"continuation": ticket,
                                                            "timeoutMs": wait}}]}}}


class YouTubeAnswers(unittest.TestCase):
    def test_the_ticket_the_watch_page_starts_with(self):
        answer = {"contents": {"twoColumnWatchNextResults": {"conversationBar": {
            "liveChatRenderer": {"continuations": [
                {"reloadContinuationData": {"continuation": "first"}}]}}}}}
        self.assertEqual(youtubechat.ticket_of(answer), "first")
        with self.assertRaises(youtubechat.NoChat):
            youtubechat.ticket_of({"contents": {}})

    def test_a_line_its_words_and_its_emoji(self):
        action = yt_text("x")
        action["addChatItemAction"]["item"]["liveChatTextMessageRenderer"]["message"] = {
            "runs": [{"text": "so good "},
                     {"emoji": {"emojiId": "\U0001f49a", "shortcuts": [":green_heart:"],
                                "image": {"thumbnails": [{"url": "https://emoji/24.png"},
                                                         {"url": "https://emoji/48.png"}]}}},
                     {"text": " yes"}]}
        batch = youtubechat.parse(yt_answer(action))
        said = batch.events[0]
        self.assertEqual(said.author, "somebody", "the @ of a handle goes")
        self.assertEqual([(word, emoji.url if emoji else None) for word, emoji in said.words],
                         [("so", None), ("good", None), (":green_heart:", "https://emoji/48.png"),
                          ("yes", None)])
        self.assertEqual((batch.ticket, batch.wait_ms), ("next", 10000))

    def test_roles_from_the_badges(self):
        badges = [{"liveChatAuthorBadgeRenderer": {"icon": {"iconType": "MODERATOR"}}},
                  {"liveChatAuthorBadgeRenderer": {"customThumbnail": {"thumbnails": []},
                                                   "tooltip": "Member (5 years)"}},
                  {"liveChatAuthorBadgeRenderer": {"icon": {"iconType": "VERIFIED"}}}]
        said = youtubechat.parse(yt_answer(yt_text("hi", authorBadges=badges))).events[0]
        self.assertEqual(said.roles, ("mod", "member"))

    def test_super_chats_stickers_members_and_gifts(self):
        actions = [
            {"addChatItemAction": {"item": {"liveChatPaidMessageRenderer": {
                "id": "p1", "timestampUsec": "1", "authorName": {"simpleText": "@a"},
                "purchaseAmountText": {"simpleText": "€5.00"},
                "message": {"runs": [{"text": "thanks"}]}}}}},
            {"addChatItemAction": {"item": {"liveChatPaidStickerRenderer": {
                "id": "p2", "timestampUsec": "2", "authorName": {"simpleText": "@b"},
                "purchaseAmountText": {"simpleText": "$2.00"},
                "sticker": {"thumbnails": [{"url": "//sticker/1.png"}]}}}}},
            {"addChatItemAction": {"item": {"liveChatMembershipItemRenderer": {
                "id": "p3", "timestampUsec": "3", "authorName": {"simpleText": "@c"},
                "headerSubtext": {"runs": [{"text": "Welcome to "}, {"text": "Alpha"}]}}}}},
            {"addChatItemAction": {"item": {
                "liveChatSponsorshipsGiftPurchaseAnnouncementRenderer": {
                    "id": "p4", "timestampUsec": "4", "authorExternalChannelId": "UCd",
                    "header": {"liveChatSponsorshipsHeaderRenderer": {
                        "authorName": {"simpleText": "@d"},
                        "primaryText": {"runs": [{"text": "Gifted 5 memberships"}]}}}}}}},
        ]
        events = youtubechat.parse(yt_answer(*actions)).events
        self.assertEqual([(one.kind, one.author, one.amount, one.header) for one in events], [
            ("paid", "a", "€5.00", ""), ("paid", "b", "$2.00", ""),
            ("notice", "c", "", "Welcome to Alpha"), ("notice", "d", "", "Gifted 5 memberships")])
        self.assertEqual(events[1].sticker, "https://sticker/1.png")

    def test_what_is_not_something_said_is_left_out(self):
        actions = [
            {"addChatItemAction": {"item": {"liveChatPlaceholderItemRenderer": {"id": "h1"}}}},
            {"addChatItemAction": {"item": {"liveChatViewerEngagementMessageRenderer": {
                "id": "e1", "message": {"runs": [{"text": "Subscribers-only mode"}]}}}}},
            {"addLiveChatTickerItemAction": {"item": {}}},
        ]
        self.assertEqual(youtubechat.parse(yt_answer(*actions)).events, ())

    def test_lines_taken_down_and_a_placeholder_filled(self):
        replaced = {"replaceChatItemAction": {"targetItemId": "h1", "replacementItem":
                    yt_text("filled in", id="h1")["addChatItemAction"]["item"]}}
        events = youtubechat.parse(yt_answer(
            {"markChatItemAsDeletedAction": {"targetItemId": "y1"}},
            {"removeChatItemByAuthorAction": {"externalChannelId": "UCbad"}},
            replaced)).events
        self.assertEqual(events[0], youtubechat.Removed(id="y1"))
        self.assertEqual(events[1], youtubechat.Removed(channel_id="UCbad"))
        self.assertEqual(events[2].words, (("filled", None), ("in", None)))

    def test_an_end_and_a_strange_wait(self):
        with self.assertRaises(youtubechat.NoChat):
            youtubechat.parse({"responseContext": {}})
        with self.assertRaises(youtubechat.NoChat):
            youtubechat.parse({"continuationContents": {"liveChatContinuation": {
                "actions": []}}})
        self.assertEqual(youtubechat.parse(yt_answer(wait=10)).wait_ms,
                         youtubechat.SHORTEST_WAIT_MS)
        self.assertEqual(youtubechat.parse(yt_answer(wait=10**9)).wait_ms,
                         youtubechat.LONGEST_WAIT_MS)


def replayed(at_ms, *actions):
    return {"replayChatItemAction": {"actions": list(actions),
                                     "videoOffsetTimeMsec": str(at_ms)}}


def replay_answer(*actions, ticket="more"):
    following = [{"playerSeekContinuationData": {"continuation": "seek"}}]
    if ticket:
        following.insert(0, {"liveChatReplayContinuationData": {
            "continuation": ticket, "timeUntilLastMessageMsec": 5000}})
    return {"continuationContents": {"liveChatContinuation": {
        "actions": list(actions), "continuations": following}}}


class ReplayAnswers(unittest.TestCase):
    def test_each_line_with_the_moment_of_the_video_it_was_written_at(self):
        engagement = {"addChatItemAction": {"item": {
            "liveChatViewerEngagementMessageRenderer": {"id": "e1"}}}}
        batch = youtubechat.parse_replay(replay_answer(
            replayed(0, engagement), replayed(80227, yt_text("hi", id="a")),
            replayed(81500, yt_text("yo", id="b"),
                     {"markChatItemAsDeletedAction": {"targetItemId": "a"}})))
        self.assertEqual([(at, getattr(one, "id", "")) for at, one in batch.events],
                         [(80227, "a"), (81500, "b"), (81500, "a")])
        self.assertIsInstance(batch.events[2][1], youtubechat.Removed)
        self.assertEqual(batch.ticket, "more", "the replay's own ticket, not the seek one")

    def test_the_end_and_a_video_with_none(self):
        self.assertEqual(youtubechat.parse_replay(replay_answer(ticket="")),
                         youtubechat.ReplayBatch((), ""))
        with self.assertRaises(youtubechat.NoChat):
            youtubechat.parse_replay({"responseContext": {}})

    def test_it_is_asked_from_a_moment_of_the_video(self):
        fetcher = mock.Mock()
        fetcher.post_json.return_value = replay_answer()
        youtubechat.ask_replay(fetcher, "ticket", "2.0", 61500)
        url, body = fetcher.post_json.call_args.args
        self.assertEqual(url, youtubechat.REPLAY)
        self.assertEqual((body["continuation"], body["currentPlayerState"]),
                         ("ticket", {"playerOffsetMs": "61500"}))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _Room(unittest.TestCase):
    def setUp(self):
        self.room = chat.ChatRoom(Config(raw={}))
        self.clock = Clock()
        patcher = mock.patch.object(chat.time, "monotonic", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.asked = []
        self.room._want_emote = lambda url: (self.asked.append(url),
                                             self.room._emotes.setdefault(url, None))
        self.addCleanup(self.room.shutdown)

    def shown(self):
        return [row["key"] for row in self.room.model.rows]

    def tick(self):
        self.room._release()


class TheRoomOnTwitch(_Room):
    def setUp(self):
        super().setUp()
        with mock.patch.object(chat.ChatRoom, "_start_reader"):
            self.room.follow({"key": "twitch:alpha", "login": "alpha", "live": True})

    def say(self, key, who="11", text="hi", **tags):
        self.room._take(twitchchat.parse_line(privmsg(text, id=key, **{"user-id": who},
                                                      **tags)))

    def test_a_line_is_shown_as_it_comes(self):
        self.assertTrue(self.room.available)
        self.say("a")
        self.tick()
        self.assertEqual(self.shown(), ["a"])
        row = self.room.model.rows[0]
        self.assertEqual(row["pieces"], [{"text": "hi"}])
        self.assertEqual(row["colour"], chat.colour_for("Someone"), "no colour of its own")

    def test_a_line_waits_a_moment_for_its_emote_and_no_longer(self):
        self.say("a", text="Kappa", emotes="25:0-4")
        self.tick()
        self.assertEqual(self.shown(), [], "waiting for the picture")
        url = self.asked[0]
        self.clock.now += chat.EMOTE_WAIT_S + 0.1
        self.tick()
        self.assertEqual(self.shown(), ["a"])
        piece = self.room.model.rows[0]["pieces"][0]
        self.assertEqual(piece["picture"], url, "from the network, since it never came")

    def test_an_emote_on_disk_is_drawn_from_there(self):
        self.say("a", text="Kappa", emotes="25:0-4")
        self.room._on_emote(self.asked[0], "file:///cache/kappa.gif", True, 1.0)
        self.tick()
        piece = self.room.model.rows[0]["pieces"][0]
        self.assertEqual((piece["picture"], piece["moves"]), ("file:///cache/kappa.gif", True))

    def test_the_extra_emotes_of_the_channel(self):
        self.room._sets["99"] = {"OMEGALUL": "https://7tv/1"}
        self.room._on_room("99")
        self.say("a", text="OMEGALUL")
        self.assertEqual(self.asked, ["https://7tv/1"])

    def test_a_ban_takes_that_persons_lines_away(self):
        self.say("a", who="11")
        self.say("b", who="22")
        self.tick()
        self.say("c", who="11")
        self.room._take(twitchchat.Cleared("11"))
        self.tick()
        self.assertEqual(self.shown(), ["b"])

    def test_a_deleted_line_and_the_whole_chat_cleared(self):
        for key in "abc":
            self.say(key)
        self.tick()
        self.room._take(twitchchat.Deleted("b"))
        self.assertEqual(self.shown(), ["a", "c"])
        self.room._take(twitchchat.Cleared(""))
        self.assertEqual(self.shown(), [])

    def test_cheers_and_subscriptions(self):
        self.say("a", text="Cheer100 nice", bits="100")
        raw = (r"@id=n1;msg-id=subgift;system-msg=Someone\sgifted\sa\ssub!;user-id=11 "
               ":tmi.twitch.tv USERNOTICE #alpha")
        self.room._take(twitchchat.parse_line(raw))
        self.tick()
        cheer, notice = self.room.model.rows
        self.assertEqual((cheer["kind"], cheer["amount"]), ("cheer", "100 bits"))
        self.assertEqual((notice["kind"], notice["header"]), ("notice", "Someone gifted a sub!"))

    def test_the_last_five_hundred_are_kept_and_more_while_scrolled_up(self):
        for number in range(chat.KEEP + 20):
            self.say(f"m{number}")
        self.tick()
        self.assertEqual(self.room.model.count, chat.KEEP)
        self.assertEqual(self.shown()[0], "m20")
        self.room.setHeld(True)
        for number in range(30):
            self.say(f"n{number}")
        self.tick()
        self.assertEqual(self.room.model.count, chat.KEEP + 30, "nothing taken from under")
        self.assertEqual(self.room.unseen, 30)
        self.room.setHeld(False)
        self.assertEqual(self.room.model.count, chat.KEEP)
        self.assertEqual(self.room.unseen, 0)

    def test_another_video_starts_an_empty_chat(self):
        self.say("a")
        self.tick()
        with mock.patch.object(chat.ChatRoom, "_start_reader"):
            self.room.follow({"key": "yt:abcdefghijk", "title": "x", "live": False})
        self.assertFalse(self.room.available)
        self.assertEqual(self.shown(), [])


class TheRoomOnYouTube(_Room):
    def setUp(self):
        super().setUp()
        with mock.patch.object(chat.ChatRoom, "_start_reader"):
            self.room.follow({"key": "yt:abcdefghijk", "live": True})

    def said(self, key, posted_s, who="UCa"):
        return youtubechat.Said(key, who, "someone", (), (("hi", None),), int(posted_s * 1e6))

    def test_what_was_said_before_comes_at_once(self):
        wall = 5000.0
        self.room._take(("youtube", wall, self.clock.now,
                         (self.said("a", wall - 200), self.said("b", wall - 100)), True))
        self.tick()
        self.assertEqual(self.shown(), ["a", "b"])

    def test_later_lines_come_out_at_the_pace_they_were_written(self):
        """Each answer carries the last ten seconds or so of the chat at once.
        Held behind their posting by the longest any of them took, they come
        out one by one at the moments they were written, the slowest at once."""
        wall = 5000.0
        self.room._take(("youtube", wall, self.clock.now, (), True))
        start = self.clock.now
        self.room._take(("youtube", wall, start,
                         (self.said("a", wall - 9), self.said("b", wall - 5),
                          self.said("c", wall - 1)), False))
        seen = {}
        for step in range(120):
            self.clock.now = start + step * 0.1
            self.tick()
            for key in self.shown():
                seen.setdefault(key, round(self.clock.now - start, 1))
        self.assertEqual(seen, {"a": 0.0, "b": 4.0, "c": 8.0})

    def test_a_line_taken_down_before_or_after_it_shows(self):
        wall = 5000.0
        self.room._take(("youtube", wall, self.clock.now,
                         (self.said("a", wall - 1), self.said("b", wall - 1, who="UCbad")), True))
        self.tick()
        self.room._take(("youtube", wall, self.clock.now,
                         (self.said("c", wall - 1), youtubechat.Removed(id="a"),
                          youtubechat.Removed(channel_id="UCbad")), False))
        self.clock.now += 5
        self.tick()
        self.assertEqual(self.shown(), ["c"])

    def test_the_end_is_said(self):
        self.room._take(("ended", "the chat has ended"))
        self.assertEqual(self.room.status, "This broadcast has no chat")


class FakeReplayReader(chat._ReplayReader):
    """Records what the room asks for, and is never started."""

    def __init__(self, room):
        super().__init__(None, Config(raw={}), "abcdefghijk", room._inbox, room)
        self.wanted = []

    def want(self, round_, at_ms, ticket=""):
        self.wanted.append((round_, at_ms, ticket))


class TheReplay(_Room):
    """A past broadcast's chat, let out at the moments of the video."""

    def setUp(self):
        super().setUp()
        self.reader = FakeReplayReader(self.room)

        with mock.patch.object(chat.ChatRoom, "_start_reader", side_effect=self.start):
            self.room.setPosition(60.0)
            self.room.follow({"key": "yt:abcdefghijk", "live": False, "chat_replay": True})
            self.room.setShown(True)

    def start(self):
        self.room._reader = self.reader
        self.room._begin_replay()

    def away_and_back(self, *positions):
        """The chat off screen while the video plays on through these
        moments, a few seconds apart as playing gives them, then back."""
        self.room.setShown(False)
        for seconds in positions:
            self.room.setPosition(seconds)
            self.room._release(self.room._position)
        self.reader = FakeReplayReader(self.room)
        with mock.patch.object(chat.ChatRoom, "_start_reader", side_effect=self.start):
            self.room.setShown(True)

    def said(self, key):
        return youtubechat.Said(key, "UCa", "someone", (), (("hi", None),), 0)

    def answer(self, *lines, ticket="more", round_=None):
        events = tuple((int(at * 1000), self.said(key)) for key, at in lines)
        self.room._take(("replay", self.room._round if round_ is None else round_,
                         youtubechat.ReplayBatch(events, ticket)))

    def play_to(self, seconds):
        self.room.setPosition(seconds)
        self.room._release(self.room._position)

    def test_it_opens_on_the_chat_until_the_queue_is_picked(self):
        self.assertTrue(self.room.available)
        self.assertEqual(self.room.platform, "replay")
        self.assertEqual(self.room.column, "chat")

    def test_it_asks_from_a_little_before_the_video_once_a_seek_has_settled(self):
        self.room._ask_replay()
        self.assertEqual(self.reader.wanted, [], "a seek may still be under way")
        self.clock.now += chat.REPLAY_SETTLE_S + 0.1
        self.room._ask_replay()
        self.room._ask_replay()
        self.assertEqual(self.reader.wanted,
                         [(self.room._round, int((60 - chat.REPLAY_HISTORY_S) * 1000), "")],
                         "once, until the answer comes")

    def test_lines_come_when_the_video_reaches_them(self):
        self.answer(("a", 55.0), ("b", 61.0), ("c", 70.0))
        self.room._release(self.room._position)
        self.assertEqual(self.shown(), ["a"], "what was said just before, at once")
        self.play_to(61.5)
        self.assertEqual(self.shown(), ["a", "b"])
        self.play_to(65.0)
        self.assertEqual(self.shown(), ["a", "b"], "paused or slow, the chat waits with it")

    def test_more_is_asked_for_as_the_video_nears_the_end_of_what_came(self):
        self.clock.now += 1
        self.answer(("a", 55.0), ("b", 80.0), ticket="t2")
        self.room._ask_replay()
        self.assertEqual(self.reader.wanted, [], "twenty seconds ahead is enough")
        self.play_to(66.0)
        self.room._ask_replay()
        self.assertEqual(self.reader.wanted, [(self.room._round, 80000, "t2")])

    def test_a_seek_starts_it_again_there_and_an_answer_for_before_is_dropped(self):
        self.answer(("a", 55.0))
        self.room._release(self.room._position)
        was = self.room._round
        self.room.setHeld(True)
        self.room.setPosition(600.0)
        self.assertEqual((self.shown(), self.room._round, self.room.held), ([], was + 1, False))
        self.answer(("old", 61.0), round_=was)
        self.play_to(601.0)
        self.assertEqual(self.shown(), [])
        self.clock.now += 1
        self.room._ask_replay()
        self.assertEqual(self.reader.wanted[-1][1], int((600 - chat.REPLAY_HISTORY_S) * 1000))

    def test_back_on_screen_it_keeps_what_came_and_reads_on(self):
        self.clock.now += 1
        self.answer(("a", 55.0), ("b", 61.0), ticket="t2")
        self.play_to(62.0)
        was = self.room._round
        self.away_and_back(64.0, 66.0)
        self.assertEqual(self.shown(), ["a", "b"], "nothing read again, nothing lost")
        self.assertEqual(self.room._round, was + 1, "an answer to the reader let go is dropped")
        self.room._ask_replay()
        self.assertEqual(self.reader.wanted, [(was + 1, 61000, "t2")])

    def test_far_past_what_was_read_it_reads_on_from_a_little_before_the_video(self):
        self.clock.now += 1
        self.answer(("a", 55.0), ("b", 61.0), ticket="t2")
        self.play_to(62.0)
        self.away_and_back(*range(65, 201, 5))
        self.assertEqual(self.shown(), ["a", "b"])
        self.room._ask_replay()
        self.assertEqual(self.reader.wanted,
                         [(self.room._round, int((200 - chat.REPLAY_HISTORY_S) * 1000), "")])

    def test_a_seek_while_it_is_away_starts_it_afresh_there(self):
        self.clock.now += 1
        self.answer(("a", 55.0), ("b", 61.0), ticket="t2")
        self.play_to(62.0)
        self.away_and_back(600.0)
        self.assertEqual(self.shown(), [])
        self.clock.now += 1
        self.room._ask_replay()
        self.assertEqual(self.reader.wanted,
                         [(self.room._round, int((600 - chat.REPLAY_HISTORY_S) * 1000), "")])

    def test_the_end_of_the_replay_asks_no_more(self):
        self.clock.now += 1
        self.answer(("a", 61.0), ticket="")
        self.play_to(100.0)
        self.room._ask_replay()
        self.assertEqual(self.reader.wanted, [])

    def test_the_queue_picked_on_one_is_where_the_next_opens(self):
        from tests.support import scratch_db

        db = scratch_db(self)
        room = chat.ChatRoom(Config(raw={}), db)
        self.addCleanup(room.shutdown)
        with mock.patch.object(chat.ChatRoom, "_start_reader"):
            room.follow({"key": "yt:abcdefghijk", "live": False, "chat_replay": True})
            room.setColumn("queue")
            again = chat.ChatRoom(Config(raw={}), db)
            self.addCleanup(again.shutdown)
            again.follow({"key": "yt:bbcdefghijk", "live": False, "chat_replay": True})
            self.assertEqual(again.column, "queue")
            again.follow({"key": "twitch:a", "login": "a", "live": True})
            self.assertEqual(again.column, "chat", "a broadcast on air always opens on its chat")


class WhereItShows(unittest.TestCase):
    def make(self, db=None):
        room = chat.ChatRoom(Config(raw={}), db)
        self.addCleanup(room.shutdown)
        return room

    def test_a_broadcast_opens_on_its_chat_and_a_video_on_its_queue(self):
        room = self.make()
        with mock.patch.object(chat.ChatRoom, "_start_reader"):
            room.follow({"key": "twitch:a", "login": "a", "live": True})
            self.assertEqual(room.column, "chat")
            room.setColumn("queue")
            self.assertEqual(room.column, "queue")
            room.follow({"key": "yt:abcdefghijk", "live": False})
        self.assertEqual(room.column, "queue")

    def test_it_is_only_read_while_it_is_on_screen(self):
        room = self.make()
        with mock.patch.object(chat.ChatRoom, "_start_reader") as start, \
                mock.patch.object(chat.ChatRoom, "_stop_reader") as stop:
            room.follow({"key": "twitch:a", "login": "a", "live": True})
            start.assert_not_called()
            room.setShown(True)
            start.assert_called_once()
            room._reader = object()
            room.setShown(False)
            stop.assert_called()

    def test_the_three_ways_over_a_filled_screen_cycle_and_are_kept(self):
        from tests.support import scratch_db

        db = scratch_db(self)
        room = self.make(db)
        self.assertEqual(room.fullMode, "full")
        room.cycleFullMode()
        self.assertEqual(room.fullMode, "beside")
        room.cycleFullMode()
        self.assertEqual(room.fullMode, "over")
        room.cycleFullMode()
        self.assertEqual(room.fullMode, "full")
        room.setFullMode("over")
        self.assertEqual(self.make(db).fullMode, "over")

    def test_the_panel_is_kept_where_it_was_left_and_inside_the_screen(self):
        from tests.support import scratch_db

        db = scratch_db(self)
        room = self.make(db)
        self.assertEqual(room.overBox, list(chat.OVER_DEFAULT))
        room.setOverBox(0.5, 0.1, 0.3, 0.4)
        self.assertEqual([round(one, 4) for one in self.make(db).overBox], [0.5, 0.1, 0.3, 0.4])
        room.setOverBox(0.95, -0.2, 0.01, 2.0)
        x, y, width, height = room.overBox
        self.assertEqual((y, height), (0.0, 1.0))
        self.assertEqual(width, chat.SMALLEST_OVER[0])
        self.assertAlmostEqual(x, 1.0 - width)

    def test_a_right_click_locks_the_panel_and_it_stays_locked(self):
        from tests.support import scratch_db

        db = scratch_db(self)
        room = self.make(db)
        self.assertFalse(room.overLocked)
        room.toggleOverLocked()
        self.assertTrue(room.overLocked)
        self.assertTrue(self.make(db).overLocked, "kept between runs")
        room.toggleOverLocked()
        self.assertFalse(self.make(db).overLocked)

    def test_the_wheel_sets_the_backdrop_in_tenths_and_it_is_kept(self):
        from tests.support import scratch_db

        db = scratch_db(self)
        room = self.make(db)
        self.assertEqual(room.overBackdrop, chat.BACKDROP_DEFAULT)
        room.stepOverBackdrop(1)
        self.assertEqual(room.overBackdrop, 0.7)
        room.stepOverBackdrop(-3)
        self.assertEqual(room.overBackdrop, 0.4)
        self.assertEqual(self.make(db).overBackdrop, 0.4, "kept between runs")

    def test_the_backdrop_stops_at_none_and_at_all(self):
        room = self.make()
        room.stepOverBackdrop(20)
        self.assertEqual(room.overBackdrop, 1.0)
        room.stepOverBackdrop(-25)
        self.assertEqual(room.overBackdrop, 0.0)
        for _ in range(7):
            room.stepOverBackdrop(1)
        self.assertEqual(room.overBackdrop, 0.7, "tenths, not a float walking off")

    def test_a_stored_backdrop_that_is_not_a_number_is_the_default(self):
        from tests.support import scratch_db

        db = scratch_db(self)
        db.set_state(chat.BACKDROP_STATE, "dark")
        self.assertEqual(self.make(db).overBackdrop, chat.BACKDROP_DEFAULT)


class Colours(unittest.TestCase):
    def test_the_same_name_the_same_colour(self):
        self.assertEqual(chat.colour_for("Someone"), chat.colour_for("someone"))
        self.assertIn(chat.colour_for("Someone"), chat.PALETTE)

    def test_which_videos_have_a_chat(self):
        self.assertEqual(chat.chat_kind({"key": "twitch:a", "login": "a", "live": True}),
                         "twitch")
        self.assertEqual(chat.chat_kind({"key": "yt:a", "live": True}), "youtube")
        self.assertEqual(chat.chat_kind({"key": "yt:a", "live": False}), "")
        self.assertEqual(chat.chat_kind({"key": "yt:a", "live": False, "chat_replay": True}),
                         "replay")
        self.assertEqual(chat.chat_kind({}), "")


class TheModel(unittest.TestCase):
    def test_taking_out_runs_keeps_the_rest_in_order(self):
        model = chat.ChatModel()
        model.append([{"key": str(n), "who": "x" if n % 3 else "y"} for n in range(10)])
        gone = model.remove_where(lambda row: row["who"] == "y")
        self.assertEqual(gone, 4)
        self.assertEqual([row["key"] for row in model.rows], ["1", "2", "4", "5", "7", "8"])


if __name__ == "__main__":
    unittest.main()
