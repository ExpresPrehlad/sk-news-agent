import unittest

from src.pages import _render_alert_flash


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


if __name__ == "__main__":
    unittest.main()
