# Bootstrap Wave Controller task-status reconciliation fix

## Problem

An accepted task-review result and the Controller's persisted task status could diverge after interrupted persistence/recovery, allowing a completed task to appear pending to a fresh host or downstream review.

## Root cause

The Controller set `tasks[].status` during Reviewer `PASS`, but retained no task-scoped, Controller-validated acceptance receipt from which reconciliation could safely reconstruct a lost status. `last_result_envelope` is only the most recent operation and cannot serve as durable multi-task acceptance history.

## Required invariant

A task is `PASS` in the Controller index if and only if the Controller has accepted a valid task-review `PASS` for that task. Registered tasks begin `PENDING`; developer completion, `FIX_REQUIRED`, and fixer completion do not change that status.

## Authoritative acceptance source

The source is a Reviewer `PASS` envelope accepted by `complete_operation` after `_validate_envelope` has matched the active Reviewer lease, wave/task scope, checkout identities, exact allowed task-review artifact, artifact hash, and review decision. The Controller atomically writes an `accepted_review` receipt into that task record only after this validation. A review file or its text alone is not authority.

## Status transition contract

At accepted Reviewer `PASS`, the selected record receives `status: PASS` and its receipt in the same atomic state write. `FIX_REQUIRED` routes to `TASK_FIX_REQUIRED`; a fixer routes back to fresh `TASK_REVIEW_REQUIRED`; neither accepts the task. The task plan remains the approved `PENDING` registration input and is not rewritten.

## Reconciliation behavior

`reconcile` verifies every persisted receipt's task ID, operation ID, Reviewer/PASS facts, exact expected review-artifact path, and artifact hash. If a verified receipt has a `PENDING` task record, it deterministically restores `PASS`. No other status is inferred. Invalid receipt facts, a missing/hash-mismatched artifact, or an unsupported status are ambiguous and route to `HUMAN_ATTENTION`.

## Multi-task behavior

Receipts are task-scoped. Repairing TASK-A cannot update TASK-B, and registration order/dependencies are untouched. After independently accepted `PASS` receipts exist for all registered tasks, normal existing progression reaches `TASKS_READY_FOR_WAVE_REVIEW` and then the Wave Reviewer action.

## Fresh-host recovery

A new Controller reads the accepted receipt and task status from the Wave control record. It preserves accepted/pending tasks, skips accepted work when selecting the next task, and recognizes Wave Review readiness after all tasks are accepted.

## Idempotency

The first safe repair persists `PASS`; subsequent reconciliation finds the same verified `PASS` receipt and makes no task-record change. No state-machine state or public CLI operation was added.

## Conflict handling

The Controller repairs only its own durable acceptance receipt. It does not accept based on arbitrary files, words such as `PASS`, or implementation validation. Ambiguity uses the existing `HUMAN_ATTENTION` convention. Task-registration plan hash conflicts remain rejected without rewriting registration.

## Tests

Focused bootstrap tests cover initial pending records; developer, `FIX_REQUIRED`, and fixer non-acceptance; per-task Reviewer `PASS`; two-task isolation/order; fresh-host recovery and accepted-task skipping; all-accepted Wave Review readiness; repeated reconciliation; malformed receipt rejection; and existing registration idempotency/changed-plan rejection. Focused command: `.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller -v` — 32 PASS.

## State-machine impact

state-machine change: NO

## Production repository integrity

Only the bootstrap Controller, its focused tests, and the listed research documentation changed. `src/engineering_flow/`, production Wave 3, Skills, CLI, commits, pushes, and the Wave Review experiment were untouched.

## Remaining risks

This fix proves Controller persistence/reconciliation in disposable unit fixtures. The intentionally deferred live Wave Review experiment remains the next separate validation boundary.

## Recommendation

READY_TO_RERUN_WAVE_REVIEW_EXPERIMENT
