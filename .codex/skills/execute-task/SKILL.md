---
description: |
  Implement exactly one approved task from the current delivery scope.
  Use after the task set has been explicitly approved and one task has
  been selected for execution. Read only the bounded context required by
  that task, implement the approved change, run applicable validation,
  and report the result. Do not redesign approved specifications, expand
  scope, review other tasks, or continue automatically to another task.
name: execute-task
---

# Execute Task

## Purpose

Implement one approved task faithfully, with the smallest safe execution
context and change surface.

The task specification is the primary execution contract. This skill
converts that contract into code, tests, configuration, or other
repository changes without silently changing upstream product or
technical decisions.

Its goal is reliable, low-ambiguity execution suitable for efficient
execution models.

## When to Use

Use this skill when:

-   an approved task set exists;
-   one specific task has been selected;
-   the selected task is ready according to its declared dependencies;
-   implementation of that task is the requested next action;
-   a previously started task needs to be completed without changing its
    approved scope.

Do not use this skill when:

-   task decomposition is still awaiting approval;
-   no specific task has been selected;
-   prerequisite tasks are incomplete;
-   the request is primarily to review an implementation;
-   the request is to fix findings produced by a review;
-   implementation requires changing approved requirements or design.

## Inputs

### Required

-   one selected approved `TASK-XXX.md`.

### Optional

Load only according to the task Context Manifest or when necessary to
resolve a local implementation detail:

-   `AGENTS.md`;
-   referenced TECHSPEC sections;
-   referenced architecture sections or ADRs;
-   primary source files/components;
-   adjacent source files required to understand contracts;
-   relevant tests;
-   dependency/configuration files;
-   task dependency artifacts when explicitly required.

## Authoritative Sources

Use the following precedence unless the user explicitly establishes
another authority:

1.  current explicit user instructions that remain within the approved
    task scope;
2.  selected approved task;
3.  approved current-scope TECHSPEC;
4.  approved architecture decisions and ADRs;
5.  approved Delivery Plan boundary;
6.  approved PRD;
7.  explicit repository constraints and conventions;
8.  existing implementation as evidence of current state.

The selected task is the immediate execution contract, but it cannot
authorize a change that contradicts a higher-level approved
specification.

If the task conflicts with an approved upstream specification, do not
choose a side silently. Report `SPEC_CHANGE_REQUIRED`.

## Preconditions

Before changing the repository:

-   [ ] exactly one task is selected;
-   [ ] the task belongs to an approved task set;
-   [ ] all declared blocking dependencies are complete;
-   [ ] required task context is available;
-   [ ] the task has actionable acceptance criteria.

If a mandatory dependency or required context is unavailable, report
`BLOCKED`.

If execution requires changing approved scope or design, report
`SPEC_CHANGE_REQUIRED`.

## Workflow

### 1. Read the execution contract

Read the selected task completely.

Identify:

-   objective;
-   scope;
-   Required Context;
-   Optional Context;
-   implementation requirements;
-   constraints;
-   acceptance criteria;
-   validation expectations;
-   dependencies;
-   out-of-scope items.

Do not begin implementation before understanding the complete task
contract.

Treat approved planning artifacts and the normative content of the selected
task as immutable execution inputs. Execution authorization does not authorize
editing requirements, acceptance criteria, validation commands, TECHSPECs,
architecture decisions, or other approved contracts. If one of those inputs
must change, report `SPEC_CHANGE_REQUIRED` instead of rewriting it.

### 2. Load the minimum required context

Read:

1.  `AGENTS.md` when present and applicable;
2.  the selected task;
3.  every item explicitly listed under Required Context.

Load Optional Context only when implementation cannot proceed safely
without it.

Prefer specific referenced TECHSPEC sections over the complete TECHSPEC.

Do not load the full PRD, all Waves, all tasks, all architecture
documentation, or the whole repository by default.

### 3. Verify dependency state

Confirm that declared prerequisite tasks have produced the repository
state or artifacts this task expects.

Do not reimplement completed prerequisite work.

If a prerequisite is incomplete or its expected contract is absent,
report `BLOCKED` unless the issue is explicitly within the selected
task's scope.

### 4. Inspect the current implementation

Before editing, inspect the files/components directly affected by the
task.

Determine:

-   existing behavior;
-   established patterns;
-   integration points;
-   nearby tests;
-   whether repository state differs materially from what the task
    expects.

Small implementation differences may be handled locally when they do not
change approved behavior or design.

Material specification conflicts must be escalated.

### 5. Plan the local change

Form a concise implementation approach bounded by the task.

The plan should identify:

-   files/components likely to change;
-   behavior to add or modify;
-   tests or validation to add/update;
-   any local compatibility concern.

Do not create a new project-wide architecture or redesign unrelated
code.

### 6. Implement the task

Make only changes necessary to satisfy the task.

Implementation may include, when explicitly required:

-   production code;
-   tests;
-   configuration;
-   migrations;
-   documentation directly affected by behavior;
-   dependency changes justified by the approved design.

Preserve existing conventions unless the task explicitly changes them.

Avoid speculative abstractions and unrelated cleanup.

### 7. Maintain scope discipline during execution

When new information appears, classify it:

**Local implementation detail**

Resolve it when:

-   it stays within task scope;
-   it does not change acceptance criteria;
-   it does not contradict the TECHSPEC or architecture;
-   it is a normal implementation choice.

**Unrelated improvement**

Do not implement it. Mention it only when materially relevant.

**Specification conflict**

Stop scope expansion and report `SPEC_CHANGE_REQUIRED`.

**Missing prerequisite/context**

Report `BLOCKED`.

### 8. Implement or update tests

Add or update tests required by the task and approved validation
strategy.

Prefer tests that demonstrate the task's acceptance criteria.

Do not inflate the task with unrelated test-suite refactoring.

When existing tests must change because approved behavior changes,
update them within task scope.

### 9. Run validation

Run the validation explicitly required by the task.

Also run repository-native checks that are directly applicable and
reasonably scoped, when known.

Examples:

-   targeted tests;
-   relevant integration tests;
-   lint;
-   type checking;
-   import/build checks;
-   migration/database verification.

Never claim a command passed unless it was actually executed.

If a required validation command cannot be executed, report it
explicitly.

Keep validation purposes distinct:

-   targeted tests demonstrate the selected task's behavior and should not
    measure unrelated production modules;
-   project-wide coverage gates run the repository-wide suite against the
    complete production coverage surface.

If an approved command mixes a targeted test selection with a project-wide
coverage threshold that cannot be satisfied within task scope, do not alter the
command. Report `SPEC_CHANGE_REQUIRED` with the exact conflicting command.

### 10. Handle validation failures

If validation fails because of the implementation created in this task:

-   diagnose the failure;
-   fix it when the fix remains within task scope;
-   rerun the affected validation.

Do not use validation failures as justification for unrelated
refactoring.

If the failure reveals an upstream specification problem, report
`SPEC_CHANGE_REQUIRED`.

If the failure is caused by unavailable infrastructure or an external
blocker, report `BLOCKED`.

### 11. Check the resulting change surface

Before completion, inspect the final repository diff or equivalent
change set.

Verify:

-   only intended files changed;
-   no accidental generated or secret files were added;
-   no unrelated behavior was modified;
-   tests/config/docs changed only when justified;
-   task acceptance criteria are represented by the implementation.

Compare approved task and upstream planning artifacts with their pre-execution
state. Their normative content must be unchanged. Only the selected task's
status metadata or its index entry may change when repository convention
requires it.

Remove accidental changes before completing.

Before reporting success, evaluate every acceptance criterion individually.
For each criterion, record the implementation evidence, test evidence, and
executed validation that demonstrate it. A criterion without sufficient
evidence prevents successful completion.

### 12. Update task status when the repository convention requires it

If the task system uses status tracking, update the selected task/index
only according to the established convention.

Recommended successful status:

`IMPLEMENTED`

Do not mark the task as `PASS` or fully accepted. Acceptance belongs to
`review-task`.

Do not change the status of unrelated tasks.

### 13. Report execution result

Provide a concise implementation summary and validation evidence.

Do not invoke `review-task` or begin the next task automatically.

## Rules

### MUST

-   execute exactly one selected task;
-   treat the task as the immediate execution contract;
-   preserve approved upstream specifications;
-   load Required Context before implementation;
-   keep Optional Context demand-driven;
-   inspect existing affected code before editing;
-   make the smallest coherent change that satisfies the task;
-   implement or update task-relevant tests when required;
-   run required validation when executable;
-   report validation evidence accurately;
-   inspect the final change surface;
-   stop after the selected task is implemented.

### MUST NOT

-   implement multiple tasks in one execution unless the approved task
    explicitly defines them as one unit;
-   change PRD scope;
-   change the Delivery Plan;
-   redesign the approved TECHSPEC;
-   silently override architecture decisions;
-   implement future-task behavior for convenience;
-   perform unrelated refactors;
-   add speculative abstractions;
-   load broad repository context without need;
-   hide failed or unexecuted validation;
-   expose or commit secrets;
-   automatically invoke `review-task`;
-   automatically start the next task;
-   claim review acceptance.

### SHOULD

-   prefer existing project patterns;
-   minimize file and dependency changes;
-   keep implementation straightforward;
-   use targeted validation before broader validation;
-   keep comments focused on non-obvious intent rather than restating
    code;
-   update directly affected documentation when behavior or usage
    changes;
-   preserve backward compatibility when required by the approved
    design.

## Context Management

Read first:

-   selected `TASK-XXX.md`;
-   `AGENTS.md` when present;
-   all task Required Context.

Read only when needed:

-   task Optional Context;
-   adjacent source files;
-   relevant tests;
-   dependency/configuration files;
-   specific upstream specification sections needed to resolve local
    ambiguity.

Do not load by default:

-   full PRD;
-   full Delivery Plan;
-   unrelated TECHSPEC sections;
-   future-Wave documentation;
-   all task files;
-   all source files;
-   all tests;
-   review history;
-   repository history.

Execution Context targets:

-   task specification: preferably approximately 1,500 tokens or less;
-   required documentation references: preferably 3 or fewer;
-   primary source files/components: preferably 5 or fewer.

These are soft targets.

If actual execution requires materially more context than the task
declares, determine whether this is a legitimate local need or evidence
of an over-broad/incomplete task.

Do not mechanically refuse execution because a soft target is exceeded.

## Output

Modify only repository artifacts necessary to implement the selected
task.

Typical outputs may include:

-   source code;
-   tests;
-   configuration;
-   migrations;
-   directly affected documentation;
-   task status metadata when the repository uses it.

Do not create a separate implementation report file unless the
repository explicitly requires one.

The completion response must contain:

``` markdown
## Result

<COMPLETED | BLOCKED | SPEC_CHANGE_REQUIRED>

## Implemented

- <concise change summary>

## Validation

- `<command>` — PASS | FAIL | NOT RUN
  - <relevant evidence or reason>

## Acceptance Criteria

| Criterion | Result | Evidence |
|-----------|--------|----------|
| <criterion> | PASS / FAIL / NOT VERIFIED | <code, test, and validation evidence> |

## Files Changed

- `<path>` — <purpose>

## Notes

- <only material implementation notes, blockers, or follow-up information>
```

Keep the report concise. The repository and validation output are the
primary evidence.

## Validation

Before reporting completion, verify:

-   [ ] exactly one task was executed;
-   [ ] all task acceptance criteria were addressed;
-   [ ] implementation remains within approved scope;
-   [ ] Required Context was inspected;
-   [ ] relevant existing implementation was inspected before editing;
-   [ ] required tests were added or updated when applicable;
-   [ ] required validation was actually executed when possible;
-   [ ] validation results are reported truthfully;
-   [ ] failures within task scope were resolved or explicitly reported;
-   [ ] final changes contain no unrelated edits;
-   [ ] every acceptance criterion has explicit implementation and validation
      evidence;
-   [ ] approved task and upstream planning content is unchanged, except for
      explicitly authorized status metadata;
-   [ ] no secrets or unintended generated files were introduced;
-   [ ] no upstream specification was silently changed;
-   [ ] no next task or review stage was started automatically.

## Completion

Return `COMPLETED` when:

-   implementation satisfies the selected task;
-   applicable required validation passes;
-   no unresolved task-scoped failure remains;
-   the change is ready for independent `review-task`.

If status tracking is used, mark the task as `IMPLEMENTED`, not `PASS`.

A `COMPLETED` execution means implementation is ready for review. It
does not mean the task has passed review.

Provide the concise result format defined above and stop.

## Escalation

Return `BLOCKED` when:

-   a declared prerequisite task is incomplete;
-   mandatory Required Context is unavailable;
-   required infrastructure or dependency prevents implementation or
    validation;
-   repository state is insufficient to continue safely;
-   a required validation cannot be completed and the task cannot
    reasonably be considered ready for review.

Return `SPEC_CHANGE_REQUIRED` when:

-   the task contradicts the approved TECHSPEC;
-   implementation requires changing an approved architecture decision;
-   acceptance criteria require behavior outside the approved delivery
    scope;
-   the task cannot be implemented without changing an approved product
    requirement;
-   the task's Context Surface reveals that its approved boundary is
    materially incorrect rather than merely inconvenient.

When escalating:

1.  stop unrelated implementation work;
2.  identify the exact task requirement or upstream specification
    involved;
3.  provide concrete repository evidence when available;
4.  explain the minimum upstream decision required;
5.  preserve already-valid changes only when they remain safe and
    clearly within scope.

Do not silently rewrite the task or upstream specifications to make
execution possible.
