# Bootstrap Wave Controller final smoke

## Purpose

Run one short, isolated composition smoke for the bootstrap Wave Controller without repeating closed negative suites or touching production Wave 3.

## Baseline

Production was clean at `627185375b74897c888d5bba603295df3ea43e4d` (`6271853 docs: record wave review acceptance rerun`). `./scripts/env-preflight` reported `READY` with repository-local Python 3.13.15.

## Prior evidence intentionally not repeated

- `docs/research/bootstrap-wave-controller-safety-recovery-experiment.md`
- `docs/research/bootstrap-wave-controller-deterministic-remediation-experiment.md`
- `docs/research/bootstrap-wave-review-task-authority-contract-fix.md`
- `docs/research/bootstrap-wave-controller-wave-review-acceptance-rerun.md`

These cover safety/recovery, stale results, leases, task-status recovery, task registration cases, task/Wave-review authority, and Wave Reviewer material-drift behavior. None was deliberately rerun.

## Environment

Linux/WSL; `.venv/bin/python3` 3.13.15; public Controller CLI invoked with `PYTHONPATH=/home/bal/projects/engineering-flow`. Fixture validation contract was `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q`.

## Disposable fixture

Exactly one new Git fixture was created at `/tmp/bootstrap-wave-controller-final-smoke.abSHF4`, Wave `smoke`. It contained a minimal greeting Wave, approved-plan artifacts, and no production Wave 3 content. Its initial control record used the Controller bootstrap initializer; all lifecycle actions after initialization used the public Controller CLI. It was stopped before task execution because of the blocker below and removed during cleanup.

## Task plan and registration

The Controller legitimately completed Wave-start authorization, Architect completion, TECHSPEC approval, Planner completion, and explicit `TASK_PLAN_APPROVAL` for the exact `tasks/smoke/TASKS.md` hash. The approved immutable execution order was:

1. `TASK-A` — Implement greeting — no dependency.
2. `TASK-B` — Decorate greeting — depends on `TASK-A`.

`register-tasks` then returned `INVALID: task registration is not permitted in the current lifecycle state`, because persisted state was `AWAITING_TASK_PLAN_APPROVAL`, although the required authority was satisfied.

The only public operation that advances that state is `next`. It transitions to `TASK_EXECUTION_REQUIRED` and immediately calls task selection. Since registration has not happened and the Controller has no tasks, it returns `HUMAN_ATTENTION: no dependency-ready task`; a subsequent public `reconcile` persists `HUMAN_ATTENTION`. This prevents the required approved-plan-to-registration composition from reaching either legal registration or Task A dispatch through the public interface.

## Task A happy path

Not run. No Developer or Reviewer was dispatched; no task-review artifact exists; no Controller task acceptance occurred.

## Task B controlled defect

Not run. No Developer was dispatched and no fixture defect was injected. Consequently no defect details were supplied to, or withheld from, a Reviewer.

## Task B first review

Not run. No Reviewer identity, fork, review artifact, review decision, reviewer write activity, or bytecode validation exists.

## Task B remediation

Not run. No Fixer was dispatched, because a `FIX_REQUIRED` review could not be reached.

## Task B fresh re-review

Not run. No second Reviewer identity, PASS artifact, or Controller acceptance exists.

## TASKS_READY_FOR_WAVE_REVIEW

Not reached. No runtime task registration or acceptance records exist.

## Wave Review authority consistency

Not evaluated live, because the registered task/runtime evidence prerequisite could not be established. The immutable plan remained the approved source for identity, order, scope, and planning-time `PENDING` metadata.

## Fresh Wave Reviewer

Not dispatched. No Wave Reviewer child identity or factual authority handoff was produced; no verdict was suggested.

## Independent Wave PASS

Not run.

## WAVE_ACCEPTED

Not reached.

## Fresh-host recovery

The required terminal `WAVE_ACCEPTED` recovery was not applicable. The public recovery call exposed the same registration dead end and persisted `HUMAN_ATTENTION`, rather than reopening a task or Wave Review.

## Workflow stop

Stopped at the first real Controller composition defect. No final review, next Wave, delivery side effect, commit, push, or production-Wave action occurred.

## Production repository integrity

Protected paths had no tracked diff before this report: `tools/wave_controller/`, `tests/bootstrap/`, `src/engineering_flow/`, `.codex/skills/`, `docs/waves/3`, and all listed historical reports. This report is the only intended persistent production change.

## Failures / blockers

`BLOCKED`: the public lifecycle has no usable state in which both (a) the plan approval has moved lifecycle out of `AWAITING_TASK_PLAN_APPROVAL` and (b) the Controller has not already attempted task selection before `register-tasks`. The documented required composition `explicit task-plan approval -> register-tasks` is therefore impossible from a Wave-authorized lifecycle without bypassing public lifecycle mechanics or manually altering state, both prohibited by this smoke.

## Remaining risks

The requested Task A PASS path, Task B controlled remediation path, task-to-Wave authority composition, Wave PASS, terminal acceptance, and fresh-host terminal stop remain unproven by this final smoke. Earlier focused evidence remains valid only for its stated scopes.

## Recommendation

NEEDS_CONTROLLER_FIX
