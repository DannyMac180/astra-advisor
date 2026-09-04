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
