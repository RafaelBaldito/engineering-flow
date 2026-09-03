# TASK-003 — Implement Sequential Task Orchestration

## Objective

Make the orchestrator the sole authority that imports an approved task plan,
processes one persisted task through Developer/test/independent-review cycles,
and safely routes every terminal condition to acceptance or human attention.

## Scope

- Evolve `PlanningOrchestrator` into the Wave 2 workflow orchestrator while
  retaining a compatibility alias and all public Wave 1 planning behavior.
- On `resume --workflow ID`, import a valid approved task plan exactly once
  from `COMPLETED/READY_FOR_WAVE_2`, move to `RUNNING/TASK_EXECUTION`, and
  drive only the next persisted permitted action. Leave the Wave 2 terminal
  stage unchanged.
- Build role-scoped Developer and Reviewer requests, dispatch through the
  generalized runtime, validate exact required-test evidence and review
  payloads, and persist lifecycle results through the transactional store APIs.
- Enforce task ordering, task-local Developer continuity, fresh Reviewer
  sessions, remediation/re-review windows, review-cycle limits, explicit
  intervention gates, failure routing, and restart reconciliation.
- Add focused fake-runtime orchestration tests for import, ordered progression,
  test/result rejection, independent review, remediation, limit/intervention,
  and no-duplicate recovery boundaries.

## Context

### Required

- `docs/waves/2-autonomous-sequential-engineering-loop/TECHSPEC.md` §4, §6.2–§6.3, and §7
- `src/engineering_flow/orchestrator.py`
- `src/engineering_flow/store.py`
- `src/engineering_flow/runtime.py`

### Optional

- `docs/architecture/architecture-overview.md` §3, §5, §7–§9, and §12–§13
- `tests/test_orchestrator.py`
- `tests/test_planning_workflow.py`

## Requirements

- Read workflow/task/cycle state before every work-driving call. Select only
  the lowest-order non-accepted task and never dispatch another active task.
  Provider results are evidence, never directions to advance/accept/retry.
- Import only the approved task-plan artifact specified by the persisted Wave 1
  workflow. A legacy/malformed plan, hash mismatch, changed manifest, unknown
  operation, invalid structured output, failed/missing/mismatched required
  test evidence, provider/auth/tool safety failure, or process loss must leave
  durable actionable `HUMAN_ATTENTION` rather than guessing or retrying.
- For each cycle, persist the operation/execution intent before calling the
  provider. Accept only a Developer payload that reports every exact required
  test command once and passing; do not dispatch a review otherwise.
- Dispatch a fresh independent Reviewer after valid test evidence. Accept a
  task only atomically on `PASS` with no blocking finding. Route
  `FIX_REQUIRED` with blocking findings below the configured limit to the same
  task-local Developer for remediation, then exact tests and a new Reviewer.
- Count the initial review as cycle 1. At the configured limit, persist the
  findings and transition to human attention without another fix. Implement
  intervention recording with actor, required reason, prior evidence, and a
  new review window; it cannot accept, skip, alter evidence, or loosen the
  per-window limit.
- Reconcile restart state deterministically: replay completed operation keys,
  mark pending/unknown calls unknown and pause, and make task acceptance plus
  next-task selection/events atomic so neither can occur twice.

## Constraints

- Depend only on runtime/store/domain abstractions; do not import Codex CLI
  internals or run subprocesses directly.
- Developer input may contain only the immutable task definition, source-plan
  reference/hash, declared canonical context files, relevant planning
  references, its own prior evidence/findings, repository, and policy rules.
  Reviewer input excludes developer transcripts, credentials, unrelated tasks,
  and future/release material.
- Do not change planning approval semantics, redefine the task-plan contract,
  add task parallelism, perform Wave acceptance, or create Git/PR operations.

## Acceptance Criteria

- A formerly Wave 1-complete workflow imports a valid multi-task manifest once,
  starts only the first task, then advances in manifest order only after each
  task has exact passing tests and an independent PASS/no-blocking review.
- Missing, duplicate, mismatched, failed, or unrecognized required-test claims
  cannot dispatch review or accept a task; malformed developer/reviewer output
  cannot transition task state.
- A blocking `FIX_REQUIRED` produces bounded task-local remediation and a new
  reviewer; the configured limit pauses with preserved evidence, and a valid
  intervention opens a new window without marking the task passed.
- Developer/Reviewer requests have the required bounded context and distinct
  session behavior; neither agent can select a task or authorize completion.
- Interruption at all task-operation boundaries, replayed resume, and terminal
  `TASKS_READY_FOR_WAVE_REVIEW` preserve recorded outcomes without duplicate
  execution, evidence, acceptance, or next-task launch.

## Validation

- `python -m unittest discover -s tests -p 'test_orchestrator.py'`
- `python -m unittest discover -s tests -p 'test_planning_workflow.py'`
- `python -m compileall -q src`

## Dependencies

- TASK-001 — imported definitions, task/cycle evidence, and idempotent store
  operations.
- TASK-002 — provider-neutral role execution, capability, session, and
  structured-result contracts.

## Out of Scope

- TOML configuration migration, CLI argument/output work, independent Wave
  review, release final review, commits, pushes, pull requests, and merge.
