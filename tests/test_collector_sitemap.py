import gzip
import hashlib
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests

from src.collector.sitemap import _get, fetch_news_sitemap
from src.config import SOURCES, SPORT_SOURCES, Source


class SourceConfigurationTests(unittest.TestCase):
    def test_hnonline_is_not_a_configured_source(self):
        for source in SOURCES + SPORT_SOURCES:
            self.assertNotEqual(source.id, "hn")
            self.assertNotIn("hnonline.sk", source.feed_url)

    def test_tnlive_uses_google_news_rss_with_existing_source_identity(self):
        source = next(source for source in SOURCES if source.id == "tnlive")
        self.assertEqual(source.name, "TN Live")
        self.assertEqual(source.kind, "rss")
        self.assertEqual(urlsplit(source.feed_url).hostname, "news.google.com")
        self.assertEqual(parse_qs(urlsplit(source.feed_url).query)["q"], ["site:tnlive.sk when:2d"])


class NewsSitemapTests(unittest.TestCase):
    NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc).timestamp()

    def setUp(self):
        # The generic sitemap parser remains supported, but TN Live's
        # active production source no longer calls its blocked sitemap.
        self.source = Source("tnlive", "TN Live", "https://tnlive.sk/xml/sitemap-news.xml", kind="news_sitemap")

    def fetch_xml(self, xml):
        with patch("src.collector.sitemap._get", return_value=xml.encode("utf-8")), \
             patch("src.collector.sitemap.time.time", return_value=self.NOW):
            return fetch_news_sitemap(self.source)

    @staticmethod
    def urlset(entries=""):
        return (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
            + entries + '</urlset>'
        )

    @staticmethod
    def entry(link, title, date):
        return (
            f'<url><loc>{link}</loc><news:news>'
            '<news:publication><news:name>tnlive.sk</news:name>'
            '<news:language>sk</news:language></news:publication>'
            f'<news:publication_date>{date}</news:publication_date>'
            f'<news:title>{title}</news:title></news:news></url>'
        )

    def test_new_tnlive_format_preserves_title_publication_time_and_uid(self):
        link = "https://tnlive.sk/ekonomika/clanok/1056730-nobelovu-cenu-za-ekonomiu"
        result = self.fetch_xml(self.urlset(self.entry(
            link, "Ekonómia &amp; Slovensko: Čerstvá správa", "2026-10-12T13:13:00+02:00",
        )))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.articles), 1)
        article = result.articles[0]
        self.assertEqual(article.title, "Ekonómia & Slovensko: Čerstvá správa")
        self.assertEqual(article.link, link)
        self.assertEqual(article.source_id, "tnlive")
        self.assertEqual(article.source_name, "TN Live")
        self.assertEqual(article.published_ts, datetime(
            2026, 10, 12, 11, 13, tzinfo=timezone.utc,
        ).timestamp())
        # The feed endpoint is not part of identity: switching sitemaps must
        # not make already-seen articles new again.
        self.assertEqual(article.uid, hashlib.sha256(
            f"tnlive:{link}".encode("utf-8"),
        ).hexdigest()[:20])

    def test_stale_articles_are_not_reintroduced_by_the_new_sitemap(self):
        result = self.fetch_xml(self.urlset(
            self.entry("https://tnlive.sk/domace/clanok/1-nova", "Nová", "2026-10-12T10:00:00Z")
            + self.entry("https://tnlive.sk/domace/clanok/2-stara", "Stará", "2026-10-08T10:00:00Z")
        ))
        self.assertTrue(result.ok)
        self.assertEqual([article.title for article in result.articles], ["Nová"])

    def test_missing_article_fields_are_skipped(self):
        result = self.fetch_xml(self.urlset(
            '<url><loc>https://tnlive.sk/domace/clanok/1-bez-titulku</loc></url>'
        ))
        self.assertTrue(result.ok)
        self.assertEqual(result.articles, [])

    def test_unexpected_xml_document_is_not_a_successful_empty_feed(self):
        for xml in ('<html><body>Not found</body></html>',
                    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>'):
            with self.subTest(xml=xml):
                result = self.fetch_xml(xml)
                self.assertFalse(result.ok)
                self.assertIn("urlset", result.error)
                self.assertEqual(result.articles, [])

    def test_valid_empty_sitemap_remains_a_success(self):
        result = self.fetch_xml(self.urlset())
        self.assertTrue(result.ok)
        self.assertEqual(result.articles, [])

    def test_broken_xml_is_reported_as_source_failure(self):
        result = self.fetch_xml("<urlset")
        self.assertFalse(result.ok)
        self.assertEqual(result.articles, [])

    def test_http_failure_does_not_escape_the_collector(self):
        with patch("src.collector.sitemap._get", side_effect=requests.HTTPError("404")):
            result = fetch_news_sitemap(self.source)
        self.assertFalse(result.ok)
        self.assertEqual(result.articles, [])

    def test_gzip_support_is_kept_for_other_sitemap_sources(self):
        xml = self.urlset().encode("utf-8")
        response = Mock(content=gzip.compress(xml))
        with patch("src.collector.sitemap.requests.get", return_value=response):
            self.assertEqual(_get("https://example.com/sitemap.xml.gz"), xml)
        response.raise_for_status.assert_called_once()


if __name__ == "__main__":
    unittest.main()
