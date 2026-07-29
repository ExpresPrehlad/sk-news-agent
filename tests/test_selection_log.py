import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.audit_page import build_audit_html
from src.selection_log import SelectionLog, read_recent_events


class SelectionLogTests(unittest.TestCase):
    def test_records_triage_and_synthesis_in_order(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            audit = SelectionLog(directory)
            audit.record_triage(
                articles=[{"t": "Článok"}],
                context_count=4,
                alerts=[
                    SimpleNamespace(
                        title="Mimoriadna téma",
                        reason="Dôvod výberu",
                        links=["https://example.com/alert"],
                        signals={
                            "geography": "slovakia",
                            "public_impact": True,
                        },
                    )
                ],
                model="test-model",
                published=True,
                decision_valid=True,
                policy_version="test-v2",
            )
            audit.record_synthesis(
                articles=[{"t": "Článok"}],
                already_featured_count=2,
                topics=[
                    SimpleNamespace(
                        headline="Hlavná téma",
                        perex="Prvá veta. Druhá veta.",
                        links=[("Zdroj", "https://example.com/topic")],
                    )
                ],
                model="test-model",
                published=False,
                forced=True,
            )

            paths = list(Path(directory).glob("*.jsonl"))
            self.assertEqual(len(paths), 1)
            records = [
                json.loads(line)
                for line in paths[0].read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [record["event_type"] for record in records],
                ["triage", "synthesis"],
            )
            self.assertEqual(records[0]["selected"][0]["reason"], "Dôvod výberu")
            self.assertEqual(
                records[0]["selected"][0]["signals"]["geography"],
                "slovakia",
            )
            self.assertEqual(
                records[0]["input"]["candidates"][0]["title"],
                "Článok",
            )
            self.assertEqual(records[0]["input"]["policy_version"], "test-v2")
            self.assertTrue(records[1]["input"]["forced"])
            self.assertFalse(records[1]["published"])
            self.assertEqual(records[0]["run_id"], records[1]["run_id"])

            recent = read_recent_events(directory)
            self.assertEqual(
                [record["event_type"] for record in recent],
                ["synthesis", "triage"],
            )

    def test_records_empty_triage_decision(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            audit = SelectionLog(directory)
            self.assertTrue(
                audit.record_triage(
                    articles=[{"t": "Bežná správa"}],
                    context_count=0,
                    alerts=[],
                    model="test-model",
                    published=True,
                    decision_valid=True,
                    policy_version="test-v2",
                )
            )
            record = read_recent_events(directory, limit=1)[0]
            self.assertEqual(record["selection_count"], 0)
            self.assertEqual(record["selected"], [])

    def test_audit_page_escapes_text_and_rejects_unsafe_link(self):
        event = {
            "recorded_ts": 1_700_000_000,
            "run_id": "abcdefgh",
            "event_type": "triage",
            "model": "<model>",
            "input": {"article_count": 1},
            "selection_count": 1,
            "selected": [
                {
                    "title": "<script>alert(1)</script>",
                    "reason": "dôvod",
                    "links": ["javascript:alert(1)"],
                }
            ],
            "published": True,
        }
        html = build_audit_html([event])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn('href="javascript:', html)

    def test_audit_page_renders_simple_filterable_archive_table(self):
        event = {
            "recorded_ts": 1_700_000_000,
            "run_id": "abcdefgh",
            "event_type": "triage",
            "model": "test-model",
            "input": {
                "article_count": 1,
                "policy_version": "test-v2",
                "candidates": [
                    {
                        "source": "Zdroj",
                        "title": "Nevybratý kandidát",
                        "link": "https://example.com/kandidat",
                    }
                ],
            },
            "selection_count": 1,
            "selected": [
                {
                    "title": "Alert",
                    "reason": "Dôvod",
                    "links": [],
                    "signals": {
                        "geography": "slovakia",
                        "event_type": "industrial",
                        "public_impact": True,
                    },
                }
            ],
            "published": True,
        }
        html = build_audit_html([event])
        self.assertIn('id="archive-table"', html)
        self.assertIn('data-filter="triage"', html)
        self.assertIn('data-filter="synthesis"', html)
        self.assertIn('data-type="triage"', html)
        self.assertIn("Mimoriadne", html)
        self.assertIn("Alert", html)
        self.assertIn("Dôvod", html)
        self.assertIn("Kopírovať zobrazené do Excelu", html)
        self.assertNotIn("Nevybratý kandidát", html)
        self.assertNotIn("politika test-v2", html)


if __name__ == "__main__":
    unittest.main()
