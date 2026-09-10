# TASK-001 — Establish Versioned Lifecycle Persistence Foundations

## Objective

Extend the domain and SQLite/WAL persistence boundary with explicit canonical
lifecycle-version, scope, operation, evidence, and migration primitives while
preserving readable historical workflows without inferred facts.

## Scope

- Add provider-neutral domain values for canonical stages, lifecycle versions,
  scopes, operation fingerprints/results, migration receipts, and classified
  human-attention outcomes.
- Add additive, auditable SQLite migrations and transactional store APIs for
  lifecycle state, scope membership, immutable evidence references/hashes,
  capability request/result records, and durable operation identity.
- Preserve historical rows and their recorded behavior; implement idempotent
  compatibility migration with rollback/paused outcome for failure, partial, or
  ambiguous input.
- Add focused domain/store tests.

## Context

### Required

- `docs/waves/3-workflow-capability-orchestration/TECHSPEC.md` §3, §7, §9–§11
- `src/engineering_flow/domain.py`
- `src/engineering_flow/store.py`

### Optional

- `docs/architecture/architecture-overview.md` §7–§8
- `tests/test_domain.py`
- `tests/test_store.py`

## Requirements

- Keep all schema changes additive and compatible with existing Wave 1/2 rows.
  Persist lifecycle version rather than deriving it from stage or artifact
  shape; never manufacture missing planning, acceptance, or authority facts.
- Every lifecycle recording and dispatch primitive must accept a durable key
  plus fingerprint: identical replay returns its prior recorded result, while
  a reused key with changed input rejects. Unknown outcomes reconcile to known
  evidence or a classified human-attention state.
- Store immutable evidence references with SHA-256 and retain sanitized
  provider-native metadata only in adapter execution records. State, result or
  decision, and correlated event must be atomically recordable.
- Migration receipts must identify source/target versions and outcome. A failed
  migration must leave the historical record intact and require human action.

## Constraints

- The store records facts and does not choose lifecycle policy, authority, or
  provider routing. Preserve WAL, foreign keys, parameterized SQL, hash checks,
  UTC timestamps, and existing public planning/task behavior.
- Do not add governance-lineage policy, provider adapters, CLI commands, task
  loop changes, or delivery side effects.

## Expected Files/Areas

- `src/engineering_flow/domain.py`, `src/engineering_flow/store.py`
- `tests/test_domain.py`, `tests/test_store.py`

## Acceptance Criteria

- Existing databases open and historical workflows remain readable under their
  recorded lifecycle contract without fabricated canonical facts.
- Canonical workflow/scope, capability, evidence, operation, and migration
  records are durable, linked, hash-verified, and transactionally consistent.
- Identical operation replay is non-duplicating; divergent same-key requests
  reject; uncertain work cannot silently redispatch.
- Successful migration is auditable and idempotent; partial, invalid, or
  ambiguous migration preserves historical data and pauses safely.

## Validation

- `.venv/bin/python3 -m unittest discover -s tests -p 'test_domain.py' -q`
- `.venv/bin/python3 -m unittest discover -s tests -p 'test_store.py' -q`
- `.venv/bin/python3 -m compileall -q src`

## Dependencies

- None.

## Out of Scope

- Capability selection, authority semantics, lifecycle driving, remediation,
  CLI presentation, Wave 4 validation, and Git/PR behavior.
