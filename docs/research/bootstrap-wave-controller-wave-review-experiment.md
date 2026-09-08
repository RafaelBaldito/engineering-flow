# Bootstrap Wave Controller Wave Review experiment

## Purpose

Run only the bootstrap Controller path needed to reach a legitimate Wave Review, then validate a fresh Wave Reviewer PASS and material-drift rejection. No production Wave, remediation loop, safety/recovery scenario, final review, delivery action, commit, or push was in scope.

## Baseline

Production started clean at `58f9ab784124fa4e95930d30e829c70935cf85d8` (`58f9ab7`). `./scripts/env-preflight` reported `READY` with repository-local Python 3.13.15.

## Environment

Linux/WSL. Public Controller invocations used:

`PYTHONPATH=/home/bal/projects/engineering-flow .venv/bin/python3 -m tools.wave_controller.cli --root <fixture> --wave wr-bootstrap <command>`

The Controller's existing `initial`/`save` bootstrap facility created each disposable fixture's initial `WAVE_AUTHORIZED` record; it was not used to change a lifecycle state. All lifecycle actions after initialization used the public CLI. Host result-envelope files were outside the fixture checkout.

## Disposable fixtures

- `/tmp/wc-wave-review-primary` — discarded setup attempt. Its host envelope was accidentally written inside the fixture, so the Controller correctly rejected it as stale. It is not used as experiment evidence.
- `/tmp/wc-wave-review-live` — the live minimal Wave lifecycle fixture.

Each fixture was an independent Git repository with committed empty `README.md` baseline and untracked deterministic Wave artifacts.

## Accepted task set

**BLOCKED.** The intended two-task set was:

- `TASK-A` — `tasks/wr-bootstrap/TASK-A.md`
- `TASK-B` — `tasks/wr-bootstrap/TASK-B.md`, dependent on `TASK-A`

The fixture had `tasks/wr-bootstrap/TASKS.md`, the approved `docs/waves/wr-bootstrap/TECHSPEC.md`, and persisted task-review records `tasks/wr-bootstrap/reviews/TASK-A-REVIEW.md` and `tasks/wr-bootstrap/reviews/TASK-B-REVIEW.md`, each with `PASS`.

These artifacts could not become a legitimate Controller-accepted task set: after the legitimate Planner completion and explicit `TASK_PLAN_APPROVAL`, the Controller persisted `TASK_EXECUTION_REQUIRED` with no dependency-ready task. The public interface has no operation that imports the approved task index and PASS evidence into the control record's `tasks` field. Manually populating it would violate the experiment boundary.

Controller state immediately before the blocked transition was `AWAITING_TASK_PLAN_APPROVAL`, with the explicit `TASK_PLAN_APPROVAL` recorded. A fresh `status` afterward reported `TASK_EXECUTION_REQUIRED` and no active operation.

## Wave Review readiness

**BLOCKED.** Fresh public `reconcile` and `next` both returned exactly:

```json
{"reason":"no dependency-ready task","status":"HUMAN_ATTENTION"}
```

The Controller did not bypass a human gate or accept task artifacts by inference. However, it could not aggregate the valid fixture task evidence into its required internal task set, so `TASKS_READY_FOR_WAVE_REVIEW` was not reached.

## Fresh Wave Reviewer

**NOT_EXERCISED.** No legitimate `WAVE_REVIEW_REQUIRED` operation existed, so no child was dispatched. Consequently there is no child identity. The Controller's prospective Wave Reviewer handoff specifies `fork_turns: "none"`, factual checkout/input metadata, exact expected output, and `PYTHONDONTWRITEBYTECODE=1`; no host prompt was sent and no suggested verdict or finding was sent.

## Wave Reviewer write restraint

**NOT_EXERCISED.** No Wave Reviewer operation was legitimately acquired.

## Wave Reviewer no-bytecode validation

**NOT_EXERCISED.** No Wave Reviewer operation was legitimately acquired.

## Wave Review PASS

**NOT_EXERCISED.** The expected Controller handoff artifact would have been `docs/waves/wr-bootstrap/WAVE-REVIEW.md` (the Controller's current public contract), but no valid Wave Review operation existed and no artifact was created.

## WAVE_ACCEPTED

**NOT_EXERCISED.** No Wave Review PASS could be submitted, so there is no fresh-process `WAVE_ACCEPTED` status, reconcile result, or terminal next action. No final review or later Wave action was started.

## Wave Reviewer material-drift rejection

**NOT_EXERCISED.** The independent negative case requires a legitimate active Wave Review operation, which the public lifecycle could not produce. No unauthorized source/test mutation was made, and no Controller completion was submitted for this case.

## Production repository integrity

No production Wave was used; in particular Wave 3 was not inspected or modified. No Controller implementation, `tests/bootstrap`, `src/engineering_flow`, Skill, or prior experiment report changed. No commit, push, or PR action occurred. The only intended persistent change is this report.

## Failures / blockers

**BLOCKED — demonstrated Controller lifecycle gap.** The public `complete-operation` path for a Planner records its envelope and moves to `AWAITING_TASK_PLAN_APPROVAL`, but it does not parse or otherwise register `TASKS.md` into the persisted task set. Following the legitimately recorded task-plan approval, public `next`/`reconcile` transitions to `TASK_EXECUTION_REQUIRED` and returns `HUMAN_ATTENTION` because the task set is empty. This prevents every subsequent task lifecycle and Wave Review stage without forbidden direct control-record editing.

The discarded setup attempt produced a separate expected safety result, `{"reason":"stale result","status":"HUMAN_ATTENTION","wave_id":"wr-bootstrap"}`, after a host envelope was incorrectly placed in the fixture checkout. It is not a Controller defect and was not used for the blocker conclusion.

## Remaining risks

The requested live Wave Reviewer PASS-to-acceptance path, fresh-host `WAVE_ACCEPTED` recovery, artifact-only write restraint/no-bytecode behavior, and independent material-drift rejection remain unvalidated. They require a Controller that can derive the persisted task set from the authorized task plan through its public lifecycle.

## Recommendation

NEEDS_CONTROLLER_FIX
