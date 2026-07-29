import sys
import types
import unittest


fake_router = types.ModuleType("src.llm.router")


class FakeAllModelsFailed(RuntimeError):
    pass


fake_router.AllModelsFailed = FakeAllModelsFailed
fake_llm = types.ModuleType("src.llm")
fake_llm.router = fake_router
sys.modules.setdefault("src.llm", fake_llm)
sys.modules.setdefault("src.llm.router", fake_router)

from src import digest  # noqa: E402


class TriagePolicyTests(unittest.TestCase):
    def test_v2_prompt_distinguishes_routine_and_strategic_accidents(self):
        self.assertIn("pravidelnú dopravnú nehodu", digest._TRIAGE_SYSTEM)
        self.assertIn("strategickej alebo štátnej stavbe", digest._TRIAGE_SYSTEM)
        self.assertIn("železničnú nehodu", digest._TRIAGE_SYSTEM)
        self.assertIn("tragickú nehodu autobusu", digest._TRIAGE_SYSTEM)
        self.assertIn("KRIMI nie je zakázané", digest._TRIAGE_SYSTEM)

    def test_triage_parses_and_normalizes_decision_signals(self):
        fake_router.generate = lambda *args, **kwargs: (
            """
            {"alerts":[{
              "title":"Nehoda v chemickom závode",
              "reason":"Hrozí únik látok.",
              "links":["https://example.com/alert"],
              "signals":{
                "geography":"SLOVAKIA",
                "event_type":"INDUSTRIAL",
                "direct_slovak_relevance":"true",
                "ongoing_danger":1,
                "public_impact":true,
                "strategic_infrastructure":false,
                "hazardous_materials":"áno"
              }
            }]}
            """,
            "test-model",
        )
        alerts, model, valid = digest.triage(
            [
                {
                    "s": "Zdroj",
                    "t": "Nehoda v chemickom závode",
                    "p": "Hrozí únik látok.",
                    "l": "https://example.com/alert",
                }
            ]
        )
        self.assertTrue(valid)
        self.assertEqual(model, "test-model")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].signals["geography"], "slovakia")
        self.assertEqual(alerts[0].signals["event_type"], "industrial")
        self.assertTrue(alerts[0].signals["direct_slovak_relevance"])
        self.assertTrue(alerts[0].signals["ongoing_danger"])
        self.assertTrue(alerts[0].signals["hazardous_materials"])
        self.assertFalse(alerts[0].signals["strategic_infrastructure"])


if __name__ == "__main__":
    unittest.main()
