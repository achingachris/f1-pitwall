from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

import responses

from seasons.services import jolpica


@override_settings(JOLPICA_BASE="https://api.jolpi.ca/ergast/f1", JOLPICA_USER_AGENT="t/1")
class JolpicaClientTests(TestCase):
    def setUp(self):
        jolpica._RECENT_CALLS.clear()

    @responses.activate
    def test_pagination_follows_offset_until_total(self):
        responses.add(
            responses.GET,
            "https://api.jolpi.ca/ergast/f1/2025/races.json",
            json={
                "MRData": {
                    "total": "3",
                    "limit": "2",
                    "offset": "0",
                    "RaceTable": {"Races": [{"round": "1"}, {"round": "2"}]},
                }
            },
        )
        responses.add(
            responses.GET,
            "https://api.jolpi.ca/ergast/f1/2025/races.json",
            json={
                "MRData": {
                    "total": "3",
                    "limit": "2",
                    "offset": "2",
                    "RaceTable": {"Races": [{"round": "3"}]},
                }
            },
        )
        with mock.patch("seasons.services.jolpica.time.sleep"):
            pages = jolpica.fetch_all("2025/races")
        rounds = [r["round"] for p in pages for r in p["RaceTable"]["Races"]]
        self.assertEqual(rounds, ["1", "2", "3"])

    @responses.activate
    def test_429_triggers_exponential_backoff(self):
        url = "https://api.jolpi.ca/ergast/f1/foo.json"
        for _ in range(3):
            responses.add(responses.GET, url, status=429)
        responses.add(
            responses.GET,
            url,
            json={
                "MRData": {"total": "0", "limit": "100", "offset": "0", "RaceTable": {"Races": []}}
            },
        )
        with mock.patch("seasons.services.jolpica.time.sleep") as slept:
            jolpica.fetch_all("foo")
        # backoffs: 2**0, 2**1, 2**2 for the 3 retries, plus the 0.3s spacer at the end.
        delays = [c.args[0] for c in slept.call_args_list]
        self.assertEqual(delays[:3], [1, 2, 4])

    @responses.activate
    def test_429_honors_retry_after_header(self):
        url = "https://api.jolpi.ca/ergast/f1/foo.json"
        responses.add(responses.GET, url, status=429, headers={"Retry-After": "42"})
        responses.add(
            responses.GET,
            url,
            json={
                "MRData": {"total": "0", "limit": "100", "offset": "0", "RaceTable": {"Races": []}}
            },
        )
        with mock.patch("seasons.services.jolpica.time.sleep") as slept:
            jolpica.fetch_all("foo")
        delays = [c.args[0] for c in slept.call_args_list]
        self.assertEqual(delays[0], 42)

    def test_hourly_throttle_blocks_when_cap_reached(self):
        # Prime the deque with 480 timestamps "just now" so the next call must wait.
        import time

        now = time.monotonic()
        for _ in range(jolpica._HOURLY_CAP):
            jolpica._RECENT_CALLS.append(now)

        with mock.patch("seasons.services.jolpica.time.sleep") as slept:
            jolpica._throttle()
        # First sleep call should be the cap-wait, > 0.
        self.assertTrue(slept.called)
        self.assertGreater(slept.call_args_list[0].args[0], 0)


class SyncYearCommandTests(TestCase):
    def test_sync_year_bumps_cache_version(self):
        cache.delete("f1:ver")

        with (
            mock.patch("seasons.management.commands.sync_year.sync_schedule"),
            mock.patch("seasons.management.commands.sync_year.sync_standings"),
        ):
            call_command("sync_year", 2025, "--skip-results")

        self.assertIsNotNone(cache.get("f1:ver"))


class CalendarServiceTests(TestCase):
    """Cover the three states the landing hero card can show:
    a weekend in progress, a weekend coming up, and an empty calendar."""

    @classmethod
    def setUpTestData(cls):
        from datetime import date, datetime, timezone

        from seasons.models import Circuit, Round, Season

        season = Season.objects.create(year=2026)
        cls.circuit = Circuit.objects.create(ref="silverstone", name="Silverstone")
        cls.round = Round.objects.create(
            season=season,
            number=10,
            name="British GP",
            circuit=cls.circuit,
            date=date(2026, 7, 5),
            fp1_at=datetime(2026, 7, 3, 12, 30, tzinfo=timezone.utc),
            fp2_at=datetime(2026, 7, 3, 16, 0, tzinfo=timezone.utc),
            fp3_at=datetime(2026, 7, 4, 11, 30, tzinfo=timezone.utc),
            qualifying_at=datetime(2026, 7, 4, 15, 0, tzinfo=timezone.utc),
            race_at=datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc),
        )

    def test_current_race_weekend_during_fp1(self):
        from datetime import datetime, timezone

        from seasons.services import calendar as cal

        now = datetime(2026, 7, 3, 13, 0, tzinfo=timezone.utc)
        self.assertEqual(cal.current_race_weekend(now=now), self.round)

        sess = cal.current_or_next_session(self.round, now=now)
        self.assertIsNotNone(sess)
        label, _, is_live = sess
        self.assertEqual(label, "FP1")
        self.assertTrue(is_live)

    def test_current_race_weekend_returns_none_off_weekend(self):
        from datetime import datetime, timezone

        from seasons.services import calendar as cal

        now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
        self.assertIsNone(cal.current_race_weekend(now=now))

    def test_next_race_weekend_finds_upcoming(self):
        from datetime import datetime, timezone

        from seasons.services import calendar as cal

        now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(cal.next_race_weekend(now=now), self.round)

    def test_next_race_weekend_skips_completed_round_later_same_day(self):
        from datetime import date, datetime, timezone

        from seasons.models import Round, Season
        from seasons.services import calendar as cal

        next_round = Round.objects.create(
            season=Season.objects.get(year=2026),
            number=11,
            name="Hungarian GP",
            circuit=self.circuit,
            date=date(2026, 7, 19),
            fp1_at=datetime(2026, 7, 17, 12, 30, tzinfo=timezone.utc),
            race_at=datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc),
        )

        now = datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc)

        self.assertIsNone(cal.current_race_weekend(now=now))
        self.assertEqual(cal.next_race_weekend(now=now), next_round)

    def test_current_or_next_session_picks_next_when_idle(self):
        from datetime import datetime, timezone

        from seasons.services import calendar as cal

        now = datetime(2026, 7, 3, 20, 0, tzinfo=timezone.utc)  # after FP2
        sess = cal.current_or_next_session(self.round, now=now)
        self.assertIsNotNone(sess)
        label, _, is_live = sess
        self.assertEqual(label, "FP3")
        self.assertFalse(is_live)

    def test_next_race_weekend_none_after_season_end(self):
        from datetime import datetime, timezone

        from seasons.services import calendar as cal

        now = datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
        self.assertIsNone(cal.next_race_weekend(now=now))
        self.assertIsNone(cal.current_race_weekend(now=now))
