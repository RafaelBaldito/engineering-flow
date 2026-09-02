---
name: fix-final-review
description: |
  Remediate actionable release-level blocking findings from the authoritative
  FINAL-REVIEW.md while preserving approved PRD, Delivery Plan, Architecture,
  TECHSPECs, accepted Wave boundaries, and release scope. Fix only executable
  RELEASE_FIX findings or explicitly executable release-level validation work.
  Record remediation evidence. Do not perform independent Wave/task review,
  change approved specifications, or automatically re-run final-review.
---

# Fix Final Review

## Purpose

Remediate actionable findings produced by `final-review`.

This skill operates at complete release scope.

It is not a substitute for:

- `fix-task`;
- `fix-wave-review`;
- `review-task`;
- `wave-review`;
- `final-review`.

The authoritative input is the persisted `FINAL-REVIEW.md`.

## When to Use

Use this skill when:

- an authoritative `FINAL-REVIEW.md` exists;
- final-review returned `FIX_REQUIRED` or contains executable release-level
  remediation;
- corrections must remain inside the already approved release scope.

Do not use this skill when:

- an included Wave still needs independent Wave review;
- the only blocker is an external environment dependency;
- approved specifications must change;
- the request is to decide final acceptance.

## Inputs

### Required

- authoritative `FINAL-REVIEW.md`;
- approved release scope;
- repository implementation state.

### Conditionally Required

Load when relevant:

- PRD;
- Delivery Plan;
- architecture/ADRs;
- TECHSPECs;
- Wave-review artifacts;
- task-review artifacts;
- release/manual acceptance procedure;
- runtime/provider configuration;
- tests.

## Authoritative Sources

Use this precedence:

1. current explicit user instructions that remain within approved release scope;
2. approved PRD;
3. approved Delivery Plan;
4. approved architecture decisions;
5. approved TECHSPECs;
6. accepted Wave-review artifacts;
7. authoritative `FINAL-REVIEW.md`;
8. repository constraints;
9. current implementation/tests.

The final review identifies the problem. It does not authorize changing approved
upstream scope.

## Preconditions

Before changing files:

- [ ] authoritative `FINAL-REVIEW.md` exists;
- [ ] release boundary is explicit;
- [ ] unresolved findings are identifiable;
- [ ] remediation ownership is understood;
- [ ] current repository state matches the review target closely enough for safe
      remediation.

If these conditions cannot be established, report `BLOCKED`.

## Workflow

### 1. Load authoritative final review

Create a remediation table with:

- finding ID;
- severity;
- ownership;
- affected scope;
- required action;
- whether this skill may execute it.

### 2. Route findings by ownership

#### `RELEASE_FIX`

Executable.

Correct release-level implementation, cross-Wave integration, tests,
configuration, non-approved operational documentation, packaging, or other
release-local defects while preserving approved scope.

#### `WAVE_REVIEW_REQUIRED`

Not executable.

Do not alter Wave-review artifacts or fabricate acceptance.

Record the exact Wave requiring independent `wave-review`.

#### `NEW_WAVE_OR_TASK_REQUIRED`

Not automatically executable.

Do not silently create or expand approved delivery scope.

Report the minimum planning/approval action required.

#### `MANUAL_VALIDATION_REQUIRED`

Conditionally executable.

If the approved release-validation procedure can be safely executed in the
current environment, execute it and persist evidence.

If it requires user action, unavailable credentials/services, or another
external precondition, report the blocker.

Never fabricate evidence.

#### `ENVIRONMENT_BLOCKED`

Not executable as a release code fix.

Diagnose and record the exact external tooling, sandbox, credential,
infrastructure, provider, or runtime dependency.

Do not alter production behavior merely to bypass an acceptance-environment
failure unless the approved specifications explicitly permit it.

#### `SPEC_CHANGE_REQUIRED`

Not executable.

Do not modify approved PRD, Delivery Plan, Architecture, TECHSPEC, or Wave scope.

Report the minimum upstream decision required.

### 3. Apply executable release remediation

For `RELEASE_FIX` findings:

- preserve approved behavior and architecture;
- make the smallest coherent correction;
- avoid unrelated refactoring;
- maintain compatibility across accepted Waves;
- update tests necessary to prove approved release behavior;
- update non-approved operational documentation when required.

Do not reopen accepted Wave scope unless the final finding demonstrates a
release-level integration defect involving that implementation.

### 4. Validate remediation

Run validation proportional to the changes, including when applicable:

- focused tests;
- full test suite;
- integration tests;
- release end-to-end checks;
- build/compile/import;
- lint/type checking;
- packaging/install checks;
- runtime smoke tests;
- `git diff --check`.

Never mark a finding resolved merely because files changed.

### 5. Persist remediation evidence

Persist:

`reviews/FINAL-REVIEW-REMEDIATION.md`

If repository convention defines another equivalent path, use it.

This artifact records corrective work. It does NOT replace
`FINAL-REVIEW.md` and does not constitute final acceptance.

For each finding use:

`RESOLVED`
- remediation is complete and validated; independent final re-review is still
  required.

`REVIEW_REQUIRED`
- corrective work is complete but an independent Wave or final review is
  required.

`BLOCKED`
- this skill cannot complete the required action.

`SPEC_CHANGE_REQUIRED`
- approved upstream scope must change.

### 6. Determine remediation result

Return `READY_FOR_FINAL_REVIEW` only when all findings executable by this skill
are remediated and no unresolved external, Wave-review, planning, or
specification blocker remains.

Return `PARTIAL` when some findings are resolved but another workflow action is
still required.

Return `BLOCKED` when safe progress cannot continue.

Return `SPEC_CHANGE_REQUIRED` when an upstream approved artifact must change.

## Rules

### MUST

- operate only on findings from the authoritative final review;
- preserve approved release scope;
- route findings by ownership;
- distinguish release defects from Wave review, manual validation, environment,
  planning, and specification work;
- validate every applied correction;
- persist remediation evidence;
- stop without accepting the release.

### MUST NOT

- run `review-task`;
- run `wave-review`;
- alter task/Wave review evidence to manufacture `PASS`;
- run `final-review`;
- change approved PRD, Delivery Plan, Architecture, TECHSPECs, or Wave scope;
- silently create new tasks or Waves;
- invent manual acceptance evidence;
- modify production code to mask an external environment failure;
- claim final release acceptance;
- commit, push, open PR, or deploy unless separately requested by an approved
  workflow stage.

### SHOULD

- make minimal release-scoped corrections;
- preserve finding-to-remediation traceability;
- group unresolved findings by their required next workflow action;
- avoid repeating remediation already proven in the current remediation run.

## Output

Persist:

```markdown
## Final Review Remediation Result

<READY_FOR_FINAL_REVIEW | PARTIAL | BLOCKED | SPEC_CHANGE_REQUIRED>

## Release Scope

<release identifier/scope>

## Source Review

`<path to FINAL-REVIEW.md>`

## Findings

| Finding | Ownership | Status | Remediation |
|---|---|---|---|
| FINAL-001 | RELEASE_FIX | RESOLVED | ... |

## Validation

| Check | Result | Evidence |
|---|---|---|
| ... | PASS / FAIL / NOT RUN | ... |

## Files Changed

- `<path>` — <reason>

## Remaining Workflow Actions

- <Wave review, manual validation, environment action, planning, or spec decision>

## Summary

<concise remediation state>
```

After persisting the artifact, report only:

1. remediation result;
2. remediation artifact path;
3. resolved findings count;
4. unresolved findings grouped by required next workflow action.

Do not automatically execute those next actions.
