import unittest
from types import SimpleNamespace

from src.config import SEEN_WINDOW_HOURS
from src.freshness import (
    fresh_synthesis_articles,
    fresh_triage_articles,
    is_fresh_for_triage,
)


class FreshnessTests(unittest.TestCase):
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

    def test_seen_memory_is_at_least_fourteen_days(self):
        self.assertGreaterEqual(SEEN_WINDOW_HOURS, 14 * 24)

    def test_synthesis_rejects_old_article_seen_now(self):
        articles = [
            {"t": "čerstvá", "ts": self.NOW, "pub": self.NOW - 3600},
            {"t": "stará", "ts": self.NOW, "pub": self.NOW - 7 * 24 * 3600},
            {"t": "bez dátumu", "ts": self.NOW},
        ]
        self.assertEqual(
            fresh_synthesis_articles(
                articles,
                max_age_hours=24,
                now_ts=self.NOW,
            ),
            [articles[0], articles[2]],
        )


if __name__ == "__main__":
    unittest.main()
