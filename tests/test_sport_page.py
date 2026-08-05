import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.sport_page import _featured_articles, _rank_articles, build_sport_html, write_sport_page


class SportPageTests(unittest.TestCase):
    @staticmethod
    def _state(articles):
        state = SimpleNamespace()
        state.sport_recent_window = lambda _hours: articles
        return state

    def test_page_is_separate_and_links_safely(self):
        html = build_sport_html(self._state([{
            "s": "Šport.sk", "t": "Veľká športová téma",
            "p": "Stručný popis", "l": "https://example.com/sport", "ts": 100,
        }]))

        self.assertIn("Športový radar", html)
        self.assertIn("Mimoriadne a Top tém", html)
        self.assertIn("Redakčný výber", html)
        self.assertIn("Sledovať", html)
        self.assertIn("--green", html)
        self.assertIn('href="https://example.com/sport"', html)
        self.assertIn('href="index.html#media-radar"', html)
        self.assertIn("fetch('version.json?check='+Date.now()", html)

    def test_page_rejects_unsafe_link(self):
        html = build_sport_html(self._state([{
            "s": "Zdroj", "t": "<Téma>", "p": "", "l": "javascript:bad()", "ts": 100,
        }]))

        self.assertNotIn("javascript:", html)
        self.assertIn("&lt;Téma&gt;", html)

    def test_sport_radar_has_publisher_filters(self):
        html = build_sport_html(self._state([
            {"u": "1", "s": "Šport.sk", "t": "Téma", "p": "", "l": "", "ts": 200},
            {"u": "2", "s": "SPORTNET", "t": "Ďalšia téma", "p": "", "l": "", "ts": 100},
        ]))

        self.assertIn("Šport Radar", html)
        self.assertIn('data-filter="SPORTNET"', html)
        self.assertIn('data-source="Šport.sk"', html)
        self.assertIn("radar-filter", html)

    def test_featured_selection_keeps_slovak_and_global_events_but_excludes_routine_content(self):
        featured = _featured_articles([
            {"t": "Live prenos z ligy", "p": "Program zápasu", "ts": 300},
            {"t": "Slovenská reprezentácia získala medailu", "p": "MS", "ts": 100},
            {"t": "Padol svetový rekord v atletike", "p": "Zahraničie", "ts": 200},
            {"t": "Bežný výsledok zahraničnej ligy", "p": "Rutinný zápas", "ts": 400},
        ])
        titles = [article["t"] for article in featured]
        self.assertIn("Slovenská reprezentácia získala medailu", titles)
        self.assertIn("Padol svetový rekord v atletike", titles)
        self.assertNotIn("Live prenos z ligy", titles)
        self.assertNotIn("Bežný výsledok zahraničnej ligy", titles)

    def test_page_writes_html(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            target = Path(directory) / "sport.html"
            write_sport_page(self._state([]), str(target))
            self.assertIn("Športový radar", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
