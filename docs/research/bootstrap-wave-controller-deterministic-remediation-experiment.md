# Bootstrap Wave Controller deterministic remediation experiment

## Purpose

Demonstrate the live, Controller-governed bootstrap task remediation sequence for a deliberately defective disposable candidate: Developer completion, independent `FIX_REQUIRED`, Fixer remediation, and a fresh independent `PASS`. This was a deterministic fault-injection experiment, not a claim that the Developer naturally made the defect.

## Baseline

Production was clean at `da16386f4ac1ed5fba0bccfcdc243cdbbf95cc2e` (`docs: record remediation loop rerun`). `git status --short` produced no output and `./scripts/env-preflight` reported `READY` before fixture creation.

## Environment

Linux/WSL; repository-local Python 3.13.15. The fixture Controller was invoked with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/bal/projects/engineering-flow .venv/bin/python3 -m tools.wave_controller.cli`. Fixture task validation used the standard library only and `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q`.

## Disposable fixture

Exactly one disposable Git fixture was created at `/tmp/bootstrap-deterministic-remediation.Byz5EX` and removed after completion (moved to the local trash). Its sole task, `TASK-001`, required `normalize_identifier(value)` to accept strings, trim surrounding whitespace, lowercase ASCII letters, collapse internal whitespace runs to `-`, return `""` for blank input, and raise `TypeError` for non-string input. The fixture started with a Controller-created initial `TASK_EXECUTION_REQUIRED` record and one dependency-ready task; all subsequent lifecycle operations used the public Controller CLI.

## Developer execution

Child `/root/deterministic_developer` received only the task and supporting specification under the Controller handoff `deterministic-developer`. It created `src/identifier.py` and `tests/test_identifier.py`; its four-test validation passed. The Developer completion envelope was accepted by the Controller, which transitioned the task to `TASK_REVIEW_REQUIRED`.

## Controlled fault injection

After Developer acceptance and before Reviewer #1 dispatch, test setup changed only fixture file `src/identifier.py`: the non-string guard was changed from `raise TypeError("value must be a string")` to `raise ValueError("value must be a string")`. This violated the explicit non-string acceptance requirement while leaving ordinary string normalization plausible.

The deterministic pre-review check `normalize_identifier(None)` failed exactly as `expected TypeError, observed ValueError: value must be a string` (exit 1). Reviewer #1 was not told that fault injection occurred, the changed file or line, the defect, this failing validation case, or an expected verdict.

## Controller checkout handling

No fingerprint, control record, task, specification, or review artifact was manually altered after fault injection. With no active operation and state `TASK_REVIEW_REQUIRED`, public `begin-operation --operation-id deterministic-reviewer-1` captured the altered candidate as its own legitimate input identity (`bdc457ba637af69506f0e43b838efc009840cf7aaa3ea2e5a42bc4d7ecabe765`) and acquired the Reviewer lease. Thus the known-defective checkout was the Controller-governed review input without bypassing checkout safety.

## Reviewer #1 independent FIX_REQUIRED

Fresh child `/root/deterministic_reviewer_1` was dispatched with `fork_turns="none"`, factual authority paths, the current Controller checkout identity, exact review-artifact path, Controller fields, and `PYTHONDONTWRITEBYTECODE=1`. It independently ran the task suite, found that non-string input raised `ValueError` rather than `TypeError`, wrote only `tasks/remediation/reviews/TASK-001-REVIEW.md`, and returned `FIX_REQUIRED`. The Controller accepted its envelope and transitioned to `TASK_FIX_REQUIRED`.

## Fixer remediation

Fresh child `/root/deterministic_fixer` received the task/specification, persisted review artifact, current checkout identity, and required validation. It changed only `src/identifier.py` to restore `TypeError`; it did not alter Controller state or the review artifact. Host deterministic validation passed: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q` ran four tests successfully. The Controller accepted the Fixer completion and required fresh review (`TASK_REVIEW_REQUIRED`).

## Reviewer #2 independent PASS

New child `/root/deterministic_reviewer_2`, distinct from Reviewer #1 and dispatched with `fork_turns="none"`, received only factual current-handoff data and no prior reviewer/fixer reasoning or suggested verdict. It independently validated the candidate, including edge and non-string checks, ran the four-test suite successfully with `PYTHONDONTWRITEBYTECODE=1`, wrote only `tasks/remediation/reviews/TASK-001-REVIEW.md`, and returned `PASS`. The Controller accepted the result, marked `TASK-001` `PASS`, and returned to `TASK_EXECUTION_REQUIRED`; no `next` call was made, so Wave Review was not begun.

## Complete remediation-loop result

PASS. The observed live sequence was:

`Developer accepted -> controlled defective candidate -> fresh Reviewer #1 FIX_REQUIRED accepted -> Fixer accepted -> fresh Reviewer #2 PASS accepted`.

## No-bytecode validation

PASS. Both Reviewers were explicitly handed `PYTHONDONTWRITEBYTECODE=1`; their Python validation used it. Fixture checks after each Reviewer found no `__pycache__` directory and no `.pyc` file. The Controller also accepted each review envelope under its exact-review-artifact-only path rule.

## Production repository integrity

PASS. After fixture cleanup and before this report was added, production remained at `da16386f4ac1ed5fba0bccfcdc243cdbbf95cc2e` with a clean worktree. `git diff --quiet` confirmed no change to `tools/wave_controller/`, `tests/bootstrap/`, `src/engineering_flow/`, `docs/waves/3`, `.codex/skills/`, or the four earlier bootstrap research artifacts. No commit or push occurred.

## Failures / blockers

None. The initial direct pre-review check intentionally failed as required to prove the controlled defect; this was test setup, not an experiment blocker.

## Remaining risks

This narrow experiment does not exercise safety/recovery behavior, material-drift rejection, Wave Review, or any production Wave. It also does not establish behavior under interruption or concurrent writers.

## Recommendation

READY_FOR_SAFETY_RECOVERY_EXPERIMENT
