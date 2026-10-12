import tempfile
import unittest
from pathlib import Path

from src.collector.rss import FetchResult
from src.config import Source
from src.state import State


class MainStateTests(unittest.TestCase):
    def test_source_status_drops_removed_sources_without_deleting_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = State(str(path))
            state.source_status = {"hn": {"name": "HN", "ok": False, "error": "403"}}
            state.sport_source_status = {"sport_sk": {"name": "Šport.sk", "ok": True}}
            state.add_recent(
                uid="historical-hn", source="HN", title="Historická správa",
                perex="", link="https://hnonline.sk/stara-sprava",
            )
            source = Source("tnlive", "TN Live", "https://tnlive.sk/xml/sitemap-news.xml")
            state.set_source_status([FetchResult(source, [])])
            state.save()

            restored = State(str(path))
            self.assertEqual(set(restored.source_status), {"tnlive"})
            self.assertTrue(restored.source_status["tnlive"]["ok"])
            self.assertEqual(restored.recent[0]["u"], "historical-hn")
            self.assertIn("sport_sk", restored.sport_source_status)

    def test_current_source_failure_is_still_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(str(Path(directory) / "state.json"))
            source = Source("tnlive", "TN Live", "https://tnlive.sk/xml/sitemap-news.xml")
            state.set_source_status([FetchResult(source, [], error="HTTP 404")])
            self.assertFalse(state.source_status["tnlive"]["ok"])
            self.assertEqual(state.source_status["tnlive"]["error"], "HTTP 404")

    def test_main_buffer_persists_publication_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = State(str(path))
            state.add_recent(
                uid="article-1",
                source="SME (GNews)",
                title="Téma",
                perex="Popis",
                link="https://example.com/article",
                published_ts=1_234_567_890.0,
            )
            state.save()

            restored = State(str(path))
            self.assertEqual(
                restored.recent[0]["pub"],
                1_234_567_890.0,
            )


if __name__ == "__main__":
    unittest.main()
