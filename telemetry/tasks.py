import logging

from celery import shared_task

from seasons.models import Round
from seasons.services.cache import bump_data_version
from telemetry.services.sync import sync_session_safe

log = logging.getLogger(__name__)


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
        bump_data_version()
    return (
        f"telemetry: {year} R{round_number} {kind} → "
        f"stats={counts['stats']} laps={counts['laps']} stints={counts['stints']} "
        f"deleted={counts.get('deleted', 0)}"
    )
