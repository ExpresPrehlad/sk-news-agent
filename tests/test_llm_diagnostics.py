"""Offline end-to-end fallback/diagnostic tests: all HTTP is mocked."""

import json
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from src import config, digest
from src.llm import diagnostics, gemini, openrouter, router
from src.llm.contracts import SelectionValidationError, validate_selection

LINK = "https://example.com/article"
ARTICLE = {"s": "SME", "t": "Title", "p": "Description", "l": LINK}
TOPICS = json.dumps({"topics": [{"headline": "Title", "perex": "First. Second.",
                                  "links": [LINK]}]})


def response(data=None, status=200, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = data
    return result


def gemini_reply(text=TOPICS):
    return response({"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"text": text}],
    }}], "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50}})


def openrouter_reply(finish="stop"):
    return response({"choices": [{"finish_reason": finish, "message": {"content": TOPICS}}],
                     "usage": {"prompt_tokens": 100, "completion_tokens": 6144,
                               "completion_tokens_details": {"reasoning_tokens": 5900}}})


class ValidationDiagnosticTests(unittest.TestCase):
    def test_failures_have_fixed_codes_and_locations_without_article_text(self):
        cases = (
            ('{"topics": []}', "empty_topics", None, None),
            ('{"topics": [{"headline": "x", "links": ["x"]}]}',
             "missing_selection_field", 0, "perex"),
            (TOPICS.replace(LINK, "https://example.com/secret-output"),
             "unknown_source_link", 0, None),
            ('{"topics": [not json]}', "invalid_json", None, None),
            ('{"alerts": []}', "wrong_root_fields", None, None),
            ('no JSON', "missing_json_object", None, None),
        )
        for text, code, index, field in cases:
            with self.subTest(code=code), self.assertRaises(SelectionValidationError) as caught:
                validate_selection(text, "synthesis", {LINK})
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.item_index, index)
            self.assertEqual(caught.exception.field, field)
            self.assertNotIn("secret-output", str(caught.exception))

    def test_invalid_url_cannot_leak_into_exception(self):
        text = TOPICS.replace(LINK, "https://[secret-output")
        with self.assertRaises(SelectionValidationError) as caught:
            validate_selection(text, "synthesis", {LINK})
        self.assertEqual(caught.exception.code, "invalid_source_url")
        self.assertNotIn("secret-output", str(caught.exception))


class FallbackDiagnosticTests(unittest.TestCase):
    def setUp(self):
        diagnostics.reset()
        router._cooldowns.clear()
        self.addCleanup(diagnostics.reset)
        self.addCleanup(router._cooldowns.clear)
        for module in (gemini, config):
            key = patch.object(module, "GEMINI_API_KEY", "secret-google-key")
            key.start()
            self.addCleanup(key.stop)
        for module in (openrouter, config):
            key = patch.object(module, "OPENROUTER_API_KEY", "secret-openrouter-key")
            key.start()
            self.addCleanup(key.stop)

    def report(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "llm.json"
            self.assertTrue(diagnostics.write_report(str(target)))
            raw = target.read_text(encoding="utf-8")
            self.assertNotIn("secret-google-key", raw)
            self.assertNotIn("secret-openrouter-key", raw)
            self.assertNotIn(LINK, raw)
            return json.loads(raw)

    @patch("requests.post")
    def test_real_client_path_falls_back_to_openrouter_and_counts_http(self, post):
        post.side_effect = lambda url, **kwargs: (
            response(status=503) if "generativelanguage" in url else openrouter_reply()
        )
        with self.assertLogs("src.llm", level="INFO") as logs:
            topics, model = digest.synthesize([ARTICLE])
        self.assertTrue(model.startswith("openrouter/"))
        self.assertEqual(len(topics), 1)
        task = self.report()["tasks"][0]
        self.assertTrue(task["openrouter_entered"])
        self.assertEqual(task["openrouter_http_requests"], 1)
        self.assertEqual(task["status"], "success")
        self.assertEqual(task["selected_model"], model)
        self.assertEqual([a["http_status"] for a in task["attempts"]], [503] * 4 + [200])
        self.assertEqual(task["attempts"][-1]["status"], "accepted")
        self.assertEqual(task["attempts"][-1]["reasoning_tokens"], 5900)
        self.assertEqual(post.call_count, 5)
        self.assertIn("provider_transition=gemini->openrouter", "\n".join(logs.output))
        self.assertNotIn("secret-google-key", "\n".join(logs.output))
        summary = "\n".join(diagnostics.summary_lines())
        self.assertIn("HTTP požiadavky OpenRouter: **1**", summary)
        self.assertNotIn("secret-openrouter-key", summary)

    @patch("requests.post")
    def test_gemini_success_does_not_call_openrouter(self, post):
        post.return_value = gemini_reply()
        digest.synthesize([ARTICLE])
        task = self.report()["tasks"][0]
        self.assertFalse(task["openrouter_entered"])
        self.assertEqual(task["openrouter_http_requests"], 0)
        self.assertEqual(len(task["attempts"]), 1)
        post.assert_called_once()

    @patch("requests.post")
    def test_all_failures_are_retained_including_truncation_usage(self, post):
        def answer(url, **kwargs):
            if "generativelanguage" in url:
                return response(status=503)
            model = kwargs["json"]["model"]
            if "super-" in model:
                return response(status=404)
            if "gemma" in model:
                return response(status=429)
            return openrouter_reply(finish="length")
        post.side_effect = answer
        with self.assertRaises(router.AllModelsFailed):
            digest.synthesize([ARTICLE])
        task = self.report()["tasks"][0]
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["openrouter_http_requests"], 3)
        self.assertEqual(task["attempts"][-1]["error_code"], "incomplete_output")
        self.assertEqual(task["attempts"][-1]["finish_reason"], "length")
        self.assertEqual(task["attempts"][-1]["output_tokens"], 6144)
        self.assertEqual(task["attempts"][-1]["reasoning_tokens"], 5900)

    @patch("requests.post")
    def test_invalid_selection_exposes_only_safe_code_and_item_index(self, post):
        wrong = TOPICS.replace(LINK, "https://example.com/secret-output")
        post.side_effect = [gemini_reply(wrong), gemini_reply()]
        with self.assertLogs("src.llm", level="INFO") as logs:
            digest.synthesize([ARTICLE])
        task = self.report()["tasks"][0]
        self.assertEqual(task["attempts"][0]["error_code"], "unknown_source_link")
        self.assertEqual(task["attempts"][0]["item_index"], 0)
        self.assertEqual(task["attempts"][0]["response_chars"], len(wrong))
        self.assertNotIn("secret-output", json.dumps(task))
        self.assertNotIn("secret-output", "\n".join(logs.output))

    @patch("requests.post")
    def test_missing_openrouter_key_is_not_reported_as_http_request(self, post):
        post.return_value = response(status=503)
        with patch.object(openrouter, "OPENROUTER_API_KEY", ""):
            with self.assertRaises(router.AllModelsFailed):
                digest.synthesize([ARTICLE])
        task = self.report()["tasks"][0]
        self.assertTrue(task["openrouter_entered"])
        self.assertEqual(task["openrouter_http_requests"], 0)
        self.assertEqual(task["attempts"][-1]["error_code"], "missing_api_key")
        self.assertEqual(post.call_count, 4)

    @patch("requests.post")
    def test_missing_gemini_key_still_reaches_openrouter(self, post):
        post.return_value = openrouter_reply()
        with patch.object(gemini, "GEMINI_API_KEY", ""):
            _, model = digest.synthesize([ARTICLE])
        self.assertTrue(model.startswith("openrouter/"))
        post.assert_called_once()
        self.assertEqual(self.report()["tasks"][0]["attempts"][0]["error_code"], "missing_api_key")

    @patch("requests.post")
    def test_network_exception_text_and_finish_metadata_do_not_leak(self, post):
        post.side_effect = [requests.ReadTimeout("secret-google-key"),
                            response({"candidates": [{"finishReason": "secret-output"}]}),
                            gemini_reply()]
        with self.assertLogs("src.llm", level="INFO") as logs:
            digest.synthesize([ARTICLE])
        task = self.report()["tasks"][0]
        self.assertEqual(task["attempts"][0]["error_code"], "request_timeout")
        self.assertEqual(task["attempts"][1]["finish_reason"], "other")
        self.assertNotIn("secret-output", json.dumps(task))
        self.assertNotIn("secret-output", "\n".join(logs.output))
        self.assertNotIn("secret-google-key", "\n".join(logs.output))

    @patch("requests.post")
    def test_cooldown_skip_is_distinct_from_a_request(self, post):
        post.return_value = response(status=503)
        router._cooldowns["openrouter"] = float("inf")
        with self.assertRaises(router.AllModelsFailed):
            digest.synthesize([ARTICLE])
        task = self.report()["tasks"][0]
        self.assertEqual(task["openrouter_http_requests"], 0)
        self.assertEqual(task["skips"][-1]["code"], "shared_quota_cooldown")
        self.assertEqual(len(task["attempts"]), 4)

    def test_empty_and_failed_report_writes_are_nonfatal(self):
        self.assertIn("žiadna LLM úloha", "\n".join(diagnostics.summary_lines()))
        self.assertFalse(diagnostics.write_report(""))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, "write_text", side_effect=OSError("secret-path")):
                with self.assertLogs("src.llm.diagnostics", level="WARNING") as logs:
                    self.assertFalse(diagnostics.write_report(str(Path(directory) / "llm.json")))
        self.assertNotIn("secret-path", "\n".join(logs.output))

    @patch("requests.post")
    def test_chain_budget_expiry_is_visible_without_extra_calls(self, post):
        with patch.object(router.time, "monotonic", side_effect=[0, 181]):
            with self.assertRaises(router.AllModelsFailed):
                digest.synthesize([ARTICLE])
        task = self.report()["tasks"][0]
        self.assertFalse(task["openrouter_entered"])
        self.assertEqual(task["attempts"], [])
        self.assertEqual(task["skips"][0]["code"], "chain_budget_exhausted")
        post.assert_not_called()

    @patch("requests.post")
    def test_cli_skipped_run_still_writes_report_and_summary_without_http(self, post):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "llm.json"
            summary = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"LLM_DIAGNOSTICS_PATH": str(target),
                                         "GITHUB_STEP_SUMMARY": str(summary)}), \
                 patch.object(sys, "argv", ["main.py"]), \
                 patch("src.schedule.should_collect", return_value=(False, None)), \
                 patch("src.state.State") as state:
                state.return_value.get_meta.return_value = 0
                with self.assertRaises(SystemExit) as caught:
                    runpy.run_path(str(Path(__file__).resolve().parents[1] / "main.py"),
                                   run_name="__main__")
            self.assertEqual(caught.exception.code, 0)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["tasks"], [])
            self.assertIn("žiadna LLM úloha", summary.read_text(encoding="utf-8"))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
