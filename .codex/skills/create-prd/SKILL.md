---
description: |
  Create or update a Product Requirements Document from a project brief,
  assignment, business request, or user-provided requirements. Use
  during product planning before delivery planning, architecture,
  technical design, task creation, or implementation. Do not use this
  skill to make detailed technical decisions, create implementation
  tasks, or write production code.
name: create-prd
---

# Create PRD

## Purpose

Transform the available project requirements into a clear, scoped,
traceable Product Requirements Document (PRD) that defines what must be
built and why.

The PRD must reduce product ambiguity without prematurely deciding how
the solution will be implemented.

## When to Use

Use this skill when:

-   a new project, feature, challenge, or assignment needs a formal
    product specification;
-   informal requirements need to be consolidated into an authoritative
    PRD;
-   an existing PRD requires an explicitly requested product-level
    update;
-   requirements must be clarified before delivery planning or technical
    design.

Do not use this skill when:

-   the request is primarily about architecture or implementation
    design;
-   an approved PRD already exists and the next activity is delivery
    planning;
-   the request is to create implementation tasks;
-   the request is to implement or review code;
-   a delivery-stage agent discovers a specification conflict without
    human authorization to change the PRD.

## Inputs

### Required

At least one authoritative source describing the requested product or
change, such as:

-   project brief;
-   assignment statement;
-   business requirement;
-   user-provided requirements;
-   explicitly approved change request.

### Optional

Load only when it materially helps product-level understanding:

-   existing PRD;
-   relevant repository README or project overview;
-   externally imposed constraints;
-   existing product documentation;
-   repository structure when needed to distinguish existing behavior
    from requested behavior.

Technical implementation artifacts are not product authority unless the
user explicitly identifies them as requirement sources.

## Authoritative Sources

Use the following precedence unless the user explicitly establishes a
different authority:

1.  current explicit user instructions;
2.  authoritative project brief, assignment, or approved requirement
    source;
3.  previously approved PRD;
4.  explicitly approved product change requests;
5.  supporting product documentation;
6.  existing implementation and technical documentation as evidence of
    current state only.

Lower-priority sources must not silently override higher-priority
requirements.

When sources conflict:

1.  identify the conflicting statements;
2.  determine whether the conflict can be resolved from a
    higher-authority source;
3.  if it cannot, record it as an open question or blocking ambiguity;
4.  do not invent a requirement to resolve the conflict.

Existing code is evidence of what currently exists, not proof of what
the product is required to do.

## Preconditions

Before producing an approval-ready PRD:

-   [ ] at least one authoritative requirement source is available;
-   [ ] the intended project or feature boundary can be identified;
-   [ ] critical ambiguities have either been resolved or explicitly
    recorded.

If there is not enough information to establish the product objective or
meaningful scope, stop and report `BLOCKED` with the missing
information.

Do not block for minor uncertainties that can safely remain as explicit
open questions.

## Workflow

### 1. Inspect the requirement sources

Read the authoritative inputs before drafting.

Extract:

-   problem or motivation;
-   desired outcomes;
-   actors or users when relevant;
-   explicit functional requirements;
-   explicit non-functional requirements;
-   constraints;
-   required deliverables;
-   externally imposed technologies or interfaces only when they are
    actual constraints;
-   acceptance expectations;
-   exclusions;
-   ambiguities and unanswered questions.

Distinguish explicitly stated requirements from reasonable
interpretations.

### 2. Establish product scope

Define:

-   what the product or change is intended to accomplish;
-   what is in scope;
-   what is explicitly out of scope;
-   which behaviors are required;
-   which constraints are externally imposed.

Do not turn implementation preferences into product requirements unless
they are mandated by an authoritative source.

### 3. Normalize requirements

Rewrite requirements so they are:

-   clear;
-   testable where practical;
-   non-duplicative;
-   implementation-neutral unless implementation is constrained;
-   individually traceable.

Use stable identifiers when the project has enough requirements to
benefit from traceability.

Recommended prefixes:

-   `FR-###` for functional requirements;
-   `NFR-###` for non-functional requirements;
-   `CON-###` for constraints.

Do not create identifiers merely to add ceremony to a trivial project.

### 4. Separate requirements from assumptions

Do not silently fill gaps.

When an interpretation is necessary but not authoritative, classify it
as one of:

-   assumption;
-   open question;
-   proposed clarification.

Critical assumptions that materially affect scope must be surfaced for
human review.

### 5. Define acceptance expectations

For important requirements, define observable acceptance criteria or
expected outcomes without prescribing implementation.

Acceptance criteria should describe externally verifiable behavior
whenever possible.

Avoid technical acceptance criteria that belong in a TECHSPEC or task
unless the technology itself is an explicit product constraint.

### 6. Check product boundaries

Verify that the PRD does not drift into:

-   detailed architecture;
-   class or module design;
-   database schema design;
-   implementation algorithms;
-   detailed API internals;
-   task decomposition;
-   code examples.

Technology names may appear when they are mandated constraints or
necessary context, but detailed technical design belongs downstream.

### 7. Evaluate document size and product decomposition

Target for the PRD:

-   preferably no more than approximately 5,000 tokens.

This is a soft limit.

If the PRD significantly exceeds the target:

1.  do not truncate required product information;
2.  evaluate whether multiple independent product domains or
    capabilities are being forced into one document;
3.  preserve a concise global product view;
4.  recommend focused supporting requirement documents when
    decomposition improves clarity;
5.  do not split solely to satisfy a numeric target.

Do not design delivery waves in this skill. Delivery decomposition
belongs to `plan-delivery`.

### 8. Produce the PRD

Create or update the repository's authoritative PRD location.

If the repository already defines a PRD path or documentation
convention, follow it.

Otherwise prefer:

`docs/PRD.md`

Use the output structure defined below.

### 9. Perform the self-check

Review the completed artifact against this skill before presenting it
for human approval.

Do not proceed to delivery planning automatically.

## Rules

### MUST

-   preserve the meaning of authoritative requirements;
-   make scope and non-goals explicit;
-   surface unresolved product ambiguity;
-   distinguish requirements from assumptions;
-   keep requirements implementation-neutral unless implementation is
    explicitly constrained;
-   preserve traceability when it provides meaningful value;
-   apply the Document Size Policy;
-   make the resulting PRD understandable without requiring the original
    planning conversation;
-   stop after producing an approval-ready PRD.

### MUST NOT

-   invent product requirements;
-   silently resolve material requirement conflicts;
-   design detailed architecture;
-   create a TECHSPEC;
-   create delivery waves;
-   create implementation tasks;
-   implement production code;
-   modify approved requirements merely to match existing code;
-   automatically continue to another workflow skill;
-   claim human approval that was not explicitly provided.

### SHOULD

-   use concise language;
-   favor observable behavior over vague statements;
-   consolidate duplicate requirements;
-   retain terminology used by authoritative sources when it improves
    traceability;
-   record uncertainty explicitly instead of hiding it;
-   avoid unnecessary process artifacts for small projects.

## Context Management

Read first:

-   the user-provided or authoritative requirement source;
-   an existing PRD when updating one.

Read only when needed:

-   `AGENTS.md` for repository-specific instructions;
-   repository overview or README;
-   supporting product documentation;
-   externally imposed constraint documentation.

Do not load by default:

-   Wave TECHSPECs;
-   unrelated architecture documents;
-   all task files;
-   review reports;
-   unrelated source code;
-   the complete repository history.

If existing implementation must be inspected to understand current
product behavior, inspect only the relevant area and treat it as
supporting evidence, not requirement authority.

## Output

Create or update the authoritative PRD.

Default path when the repository has no established convention:

`docs/PRD.md`

Recommended structure:

``` markdown
# Product Requirements Document

## 1. Overview

## 2. Problem / Context

## 3. Goals

## 4. Non-Goals

## 5. Actors / Users

## 6. Scope

### In Scope

### Out of Scope

## 7. Functional Requirements

## 8. Non-Functional Requirements

## 9. Constraints

## 10. User / System Flows

## 11. Acceptance Criteria

## 12. Risks and Product-Level Dependencies

## 13. Assumptions

## 14. Open Questions

## 15. Requirement Traceability
```

Adapt the structure to project size. Do not create empty or artificial
sections when they add no value.

The PRD must contain enough information for `plan-delivery` to assess
delivery complexity without requiring reconstruction of the original
conversation.

## Self-Check

Before completing, verify:

-   [ ] the problem and desired outcome are clear;
-   [ ] goals and non-goals are explicit;
-   [ ] in-scope and out-of-scope boundaries are understandable;
-   [ ] functional requirements are clear and non-duplicative;
-   [ ] relevant non-functional requirements are represented;
-   [ ] externally imposed constraints are distinguishable from design
    choices;
-   [ ] material assumptions are visible;
-   [ ] unresolved questions are visible;
-   [ ] acceptance expectations are observable where practical;
-   [ ] no detailed architecture was introduced unnecessarily;
-   [ ] no implementation tasks or production code were created;
-   [ ] requirement identifiers are used only when they add traceability
    value;
-   [ ] the PRD respects the Document Size Policy or any justified
    exception is explained;
-   [ ] the PRD can be understood without relying on chat history;
-   [ ] no downstream workflow stage was started automatically.

## Completion

When the PRD is ready for review, return:

`AWAITING_HUMAN_APPROVAL`

Provide a concise summary containing:

-   artifact created or updated;
-   major scope captured;
-   important assumptions;
-   unresolved open questions;
-   any justified document size exception.

Do not invoke or simulate human approval.

After explicit human approval, this skill is complete. The next workflow
stage may then be initiated separately.

## Escalation

Return `BLOCKED` when:

-   no authoritative requirement source is available;
-   the core objective cannot be determined;
-   contradictory authoritative requirements prevent a coherent product
    scope;
-   proceeding would require inventing a material requirement.

When blocked:

1.  state the exact ambiguity or missing information;
2.  cite or identify the conflicting requirement sources when available;
3.  ask only for information necessary to unblock product definition.

Do not use `SPEC_CHANGE_REQUIRED` while initially creating a PRD.

When updating an already approved PRD, if the requested change conflicts
with another approved product requirement and authority cannot be
resolved, stop and report `BLOCKED` rather than silently changing the
product contract.