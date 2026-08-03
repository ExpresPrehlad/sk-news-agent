import tempfile
import unittest
from pathlib import Path

from src.state import State


class SportStateTests(unittest.TestCase):
    def test_sport_buffer_is_persisted_separately_from_main_buffer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = State(str(path))
            state.add_sport_recent(
                uid="sport-1", source="Šport.sk", title="Téma",
                perex="Popis", link="https://example.com/sport",
            )
            state.save()

            restored = State(str(path))
            self.assertEqual(len(restored.sport_recent), 1)
            self.assertEqual(restored.recent, [])
            self.assertEqual(restored.sport_recent[0]["t"], "Téma")


if __name__ == "__main__":
    unittest.main()
