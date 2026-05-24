from django.db import models

from competitors.models import Constructor, Driver
from seasons.models import Round


class Session(models.Model):
    """A single on-track session within a race weekend.

    There is at most one Session per (Round, kind). The `kind` enum mirrors
    FastF1's session identifiers so that loading code stays a straight
    translation; the `FASTF1_CODES` map below is the canonical bridge.
    """

    FP1 = "fp1"
    FP2 = "fp2"
    FP3 = "fp3"
    QUALIFYING = "q"
    SPRINT_QUALIFYING = "sq"
    SPRINT = "sprint"
    RACE = "race"

    KIND_CHOICES = (
        (FP1, "FP1"),
        (FP2, "FP2"),
        (FP3, "FP3"),
        (QUALIFYING, "Qualifying"),
        (SPRINT_QUALIFYING, "Sprint Qualifying"),
        (SPRINT, "Sprint"),
        (RACE, "Race"),
    )

    # FastF1 session-identifier ↔ our kind. Keep both directions in sync if a
    # new session type ever lands (e.g. a future "warm-up").
    FASTF1_CODES = {
        FP1: "FP1",
        FP2: "FP2",
        FP3: "FP3",
        QUALIFYING: "Q",
        SPRINT_QUALIFYING: "SQ",
        SPRINT: "S",
        RACE: "R",
    }

    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="telemetry_sessions")
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    last_synced = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("round", "kind")
        ordering = ["round__season__year", "round__number", "kind"]

    def __str__(self) -> str:
        return f"{self.round} {self.get_kind_display()}"


class SessionStat(models.Model):
    """Telemetry-derived per-driver aggregates for one Session.

    All numeric fields are nullable because FastF1 may legitimately have no
    data for a driver (DNS, no flying lap, sensor dropouts) — we still want
    the row so re-syncs are idempotent.
    """

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="stats")
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT)
    constructor = models.ForeignKey(Constructor, on_delete=models.PROTECT, null=True, blank=True)

    fastest_lap_seconds = models.FloatField(null=True, blank=True)
    fastest_lap_number = models.IntegerField(null=True, blank=True)
    fastest_lap_compound = models.CharField(max_length=12, blank=True)

    top_speed_kmh = models.FloatField(null=True, blank=True)

    sector1_best_seconds = models.FloatField(null=True, blank=True)
    sector2_best_seconds = models.FloatField(null=True, blank=True)
    sector3_best_seconds = models.FloatField(null=True, blank=True)
    theoretical_best_seconds = models.FloatField(null=True, blank=True)

    laps_completed = models.IntegerField(default=0)

    class Meta:
        unique_together = ("session", "driver")
        indexes = [
            models.Index(fields=["session", "top_speed_kmh"]),
            models.Index(fields=["session", "fastest_lap_seconds"]),
        ]
        ordering = ["session", "fastest_lap_seconds"]

    def __str__(self) -> str:
        return f"{self.session} · {self.driver} · {self.fastest_lap_seconds}s"


class Lap(models.Model):
    """One driver's lap within a Session.

    Sized for race + practice volume: roughly 50 drivers × 70 laps per race,
    upserted via bulk_create(update_conflicts=True), so the natural-key
    UniqueConstraint below is load-bearing — the database needs it to know
    which existing row to update.
    """

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="laps")
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT)
    number = models.IntegerField()

    lap_time_seconds = models.FloatField(null=True, blank=True)
    sector1_seconds = models.FloatField(null=True, blank=True)
    sector2_seconds = models.FloatField(null=True, blank=True)
    sector3_seconds = models.FloatField(null=True, blank=True)

    compound = models.CharField(max_length=12, blank=True)
    # Laps the tyre has done at the END of this lap (FastF1's TyreLife column).
    tyre_life = models.IntegerField(null=True, blank=True)
    stint_number = models.IntegerField(null=True, blank=True)

    position = models.IntegerField(null=True, blank=True)
    speed_st_kmh = models.FloatField(null=True, blank=True)

    is_personal_best = models.BooleanField(default=False)
    # FIA-deleted laps (track-limits, yellow-flag improvements, etc). FastF1
    # exposes the `Deleted` flag on the laps frame.
    is_deleted = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "driver", "number"], name="uniq_lap_session_driver_number"
            )
        ]
        indexes = [
            models.Index(fields=["session", "driver", "number"]),
            models.Index(fields=["session", "lap_time_seconds"]),
        ]
        ordering = ["session", "driver", "number"]

    def __str__(self) -> str:
        return f"{self.session} · {self.driver} · L{self.number}"


class Stint(models.Model):
    """A contiguous run on one set of tyres for a driver in a session."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="stints")
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT)
    number = models.IntegerField()

    compound = models.CharField(max_length=12, blank=True)
    lap_start = models.IntegerField()
    lap_end = models.IntegerField()
    laps_count = models.IntegerField()
    # Tyre life when the set was fitted (0 = brand-new). FastF1 reports this
    # via TyreLife on the first lap of the stint.
    compound_age_at_start = models.IntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "driver", "number"], name="uniq_stint_session_driver_number"
            )
        ]
        indexes = [models.Index(fields=["session", "driver"])]
        ordering = ["session", "driver", "number"]

    def __str__(self) -> str:
        return f"{self.session} · {self.driver} · stint {self.number} ({self.compound})"
