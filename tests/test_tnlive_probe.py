import unittest
from pathlib import Path

from tools.check_tnlive_sitemaps import describe_content, report


class TnLiveProbeTests(unittest.TestCase):
    def test_diagnostic_workflow_excludes_production_and_has_no_secrets(self):
        workflow = (Path(__file__).parents[1] / '.github/workflows/collect.yml').read_text(encoding='utf-8')
        self.assertIn("if: github.ref != 'refs/heads/codex/tnlive-sitemap-check'", workflow)
        self.assertIn("&& 'tnlive-sitemap-check' || 'collect'", workflow)
        diagnostic = workflow.split('  sitemap-check:', 1)[1]
        self.assertIn("if: github.ref == 'refs/heads/codex/tnlive-sitemap-check'", diagnostic)
        self.assertIn('contents: read', diagnostic)
        self.assertIn('persist-credentials: false', diagnostic)
        self.assertNotIn('secrets.', diagnostic)
        self.assertNotIn('main.py', diagnostic)
        self.assertNotIn('git push', diagnostic)

    def test_news_sitemap_counts_titles_and_publication_dates(self):
        xml = b'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
          xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
          <url><loc>https://tnlive.sk/domace/clanok/1-tema</loc><news:news>
          <news:title>Tema</news:title><news:publication_date>2026-10-12T12:00:00Z</news:publication_date>
          </news:news></url></urlset>'''
        result = describe_content(xml, 200)
        self.assertTrue(result["usable"])
        self.assertEqual((result["urls"], result["titles"], result["publication_dates"]), (1, 1, 1))

    def test_plain_sitemap_does_not_claim_publication_times(self):
        xml = b'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://tnlive.sk/domace/clanok/1-tema</loc><lastmod>2026-10-12</lastmod></url></urlset>'''
        result = describe_content(xml, 200)
        self.assertTrue(result["usable"])
        self.assertEqual(result["publication_dates"], 0)
        self.assertEqual(result["date_only_lastmod"], 1)

    def test_challenge_and_error_pages_are_never_success(self):
        for status in (200, 403, 404):
            with self.subTest(status=status):
                self.assertFalse(describe_content(b"<html><body>challenge</body></html>", status)["usable"])

    def test_index_is_not_a_collected_article_feed(self):
        result = describe_content(
            b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>', 200,
        )
        self.assertFalse(result["usable"])
        self.assertEqual(result["root"], "sitemapindex")

    def test_summary_distinguishes_xml_from_http_success(self):
        summary = report([{"mode": "test", "url": "https://tnlive.sk/", "status": 200, "usable": False}])
        self.assertIn("| 200 | nie |", summary)
        self.assertIn("lastmod", summary)


if __name__ == "__main__":
    unittest.main()
