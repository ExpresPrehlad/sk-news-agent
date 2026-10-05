"""Offline API/fallback regression tests. No keys or network required."""

import json
import unittest
from unittest.mock import Mock, patch

import requests

from src import config, digest
from src.llm import gemini, openrouter, router
from src.llm.contracts import resolve_source_link, selection_schema, validate_selection


LINK = "https://example.com/article"
ARTICLE = {"s": "SME", "t": "Téma", "p": "Popis", "l": LINK}
TOPICS = json.dumps({"topics": [{"headline": "Téma", "perex": "Prvá veta. Druhá veta.",
                                  "links": [LINK]}]})
ALERTS = json.dumps({"alerts": [{"title": "Udalosť", "reason": "Ohrozenie verejnosti.",
                                  "links": [LINK], "signals": {}}]})


def response(data=None, status=200, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = data
    return result


def gemini_response(text='{"alerts": []}', finish="STOP", extra_parts=None):
    return response({"candidates": [{"finishReason": finish, "content": {
        "parts": [*(extra_parts or []), {"text": text}],
    }}], "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10}})


def openrouter_response(text='{"alerts": []}', finish="stop", model=None):
    data = {"choices": [{"finish_reason": finish, "message": {"content": text}}]}
    if model is not None:
        data["model"] = model
    return response(data)


class ContractTests(unittest.TestCase):
    def test_empty_alerts_are_valid_but_empty_topics_are_not(self):
        validate_selection('{"alerts": []}', "triage", {LINK})
        with self.assertRaises(ValueError):
            validate_selection('{"topics": []}', "synthesis", {LINK})

    def test_markdown_and_legacy_signals_remain_compatible(self):
        validate_selection("```json\n" + ALERTS + "\n```", "triage", {LINK})
        validate_selection(TOPICS, "synthesis", {LINK})

    def test_wrong_shapes_and_safety_verdicts_are_rejected(self):
        for text in ('{"safe": true}', '{"alerts": null}', '{"alerts": {}}',
                     '{"alerts": ["news"]}', '{"topics": []}', "safe"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_selection(text, "triage", {LINK})

    def test_invented_or_missing_links_are_rejected(self):
        for links in (["https://example.com/invented"], [], "url", [1]):
            text = json.dumps({"alerts": [{"title": "Téma", "reason": "Dôvod",
                                           "links": links}]})
            with self.subTest(links=links), self.assertRaises(ValueError):
                validate_selection(text, "triage", {LINK})

    def test_partial_json_is_not_repaired_into_a_decision(self):
        with self.assertRaises(ValueError):
            validate_selection(ALERTS[:-2] + ',{"title":', "triage", {LINK})

    def test_tracking_parameters_resolve_to_original_source_only(self):
        original = LINK + "?id=42&utm_source=rss"
        self.assertEqual(resolve_source_link(LINK + "?id=42", {original}), original)
        for altered in (LINK + "?id=43", LINK + "/invented?id=42", LINK + "?id=42#other"):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                resolve_source_link(altered, {original})

    def test_required_content_is_checked(self):
        for field in ("title", "reason"):
            data = json.loads(ALERTS)
            data["alerts"][0][field] = " "
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_selection(json.dumps(data), "triage", {LINK})

    def test_schema_preserves_valid_empty_alerts(self):
        self.assertEqual(selection_schema("triage")["properties"]["alerts"]["minItems"], 0)
        self.assertEqual(selection_schema("synthesis")["properties"]["topics"]["minItems"], 1)


class ClientTests(unittest.TestCase):
    def setUp(self):
        keys = patch.multiple(gemini, GEMINI_API_KEY="test-key")
        keys.start()
        self.addCleanup(keys.stop)
        key = patch.object(openrouter, "OPENROUTER_API_KEY", "test-key")
        key.start()
        self.addCleanup(key.stop)

    @patch.object(gemini.requests, "post")
    def test_gemini_does_not_call_unreviewed_paid_models(self, post):
        with self.assertRaises(gemini.LLMError):
            gemini.generate("gemini-3.1-pro-preview", "s", "u")
        post.assert_not_called()

    @patch.object(gemini.requests, "post")
    def test_gemini_honors_daily_quota_and_retry_hint(self, post):
        post.return_value = response({"error": {"details": [
            {"retryDelay": "120s"},
        ]}}, status=429)
        with self.assertRaises(gemini.RateLimited) as minute:
            gemini.generate("gemini-3.5-flash-lite", "s", "u")
        self.assertEqual(minute.exception.cooldown_seconds, 120)
        post.return_value = response({"error": {"details": [{"violations": [
            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"},
        ]}]}}, status=429)
        with self.assertRaises(gemini.RateLimited) as daily:
            gemini.generate("gemini-3.5-flash-lite", "s", "u")
        self.assertEqual(daily.exception.cooldown_seconds, 86400)
        self.assertFalse(daily.exception.provider_wide)

    @patch.object(gemini.requests, "post")
    def test_gemini_payload_json_thinking_and_header_auth(self, post):
        post.return_value = gemini_response()
        result = gemini.generate("gemini-3.8-flash", "system", "user", 4096,
                                 response_schema=selection_schema("synthesis"), timeout=23)
        self.assertEqual(result, '{"alerts": []}')
        payload = post.call_args.kwargs
        self.assertNotIn("params", payload)
        self.assertEqual(payload["headers"]["x-goog-api-key"], "test-key")
        self.assertEqual(payload["timeout"], 23)
        generation = payload["json"]["generationConfig"]
        self.assertEqual(generation["responseMimeType"], "application/json")
        self.assertEqual(generation["thinkingConfig"]["thinkingLevel"], "LOW")
        self.assertFalse(generation["thinkingConfig"]["includeThoughts"])
        self.assertGreater(generation["maxOutputTokens"], 4096)
        self.assertNotIn("tools", payload["json"])

    @patch.object(gemini.requests, "post")
    def test_gemini_excludes_thought_parts(self, post):
        post.return_value = gemini_response(extra_parts=[{"text": "secret thoughts", "thought": True}])
        self.assertEqual(gemini.generate("gemini-3.5-flash-lite", "s", "u"), '{"alerts": []}')

    @patch.object(gemini.requests, "post")
    def test_gemini_rejects_truncation_and_safety_blocks(self, post):
        for finish in ("MAX_TOKENS", "SAFETY", "RECITATION"):
            post.return_value = gemini_response(finish=finish)
            with self.subTest(finish=finish), self.assertRaises(gemini.LLMError):
                gemini.generate("gemini-3.8-flash", "s", "u")

    @patch.object(gemini.requests, "post")
    def test_network_error_does_not_expose_key(self, post):
        post.side_effect = requests.ConnectionError("https://example.com/?key=test-key")
        with self.assertRaises(gemini.LLMError) as result:
            gemini.generate("gemini-3.8-flash", "s", "u")
        self.assertNotIn("test-key", str(result.exception))

    @patch.object(openrouter.requests, "post")
    def test_only_explicit_free_models_can_be_called(self, post):
        for model in ("openrouter/free", "openai/gpt-oss-20b:free", "google/gemma-4-31b-it",
                      "nvidia/nemotron-3.5-content-safety:free"):
            with self.subTest(model=model), self.assertRaises(gemini.LLMError):
                openrouter.generate(model, "s", "u")
        post.assert_not_called()

    @patch.object(openrouter.requests, "post")
    def test_openrouter_zero_price_caps_and_model_specific_formats(self, post):
        for model, expected_format in (
            ("nvidia/nemotron-3-super-120b-a12b:free", "json_schema"),
            ("google/gemma-4-31b-it:free", "json_object"),
            ("nvidia/nemotron-3-ultra-550b-a55b:free", None),
        ):
            post.return_value = openrouter_response(model=model.removesuffix(":free"))
            with self.subTest(model=model):
                openrouter.generate(model, "s", "u", response_schema=selection_schema("triage"))
                payload = post.call_args.kwargs["json"]
                self.assertEqual(payload["provider"]["max_price"],
                                 {"prompt": 0, "completion": 0, "request": 0})
                self.assertTrue(payload["provider"]["require_parameters"])
                self.assertEqual(payload.get("response_format", {}).get("type"), expected_format)
                self.assertNotIn("models", payload)
                self.assertNotIn("plugins", payload)

    @patch.object(openrouter.requests, "post")
    def test_openrouter_rejects_changed_model_or_incomplete_output(self, post):
        for reply in (openrouter_response(finish="length"),
                      openrouter_response(model="paid/model"),
                      response({"error": {"code": 429}})):
            post.return_value = reply
            with self.assertRaises(gemini.LLMError):
                openrouter.generate("google/gemma-4-31b-it:free", "s", "u")

    @patch.object(openrouter.requests, "post")
    def test_shared_quota_is_distinct_from_provider_backpressure(self, post):
        post.return_value = response(status=429, headers={"X-RateLimit-Limit": "50", "Retry-After": "120"})
        with self.assertRaises(gemini.RateLimited) as shared:
            openrouter.generate("google/gemma-4-31b-it:free", "s", "u")
        self.assertTrue(shared.exception.provider_wide)
        self.assertEqual(shared.exception.cooldown_seconds, 120)
        post.return_value = response(status=503)
        with self.assertRaises(gemini.RateLimited) as provider:
            openrouter.generate("google/gemma-4-31b-it:free", "s", "u")
        self.assertFalse(provider.exception.provider_wide)


class RouterTests(unittest.TestCase):
    def setUp(self):
        router._cooldowns.clear()
        self.addCleanup(router._cooldowns.clear)
        first = patch.object(gemini, "generate")
        second = patch.object(openrouter, "generate")
        self.gemini = first.start()
        self.openrouter = second.start()
        self.addCleanup(first.stop)
        self.addCleanup(second.stop)

    def triage(self):
        return digest.triage([ARTICLE])

    def test_task_specific_models_and_empty_alert_success(self):
        self.gemini.return_value = '{"alerts": []}'
        alerts, model, valid = self.triage()
        self.assertEqual((alerts, valid), ([], True))
        self.assertEqual(model, "gemini/gemini-3.5-flash-lite")
        self.gemini.assert_called_once()
        self.openrouter.assert_not_called()
        self.gemini.reset_mock()
        self.gemini.return_value = TOPICS
        topics, model = digest.synthesize([ARTICLE])
        self.assertEqual(model, "gemini/gemini-3.8-flash")
        self.assertEqual(topics[0].links, [("SME", LINK)])

    def test_invalid_json_safety_verdict_and_invented_link_trigger_fallback(self):
        invented = ALERTS.replace(LINK, "https://example.com/invented")
        for bad in ("safe", '{"safe": true}', invented, '{"alerts": null}'):
            self.gemini.reset_mock()
            self.gemini.side_effect = [bad, ALERTS]
            with self.subTest(bad=bad):
                alerts, model, valid = self.triage()
                self.assertTrue(valid)
                self.assertEqual(len(alerts), 1)
                self.assertEqual(model, "gemini/gemini-3.1-flash-lite")
                self.assertEqual(self.gemini.call_count, 2)

    def test_empty_digest_tries_next_model(self):
        self.gemini.side_effect = ['{"topics": []}', TOPICS]
        topics, model = digest.synthesize([ARTICLE])
        self.assertEqual(len(topics), 1)
        self.assertEqual(model, "gemini/gemini-3.5-flash")

    def test_model_stripping_tracking_keeps_source_and_avoids_extra_call(self):
        original = LINK + "?utm_source=rss"
        article = {**ARTICLE, "l": original}
        self.gemini.return_value = ALERTS
        alerts, _, valid = digest.triage([article])
        self.assertTrue(valid)
        self.assertEqual(alerts[0].links, [original])
        self.gemini.assert_called_once()
        self.gemini.reset_mock()
        self.gemini.return_value = TOPICS
        topics, _ = digest.synthesize([article])
        self.assertEqual(topics[0].links, [("SME", original)])
        self.gemini.assert_called_once()

    def test_unsupported_new_model_keeps_legacy_fallback(self):
        self.gemini.side_effect = [gemini.LLMError("HTTP 404"), '{"alerts": []}']
        self.assertEqual(self.triage()[1], "gemini/gemini-3.1-flash-lite")

    def test_gemini_outage_uses_free_openrouter(self):
        self.gemini.side_effect = gemini.LLMError("outage")
        self.openrouter.return_value = ALERTS
        self.assertEqual(self.triage()[1], "openrouter/nvidia/nemotron-3-super-120b-a12b:free")

    def test_all_bad_replies_fail_closed(self):
        self.gemini.return_value = "bad"
        self.openrouter.return_value = "bad"
        with self.assertRaises(router.AllModelsFailed):
            self.triage()

    def test_shared_openrouter_quota_stops_other_free_models(self):
        self.gemini.side_effect = gemini.LLMError("outage")
        self.openrouter.side_effect = gemini.RateLimited("daily quota", provider_wide=True)
        for _ in range(2):
            with self.assertRaises(router.AllModelsFailed):
                self.triage()
        self.openrouter.assert_called_once()

    def test_provider_limit_still_tries_different_openrouter_model(self):
        self.gemini.side_effect = gemini.LLMError("outage")
        self.openrouter.side_effect = [gemini.RateLimited("provider busy"), ALERTS]
        self.assertEqual(self.triage()[1], "openrouter/google/gemma-4-31b-it:free")

    def test_missing_key_skips_provider_not_entire_chain(self):
        self.gemini.side_effect = gemini.LLMError("missing key", retryable_next=False)
        self.openrouter.return_value = ALERTS
        self.triage()
        self.gemini.assert_called_once()
        self.openrouter.assert_called_once()

    def test_exhausted_time_budget_stops_calls(self):
        with patch.object(router.time, "monotonic", side_effect=[0, 181]):
            with self.assertRaises(router.AllModelsFailed):
                self.triage()
        self.gemini.assert_not_called()
        self.openrouter.assert_not_called()

    def test_slow_gemini_cannot_use_up_openrouter_time_reserve(self):
        clock = [0.0]

        def slow(*args, **kwargs):
            clock[0] += kwargs["timeout"]
            raise gemini.LLMError("timeout")

        self.gemini.side_effect = slow
        self.openrouter.return_value = ALERTS
        with patch.object(router.time, "monotonic", side_effect=lambda: clock[0]):
            self.assertEqual(self.triage()[1], "openrouter/nvidia/nemotron-3-super-120b-a12b:free")
        self.assertGreaterEqual(self.openrouter.call_args.kwargs["timeout"], 60)

    def test_model_config_keeps_legacy_and_only_free_variants(self):
        self.assertIn("gemini-3.1-flash-lite", config.GEMINI_SYNTHESIS_MODELS)
        self.assertTrue(all(model.endswith(":free") for model in config.OPENROUTER_MODELS))
        self.assertNotIn("openrouter/free", config.OPENROUTER_MODELS)
        self.assertTrue(set(config.GEMINI_TRIAGE_MODELS + config.GEMINI_SYNTHESIS_MODELS)
                        <= gemini._FREE_MODELS)
        self.assertTrue(set(config.OPENROUTER_MODELS) <= openrouter._FREE_MODELS)


class FailureIsolationTests(unittest.TestCase):
    def test_failed_synthesis_keeps_previous_digest_and_does_not_publish(self):
        import main

        state = Mock()
        state.get_meta.return_value = 0
        state.recent_window.return_value = [ARTICLE.copy() for _ in range(5)]
        state.recent_digest_headlines.return_value = ["Predošlý prehľad"]
        with patch.object(main, "synthesize", side_effect=router.AllModelsFailed(["outage"])), \
             patch.object(main, "send_digest") as publish, \
             patch.object(main, "_report_llm_outage"):
            status = main._run_synthesis(state, Mock(), Mock(), False, 15)
        self.assertIn("zlyhala", status)
        publish.assert_not_called()
        state.set_last_digest.assert_not_called()
        state.set_meta.assert_not_called()

    def test_failed_triage_is_logged_as_failure_not_no_breaking_news(self):
        import main

        state, selection_log = Mock(), Mock()
        state.recent_window.return_value = []
        with patch.object(main, "triage", side_effect=router.AllModelsFailed(["bad JSON"])), \
             patch.object(main, "send_alerts") as publish, \
             patch.object(main, "_report_llm_outage"):
            status = main._run_triage(state, Mock(), selection_log, [ARTICLE])
        self.assertIn("zlyhala", status)
        publish.assert_not_called()
        state.add_alerts.assert_not_called()
        self.assertFalse(selection_log.record_triage.call_args.kwargs["decision_valid"])
        self.assertFalse(selection_log.record_triage.call_args.kwargs["published"])


if __name__ == "__main__":
    unittest.main()
