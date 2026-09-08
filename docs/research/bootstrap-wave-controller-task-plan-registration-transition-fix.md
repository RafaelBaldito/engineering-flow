# Bootstrap Wave Controller task-plan registration transition fix

## Purpose

Repair only the public boundary from a valid task-plan approval to Controller task registration.

## Baseline

Production baseline was clean at `8a0081eb2e0f44754aa078b16c1641233820d6cd` (`8a0081e docs: record blocked bootstrap final smoke`). `./scripts/env-preflight` reported `READY` using the repository-local Python 3.13.15.

## Reproduction

A disposable Git fixture under `/tmp` used the public Controller lifecycle through Wave-start authorization, Architect completion, TECHSPEC approval, Planner completion, and task-plan approval. The exact approved `tasks/smoke/TASKS.md` SHA-256 was persisted by `record-authority --gate TASK_PLAN_APPROVAL --decision APPROVE --authority-wave smoke`.

Before approval, the state was `AWAITING_TASK_PLAN_APPROVAL`. In the pre-fix composition, approval persisted a satisfied `TASK_PLAN_APPROVAL` gate but retained that lifecycle state. The blocked final-smoke public `register-tasks` result was `{"status":"INVALID","reason":"task registration is not permitted in the current lifecycle state"}`.

## Exact failure

`register_tasks()` required `TASK_EXECUTION_REQUIRED`, while `record_authority()` only stored the satisfied task-plan gate. The only former route from `AWAITING_TASK_PLAN_APPROVAL` to `TASK_EXECUTION_REQUIRED` was `next()`. With no registered tasks, that call returned `HUMAN_ATTENTION: no dependency-ready task`; it was not a valid registration transition.

## Root cause

The public authority operation and the public registration operation disagreed about the required lifecycle position. Approval was correct and hash-bound, but it did not perform the already-defined approval-gate transition that registration required.

## Public lifecycle contract

`TASKS.md` exists -> public exact `TASK_PLAN_APPROVAL` -> persisted state is `TASK_EXECUTION_REQUIRED` with the satisfied approval retained -> `register-tasks` -> persisted ordered `PENDING` tasks -> fresh host `next` selects the first dependency-ready task. No reconciliation, state edit, or task selection precedes registration.

## Approval authority contract

`record-authority` still requires the exact Controller wave ID, gate currently open for that state, `APPROVE`, non-empty actor and evidence, and valid artifact hashes. Registration independently requires evidence for `tasks/<wave>/TASKS.md` at its exact current SHA-256.

## Registration preconditions

Registration requires `TASK_EXECUTION_REQUIRED`, no active operation, satisfied `TASK_PLAN_APPROVAL`, exact approved plan identity/hash, and a valid canonical `## Execution Order` table. Replays of the same persisted registration remain idempotent; changed plan identity is rejected.

## Fix

When the open `TASK_PLAN_APPROVAL` is validly recorded, `record_authority()` now advances the existing `AWAITING_TASK_PLAN_APPROVAL -> TASK_EXECUTION_REQUIRED` transition atomically with the persisted authority. Other gates are unchanged. `register_tasks()` remains the sole task-set importer and no automatic task selection occurs.

## Fresh-process behavior

Post-fix disposable-fixture proof: a fresh Controller after approval saw `TASK_EXECUTION_REQUIRED` and the satisfied plan authority; a second fresh Controller returned `REGISTERED` for two tasks; a third fresh Controller returned `ACTION_REQUIRED` for Developer task `TASK-A`. Persisted registration was `TASK-A` (`PENDING`, no dependencies), then `TASK-B` (`PENDING`, depends on `TASK-A`).

## Regression scenario from final smoke

The focused public-CLI regression test records `TASK_PLAN_APPROVAL` from `AWAITING_TASK_PLAN_APPROVAL`, uses a fresh Controller to confirm recovery, invokes public `register-tasks`, reloads again, and calls `next`. It covers the previously blocked approval-to-registration command sequence without entering Developer execution.

## Tests

`.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller -v` — 37 PASS.

`.venv/bin/python3 -m unittest discover -s tests -q` — 101 PASS.

## State-machine impact

state-machine change: NO

No state, gate, or transition is added. The fix makes the existing task-plan approval transition happen when its explicit public authority is durably recorded, rather than requiring a later `next` call that attempts task selection too early.

## Production repository integrity

Only `tools/wave_controller/core.py`, `tests/bootstrap/test_wave_controller.py`, and this focused research artifact are intended persistent changes. `src/engineering_flow/`, production Wave 3, Skills, remediation, Wave Review, final-review, and historical reports are unchanged.

## Remaining risks

This bounded work does not rerun the final smoke or exercise Developer execution, remediation, Wave Review, or final review. Those remain outside this transition proof.

## Recommendation

READY_TO_RERUN_FINAL_SMOKE
