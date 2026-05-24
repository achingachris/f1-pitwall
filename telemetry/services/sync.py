"""Idempotent FastF1 → DB sync.

Mirrors the contract of `seasons.services.sync`: every writer is keyed on a
natural key, so re-running on unchanged data is a no-op. jolpica remains
truth for results and standings — telemetry only writes into the
`telemetry_*` tables.

The umbrella entry point is `sync_session(round, kind)`. It loads a single
FastF1 session once and writes:
- one Session row (the parent),
- one SessionStat row per driver (aggregates),
- one Lap row per driver lap,
- one Stint row per driver stint.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils.timezone import now

from competitors.models import Constructor, Driver
from seasons.models import Round
from telemetry.models import Lap, Session, SessionStat, Stint
from telemetry.services.fastf1_client import FastF1Unavailable, load_session

log = logging.getLogger(__name__)


def _seconds(value: Any) -> float | None:
    """Convert a FastF1 timing value (pandas Timedelta or NaT) to seconds."""
    if value is None:
        return None
    try:
        if value != value:  # NaT/NaN don't equal themselves
            return None
    except TypeError:
        pass
    total = getattr(value, "total_seconds", None)
    if callable(total):
        try:
            secs = total()
        except (TypeError, ValueError):
            return None
        if secs != secs:
            return None
        return float(secs)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _int_or_none(value: Any) -> int | None:
    f = _float_or_none(value)
    if f is None:
        return None
    return int(f)


def _bool_or_false(value: Any) -> bool:
    if value is None:
        return False
    try:
        if value != value:  # NaN
            return False
    except TypeError:
        pass
    return bool(value)


def _resolve_driver(code: str) -> Driver | None:
    """Find our Driver by the three-letter code FastF1 uses (matches jolpica).

    Returns None if we have no matching jolpica driver yet — telemetry must
    not invent driver rows. Run `sync_year` first.
    """
    if not code:
        return None
    return Driver.objects.filter(code=code).first()


def _resolve_constructor(team_name: str) -> Constructor | None:
    """Best-effort team-name → Constructor lookup.

    FastF1 reports the marketing name (e.g. "Red Bull Racing", "Kick Sauber"),
    jolpica stores a shorter form ("Red Bull", "Sauber"). We try, in order:
    exact match, first-token substring, last-token substring. Returns None
    on miss — the SessionStat row is still useful with just the driver
    attached.
    """
    if not team_name:
        return None
    exact = Constructor.objects.filter(name__iexact=team_name).first()
    if exact:
        return exact
    tokens = team_name.split()
    if not tokens:
        return None
    by_first = Constructor.objects.filter(name__icontains=tokens[0]).first()
    if by_first:
        return by_first
    if len(tokens) > 1:
        return Constructor.objects.filter(name__icontains=tokens[-1]).first()
    return None


def _aggregate_driver_laps(driver_laps) -> dict[str, Any]:
    """Compute the SessionStat field bundle from a driver's lap DataFrame."""
    fastest_lap = driver_laps.pick_fastest()
    fastest_seconds: float | None = None
    fastest_number: int | None = None
    fastest_compound = ""
    if fastest_lap is not None:
        fastest_seconds = _seconds(fastest_lap.get("LapTime"))
        fastest_number = _int_or_none(fastest_lap.get("LapNumber"))
        fastest_compound = str(fastest_lap.get("Compound") or "")

    top_speed: float | None = None
    if "SpeedST" in driver_laps.columns:
        try:
            top_speed = _float_or_none(driver_laps["SpeedST"].max())
        except ValueError:
            top_speed = None

    def _col_min(col: str) -> float | None:
        if col not in driver_laps.columns:
            return None
        try:
            return _seconds(driver_laps[col].min())
        except ValueError:
            return None

    s1 = _col_min("Sector1Time")
    s2 = _col_min("Sector2Time")
    s3 = _col_min("Sector3Time")
    theoretical = (s1 + s2 + s3) if (s1 and s2 and s3) else None

    return {
        "fastest_lap_seconds": fastest_seconds,
        "fastest_lap_number": fastest_number,
        "fastest_lap_compound": fastest_compound,
        "top_speed_kmh": top_speed,
        "sector1_best_seconds": s1,
        "sector2_best_seconds": s2,
        "sector3_best_seconds": s3,
        "theoretical_best_seconds": theoretical,
        "laps_completed": int(len(driver_laps)),
    }


def _iter_lap_rows(driver_laps) -> list[dict[str, Any]]:
    """Walk a driver's lap DataFrame and return one dict per lap, ordered by number."""
    cols = set(driver_laps.columns)
    out: list[dict[str, Any]] = []
    # ``driver_laps`` is a pandas-like; iterate via .iloc + .iterrows where
    # possible. Our fake test stub exposes plain row dicts on `_rows`; real
    # FastF1 laps are DataFrames with .itertuples(). Use a duck-typed access
    # path: prefer .to_dict('records') (pandas) then fall back to ._rows
    # (test fake).
    records_fn = getattr(driver_laps, "to_dict", None)
    if callable(records_fn):
        try:
            records = records_fn(orient="records")
        except TypeError:
            records = driver_laps._rows  # type: ignore[attr-defined]
    else:
        records = driver_laps._rows  # type: ignore[attr-defined]

    for r in records:
        lap_number = _int_or_none(r.get("LapNumber"))
        if lap_number is None:
            continue
        row: dict[str, Any] = {
            "number": lap_number,
            "lap_time_seconds": _seconds(r.get("LapTime")),
            "sector1_seconds": _seconds(r.get("Sector1Time")) if "Sector1Time" in cols else None,
            "sector2_seconds": _seconds(r.get("Sector2Time")) if "Sector2Time" in cols else None,
            "sector3_seconds": _seconds(r.get("Sector3Time")) if "Sector3Time" in cols else None,
            "compound": str(r.get("Compound") or ""),
            "tyre_life": _int_or_none(r.get("TyreLife")),
            "stint_number": _int_or_none(r.get("Stint")),
            "position": _int_or_none(r.get("Position")),
            "speed_st_kmh": _float_or_none(r.get("SpeedST")) if "SpeedST" in cols else None,
            "is_personal_best": _bool_or_false(r.get("IsPersonalBest")),
            "is_deleted": _bool_or_false(r.get("Deleted")) if "Deleted" in cols else False,
        }
        out.append(row)
    out.sort(key=lambda x: x["number"])
    return out


def _stints_from_laps(lap_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group lap rows into per-stint summaries.

    Uses the Stint column FastF1 sets on each lap. Falls back to a "stint 1"
    bucket if the column is missing/empty — we still want one Stint row so
    re-syncs delete cleanly on subsequent runs.
    """
    by_stint: dict[int, list[dict[str, Any]]] = {}
    for row in lap_rows:
        stint = row.get("stint_number") or 1
        by_stint.setdefault(stint, []).append(row)

    out: list[dict[str, Any]] = []
    for stint_number in sorted(by_stint):
        laps = by_stint[stint_number]
        first, last = laps[0], laps[-1]
        first_tyre_life = first.get("tyre_life")
        compound_age = (first_tyre_life - 1) if first_tyre_life else first_tyre_life
        out.append(
            {
                "number": stint_number,
                "compound": first.get("compound") or "",
                "lap_start": first["number"],
                "lap_end": last["number"],
                "laps_count": len(laps),
                "compound_age_at_start": compound_age,
            }
        )
    return out


def _iter_drivers(ff1_session) -> list[tuple[str, Any]]:
    """Return [(driver_code, lap_subset_df), ...] for the loaded session."""
    laps = ff1_session.laps
    if laps is None or len(laps) == 0 or "Driver" not in laps.columns:
        return []
    out: list[tuple[str, Any]] = []
    for code in laps["Driver"].dropna().unique():
        out.append((str(code), laps.pick_drivers(code)))
    return out


_LAP_UPDATE_FIELDS = [
    "lap_time_seconds",
    "sector1_seconds",
    "sector2_seconds",
    "sector3_seconds",
    "compound",
    "tyre_life",
    "stint_number",
    "position",
    "speed_st_kmh",
    "is_personal_best",
    "is_deleted",
]

_STINT_UPDATE_FIELDS = [
    "compound",
    "lap_start",
    "lap_end",
    "laps_count",
    "compound_age_at_start",
]


@transaction.atomic
def sync_session(rnd: Round, kind: str) -> dict[str, int]:
    """Pull one (round, kind) session from FastF1 and upsert all telemetry tables.

    Writes a Session row plus SessionStat, Lap, and Stint rows for every
    driver we can resolve. Returns row counts for each table plus stale rows
    deleted: ``{"stats": N, "laps": N, "stints": N, "deleted": N}``.

    Raises FastF1Unavailable when the season pre-dates FastF1 coverage.
    """
    if kind not in Session.FASTF1_CODES:
        raise ValueError(f"Unknown session kind: {kind!r}")

    year = rnd.season.year
    code = Session.FASTF1_CODES[kind]

    ff1 = load_session(year, rnd.number, code)

    session_obj, _ = Session.objects.update_or_create(
        round=rnd, kind=kind, defaults={"last_synced": now()}
    )

    stats_written = laps_written = stints_written = deleted = 0
    lap_batch: list[Lap] = []
    stint_batch: list[Stint] = []
    seen_driver_ids: set[int] = set()
    lap_numbers_by_driver: dict[int, set[int]] = {}
    stint_numbers_by_driver: dict[int, set[int]] = {}

    for driver_code, driver_laps in _iter_drivers(ff1):
        driver = _resolve_driver(driver_code)
        if driver is None:
            log.warning(
                "telemetry: skipping %s %s — no Driver row for code %s (run sync_year first)",
                rnd,
                kind,
                driver_code,
            )
            continue

        seen_driver_ids.add(driver.id)

        team_name = ""
        if "Team" in driver_laps.columns and len(driver_laps):
            team_name = str(driver_laps["Team"].iloc[0] or "")
        constructor = _resolve_constructor(team_name)

        aggregates = _aggregate_driver_laps(driver_laps)
        SessionStat.objects.update_or_create(
            session=session_obj,
            driver=driver,
            defaults={"constructor": constructor, **aggregates},
        )
        stats_written += 1

        lap_rows = _iter_lap_rows(driver_laps)
        lap_numbers_by_driver[driver.id] = {row["number"] for row in lap_rows}
        for row in lap_rows:
            lap_batch.append(Lap(session=session_obj, driver=driver, **row))

        stint_rows = _stints_from_laps(lap_rows)
        stint_numbers_by_driver[driver.id] = {row["number"] for row in stint_rows}
        for srow in stint_rows:
            stint_batch.append(Stint(session=session_obj, driver=driver, **srow))

    stale_stats = SessionStat.objects.filter(session=session_obj).exclude(
        driver_id__in=seen_driver_ids
    )
    deleted += stale_stats.delete()[0]
    stale_laps = Lap.objects.filter(session=session_obj).exclude(driver_id__in=seen_driver_ids)
    deleted += stale_laps.delete()[0]
    stale_stints = Stint.objects.filter(session=session_obj).exclude(driver_id__in=seen_driver_ids)
    deleted += stale_stints.delete()[0]

    for driver_id, lap_numbers in lap_numbers_by_driver.items():
        deleted += (
            Lap.objects.filter(session=session_obj, driver_id=driver_id)
            .exclude(number__in=lap_numbers)
            .delete()[0]
        )
    for driver_id, stint_numbers in stint_numbers_by_driver.items():
        deleted += (
            Stint.objects.filter(session=session_obj, driver_id=driver_id)
            .exclude(number__in=stint_numbers)
            .delete()[0]
        )

    if lap_batch:
        Lap.objects.bulk_create(
            lap_batch,
            update_conflicts=True,
            unique_fields=["session", "driver", "number"],
            update_fields=_LAP_UPDATE_FIELDS,
        )
        laps_written = len(lap_batch)

    if stint_batch:
        Stint.objects.bulk_create(
            stint_batch,
            update_conflicts=True,
            unique_fields=["session", "driver", "number"],
            update_fields=_STINT_UPDATE_FIELDS,
        )
        stints_written = len(stint_batch)

    log.info(
        "telemetry: %s %s — stats=%d laps=%d stints=%d deleted=%d",
        rnd,
        kind,
        stats_written,
        laps_written,
        stints_written,
        deleted,
    )
    return {
        "stats": stats_written,
        "laps": laps_written,
        "stints": stints_written,
        "deleted": deleted,
    }


def sync_session_safe(rnd: Round, kind: str) -> dict[str, int]:
    """Like sync_session but swallows FastF1Unavailable.

    Returns zero-filled counts when the season pre-dates FastF1 coverage.
    """
    try:
        return sync_session(rnd, kind)
    except FastF1Unavailable as e:
        log.info("telemetry: %s %s skipped — %s", rnd, kind, e)
        return {"stats": 0, "laps": 0, "stints": 0, "deleted": 0}
