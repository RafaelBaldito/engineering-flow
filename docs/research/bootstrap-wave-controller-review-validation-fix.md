# Bootstrap Reviewer Validation Fix

## Purpose

Record the narrow bootstrap correction for review-time Python bytecode writes discovered by integrated dry-run 2.

## Dry-run 2 finding

The real task Reviewer correctly returned `FIX_REQUIRED`, but its required Python unittest validation created `__pycache__/` paths. The Controller correctly rejected the resulting review completion because the review had changed paths beyond its exact authoritative review artifact.

## Root cause

Python's normal bytecode cache behavior ran inside a read-mostly review operation without an explicit no-bytecode execution convention.

## Decision

Reviewer and Wave Reviewer handoffs now carry `validation_environment: {PYTHONDONTWRITEBYTECODE: "1"}`. The Host must apply this environment to Python validation run for those review roles. Transient Python bytecode is prevented at validation execution; it is **not** added to the Controller's allowed review paths.

## Implementation

`tools/wave_controller/core.py` adds the explicit environment only to Reviewer and Wave Reviewer handoffs. It does not inject Python configuration into unrelated role validation. Controller exact-artifact validation is unchanged.

## Regression tests

Focused bootstrap coverage verifies both review handoffs carry the environment; a representative `unittest discover` invocation under that environment creates neither `__pycache__` nor `.pyc`; exact task review artifact completion remains accepted; task-review artifact plus bytecode and source drift remain rejected; and Wave-review artifact plus material drift remains rejected.

## Focused validation

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller -v` — PASS (25 tests).

## Full repository validation

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -m unittest discover -s tests -q` — PASS (101 tests).

## Architectural impact

No lifecycle or state-machine change. The approved 19 named lifecycle states and Controller artifact-only policy are unchanged.

## Remaining live risks

The following still require live validation in another full dry-run: material-drift rejection; the complete `FIX_REQUIRED -> Fixer -> fresh Reviewer` path; stale-result rejection; human authority CLI; fresh-host recovery; unresolved writer behavior if applicable; Wave Reviewer; and Wave acceptance.

## Recommendation

READY_TO_RERUN_INTEGRATED_DRY_RUN
