from django.db import models


class Season(models.Model):
    year = models.IntegerField(unique=True)
    last_synced = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-year"]

    def __str__(self) -> str:
        return str(self.year)


class Circuit(models.Model):
    ref = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=120)
    locality = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True)

    def __str__(self) -> str:
        return self.name


class Round(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="rounds")
    number = models.IntegerField()
    name = models.CharField(max_length=120)
    circuit = models.ForeignKey(Circuit, on_delete=models.PROTECT)
    date = models.DateField()
    has_sprint = models.BooleanField(default=False)

    # Per-session start times (UTC). jolpica /races provides these alongside
    # each race; we capture the lot so the bot can show "Sessions" schedules.
    fp1_at = models.DateTimeField(null=True, blank=True)
    fp2_at = models.DateTimeField(null=True, blank=True)
    fp3_at = models.DateTimeField(null=True, blank=True)
    qualifying_at = models.DateTimeField(null=True, blank=True)
    sprint_qualifying_at = models.DateTimeField(null=True, blank=True)
    sprint_at = models.DateTimeField(null=True, blank=True)
    race_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("season", "number")
        ordering = ["season__year", "number"]

    def __str__(self) -> str:
        return f"{self.season.year} R{self.number} {self.name}"

    @property
    def sessions(self) -> list[tuple[str, "models.DateTimeField"]]:
        """All known session timestamps in chronological order.

        Returns a list of (label, datetime) tuples for sessions that have
        timestamps set. Useful for "Sessions" displays.
        """
        candidates = [
            ("FP1", self.fp1_at),
            ("FP2", self.fp2_at),
            ("FP3", self.fp3_at),
            ("Sprint Quali", self.sprint_qualifying_at),
            ("Sprint", self.sprint_at),
            ("Qualifying", self.qualifying_at),
            ("Race", self.race_at),
        ]
        return [(label, dt) for label, dt in candidates if dt is not None]
