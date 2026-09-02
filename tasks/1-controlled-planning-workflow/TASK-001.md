# TASK-001 — Establish the Durable Workflow Core

## Objective

Create the provider-neutral domain model and durable local persistence layer
that make workflow state, artifacts, approvals, operations, and sanitized
events authoritative across process restarts.

## Scope

- Bootstrap the `src/engineering_flow/` package.
- Implement `domain.py` immutable value objects, enums, and typed failures for
  the Wave 1 workflow, stages, approvals, roles, artifacts, executions,
  operations, events, and failure classifications.
- Implement `sanitization.py` redaction for configured secret values and
  key/token/password-like values before retained or displayed diagnostics.
- Implement `store.py` with SQLite WAL mode, foreign keys, a single-writer
  transaction guard, the specified durable records, append-only artifact
  revisions, SHA-256 verification, monotonic workflow events, deterministic
  operation keys, and read/query APIs required by orchestration and CLI.
- Add focused `unittest` coverage for schema creation, transactional writes,
  idempotency, artifact integrity/corruption, event ordering, and sanitization.

## Context

### Required

- `docs/waves/1-controlled-planning-workflow/TECHSPEC.md` §3, §4.1, §6, and §8
- `docs/architecture/architecture-overview.md` §8–§9 and §12–§13
- `pyproject.toml`

### Optional

- `docs/waves/1-controlled-planning-workflow/TECHSPEC.md` §9

## Requirements

- Enable WAL mode and foreign-key enforcement for the single database at the
  application-owned workspace path; use parameterized SQL exclusively.
- Persist all minimum records and required uniqueness constraints from
  TECHSPEC §6, with UTC ISO-8601 timestamps and event sequence monotonic per
  workflow.
- Create generation-operation and execution intent records in one transaction;
  expose atomic APIs the orchestrator can use for completion, failure, approval,
  and reconciliation without direct SQL in higher layers.
- Write artifact files only to orchestrator-selected, revisioned destinations;
  commit their SHA-256 with the authoritative artifact record. Verify the hash
  before artifact display and raise a typed corruption failure on mismatch.
- Keep provider behavior, subprocess invocation, state-transition decisions,
  and CLI parsing out of this task’s production modules.

## Constraints

- Standard library only; do not add dependencies.
- Never persist raw environment variables, unredacted provider stderr, or
  secrets. A locked database must surface as a recoverable `persistence`
  failure, never cause creation of a replacement database.
- Preserve the architecture contract that only orchestration decides lifecycle
  progression, even though the store records its decisions.

## Acceptance Criteria

- The domain expresses every Wave 1 stage, status, approval decision/policy,
  role, and specified failure classification without Codex-specific types.
- A new database has all required durable records, constraints, WAL, and
  foreign-key behavior.
- Replaying a completed operation key or approval cannot create a duplicate
  recorded side effect.
- Artifact revisions are immutable, hash-verified on read, and a modified file
  results in a typed corruption failure.
- Persisted event payloads are sanitized and maintain a strictly increasing
  sequence for each workflow.

## Validation

- `python -m unittest discover -s tests -p 'test_domain.py'`
- `python -m unittest discover -s tests -p 'test_store.py'`
- `python -m unittest discover -s tests -p 'test_sanitization.py'`
- `python -m compileall src`

## Dependencies

- None.

## Out of Scope

- Provider execution, orchestration transitions, configuration parsing, and
  command-line behavior.
