#!/usr/bin/env python3
"""Create an API-equivalent cost receipt from bounded per-call usage JSON."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MILLION = Decimal("1000000")
ROLES = {"parent", "delegate", "reviewer"}
USAGE_KINDS = {"observed", "estimated", "partial", "unavailable"}
SOURCES = {"observed", "assumed"}


class ReceiptError(ValueError):
    """Raised for input that could produce a misleading receipt."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReceiptError(f"{label} must be a JSON object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReceiptError(f"{label} must be a JSON array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReceiptError(f"{label} must be a non-empty string")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ReceiptError(f"{label} must be a boolean")
    return value


def _tokens(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReceiptError(f"{label} must be an integer token count (booleans and non-finite values are invalid)")
    if value < 0:
        raise ReceiptError(f"{label} must be non-negative")
    return value


def _money(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ReceiptError(f"{label} must be a non-negative decimal string")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ReceiptError(f"{label} must be a valid decimal") from exc
    if not result.is_finite() or result < 0:
        raise ReceiptError(f"{label} must be finite and non-negative")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(
                handle,
                parse_float=Decimal,
                parse_constant=lambda raw: (_ for _ in ()).throw(
                    ReceiptError(f"non-finite JSON number is invalid: {raw}")
                ),
            )
    except OSError as exc:
        raise ReceiptError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReceiptError(f"invalid JSON in {path}: {exc}") from exc
    return _object(value, str(path))


def _load_pricing(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    snapshot = _read_json(path)
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ReceiptError("pricing.schema_version must equal 1")
    if snapshot.get("currency") != "USD" or snapshot.get("unit") != "per_million_tokens":
        raise ReceiptError("pricing must use USD per_million_tokens")
    if snapshot.get("eligibility") != "standard_short_context":
        raise ReceiptError("pricing eligibility must be standard_short_context")
    max_standard_input = _tokens(
        snapshot.get("implementation_max_input_tokens"),
        "pricing.implementation_max_input_tokens",
    )
    if max_standard_input == 0:
        raise ReceiptError("pricing.implementation_max_input_tokens must be positive")
    models = _object(snapshot.get("models"), "pricing.models")
    parsed: dict[str, dict[str, Any]] = {}
    for model, raw in models.items():
        name = _string(model, "pricing model name")
        entry = _object(raw, f"pricing.models.{name}")
        parsed_rates = {
            key: _decimal(entry[key], f"pricing.models.{name}.{key}")
            if key in entry
            else None
            for key in ("input", "cached_input", "output")
        }
        parsed[name] = {
            **parsed_rates,
            "promotional": _boolean(
                entry.get("promotional"), f"pricing.models.{name}.promotional"
            ),
            "source_url": _string(
                entry.get("source_url"), f"pricing.models.{name}.source_url"
            ),
            "freshness_disclosure": entry.get("freshness_disclosure"),
        }
        if parsed[name]["promotional"]:
            _string(
                parsed[name]["freshness_disclosure"],
                f"pricing.models.{name}.freshness_disclosure",
            )
    metadata = {
        "path": str(path),
        "snapshot_date": _string(snapshot.get("snapshot_date"), "pricing.snapshot_date"),
        "verified_on": _string(snapshot.get("verified_on"), "pricing.verified_on"),
        "currency": "USD",
        "unit": "per_million_tokens",
        "eligibility": "standard_short_context",
        "implementation_max_input_tokens": max_standard_input,
        "provenance": _object(snapshot.get("provenance"), "pricing.provenance"),
    }
    return parsed, metadata


def _validate_usage(raw: Any, call_label: str) -> dict[str, Any]:
    usage = _object(raw, f"{call_label}.usage")
    allowed_keys = {
        "kind",
        "source",
        "reason",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    }
    unknown_keys = sorted(set(usage) - allowed_keys)
    if unknown_keys:
        raise ReceiptError(
            f"{call_label}.usage contains unsupported fields: {', '.join(unknown_keys)}; cache-write telemetry is unsupported"
        )
    kind = _string(usage.get("kind"), f"{call_label}.usage.kind")
    if kind not in USAGE_KINDS:
        raise ReceiptError(
            f"{call_label}.usage.kind must be observed, estimated, partial, or unavailable"
        )
    source = _string(usage.get("source"), f"{call_label}.usage.source")
    token_keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")
    present = {key: _tokens(usage[key], f"{call_label}.usage.{key}") for key in token_keys if key in usage}

    if kind in {"observed", "estimated"}:
        for required in ("input_tokens", "cached_input_tokens", "output_tokens"):
            if required not in present:
                raise ReceiptError(f"{call_label}.usage.{required} is required for {kind} usage")
    elif kind == "partial":
        _string(usage.get("reason"), f"{call_label}.usage.reason")
        if not present:
            raise ReceiptError(f"{call_label}.usage partial data must include at least one token count")
    else:
        _string(usage.get("reason"), f"{call_label}.usage.reason")
        if present:
            raise ReceiptError(f"{call_label}.usage unavailable data must not include token counts")

    input_tokens = present.get("input_tokens")
    cached_tokens = present.get("cached_input_tokens")
    output_tokens = present.get("output_tokens")
    reasoning_tokens = present.get("reasoning_tokens")
    if input_tokens is None and "cached_input_tokens" in present:
        raise ReceiptError(f"{call_label}.usage.cached_input_tokens requires input_tokens")
    if input_tokens is not None and cached_tokens is not None and cached_tokens > input_tokens:
        raise ReceiptError(f"{call_label}.usage.cached_input_tokens must be a subset of input_tokens")
    if output_tokens is None and "reasoning_tokens" in present:
        raise ReceiptError(f"{call_label}.usage.reasoning_tokens requires output_tokens")
    if output_tokens is not None and reasoning_tokens is not None and reasoning_tokens > output_tokens:
        raise ReceiptError(f"{call_label}.usage.reasoning_tokens must be a subset of output_tokens")

    return {
        "kind": kind,
        "source": source,
        "reason": usage.get("reason"),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


def _price_known(
    usage: dict[str, Any], rates: dict[str, Any]
) -> tuple[Decimal, list[str], bool]:
    cost = Decimal(0)
    missing: list[str] = []
    priced_component = False
    input_tokens = usage["input_tokens"]
    cached = usage["cached_input_tokens"]
    if input_tokens is None or cached is None:
        if input_tokens is None:
            missing.append("input_tokens")
        if cached is None:
            missing.append("cached_input_tokens")
    else:
        cost += (Decimal(input_tokens - cached) * rates["input"] + Decimal(cached) * rates["cached_input"]) / MILLION
        priced_component = True
    output_tokens = usage["output_tokens"]
    if output_tokens is None:
        missing.append("output_tokens")
    else:
        cost += Decimal(output_tokens) * rates["output"] / MILLION
        priced_component = True
    return cost, missing, priced_component


def calculate_receipt(payload: dict[str, Any], pricing_path: Path) -> dict[str, Any]:
    """Validate payload and return a non-billing API-equivalent receipt."""
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ReceiptError("schema_version must equal 1")
    task_id = _string(payload.get("task_id"), "task_id")
    illustrative = payload.get("illustrative", False)
    if not isinstance(illustrative, bool):
        raise ReceiptError("illustrative must be a boolean")

    coverage_input = _object(payload.get("coverage"), "coverage")
    scope = _string(coverage_input.get("scope"), "coverage.scope")
    if scope not in {"whole_task", "delegated_only"}:
        raise ReceiptError("coverage.scope must be whole_task or delegated_only")
    roster_complete = _boolean(
        coverage_input.get("agent_roster_complete"), "coverage.agent_roster_complete"
    )
    parent_cutoff = _boolean(
        coverage_input.get("final_parent_usage_cutoff"),
        "coverage.final_parent_usage_cutoff",
    )

    agents_input = _array(payload.get("agents"), "agents")
    if not agents_input:
        raise ReceiptError("agents must not be empty")
    agents: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(agents_input):
        agent = _object(raw, f"agents[{index}]")
        agent_id = _string(agent.get("agent_id"), f"agents[{index}].agent_id")
        if agent_id in agents:
            raise ReceiptError(f"duplicate agent_id: {agent_id}")
        role = _string(agent.get("role"), f"agents[{index}].role")
        if role not in ROLES:
            raise ReceiptError(f"agents[{index}].role must be parent, delegate, or reviewer")
        agents[agent_id] = {
            "agent_id": agent_id,
            "role": role,
            "calls_complete": _boolean(
                agent.get("calls_complete"), f"agents[{index}].calls_complete"
            ),
        }

    calls_input = _array(payload.get("calls"), "calls")
    if not calls_input:
        raise ReceiptError("calls must not be empty; use an explicit unavailable call when telemetry is missing")
    rates, pricing_metadata = _load_pricing(pricing_path)
    call_ids: set[str] = set()
    calls_by_agent = {agent_id: 0 for agent_id in agents}
    call_results: list[dict[str, Any]] = []
    known_total = Decimal(0)
    any_priced_component = False

    for index, raw in enumerate(calls_input):
        call = _object(raw, f"calls[{index}]")
        allowed_call_keys = {
            "call_id",
            "agent_id",
            "model",
            "effort",
            "aggregation",
            "usage",
            "context",
            "context_source",
            "service_tier",
            "service_tier_source",
        }
        unknown_call_keys = sorted(set(call) - allowed_call_keys)
        if unknown_call_keys:
            raise ReceiptError(
                f"calls[{index}] contains unsupported fields: {', '.join(unknown_call_keys)}; cache-write telemetry is unsupported"
            )
        call_id = _string(call.get("call_id"), f"calls[{index}].call_id")
        if call_id in call_ids:
            raise ReceiptError(f"duplicate call_id: {call_id}")
        call_ids.add(call_id)
        agent_id = _string(call.get("agent_id"), f"calls[{index}].agent_id")
        if agent_id not in agents:
            raise ReceiptError(f"calls[{index}].agent_id is not in the declared agent roster: {agent_id}")
        calls_by_agent[agent_id] += 1
        aggregation = _string(call.get("aggregation"), f"calls[{index}].aggregation")
        if aggregation != "atomic":
            raise ReceiptError(
                f"calls[{index}].aggregation={aggregation!r} is unsupported; cumulative and parent-inclusive aggregates would double count"
            )
        context = call.get("context")
        if context != "standard":
            raise ReceiptError(f"calls[{index}].context must be standard; long-context pricing is unsupported")
        context_source = _string(call.get("context_source"), f"calls[{index}].context_source")
        if context_source not in SOURCES:
            raise ReceiptError(f"calls[{index}].context_source must be observed or assumed")
        tier = call.get("service_tier")
        if tier != "standard":
            raise ReceiptError(f"calls[{index}].service_tier must be standard; other or unknown tiers are unsupported")
        tier_source = _string(
            call.get("service_tier_source"), f"calls[{index}].service_tier_source"
        )
        if tier_source not in SOURCES:
            raise ReceiptError(f"calls[{index}].service_tier_source must be observed or assumed")
        model = _string(call.get("model"), f"calls[{index}].model")
        effort = call.get("effort")
        if effort is not None:
            effort = _string(effort, f"calls[{index}].effort")
        usage = _validate_usage(call.get("usage"), f"calls[{index}]")
        if (
            usage["input_tokens"] is not None
            and usage["input_tokens"]
            > pricing_metadata["implementation_max_input_tokens"]
        ):
            raise ReceiptError(
                f"calls[{index}].usage.input_tokens exceeds the conservative implementation boundary of "
                f"{pricing_metadata['implementation_max_input_tokens']}; long-context pricing is unsupported"
            )
        result: dict[str, Any] = {
            "call_id": call_id,
            "agent_id": agent_id,
            "role": agents[agent_id]["role"],
            "model": model,
            "effort": effort,
            "usage_kind": usage["kind"],
            "usage_source": usage["source"],
            "input_tokens": usage["input_tokens"],
            "cached_input_tokens": usage["cached_input_tokens"],
            "output_tokens": usage["output_tokens"],
            "reasoning_tokens_included_in_output": usage["reasoning_tokens"],
            "context": {"value": context, "source": context_source},
            "service_tier": {"value": tier, "source": tier_source},
        }
        model_rates = rates.get(model)
        if model_rates is None:
            result.update(status="unavailable", reason=f"no rate for model {model}")
        elif missing_rates := [
            name for name in ("input", "cached_input", "output") if model_rates[name] is None
        ]:
            result.update(
                status="unavailable",
                reason=f"missing {', '.join(missing_rates)} rate for model {model}",
            )
        elif usage["kind"] == "unavailable":
            result.update(status="unavailable", reason=usage["reason"])
        else:
            known_cost, missing, priced_component = _price_known(usage, model_rates)
            known_total += known_cost
            any_priced_component = any_priced_component or priced_component
            result["known_cost_usd"] = _money(known_cost) if priced_component else None
            if missing or usage["kind"] == "partial":
                result.update(
                    status="partial",
                    reason=usage["reason"],
                    missing_token_fields=missing,
                )
            elif usage["kind"] == "estimated":
                result.update(status="estimated", estimated_cost_usd=_money(known_cost))
            else:
                result.update(status="available", cost_usd=_money(known_cost))
            result["rate_source_url"] = model_rates["source_url"]
            result["promotional_rate"] = model_rates["promotional"]
            if model_rates["freshness_disclosure"]:
                result["freshness_disclosure"] = model_rates["freshness_disclosure"]
        call_results.append(result)

    coverage_reasons: list[str] = []
    parent_ids = [agent_id for agent_id, agent in agents.items() if agent["role"] == "parent"]
    if not roster_complete:
        coverage_reasons.append("agent roster is not asserted complete")
    incomplete_agents = [agent_id for agent_id, agent in agents.items() if not agent["calls_complete"]]
    if incomplete_agents:
        coverage_reasons.append("call enumeration is incomplete for: " + ", ".join(incomplete_agents))
    missing_call_agents = [agent_id for agent_id, count in calls_by_agent.items() if count == 0]
    if missing_call_agents:
        coverage_reasons.append("agents have no atomic or explicit unavailable call: " + ", ".join(missing_call_agents))
    if scope == "whole_task":
        if len(parent_ids) != 1:
            coverage_reasons.append("whole_task scope requires exactly one declared parent")
        if not parent_cutoff:
            coverage_reasons.append("whole_task scope requires a final parent usage cutoff")
    elif parent_ids:
        coverage_reasons.append("delegated_only scope must not include parent work")

    coverage_status = "complete" if not coverage_reasons else "unavailable"
    statuses = [result["status"] for result in call_results]
    all_observed_priced = all(status == "available" for status in statuses)
    all_priced = all(status in {"available", "estimated"} for status in statuses)
    receipt_status = "unavailable"
    if coverage_status == "complete" and all_observed_priced:
        receipt_status = "observed_tokens_api_estimate"
    elif coverage_status == "complete" and all_priced:
        receipt_status = "estimated"
    elif known_total > 0 or any(status in {"available", "estimated", "partial"} for status in statuses):
        receipt_status = "partial"

    comparison: dict[str, Any]
    has_subagent = any(agent["role"] in {"delegate", "reviewer"} for agent in agents.values())
    if not has_subagent:
        comparison = {
            "status": "unavailable",
            "reason": "no subagents; there is no delegation price difference to report",
            "claim": "no_delegation_savings",
        }
    elif coverage_status != "complete":
        comparison = {"status": "unavailable", "reason": "coverage is incomplete"}
    elif not all_observed_priced:
        comparison = {
            "status": "unavailable",
            "reason": "same-token comparison requires complete observed usage and rates for every in-scope call",
        }
    elif "gpt-6-astra" not in rates or any(
        rates["gpt-6-astra"].get(name) is None
        for name in ("input", "cached_input", "output")
    ):
        comparison = {"status": "unavailable", "reason": "Astra rate is unavailable"}
    else:
        astra_total = Decimal(0)
        astra_rates = rates["gpt-6-astra"]
        for raw in calls_input:
            usage = _validate_usage(raw["usage"], "comparison call")
            repriced, missing, _ = _price_known(usage, astra_rates)
            if missing:  # Defensive; all_observed_priced already excludes this.
                raise ReceiptError("internal comparison error: observed usage is incomplete")
            astra_total += repriced
        routed_total = sum((Decimal(result["cost_usd"]) for result in call_results), Decimal(0))
        comparison = {
            "status": "available",
            "label": "same-token API price comparison (not a measured all-Astra counterfactual)",
            "scope": scope,
            "routed_api_price_usd": _money(routed_total),
            "same_tokens_at_astra_api_price_usd": _money(astra_total),
            "api_price_difference_usd": _money(astra_total - routed_total),
            "limitations": [
                "This reprices the same observed tokens; it does not predict tokens an all-Astra run would use.",
                "It does not establish actual net task savings, quality changes, or speed changes.",
                "It does not represent ChatGPT subscription billing or usage-credit consumption.",
            ],
        }

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "illustrative": illustrative,
        "status": receipt_status,
        "coverage": {
            "scope": scope,
            "status": coverage_status,
            "agent_roster_complete": roster_complete,
            "final_parent_usage_cutoff": parent_cutoff,
            "declared_agent_ids": list(agents),
            "reasons": coverage_reasons,
        },
        "pricing": pricing_metadata,
        "accounting": {
            "aggregation": "unique atomic calls only",
            "cached_input": "included within input_tokens and charged at the cached-input rate",
            "reasoning": "included within output_tokens and not added again",
            "effort": "metadata only; no price multiplier applied",
        },
        "agents": list(agents.values()),
        "calls": call_results,
        "known_routed_cost_usd": _money(known_total) if any_priced_component else None,
        "same_token_api_price_comparison": comparison,
        "billing_notice": "API-equivalent estimate only; no ChatGPT bill or usage-credit deduction is implied.",
    }
    if receipt_status == "observed_tokens_api_estimate":
        receipt["routed_api_price_usd"] = _money(known_total)
    elif receipt_status == "estimated":
        receipt["estimated_routed_api_price_usd"] = _money(known_total)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="usage receipt input JSON")
    parser.add_argument(
        "--pricing",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "pricing" / "2026-09-04.json",
        help="versioned pricing snapshot JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = _read_json(args.input)
        result = calculate_receipt(payload, args.pricing)
    except ReceiptError as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "invalid", "errors": [str(exc)]}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
