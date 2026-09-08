# Bootstrap Wave Controller task-registration fix

## Problem

An explicitly approved `TASKS.md` could not become the Controller's authoritative task set through any public lifecycle operation. As a result, `TASK_EXECUTION_REQUIRED` had no task to select.

## Root cause

Planner completion recorded the task-plan approval gate, but neither that completion nor a public Controller command registered the approved index's task identities, order, and dependencies in persisted state.

## Contract

The Controller now supports one explicit task-set registration after task-plan approval and before task execution. Registration persists only the ordered task identities and dependency lists required by the existing task lifecycle, with all registered task statuses initialized to `PENDING`.

## Public operation

`python -m tools.wave_controller.cli --root <repo> --wave <wave-id> register-tasks`

The matching Controller method is `register_tasks()`. It requires `TASK_EXECUTION_REQUIRED`, no active operation, and the satisfied persisted `TASK_PLAN_APPROVAL` gate. It does not dispatch work, approve anything, or advance the lifecycle state.

## Approval boundary

`register-tasks` requires approval evidence containing the exact current `tasks/<wave-id>/TASKS.md` path and SHA-256 hash. A task plan that merely exists, or an approval for another artifact revision, is rejected. Registration is therefore distinct from and cannot imply task-plan approval.

## TASKS.md parsing contract

Only the canonical `## Execution Order` table is parsed. It must have exactly these columns:

`Task | Title | Depends On | Status`

Rows are contiguous through the next Markdown heading or EOF. Each requires a unique `TASK-...` ID, non-empty title, `PENDING` status, and either `—` or a comma-separated list of unique known `TASK-...` dependencies. Empty tables, malformed headers/separators/rows, duplicate IDs, duplicate dependencies, unknown dependencies, and self-dependencies reject explicitly. No broader Markdown interpretation is performed.

## Persistence model

Schema-v1 remains unchanged. The existing `tasks` list receives records in table order with `id`, `dependencies`, and `PENDING` status. A `task_plan` record stores the approved index path and SHA-256. Atomic state persistence remains unchanged.

## Idempotency

Calling `register-tasks` again with the same unchanged approved plan and exact persisted registration returns `IDEMPOTENT`. It does not duplicate tasks or alter counters, task status, selection, or attempts.

## Conflict handling

If the approved index changes, its approval-evidence hash no longer validates and the operation rejects under the Controller's existing authoritative-artifact integrity rule. A different persisted plan or task set also rejects as a conflicting registration. The already-written control record is not modified by either rejection.

## Fresh-host recovery

Task order, IDs, dependencies, and plan identity are stored in the Wave control record. A new Controller process reads them normally; `next` deterministically selects the first dependency-ready registered task and persists that selection using existing behavior.

## Tests

Focused bootstrap tests cover rejection before approval, public CLI registration, table order/dependencies, duplicate/malformed/empty plans, idempotent replay, changed-plan rejection with preserved registration, fresh-process recovery, deterministic next selection, and existing lifecycle/gate regressions.

## State-machine impact

state-machine change: NO

`register-tasks` is an explicit operation within existing `TASK_EXECUTION_REQUIRED`; no lifecycle state or gate is added or weakened.

## Production repository integrity

This correction changes only the bootstrap Controller, its focused tests, and research documentation. It does not modify `src/engineering_flow/`, production Wave 3, Skills, or historical experiment reports other than the listed implementation record.

## Remaining risks

The previously blocked real Wave Review experiment remains intentionally unrun in this session. Its downstream Wave Reviewer acceptance, drift rejection, and host interruption scenarios still require their own bounded experiment.

## Recommendation

READY_TO_RERUN_WAVE_REVIEW_EXPERIMENT
