import json
from datetime import date
from unittest import mock

from django.test import Client, TestCase, override_settings

from bot import formatters, resolvers
from competitors.models import Constructor, Driver
from seasons.models import Circuit, Round, Season
from telemetry.models import Lap, Session, SessionStat, Stint


class ResolverTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hamilton = Driver.objects.create(
            ref="hamilton", code="HAM", given_name="Lewis", family_name="Hamilton"
        )
        cls.norris = Driver.objects.create(
            ref="norris", code="NOR", given_name="Lando", family_name="Norris"
        )
        cls.mercedes = Constructor.objects.create(ref="mercedes", name="Mercedes")
        cls.red_bull = Constructor.objects.create(ref="red_bull", name="Red Bull")

    def test_driver_lookup_by_code(self):
        hits = resolvers.find_drivers("HAM")
        self.assertEqual(hits, [self.hamilton])

    def test_driver_lookup_by_lowercase_code(self):
        self.assertEqual(resolvers.find_drivers("ham"), [self.hamilton])

    def test_driver_lookup_by_family_name(self):
        self.assertEqual(resolvers.find_drivers("Hamilton"), [self.hamilton])

    def test_driver_lookup_by_two_words(self):
        self.assertEqual(resolvers.find_drivers("lewis hamilton"), [self.hamilton])

    def test_driver_lookup_misses_return_empty(self):
        self.assertEqual(resolvers.find_drivers("xyz"), [])

    def test_team_lookup_by_partial_name(self):
        self.assertEqual(resolvers.find_constructors("red"), [self.red_bull])


@override_settings(
    TELEGRAM_BOT_TOKEN="fake-token-not-real",
    TELEGRAM_WEBHOOK_SECRET="testsecret",
    ALLOWED_HOSTS=["*"],
)
class WebhookViewTests(TestCase):
    def test_wrong_secret_returns_404(self):
        c = Client()
        r = c.post("/telegram/webhook/wrong/", data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 404)

    def test_empty_secret_setting_rejects_anything(self):
        with override_settings(TELEGRAM_WEBHOOK_SECRET=""):
            r = Client().post(
                "/telegram/webhook/testsecret/", data="{}", content_type="application/json"
            )
            self.assertEqual(r.status_code, 404)

    def test_get_is_rejected(self):
        r = Client().get("/telegram/webhook/testsecret/")
        self.assertEqual(r.status_code, 405)

    def test_empty_body_returns_200(self):
        r = Client().post("/telegram/webhook/testsecret/", data="", content_type="application/json")
        self.assertEqual(r.status_code, 200)

    def test_malformed_json_returns_400(self):
        r = Client().post(
            "/telegram/webhook/testsecret/", data="not-json", content_type="application/json"
        )
        self.assertEqual(r.status_code, 400)

    def test_valid_update_dispatches_to_bot(self):
        update_payload = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42, "is_bot": False, "first_name": "Tester"},
                "text": "/start",
            },
        }
        fake_bot = mock.Mock()
        with mock.patch("bot.views.get_bot", return_value=fake_bot):
            r = Client().post(
                "/telegram/webhook/testsecret/",
                data=json.dumps(update_payload),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200)
        fake_bot.process_new_updates.assert_called_once()

    def test_handler_crash_does_not_500(self):
        update_payload = {"update_id": 1}
        fake_bot = mock.Mock()
        fake_bot.process_new_updates.side_effect = RuntimeError("boom")
        with mock.patch("bot.views.get_bot", return_value=fake_bot):
            r = Client().post(
                "/telegram/webhook/testsecret/",
                data=json.dumps(update_payload),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200)


class EventLoggingTests(TestCase):
    """The bot's per-command audit log — keeps a forensic trail in production."""

    def test_message_log_captures_user_chat_and_text(self):
        from bot.handlers import _log_message

        message = mock.Mock()
        message.from_user = mock.Mock(id=42, username="chris")
        message.chat = mock.Mock(id=99)
        message.text = "/contenders drivers 2025"

        with self.assertLogs("bot.event", level="INFO") as captured:
            _log_message(message, "/contenders")
        joined = "\n".join(captured.output)
        self.assertIn("/contenders", joined)
        self.assertIn("user=42", joined)
        self.assertIn("username=chris", joined)
        self.assertIn("chat=99", joined)
        self.assertIn("drivers 2025", joined)

    def test_message_log_tolerates_missing_fields(self):
        from bot.handlers import _log_message

        message = mock.Mock(spec=["from_user", "chat", "text"])
        message.from_user = None
        message.chat = None
        message.text = None

        with self.assertLogs("bot.event", level="INFO") as captured:
            _log_message(message, "/start")
        self.assertIn("/start", "\n".join(captured.output))

    def test_callback_log_captures_user_and_data(self):
        from bot.handlers import _log_callback

        call = mock.Mock()
        call.from_user = mock.Mock(id=42, username="chris")
        call.data = "stand:driver:2025:10"

        with self.assertLogs("bot.event", level="INFO") as captured:
            _log_callback(call, "stand")
        joined = "\n".join(captured.output)
        self.assertIn("stand:driver:2025:10", joined)
        self.assertIn("user=42", joined)


class TelemetryFormatterTests(TestCase):
    """Smoke tests for the FastF1-backed bot formatters."""

    @classmethod
    def setUpTestData(cls):
        season = Season.objects.create(year=2024)
        circuit = Circuit.objects.create(ref="bahrain", name="Bahrain")
        cls.round = Round.objects.create(
            season=season,
            number=1,
            name="Bahrain GP",
            circuit=circuit,
            date=date(2024, 3, 2),
        )
        cls.ver = Driver.objects.create(
            ref="max_verstappen",
            code="VER",
            given_name="Max",
            family_name="Verstappen",
            nationality="Dutch",
        )
        cls.ham = Driver.objects.create(
            ref="hamilton",
            code="HAM",
            given_name="Lewis",
            family_name="Hamilton",
            nationality="British",
        )
        cls.redbull = Constructor.objects.create(
            ref="red_bull", name="Red Bull", nationality="Austrian"
        )
        cls.session = Session.objects.create(round=cls.round, kind=Session.RACE)
        SessionStat.objects.create(
            session=cls.session,
            driver=cls.ver,
            constructor=cls.redbull,
            fastest_lap_seconds=90.1,
            top_speed_kmh=332.4,
            laps_completed=57,
        )
        SessionStat.objects.create(
            session=cls.session,
            driver=cls.ham,
            constructor=None,
            fastest_lap_seconds=91.0,
            top_speed_kmh=325.0,
            laps_completed=57,
        )
        # Two stints + a few laps for VER so format_laps has something to render.
        Stint.objects.create(
            session=cls.session,
            driver=cls.ver,
            number=1,
            compound="SOFT",
            lap_start=1,
            lap_end=3,
            laps_count=3,
        )
        Stint.objects.create(
            session=cls.session,
            driver=cls.ver,
            number=2,
            compound="HARD",
            lap_start=4,
            lap_end=5,
            laps_count=2,
        )
        Lap.objects.bulk_create(
            [
                Lap(
                    session=cls.session,
                    driver=cls.ver,
                    number=n,
                    lap_time_seconds=90.1 + 0.1 * (n - 1),
                )
                for n in range(1, 6)
            ]
        )

    def test_top_speeds_lists_drivers_in_order(self):
        out = formatters.format_top_speeds(2024)
        self.assertIn("Top speeds · 2024", out)
        self.assertIn("332.4", out)
        self.assertIn("Verstappen", out)
        self.assertLess(out.index("Verstappen"), out.index("Hamilton"))

    def test_top_speeds_empty_year_returns_friendly_message(self):
        out = formatters.format_top_speeds(2099)
        self.assertIn("No FastF1 data", out)

    def test_format_laps_renders_stints_and_best_lap(self):
        out = formatters.format_laps(self.round)
        self.assertIn("Lap by lap", out)
        self.assertIn("Verstappen", out)
        self.assertIn("90.100", out)
        # Compound emoji + lap count: SOFT 3-lap stint -> "🟥3"
        self.assertIn("🟥3", out)
        self.assertIn("⚪2", out)  # HARD

    def test_format_laps_empty_round_returns_friendly_message(self):
        empty_season = Season.objects.create(year=2025)
        empty_round = Round.objects.create(
            season=empty_season,
            number=1,
            name="Future GP",
            circuit=self.round.circuit,
            date=date(2025, 3, 1),
        )
        out = formatters.format_laps(empty_round)
        self.assertIn("No FastF1 race-lap data", out)

    def test_funstats_appends_top_speed_section_when_telemetry_present(self):
        out = formatters.format_funstats(2024)
        self.assertIn("Top speed-trap", out)
        self.assertIn("332.4", out)
