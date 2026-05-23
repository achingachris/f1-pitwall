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

    class Meta:
        unique_together = ("season", "number")
        ordering = ["season__year", "number"]

    def __str__(self) -> str:
        return f"{self.season.year} R{self.number} {self.name}"
