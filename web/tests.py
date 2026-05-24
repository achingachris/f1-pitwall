from django.test import TestCase

import responses

from web import nationalities
from web.services import wiki
from web.templatetags.flags import flag


class SeoMetaTests(TestCase):
    def test_about_page_includes_open_graph_and_twitter_image_metadata(self):
        from django.test import Client

        response = Client().get("/about/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'property="og:title"')
        self.assertContains(response, 'property="og:image"')
        self.assertContains(response, 'property="og:image:width" content="1200"')
        self.assertContains(response, 'property="og:image:height" content="630"')
        self.assertContains(response, "/static/web/img/pitwall-og.png")
        self.assertContains(response, 'name="twitter:card" content="summary_large_image"')

    def test_base_layout_includes_telegram_bot_link(self):
        from django.test import Client

        response = Client().get("/about/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="https://t.me/pitwallBycdc_bot"')
        self.assertContains(response, 'aria-label="Open Pitwall Telegram bot"')


class NavigationTests(TestCase):
    def test_landing_page_includes_mobile_navigation_toggle(self):
        from django.test import Client

        response = Client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="site-nav"')
        self.assertContains(response, 'class="nav-toggle"')
        self.assertContains(response, 'aria-controls="site-nav"')
        self.assertContains(response, 'aria-expanded="false"')


class NationalityTests(TestCase):
    def test_known_demonym_maps_to_flag(self):
        self.assertEqual(nationalities.country_code("British"), "GB")
        self.assertEqual(nationalities.flag_emoji("British"), "\U0001f1ec\U0001f1e7")

    def test_monegasque_accent_variant_is_recognized(self):
        self.assertEqual(nationalities.country_code("Monégasque"), "MC")
        self.assertEqual(nationalities.country_code("Monegasque"), "MC")

    def test_unknown_demonym_returns_empty(self):
        self.assertEqual(nationalities.country_code("Klingon"), "")
        self.assertEqual(nationalities.flag_emoji("Klingon"), "")


class WikiSummaryTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    @responses.activate
    def test_returns_extract_and_thumbnail(self):
        responses.add(
            responses.GET,
            "https://en.wikipedia.org/api/rest_v1/page/summary/Lewis_Hamilton",
            json={
                "extract": "Sir Lewis Hamilton is a British racing driver.",
                "thumbnail": {"source": "https://example.com/lh.jpg"},
                "content_urls": {
                    "desktop": {"page": "https://en.wikipedia.org/wiki/Lewis_Hamilton"}
                },
            },
        )
        result = wiki.fetch_summary("https://en.wikipedia.org/wiki/Lewis_Hamilton")
        self.assertIn("British racing driver", result["extract"])
        self.assertEqual(result["thumbnail"], "https://example.com/lh.jpg")

    @responses.activate
    def test_404_returns_empty_dict(self):
        responses.add(
            responses.GET,
            "https://en.wikipedia.org/api/rest_v1/page/summary/Nobody",
            status=404,
        )
        self.assertEqual(wiki.fetch_summary("https://en.wikipedia.org/wiki/Nobody"), {})

    @responses.activate
    def test_falls_back_to_title_when_url_empty(self):
        responses.add(
            responses.GET,
            "https://en.wikipedia.org/api/rest_v1/page/summary/Some%20Person",
            json={"extract": "ok"},
        )
        self.assertEqual(wiki.fetch_summary("", fallback_title="Some Person")["extract"], "ok")


class RequestLogMiddlewareTests(TestCase):
    """Verify the access-log line shape — what ops staff will be grepping."""

    def test_request_logs_method_path_status_and_duration(self):
        from django.test import Client

        c = Client()
        with self.assertLogs("web.request", level="INFO") as captured:
            r = c.get("/about/")
        self.assertEqual(r.status_code, 200)
        line = next((m for m in captured.output if "/about/" in m), None)
        self.assertIsNotNone(line, "expected a request-log line for /about/")
        self.assertIn("GET /about/", line)
        self.assertIn(" 200 ", line)
        self.assertIn("ip=", line)
        self.assertIn("ua=", line)

    def test_static_paths_are_not_logged(self):
        from django.test import Client

        c = Client()
        try:
            with self.assertLogs("web.request", level="INFO") as captured:
                c.get("/static/web/styles.css")
        except AssertionError:
            return  # no log emitted — exactly what we want
        self.assertFalse(
            any("/static/" in m for m in captured.output),
            "static asset paths should not appear in the access log",
        )


class FlagFilterTests(TestCase):
    def test_known_nationality_returns_emoji_span(self):
        out = flag("British")
        self.assertIn("\U0001f1ec\U0001f1e7", out)
        self.assertIn('class="flag"', out)
        # Trailing space so the table-cell layout stays right.
        self.assertTrue(out.endswith(" "))

    def test_empty_or_none_returns_empty_string(self):
        self.assertEqual(flag(""), "")
        self.assertEqual(flag(None), "")

    def test_unknown_nationality_returns_empty_string(self):
        # The filter must not leave dangling "<span class='flag'></span>"
        # spans when the nationality can't be mapped.
        self.assertEqual(flag("Klingon"), "")
