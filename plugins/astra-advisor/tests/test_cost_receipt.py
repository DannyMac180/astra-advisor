from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / "scripts" / "cost_receipt.py"
PRICING = PLUGIN / "pricing" / "2026-09-04.json"
EXAMPLE = PLUGIN / "examples" / "illustrative-usage.json"
SPEC = importlib.util.spec_from_file_location("cost_receipt", SCRIPT)
assert SPEC and SPEC.loader
cost_receipt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cost_receipt)


def atomic_call(
    call_id: str,
    agent_id: str,
    model: str,
    *,
    input_tokens: int = 1000,
    cached_input_tokens: int = 100,
    output_tokens: int = 200,
    reasoning_tokens: int | None = 50,
) -> dict:
    usage = {
        "kind": "observed",
        "source": "test telemetry",
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
    }
    if reasoning_tokens is not None:
        usage["reasoning_tokens"] = reasoning_tokens
    return {
        "call_id": call_id,
        "agent_id": agent_id,
        "model": model,
        "effort": "high",
        "aggregation": "atomic",
        "context": "standard",
        "context_source": "observed",
        "service_tier": "standard",
        "service_tier_source": "assumed",
        "usage": usage,
    }


def whole_task() -> dict:
    return {
        "schema_version": 1,
        "task_id": "test-task",
        "coverage": {
            "scope": "whole_task",
            "agent_roster_complete": True,
            "final_parent_usage_cutoff": True,
        },
        "agents": [
            {"agent_id": "p", "role": "parent", "calls_complete": True},
            {"agent_id": "d", "role": "delegate", "calls_complete": True},
            {"agent_id": "r", "role": "reviewer", "calls_complete": True},
        ],
        "calls": [
            atomic_call("p1", "p", "gpt-6-astra"),
            atomic_call(
                "d1",
                "d",
                "gpt-5.6-luna",
                input_tokens=2000,
                cached_input_tokens=500,
                output_tokens=300,
                reasoning_tokens=75,
            ),
            atomic_call(
                "r1",
                "r",
                "gpt-5.6-sol",
                input_tokens=1000,
                cached_input_tokens=0,
                output_tokens=100,
                reasoning_tokens=None,
            ),
        ],
    }


class CostReceiptTests(unittest.TestCase):
    def calculate(self, payload: dict) -> dict:
        return cost_receipt.calculate_receipt(payload, PRICING)

    def assert_invalid(self, payload: dict, text: str) -> None:
        with self.assertRaisesRegex(cost_receipt.ReceiptError, text):
            self.calculate(payload)

    def test_exact_decimal_accounting_and_same_token_comparison(self) -> None:
        result = self.calculate(whole_task())

        self.assertEqual(result["status"], "observed_tokens_api_estimate")
        self.assertEqual(result["routed_api_price_usd"], "0.02577")
        comparison = result["same_token_api_price_comparison"]
        self.assertEqual(comparison["scope"], "whole_task")
        self.assertEqual(comparison["same_tokens_at_astra_api_price_usd"], "0.0646")
        self.assertEqual(comparison["api_price_difference_usd"], "0.03883")
        self.assertIn("not a measured", comparison["label"])
        self.assertTrue(result["calls"][2]["promotional_rate"])
        self.assertIsNone(result["calls"][2]["reasoning_tokens_included_in_output"])

    def test_cached_and_reasoning_subsets_are_not_double_counted(self) -> None:
        payload = whole_task()
        payload["agents"] = [{"agent_id": "p", "role": "parent", "calls_complete": True}]
        payload["calls"] = [
            atomic_call(
                "p1",
                "p",
                "gpt-6-astra",
                input_tokens=1000,
                cached_input_tokens=1000,
                output_tokens=100,
                reasoning_tokens=100,
            )
        ]
        result = self.calculate(payload)
        self.assertEqual(result["routed_api_price_usd"], "0.006")
        self.assertEqual(
            result["same_token_api_price_comparison"]["claim"],
            "no_delegation_savings",
        )

    def test_whole_task_coverage_requires_complete_roster_calls_and_cutoff(self) -> None:
        payload = whole_task()
        payload["coverage"]["agent_roster_complete"] = False
        payload["coverage"]["final_parent_usage_cutoff"] = False
        payload["agents"][2]["calls_complete"] = False
        payload["calls"] = payload["calls"][:2]

        result = self.calculate(payload)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"]["status"], "unavailable")
        reasons = " ".join(result["coverage"]["reasons"])
        self.assertIn("roster", reasons)
        self.assertIn("cutoff", reasons)
        self.assertIn("r", reasons)
        self.assertNotIn("routed_api_price_usd", result)

    def test_delegated_only_includes_delegate_and_reviewer(self) -> None:
        payload = whole_task()
        payload["coverage"]["scope"] = "delegated_only"
        payload["coverage"]["final_parent_usage_cutoff"] = False
        payload["agents"] = payload["agents"][1:]
        payload["calls"] = payload["calls"][1:]

        result = self.calculate(payload)
        self.assertEqual(result["coverage"]["status"], "complete")
        self.assertEqual(result["same_token_api_price_comparison"]["scope"], "delegated_only")

    def test_unknown_usage_is_unavailable_not_zero(self) -> None:
        payload = whole_task()
        payload["calls"][0]["usage"] = {
            "kind": "unavailable",
            "source": "runtime omitted usage",
            "reason": "no token telemetry",
        }
        payload["calls"][1]["usage"] = deepcopy(payload["calls"][0]["usage"])
        payload["calls"][2]["usage"] = deepcopy(payload["calls"][0]["usage"])

        result = self.calculate(payload)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["known_routed_cost_usd"])
        self.assertEqual(result["same_token_api_price_comparison"]["status"], "unavailable")

    def test_partial_usage_reports_only_known_output_cost(self) -> None:
        payload = whole_task()
        payload["calls"][0]["usage"] = {
            "kind": "partial",
            "source": "partial telemetry",
            "reason": "input and cached-input counts omitted",
            "output_tokens": 200,
            "reasoning_tokens": 50,
        }
        result = self.calculate(payload)
        first = result["calls"][0]
        self.assertEqual(first["status"], "partial")
        self.assertEqual(first["known_cost_usd"], "0.01")
        self.assertEqual(first["missing_token_fields"], ["input_tokens", "cached_input_tokens"])

    def test_missing_rate_is_unavailable(self) -> None:
        payload = whole_task()
        payload["calls"][1]["model"] = "gpt-unknown"
        result = self.calculate(payload)
        self.assertEqual(result["calls"][1]["status"], "unavailable")
        self.assertEqual(result["status"], "partial")

    def test_missing_individual_rate_is_unavailable_but_invalid_rate_is_rejected(self) -> None:
        snapshot = json.loads(PRICING.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pricing.json"
            del snapshot["models"]["gpt-5.6-luna"]["output"]
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            result = cost_receipt.calculate_receipt(whole_task(), path)
            self.assertEqual(result["calls"][1]["status"], "unavailable")
            self.assertIn("missing output rate", result["calls"][1]["reason"])

            snapshot["models"]["gpt-5.6-luna"]["output"] = "not-a-rate"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaisesRegex(cost_receipt.ReceiptError, "valid decimal"):
                cost_receipt.calculate_receipt(whole_task(), path)

    def test_rejects_duplicate_and_non_atomic_calls(self) -> None:
        payload = whole_task()
        payload["calls"][1]["call_id"] = "p1"
        self.assert_invalid(payload, "duplicate call_id")

        payload = whole_task()
        payload["calls"][1]["aggregation"] = "cumulative"
        self.assert_invalid(payload, "would double count")
        payload = whole_task()
        payload["calls"][1]["aggregation"] = "parent_inclusive"
        self.assert_invalid(payload, "would double count")

    def test_rejects_unknown_cache_write_fields_and_unsupported_eligibility(self) -> None:
        for field in ("cache_write_tokens", "cache_write_input_tokens"):
            payload = whole_task()
            payload["calls"][0]["usage"][field] = 1
            self.assert_invalid(payload, "cache-write telemetry is unsupported")
        payload = whole_task()
        payload["calls"][0]["cache_write_tokens"] = 1
        self.assert_invalid(payload, "cache-write telemetry is unsupported")

        payload = whole_task()
        payload["calls"][0]["context"] = "long"
        self.assert_invalid(payload, "long-context pricing is unsupported")
        payload = whole_task()
        payload["calls"][0]["service_tier"] = None
        self.assert_invalid(payload, "other or unknown tiers are unsupported")

    def test_rejects_unsafe_token_values_and_oversized_standard_context(self) -> None:
        cases = [
            ("input_tokens", True, "integer token count"),
            ("input_tokens", -1, "non-negative"),
            ("cached_input_tokens", 1001, "subset"),
            ("reasoning_tokens", 201, "subset"),
            ("input_tokens", 128001, "implementation boundary"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field, value=value):
                payload = whole_task()
                payload["calls"][0]["usage"][field] = value
                self.assert_invalid(payload, message)

    def test_complete_usage_requires_explicit_cached_count(self) -> None:
        payload = whole_task()
        del payload["calls"][0]["usage"]["cached_input_tokens"]
        self.assert_invalid(payload, "cached_input_tokens is required")

    def test_estimated_tokens_are_labeled_and_not_compared(self) -> None:
        payload = whole_task()
        payload["calls"][1]["usage"]["kind"] = "estimated"
        result = self.calculate(payload)
        self.assertEqual(result["status"], "estimated")
        self.assertEqual(result["calls"][1]["status"], "estimated")
        self.assertEqual(result["same_token_api_price_comparison"]["status"], "unavailable")

    def test_cli_outputs_json_and_honors_optional_pricing_path(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), str(EXAMPLE), "--pricing", str(PRICING)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["illustrative"])
        self.assertEqual(result["pricing"]["snapshot_date"], "2026-09-04")

    def test_cli_rejects_nonfinite_json_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text('{"schema_version": 1, "input_tokens": NaN}', encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("non-finite", json.loads(completed.stdout)["errors"][0])


if __name__ == "__main__":
    unittest.main()
