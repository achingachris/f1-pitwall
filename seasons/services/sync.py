"""Idempotent sync layer between jolpica and our database.

Every writer uses `update_or_create` keyed on natural keys so re-running on
unchanged data is a no-op.
"""

import logging
from datetime import date as _date
from datetime import datetime
from typing import Any

from django.db import transaction

from competitors.models import Constructor, Driver
from results.models import Qualifying, Result, Standing
from seasons.models import Circuit, Round, Season
from seasons.services.jolpica import paginate

log = logging.getLogger(__name__)


def _to_date(s: str) -> _date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _session_dt(session: dict[str, Any] | None) -> datetime | None:
    """Combine a jolpica session block's date+time into a datetime, or None.

    Session blocks look like {"date": "2026-03-08", "time": "15:00:00Z"}.
    Missing/malformed → None.
    """
    if not session:
        return None
    date_str = session.get("date")
    time_str = session.get("time") or "00:00:00Z"
    if not date_str:
        return None
    try:
        # Trim trailing Z (Python's %z doesn't accept bare Z in 3.11+; format
        # with explicit timezone instead).
        iso = f"{date_str}T{time_str.rstrip('Z')}+00:00"
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _as_int(value: Any, default: int = 0) -> int:
    """Parse an Ergast field that should be an int but may be missing or non-numeric."""
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _circuit(payload: dict[str, Any]) -> Circuit:
    obj, _ = Circuit.objects.update_or_create(
        ref=payload["circuitId"],
        defaults={
            "name": payload["circuitName"],
            "locality": payload.get("Location", {}).get("locality", ""),
            "country": payload.get("Location", {}).get("country", ""),
        },
    )
    return obj


def _driver(payload: dict[str, Any]) -> Driver:
    dob_raw = payload.get("dateOfBirth")
    defaults = {
        "code": payload.get("code", ""),
        "given_name": payload["givenName"],
        "family_name": payload["familyName"],
        "nationality": payload.get("nationality", ""),
        "url": payload.get("url", ""),
    }
    if dob_raw:
        try:
            defaults["date_of_birth"] = _to_date(dob_raw)
        except ValueError:
            pass
    obj, _ = Driver.objects.update_or_create(ref=payload["driverId"], defaults=defaults)
    return obj


def _constructor(payload: dict[str, Any]) -> Constructor:
    obj, _ = Constructor.objects.update_or_create(
        ref=payload["constructorId"],
        defaults={
            "name": payload["name"],
            "nationality": payload.get("nationality", ""),
            "url": payload.get("url", ""),
        },
    )
    return obj


_SPRINT_KEYS = ("Sprint", "SprintQualifying", "SprintShootout")


def _is_sprint_weekend(race: dict[str, Any]) -> bool:
    """A 2021+ jolpica race payload tags sprint weekends with one of these keys."""
    return any(k in race for k in _SPRINT_KEYS)


@transaction.atomic
def sync_schedule(year: int) -> Season:
    season, _ = Season.objects.update_or_create(year=year)

    # Belt-and-suspenders: the /sprint endpoint returns historical sprint *results*
    # (so it confirms past sprint weekends), but it does not list upcoming ones.
    # We rely primarily on the per-race Sprint/SprintQualifying flag on /races.
    has_sprint_by_round: dict[int, bool] = {}
    for page in paginate(f"{year}/sprint"):
        for race in page.get("RaceTable", {}).get("Races", []):
            has_sprint_by_round[int(race["round"])] = True

    for page in paginate(f"{year}/races"):
        for race in page.get("RaceTable", {}).get("Races", []):
            number = int(race["round"])
            circuit = _circuit(race["Circuit"])
            has_sprint = _is_sprint_weekend(race) or has_sprint_by_round.get(number, False)
            # The race itself has top-level "date" + "time"; treat as a session.
            race_block = {"date": race.get("date"), "time": race.get("time")}
            Round.objects.update_or_create(
                season=season,
                number=number,
                defaults={
                    "name": race["raceName"],
                    "circuit": circuit,
                    "date": _to_date(race["date"]),
                    "has_sprint": has_sprint,
                    "fp1_at": _session_dt(race.get("FirstPractice")),
                    "fp2_at": _session_dt(race.get("SecondPractice")),
                    "fp3_at": _session_dt(race.get("ThirdPractice")),
                    "qualifying_at": _session_dt(race.get("Qualifying")),
                    "sprint_qualifying_at": _session_dt(
                        race.get("SprintQualifying") or race.get("SprintShootout")
                    ),
                    "sprint_at": _session_dt(race.get("Sprint")),
                    "race_at": _session_dt(race_block),
                },
            )
    return season


def sync_results(rnd: Round, session: str = "race") -> int:
    path = (
        f"{rnd.season.year}/{rnd.number}/results"
        if session == "race"
        else f"{rnd.season.year}/{rnd.number}/sprint"
    )
    written = 0
    for page in paginate(path):
        races = page.get("RaceTable", {}).get("Races", [])
        for race in races:
            key = "Results" if session == "race" else "SprintResults"
            for row in race.get(key, []):
                driver = _driver(row["Driver"])
                constructor = _constructor(row["Constructor"])
                fl = row.get("FastestLap") or {}
                fl_time = (fl.get("Time") or {}).get("time", "")
                fl_speed = (fl.get("AverageSpeed") or {}).get("speed")
                position_raw = row.get("position")
                Result.objects.update_or_create(
                    round=rnd,
                    driver=driver,
                    session=session,
                    defaults={
                        "constructor": constructor,
                        "position": _as_int(position_raw) if position_raw else None,
                        "position_text": row.get("positionText", ""),
                        "points": _as_float(row.get("points")),
                        "grid": _as_int(row.get("grid")),
                        "status": row.get("status", ""),
                        "fastest_lap_rank": (_as_int(fl.get("rank")) if fl.get("rank") else None),
                        "fastest_lap_time": fl_time,
                        "fastest_lap_speed_kmh": (_as_float(fl_speed) if fl_speed else None),
                    },
                )
                written += 1
    return written


def sync_qualifying(rnd: Round) -> int:
    path = f"{rnd.season.year}/{rnd.number}/qualifying"
    written = 0
    for page in paginate(path):
        for race in page.get("RaceTable", {}).get("Races", []):
            for row in race.get("QualifyingResults", []):
                Qualifying.objects.update_or_create(
                    round=rnd,
                    driver=_driver(row["Driver"]),
                    defaults={
                        "constructor": _constructor(row["Constructor"]),
                        "position": _as_int(row.get("position")),
                        "q1": row.get("Q1", ""),
                        "q2": row.get("Q2", ""),
                        "q3": row.get("Q3", ""),
                    },
                )
                written += 1
    return written


def sync_standings(year: int) -> int:
    """Snapshot driver + constructor standings AFTER the most recent completed round."""
    written = 0
    season = Season.objects.get(year=year)

    for page in paginate(f"{year}/driverstandings"):
        lists = page.get("StandingsTable", {}).get("StandingsLists", [])
        for sl in lists:
            number = int(sl["round"])
            rnd = Round.objects.filter(season=season, number=number).first()
            if not rnd:
                continue
            for row in sl.get("DriverStandings", []):
                driver = _driver(row["Driver"])
                Standing.objects.update_or_create(
                    round=rnd,
                    kind="driver",
                    driver=driver,
                    constructor=None,
                    defaults={
                        "position": _as_int(row.get("position")),
                        "points": _as_float(row.get("points")),
                        "wins": _as_int(row.get("wins")),
                    },
                )
                written += 1

    for page in paginate(f"{year}/constructorstandings"):
        lists = page.get("StandingsTable", {}).get("StandingsLists", [])
        for sl in lists:
            number = int(sl["round"])
            rnd = Round.objects.filter(season=season, number=number).first()
            if not rnd:
                continue
            for row in sl.get("ConstructorStandings", []):
                constructor = _constructor(row["Constructor"])
                Standing.objects.update_or_create(
                    round=rnd,
                    kind="constructor",
                    driver=None,
                    constructor=constructor,
                    defaults={
                        "position": _as_int(row.get("position")),
                        "points": _as_float(row.get("points")),
                        "wins": _as_int(row.get("wins")),
                    },
                )
                written += 1
    return written


def unsynced_completed_rounds(year: int):
    """Rounds whose date is past and which have no race Result rows yet."""
    return Round.objects.filter(season__year=year, date__lt=_date.today()).exclude(
        results__session="race"
    )
