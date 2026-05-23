from django.test import TestCase

import responses

from web import nationalities
from web.services import wiki


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
