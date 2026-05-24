from django.core.management.base import BaseCommand, CommandError

from seasons.models import Round
from seasons.services.cache import bump_data_version
from telemetry.models import Session
from telemetry.services.fastf1_client import FastF1Unavailable
from telemetry.services.sync import sync_session


class Command(BaseCommand):
    help = (
        "Pull telemetry (SessionStat + Lap + Stint) for one (year, round, kind) "
        "session from FastF1. Requires the round to already exist via `sync_year`."
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
        rnd = Round.objects.filter(season__year=year, number=round).first()
        if rnd is None:
            raise CommandError(f"No Round for {year} R{round}. Run `sync_year {year}` first.")

        self.stdout.write(f"→ FastF1 {year} R{round} {kind}")
        try:
            counts = sync_session(rnd, kind)
        except FastF1Unavailable as e:
            raise CommandError(str(e)) from e

        if any(counts.values()):
            bump_data_version()
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ stats={counts['stats']} laps={counts['laps']} "
                f"stints={counts['stints']} deleted={counts.get('deleted', 0)}"
            )
        )
