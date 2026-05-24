"""Tests for the telemetry v2 layer.

The FastF1 client is mocked so these tests run without the heavy
pandas/fastf1 stack and without ever hitting the F1 live-timing API.
"""

from datetime import date, timedelta
from unittest import mock

from django.test import TestCase

from competitors.models import Constructor, Driver
from seasons.models import Circuit, Round, Season
from telemetry.models import Lap, Session, SessionStat, Stint
from telemetry.services import sync as sync_module
from telemetry.services.fastf1_client import FastF1Unavailable, load_session


class _FakeSeries:
    """Just enough of a pandas Series to satisfy telemetry/services/sync.py."""

    def __init__(self, values):
        self._values = list(values)

    def max(self):
        cleaned = [v for v in self._values if v is not None]
        return max(cleaned) if cleaned else None

    def min(self):
        cleaned = [v for v in self._values if v is not None]
        return min(cleaned) if cleaned else None

    def dropna(self):
        return _FakeSeries([v for v in self._values if v is not None])

    def unique(self):
        seen, out = set(), []
        for v in self._values:
            if v in seen:
                continue
            seen.add(v)
            out.append(v)
        return out

    @property
    def iloc(self):
        return self._values

    def __len__(self):
        return len(self._values)


class _FakeLaps:
    """Minimal stand-in for a FastF1 laps DataFrame."""

    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.columns = sorted({k for r in rows for k in r.keys()})

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, col):
        return _FakeSeries([r.get(col) for r in self._rows])

    def pick_drivers(self, code):
        return _FakeLaps([r for r in self._rows if r.get("Driver") == code])

    def pick_fastest(self):
        with_time = [r for r in self._rows if r.get("LapTime") is not None]
        if not with_time:
            return None
        fastest = min(with_time, key=lambda r: r["LapTime"].total_seconds())
        return _FakeRow(fastest)


class _FakeRow:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeSession:
    def __init__(self, laps):
        self.laps = laps


def _lap(driver: str, team: str, number: int, time_s: float, **extra) -> dict:
    base = {
        "Driver": driver,
        "Team": team,
        "LapNumber": number,
        "LapTime": timedelta(seconds=time_s),
        "Compound": extra.get("Compound", "SOFT"),
        "TyreLife": extra.get("TyreLife", number),
        "Stint": extra.get("Stint", 1),
        "Position": extra.get("Position", 1),
        "SpeedST": extra.get("SpeedST", 320.0),
        "Sector1Time": timedelta(seconds=extra.get("S1", time_s / 3)),
        "Sector2Time": timedelta(seconds=extra.get("S2", time_s / 3)),
        "Sector3Time": timedelta(seconds=extra.get("S3", time_s / 3)),
        "IsPersonalBest": extra.get("IsPersonalBest", False),
        "Deleted": extra.get("Deleted", False),
    }
    return base


class FastF1ClientGuardTests(TestCase):
    def test_load_session_rejects_pre_2018(self):
        with self.assertRaises(FastF1Unavailable):
            load_session(2017, 1, "R")

    def test_sprint_qualifying_uses_current_fastf1_code(self):
        self.assertEqual(Session.FASTF1_CODES[Session.SPRINT_QUALIFYING], "SQ")


class SyncSessionTests(TestCase):
    def setUp(self):
        season = Season.objects.create(year=2024)
        circuit = Circuit.objects.create(ref="bahrain", name="Bahrain")
        self.round = Round.objects.create(
            season=season,
            number=1,
            name="Bahrain GP",
            circuit=circuit,
            date=date(2024, 3, 2),
        )
        self.ver = Driver.objects.create(
            ref="max_verstappen", code="VER", given_name="Max", family_name="Verstappen"
        )
        self.ham = Driver.objects.create(
            ref="hamilton", code="HAM", given_name="Lewis", family_name="Hamilton"
        )
        self.redbull = Constructor.objects.create(ref="red_bull", name="Red Bull")
        self.mercedes = Constructor.objects.create(ref="mercedes", name="Mercedes")

    def _fake_session(self):
        rows = [
            _lap("VER", "Red Bull Racing", 1, 90.5, Stint=1, TyreLife=1, IsPersonalBest=True),
            _lap("VER", "Red Bull Racing", 2, 90.2, Stint=1, TyreLife=2, IsPersonalBest=True),
            _lap(
                "VER",
                "Red Bull Racing",
                3,
                90.1,
                Stint=1,
                TyreLife=3,
                SpeedST=332.4,
                IsPersonalBest=True,
            ),
            _lap(
                "VER",
                "Red Bull Racing",
                4,
                91.0,
                Stint=2,
                Compound="MEDIUM",
                TyreLife=1,
            ),
            _lap(
                "VER",
                "Red Bull Racing",
                5,
                91.5,
                Stint=2,
                Compound="MEDIUM",
                TyreLife=2,
            ),
            _lap("HAM", "Mercedes", 1, 92.2, Stint=1, TyreLife=1, Compound="MEDIUM"),
            _lap(
                "HAM",
                "Mercedes",
                2,
                95.0,
                Stint=1,
                TyreLife=2,
                Compound="MEDIUM",
                Deleted=True,
            ),
        ]
        return _FakeSession(_FakeLaps(rows))

    def test_sync_session_writes_stats_laps_and_stints(self):
        with mock.patch.object(sync_module, "load_session", return_value=self._fake_session()):
            counts = sync_module.sync_session(self.round, Session.RACE)

        self.assertEqual(counts["stats"], 2)
        self.assertEqual(counts["laps"], 7)
        self.assertEqual(counts["stints"], 3)  # VER stint 1, VER stint 2, HAM stint 1

        ver_stat = SessionStat.objects.get(driver=self.ver)
        self.assertAlmostEqual(ver_stat.fastest_lap_seconds, 90.1, places=2)
        self.assertEqual(ver_stat.constructor, self.redbull)

        ver_laps = Lap.objects.filter(driver=self.ver).order_by("number")
        self.assertEqual(ver_laps.count(), 5)
        first = ver_laps.first()
        self.assertEqual(first.number, 1)
        self.assertEqual(first.compound, "SOFT")
        self.assertTrue(first.is_personal_best)

        ham_deleted = Lap.objects.get(driver=self.ham, number=2)
        self.assertTrue(ham_deleted.is_deleted)

        ver_stints = list(Stint.objects.filter(driver=self.ver).order_by("number"))
        self.assertEqual(len(ver_stints), 2)
        self.assertEqual(ver_stints[0].compound, "SOFT")
        self.assertEqual(ver_stints[0].lap_start, 1)
        self.assertEqual(ver_stints[0].lap_end, 3)
        self.assertEqual(ver_stints[0].laps_count, 3)
        self.assertEqual(ver_stints[0].compound_age_at_start, 0)
        self.assertEqual(ver_stints[1].compound, "MEDIUM")
        self.assertEqual(ver_stints[1].laps_count, 2)

    def test_sync_session_is_idempotent(self):
        with mock.patch.object(sync_module, "load_session", return_value=self._fake_session()):
            sync_module.sync_session(self.round, Session.RACE)
            sync_module.sync_session(self.round, Session.RACE)

        self.assertEqual(Session.objects.count(), 1)
        self.assertEqual(SessionStat.objects.count(), 2)
        self.assertEqual(Lap.objects.count(), 7)
        self.assertEqual(Stint.objects.count(), 3)

    def test_sync_session_prunes_stale_rows_on_corrected_resync(self):
        with mock.patch.object(sync_module, "load_session", return_value=self._fake_session()):
            sync_module.sync_session(self.round, Session.RACE)

        corrected = _FakeSession(
            _FakeLaps(
                [
                    _lap(
                        "VER",
                        "Red Bull Racing",
                        1,
                        90.5,
                        Stint=1,
                        TyreLife=1,
                        IsPersonalBest=True,
                    ),
                    _lap(
                        "VER",
                        "Red Bull Racing",
                        2,
                        90.2,
                        Stint=1,
                        TyreLife=2,
                        IsPersonalBest=True,
                    ),
                ]
            )
        )
        with mock.patch.object(sync_module, "load_session", return_value=corrected):
            counts = sync_module.sync_session(self.round, Session.RACE)

        self.assertGreater(counts["deleted"], 0)
        self.assertEqual(SessionStat.objects.count(), 1)
        self.assertEqual(SessionStat.objects.get().driver, self.ver)
        self.assertEqual(
            list(Lap.objects.values_list("driver__code", "number")), [("VER", 1), ("VER", 2)]
        )
        self.assertEqual(Stint.objects.count(), 1)
        self.assertEqual(Stint.objects.get().driver, self.ver)

    def test_sync_session_skips_unknown_driver_codes(self):
        rows = [_lap("ZZZ", "Unknown", 1, 95.0)]
        fake = _FakeSession(_FakeLaps(rows))
        with mock.patch.object(sync_module, "load_session", return_value=fake):
            counts = sync_module.sync_session(self.round, Session.RACE)
        self.assertEqual(counts["stats"], 0)
        self.assertEqual(counts["laps"], 0)
        self.assertEqual(counts["stints"], 0)
        # Session row still gets created so re-runs are stable.
        self.assertTrue(Session.objects.filter(round=self.round, kind=Session.RACE).exists())

    def test_sync_session_safe_swallows_pre_2018(self):
        old_season = Season.objects.create(year=2010)
        old_round = Round.objects.create(
            season=old_season,
            number=1,
            name="Bahrain GP",
            circuit=self.round.circuit,
            date=date(2010, 3, 14),
        )
        counts = sync_module.sync_session_safe(old_round, Session.RACE)
        self.assertEqual(counts, {"stats": 0, "laps": 0, "stints": 0, "deleted": 0})
        self.assertFalse(SessionStat.objects.exists())
        self.assertFalse(Lap.objects.exists())

    def test_sync_session_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            sync_module.sync_session(self.round, "bogus")


class QueryTests(TestCase):
    def setUp(self):
        season = Season.objects.create(year=2024)
        circuit = Circuit.objects.create(ref="bahrain", name="Bahrain")
        self.round = Round.objects.create(
            season=season,
            number=1,
            name="Bahrain GP",
            circuit=circuit,
            date=date(2024, 3, 2),
        )
        self.ver = Driver.objects.create(
            ref="max_verstappen", code="VER", given_name="Max", family_name="Verstappen"
        )
        self.ham = Driver.objects.create(
            ref="hamilton", code="HAM", given_name="Lewis", family_name="Hamilton"
        )
        self.session = Session.objects.create(round=self.round, kind=Session.RACE)
        Lap.objects.bulk_create(
            [
                Lap(session=self.session, driver=self.ver, number=1, lap_time_seconds=90.5),
                Lap(session=self.session, driver=self.ver, number=2, lap_time_seconds=90.1),
                Lap(session=self.session, driver=self.ham, number=1, lap_time_seconds=92.2),
            ]
        )

    def test_race_lap_series_sorts_by_best_lap(self):
        from telemetry.services import queries

        out = queries.race_lap_series(self.round)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["driver"], self.ver)
        self.assertAlmostEqual(out[0]["best_seconds"], 90.1, places=2)
        self.assertEqual(out[1]["driver"], self.ham)

    def test_race_lap_series_skips_deleted_and_null_laps(self):
        from telemetry.services import queries

        Lap.objects.create(session=self.session, driver=self.ver, number=3, lap_time_seconds=None)
        Lap.objects.create(
            session=self.session,
            driver=self.ver,
            number=4,
            lap_time_seconds=89.0,
            is_deleted=True,
        )
        out = queries.race_lap_series(self.round)
        ver_row = next(r for r in out if r["driver"] == self.ver)
        # Best stays 90.1 — deleted lap was faster but excluded; null lap excluded.
        self.assertAlmostEqual(ver_row["best_seconds"], 90.1, places=2)
        self.assertEqual(len(ver_row["laps"]), 2)


class HelperTests(TestCase):
    def test_seconds_handles_none_and_nan(self):
        self.assertIsNone(sync_module._seconds(None))
        self.assertIsNone(sync_module._seconds(float("nan")))
        self.assertAlmostEqual(sync_module._seconds(timedelta(seconds=12.5)), 12.5)


class SyncRecentTelemetryTaskTests(TestCase):
    """Cover the scheduled telemetry fan-out: which (round, kind) pairs end
    up queued for the latest N completed rounds."""

    def _make_round(self, year, number, *, race_days_ago, has_sprint=False):
        from django.utils.timezone import now

        season, _ = Season.objects.get_or_create(year=year)
        circuit, _ = Circuit.objects.get_or_create(
            ref=f"c{number}", defaults={"name": f"C{number}"}
        )
        return Round.objects.create(
            season=season,
            number=number,
            name=f"R{number}",
            circuit=circuit,
            date=date.today() - timedelta(days=race_days_ago),
            race_at=now() - timedelta(days=race_days_ago),
            has_sprint=has_sprint,
        )

    def test_skips_pre_2018_year(self):
        from telemetry import tasks

        with (
            mock.patch("telemetry.tasks.date") as fake_date,
            mock.patch("telemetry.tasks.sync_session_task.delay") as delay,
        ):
            fake_date.today.return_value = date(2017, 6, 1)
            result = tasks.sync_recent_telemetry()
        delay.assert_not_called()
        self.assertIn("skipped", result)

    def test_fans_out_per_session_for_latest_rounds(self):
        from telemetry import tasks

        year = date.today().year
        oldest = self._make_round(year, 1, race_days_ago=30)
        middle = self._make_round(year, 2, race_days_ago=14, has_sprint=True)
        latest = self._make_round(year, 3, race_days_ago=2)

        with mock.patch("telemetry.tasks.sync_session_task.delay") as delay:
            result = tasks.sync_recent_telemetry(rounds_back=2)

        queued = {(c.args[1], c.args[2]) for c in delay.call_args_list}
        self.assertEqual(
            queued,
            {
                (latest.number, "race"),
                (latest.number, "q"),
                (middle.number, "race"),
                (middle.number, "q"),
                (middle.number, "sprint"),
                (middle.number, "sq"),
            },
        )
        self.assertNotIn(oldest.number, {c.args[1] for c in delay.call_args_list})
        self.assertIn("queued 6", result)

    def test_skips_future_rounds(self):
        from telemetry import tasks

        year = date.today().year
        self._make_round(year, 1, race_days_ago=-7)

        with mock.patch("telemetry.tasks.sync_session_task.delay") as delay:
            result = tasks.sync_recent_telemetry()
        delay.assert_not_called()
        self.assertIn("queued 0", result)


class BackfillTelemetryTaskTests(TestCase):
    def test_walks_every_completed_round_across_years_newest_first(self):
        from django.utils.timezone import now

        from telemetry import tasks

        # Two years; one round per year. Pre-2018 round is filtered out.
        for year, race_days_ago in [(2017, 30), (2018, 60), (2019, 90)]:
            season, _ = Season.objects.get_or_create(year=year)
            circuit, _ = Circuit.objects.get_or_create(
                ref=f"c{year}", defaults={"name": f"C{year}"}
            )
            Round.objects.create(
                season=season,
                number=1,
                name=f"R{year}",
                circuit=circuit,
                date=date.today() - timedelta(days=race_days_ago),
                race_at=now() - timedelta(days=race_days_ago),
            )

        with mock.patch("telemetry.tasks.sync_session_task.delay") as delay:
            result = tasks.backfill_telemetry(start_year=2018, end_year=2019)

        years_queued = [c.args[0] for c in delay.call_args_list]
        self.assertNotIn(2017, years_queued)
        # Newest year fires first — important so the freshest data lands
        # early if the queue gets interrupted.
        self.assertEqual(years_queued[0], 2019)
        # 2 years × 1 round × 2 kinds (race + q, no sprint) = 4 tasks.
        self.assertEqual(len(years_queued), 4)
        self.assertIn("queued 4", result)
