"""Reading what YouTube puts beside a video, from answers shaped the way the
watch page's own call answers, measured 2026-10-02. Every id, title and token
here is made up."""

import unittest

from weave.sources import watchnext


def lockup(video_id, title, channel="Someone", kind="LOCKUP_CONTENT_TYPE_VIDEO",
           duration="3:25", facts=("1.3M views", "2 years ago"), channel_id="UC" + "c" * 22):
    return {"lockupViewModel": {
        "contentId": video_id,
        "contentType": kind,
        "contentImage": {"thumbnailViewModel": {
            "image": {"sources": [{"url": f"https://pictures.invalid/{video_id}-small.jpg"},
                                  {"url": f"https://pictures.invalid/{video_id}.jpg"}]},
            "overlays": [{"thumbnailBottomOverlayViewModel": {"badges": [
                {"thumbnailBadgeViewModel": {"text": duration}}]}}]}},
        "metadata": {"lockupMetadataViewModel": {
            "title": {"content": title},
            "image": {"decoratedAvatarViewModel": {"rendererContext": {"commandContext": {
                "onTap": {"innertubeCommand": {"browseEndpoint": {"browseId": channel_id}}}}}}},
            "metadata": {"contentMetadataViewModel": {"metadataRows": [
                {"metadataParts": [{"text": {"content": channel}}]},
                {"metadataParts": [{"text": {"content": fact}} for fact in facts]},
            ]}}}},
    }}


def mix_row(video_id, title, channel="Someone", length="4:01"):
    return {"playlistPanelVideoRenderer": {
        "videoId": video_id,
        "title": {"simpleText": title},
        "longBylineText": {"runs": [{"text": channel, "navigationEndpoint": {
            "browseEndpoint": {"browseId": "UC" + "m" * 22}}}]},
        "lengthText": {"simpleText": length},
        "thumbnail": {"thumbnails": [{"url": f"https://pictures.invalid/{video_id}.jpg"}]},
    }}


def chip(label, token=None):
    found = {"chipCloudChipRenderer": {"text": {"simpleText": label}}}
    if token is not None:
        found["chipCloudChipRenderer"]["navigationEndpoint"] = {
            "continuationCommand": {"token": token}}
    return found


def answer(side, mix=()):
    found = {"contents": {"twoColumnWatchNextResults": {
        "secondaryResults": {"secondaryResults": {"results": side}}}}}
    if mix:
        found["contents"]["twoColumnWatchNextResults"]["playlist"] = {
            "playlist": {"contents": list(mix)}}
    return found


SEED = "seedseedsee"


class SignedIn(unittest.TestCase):
    """Chips across the top, then the videos in a section of their own, with a
    Shorts shelf in among them."""

    def setUp(self):
        self.found = watchnext.parse_beside(answer([
            {"relatedChipCloudRenderer": {"content": {"chipCloudRenderer": {"chips": [
                chip("All", "tok-all"), chip("From Someone", "tok-from"),
                chip("Related", "tok-rel"), chip("Unaskable")]}}}},
            {"itemSectionRenderer": {"contents": [
                lockup("aaaaaaaaaaa", "First"),
                {"reelShelfRenderer": {"items": [lockup("shortshorts", "A Short")]}},
                lockup("PLlistlist1", "A playlist", kind="LOCKUP_CONTENT_TYPE_PLAYLIST"),
                lockup(SEED, "The one playing"),
                lockup("bbbbbbbbbbb", "Second", duration="LIVE", facts=("watching",)),
                lockup("aaaaaaaaaaa", "First again"),
                {"continuationItemRenderer": {}},
            ]}},
        ], mix=[mix_row(SEED, "The one playing"), mix_row("ccccccccccc", "Third"),
                mix_row("ddddddddddd", "Fourth")]), SEED)

    def test_the_mix_comes_first_then_the_chips_that_can_be_asked(self):
        self.assertEqual([(one.label, one.token) for one in self.found.chips],
                         [("Mix", ""), ("All", "tok-all"), ("From Someone", "tok-from"),
                          ("Related", "tok-rel")])

    def test_the_mix_leaves_out_the_one_playing(self):
        mix = self.found.cards["Mix"]
        self.assertEqual([card.video_id for card in mix], ["ccccccccccc", "ddddddddddd"])
        self.assertEqual((mix[0].title, mix[0].channel, mix[0].channel_id, mix[0].duration,
                          mix[0].picture),
                         ("Third", "Someone", "UC" + "m" * 22, "4:01",
                          "https://pictures.invalid/ccccccccccc.jpg"))

    def test_all_is_videos_once_each_without_shorts_or_playlists(self):
        cards = self.found.cards["All"]
        self.assertEqual([card.video_id for card in cards], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        first, second = cards
        self.assertEqual((first.title, first.channel, first.channel_id, first.duration,
                          first.views, first.age, first.picture),
                         ("First", "Someone", "UC" + "c" * 22, "3:25", "1.3M views",
                          "2 years ago", "https://pictures.invalid/aaaaaaaaaaa.jpg"))
        self.assertEqual((second.duration, second.views, second.age), ("LIVE", "watching", ""))


class SignedOut(unittest.TestCase):
    def test_no_chips_is_the_mix_and_all(self):
        found = watchnext.parse_beside(answer([lockup("aaaaaaaaaaa", "First")]), SEED)
        self.assertEqual([one.label for one in found.chips], ["Mix", "All"])
        self.assertEqual([card.title for card in found.cards["All"]], ["First"])
        self.assertEqual(found.cards["Mix"], [])

    def test_an_answer_with_no_watch_page_is_an_error(self):
        with self.assertRaises(watchnext.WatchNextError):
            watchnext.parse_beside({"error": {"code": 400}})


class AChipPressed(unittest.TestCase):
    def test_a_reload_and_more_after_it(self):
        found = watchnext.parse_chip({"onResponseReceivedEndpoints": [
            {"reloadContinuationItemsCommand": {"continuationItems": [
                lockup("aaaaaaaaaaa", "First"), lockup("bbbbbbbbbbb", "Second")]}},
            {"appendContinuationItemsAction": {"continuationItems": [
                lockup("ccccccccccc", "Third"), {"continuationItemRenderer": {}}]}},
        ]})
        self.assertEqual([card.title for card in found], ["First", "Second", "Third"])

    def test_nothing_for_the_chip_is_an_error(self):
        with self.assertRaises(watchnext.WatchNextError):
            watchnext.parse_chip({"responseContext": {}})


class Asking(unittest.TestCase):
    def test_the_first_call_names_the_mix_and_a_chip_sends_its_token(self):
        sent = []

        class Fetcher:
            def post_json(self, url, payload, headers=None):
                sent.append((url, payload, headers))
                return answer([]) if "videoId" in payload else {
                    "onResponseReceivedEndpoints": []}

        watchnext.beside(Fetcher(), SEED, {"Cookie": "x"})
        watchnext.chip(Fetcher(), "tok-rel")
        (url, first, headers), (_, second, _) = sent
        self.assertEqual(url, watchnext.ENDPOINT)
        self.assertEqual((first["videoId"], first["playlistId"]), (SEED, "RD" + SEED))
        self.assertEqual(first["context"]["client"]["clientName"], "WEB")
        self.assertEqual(headers, {"Cookie": "x"})
        self.assertEqual(second["continuation"], "tok-rel")


if __name__ == "__main__":
    unittest.main()
