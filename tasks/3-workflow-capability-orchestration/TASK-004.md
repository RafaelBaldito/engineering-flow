# TASK-004 — Orchestrate Canonical Lifecycle Progression

## Objective

Make the orchestration core the sole policy-controlled driver of the expanded
canonical lifecycle, using resolved capabilities and active governance facts.

## Scope

- Expand stage/policy orchestration for delivery planning, conditional
  architecture, Wave start, per-Wave TECHSPEC, task-plan gates, Wave/release
  review gates, release acceptance, and recorded delivery authorization
  precondition.
- Drive capability request, resolution, verified dispatch, normalized result,
  and advancement as controlled transactions; consume accepted Wave 2 task
  evidence without reinterpreting its `PENDING` task-plan cells.
- Implement resume/reconciliation and classified human-attention routing for
  invalid state, evidence, capability, authority, permission, or unknown work.
- Add focused orchestration tests for transition and compatibility behavior.

## Context

### Required

- `docs/waves/3-workflow-capability-orchestration/TECHSPEC.md` §3–§5, §7, §9
- `src/engineering_flow/orchestrator.py`
- `src/engineering_flow/store.py`
- `src/engineering_flow/runtime.py`

### Optional

- `src/engineering_flow/domain.py`
- `tests/test_orchestrator.py`
- `tests/test_planning_workflow.py`

## Requirements

- The orchestrator evaluates policy, resolves capability, validates normalized
  evidence and active authority, then atomically records result/state/event.
  No adapter or provider result may choose a transition.
- Conditional architecture routing must use persisted policy/evidence. Exact
  active TECHSPEC approval permits only canonical task planning; task-plan
  approval permits task registration and the existing bounded Wave 2 loop;
  neither needs a separate task-planning/execution authorization.
- Preserve historical lifecycle reads and route incompatible versions, missing
  facts, unsupported binding, unknown outcome, or invalid transition to
  actionable human attention rather than guessing or fallback.
- Model release acceptance and delivery authorization only as governance facts
  and future preconditions; do not invoke Wave 4 final validation or any Git/
  hosting action.

## Constraints

- Keep Wave 2 authoritative for task-local selection, test evidence, reviewer
  PASS, fix limits, and task acceptance. Do not alter bootstrap controller code
  or replace it with product architecture.

## Expected Files/Areas

- `src/engineering_flow/orchestrator.py`, `src/engineering_flow/domain.py`,
  `src/engineering_flow/store.py`, `src/engineering_flow/runtime.py`
- `tests/test_orchestrator.py`, `tests/test_planning_workflow.py`

## Acceptance Criteria

- A canonical workflow follows only legal persisted stages and demands the
  required active governance fact plus structured capability result at each
  gated transition.
- Conditional architecture and exact approval canonical-successor behavior are
  deterministic; a Wave PASS cannot start another Wave.
- Historical records remain readable without inferred governance, while new
  canonical workflows persist versioned state and resume without duplicate
  lifecycle/provider work.
- Any missing or ambiguous authority/evidence/capability outcome is classified,
  evented, and paused without delivery side effects.

## Validation

- `.venv/bin/python3 -m unittest discover -s tests -p 'test_orchestrator.py' -q`
- `.venv/bin/python3 -m unittest discover -s tests -p 'test_planning_workflow.py' -q`
- `.venv/bin/python3 -m compileall -q src`

## Dependencies

- TASK-001 — lifecycle persistence, migration, and operation reconciliation.
- TASK-002 — capability registry, resolver, and validated Codex bindings.
- TASK-003 — active governance/authority evaluation.

## Out of Scope

- Wave-review finding ownership, CLI presentation, task-loop redesign, final
  validation, commit, push, Pull Request creation, and merge.
