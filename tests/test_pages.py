import unittest

from src.pages import _render_alert_flash, _render_raw_feed, _render_topics


class AlertFlashTests(unittest.TestCase):
    def test_alert_is_clickable_with_first_safe_source_link(self):
        html = _render_alert_flash(
            [
                {
                    "title": "Mimoriadna správa",
                    "reason": "Dôvod",
                    "links": [
                        "https://example.com/sprava?x=1&y=2",
                        "https://example.com/druhy-zdroj",
                    ],
                }
            ]
        )

        self.assertIn('<a class="flash-item"', html)
        self.assertIn(
            'href="https://example.com/sprava?x=1&amp;y=2"',
            html,
        )
        self.assertIn('target="_blank" rel="noopener"', html)
        self.assertNotIn("druhy-zdroj", html)

    def test_alert_without_safe_link_remains_plain_text(self):
        html = _render_alert_flash(
            [
                {
                    "title": "<Mimoriadna>",
                    "reason": "Dôvod",
                    "links": ["javascript:alert(1)"],
                }
            ]
        )

        self.assertNotIn("<a ", html)
        self.assertNotIn("javascript:", html)
        self.assertIn("&lt;Mimoriadna&gt;", html)
        self.assertIn('<div class="flash-item">', html)


class BriefingPageTests(unittest.TestCase):
    def test_top_topics_use_one_lead_and_four_secondary_items(self):
        topics = [
            {
                "headline": f"Téma {index}",
                "perex": "Krátky perex",
                "links": [("Zdroj", f"https://example.com/{index}")],
            }
            for index in range(1, 7)
        ]

        html = _render_topics({"topics": topics, "ts": 0})

        self.assertEqual(html.count("topic topic-lead"), 1)
        self.assertEqual(html.count("topic topic-secondary"), 4)
        self.assertNotIn("Téma 6", html)
        self.assertIn('href="https://example.com/1"', html)

    def test_media_radar_is_chronological_and_has_source_filters(self):
        html = _render_raw_feed(
            [
                {
                    "s": "SME",
                    "t": "Staršia správa",
                    "l": "https://example.com/older",
                    "ts": 100,
                },
                {
                    "s": "Aktuality",
                    "t": "Novšia správa",
                    "l": "https://example.com/newer",
                    "ts": 200,
                },
            ]
        )

        self.assertLess(html.index("Novšia správa"), html.index("Staršia správa"))
        self.assertIn('data-filter="all"', html)
        self.assertIn('data-filter="Aktuality"', html)
        self.assertIn('data-source="SME"', html)


if __name__ == "__main__":
    unittest.main()
