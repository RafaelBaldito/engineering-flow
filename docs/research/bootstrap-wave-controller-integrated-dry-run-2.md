# Bootstrap Wave Controller integrated dry-run 2

## Purpose

Run the corrected bootstrap Controller against the real Codex Host/child runtime in a new disposable Git fixture, without starting Wave 3 or changing product code or workflow contracts.

## Baseline commit

`7651cd8 fix: harden bootstrap wave controller after dry run`

## Scope / non-goals

This was a disposable controller/runtime integration experiment only. No production Wave, architecture, `src/engineering_flow/`, Skill, approval, task plan, review, or Controller implementation was changed. No commit or push was made.

## Environment

Linux/WSL; repository-local Python 3.13.15. `./scripts/env-preflight` returned `READY` and `git=clean` before the experiment. Controller interface: `PYTHONPATH=/home/bal/projects/engineering-flow /home/bal/projects/engineering-flow/.venv/bin/python3 -m tools.wave_controller.cli`.

## Disposable fixture

`/tmp/bootstrap-wave-controller-rerun.uyQ2Ml`, an independently initialized Git repository, contained a standard-library `normalizer.py`, unittest suite, tiny TECHSPEC, two approved disposable task files, and Controller-created Wave state for Wave `rerun`. It was not a production Wave or Wave 3.

## Controller authority

PASS. The Host used only `next`, `status`, `begin-operation`, and `complete-operation` to choose/acquire/complete work. It did not write `WAVE-WORKFLOW-STATE.md` or infer transitions.

## Task-selection persistence

PASS. From `TASK_EXECUTION_REQUIRED`, `next` selected `TASK-PASS` and persisted it. A fresh CLI `status` reported the durable state, and fresh-process `begin-operation --operation-id pass-dev` acquired a lease whose handoff and `active_operation.task_id` were both `TASK-PASS`. The valid task-scoped Developer envelope was accepted, transitioning to `TASK_REVIEW_REQUIRED`.

## Developer dispatch

PASS. Fresh child `/root/developer_pass` used `fork_turns: none` and the `execute-task` contract. Requested metadata was Terra/medium; literal model selection was unavailable, so observed dispatch is recorded as fallback. It changed only `tests/test_normalizer.py`; `python3 -m unittest discover -s tests -q` passed (3 tests).

## Single-writer enforcement

PASS. While `pass-dev` was active, `begin-operation --operation-id prohibited-second-writer` returned `REJECT` with `known active writer`. No second writer was dispatched.

## Reviewer isolation

The real PASS Reviewer child `/root/reviewer_pass` was fresh with `fork_turns: none`. A separate clean fresh-context probe `/root/reviewer_marker_probe`, given only the generic question and no marker value in prompt, handoff, repository, environment, command line, artifact, or result, answered `NO`. This is a passing parent-marker isolation probe.

## Reviewer factual handoff

PASS. The actual handoff contained task/Wave identifiers, checkout identity, changed path, validation fact, expected review path, role/capability, model metadata, and `fork_turns`; it contained no Developer reasoning, rationale, suggested verdict, or Host conclusion.

## Reviewer write restraint

PASS for the ordinary PASS Reviewer: `/root/reviewer_pass` changed only `tasks/rerun/reviews/TASK-PASS-REVIEW.md`; source, tests, specs, and task plan remained unchanged across review.

## Reviewer artifact-only allowance

Positive case PASS: the ordinary Reviewer wrote exactly `tasks/rerun/reviews/TASK-PASS-REVIEW.md`; a live CLI completion envelope with its hash was accepted and transitioned to `TASK_EXECUTION_REQUIRED`.

Negative material-drift case was not reached after the authoritative fixture entered `HUMAN_ATTENTION`; no unit result is substituted for a live demonstration.

## Task PASS path

PASS: Developer (`pass-dev`) -> fresh Reviewer (`pass-review`) -> PASS was accepted by the Controller and returned to `TASK_EXECUTION_REQUIRED`.

## FIX_REQUIRED path

PARTIAL / BLOCKED. Fresh Developer `/root/developer_fix` made the controlled small incomplete implementation for `TASK-FIX`. Its valid envelope was accepted. Fresh independent Reviewer `/root/reviewer_fix_1`, with no defect suggested in its handoff, independently returned `FIX_REQUIRED`: it found that only integers were rejected while other non-strings raise `AttributeError`.

However the Reviewer's required unittest run created new `__pycache__/` and `tests/__pycache__/` paths. The submitted live completion envelope therefore returned `HUMAN_ATTENTION: invalid result envelope: review operation changed unauthorized paths`. This was correct Controller enforcement of its exact artifact-only rule; the authoritative scenario was not manually repaired or advanced. Fixer and fresh re-reviewer were not dispatched.

## Stale-result rejection

Not exercised live before the authoritative stop.

## Human authority CLI

Not exercised live before the authoritative stop.

## Fresh-host recovery

Not exercised after a valid durable transition before the stop.

## Interruption / unresolved writer behavior

Not exercised live in this run.

## Wave Reviewer

Not reached; no Wave Reviewer child was dispatched.

## Wave Reviewer artifact-only allowance

Not reached; neither positive nor negative case was run live.

## Wave acceptance

Not reached. No next Wave, final review, release lifecycle, commit, push, PR, or Wave 3 activity occurred.

## Model/reasoning dispatch

Controller requested Terra/medium for Developers and Terra/high for Reviewers. The collaboration runtime exposed the required `fork_turns` isolation but not literal Terra model selection; observed model selection is **FALLBACK**. The Developer ran at requested medium effort; Reviewers were requested high effort.

## Failures / blockers

The complete mandatory FIX_REQUIRED -> Fixer -> fresh Reviewer path could not continue because a real Reviewer's validation produced transient Python bytecode paths, which the Controller correctly rejected as unauthorized output. The handoff/role procedure needs an explicit no-bytecode validation convention or a clean review execution environment before a full rerun can meet the exact artifact-only requirement. This run found no Controller code defect and did not patch Controller code.

## Remaining risks

Live material-drift rejection, stale-result rejection, explicit human authority, fresh-host recovery, unresolved writer handling, Wave Reviewer behavior, and `WAVE_ACCEPTED` remain unvalidated for the corrected build.

## Recommendation

NEEDS_ANOTHER_DRY_RUN
