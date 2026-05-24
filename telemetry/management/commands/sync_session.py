from django.core.management.base import BaseCommand, CommandError

from seasons.models import Round
from telemetry.models import Session
from telemetry.tasks import sync_session_task


class Command(BaseCommand):
    help = (
        "Enqueue a Celery task to pull telemetry (SessionStat + Lap + Stint) "
        "for one (year, round, kind) session from FastF1. Requires the round "
        "to already exist via `sync_year`, and a running Celery worker."
    )

    def add_arguments(self, parser):
        parser.add_argument("year", type=int)
        parser.add_argument("round", type=int, help="Round number within the season.")
        parser.add_argument(
            "kind",
            choices=[k for k, _ in Session.KIND_CHOICES],
            help="Session kind: fp1, fp2, fp3, q, sq, sprint, race.",
        )

    def handle(self, *args, year: int, round: int, kind: str, **opts):
        if not Round.objects.filter(season__year=year, number=round).exists():
            raise CommandError(f"No Round for {year} R{round}. Run `sync_year {year}` first.")

        result = sync_session_task.delay(year, round, kind)
        self.stdout.write(
            self.style.SUCCESS(f"queued sync_session_task({year}, {round}, {kind}) → {result.id}")
        )
