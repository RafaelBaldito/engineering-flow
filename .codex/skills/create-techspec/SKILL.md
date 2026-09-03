---
description: |
  Create or update an implementation-ready technical specification for
  the currently approved delivery scope. Use after the PRD and delivery
  plan are approved, required architecture approval is complete, and the
  current SINGLE scope or Wave has been authorized for technical design. Do not
  use to redefine product requirements, plan future
  waves in detail, create implementation tasks, or write production
  code.
name: create-techspec
---

# Create TECHSPEC

## Purpose

Transform the currently approved delivery scope into a bounded,
implementation-ready technical specification.

The TECHSPEC defines how the selected scope should be implemented while
preserving approved product requirements and delivery boundaries.

Its goal is to remove enough technical ambiguity for task decomposition
and implementation without over-designing unrelated or future work.

## When to Use

Use this skill when:

-   the approved delivery mode is `SINGLE` and its implementation scope
    is ready for technical design;
-   the approved delivery mode is `WAVES` and one specific Wave has been
    selected for just-in-time technical design, its predecessor (when any) has
    authoritative Wave acceptance, and explicit persisted authorization to
    start that Wave exists;
-   an existing TECHSPEC requires an explicitly approved technical
    update;
-   task creation is blocked because the current delivery scope lacks
    sufficient technical definition.

Do not use this skill when:

-   the PRD is not approved;
-   the Delivery Plan is not approved;
-   the approved delivery plan requires an architecture overview that is absent
    or awaiting approval;
-   a later Wave lacks predecessor authoritative acceptance or explicit
    persisted start authorization;
-   no current delivery scope has been selected;
-   the request is to redesign product requirements;
-   the request is to detail future Waves;
-   the request is to create implementation tasks;
-   the request is to implement or review code.

## Inputs

### Required

-   approved PRD;
-   approved Delivery Plan;
-   approved current delivery scope:
    -   `SINGLE`, or
    -   one selected Wave.

### Optional

Load only when relevant to the selected scope:

-   approved Delivery Plan;
-   approved architecture overview when the Delivery Plan marks it `REQUIRED`;
-   authoritative predecessor Wave-review PASS and explicit persisted next-Wave
    authorization when designing a later Wave;
-   `AGENTS.md`;
-   existing global architecture documentation;
-   relevant ADRs;
-   repository README or overview;
-   relevant source files and tests;
-   infrastructure configuration;
-   dependency manifests;
-   externally imposed technical constraints;
-   an existing TECHSPEC when updating it.

## Authoritative Sources

Use the following precedence unless the user explicitly establishes
another authority:

1.  current explicit user instructions that are authorized to change
    technical design;
2.  approved PRD;
3.  approved Delivery Plan and selected delivery boundary;
4.  approved architecture decisions and ADRs;
5.  approved current-scope TECHSPEC when updating it;
6.  explicit repository constraints and conventions;
7.  existing implementation as evidence of current state.

A lower-priority source must not silently override a higher-priority
source.

Existing implementation is not automatically authoritative when it
conflicts with an approved specification.

When sources conflict:

1.  identify the conflicting sources;
2.  preserve higher-authority approved requirements and boundaries;
3.  determine whether the conflict is a technical decision that this
    skill is authorized to resolve;
4.  if resolution requires changing approved product or delivery scope,
    report `SPEC_CHANGE_REQUIRED`;
5.  never silently adapt approved specifications to match existing code.

## Preconditions

Before producing an approval-ready TECHSPEC:

-   [ ] an authoritative approved PRD exists;
-   [ ] the Delivery Plan is approved;
-   [ ] the plan-required architecture overview is approved, when applicable;
-   [ ] exactly one current delivery scope is selected;
-   [ ] for a later Wave, the predecessor has authoritative Wave-review `PASS`
      and explicit persisted authorization to start the selected Wave;
-   [ ] mandatory architecture decisions for the scope are available or
    can be safely defined within the current boundary.

If the selected scope cannot be identified, report `BLOCKED`.

If implementation-ready design requires changing approved product or
delivery scope, report `SPEC_CHANGE_REQUIRED`.

## Workflow

### 1. Establish the current technical boundary

Identify:

-   selected `SINGLE` scope or Wave;
-   product requirements assigned to it;
-   explicit exclusions;
-   prerequisites;
-   expected demonstrable outcome;
-   cross-cutting constraints that apply.

Do not absorb requirements assigned to future Waves.

### 2. Inspect only relevant repository context

Inspect enough of the existing repository to understand:

-   components affected by the current scope;
-   existing conventions and abstractions;
-   reusable code;
-   dependency and configuration patterns;
-   tests relevant to the affected behavior;
-   infrastructure boundaries.

Prefer targeted inspection over broad repository loading.

Do not redesign unrelated existing code merely because an alternative
design would be cleaner.

### 3. Resolve current-scope technical decisions

Define only the technical decisions necessary to implement the selected
scope.

Depending on the project, this may include:

-   components or modules;
-   responsibilities and boundaries;
-   data flow;
-   interfaces and contracts;
-   persistence behavior;
-   external integrations;
-   configuration;
-   error handling;
-   observability;
-   security considerations;
-   dependency usage;
-   migration or compatibility concerns.

Do not create sections merely because they appear in this list.

### 4. Preserve architecture consistency

When approved global architecture or ADRs exist:

-   conform to them;
-   reference the relevant decision instead of duplicating it;
-   introduce local design only where the current scope requires detail.

If the current scope exposes a need for a new global architectural
decision, make the issue explicit.

Do not silently establish a project-wide architecture rule inside a Wave
TECHSPEC when it should be approved globally.

### 5. Define interfaces and behavior precisely

Where implementation depends on a contract, specify enough detail to
avoid guesswork.

Examples include:

-   function or service responsibilities;
-   input/output shape;
-   storage expectations;
-   environment/configuration variables;
-   error behavior;
-   integration boundaries.

Use examples when they materially reduce ambiguity.

Examples are illustrative unless explicitly marked as normative.

Avoid large production-ready code blocks. The TECHSPEC defines design;
it does not implement the feature.

### 6. Define validation strategy

For each important technical behavior, describe how implementation can
be validated.

Consider when applicable:

-   unit tests;
-   integration tests;
-   end-to-end behavior;
-   import/build checks;
-   lint/type checks;
-   database or migration verification;
-   manual validation for externally observable behavior.

Tie validation expectations to requirements and technical risks.

Do not invent tooling that the repository does not use unless
introducing it is part of the approved technical design.

### 7. Identify risks and open technical questions

Record:

-   unresolved technical decisions;
-   dependency risks;
-   compatibility concerns;
-   performance or security risks;
-   assumptions that implementation must verify.

A critical unresolved decision that prevents safe task decomposition
should not be hidden inside the document.

If it can be resolved within the approved scope, resolve it.

If it requires product/delivery change, report `SPEC_CHANGE_REQUIRED`.

### 8. Evaluate Context Surface

The TECHSPEC must support bounded downstream execution.

Evaluate whether the selected scope would force individual
implementation tasks to inspect excessive context, such as:

-   many unrelated documentation sections;
-   a large number of primary source files;
-   several unrelated components;
-   substantial knowledge of future Waves;
-   multiple independent technical outcomes.

If Context Surface is excessive, first determine whether the TECHSPEC
can be organized into clearer internal sections.

If the delivery scope itself contains multiple independent delivery
boundaries, report the decomposition concern rather than silently
redefining the approved Delivery Plan.

### 9. Apply TECHSPEC size discipline

Target:

-   approximately 4,000 tokens or less.

This is a soft limit.

If the TECHSPEC becomes substantially larger:

1.  do not truncate required design information;
2.  check whether unrelated or future design has leaked into the scope;
3.  move large reusable examples or reference material to a dedicated
    reference artifact only when justified;
4.  determine whether the selected Wave or SINGLE scope is too broad;
5.  surface a decomposition concern when the scope itself is the cause.

Document length alone does not justify changing approved delivery
boundaries.

### 10. Produce the TECHSPEC

Follow convention over discovery.

If the repository defines an explicit technical-specification
convention, follow it.

Otherwise:

For `SINGLE` delivery use:

`docs/TECHSPEC.md`

For `WAVES` delivery use:

`docs/waves/<wave-id>-<short-name>/TECHSPEC.md`

Use the Wave identifier and short name from the approved Delivery Plan.
Do not invent a different naming scheme from task context.

### 11. Perform the self-check

Review the TECHSPEC against:

-   approved requirements;
-   selected delivery boundary;
-   relevant architecture decisions;
-   repository constraints;
-   this skill.

Do not create implementation tasks or code automatically.

## Rules

### MUST

-   remain inside the selected delivery scope;
-   preserve approved product requirements;
-   preserve approved delivery boundaries;
-   conform to approved global architecture decisions;
-   inspect existing implementation before designing changes that affect
    it;
-   define enough technical detail for downstream task decomposition;
-   make important contracts and error behavior explicit;
-   define validation expectations;
-   surface technical assumptions and unresolved risks;
-   consider downstream Context Surface;
-   distinguish normative decisions from illustrative examples;
-   stop after producing an approval-ready TECHSPEC.

### MUST NOT

-   change approved product requirements;
-   silently change the Delivery Plan;
-   design future Waves in detail;
-   create implementation tasks;
-   implement production code;
-   perform unrelated refactors;
-   create speculative abstractions for hypothetical future needs;
-   duplicate large sections of global architecture documentation;
-   treat existing code as higher authority than approved
    specifications;
-   automatically continue to another workflow skill;
-   claim human approval that was not explicitly provided.

### SHOULD

-   prefer existing project conventions and abstractions;
-   minimize unnecessary new dependencies;
-   prefer the simplest design that satisfies the approved scope;
-   use precise interfaces where ambiguity would affect implementation;
-   keep examples small and purpose-driven;
-   reference global decisions instead of duplicating them;
-   organize the document so downstream tasks can reference specific
    sections;
-   optimize for bounded implementation context.

## Context Management

Read first:

-   approved PRD sections relevant to the selected scope;
-   approved Delivery Plan section for the selected scope, when
    applicable;
-   current TECHSPEC when updating one.

Read only when needed:

-   `AGENTS.md`;
-   relevant architecture sections and ADRs;
-   repository README or overview;
-   source files directly affected by the scope;
-   adjacent source files needed to understand contracts;
-   relevant tests;
-   dependency manifests;
-   configuration and infrastructure files.

Do not load by default:

-   full documentation for unrelated Waves;
-   all task files;
-   all source files;
-   all tests;
-   review history;
-   repository history;
-   future-Wave TECHSPECs.

Stop repository inspection when enough evidence exists to design the
current scope safely.

## Output

Create or update exactly one authoritative TECHSPEC for the selected
delivery scope.

Default paths:

For `SINGLE`:

`docs/TECHSPEC.md`

For `WAVES`:

`docs/waves/<wave-id>-<short-name>/TECHSPEC.md`

Recommended structure:

``` markdown
# Technical Specification — <Scope Name>

## 1. Scope

## 2. Requirements Traceability

## 3. Current-State Context

## 4. Technical Design

## 5. Components and Responsibilities

## 6. Data Flow

## 7. Interfaces and Contracts

## 8. Data / Persistence

## 9. Configuration and Dependencies

## 10. Error Handling

## 11. Security and Operational Considerations

## 12. Validation Strategy

## 13. Risks and Technical Assumptions

## 14. Open Technical Questions

## 15. Implementation Boundaries
```

Adapt the structure to the selected scope. Omit irrelevant sections
rather than creating empty ceremony.

Structure the document so `create-tasks` can reference focused TECHSPEC
sections instead of requiring every task to load the entire document.

## Self-Check

Before completing, verify:

-   [ ] exactly one delivery scope is being specified;
-   [ ] all included requirements belong to that scope;
-   [ ] no future-Wave requirement was pulled into detailed design;
-   [ ] existing relevant implementation was inspected when applicable;
-   [ ] approved architecture decisions were preserved;
-   [ ] components and responsibilities are clear enough for task
    decomposition;
-   [ ] important interfaces and contracts are explicit;
-   [ ] error behavior is defined where relevant;
-   [ ] validation strategy covers important behavior and risks;
-   [ ] assumptions and open technical questions are visible;
-   [ ] examples are not being mistaken for production implementation;
-   [ ] no speculative architecture was added without need;
-   [ ] downstream Context Surface is reasonable;
-   [ ] the TECHSPEC respects the local size target or explains a
    justified exception;
-   [ ] no implementation tasks or production code were created;
-   [ ] the artifact can be understood without chat history;
-   [ ] no downstream workflow stage was started automatically.

## Completion

When the TECHSPEC is ready for review, return:

`AWAITING_HUMAN_APPROVAL`

Provide a concise summary containing:

-   scope specified;
-   major technical decisions;
-   affected components;
-   validation approach;
-   important risks or assumptions;
-   unresolved technical questions;
-   any Context Surface or decomposition concern.

Do not invoke or simulate human approval.

After explicit human approval, this skill is complete. `create-tasks` may then
be initiated separately for exactly this approved scope. Do not start task
execution, accept the Wave, or begin another Wave automatically.

## Escalation

Return `BLOCKED` when:

-   the selected delivery scope cannot be established;
-   required repository context is unavailable;
-   a mandatory external technical constraint cannot be determined;
-   a critical technical decision cannot be safely made with available
    evidence.

Return `SPEC_CHANGE_REQUIRED` when:

-   implementation-ready design requires changing an approved product
    requirement;
-   the selected delivery boundary cannot satisfy its assigned
    requirements without changing the approved Delivery Plan;
-   an approved architecture decision must be changed rather than
    locally implemented;
-   contradictory approved specifications prevent a coherent technical
    design.

When escalating:

1.  identify the exact conflict or missing decision;
2.  identify the affected requirement, delivery boundary, or
    architecture decision;
3.  explain why the TECHSPEC cannot safely resolve it locally;
4.  request only the decision necessary to continue.

Do not silently expand scope or rewrite upstream approved artifacts.
