"""Calendar lookups for the landing-page hero card.

Cheap, pure-DB. NOT cached — the landing view computes them on every request
so countdowns stay fresh. Two indexed `Round` queries at most.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from seasons.models import Round

# Rough upper bound on how long a session can run. Used to decide if a session
# is still "underway" — F1 race sessions are scheduled 1:30 but can stretch
# (red flags, safety cars), and qualifying / practice fit comfortably inside
# 3h. This keeps the hero card showing "live" for an extra cushion past the
# scheduled start.
SESSION_DURATION = timedelta(hours=3)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _round_window(rnd: Round) -> Optional[tuple[datetime, datetime]]:
    """The (start, end) window for a race weekend, in UTC.

    Start = earliest known session time. End = race_at + SESSION_DURATION
    (or the last known session + SESSION_DURATION if race_at is missing).
    Returns None when the round has no session timestamps at all.
    """
    sessions = rnd.sessions  # already chronologically sorted, only those set
    if not sessions:
        return None
    start = sessions[0][1]
    last = rnd.race_at or sessions[-1][1]
    return start, last + SESSION_DURATION


def current_race_weekend(now: Optional[datetime] = None) -> Optional[Round]:
    """The Round whose session window covers `now`, if any.

    Looks at rounds dated within ±4 days of `now` so we don't scan the whole
    calendar. Returns None outside any race weekend.
    """
    now = now or _now()
    candidates = Round.objects.filter(
        date__gte=(now - timedelta(days=4)).date(),
        date__lte=(now + timedelta(days=4)).date(),
    ).select_related("circuit", "season")
    for rnd in candidates:
        window = _round_window(rnd)
        if window and window[0] <= now <= window[1]:
            return rnd
    return None


def next_race_weekend(now: Optional[datetime] = None) -> Optional[Round]:
    """The next Round whose session schedule (or date fallback) is in the future."""
    now = now or _now()
    today = now.date()
    candidates = (
        Round.objects.filter(date__gte=today)
        .select_related("circuit", "season")
        .order_by("date", "number")
    )
    for rnd in candidates:
        sessions = rnd.sessions
        if sessions:
            if any(dt > now for _, dt in sessions):
                return rnd
            continue
        if rnd.date >= today:
            return rnd
    return None


def current_or_next_session(
    rnd: Round, now: Optional[datetime] = None
) -> Optional[tuple[str, datetime, bool]]:
    """For a given round, return (label, datetime, is_live) for the most
    relevant session.

    Picks the live session if any is currently within its window, else the
    earliest upcoming one, else None.
    """
    now = now or _now()
    sessions = rnd.sessions
    if not sessions:
        return None
    for label, dt in sessions:
        if dt <= now <= dt + SESSION_DURATION:
            return label, dt, True
    for label, dt in sessions:
        if dt > now:
            return label, dt, False
    return None
