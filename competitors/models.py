from django.db import models


class Constructor(models.Model):
    ref = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=80)
    nationality = models.CharField(max_length=60, blank=True)
    url = models.URLField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Driver(models.Model):
    ref = models.CharField(max_length=50, unique=True)
    code = models.CharField(max_length=5, blank=True)
    given_name = models.CharField(max_length=60)
    family_name = models.CharField(max_length=60)
    nationality = models.CharField(max_length=60, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    url = models.URLField(blank=True)

    class Meta:
        ordering = ["family_name", "given_name"]

    def __str__(self) -> str:
        return f"{self.given_name} {self.family_name}"

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}"

    @property
    def age(self) -> int | None:
        if not self.date_of_birth:
            return None
        from datetime import date

        today = date.today()
        return (
            today.year
            - self.date_of_birth.year
            - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        )
