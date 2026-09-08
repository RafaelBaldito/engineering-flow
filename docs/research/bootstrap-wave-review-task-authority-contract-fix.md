# Bootstrap Wave Review task-authority contract fix

## Problem

The independent Wave Reviewer rejected a legitimately ready disposable Wave
because the immutable approved `TASKS.md` retained the registration-required
`PENDING` entries after the Controller had accepted task reviews as `PASS`.

## Live evidence

`bootstrap-wave-controller-wave-review-final-rerun.md` records two registered
tasks with Controller `PASS` records and Controller-validated accepted-review
receipts, plus matching task-review `PASS` artifacts. A fresh Controller
reached `WAVE_REVIEW_REQUIRED`; the independent reviewer nevertheless emitted
`FIX_REQUIRED` solely from the plan's `PENDING` cells.

## Root cause

A+B. The Controller Wave Reviewer handoff did not provide an explicit,
per-task runtime acceptance manifest, and the Wave Review Skill's ambiguous
task-index consistency wording allowed the approved planning table to be read
as current runtime status. This is not a disposable-fixture format issue:
`register-tasks` intentionally requires those planning entries to be `PENDING`.

## Authority model

`TASKS.md` is authoritative for approved task identity, order, scope,
decomposition, dependencies, and planning metadata. Controller task records
and accepted-review receipts are authoritative for runtime acceptance state.
The task-review artifact named in the accepted receipt is authoritative review
evidence and its decision must be `PASS` for accepted work.

## TASKS.md responsibility

The approved plan remains immutable after registration. Its `PENDING` cells
are registration-time planning metadata, not authority for runtime acceptance.

## Controller runtime status responsibility

The Controller persists each task's runtime `PASS` together with a
Controller-validated accepted-review receipt. The new handoff represents that
runtime fact as `controller_runtime_status: accepted`.

## Task-review artifact responsibility

The accepted receipt identifies the exact `TASK-<id>-REVIEW.md` artifact and
requires a Reviewer `PASS`. A file alone does not accept a task; a receipt with
the wrong task identity, a missing artifact, or a non-PASS decision is
rejected.

## Wave Review evidence contract

For every task, Wave Review uses plan identity/order/scope plus Controller
accepted status plus the authoritative `PASS` artifact. Planning `PENDING`
does not contradict accepted+PASS. Controller accepted with `FIX_REQUIRED`,
Controller pending with `PASS`, missing evidence, wrong review identity, and
plan/index identity or ordering disagreement all stop before Wave Reviewer
dispatch.

## Handoff contract

The Controller adds `task_acceptance_evidence` only to the fresh Wave Reviewer
handoff. Each entry contains `task_id`, `task_plan_position`,
`task_plan_source`, `controller_runtime_status`,
`authoritative_review_artifact`, and `authoritative_review_decision`. It is
factual, validates the approved plan hash and receipt artifacts, contains no
developer reasoning or suggested verdict, and retains `fork_turns: none`.

## Skill changes

The Wave Review Skill now explicitly separates task-plan planning status from
runtime acceptance evidence. It requires Controller runtime and task-review
evidence to agree, while preserving `TASK_REVIEW_REQUIRED` for a real runtime
status/review conflict.

## Negative consistency cases

Focused tests reject accepted plus `FIX_REQUIRED`, pending plus `PASS`, absent
receipt, wrong task-review artifact identity, and plan/index ordering mismatch.
They do not infer `PASS` from a plan or from an unvalidated review file.

## Fresh-host behavior

A newly constructed Controller produces the same Wave Reviewer evidence
manifest from the persisted approved-plan hash, ordered task records, and
accepted-review receipts. No host conversation is needed.

## Tests

`.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller -v`:
35 PASS. Coverage includes immutable planning `PENDING`, accepted/PASS handoff
consistency, all negative evidence cases, fresh-host manifest stability,
registration, and task-status reconciliation regression coverage.

## State-machine impact

state-machine change: NO

No lifecycle state, transition, or approval gate changed.

## Production repository integrity

Only the bootstrap Controller, focused bootstrap tests, Wave Review Skill, and
listed research records changed. `src/engineering_flow/`, production Wave 3,
historical experiment reports, commits, pushes, and the live Wave Review
experiment were not modified or run.

## Remaining risks

The focused contract proves Controller handoff/evidence representation, not a
new live Wave Review rerun. A future independent experiment must verify that a
fresh Wave Reviewer follows the clarified Skill through `WAVE_ACCEPTED`.

## Recommendation

READY_TO_RERUN_WAVE_REVIEW_EXPERIMENT
