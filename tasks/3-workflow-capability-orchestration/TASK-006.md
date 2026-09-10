# TASK-006 — Expose Governed Lifecycle Commands and Observability

## Objective

Extend the thin CLI and projections so operators can submit validated governed
decisions and inspect authoritative, correlated, sanitized lifecycle facts.

## Scope

- Extend configuration/composition only as needed for canonical lifecycle
  policy and configured capability bindings.
- Implement validated `approve`, `reject`, `authorize`, `revoke`, `supersede`,
  `resume`, and intervention command inputs that identify scope and evidence
  and delegate to orchestration services.
- Extend status/log projections and provider-neutral events for lifecycle,
  stage, capability, decision, authorization, acceptance, remediation,
  session/execution/test/review correlation.
- Add focused CLI/config tests.

## Context

### Required

- `docs/waves/3-workflow-capability-orchestration/TECHSPEC.md` §7–§10
- `src/engineering_flow/cli.py`
- `src/engineering_flow/config.py`
- `src/engineering_flow/orchestrator.py`

### Optional

- `src/engineering_flow/store.py`
- `tests/test_cli.py`
- `tests/test_config.py`

## Requirements

- Commands must validate target workflow/scope, identifiable actor, action,
  and hash-bound evidence references; they must never accept free-form agent
  prose as authority or embed lifecycle policy.
- Status/log views must read persisted authoritative facts, expose sanitized
  correlation IDs and actionable human-attention information, and never expose
  secrets or provider-only control data.
- Event emission stays provider-neutral and durable/correlated with the
  corresponding transaction. Preserve existing command compatibility where the
  recorded lifecycle version requires it.

## Constraints

- The CLI is a thin client. Do not implement authority evaluation, routing,
  provider dispatch, Wave 2 loop behavior, final validation, or delivery side
  effects in CLI/config code.

## Expected Files/Areas

- `src/engineering_flow/cli.py`, `src/engineering_flow/config.py`, and thin
  composition points in `src/engineering_flow/orchestrator.py`
- `tests/test_cli.py`, `tests/test_config.py`

## Acceptance Criteria

- Each authorized lifecycle decision command rejects missing/invalid scope or
  evidence and delegates valid requests to the orchestration core only.
- Status/log output exposes current version/stage, active authority and
  acceptance/remediation facts, correlated events, and human actions without
  deriving progress from provider prose.
- Events and projections retain sanitization and monotonic workflow correlation
  across resume/replay, with legacy workflows still inspectable.
- No CLI command can commit, push, create a Pull Request, merge, or treat a
  delivery authorization record as an external side effect.

## Validation

- `.venv/bin/python3 -m unittest discover -s tests -p 'test_cli.py' -q`
- `.venv/bin/python3 -m unittest discover -s tests -p 'test_config.py' -q`
- `.venv/bin/python3 -m compileall -q src`

## Dependencies

- TASK-002 — capability/binding configuration and events.
- TASK-003 — governed decision and authority service APIs.
- TASK-004 — lifecycle services and projections.
- TASK-005 — remediation/acceptance facts.

## Out of Scope

- New UI, identity provider, provider execution, task-loop changes, Wave 4
  final validation, Git/hosting delivery, and merge.
