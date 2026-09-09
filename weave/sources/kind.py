"""Whether one video is a Short, asked of the video itself.

RSS cannot answer this. The Atom feed carries no flag for it and no duration
either, which is not a gap in this code: NewPipe's own feed extractor has no
isShortFormContent method at all and its getDuration returns -1 with the
comment "Not available when fetching through the feed endpoint", and FreeTube
reads the kind off the InnerTube node type instead, ReelItem and
ShortsLockupView. Every client that filters Shorts does it from a browse call.

Asking for a channel's UULF tab is the cheap answer and stays the first one,
since it is one request for a whole channel and settles every row it carries
in advance. This is for what that cannot reach: a channel stuck on the mixed
feed, whose rows arrive of no stated kind, and which the Shorts tab only names
the Shorts of, never the ordinary videos.

The test is a redirect. `/shorts/<id>` is the Short player, so YouTube answers
200 for a Short and sends a 303 to `/watch?v=` for anything else. MEASURED
2026-09-09 against the live site, as a HEAD, on rows of already known kind:
three Shorts answered 200, three long videos answered 303, and of four rows of
unknown kind two came back Shorts and two came back ordinary videos.

Two things it must have. The consent cookie: without SOCS=CAI both a Short and
a long video answer 302 to the consent page, which destroys the
discriminator, measured the same day. And a HEAD rather than a GET, since the
body is a megabyte of player HTML and nothing here reads it.

Length is NOT the signal and never was. A Short is at most three minutes, but
so are plenty of ordinary videos: the clip this was first tested on runs 88
seconds and answers 303. An older rule here classified by duration and could
not classify 89% of a real library, because RSS carries no duration to
classify by.
"""

from __future__ import annotations

from ..net import Fetcher

_BASE = "https://www.youtube.com/shorts/"

# Without this both kinds answer 302 to the consent page. It is the same value
# a browser stores after the notice is dismissed and it carries no identity.
_CONSENT = {"SOCS": "CAI"}

# 200 means the Short player answered for this id. A 303 to /watch means it is
# an ordinary video. Anything else is the site not answering the question, and
# is not an answer about the video.
_IS_SHORT = 200
_IS_A_VIDEO = 303


def is_short(fetcher: Fetcher, video_id: str) -> bool | None:
    """Whether this video is a Short, or None if the site did not say.

    None on anything but the two known answers, deliberately: a refusal, a
    consent page, a redirect somewhere else and a 5xx all look alike from
    here, and a row left unknown is asked again later, while a row marked
    wrongly is either a Short in the feed or an ordinary video missing from
    it for good.
    """
    status, _ = fetcher.head_status(_BASE + video_id, cookies=_CONSENT)
    if status == _IS_SHORT:
        return True
    if status == _IS_A_VIDEO:
        return False
    return None
