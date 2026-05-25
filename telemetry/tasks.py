import logging
from datetime import date

from django.utils.timezone import now

from celery import shared_task

from seasons.models import Round
from seasons.services.cache import bump_telemetry_version
from telemetry.services.sync import sync_session_safe

log = logging.getLogger(__name__)

# FastF1 coverage cutoff; older seasons resolve to a no-op via
# sync_session_safe but skipping early avoids queuing pointless tasks.
_FASTF1_MIN_YEAR = 2018


@shared_task
def sync_session_task(year: int, round_number: int, kind: str) -> str:
    """Sync one (year, round, kind) session via FastF1.

    Safe wrapper: returns a status string and bumps the cache version key
    when anything was written, so cached telemetry views invalidate. Seasons
    before FastF1 coverage (pre-2018) resolve to a no-op via
    `sync_session_safe`.
    """
    rnd = Round.objects.filter(season__year=year, number=round_number).first()
    if rnd is None:
        return f"telemetry: no Round for {year} R{round_number}"
    counts = sync_session_safe(rnd, kind)
    if any(counts.values()):
        bump_telemetry_version()
    return (
        f"telemetry: {year} R{round_number} {kind} → "
        f"stats={counts['stats']} laps={counts['laps']} stints={counts['stints']} "
        f"deleted={counts.get('deleted', 0)}"
    )


@shared_task
def sync_recent_telemetry(rounds_back: int = 2) -> str:
    """Fan out `sync_session_task` calls for the latest N completed rounds
    of the current season. Idempotent end-to-end — each session sync is a
    no-op when FastF1 has nothing new. Used by the race-weekend Beat
    schedule to keep Lap/Stint/SessionStat rows fresh without manual
    intervention.

    Each (round, kind) becomes its own task so progress is visible per
    session in the django-celery-results admin.
    """
    year = date.today().year
    if year < _FASTF1_MIN_YEAR:
        return f"telemetry: skipped (year {year} < FastF1 cutoff)"

    recent = list(
        Round.objects.filter(season__year=year, race_at__lte=now()).order_by("-race_at")[
            :rounds_back
        ]
    )

    queued = 0
    for rnd in recent:
        kinds = ["race", "q"]
        if rnd.has_sprint:
            kinds += ["sprint", "sq"]
        for kind in kinds:
            sync_session_task.delay(year, rnd.number, kind)
            queued += 1

    return f"telemetry: queued {queued} session syncs across {len(recent)} round(s) in {year}"


@shared_task
def backfill_telemetry(start_year: int = _FASTF1_MIN_YEAR, end_year: int | None = None) -> str:
    """One-shot: fan out sync_session_task for every completed round across
    `start_year..end_year`. Walks newest-first so the freshest data lands
    early — if the queue gets interrupted, the most-valuable rounds are
    already done.

    Each (round, kind) is idempotent end-to-end. Pre-2018 years are clamped
    out because FastF1 has no coverage."""
    end_year = end_year or date.today().year
    start_year = max(start_year, _FASTF1_MIN_YEAR)

    queued = 0
    rounds_seen = 0
    for year in range(end_year, start_year - 1, -1):
        rounds = Round.objects.filter(season__year=year, race_at__lte=now()).order_by("-number")
        for rnd in rounds:
            rounds_seen += 1
            kinds = ["race", "q"]
            if rnd.has_sprint:
                kinds += ["sprint", "sq"]
            for kind in kinds:
                sync_session_task.delay(year, rnd.number, kind)
                queued += 1

    return (
        f"telemetry backfill: queued {queued} session syncs across "
        f"{rounds_seen} round(s) in {start_year}..{end_year}"
    )
