from django.db import models

from competitors.models import Constructor, Driver
from seasons.models import Round


class Result(models.Model):
    SESSION_CHOICES = (
        ("race", "race"),
        ("sprint", "sprint"),
    )

    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="results")
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT)
    constructor = models.ForeignKey(Constructor, on_delete=models.PROTECT)
    session = models.CharField(max_length=6, choices=SESSION_CHOICES, default="race")
    position = models.IntegerField(null=True, blank=True)
    position_text = models.CharField(max_length=3)
    points = models.FloatField(default=0)
    grid = models.IntegerField(default=0)
    status = models.CharField(max_length=40, blank=True)
    fastest_lap_rank = models.IntegerField(null=True, blank=True)
    fastest_lap_time = models.CharField(max_length=15, blank=True)
    fastest_lap_speed_kmh = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("round", "driver", "session")
        indexes = [
            models.Index(fields=["round", "session"]),
            models.Index(fields=["driver", "session"]),
            models.Index(fields=["constructor", "session"]),
        ]
        ordering = ["round__season__year", "round__number", "session", "position"]

    def __str__(self) -> str:
        return f"{self.round} {self.session} P{self.position_text} {self.driver}"


class Qualifying(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="qualifying")
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT)
    constructor = models.ForeignKey(Constructor, on_delete=models.PROTECT)
    position = models.IntegerField()
    q1 = models.CharField(max_length=15, blank=True)
    q2 = models.CharField(max_length=15, blank=True)
    q3 = models.CharField(max_length=15, blank=True)

    class Meta:
        unique_together = ("round", "driver")
        ordering = ["round__season__year", "round__number", "position"]

    def __str__(self) -> str:
        return f"{self.round} Q P{self.position} {self.driver}"


class Standing(models.Model):
    KIND_CHOICES = (
        ("driver", "driver"),
        ("constructor", "constructor"),
    )

    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="standings")
    kind = models.CharField(max_length=11, choices=KIND_CHOICES)
    driver = models.ForeignKey(Driver, null=True, blank=True, on_delete=models.CASCADE)
    constructor = models.ForeignKey(Constructor, null=True, blank=True, on_delete=models.CASCADE)
    position = models.IntegerField()
    points = models.FloatField()
    wins = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["round", "kind", "driver"],
                condition=models.Q(kind="driver", constructor__isnull=True),
                name="uniq_driver_standing_snapshot",
            ),
            models.UniqueConstraint(
                fields=["round", "kind", "constructor"],
                condition=models.Q(kind="constructor", driver__isnull=True),
                name="uniq_constructor_standing_snapshot",
            ),
        ]
        indexes = [
            models.Index(fields=["round", "kind", "position"]),
        ]
        ordering = ["round__season__year", "round__number", "kind", "position"]

    def __str__(self) -> str:
        who = self.driver or self.constructor
        return f"{self.round} {self.kind} P{self.position} {who} ({self.points})"
