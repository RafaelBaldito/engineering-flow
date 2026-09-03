---
name: fix-wave-review
description: |
  Remediate actionable blocking findings from the authoritative review of one
  delivery Wave while preserving the approved PRD, Delivery Plan, Architecture,
  Wave TECHSPEC, and Wave boundary. Fix only findings owned by WAVE_FIX or other
  explicitly executable Wave-local remediation. Record remediation evidence.
  Do not perform independent task review, change approved specifications, start
  another Wave, or automatically re-run wave-review.
---

# Fix Wave Review

## Purpose

Remediate blocking findings produced by `wave-review` for one Wave.

This skill operates at Wave scope. It is part of the Wave-remediation route;
it cannot accept the Wave, start a later Wave, substitute for `final-review`,
or authorize release delivery.

It is not a replacement for:

- `fix-task`, which remediates defects found by a task-level review;
- `review-task`, which provides independent task acceptance;
- `wave-review`, which independently decides Wave acceptance;
- `final-review`, which validates the complete approved release.

The authoritative input is the current persisted `WAVE-REVIEW.md`.

## When to Use

Use this skill when:

- the target Wave has a persisted `WAVE-REVIEW.md`;
- the Wave review result is `FIX_REQUIRED` or contains actionable Wave-local
  findings;
- remediation must remain inside the approved Wave boundary.

Do not use this skill when:

- there is no authoritative Wave review artifact;
- the only unresolved findings require independent task review;
- the only unresolved finding is an external environment blocker;
- approved specifications must change;
- the request is to review or accept the Wave.

## Inputs

### Required

- authoritative Wave review artifact;
- approved Wave TECHSPEC;
- repository implementation state.

### Conditionally Required

Load when relevant:

- PRD;
- Delivery Plan;
- architecture/ADRs;
- task specifications;
- task-review evidence;
- manual-acceptance procedure;
- tests and runtime configuration.

## Authoritative Sources

Use this precedence:

1. current explicit user instructions that remain within approved scope;
2. approved PRD;
3. approved Delivery Plan;
4. approved architecture decisions;
5. approved Wave TECHSPEC;
6. approved task specifications;
7. authoritative `WAVE-REVIEW.md`;
8. repository constraints;
9. current implementation/tests.

The Wave review defines what is blocking. It does not authorize changes to
approved upstream scope.

## Preconditions

Before changing files:

- [ ] target Wave is explicit;
- [ ] authoritative `WAVE-REVIEW.md` exists;
- [ ] unresolved findings can be identified;
- [ ] remediation ownership is understood;
- [ ] approved Wave scope is available.

If the review artifact is ambiguous or stale in a way that prevents safe
remediation, report `BLOCKED`.

## Workflow

### 1. Load the authoritative Wave review

Read the current `WAVE-REVIEW.md`.

Build a remediation table containing:

- finding ID;
- severity;
- ownership;
- affected scope;
- required action;
- whether the action is executable by this skill.

### 2. Route findings by ownership

Handle each ownership as follows.

#### `WAVE_FIX`

Executable.

Remediate implementation, tests, non-approved operational documentation,
configuration, or Wave-local validation support necessary to satisfy the
approved Wave scope.

#### `TASK_REVIEW_REQUIRED`

Not executable.

Do not alter task-review artifacts to manufacture acceptance.

Record that independent `review-task` execution is required.

#### `NEW_TASK_REQUIRED`

Not automatically executable.

Do not silently create or redefine approved task scope.

Report the minimum task-planning action required and stop that finding as
`BLOCKED` unless the user has explicitly authorized task creation.

#### `MANUAL_VALIDATION_REQUIRED`

Conditionally executable.

If the approved validation procedure can be run safely in the current
environment without requiring unavailable external action, execute it and
persist the resulting evidence.

If user interaction, credentials, unavailable services, or another external
precondition is required, record it as blocked.

Do not fabricate validation evidence.

#### `ENVIRONMENT_BLOCKED`

Not executable as a code fix.

Diagnose and record the exact external dependency or environment failure.

Do not modify production code merely to bypass an acceptance environment
requirement unless the approved specification explicitly permits that behavior.

#### `SPEC_CHANGE_REQUIRED`

Not executable.

Do not change PRD, Delivery Plan, Architecture, TECHSPEC, or task scope.

Report the minimum upstream decision required.

### 3. Apply executable Wave-local remediation

For each executable finding:

- preserve approved behavior;
- make the smallest coherent correction;
- avoid unrelated refactoring;
- update tests when needed to validate the approved behavior;
- update non-approved operational documentation when needed;
- preserve provider-neutral boundaries unless the TECHSPEC says otherwise.

### 4. Validate remediation

Run validation proportional to the changes.

Prefer:

- focused tests for modified behavior;
- full applicable test suite;
- compile/build/import checks;
- lint/type checks when repository-defined;
- relevant end-to-end or manual acceptance steps;
- `git diff --check`.

Never mark a finding resolved solely because code was changed.

### 5. Record remediation evidence

Persist:

`tasks/<wave>/reviews/WAVE-REVIEW-REMEDIATION.md`

If repository convention defines an equivalent path, use it.

The remediation artifact is evidence of corrective work. It is NOT acceptance
evidence and does not replace `WAVE-REVIEW.md`.

For each finding record:

- original finding ID;
- ownership;
- remediation status;
- files changed;
- validation performed;
- evidence;
- remaining blocker if unresolved.

Use these remediation statuses:

`RESOLVED`

The corrective action is complete and validated, but still requires independent
Wave re-review before acceptance. A later Wave remains blocked until that
authoritative PASS and explicit persisted start authorization.

`REVIEW_REQUIRED`

Correction is complete but independent task or Wave review is required.

`BLOCKED`

This skill cannot complete the required remediation.

`SPEC_CHANGE_REQUIRED`

The finding cannot be resolved without an approved specification change.

### 6. Determine fix result

Return `READY_FOR_WAVE_REVIEW` only when all findings executable by this skill
have been remediated and no unresolved external/task-review/specification
blocker remains.

Return `PARTIAL` when some findings are resolved but others require another
workflow stage.

Return `BLOCKED` when no safe progress can continue.

Return `SPEC_CHANGE_REQUIRED` when an upstream approved artifact must change.

## Rules

### MUST

- operate on exactly one Wave;
- use the persisted Wave review as the authoritative finding source;
- preserve approved PRD, Delivery Plan, Architecture, TECHSPEC, and Wave scope;
- route findings by ownership;
- distinguish code fixes from review, evidence, environment, and spec work;
- validate every applied correction;
- persist remediation evidence;
- stop without independently accepting the Wave.

### MUST NOT

- run `review-task`;
- alter a task-review result to `PASS`;
- run `wave-review`;
- run `final-review`;
- start another Wave;
- change approved specifications;
- silently create new tasks;
- invent manual acceptance evidence;
- modify production code to mask an external environment failure;
- claim the Wave is accepted.

### SHOULD

- make minimal scoped changes;
- preserve traceability from finding to remediation;
- explicitly report non-executable findings and their next required workflow
  action;
- avoid re-solving findings already resolved in the current remediation run.

## Output

Persist `WAVE-REVIEW-REMEDIATION.md`:

```markdown
## Wave Review Remediation Result

<READY_FOR_WAVE_REVIEW | PARTIAL | BLOCKED | SPEC_CHANGE_REQUIRED>

## Wave

<wave identifier and name>

## Source Review

`<path to WAVE-REVIEW.md>`

## Findings

| Finding | Ownership | Status | Remediation |
|---|---|---|---|
| WAVE-001 | WAVE_FIX | RESOLVED | ... |

## Validation

| Check | Result | Evidence |
|---|---|---|
| ... | PASS / FAIL / NOT RUN | ... |

## Files Changed

- `<path>` — <reason>

## Remaining Workflow Actions

- <independent review, manual validation, environment action, task planning, or spec decision>

## Summary

<concise remediation state>
```

After persisting the artifact, report only:

1. remediation result;
2. remediation artifact path;
3. resolved findings count;
4. unresolved findings grouped by required next workflow action.

Do not automatically execute those next actions.
