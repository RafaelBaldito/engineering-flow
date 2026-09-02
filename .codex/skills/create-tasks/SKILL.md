---
description: |
  Decompose one approved implementation-ready TECHSPEC into bounded,
  executable tasks. Use after the current SINGLE scope or Wave TECHSPEC
  has been explicitly approved. Produce an ordered task index and
  focused task specifications with minimal required context. Do not
  redesign the approved solution, implement code, review implementation,
  or create tasks for future delivery scopes.
name: create-tasks
---

# Create Tasks

## Purpose

Transform one approved TECHSPEC into a small, ordered set of
implementation tasks that can be executed independently or with explicit
dependencies.

Each task must behave like a high-quality engineering work item: clear
goal, bounded scope, required context, constraints, acceptance criteria,
and validation expectations.

The primary optimization target is reliable execution with a bounded
Context Surface.

## When to Use

Use this skill when:

-   a `SINGLE` TECHSPEC has been explicitly approved and is ready for
    implementation decomposition;
-   one Wave TECHSPEC has been explicitly approved and is ready for
    implementation decomposition;
-   an approved TECHSPEC changed and its task set must be explicitly
    regenerated or updated;
-   implementation needs smaller work units before `execute-task`.

Do not use this skill when:

-   the current TECHSPEC is not approved;
-   the technical design is still unresolved;
-   the request requires changing product or delivery scope;
-   the request is to create tasks for future Waves whose TECHSPECs do
    not yet exist;
-   the request is to implement, review, or fix code.

## Inputs

### Required

-   one approved current-scope TECHSPEC.

### Optional

Load only when required to preserve traceability or repository
conventions:

-   relevant approved PRD sections;
-   relevant approved Delivery Plan section;
-   `AGENTS.md`;
-   relevant architecture sections or ADRs;
-   repository README or overview;
-   relevant source files and tests;
-   existing task set when updating it.

## Authoritative Sources

Use the following precedence unless the user explicitly establishes
another authority:

1.  current explicit user instructions authorized to change task
    decomposition;
2.  approved current-scope TECHSPEC;
3.  approved architecture decisions referenced by the TECHSPEC;
4.  approved Delivery Plan boundary;
5.  approved PRD requirements assigned to the scope;
6.  explicit repository constraints and conventions;
7.  existing implementation as evidence of current state.

Task decomposition must implement the approved technical design, not
redesign it.

If task creation reveals that the TECHSPEC cannot be implemented
coherently, do not repair the specification silently. Report
`SPEC_CHANGE_REQUIRED`.

## Preconditions

Before creating tasks:

-   [ ] exactly one current delivery scope is selected;
-   [ ] its TECHSPEC exists;
-   [ ] the TECHSPEC has been explicitly approved;
-   [ ] critical technical questions required for implementation are
    resolved.

If approval or scope cannot be established, report `BLOCKED`.

If safe task decomposition requires changing the approved design, report
`SPEC_CHANGE_REQUIRED`.

## Workflow

### 1. Establish the task boundary

Identify from the approved TECHSPEC:

-   implementation objective;
-   included requirements;
-   affected components;
-   technical decisions;
-   interfaces and contracts;
-   validation expectations;
-   explicit implementation boundaries;
-   known risks and dependencies.

Do not include future delivery scopes.

### 2. Inspect implementation context selectively

Inspect only enough repository context to produce realistic work units.

Use it to understand:

-   existing file/module boundaries;
-   relevant tests;
-   established patterns;
-   likely integration points;
-   existing configuration or infrastructure.

Do not perform a broad code review.

Existing code may influence task boundaries, but it must not silently
override the approved TECHSPEC.

### 3. Identify implementation units

Decompose the TECHSPEC into cohesive engineering outcomes.

A task should preferably:

-   have one primary objective;
-   produce a reviewable change;
-   have clear acceptance criteria;
-   have explicit dependencies;
-   be independently verifiable when practical;
-   avoid mixing unrelated concerns.

Do not equate one task with one file.

Do not create tiny tasks for trivial edits that are naturally part of
the same implementation outcome.

### 4. Order tasks by dependency

Build the minimum necessary dependency graph.

Prefer:

-   enabling contracts before consumers;
-   required infrastructure before behavior that depends on it;
-   implementation and directly related tests within the same task when
    this keeps the outcome cohesive;
-   early tasks that reduce uncertainty for later tasks.

Avoid long dependency chains when tasks can safely remain independent.

Do not encode dependencies that exist only because of arbitrary task
numbering.

### 5. Define each task contract

Each task must contain:

-   identifier;
-   title;
-   objective;
-   scope;
-   required context;
-   implementation requirements;
-   constraints;
-   acceptance criteria;
-   validation;
-   dependencies;
-   explicit out-of-scope items when useful.

The task must provide enough direction for `execute-task` without
requiring the execution agent to reconstruct planning decisions.

### 6. Build the Context Manifest

Each task must explicitly identify the minimum context needed for
execution.

Use:

``` markdown
## Context

### Required
- <specific TECHSPEC section>
- <primary source file or component>

### Optional
- <architecture section or adjacent source file>
```

Prefer references to specific document sections rather than entire
documents.

Required documentation references should preferably be no more than 3.

Primary source files or components should preferably be no more than 5.

These are soft targets, not hard limits.

Do not add a file to Required Context merely because it might be useful.

### 7. Evaluate Context Surface

Evaluate the total information an execution agent must inspect,
including:

-   task specification size;
-   required documentation;
-   source files or components;
-   architecture decisions;
-   prerequisite-task knowledge;
-   cross-component dependencies.

A short task with many mandatory references is still a large-context
task.

If Context Surface is excessive:

1.  determine whether the task contains multiple independent outcomes;
2.  split it when doing so preserves a coherent implementation sequence;
3.  remove unnecessary Required Context;
4.  use focused TECHSPEC section references;
5.  if the problem originates from an over-broad or incomplete approved
    TECHSPEC, report `SPEC_CHANGE_REQUIRED`.

Do not mechanically split a cohesive task only to satisfy numeric
targets.

### 8. Define acceptance criteria

Acceptance criteria must be observable and specific to the task.

They should describe what must be true after implementation.

Where useful, trace them to:

-   TECHSPEC decisions;
-   assigned product requirements;
-   expected integration behavior.

Do not use vague criteria such as:

-   "works correctly";
-   "code is clean";
-   "implementation is complete".

### 9. Define validation expectations

Specify commands or checks when they are already known from repository
conventions or the approved TECHSPEC.

Examples:

-   targeted tests;
-   full relevant test suite;
-   lint;
-   type checking;
-   import/build verification;
-   database verification;
-   manual behavior checks.

Do not claim validation has been executed during task creation.

Do not invent project tooling solely to populate this section.

Keep validation layers semantically separate:

-   targeted task tests validate the behavior owned by the task;
-   module coverage may target only the production module exercised by those
    tests when repository tooling supports that form reliably;
-   project-wide coverage thresholds must run the repository-wide suite over
    the complete production coverage surface.

Do not combine a narrow test selection with a project-wide coverage target
unless repository evidence proves the command is satisfiable without testing
unrelated modules. Before presenting the task set for approval, check each
specified command for coherent test and coverage scope.

### 10. Apply task-size discipline

Target per task specification:

-   approximately 1,500 tokens or less.

This is a soft limit.

If a task substantially exceeds the target:

1.  check for multiple implementation outcomes;
2.  remove duplicated upstream documentation;
3.  replace copied design content with focused references;
4.  split only when the resulting tasks remain cohesive.

Task files should contain execution instructions, not duplicate the
TECHSPEC.

### 11. Create the task set

Follow convention over discovery.

For `SINGLE` delivery, use by default:

`tasks/`

For `WAVES`, use by default:

`tasks/<wave-id>-<short-name>/`

Inside the scope directory create:

-   `TASKS.md` --- ordered task index;
-   `TASK-001.md`;
-   `TASK-002.md`;
-   and so on.

Use zero-padded sequential identifiers within the current scope.

Do not create task files for future Waves.

If the repository already defines an explicit task convention, follow
it.

### 12. Validate task coverage

Before completion, verify that:

-   every implementation-relevant TECHSPEC decision has a task
    destination;
-   every task maps back to the approved TECHSPEC;
-   dependencies are coherent;
-   no task silently changes scope;
-   no implementation requirement was lost between TECHSPEC and tasks.

### 13. Perform the self-check

Review the complete task set before presenting it for human approval.

Do not execute any task automatically.

## Rules

### MUST

-   decompose exactly one approved TECHSPEC at a time;
-   preserve approved technical design;
-   preserve delivery boundaries;
-   give every task one primary implementation objective;
-   make task dependencies explicit;
-   include acceptance criteria;
-   include validation expectations;
-   include a bounded Context Manifest;
-   optimize for low Context Surface;
-   maintain traceability from TECHSPEC to tasks;
-   keep implementation and directly related tests together when that
    creates a more cohesive outcome;
-   stop after producing an approval-ready task set.

### MUST NOT

-   change the PRD;
-   change the Delivery Plan;
-   redesign the TECHSPEC;
-   create tasks for future Waves;
-   implement production code;
-   perform code review;
-   create one task per file by default;
-   create artificial microtasks for trivial changes;
-   copy large TECHSPEC sections into task files;
-   require the full PRD or full repository as default task context;
-   automatically invoke `execute-task`;
-   claim human approval that was not explicitly provided.

### SHOULD

-   prefer a small number of cohesive tasks over many fragmented tasks;
-   prefer tasks that produce reviewable outcomes;
-   minimize dependency chains;
-   reference exact TECHSPEC sections;
-   keep Required Context smaller than Optional Context;
-   make validation executable by the implementation/review agent;
-   use repository-native terminology and paths;
-   keep task files understandable without chat history.

## Context Management

Read first:

-   approved current-scope TECHSPEC.

Read only when needed:

-   relevant PRD requirement sections;
-   selected Delivery Plan section;
-   `AGENTS.md`;
-   architecture sections referenced by the TECHSPEC;
-   source files needed to establish realistic task boundaries;
-   relevant tests;
-   existing task files when updating the task set.

Do not load by default:

-   unrelated PRD sections;
-   future-Wave documentation;
-   all architecture documentation;
-   all source files;
-   all tests;
-   review history;
-   repository history.

Stop repository inspection when task boundaries and execution context
can be defined safely.

## Output

Create one task set for the selected delivery scope.

Default paths:

For `SINGLE`:

``` text
tasks/
├── TASKS.md
├── TASK-001.md
├── TASK-002.md
└── ...
```

For `WAVES`:

``` text
tasks/<wave-id>-<short-name>/
├── TASKS.md
├── TASK-001.md
├── TASK-002.md
└── ...
```

### TASKS.md

The index should contain:

``` markdown
# Tasks — <Scope Name>

## Scope

## Execution Order

| Task | Title | Depends On | Status |
|------|-------|------------|--------|
| TASK-001 | ... | — | PENDING |
| TASK-002 | ... | TASK-001 | PENDING |

## Coverage

- <TECHSPEC section / requirement> → <task(s)>

## Execution Notes
```

Initial task status:

`PENDING`

### TASK-XXX.md

Use the following structure:

``` markdown
# TASK-XXX — <Title>

## Objective

## Scope

## Context

### Required

### Optional

## Requirements

## Constraints

## Acceptance Criteria

## Validation

## Dependencies

## Out of Scope
```

Omit optional sections that add no value.

A task must not require chat history to be executed.

## Self-Check

Before completing, verify:

-   [ ] exactly one approved TECHSPEC was decomposed;
-   [ ] all implementation-relevant TECHSPEC content has task coverage;
-   [ ] every task maps to the TECHSPEC;
-   [ ] tasks have one primary objective;
-   [ ] dependencies are explicit and minimal;
-   [ ] acceptance criteria are observable;
-   [ ] validation expectations are actionable;
-   [ ] targeted test commands and project-wide coverage gates have coherent,
      distinct scopes;
-   [ ] Required Context contains only necessary references;
-   [ ] documentation references preferably stay within the soft target
    of 3;
-   [ ] primary source files/components preferably stay within the soft
    target of 5;
-   [ ] each task is preferably within approximately 1,500 tokens;
-   [ ] excessive Context Surface was analyzed rather than ignored;
-   [ ] no future-Wave tasks were created;
-   [ ] no approved design was silently changed;
-   [ ] no production code was implemented;
-   [ ] task files can be executed without chat history;
-   [ ] no downstream workflow stage was started automatically.

## Completion

When the task set is ready for review, return:

`AWAITING_HUMAN_APPROVAL`

Provide a concise summary containing:

-   number of tasks created;
-   intended execution order;
-   important dependencies;
-   TECHSPEC coverage;
-   any task with elevated Context Surface;
-   unresolved decomposition concerns.

Do not invoke or simulate human approval.

After explicit human approval, this skill is complete. Individual tasks
may then be executed separately using `execute-task`.

## Escalation

Return `BLOCKED` when:

-   the current TECHSPEC cannot be located;
-   TECHSPEC approval cannot be established;
-   the selected delivery scope is ambiguous;
-   repository context required to define executable tasks is
    unavailable.

Return `SPEC_CHANGE_REQUIRED` when:

-   the approved TECHSPEC contains contradictory implementation
    decisions;
-   the TECHSPEC lacks a critical decision required for safe task
    decomposition;
-   task decomposition reveals that the approved scope contains
    incompatible implementation boundaries;
-   creating executable tasks would require changing approved technical
    design.

When escalating:

1.  identify the exact TECHSPEC section or decision involved;
2.  explain why task decomposition cannot safely resolve it;
3.  identify the minimum upstream decision required;
4.  do not silently redesign the specification.

Do not create speculative tasks to work around an unresolved
specification.
