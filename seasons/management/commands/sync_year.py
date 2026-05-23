from django.core.management.base import BaseCommand
from django.utils.timezone import now

from seasons.models import Round, Season
from seasons.services.cache import bump_data_version
from seasons.services.sync import (
    sync_qualifying,
    sync_results,
    sync_schedule,
    sync_standings,
)


class Command(BaseCommand):
    help = "Sync schedule, results, qualifying, and standings for a given season."

    def add_arguments(self, parser):
        parser.add_argument("year", type=int)
        parser.add_argument(
            "--skip-results",
            action="store_true",
            help="Only refresh schedule + standings; skip per-round results/qualifying.",
        )

    def handle(self, *args, year: int, skip_results: bool, **opts):
        self.stdout.write(f"→ schedule {year}")
        sync_schedule(year)
        if not skip_results:
            for rnd in Round.objects.filter(season__year=year).order_by("number"):
                self.stdout.write(f"  • R{rnd.number} {rnd.name}")
                sync_results(rnd, "race")
                if rnd.has_sprint:
                    sync_results(rnd, "sprint")
                sync_qualifying(rnd)
        self.stdout.write("→ standings")
        sync_standings(year)
        Season.objects.filter(year=year).update(last_synced=now())
        bump_data_version()
        self.stdout.write(self.style.SUCCESS(f"✓ {year} synced"))
