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
