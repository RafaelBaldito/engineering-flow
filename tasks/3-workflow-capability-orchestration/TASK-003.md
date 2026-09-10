# TASK-003 — Persist Governance Facts and Active Authority Lineage

## Objective

Provide immutable auditable decisions and deterministic active-authority
evaluation for approvals, acceptance, authorization, revocation, and
supersession.

## Scope

- Implement domain/store records and APIs for the TECHSPEC §5 decision types,
  actor/audit metadata, exact scope, predecessor facts, evidence hashes, and
  affected decision links.
- Implement active authority evaluation, including evidence validation,
  scope-match, ordering, revocation, supersession, conflict detection, and
  downstream invalidation boundaries.
- Record correlated governance events atomically and add focused tests.

## Context

### Required

- `docs/waves/3-workflow-capability-orchestration/TECHSPEC.md` §5 and §7
- `src/engineering_flow/domain.py`
- `src/engineering_flow/store.py`

### Optional

- `docs/architecture/architecture-overview.md` §3–§4, §7
- `tests/test_store.py`

## Requirements

- Decision records are append-only and include workflow, release/Wave/task
  scope, lifecycle version, operation ID, status/decision, identifiable actor,
  timestamp, exact evidence references/hashes, predecessors, and affected IDs.
- Active authority exists only with validated evidence, exact matching scope,
  no revocation, and no later valid supersession. Duplicate active authority,
  conflicting records, or uncertain ordering must produce human attention.
- Revocation/supersession retains history and completed evidence, atomically
  invalidates only dependent downstream action eligibility, and requires fresh
  authority before redispatch. It must not delete records or reopen unrelated
  or future scope.

## Constraints

- No external identity/authentication technology is selected. Provider output
  is evidence, never authority or a transition instruction.
- Do not implement stage driving, Wave 2 acceptance internals, remediation
  ownership routing, CLI argument handling, or Wave 4 side effects.

## Expected Files/Areas

- `src/engineering_flow/domain.py`, `src/engineering_flow/store.py`
- `tests/test_domain.py`, `tests/test_store.py`

## Acceptance Criteria

- Every required decision type can be recorded once with complete auditable
  scope, actor, predecessor, hash, and correlation information.
- Missing/invalid/mismatched evidence and ambiguous/conflicting lineage cannot
  yield an active authority.
- Revocation and supersession preserve history, emit audit evidence, invalidate
  only dependent eligibility atomically, and block redispatch pending fresh
  authority.
- No historical missing governance fact is inferred.

## Validation

- `.venv/bin/python3 -m unittest discover -s tests -p 'test_domain.py' -q`
- `.venv/bin/python3 -m unittest discover -s tests -p 'test_store.py' -q`
- `.venv/bin/python3 -m compileall -q src`

## Dependencies

- TASK-001 — versioned scope, evidence, operations, transactions, and events.

## Out of Scope

- Capability binding, lifecycle dispatch, review remediation, CLI, final
  validation, commit, push, Pull Request, and merge.
