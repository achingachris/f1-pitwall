"""Pure-DB analytics. No outbound calls."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Max, Sum

from results.models import Result, Standing
from seasons.models import Round

# Points for one finish. Constructors get both cars' worth (1+2 sweep): 25+18, 8+7.
RACE_WIN = 25
SPRINT_WIN = 8
CONSTRUCTOR_RACE_TOP = RACE_WIN + 18
CONSTRUCTOR_SPRINT_TOP = SPRINT_WIN + 7


def _is_classified_status(status: str) -> bool:
    return status == "Finished" or (status.startswith("+") and "Lap" in status)


@dataclass
class Contender:
    label: str
    points: float
    gap: float
    max_attainable: float
    ref: str = ""
    kind: str = "driver"  # "driver" or "constructor" — used to build the modal URL
    nationality: str = ""


@dataclass(frozen=True)
class StandingChange:
    """Movement vs the previous stored standings snapshot (current season only)."""

    position_delta: int  # positive = gained places (e.g. P5 → P3 → +2)
    points_delta: float

    @property
    def positions_up(self) -> int:
        return self.position_delta if self.position_delta > 0 else 0

    @property
    def positions_down(self) -> int:
        return -self.position_delta if self.position_delta < 0 else 0


def latest_standings_round(year: int, kind: str = "driver") -> Round | None:
    """The Round our most recent stored standings snapshot points at.

    Anchored on Standing rows (not Result rows) because jolpica's standings
    response may reference a round that's a step ahead of the rounds we have
    Result data for — we always trust the points snapshot.
    """
    return (
        Round.objects.filter(
            season__year=year,
            standings__kind=kind,
        )
        .distinct()
        .order_by("-number")
        .first()
    )


def _previous_standings_round(year: int, latest: Round, kind: str) -> Round | None:
    return (
        Round.objects.filter(
            season__year=year,
            number__lt=latest.number,
            standings__kind=kind,
        )
        .distinct()
        .order_by("-number")
        .first()
    )


def standing_changes(year: int, kind: str = "driver") -> dict[int, StandingChange] | None:
    """Per-entity movement after the latest race/sprint on the current season.

    Compares the latest jolpica standings snapshot to the prior round's snapshot.
    Returns None when the change column should be hidden (past seasons, round 1,
    or no race/sprint results yet for the latest round).
    """
    if year != date.today().year:
        return None

    latest = latest_standings_round(year, kind=kind)
    if latest is None:
        return None

    if not Result.objects.filter(round=latest, session__in=("race", "sprint")).exists():
        return None

    previous = _previous_standings_round(year, latest, kind)
    if previous is None:
        return None

    prev_rows = Standing.objects.filter(round=previous, kind=kind)
    if kind == "driver":
        prev_by_id = {row.driver_id: row for row in prev_rows if row.driver_id}
    else:
        prev_by_id = {row.constructor_id: row for row in prev_rows if row.constructor_id}

    changes: dict[int, StandingChange] = {}
    for current in Standing.objects.filter(round=latest, kind=kind):
        eid = current.driver_id if kind == "driver" else current.constructor_id
        if not eid:
            continue
        prior = prev_by_id.get(eid)
        if prior is None:
            continue
        changes[eid] = StandingChange(
            position_delta=prior.position - current.position,
            points_delta=current.points - prior.points,
        )
    return changes


def contenders(year: int, constructor: bool = False) -> list[Contender]:
    kind = "constructor" if constructor else "driver"
    latest = latest_standings_round(year, kind=kind)
    if latest is None:
        return []

    # "Rounds left" = anything in the calendar after the latest standings round.
    # This stays consistent with whichever round the standings reflect, even
    # if it doesn't match today's date.
    rounds_left = Round.objects.filter(season__year=year, number__gt=latest.number)
    races_left = rounds_left.count()
    sprints_left = rounds_left.filter(has_sprint=True).count()
    per_race = CONSTRUCTOR_RACE_TOP if constructor else RACE_WIN
    per_sprint = CONSTRUCTOR_SPRINT_TOP if constructor else SPRINT_WIN
    cap = races_left * per_race + sprints_left * per_sprint

    table = Standing.objects.filter(round=latest, kind=kind).select_related("driver", "constructor")
    leader = table.aggregate(m=Max("points"))["m"] or 0

    out: list[Contender] = []
    for row in table.order_by("position"):
        if row.points + cap >= leader:
            if constructor and row.constructor:
                label = row.constructor.name
                ref = row.constructor.ref
                nationality = row.constructor.nationality
            elif row.driver:
                label = f"{row.driver.given_name} {row.driver.family_name}"
                ref = row.driver.ref
                nationality = row.driver.nationality
            else:
                label = "?"
                ref = ""
                nationality = ""
            out.append(
                Contender(
                    label=label,
                    ref=ref,
                    kind="constructor" if constructor else "driver",
                    nationality=nationality,
                    points=row.points,
                    gap=leader - row.points,
                    max_attainable=row.points + cap,
                )
            )
    return out


def most_improved(year: int, constructor: bool = False) -> dict[str, Any] | None:
    """Compare avg points/round in the second half vs the first half of the season."""
    grp = "constructor" if constructor else "driver"
    rows = list(
        Result.objects.filter(round__season__year=year, session="race")
        .values(grp, "round__number")
        .annotate(pts=Sum("points"))
        .order_by("round__number")
    )
    if not rows:
        return None

    series: dict[int, dict[int, float]] = defaultdict(dict)
    for r in rows:
        series[r[grp]][r["round__number"]] = float(r["pts"])

    rounds_played = sorted({r["round__number"] for r in rows})
    if len(rounds_played) < 2:
        return None
    mid = len(rounds_played) // 2
    first_half, second_half = rounds_played[:mid], rounds_played[mid:]

    def delta(by_round: dict[int, float]) -> float:
        first = sum(by_round.get(n, 0) for n in first_half) / max(len(first_half), 1)
        second = sum(by_round.get(n, 0) for n in second_half) / max(len(second_half), 1)
        return second - first

    pk, by_round = max(series.items(), key=lambda kv: delta(kv[1]))
    diff = delta(by_round)

    if constructor:
        from competitors.models import Constructor

        obj = Constructor.objects.filter(pk=pk).first()
        label = obj.name if obj else "?"
        ref = obj.ref if obj else ""
        nationality = obj.nationality if obj else ""
        kind = "constructor"
    else:
        from competitors.models import Driver

        obj = Driver.objects.filter(pk=pk).first()
        label = obj.full_name if obj else "?"
        ref = obj.ref if obj else ""
        nationality = obj.nationality if obj else ""
        kind = "driver"

    return {
        "label": label,
        "ref": ref,
        "kind": kind,
        "nationality": nationality,
        "delta": diff,
        "first_half_avg": sum(by_round.get(n, 0) for n in first_half) / max(len(first_half), 1),
        "second_half_avg": sum(by_round.get(n, 0) for n in second_half) / max(len(second_half), 1),
        "rounds_played": len(rounds_played),
    }


def funstats(year: int) -> dict[str, Any]:
    """Fastest / slowest aggregates for a season."""
    fastest_qs = (
        Result.objects.filter(round__season__year=year, fastest_lap_rank=1, session="race")
        .exclude(fastest_lap_time="")
        .select_related("driver", "round")
    )
    fastest_lap = fastest_qs.order_by("fastest_lap_time").first()

    by_round_fastest = list(
        Result.objects.filter(round__season__year=year, fastest_lap_rank=1, session="race")
        .exclude(fastest_lap_time="")
        .select_related("driver", "round")
        .order_by("round__number")
    )

    # Slowest classified finisher per round (last classified position).
    race_results = (
        Result.objects.filter(round__season__year=year, session="race", position__isnull=False)
        .select_related("driver", "round")
        .order_by("round__number", "-position")
    )
    seen: set[int] = set()
    slowest_finishers: list[Result] = []
    for r in race_results:
        if r.round_id in seen:
            continue
        if not _is_classified_status(r.status):
            continue
        seen.add(r.round_id)
        slowest_finishers.append(r)

    return {
        "season_fastest_lap": fastest_lap,
        "fastest_lap_per_gp": by_round_fastest,
        "slowest_finishers": slowest_finishers,
    }
