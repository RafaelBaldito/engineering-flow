# TASK-007 — Prove Canonical Lifecycle Compatibility and Safety

## Objective

Add deterministic cross-component evidence that the completed Wave 3 control
plane enforces its canonical lifecycle, governance, compatibility, recovery,
and no-delivery-side-effect boundaries.

## Scope

- Add offline integration tests using temporary SQLite/worktree fixtures and
  deterministic runtime fakes; refactor test helpers only when necessary.
- Cover canonical capability resolution, conditional architecture routing,
  exact evidence/scope authority, revocation/supersession, Wave 2 evidence
  consumption, remediation/re-review, resume/reconciliation, migrations, and
  CLI/event correlation.
- Add regression coverage proving no Wave 4 Git/hosting operation is callable
  and delivery authorization alone has no side effect; run the complete suite.

## Context

### Required

- `docs/waves/3-workflow-capability-orchestration/TECHSPEC.md` §10–§11
- `src/engineering_flow/orchestrator.py`
- `src/engineering_flow/store.py`
- `tests/test_orchestrator.py`
- `tests/test_cli.py`

### Optional

- `tests/test_task_lifecycle.py`
- `tests/test_store.py`
- `tests/test_runtime.py`

## Requirements

- Tests remain deterministic, standard-library `unittest`, offline, and free
  of live Codex credentials, network, commits, pushes, PRs, or merges.
- Verify every uncertain, invalid, unsupported, duplicate, conflicting, or
  ambiguous lifecycle/governance/remediation condition pauses with durable
  classified evidence rather than inferring, redispatching, or falling back.
- Exercise historical read compatibility and idempotent migration success and
  failure/rollback paths. Preserve Wave 1/2 regression behavior.

## Constraints

- This is integration/acceptance-focused validation, not a vehicle for new
  production features or TECHSPEC changes. Report defects to their owning task
  instead of expanding scope.

## Expected Files/Areas

- New or extended integration coverage under `tests/`, principally
  `tests/test_orchestrator.py`, `tests/test_store.py`, `tests/test_cli.py`, and
  `tests/test_runtime.py`; test helpers only where necessary.

## Acceptance Criteria

- Integration scenarios prove only resolved compatible capabilities dispatch,
  providers cannot advance state, and canonical gates require exact active
  governance/evidence.
- Tests prove revocation/supersession and remediation invalidate only affected
  downstream eligibility, require fresh authority/review, and preserve history.
- Resume/replay/migration tests prove no duplicated lifecycle result and no
  inferred historical fact; every unsafe uncertainty becomes human attention.
- CLI/event tests prove correlated sanitized observability, and regression
  tests prove Wave 4 external delivery cannot be called in Wave 3.
- The complete repository test suite passes.

## Validation

- `.venv/bin/python3 -m unittest discover -s tests -q`
- `.venv/bin/python3 -m compileall -q src`

## Dependencies

- TASK-001 through TASK-006 — all Wave 3 implementation seams under test.

## Out of Scope

- Production feature work beyond focused test helpers, Wave review/acceptance,
  final release validation, Git delivery, Pull Requests, and merge.
