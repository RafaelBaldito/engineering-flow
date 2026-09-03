# TASK-005 — Prove the End-to-End Durable Task Lifecycle

## Objective

Add deterministic cross-component evidence that the completed Wave 2 control
plane satisfies sequential execution, independent review, remediation limits,
restart safety, observability, and Wave 1 regression requirements.

## Scope

- Add a focused task-lifecycle integration test module using deterministic
  provider/runtime fakes and temporary Git-worktree fixtures; refactor shared
  test helpers only when this reduces duplication without changing production
  behavior.
- Exercise a valid approved multi-task manifest from `READY_FOR_WAVE_2` to
  `TASKS_READY_FOR_WAVE_REVIEW`, including exact-test gating, independent
  sessions, review-fix-re-review, and no Git/PR side effects.
- Exercise all required human-attention and recovery boundaries: malformed or
  legacy/escaping plans, invalid payloads, failed tests, exhausted review
  limit, explicit intervention, provider failure, and restart at pending,
  post-artifact, post-review, and post-acceptance boundaries.
- Verify CLI status/log task projections and retain Wave 1 planning regression
  coverage. Record the TECHSPEC §10 disposable-repository manual acceptance
  procedure in existing project documentation if an appropriate location is
  already established; do not run live Codex in automated validation.

## Context

### Required

- `docs/waves/2-autonomous-sequential-engineering-loop/TECHSPEC.md` §10
- `src/engineering_flow/orchestrator.py`
- `src/engineering_flow/store.py`
- `tests/test_orchestrator.py`
- `tests/test_cli.py`

### Optional

- `docs/waves/2-autonomous-sequential-engineering-loop/TECHSPEC.md` §4.3, §6.3, and §7–§9
- `tests/test_planning_workflow.py`
- `README.md`

## Requirements

- Automated tests must be deterministic, standard-library `unittest`, and
  entirely offline: no live Codex, credentials, network, commit, push, or PR.
  Use fakes that return only schema-valid provider results unless a test owns
  an invalid-output case.
- Demonstrate ordered one-task-at-a-time progression, with a task accepted
  only after all exact required test commands pass and a fresh independent
  reviewer returns `PASS` with no blocking findings.
- Demonstrate `FIX_REQUIRED` evidence feeding the same Developer task context,
  followed by tests and a distinct re-review; prove initial review/cycle
  counting, limit pause, immutable findings, mandatory intervention, and a new
  bounded review window.
- Simulate interruption and reopening around every named durability boundary.
  Assert no duplicate execution, cycle, evidence, task acceptance, or next-task
  launch, and assert pending/unknown provider work becomes human attention.
- Verify status/log output remains sanitized, ordered, and correlated, and run
  the complete test suite so former Wave 1 workflows still reach their prior
  terminal behavior before Wave 2 resume begins.

## Constraints

- Do not modify approved TECHSPEC/design documents, change provider behavior,
  or implement new production features under the guise of test work. If tests
  expose an implementation defect, report it for the owning implementation
  task rather than broadening this task.
- Manual acceptance is a documented future operator check in a disposable,
  authenticated repository; it is not an automated command and must verify
  absence of commit, push, and PR side effects.

## Acceptance Criteria

- One deterministic integration scenario proves multiple tasks complete in
  manifest order and reaches `COMPLETED/TASKS_READY_FOR_WAVE_REVIEW` without
  any delivery side effect.
- Tests prove every specified failed/invalid/import/recovery condition pauses
  safely with durable actionable evidence rather than launching duplicate or
  unauthorized work.
- Tests prove both review remediation and limit/intervention behavior,
  including separate reviewer sessions and unchanged task evidence.
- CLI-facing tests demonstrate useful task/cycle/intervention status and
  monotonic correlated logs with redaction.
- The full suite and compile check pass, and the documented manual procedure
  covers two tasks, remediation, limit/intervention, restart, and no Git/PR
  operation.

## Validation

- `python -m unittest discover -s tests -p 'test_task_lifecycle.py'`
- `python -m unittest discover -s tests`
- `python -m compileall -q src`
- Manual acceptance in a disposable authenticated Git repository following
  TECHSPEC §10 (not part of automated validation).

## Dependencies

- TASK-001 — durable task definitions, evidence, and recovery records.
- TASK-002 — role-specific runtime contracts and adapter safety behavior.
- TASK-003 — task lifecycle orchestration.
- TASK-004 — execution policy, intervention command, and task observability.

## Out of Scope

- Fixing implementation defects outside this task's test-helper scope, Wave
  acceptance, release final review, Git/PR delivery, merge, and Wave 3 work.
