import calendar
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from src.collector.rss import _clean_google_news_title, _entry_timestamp, fetch_all, fetch_source
from src.config import SOURCES, Source
from src.freshness import fresh_synthesis_articles, fresh_triage_articles


class GoogleNewsRssTests(unittest.TestCase):
    NOW = datetime(2026, 10, 12, 14, tzinfo=timezone.utc).timestamp()
    FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>TN Live Google News</title>
      <item><title>Nova sprava - tnlive.sk</title>
        <link>https://news.google.com/rss/articles/fresh</link>
        <guid isPermaLink="false">fresh-guid</guid>
        <pubDate>Mon, 12 Oct 2026 13:00:00 GMT</pubDate>
        <description>&lt;a href="https://news.google.com/rss/articles/fresh"&gt;Nova sprava&lt;/a&gt;</description>
        <source url="https://tnlive.sk">tnlive.sk</source>
      </item>
      <item><title>Stara sprava - tnlive.sk</title>
        <link>https://news.google.com/rss/articles/stale</link>
        <guid isPermaLink="false">stale-guid</guid>
        <pubDate>Thu, 08 Oct 2026 13:00:00 GMT</pubDate>
        <source url="https://tnlive.sk">tnlive.sk</source>
      </item>
    </channel></rss>'''

    def setUp(self):
        self.source = next(source for source in SOURCES if source.id == "tnlive")

    def fetch(self):
        response = Mock(content=self.FEED, headers={})
        with patch("src.collector.rss.requests.get", return_value=response) as get:
            result = fetch_source(self.source)
            get.assert_called_once()
            self.assertIn("news.google.com/rss/", get.call_args.args[0])
        return result

    def test_tnlive_keeps_display_name_and_cleans_publisher_suffix(self):
        result = self.fetch()
        self.assertTrue(result.ok)
        article = result.articles[0]
        self.assertEqual(article.title, "Nova sprava")
        self.assertEqual(article.summary, "Nova sprava")
        self.assertEqual(article.source_id, "tnlive")
        self.assertEqual(article.source_name, "TN Live")
        self.assertEqual(article.link, "https://news.google.com/rss/articles/fresh")

    def test_publication_time_is_utc_independent_of_machine_timezone(self):
        parsed = (2026, 10, 12, 13, 0, 0, 0, 285, 0)
        with patch("time.mktime", side_effect=AssertionError("local time must not be used")):
            self.assertEqual(_entry_timestamp({"published_parsed": parsed}), calendar.timegm(parsed))
        article = self.fetch().articles[0]
        self.assertEqual(article.published_ts, datetime(
            2026, 10, 12, 13, tzinfo=timezone.utc,
        ).timestamp())

    def test_old_rss_articles_do_not_enter_triage_or_synthesis(self):
        articles = self.fetch().articles
        self.assertEqual(
            fresh_triage_articles(articles, max_age_hours=12, now_ts=self.NOW),
            [articles[0]],
        )
        candidates = [{"t": a.title, "ts": self.NOW, "pub": a.published_ts} for a in articles]
        self.assertEqual(
            fresh_synthesis_articles(candidates, max_age_hours=24, now_ts=self.NOW),
            [candidates[0]],
        )

    def test_rss_uid_is_stable_between_runs(self):
        self.assertEqual(self.fetch().articles[0].uid, self.fetch().articles[0].uid)

    def test_tnlive_dispatch_uses_rss_not_the_blocked_sitemap(self):
        with patch("src.collector.rss.fetch_source", return_value="rss") as rss, \
             patch("src.collector.sitemap.fetch_news_sitemap") as sitemap:
            self.assertEqual(fetch_all([self.source]), ["rss"])
        rss.assert_called_once_with(self.source)
        sitemap.assert_not_called()

    def test_other_rss_sources_do_not_lose_title_text(self):
        source = Source("ordinary", "Publisher", "https://example.com/feed")
        title = "Important topic - Publisher"
        self.assertEqual(_clean_google_news_title(title, source, "Publisher"), title)

    def test_existing_gnews_suffix_cleaning_still_works(self):
        source = Source("sportnet_gnews", "SPORTNET", "https://news.google.com/rss/search?q=x")
        self.assertEqual(_clean_google_news_title("Tema - SPORTNET", source), "Tema")
        self.assertEqual(_clean_google_news_title("Tema - iny vydavatel", source, "SPORTNET"),
                         "Tema - iny vydavatel")


if __name__ == "__main__":
    unittest.main()
