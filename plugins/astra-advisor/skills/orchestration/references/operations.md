# Astra Advisor operations

This reference holds the operational details behind the short orchestration skill.
It describes capability selection and evidence rules; it does not define installed
roles, role files, task lanes, or an installer.

## Parent session

The primary session is GPT-6 Astra at whatever supported effort the user selected.
The invocation is authoritative. Do not require a particular effort, rewrite the
parent configuration, or claim a model/effort pin without runtime evidence. If the
session exposes model and effort metadata and the model is not `gpt-6-astra`, report
that mismatch as a selection prerequisite and do not claim Astra orchestration. If
metadata does not expose the model or effort, report the value as unobservable and
continue within the user's request without inventing confirmation.

After capability preflight and before the first implementation or delegation task
call, record the selected plan:

~~~text
ASTRA ROUTE
parent: <observed model or unobservable> / <observed effort or unobservable>
delegation: <none or each selected model and effort>
risk: <concise, task-specific rationale>
~~~

The declaration is a record of the current decision, not a fixed set of workflow
lanes. Update it only when new evidence changes the plan, and explain that evidence.

## Dynamic native delegation

Use the generic `collaboration.spawn_agent` only if the current environment exposes
that tool and its schema. Select a model and effort for each concrete, bounded,
independent deliverable from the task's risk, context, and available work. Pass the
chosen values explicitly:

~~~text
model: <selected supported model>
reasoning_effort: <selected supported effort>
fork_turns: none
~~~

Include a task name and a message that states the bounded ownership and expected
return. For example, this is one illustrative request shape; the model and effort
must be selected afresh for the actual task:

~~~json
{
  "task_name": "inspect_auth_boundary",
  "message": "Inspect the auth boundary in the owned files. Return findings, exact file references, and the checks you ran; do not edit outside that boundary.",
  "model": "gpt-5.6-luna",
  "reasoning_effort": "max",
  "fork_turns": "none"
}
~~~

The example does not prescribe a model, effort, task name, or number of subagents.
Use the current tool schema for any additional required fields and reject a request
whose selected controls cannot be enforced.

Do not rely on role names, predefined TOMLs, a role-to-model table, or a fixed count
cap. Dispatch only work whose files, interfaces, and acceptance evidence are clear;
keep useful planning, implementation, integration, or verification work in the
parent session while independent subagents run. Avoid assigning the same change or
check to both parent and subagent. Preserve concurrent edits and return each
subagent's actual result and evidence to the parent.

The following is the known capability snapshot for routing. It is guidance for a
selection, not a contract that overrides live tool metadata:

| Model | Efforts known in the current snapshot |
| --- | --- |
| `gpt-5.6-sol` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` |
| `gpt-5.6-terra` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` |
| `gpt-5.6-luna` | `low`, `medium`, `high`, `xhigh`, `max` |

Inspect the current tool metadata when selecting and invoking a subagent. A changed
live capability list wins over this snapshot. If the selected model, effort, explicit
spawn control, or required tool is unavailable, conflicting, or unobservable, fail
the affected delegation closed. Continue safe parent work when possible and report
the limitation; never silently substitute another model, effort, or tool.

## Evidence and review

The public spawn and thread metadata are authoritative for model and effort. Use
runtime introspection only to resolve a field that public metadata omitted, and report
the source of each value. Chosen values are not the same as runtime-confirmed values.

For substantial implementation, the parent first inspects the complete accumulated
diff and reruns the requested checks. It then starts a fresh read-only reviewer in a
new context. The reviewer can be `gpt-5.6-sol`, `gpt-5.6-terra`, or `gpt-5.6-luna`,
with an effort supported by live metadata, and must receive the exact change set,
interfaces, constraints, and verification evidence. Ask it to return:

~~~text
ASTRA REVIEW
VERDICT: ship | fix-first | rethink
REASON: <evidence-based reason>
FINDINGS: <precise findings or none>
RESIDUAL RISK: <remaining risk or none>
~~~

Treat `ship` as the only accepting verdict for substantial implementation. On
`fix-first`, the parent makes the correction, reruns verification, and obtains a new
fresh review. On `rethink`, revise the plan before claiming completion. The reviewer
must not edit files or implement its own fixes. Capture actual sandbox and permission
metadata when the host exposes them; do not claim enforced read-only isolation unless
it was observed.

## ChatGPT app and cloud boundaries

Native Codex subagents in the ChatGPT app are usable when the exposed tool schema
provides the needed controls. Separate app tasks require an explicit user request.
For an explicit Codex app project task, `mcp__codex_app__create_thread` supports
`model` and `thinking`; call `mcp__codex_app__list_projects` first, use a worktree by
default when the selected project is a Git repository, and use local otherwise.
Follow any explicit starting-state request exactly.

ChatGPT Work cloud `create_thread` does not accept `model` or `thinking`; omit both.
Cloud work therefore cannot currently promise arbitrary model or effort control. Do
not dispatch an incompatible model-pinned request there by default, and do not use an
API key, nested CLI, or fabricated tool as a workaround. A future native work tool is
usable only once its schema exposes the required controls.

## Reporting

For each delegation and review, report the selected model/effort, the evidence source,
the bounded deliverable, and the actual result. Keep chosen-but-unconfirmed values
separate from runtime-confirmed values. A parent acceptance claim requires its own
diff inspection and requested checks; a subagent's assertion alone is insufficient.

## Automatic lifecycle updates

Emit these updates in the user's conversation, not only in an internal log. They
apply to each implementer and each fresh reviewer, including failed dispatches:

~~~text
ASTRA DELEGATE <name>
task: <bounded deliverable and owned files>
requested: <model> / <effort>
reason: <why this work warrants this selection>

ASTRA RESULT <name> / <agent ID or unavailable>
status: <completed, failed, interrupted, or blocked; actual evidence>
requested: <model> / <effort>
observed: <model or unobservable> / <effort or unobservable>
evidence: <runtime metadata source or unavailable>
~~~

Do not equate a successful dispatch with completed work. Keep a record of agent IDs,
requested settings, runtime observations, result evidence, and any usage source.
Native metadata may expose neither realized settings nor billing-grade usage; say so.
No API keys, external inference CLIs, billing-account queries, or dashboard are needed.

## API-equivalent receipt policy

Every task completion requires a visible receipt, including a task with no delegation
or no accessible token telemetry. The calculator is Python standard library only:
[calculator](../../../scripts/cost_receipt.py),
[pricing snapshot](../../../pricing/2026-09-04.json).
Resolve these paths relative to this installed reference, not a guessed cache version.

Use only non-overlapping observed usage with an explicit source. Cumulative telemetry
snapshots are not additive calls. Never sum a parent-inclusive aggregate with child
totals. Do not turn message lengths into claimed observed usage. Missing usage or
rates must remain unavailable, and partial coverage must state which work is missing.
Whole-task coverage requires every parent and subagent call, including failed attempts,
review, corrections, and final parent work. If the final response's tokens cannot yet
be observed, identify the receipt's cutoff and do not claim whole-task completeness.

Cached input is a subset of total input. Output already contains reasoning tokens;
never add them a second time. Explicit per-call standard short-context eligibility
is required; unknown or unsupported long-context, service-tier, or cache-write pricing
must not silently inherit standard rates. Effort is recorded without a rate multiplier.

The snapshot records USD per million tokens and official source URLs, with a
2026-09-04 verification date supplied by the recording coordinator. It is a historical
snapshot, not a live-price guarantee; Sol rates are promotional. Disclose the snapshot
date and freshness when showing an estimate. Use a newly verified versioned snapshot
if current prices are required. Do not silently change historical receipts.

~~~text
API-EQUIVALENT COST RECEIPT
usage: <observed source and cutoff, partial, or unavailable with reason>
scope: <whole task only if complete; delegated-only or observed subset otherwise>
pricing: <snapshot date; historical USD estimate; Sol promotional if applicable>
routed: <USD estimate or unavailable>
same-token Astra repricing: <USD or unavailable>
same-token API price difference: <USD and percentage where valid, or unavailable>
limits: This is not a measured all-Astra counterfactual, actual net task savings,
        or a change in ChatGPT subscription charges or usage credits.
~~~

When no subagents ran, state `no delegation savings`. When no usage is exposed,
state `unavailable: native tools did not expose observed token usage`; never show
zero cost. Keep any illustrative fixture result visibly separate from live usage.

## Calculator input and execution

Run `python3 cost_receipt.py INPUT.json [--pricing PATH]` using the installed
calculator path above. It emits a JSON receipt; exit 0 includes calculated, partial,
and unavailable outcomes, while invalid input or pricing exits 2. Inspect the
receipt status instead of treating exit 0 as proof of complete usage.

The version 1 input contains:

- `schema_version: 1`, `task_id`, and `coverage` with `scope` (`whole_task` or
  `delegated_only`), `agent_roster_complete`, and `final_parent_usage_cutoff` booleans.
- `agents`: unique `agent_id`, `role` (`parent`, `delegate`, or `reviewer`), and
  `calls_complete`. Declare missing agents rather than omitting them to improve coverage.
- `calls`: globally unique `call_id`, declared `agent_id`, `model`, optional `effort`,
  and `aggregation: "atomic"`. Supply `usage.kind`, a non-empty `usage.source`, and
  `input_tokens`, `cached_input_tokens`, and `output_tokens` when known. Optional
  `reasoning_tokens` is already included in output. Missing values stay unknown.
- Each call also declares `context: "standard"` and `service_tier: "standard"`, with
  `context_source` and `service_tier_source` set to `observed` or `assumed`. If runtime
  tier metadata is null, a clearly disclosed standard-price scenario is permitted;
  never relabel that assumption as observed billing. Known nonstandard regimes
  are unsupported. Do not assume a workload eligible when evidence contradicts it.

See the [illustrative input](../../../examples/illustrative-usage.json) for an
executable fixture, distinct from observed task usage. Receipts preserve assumptions,
usage provenance, and per-agent coverage. Delegated-only scope includes reviewers;
whole-task scope needs an authoritative complete roster, complete calls for each
agent, a parent, and final parent usage. Solo work does not require an invented
reviewer. False completeness flags keep the result partial or unavailable.

For cumulative native telemetry, retain each snapshot as source evidence, skip exact
repeats, and derive atomic records only when the cumulative delta matches the
reported last-call usage for every token field. If events are missing, counters reset,
or aggregate ownership is unclear, mark that coverage unavailable rather than
inventing calls. Keep preparation-turn usage separate from the implementation turn
when that is the declared task scope.

The bundled calculator conservatively caps each call at 128,000 input tokens. This
is an implementation support boundary, not an official model pricing threshold.
Missing cache counts remain unknown; provide an explicit zero only when supported
by the usage source. Unknown usage fields are rejected to avoid ignoring cache writes.
