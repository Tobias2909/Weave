"""Deciding whether a video is a Short.

Nothing cheap exposes this. RSS has no flag, the Shorts tab reports no
duration, and the subscriptions sweep has no marker either. The one reliable
test is what the Shorts address does. A Short answers directly, a long form
video redirects to its watch page.

The request carries a consent choice. Without it YouTube answers every request
from here with a redirect to its consent page, which makes both cases look
identical. This is a stored consent preference rather than a claim about who is
asking, and the user agent stays honest.
"""

from __future__ import annotations

from ..net import Fetcher

SHORTS_URL = "https://www.youtube.com/shorts/{video_id}"

# Recording a consent choice, which is what the interstitial asks for.
CONSENT_COOKIES = {"SOCS": "CAI"}

SHORT_STATUS = 200
LONG_FORM_STATUSES = (301, 302, 303, 307, 308)


class UndecidedError(RuntimeError):
    """The answer was neither a Short nor a redirect to a watch page."""


def classify(fetcher: Fetcher, video_id: str) -> bool:
    """True when the id is a Short. Raises when the answer is unusable, so an
    undecided video stays unclassified and gets another chance later rather
    than being wrongly filed."""
    status, location = fetcher.head_status(
        SHORTS_URL.format(video_id=video_id), cookies=CONSENT_COOKIES)
    if status == SHORT_STATUS:
        return True
    if status in LONG_FORM_STATUSES:
        if "consent." in location:
            raise UndecidedError("answered with the consent page")
        if "/watch" in location:
            return False
        raise UndecidedError(f"redirected somewhere unexpected, {location[:60]}")
    raise UndecidedError(f"unexpected status {status}")
