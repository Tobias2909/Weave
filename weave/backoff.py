"""Easing off an endpoint that is pushing back.

The feed endpoint refuses a burst with a 404 rather than with a busy signal, so
a refusal looks exactly like a channel that has no such feed. One of those is
nothing; a third of a round of them is the endpoint saying stop. Measured on a
real collection: four hours of two hundred requests a quarter hour with not one
refusal, then a quarter hour where seventy-nine of two hundred and thirty-two
were refused, and every one of them a channel that answered fine an hour
earlier and answered fine again ten minutes later.

Without this, nothing changed when that happened. The poller went on asking
fifteen channels a minute into an endpoint that was refusing every third one,
which is the one thing certain not to help.

The decision is a pure function of what the last few minutes look like, so it
can be tested without a clock, a database or a network. Where it is written
down matters as much: a rest lives in the database rather than in the poller,
because a restart starts a round at once and somebody testing a build restarts
constantly.
"""

from __future__ import annotations

from dataclasses import dataclass

# What the last few minutes have to look like before anything is called
# pushback. The share catches a refusing endpoint; the floor stops a quiet
# minute with one bad channel in it from resting the whole feed.
WINDOW_S = 300
SHARE = 0.25
FLOOR = 5

# Doubling from two minutes. Half an hour is where it stops, because a rest
# longer than that is indistinguishable from the application being broken, and
# because the endpoint has always come back well inside it.
FIRST_S = 120
LONGEST_S = 1800


@dataclass(frozen=True)
class Rest:
    """What to do about an endpoint, and what to say about it."""

    seconds: int = 0
    step: int = 0

    @property
    def resting(self) -> bool:
        return self.seconds > 0


def pushing_back(sent: int, refused: int) -> bool:
    """Whether what came back counts as the endpoint saying stop."""
    if refused < FLOOR or sent <= 0:
        return False
    return refused / sent >= SHARE


def next_rest(sent: int, refused: int, step: int = 0) -> Rest:
    """How long to leave the endpoint alone, given the last few minutes.

    Doubling while it keeps refusing, and back to nothing the moment a window
    comes back clean, so an endpoint that recovers is asked again at once
    rather than being punished for what it did ten minutes ago.
    """
    if not pushing_back(sent, refused):
        return Rest(0, 0)
    step = max(0, step) + 1
    seconds = min(LONGEST_S, FIRST_S * (2 ** (step - 1)))
    return Rest(seconds, step)


def said(endpoint: str, seconds_left: int) -> str:
    """What to tell somebody staring at a window that is not refreshing."""
    minutes = max(1, (seconds_left + 59) // 60)
    return (f"the {endpoint} endpoint is refusing, resting {minutes} min. "
            "It clears on its own")
