---
description: |
  Fix implementation defects for exactly one reviewed task using the
  structured findings from review-task. Use after a task receives
  FIX_REQUIRED. Apply only the minimum changes needed to resolve
  accepted findings, rerun applicable validation, and return the task to
  a review-ready state. Do not redesign approved specifications, perform
  unrelated refactors, or mark the task PASS.
name: fix-task
---

# Fix Task

## Purpose

Correct implementation defects identified by an independent task review
while preserving the approved task contract and minimizing change
surface.

This skill is a constrained remediation step. It must resolve review
findings, not reopen implementation planning or opportunistically
improve unrelated code.

A successful fix returns the task to a state ready for `review-task`.

## When to Use

Use this skill when:

-   exactly one implemented task has received `FIX_REQUIRED`;
-   structured review findings identify defects within the approved task
    scope;
-   a previous fix did not fully resolve the findings and another
    remediation pass is explicitly requested.

Do not use this skill when:

-   no task review exists;
-   the task already has `PASS`;
-   the review result is `SPEC_CHANGE_REQUIRED`;
-   the review result is `BLOCKED` and the blocker has not been
    resolved;
-   the requested change is unrelated to the review findings;
-   the request is to perform a fresh implementation or broad refactor.

## Inputs

### Required

-   one selected reviewed `TASK-XXX.md`;
-   the latest applicable `review-task` result with `FIX_REQUIRED`;
-   repository state containing the reviewed implementation.

### Optional

Load only when required to understand or validate a finding:

-   `AGENTS.md`;
-   task Required Context;
-   specific TECHSPEC sections referenced by a finding;
-   relevant architecture sections or ADRs;
-   affected source files;
-   affected tests;
-   validation configuration;
-   previous fix/review result when needed to understand repeated
    findings.

## Authoritative Sources

Use the following precedence unless the user explicitly establishes
another authority:

1.  current explicit user instructions that remain within the approved
    fix scope;
2.  approved selected task;
3.  approved current-scope TECHSPEC;
4.  approved architecture decisions and ADRs;
5.  approved Delivery Plan boundary;
6.  approved PRD;
7.  latest applicable review findings;
8.  explicit repository constraints and conventions;
9.  existing implementation as evidence of current state.

Review findings identify defects and evidence, but they do not authorize
changes that contradict approved specifications.

If a finding can only be resolved by changing approved upstream scope or
design, report `SPEC_CHANGE_REQUIRED`.

## Preconditions

Before editing:

-   [ ] exactly one task is selected;
-   [ ] its latest applicable review result is `FIX_REQUIRED`;
-   [ ] the findings to resolve are identifiable;
-   [ ] the repository still contains the implementation being reviewed;
-   [ ] required context for the findings is available.

If the review findings or required repository state cannot be
established, report `BLOCKED`.

If remediation requires changing approved specifications, report
`SPEC_CHANGE_REQUIRED`.

## Workflow

### 1. Read the remediation contract

Read:

-   selected task;
-   latest applicable review result;
-   every blocking finding;
-   relevant validation evidence.

For each finding identify:

-   finding ID;
-   severity;
-   affected location;
-   observed defect;
-   expected behavior;
-   fix direction;
-   validation that can demonstrate resolution.

Do not treat non-blocking notes as mandatory work unless explicitly
requested.

Treat the approved task and all upstream planning artifacts as immutable. A
review finding may identify a contract defect, but it does not authorize
`fix-task` to edit that contract.

### 2. Load minimum required context

Read:

1.  `AGENTS.md` when present and applicable;
2.  selected task;
3.  latest review findings;
4.  files directly involved in those findings.

Load referenced TECHSPEC, architecture, adjacent source files, or tests
only when needed to understand the approved behavior.

Do not reload broad project context merely because it was used during
the original implementation.

### 3. Reproduce or confirm each defect

When practical, confirm the finding before editing by:

-   inspecting the reported code path;
-   running the failing targeted test;
-   reproducing the relevant validation failure;
-   verifying the contract mismatch.

If the finding is clearly established by static evidence, reproduction
is not mandatory.

If a finding is no longer applicable because repository state changed,
record that fact rather than making an unnecessary change.

### 4. Determine the minimum safe fix

For each blocking finding, identify the smallest coherent change that
restores approved behavior.

The fix may modify:

-   production code;
-   task-relevant tests;
-   configuration;
-   migrations;
-   directly affected documentation.

Do not broaden the fix into unrelated cleanup.

Multiple findings with the same root cause may be resolved by one
coherent change.

If any accepted finding requires changing approved task requirements,
acceptance criteria, validation commands, TECHSPECs, or architecture, stop
before editing and report `SPEC_CHANGE_REQUIRED`.

### 5. Apply fixes

Implement only changes necessary to resolve the selected task's review
findings.

Preserve:

-   task scope;
-   TECHSPEC decisions;
-   architecture constraints;
-   behavior that already passed review.

Do not rewrite working areas simply to use a preferred implementation
style.

### 6. Update tests when justified

Add or update tests when:

-   a finding exposes missing regression coverage;
-   approved behavior was implemented incorrectly;
-   the review explicitly identified inadequate task-scoped validation.

Do not weaken tests merely to make validation pass.

Do not remove meaningful assertions that expose a real defect.

### 7. Run targeted validation

For each fixed finding, run the narrowest useful validation that
demonstrates the defect is resolved.

Examples:

-   previously failing test;
-   targeted test module;
-   lint/type check for affected files;
-   relevant integration check.

Record actual results.

Never claim a finding is fixed solely because code changed.

### 8. Run applicable task validation

After targeted checks pass, rerun the task's applicable validation to
detect regressions introduced by the fix.

Prefer the same checks used by `review-task` when they are available and
relevant.

If a required validation cannot run, report the reason.

Keep targeted behavior checks separate from project-wide coverage gates. Do
not narrow, replace, or rewrite an approved validation command to make the fix
appear successful.

### 9. Inspect final change surface

Inspect the resulting diff or equivalent.

Verify:

-   changes map to review findings;
-   no unrelated refactor was introduced;
-   previously valid task behavior remains intact;
-   no secret or unintended generated file was added;
-   test changes do not hide failures.

Compare the selected task and upstream planning artifacts with their pre-fix
state. Their normative content must be unchanged; only status metadata in the
applicable task index may change when repository convention requires it.

Remove accidental changes.

### 10. Evaluate unresolved findings

For every blocking finding classify the remediation state as:

`RESOLVED`

Evidence demonstrates the finding has been addressed.

`UNRESOLVED`

The attempted fix did not resolve the defect but further work remains
within the approved task scope.

`SPEC_CHANGE_REQUIRED`

Correct resolution requires changing an approved upstream specification.

`BLOCKED`

Resolution cannot continue because required context, infrastructure, or
dependency is unavailable.

Do not mark the task `PASS`. Only `review-task` can accept the task.

### 11. Update task status when repository convention requires it

If all blocking findings are resolved and the task is ready for
re-review, recommended status:

`IMPLEMENTED`

If unresolved implementation defects remain:

`FIX_REQUIRED`

If escalation is required:

`SPEC_CHANGE_REQUIRED` or `BLOCKED`

Do not update unrelated tasks.

### 12. Report remediation result

Provide concise mapping from findings to fixes and validation evidence.

Stop after the selected task is ready for re-review or an escalation
state is reached.

Do not invoke `review-task` automatically.

## Rules

### MUST

-   fix exactly one reviewed task;
-   use the latest applicable review findings as remediation input;
-   preserve approved upstream specifications;
-   address blocking findings with concrete changes or explicit
    escalation;
-   keep changes tightly mapped to findings;
-   confirm fixes with actual validation when possible;
-   rerun applicable task validation;
-   inspect final change surface;
-   report unresolved findings honestly;
-   return successful remediation to a review-ready state;
-   stop before independent re-review.

### MUST NOT

-   mark a task `PASS`;
-   modify approved PRD scope;
-   modify the Delivery Plan;
-   redesign the approved TECHSPEC;
-   silently change architecture decisions;
-   fix unrelated issues;
-   perform opportunistic refactors;
-   implement future-task behavior;
-   weaken meaningful tests to hide defects;
-   dismiss a valid finding without evidence;
-   claim validation passed when it was not executed;
-   automatically invoke `review-task`;
-   automatically begin another task.

### SHOULD

-   prefer root-cause fixes over superficial patches;
-   use the smallest coherent change;
-   preserve already-correct behavior;
-   add regression tests for meaningful defects;
-   use targeted validation before broader validation;
-   avoid duplicating review evidence unnecessarily;
-   keep remediation understandable from the diff and concise report.

## Context Management

Read first:

-   selected `TASK-XXX.md`;
-   latest applicable `FIX_REQUIRED` review;
-   `AGENTS.md` when present;
-   files directly referenced by blocking findings.

Read only when needed:

-   task Required Context;
-   specific TECHSPEC sections;
-   relevant architecture sections;
-   adjacent source files;
-   affected tests;
-   validation configuration;
-   prior review/fix history needed to understand a repeated defect.

Do not load by default:

-   full PRD;
-   full Delivery Plan;
-   unrelated TECHSPEC sections;
-   future-Wave documentation;
-   unrelated tasks;
-   all source files;
-   all tests;
-   unrelated review history;
-   repository history.

The fix Context Surface should normally be no larger than the original
task execution context and should preferably be smaller because findings
identify specific defect locations.

If resolving a finding requires materially broader context, evaluate
whether the issue is actually a specification or task-boundary problem.

## Output

Modify only repository artifacts necessary to resolve the selected
task's review findings.

Typical outputs may include:

-   corrected source code;
-   regression or corrected tests;
-   configuration or migration fixes;
-   directly affected documentation;
-   task status metadata when used by the repository.

Return:

``` markdown
## Fix Result

<COMPLETED | FIX_REQUIRED | SPEC_CHANGE_REQUIRED | BLOCKED>

## Task

`TASK-XXX — <Title>`

## Findings

| Finding | Status | Fix |
|---------|--------|-----|
| FINDING-001 | RESOLVED / UNRESOLVED | <concise change> |

## Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `<command or check>` | PASS / FAIL / NOT RUN | <concise evidence> |

## Files Changed

- `<path>` — <purpose>

## Summary

<concise remediation result and anything requiring re-review attention>
```

Do not create a separate fix-report file unless repository conventions
explicitly require one.

## Validation

Before completing, verify:

-   [ ] exactly one reviewed task was modified;
-   [ ] every blocking finding has a remediation state;
-   [ ] changes map directly to findings;
-   [ ] approved specifications were preserved;
-   [ ] meaningful tests were not weakened to hide defects;
-   [ ] targeted validation was run when possible;
-   [ ] applicable task validation was rerun;
-   [ ] validation results are reported truthfully;
-   [ ] no unrelated changes remain in the final diff;
-   [ ] no secrets or unintended generated files were introduced;
-   [ ] the task was not marked `PASS`;
-   [ ] independent re-review was not started automatically.

## Completion

Always choose from `COMPLETED`, `FIX_REQUIRED`, `SPEC_CHANGE_REQUIRED`, or
`BLOCKED` according to the evidence. A request that prescribes only
`IMPLEMENTED` does not override escalation requirements.

Return `COMPLETED` when:

-   all blocking review findings are resolved;
-   applicable validation passes;
-   no new unresolved task-scoped defect remains;
-   the task is ready for independent re-review.

Recommended task status after successful remediation:

`IMPLEMENTED`

`COMPLETED` means "ready for re-review", not "accepted".

Return `FIX_REQUIRED` when:

-   one or more implementation findings remain unresolved;
-   further remediation is still possible within the approved task
    scope.

Do not invoke `review-task` automatically.

## Escalation

Return `BLOCKED` when:

-   the latest review findings cannot be identified;
-   repository state no longer permits safe remediation;
-   required infrastructure or dependencies prevent the fix or its
    validation;
-   mandatory context is unavailable.

Return `SPEC_CHANGE_REQUIRED` when:

-   a review finding cannot be correctly resolved without changing the
    approved task contract;
-   the fix requires changing the TECHSPEC or an approved architecture
    decision;
-   expected behavior conflicts with approved product or delivery scope;
-   repeated remediation demonstrates that the approved specification
    itself is the root cause.

When escalating:

1.  identify the affected finding;
2.  identify the conflicting task or upstream specification;
3.  provide concrete implementation/validation evidence;
4.  explain why another implementation-only fix would be incorrect;
5.  request the minimum upstream decision required.

Do not keep patching implementation when the correct resolution belongs
upstream.
