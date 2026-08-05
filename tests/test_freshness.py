import unittest
from types import SimpleNamespace

from src.config import SEEN_WINDOW_HOURS
from src.freshness import fresh_triage_articles, is_fresh_for_triage


class TriageFreshnessTests(unittest.TestCase):
    NOW = 2_000_000_000.0

    def test_two_day_old_article_is_rejected(self):
        self.assertFalse(
            is_fresh_for_triage(
                self.NOW - 48 * 3600,
                max_age_hours=12,
                now_ts=self.NOW,
            )
        )

    def test_recent_article_is_kept(self):
        self.assertTrue(
            is_fresh_for_triage(
                self.NOW - 2 * 3600,
                max_age_hours=12,
                now_ts=self.NOW,
            )
        )

    def test_source_without_timestamp_is_kept(self):
        self.assertTrue(
            is_fresh_for_triage(None, max_age_hours=12, now_ts=self.NOW)
        )

    def test_filter_preserves_only_eligible_candidates(self):
        recent = SimpleNamespace(published_ts=self.NOW - 3600)
        stale = SimpleNamespace(published_ts=self.NOW - 2 * 24 * 3600)
        unknown = SimpleNamespace(published_ts=None)
        self.assertEqual(
            fresh_triage_articles(
                [recent, stale, unknown],
                max_age_hours=12,
                now_ts=self.NOW,
            ),
            [recent, unknown],
        )

    def test_seen_memory_is_at_least_seven_days(self):
        self.assertGreaterEqual(SEEN_WINDOW_HOURS, 7 * 24)


if __name__ == "__main__":
    unittest.main()
