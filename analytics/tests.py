from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase

from analytics import services
from competitors.models import Constructor, Driver
from results.models import Result, Standing
from seasons.models import Circuit, Round, Season


def _make_season(year: int, rounds: int = 4, future: int = 2):
    """Build `rounds` past rounds and `future` upcoming rounds."""
    season = Season.objects.create(year=year)
    circuit = Circuit.objects.create(ref="c1", name="Test Circuit")
    today = date.today()
    rs = []
    for i in range(1, rounds + 1):
        rs.append(
            Round.objects.create(
                season=season,
                number=i,
                name=f"GP {i}",
                circuit=circuit,
                date=today - timedelta(days=(rounds - i + 1) * 14),
            )
        )
    for j in range(1, future + 1):
        Round.objects.create(
            season=season,
            number=rounds + j,
            name=f"GP {rounds + j}",
            circuit=circuit,
            date=today + timedelta(days=j * 14),
        )
    return season, rs


class ContendersTests(TestCase):
    def test_leader_and_in_reach_trailer_are_contenders_exact_boundary(self):
        _, rounds = _make_season(2025, rounds=4, future=2)
        c = Constructor.objects.create(ref="x", name="X")
        leader = Driver.objects.create(ref="l", given_name="Leader", family_name="L")
        trailer = Driver.objects.create(ref="t", given_name="Trailer", family_name="T")
        beyond = Driver.objects.create(ref="b", given_name="Beyond", family_name="B")

        latest = rounds[-1]
        # Per-race cap with 2 races left (rounds 5 & 6), no sprints: 2 * 25 = 50.
        Standing.objects.create(round=latest, kind="driver", driver=leader, position=1, points=100)
        Standing.objects.create(round=latest, kind="driver", driver=trailer, position=2, points=50)
        Standing.objects.create(round=latest, kind="driver", driver=beyond, position=3, points=49)

        labels = {c.label for c in services.contenders(2025, constructor=False)}
        self.assertIn("Leader L", labels)
        self.assertIn("Trailer T", labels)
        self.assertNotIn("Beyond B", labels)

    def test_driver_standing_snapshot_is_unique_despite_null_constructor(self):
        _, rounds = _make_season(2025, rounds=1, future=0)
        driver = Driver.objects.create(ref="l", given_name="Leader", family_name="L")

        Standing.objects.create(
            round=rounds[0], kind="driver", driver=driver, position=1, points=25
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Standing.objects.create(
                round=rounds[0],
                kind="driver",
                driver=driver,
                position=1,
                points=25,
            )


class StandingChangeTests(TestCase):
    def test_hidden_for_past_seasons(self):
        _, rounds = _make_season(2020, rounds=2, future=0)
        driver = Driver.objects.create(ref="d", given_name="A", family_name="B")
        for rnd in rounds:
            Standing.objects.create(
                round=rnd, kind="driver", driver=driver, position=1, points=10
            )
        self.assertIsNone(services.standing_changes(2020, kind="driver"))

    def test_gained_positions_and_points_on_current_season(self):
        year = date.today().year
        season = Season.objects.create(year=year)
        circuit = Circuit.objects.create(ref="chg", name="Change Circuit")
        r1 = Round.objects.create(
            season=season, number=1, name="GP1", circuit=circuit, date=date.today()
        )
        r2 = Round.objects.create(
            season=season, number=2, name="GP2", circuit=circuit, date=date.today()
        )
        constructor = Constructor.objects.create(ref="c", name="C")
        driver = Driver.objects.create(ref="mv", given_name="Mover", family_name="Up")
        Standing.objects.create(round=r1, kind="driver", driver=driver, position=3, points=10)
        Standing.objects.create(round=r2, kind="driver", driver=driver, position=1, points=35)
        Result.objects.create(
            round=r2,
            driver=driver,
            constructor=constructor,
            session="race",
            position=1,
            position_text="1",
            points=25,
        )

        changes = services.standing_changes(year, kind="driver")
        self.assertIsNotNone(changes)
        change = changes[driver.id]
        self.assertEqual(change.position_delta, 2)
        self.assertEqual(change.points_delta, 25)
        self.assertEqual(change.positions_up, 2)
        self.assertEqual(change.positions_down, 0)

    def test_same_position_shows_zero_delta(self):
        year = date.today().year
        season = Season.objects.create(year=year)
        circuit = Circuit.objects.create(ref="flat", name="Flat Circuit")
        r1 = Round.objects.create(
            season=season, number=1, name="GP1", circuit=circuit, date=date.today()
        )
        r2 = Round.objects.create(
            season=season, number=2, name="GP2", circuit=circuit, date=date.today()
        )
        constructor = Constructor.objects.create(ref="c2", name="C2")
        driver = Driver.objects.create(ref="flat", given_name="Flat", family_name="P")
        Standing.objects.create(round=r1, kind="driver", driver=driver, position=2, points=20)
        Standing.objects.create(round=r2, kind="driver", driver=driver, position=2, points=32)
        Result.objects.create(
            round=r2,
            driver=driver,
            constructor=constructor,
            session="sprint",
            position=2,
            position_text="2",
            points=8,
        )

        change = services.standing_changes(year, kind="driver")[driver.id]
        self.assertEqual(change.position_delta, 0)
        self.assertEqual(change.points_delta, 12)


class MostImprovedTests(TestCase):
    def test_late_bloomer_wins_delta(self):
        _, rounds = _make_season(2025, rounds=4, future=0)
        c = Constructor.objects.create(ref="x", name="X")
        slump = Driver.objects.create(ref="s", given_name="Slump", family_name="S")
        bloom = Driver.objects.create(ref="b", given_name="Bloom", family_name="B")

        # Slump: 25, 25, 0, 0 — first half avg 25, second half avg 0, Δ = -25
        # Bloom: 0,  0, 25, 25 — Δ = +25
        for r, (s_pts, b_pts) in zip(rounds, [(25, 0), (25, 0), (0, 25), (0, 25)]):
            Result.objects.create(
                round=r,
                driver=slump,
                constructor=c,
                session="race",
                position_text="1",
                points=s_pts,
            )
            Result.objects.create(
                round=r,
                driver=bloom,
                constructor=c,
                session="race",
                position_text="2",
                points=b_pts,
            )

        winner = services.most_improved(2025, constructor=False)
        self.assertIsNotNone(winner)
        self.assertEqual(winner["label"], "Bloom B")
        self.assertAlmostEqual(winner["delta"], 25.0)


class FunStatsTests(TestCase):
    def test_slowest_classified_finisher_includes_lapped_cars(self):
        _, rounds = _make_season(2025, rounds=1, future=0)
        constructor = Constructor.objects.create(ref="x", name="X")
        lead_lap = Driver.objects.create(ref="f", given_name="Finished", family_name="F")
        lapped = Driver.objects.create(ref="l", given_name="Lapped", family_name="L")
        retired = Driver.objects.create(ref="r", given_name="Retired", family_name="R")

        Result.objects.create(
            round=rounds[0],
            driver=lead_lap,
            constructor=constructor,
            session="race",
            position=8,
            position_text="8",
            status="Finished",
        )
        Result.objects.create(
            round=rounds[0],
            driver=lapped,
            constructor=constructor,
            session="race",
            position=9,
            position_text="9",
            status="+1 Lap",
        )
        Result.objects.create(
            round=rounds[0],
            driver=retired,
            constructor=constructor,
            session="race",
            position=10,
            position_text="10",
            status="Engine",
        )

        data = services.funstats(2025)

        self.assertEqual(data["slowest_finishers"], [Result.objects.get(driver=lapped)])
