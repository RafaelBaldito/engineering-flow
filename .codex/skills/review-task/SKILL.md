---
description: |
  Review the implementation of exactly one task after execution. Use
  when a selected task has been implemented and is ready for independent
  validation against its approved task contract, TECHSPEC, architecture
  constraints, and repository quality checks. Produce PASS or
  FIX_REQUIRED with structured, evidence-based findings. Do not fix
  code, expand scope, redesign upstream specifications, or review
  unrelated tasks.
name: review-task
---

# Review Task

## Purpose

Independently verify whether one implemented task satisfies its approved
contract and is ready to be accepted.

This skill combines deterministic validation with semantic review. It
checks both whether the implementation works and whether it matches the
approved scope, design, and acceptance criteria.

The reviewer must remain independent from implementation and must not
silently repair defects while reviewing.

## When to Use

Use this skill when:

-   one specific task has been implemented;
-   the task is marked or considered ready for review;
-   implementation validation must be checked independently;
-   a previously reviewed task was fixed and needs re-review.

Do not use this skill when:

-   the selected task has not been implemented;
-   the request is to make code changes;
-   the request is to review an entire Wave or project;
-   the request is to create or redesign requirements;
-   the request is to review multiple unrelated tasks together.

## Inputs

### Required

-   one selected implemented `TASK-XXX.md`;
-   repository state containing that task's implementation.

### Optional

Load only when necessary to validate the selected task:

-   `AGENTS.md`;
-   task Required Context;
-   referenced TECHSPEC sections;
-   referenced architecture sections or ADRs;
-   changed source files;
-   relevant adjacent source files;
-   changed and relevant tests;
-   validation configuration;
-   implementation summary from `execute-task`, if available.

## Authoritative Sources

Use the following precedence unless the user explicitly establishes
another authority:

1.  current explicit user instructions that remain within review scope;
2.  selected approved task;
3.  approved current-scope TECHSPEC;
4.  approved architecture decisions and ADRs;
5.  approved Delivery Plan boundary;
6.  approved PRD;
7.  explicit repository constraints and conventions;
8.  implementation under review.

The implementation is evidence to inspect, not authority over approved
specifications.

If the task itself conflicts with approved upstream specifications, do
not mark the implementation as correct merely because it follows the
task. Report `SPEC_CHANGE_REQUIRED`.

## Preconditions

Before reviewing:

-   [ ] exactly one task is selected;
-   [ ] the task belongs to an approved task set;
-   [ ] implementation for that task exists;
-   [ ] required review context is available;
-   [ ] acceptance criteria can be evaluated.

If implementation is missing or required context is unavailable, report
`BLOCKED`.

If review reveals an upstream specification contradiction that cannot be
resolved at task level, report `SPEC_CHANGE_REQUIRED`.

## Workflow

### 1. Read the review contract

Read the selected task completely.

Identify:

-   objective;
-   scope;
-   acceptance criteria;
-   validation requirements;
-   constraints;
-   dependencies;
-   Required Context;
-   Out of Scope.

Do not infer success criteria from implementation alone.

### 2. Load bounded review context

Read:

1.  `AGENTS.md` when present and applicable;
2.  the selected task;
3.  task Required Context;
4.  changed files associated with the task.

Load additional context only when necessary to validate behavior or
resolve a potential finding.

For re-review, load the latest review handoff and its prior blocking findings.
This is required review context, not unrelated review history.

Prefer specific TECHSPEC sections over full documents.

Do not load unrelated Waves, tasks, source files, or project history by
default.

### 3. Inspect the implementation change

Inspect the relevant diff or equivalent repository changes.

Determine:

-   what behavior changed;
-   which files changed;
-   whether the change matches the task objective;
-   whether unrelated files or behavior were modified;
-   whether tests and documentation changed appropriately.

Do not fix issues while inspecting.

### 4. Run deterministic validation

Run all applicable validation required by the task and repository
conventions.

Examples:

-   targeted unit tests;
-   relevant integration tests;
-   full relevant test suite;
-   lint;
-   type checking;
-   import/build checks;
-   database/migration validation;
-   static security checks when already established by the repository.

Never claim a check passed unless it was actually executed.

Record command, result, and material evidence.

If a required command cannot run, report the reason explicitly.

### 5. Review acceptance criteria

Evaluate every acceptance criterion individually.

For each criterion, determine whether it is:

-   satisfied;
-   not satisfied;
-   not verifiable with available evidence.

Do not assume a criterion is satisfied merely because tests pass.

Complete the full acceptance-criteria matrix before deciding the result. Do
not stop after finding the first blocking defect.

Perform a complete-pass review of all applicable acceptance criteria, changed
files, specification contracts, and deterministic gates. Report every material
finding identifiable from the current repository state, grouping findings that
share one root cause.

On re-review:

-   verify every previous blocking finding and record whether it is resolved;
-   check the complete acceptance matrix again to detect regressions;
-   do not limit inspection to lines changed by the fix;
-   mark a pre-existing material defect omitted by the preceding review as
    `MISSED_IN_PREVIOUS_REVIEW: yes` and explain why it is newly reported;
-   mark a defect introduced by remediation as `REGRESSION_FROM_FIX: yes`.

### 6. Review specification compliance

Check implementation against:

-   selected task requirements;
-   referenced TECHSPEC decisions;
-   relevant architecture constraints;
-   delivery boundary.

Look for:

-   missing required behavior;
-   behavior outside scope;
-   contract mismatches;
-   architectural violations;
-   silent changes to approved assumptions.

If implementation reveals that the approved task or TECHSPEC itself is
incorrect, distinguish that from an implementation defect.

### 7. Review code quality within scope

Inspect only quality concerns that materially affect the selected task.

Consider when relevant:

-   correctness;
-   readability;
-   maintainability;
-   duplication introduced by the change;
-   error handling;
-   boundary conditions;
-   resource management;
-   dependency usage;
-   compatibility;
-   logging/observability;
-   security hygiene.

Do not turn review into a broad refactoring audit.

A stylistic preference that does not violate repository conventions or
create a meaningful quality risk should not become a blocking finding.

### 8. Review tests

Evaluate whether tests:

-   cover important acceptance behavior;
-   exercise failure paths where relevant;
-   are meaningful rather than tautological;
-   follow repository patterns;
-   avoid excessive implementation coupling;
-   demonstrate regressions prevented by the task.

Do not require arbitrary coverage percentages unless the repository or
task defines them.

If coverage tooling exists and is relevant, use it as evidence rather
than as the sole quality criterion.

### 9. Review scope discipline

Verify that the implementation did not:

-   implement future tasks;
-   perform unrelated refactors;
-   add speculative abstractions;
-   introduce unnecessary dependencies;
-   modify upstream specification artifacts without authorization;
-   change unrelated behavior.

Unrelated changes should become findings when they increase risk or
violate the task contract.

### 10. Classify findings

Every material issue must be classified by severity.

Use:

`CRITICAL`

-   severe correctness, security, data-loss, or specification violation
    that makes the implementation unsafe to accept.

`HIGH`

-   major task requirement not satisfied;
-   important behavior is incorrect;
-   significant architecture or contract violation;
-   required validation fails materially.

`MEDIUM`

-   real quality, edge-case, testing, or maintainability issue that
    should be fixed before acceptance but is not catastrophic.

`LOW`

-   non-blocking improvement with concrete value.

Avoid subjective or cosmetic findings without material impact.

Each finding must include:

-   identifier;
-   severity;
-   location;
-   issue;
-   evidence;
-   expected behavior;
-   suggested fix direction without implementing it.

### 11. Determine review outcome

Always choose from `PASS`, `FIX_REQUIRED`, `SPEC_CHANGE_REQUIRED`, or
`BLOCKED` according to the evidence. A request that mentions only a subset of
these states does not authorize misclassifying a specification conflict or
blocker as `FIX_REQUIRED`.

Return `PASS` only when:

-   all acceptance criteria are satisfied;
-   required validation passes or has an explicitly acceptable reason
    not to run;
-   no `CRITICAL`, `HIGH`, or `MEDIUM` blocking finding remains;
-   implementation stays within approved scope.

Return `FIX_REQUIRED` when implementation defects within the approved
task scope must be corrected.

Return `SPEC_CHANGE_REQUIRED` when the implementation cannot be judged
or fixed correctly without changing an approved upstream specification.

Return `BLOCKED` when review cannot be completed because required
evidence, infrastructure, or context is unavailable.

### 12. Update task status when repository convention requires it

If task status tracking is used:

On `PASS`, recommended status:

`PASS`

On `FIX_REQUIRED`, recommended status:

`FIX_REQUIRED`

On `SPEC_CHANGE_REQUIRED`:

`SPEC_CHANGE_REQUIRED`

On `BLOCKED`:

`BLOCKED`

Do not change unrelated task statuses.

### 13. Persist a fix handoff

When the outcome is `FIX_REQUIRED`, create a durable handoff for `fix-task`.

- Create `<selected-task-parent>/reviews/TASK-XXX-REVIEW.md`. For example,
  a selected `tasks/<wave-id>/TASK-XXX.md` produces
  `tasks/<wave-id>/reviews/TASK-XXX-REVIEW.md`; a single-delivery task under
  `tasks/` produces `tasks/reviews/TASK-XXX-REVIEW.md`.
- Update the selected task's status to `FIX_REQUIRED` in the applicable task
  index when that index exists.
- Write the complete review-result format from this skill to the handoff file,
  including executed validation evidence, each acceptance-criterion result,
  and all structured findings. It must give `fix-task` sufficient context to
  act without reconstructing the review.
- Do not create a handoff artifact for `PASS`, `SPEC_CHANGE_REQUIRED`, or
  `BLOCKED`. Do not commit or push review artifacts unless the user explicitly
  asks for that action.

### 14. Produce the review result

Return a concise evidence-based report.

Do not modify code.

Do not invoke `fix-task` automatically.

## Rules

### MUST

-   review exactly one selected task;
-   remain independent from implementation;
-   evaluate every acceptance criterion;
-   run applicable deterministic validation;
-   report validation results truthfully;
-   compare implementation with approved specifications;
-   inspect relevant tests;
-   classify material findings by severity;
-   distinguish implementation defects from specification defects;
-   base findings on concrete evidence;
-   stop after producing the review result.

### MUST NOT

-   modify production code;
-   modify tests to make them pass;
-   silently fix review findings;
-   redesign the approved task;
-   change the PRD, Delivery Plan, TECHSPEC, or architecture;
-   review unrelated tasks;
-   create speculative findings;
-   fail a task solely because of personal style preference;
-   claim a validation command ran when it did not;
-   automatically invoke `fix-task`;
-   automatically start another review.

### SHOULD

-   prefer targeted validation before broader checks;
-   keep findings minimal and actionable;
-   avoid duplicate findings for the same root cause;
-   cite exact files, symbols, tests, or commands where useful;
-   distinguish blocking from non-blocking observations;
-   recognize repository-native conventions;
-   avoid requiring new tooling unless already mandated.

## Context Management

Read first:

-   selected `TASK-XXX.md`;
-   `AGENTS.md` when present;
-   task Required Context;
-   files changed by the implementation.

Read only when needed:

-   task Optional Context;
-   referenced TECHSPEC sections;
-   architecture sections;
-   adjacent implementation files;
-   relevant tests;
-   validation configuration;
-   dependency artifacts.

Do not load by default:

-   full PRD;
-   full Delivery Plan;
-   unrelated TECHSPEC sections;
-   future-Wave documentation;
-   all tasks;
-   all source files;
-   all tests;
-   unrelated review history;
-   repository history.

Review context should remain proportional to the selected task.

If validating the task requires materially broader context than
declared, determine whether this indicates a task-boundary problem and
report it when relevant.

## Output

Do not create or modify production artifacts.

Update task status metadata only when the repository's task convention
requires it.

Return:

``` markdown
## Review Result

<PASS | FIX_REQUIRED | SPEC_CHANGE_REQUIRED | BLOCKED>

## Task

`TASK-XXX — <Title>`

## Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `<command or check>` | PASS / FAIL / NOT RUN | <concise evidence> |

## Acceptance Criteria

| Criterion | Result | Evidence |
|-----------|--------|----------|
| <criterion> | PASS / FAIL / NOT VERIFIED | <evidence> |

## Findings

### FINDING-001 — <Severity> — <Title>

- Location: `<path:symbol-or-line>`
- Issue: <what is wrong>
- Evidence: <concrete evidence>
- Expected: <approved expected behavior>
- Fix direction: <concise non-implementation guidance>
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: yes|no`;
  `REGRESSION_FROM_FIX: yes|no`

## Non-Blocking Notes

- <optional low-severity observations>

## Summary

<concise reason for the result>
```

For `PASS`, the Findings section may be omitted when no findings exist.

For `FIX_REQUIRED`, the required handoff artifact above is the exception to
the normal rule against creating separate review artifacts.

## Validation

Before completing the review, verify:

-   [ ] exactly one task was reviewed;
-   [ ] task acceptance criteria were evaluated individually;
-   [ ] applicable validation was actually run;
-   [ ] validation evidence is truthful;
-   [ ] relevant implementation changes were inspected;
-   [ ] relevant tests were inspected;
-   [ ] approved TECHSPEC/architecture constraints were checked where
    applicable;
-   [ ] findings are evidence-based;
-   [ ] severity reflects material impact;
-   [ ] implementation defect and specification defect are
    distinguished;
-   [ ] no code or tests were modified;
-   [ ] no unrelated task was reviewed;
-   [ ] no fix stage was started automatically.
-   [ ] when `FIX_REQUIRED`, the handoff artifact and applicable task status
      were updated without committing or pushing.

## Completion

Return `PASS` when the task is accepted.

Return `FIX_REQUIRED` when one or more implementation defects must be
corrected within the existing approved task scope.

Do not return `FIX_REQUIRED` when the required correction changes approved
task requirements, acceptance criteria, validation contracts, TECHSPECs, or
architecture. Return `SPEC_CHANGE_REQUIRED` even if the invoking prompt lists
only `PASS` and `FIX_REQUIRED`.

A `PASS` result means the selected task has completed independent review and
is accepted at the task layer only. It is evidence for, but never a substitute
for, the later Wave-review acceptance gate.

A `FIX_REQUIRED` result must include sufficient structured findings for
`fix-task` to act without reconstructing the entire review.

Do not invoke the next workflow stage automatically. After every required task
has task-level PASS, `wave-review` may be requested separately for that Wave.

## Escalation

Return `BLOCKED` when:

-   implementation for the selected task cannot be identified;
-   required review context is unavailable;
-   mandatory validation infrastructure is unavailable and prevents a
    reliable decision;
-   repository state prevents determination of the task result.

Return `SPEC_CHANGE_REQUIRED` when:

-   the selected task contradicts the approved TECHSPEC;
-   the TECHSPEC contradicts an approved architecture or product
    requirement;
-   satisfying the task acceptance criteria would require violating
    approved upstream scope or design;
-   review reveals that the defect cannot be fixed correctly within the
    approved task contract.

When escalating:

1.  identify the exact conflicting artifact and section;
2.  provide concrete implementation or validation evidence;
3.  explain why `fix-task` would be insufficient;
4.  request the minimum upstream decision necessary.

Do not downgrade specification conflicts into implementation findings
merely to keep the task moving.
