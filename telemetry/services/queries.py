"""Pure-DB read helpers for the telemetry tables.

Mirrors the role of `analytics.services` for jolpica-derived tables: no
network calls, view-callable, cache the output upstream.
"""

from __future__ import annotations

from typing import Any

from competitors.models import Driver
from seasons.models import Round
from telemetry.models import Lap, Session, SessionStat, Stint


def season_top_speeds(year: int, limit: int = 20) -> list[dict[str, Any]]:
    """Top speed-trap reading per driver across a season's race sessions.

    Only race sessions are considered — practice and qualifying numbers are
    less interesting and would dominate the top of the table (slipstream,
    DRS-train laps).
    """
    rows = (
        SessionStat.objects.filter(
            session__round__season__year=year,
            session__kind=Session.RACE,
            top_speed_kmh__isnull=False,
        )
        .select_related("driver", "constructor", "session__round")
        .order_by("-top_speed_kmh")
    )

    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.driver_id in seen:
            continue
        seen.add(row.driver_id)
        out.append(
            {
                "driver": row.driver,
                "constructor": row.constructor,
                "round": row.session.round,
                "top_speed_kmh": row.top_speed_kmh,
            }
        )
        if len(out) >= limit:
            break
    return out


def season_has_telemetry(year: int) -> bool:
    return SessionStat.objects.filter(session__round__season__year=year).exists()


def race_session(rnd: Round) -> Session | None:
    return Session.objects.filter(round=rnd, kind=Session.RACE).first()


def race_lap_series(rnd: Round) -> list[dict[str, Any]]:
    """Per-driver lap timing for the race session of a given round.

    Returns one entry per driver: their stints + their lap times. View-side
    rendering picks the slowest valid lap to scale a simple horizontal bar.
    Drivers are ordered by their best lap (fastest first), so the lap-time
    chart reads top-down by pace.
    """
    session = race_session(rnd)
    if session is None:
        return []

    laps = (
        Lap.objects.filter(session=session, lap_time_seconds__isnull=False, is_deleted=False)
        .select_related("driver")
        .order_by("driver__family_name", "number")
    )
    stints = Stint.objects.filter(session=session).order_by("driver__family_name", "number")
    stints_by_driver: dict[int, list[Stint]] = {}
    for s in stints:
        stints_by_driver.setdefault(s.driver_id, []).append(s)

    by_driver: dict[int, dict[str, Any]] = {}
    for lap in laps:
        d = by_driver.setdefault(
            lap.driver_id,
            {
                "driver": lap.driver,
                "laps": [],
                "stints": stints_by_driver.get(lap.driver_id, []),
                "best_seconds": None,
            },
        )
        d["laps"].append(lap)
        if d["best_seconds"] is None or lap.lap_time_seconds < d["best_seconds"]:
            d["best_seconds"] = lap.lap_time_seconds

    drivers: list[dict[str, Any]] = list(by_driver.values())
    drivers.sort(key=lambda r: r["best_seconds"] or float("inf"))
    return drivers


def driver_lap_table(rnd: Round, driver: Driver) -> list[Lap]:
    """Sequential lap rows for one driver in the race session of a round."""
    session = race_session(rnd)
    if session is None:
        return []
    return list(Lap.objects.filter(session=session, driver=driver).order_by("number"))
