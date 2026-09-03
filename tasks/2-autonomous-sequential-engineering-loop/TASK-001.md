# TASK-001 — Establish Durable Task Definitions and Lifecycle Evidence

## Objective

Extend the provider-neutral domain and SQLite persistence boundary so an
approved Wave 1 task plan can become immutable, hash-verified, task-correlated
evidence that survives restart without duplicate lifecycle work.

## Scope

- Add Wave 2 stages, Developer/Reviewer roles, `TEST`/`REVIEW` failure
  classifications, task statuses, and immutable task, cycle, intervention,
  and task-artifact domain values in `domain.py`.
- Add additive SQLite migrations and transactional store APIs for task
  definitions, cycles, task artifacts, interventions, and task/cycle
  correlation on sessions, executions, and operations. Keep existing planning
  records and queries compatible.
- Implement deterministic parsing/validation support for the single
  `engineering-flow-task-plan` JSON fenced block and atomic import of its
  immutable definitions from an approved task-plan artifact.
- Persist canonical task evidence under the specified workflow workspace
  layout, verify recorded hashes on later reads, and provide the query/mutation
  primitives needed by orchestration for operation intent, completion,
  unknown recovery, acceptance, and task selection.
- Add focused domain/store tests for migrations, import validation,
  idempotency, canonical paths, evidence integrity, and transaction boundaries.

## Context

### Required

- `docs/waves/2-autonomous-sequential-engineering-loop/TECHSPEC.md` §4.1–§4.2 and §7
- `src/engineering_flow/domain.py`
- `src/engineering_flow/store.py`

### Optional

- `docs/architecture/architecture-overview.md` §3, §8–§9, and §12–§13
- `tests/test_domain.py`
- `tests/test_store.py`

## Requirements

- Add only the task-stage values and records specified in TECHSPEC §§4 and 7;
  do not reinterpret or rewrite a Wave 1 planning artifact. Persist each
  imported canonical definition JSON and SHA-256 with its source artifact ID
  and hash; a repeated source hash returns existing records, while a changed
  manifest after import is surfaced as a conflict/corruption condition.
- Reject import before provider execution unless Markdown has exactly one
  tagged manifest; its version, non-empty/unique ordered tasks, required
  strings/arrays, and optional context paths meet TECHSPEC §4.2. Canonicalize
  and validate every context path as an existing repository-relative file;
  reject escapes, directories, and canonical duplicates.
- Preserve SQLite WAL, foreign keys, single-writer transactions, UTC times,
  sanitization, and immutable hash verification. Use additive migrations at
  store open and retain compatibility with existing Wave 1 rows and public
  planning behavior.
- Store writes task evidence only to fixed canonical destinations selected by
  the store. Add stable task-operation handling so completed keys replay their
  recorded result and pending operations can be marked unknown without a new
  provider call.
- Supply atomic store operations sufficient for the orchestrator to record a
  task/cycle terminal result, associated evidence and events, task acceptance,
  and next-task eligibility without direct SQL or split acceptance/advance
  transactions.

## Constraints

- The store records decisions; it must not decide task progression, review
  policy, or provider retry behavior.
- Treat artifact text and provider-originated fields as untrusted. Do not let
  them choose artifact destinations or bypass canonical-root/hash checks.
- Use the standard library and parameterized SQL only. Do not add provider
  invocation, CLI parsing, Git/PR behavior, or a mutable second task plan.

## Acceptance Criteria

- Existing planning data opens successfully after migration, and new Wave 2
  task/cycle/session/execution/operation records retain their required links,
  uniqueness constraints, sanitized payloads, and UTC timestamps.
- A valid approved source artifact imports ordered immutable task records once;
  malformed, missing, duplicate, escaping, directory, unsupported-version,
  and changed-after-import manifests are rejected safely before any execution.
- Task definitions and task artifacts are stored at canonical workflow paths,
  have recorded SHA-256 values, and fail typed integrity checks when modified.
- Replaying a completed task operation does not create another execution,
  cycle, artifact, intervention, acceptance, or next-task launch; a recovered
  pending operation can be represented as unknown.
- Domain/store tests prove no provider- or Codex-specific type controls the
  persisted task lifecycle.

## Validation

- `python -m unittest discover -s tests -p 'test_domain.py'`
- `python -m unittest discover -s tests -p 'test_store.py'`
- `python -m compileall -q src`

## Dependencies

- None.

## Out of Scope

- Developer/Reviewer runtime execution, orchestration state transitions,
  execution-policy configuration, CLI commands, Wave review, and Git/PR work.
