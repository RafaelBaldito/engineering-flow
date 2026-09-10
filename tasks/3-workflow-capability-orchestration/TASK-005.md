# TASK-005 — Route Review Remediation and Acceptance Safely

## Objective

Implement deterministic Wave/release review remediation routing and acceptance
invalidation without changing Wave 2 task-local remediation mechanics.

## Scope

- Define normalized Wave/final review result and finding records with decision,
  blocking findings, owner scope, evidence references, and operation identity.
- Implement routing policy that returns an eligible owning prior scope only
  when ownership and necessary active authority are unambiguous; otherwise
  creates human attention.
- Invalidate affected acceptance on remediation, require the applicable fresh
  review, record Wave/release acceptance only after required PASS, and add
  focused tests.

## Context

### Required

- `docs/waves/3-workflow-capability-orchestration/TECHSPEC.md` §5–§6 and §9–§10
- `src/engineering_flow/orchestrator.py`
- `src/engineering_flow/store.py`
- `src/engineering_flow/domain.py`

### Optional

- `tests/test_orchestrator.py`
- `tests/test_store.py`

## Requirements

- Keep task `FIX_REQUIRED` exclusively on the accepted Wave 2 task-local
  route. Only Wave/final review results enter this task's deterministic policy.
- Routing must not manufacture authorization, silently reopen a future Wave,
  bypass a human gate, or act on missing/ambiguous ownership. Persist its
  decision and correlated evidence before any eligible redispatch.
- A remediation result atomically invalidates only its affected acceptance;
  completed evidence remains immutable, and the applicable review must repeat
  before a new acceptance can become active.

## Constraints

- Do not implement task developer/reviewer dispatch, review/fix limits, CLI
  parsing, final validation, delivery preparation, Git/PR work, or merge.

## Expected Files/Areas

- `src/engineering_flow/orchestrator.py`, `src/engineering_flow/store.py`,
  `src/engineering_flow/domain.py`
- `tests/test_orchestrator.py`, `tests/test_store.py`

## Acceptance Criteria

- Structured review results retain scope, operation, findings, and evidence;
  malformed or unsupported results cannot alter acceptance or routing.
- Task-local fixes remain Wave 2 behavior; Wave/final `FIX_REQUIRED` routes
  only to a uniquely eligible owned prior scope with required active authority.
- Ambiguous ownership, authority, ordering, or unsupported remediation pauses
  safely with a required human action.
- Remediation invalidates the targeted acceptance, preserves audit history, and
  requires a fresh authoritative review PASS before reacceptance.

## Validation

- `.venv/bin/python3 -m unittest discover -s tests -p 'test_orchestrator.py' -q`
- `.venv/bin/python3 -m unittest discover -s tests -p 'test_store.py' -q`
- `.venv/bin/python3 -m compileall -q src`

## Dependencies

- TASK-003 — decision lineage, active authority, and invalidation primitives.
- TASK-004 — canonical stage and review integration points.

## Out of Scope

- Task execution/fix implementation, future-Wave activation, CLI, external
  delivery, final validation, and merge.
