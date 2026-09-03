---
description: |
  Create or update the delivery strategy for an approved Product
  Requirements Document. Use after product requirements have been
  explicitly approved and before detailed technical design. Decide
  whether delivery should use a single implementation scope or multiple
  incremental waves. Do not create detailed TECHSPECs, implementation
  tasks, or production code.
name: plan-delivery
---

# Plan Delivery

## Purpose

Transform an approved PRD into a clear delivery strategy that determines
how the product scope should be implemented incrementally.

The approved delivery plan is the authority for whether the project is handled as a single
delivery scope (`SINGLE`) or as multiple bounded delivery waves
(`WAVES`), their boundaries and dependencies, and whether a global architecture
overview is required. It keeps future technical design intentionally
lightweight.

Its primary goal is to reduce planning risk, context growth, and
premature technical specification.

## When to Use

Use this skill when:

-   `docs/PRD.md` or the repository's authoritative PRD has been
    explicitly approved;
-   a project needs to decide between a single implementation scope and
    incremental waves;
-   an approved delivery plan needs an explicitly requested
    product-scope-aligned update;
-   the next step after product definition is organizing delivery
    boundaries.

Do not use this skill when:

-   the PRD is still awaiting approval;
-   critical product scope is unresolved;
-   the request is to design detailed architecture;
-   the request is to create a TECHSPEC;
-   the request is to create implementation tasks;
-   the request is to implement or review code.

## Inputs

### Required

-   approved PRD.

### Optional

Load only when materially useful:

-   `AGENTS.md`;
-   repository overview or README;
-   existing high-level architecture documentation;
-   relevant repository structure;
-   externally imposed delivery or technical constraints;
-   an existing delivery plan when updating it.

## Authoritative Sources

Use the following precedence unless the user explicitly establishes
another authority:

1.  current explicit user instructions;
2.  approved PRD;
3.  approved product change requests;
4.  explicit repository constraints;
5.  approved architecture decisions that already exist;
6.  existing implementation as evidence of current state.

The delivery plan organizes approved scope. It must not redefine product
scope.

If delivery planning reveals a contradiction or missing product decision
that materially affects decomposition, do not silently resolve it.
Report the issue for human resolution.

## Preconditions

Before producing an approval-ready delivery plan:

-   [ ] an authoritative PRD exists;
-   [ ] the PRD has been explicitly approved;
-   [ ] product scope is sufficiently stable to organize delivery.

If the PRD is not approved, stop and report `BLOCKED`.

If delivery planning exposes a material product ambiguity that prevents
safe decomposition, stop and report `SPEC_CHANGE_REQUIRED`.

## Workflow

### 1. Inspect the approved product scope

Identify:

-   product goals;
-   functional capabilities;
-   non-functional requirements;
-   externally imposed constraints;
-   dependencies between capabilities;
-   acceptance expectations;
-   explicit non-goals.

Do not reinterpret or expand approved requirements.

### 2. Inspect relevant repository context

When an existing codebase is present, inspect only enough context to
understand:

-   major existing components;
-   integration boundaries;
-   infrastructure already provided;
-   implementation constraints that affect delivery sequencing.

Do not perform detailed architecture analysis at this stage.

### 3. Assess delivery complexity

Evaluate the product semantically rather than by counting requirements
or lines.

Consider:

-   number of distinct capabilities;
-   dependency depth;
-   integration boundaries;
-   infrastructure prerequisites;
-   uncertainty;
-   cross-cutting concerns;
-   amount of context likely required by implementation agents;
-   whether meaningful intermediate outcomes can be demonstrated
    independently.

Do not use arbitrary numeric requirement counts as the primary
decomposition rule.

### 4. Select the delivery mode

Choose exactly one:

`SINGLE`

Use when the product can reasonably be specified and implemented as one
bounded scope without creating excessive planning or execution context.

`WAVES`

Use when incremental delivery materially improves one or more of:

-   context efficiency;
-   implementation clarity;
-   validation;
-   risk isolation;
-   dependency sequencing;
-   ability to learn from earlier implementation before specifying later
    work.

Document the rationale for the selected mode.

### 5. Define delivery boundaries

For `SINGLE`:

-   define the complete delivery boundary;
-   identify the expected demonstrable outcome;
-   identify major prerequisites and constraints;
-   do not create artificial waves.

For `WAVES`:

-   define a small ordered set of meaningful delivery waves;
-   give each wave a clear objective and demonstrable outcome;
-   identify dependencies between waves;
-   map approved product requirements to the wave responsible for
    delivering them;
-   keep future waves at outline level.

Prefer vertical slices that produce testable or demonstrable behavior
when technically feasible.

Avoid waves that merely mirror technical layers such as "database",
"backend", and "frontend" unless the project genuinely requires that
sequencing.

### 6. Evaluate wave quality

Each proposed wave should:

-   have a coherent delivery objective;
-   produce a meaningful testable or demonstrable outcome;
-   have bounded context;
-   avoid unnecessary dependence on future-wave details;
-   be small enough for a focused TECHSPEC;
-   preserve traceability to approved requirements.

If a proposed wave requires detailed knowledge of most future waves to
be understood, reconsider the boundaries.

### 7. Define architecture planning needs

Determine whether the project needs a concise global architecture
overview before detailed implementation planning.

A global architecture overview is useful when multiple delivery scopes
share stable boundaries such as:

-   major components;
-   data stores;
-   external systems;
-   cross-cutting infrastructure;
-   security boundaries;
-   shared integration contracts.

Do not create the architecture document in this skill.

Record one of `REQUIRED` or `NOT REQUIRED` and the stable concerns it should
cover when required. Do not leave architecture applicability as a non-binding
recommendation.

For small `SINGLE` projects, a separate architecture overview may be
unnecessary.

### 8. Apply delivery-plan size discipline

Target:

-   approximately 3,000 tokens or less.

This is a soft limit.

If the plan becomes substantially larger:

1.  do not remove necessary delivery information merely to meet the
    target;
2.  check whether future waves are being specified in excessive detail;
3.  reduce future-wave content to objectives, boundaries, dependencies,
    and requirement mapping;
4.  move technical design downstream rather than expanding this
    artifact.

### 9. Produce the delivery plan

Follow convention over discovery.

If the repository already defines an explicit delivery-plan path, follow
it.

Otherwise use:

`docs/DELIVERY-PLAN.md`

Do not generate context-derived filenames when the standard path is
available.

### 10. Perform the self-check

Validate the delivery strategy against the approved PRD and this skill.

Do not create the architecture overview, TECHSPEC, tasks, or code
automatically.

## Rules

### MUST

-   use only approved product scope;
-   explicitly choose `SINGLE` or `WAVES`;
-   explain the delivery-mode decision;
-   preserve requirement traceability;
-   make delivery dependencies visible;
-   keep future technical design intentionally lightweight;
-   prefer demonstrable delivery outcomes;
-   consider implementation context size when defining boundaries;
-   stop after producing an approval-ready delivery plan.

### MUST NOT

-   change approved product requirements;
-   invent product scope;
-   create detailed architecture;
-   create detailed future-wave designs;
-   create TECHSPECs;
-   create implementation tasks;
-   implement production code;
-   decompose solely from arbitrary requirement counts or document
    length;
-   create waves merely to satisfy a process convention;
-   automatically continue to another workflow skill;
-   claim human approval that was not explicitly provided.

### SHOULD

-   prefer the simplest delivery structure that safely fits the project;
-   use `SINGLE` for genuinely bounded projects;
-   use `WAVES` when incremental planning reduces uncertainty or
    context;
-   prefer vertical slices over horizontal technical layers when
    feasible;
-   minimize dependencies between waves;
-   place foundational work inside the earliest wave that needs it
    rather than creating ceremony-only foundation waves;
-   keep the number of waves as small as reasonably possible.

## Context Management

Read first:

-   approved PRD.

Read only when needed:

-   `AGENTS.md`;
-   repository README or overview;
-   existing architecture overview;
-   relevant top-level repository structure;
-   explicit constraint documentation;
-   existing delivery plan when updating it.

Do not load by default:

-   detailed source files unrelated to delivery boundaries;
-   all existing tests;
-   task files;
-   review reports;
-   unrelated technical documentation;
-   repository history.

Repository inspection should stop once enough information exists to make
a sound delivery-boundary decision.

## Output

Create or update the authoritative delivery plan.

Default path:

`docs/DELIVERY-PLAN.md`

Recommended structure:

``` markdown
# Delivery Plan

## 1. Delivery Summary

## 2. Delivery Mode

SINGLE | WAVES

## 3. Decision Rationale

## 4. Requirement Coverage

## 5. Architecture Overview Applicability

REQUIRED | NOT REQUIRED

## 6. Delivery Scope

### For SINGLE

#### Objective
#### Included Requirements
#### Dependencies
#### Demonstrable Outcome

### For WAVES

#### Wave 1 — <Name>
- Objective
- Included Requirements
- Dependencies
- Demonstrable Outcome

#### Wave 2 — <Name>
...

## 7. Cross-Cutting Constraints

## 8. Delivery Risks and Dependencies

## 9. Open Delivery Questions
```

Adapt the structure to project size.

For `WAVES`, future-wave descriptions must remain outlines. Detailed
design belongs in each wave's just-in-time TECHSPEC.

The plan must make it possible to identify the next delivery scope
without loading the original planning conversation.

## Self-Check

Before completing, verify:

-   [ ] the PRD was explicitly approved;
-   [ ] `SINGLE` or `WAVES` was selected explicitly;
-   [ ] the selection rationale is understandable;
-   [ ] all approved requirements have a delivery destination;
-   [ ] no new product requirements were introduced;
-   [ ] delivery dependencies are visible;
-   [ ] each wave, when used, has a coherent demonstrable outcome;
-   [ ] future waves remain outline-level;
-   [ ] wave boundaries are not arbitrary technical-layer splits;
-   [ ] context efficiency was considered;
-   [ ] architecture-overview applicability was decided as `REQUIRED` or
      `NOT REQUIRED`;
-   [ ] no TECHSPEC or implementation task was created;
-   [ ] the plan respects the local document-size target or explains a
    justified exception;
-   [ ] the artifact can be understood without chat history;
-   [ ] no downstream workflow stage was started automatically.

## Completion

When the delivery plan is ready for review, return:

`AWAITING_HUMAN_APPROVAL`

Provide a concise summary containing:

-   selected delivery mode;
-   rationale;
-   delivery scopes or wave sequence;
-   architecture-overview recommendation;
-   important dependencies or risks;
-   unresolved delivery questions.

Do not invoke or simulate human approval.

After explicit human approval, this skill is complete. If the approved plan
marks the architecture overview `REQUIRED`, `create-architecture-overview` is
the next stage and its artifact requires approval before any TECHSPEC. If it is
`NOT REQUIRED`, the selected initial scope's TECHSPEC may be initiated
separately. For a later Wave, its TECHSPEC additionally requires predecessor
Wave PASS and exactly one valid active canonical
`WAVE-START-AUTHORIZATION.md`, as defined by the approved Delivery Plan.

## Escalation

Return `BLOCKED` when:

-   the authoritative PRD cannot be located;
-   PRD approval cannot be established;
-   mandatory repository context required for delivery planning is
    unavailable.

Return `SPEC_CHANGE_REQUIRED` when:

-   approved requirements materially contradict each other during
    decomposition;
-   a missing product decision prevents safe delivery boundaries;
-   delivery would require changing approved scope rather than merely
    sequencing it.

When escalating:

1.  identify the exact blocking or conflicting requirement;
2.  explain why delivery planning cannot safely resolve it;
3.  request only the decision needed to continue.

Do not silently modify the PRD or expand delivery scope.
