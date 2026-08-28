import tempfile
import unittest
from pathlib import Path

from src.state import State


class MainStateTests(unittest.TestCase):
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
