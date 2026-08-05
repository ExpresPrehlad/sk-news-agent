import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.sport_audit_page import build_sport_audit_html
from src.sport_selection_log import SportSelectionLog, read_recent_sport_events


class SportSelectionLogTests(unittest.TestCase):
    def test_records_priority_result_and_builds_copyable_archive_page(self):
        with tempfile.TemporaryDirectory() as directory:
            log = SportSelectionLog(directory)
            article = SimpleNamespace(
                source_name="TERAZ.SK", title="Slovensko získalo medailu",
                summary="Veľký úspech reprezentácie", link="https://example.com/sport",
            )
            self.assertTrue(log.record_articles([article]))
            records = read_recent_sport_events(directory)
            self.assertEqual(records[0]["category"], "redakcny_vyber")
            self.assertGreater(records[0]["score"], 0)
            self.assertTrue(records[0]["reasons"])

            html = build_sport_audit_html(records)
            self.assertIn("História športových výberov", html)
            self.assertIn("Kopírovať zobrazené do Excelu", html)
            self.assertIn('data-filter="redakcny_vyber"', html)
            self.assertIn('data-filter="sport_radar"', html)
            self.assertIn('href="https://example.com/sport"', html)
            self.assertIn("navigator.clipboard.writeText", html)

    def test_log_is_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            log = SportSelectionLog(directory)
            article = SimpleNamespace(source_name="Šport.sk", title="Bežný výsledok", summary="", link="")
            log.record_articles([article])
            path = next(Path(directory).glob("*.jsonl"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8").strip())["source"], "Šport.sk")


if __name__ == "__main__":
    unittest.main()
