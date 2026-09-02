---
description: |
  Create a concise global architecture overview that defines stable cross-wave boundaries before wave-specific TECHSPECs are produced.
name: create-architecture-overview
---

# Create Architecture Overview

## Purpose

Create a concise, global architecture overview for the product before detailed wave-specific TECHSPECs are generated.

This artifact defines stable architectural boundaries that should remain consistent across multiple delivery waves.

It must establish the shared architecture contract for the system without becoming a substitute for a TECHSPEC.

---

## When to Use

Use this skill after:

1. The Product Vision exists.
2. The PRD has been approved.
3. The delivery plan has been defined.
4. Before the first detailed TECHSPEC is created.

This skill is especially appropriate when:

- multiple delivery waves share architectural concerns;
- the TECHSPEC would otherwise need to redefine global boundaries repeatedly;
- provider/runtime abstractions span multiple waves;
- persistence, workflow state, observability, Git, CLI, or safety concerns affect the entire product.

---

## Inputs

Use the following sources when available:

- `docs/product/vision.md`
- `docs/product/prd.md`
- the approved delivery plan produced by `plan-delivery`

Treat the approved PRD as the authoritative source for product scope.

Treat the delivery plan as the authoritative source for wave boundaries and dependency order.

Do not add product scope that is not supported by the approved PRD.

---

## Output

Create:

`docs/architecture/architecture-overview.md`

Create the directory if necessary.

---

## Primary Goal

Define the stable architectural boundaries shared across the product and across delivery waves.

The overview should answer:

- What are the major architectural responsibilities?
- Who owns workflow decisions?
- What boundaries exist between orchestration and execution?
- What abstractions must remain provider-neutral?
- How does state persist across executions?
- How are failures, retries, resume, and idempotency treated?
- How do CLI, artifacts, logs, Git, and PR operations interact with the core workflow?
- What safety boundaries must always hold?
- Which concerns belong globally versus inside wave-specific TECHSPECs?

---

## Required Architecture Areas

The architecture overview must cover the following areas when relevant to the approved product scope.

### 1. System Responsibility Boundaries

Define the major system responsibilities.

Clarify which component owns:

- workflow progression;
- approval gates;
- task lifecycle;
- quality gates;
- retries;
- review/fix cycles;
- persistence;
- external agent invocation;
- Git lifecycle;
- Pull Request creation.

Explicitly distinguish orchestration responsibilities from agent execution responsibilities.

---

### 2. Workflow Ownership and State Transitions

Define the global workflow model at a conceptual level.

Describe:

- workflow ownership;
- stage transitions;
- approval transitions;
- failure transitions;
- retry transitions;
- human intervention states;
- completion conditions.

The architecture overview may define state categories or a high-level state model.

Do not specify implementation-level state machine code.

---

### 3. Provider-Neutral Agent Boundary

Define the architectural boundary between the orchestration engine and external coding-agent runtimes.

The design must remain provider-neutral.

Cover the conceptual boundaries for:

- interaction;
- session;
- execution;
- events;
- capabilities.

Prefer provider-neutral terminology such as:

- AgentRuntime
- AgentSession
- AgentExecution
- AgentEvent
- AgentCapabilities

Do not make the core architecture dependent on a specific provider.

Provider-specific behavior must remain behind an adapter boundary.

---

### 4. Provider Adapter Boundary

Describe where provider-specific integrations live and what responsibilities belong there.

Clarify that provider adapters may translate between:

- orchestration requests;
- provider-native session APIs;
- provider-native events;
- provider-native approvals;
- provider-native execution results.

Do not specify detailed provider SDK calls unless they are necessary to explain a stable architectural boundary.

Detailed provider integration belongs in the relevant TECHSPEC.

---

### 5. Session and Execution Boundaries

Define the conceptual difference between:

- a persistent logical session;
- an individual execution or turn;
- workflow state;
- provider state.

Clarify where session continuity is desirable and where isolation is preferable.

For example, when applicable:

- implementation/fix work may preserve context;
- review execution should remain independently evaluable.

Keep this conceptual and cross-wave.

---

### 6. Persistence Boundary

Define what categories of state must survive process termination.

Consider:

- workflow identity;
- current stage;
- current task;
- approvals;
- provider/session identifiers;
- execution history;
- review cycles;
- retries;
- failures;
- Git state;
- Pull Request state.

Describe persistence responsibilities and ownership.

Do not prescribe detailed database schemas unless absolutely necessary for a stable cross-wave contract.

---

### 7. Idempotency and Resume Boundary

Define the global expectation that workflows must safely resume after interruption.

Identify operations where idempotency matters, such as:

- approval recording;
- task completion;
- commit creation;
- push;
- Pull Request creation;
- repeated workflow transitions.

Describe the architectural principle.

Detailed algorithms belong in TECHSPECs.

---

### 8. Event and Observability Boundary

Define the global event model at a conceptual level.

Events should be provider-neutral where possible.

Examples may include:

- workflow.started
- workflow.completed
- workflow.failed
- stage.started
- stage.completed
- approval.requested
- approval.completed
- agent.session.started
- agent.execution.started
- agent.execution.completed
- test.started
- test.completed
- review.completed
- git.commit.created
- git.push.completed
- pull_request.created

Define where logs, structured events, metrics, and tracing conceptually belong.

Do not design the full telemetry implementation.

---

### 9. CLI and User Interaction Boundary

Define the role of the CLI.

Clarify what kinds of operations the CLI may initiate or expose, such as:

- start workflow;
- inspect workflow status;
- approve;
- reject;
- resume;
- inspect logs;
- inspect artifacts.

The CLI should interact with orchestration services rather than contain workflow business logic.

---

### 10. Artifact Boundary

Define how workflow-generated artifacts conceptually relate to execution.

Examples may include:

- PRD;
- architecture overview;
- delivery plan;
- TECHSPEC;
- task definitions;
- reviews;
- logs;
- execution metadata.

Clarify which artifacts are authoritative inputs to later stages.

---

### 11. Git and Pull Request Boundary

Define the global Git ownership model.

Clarify which responsibilities belong to the orchestration layer versus the coding agent.

Prefer that the orchestration layer owns controlled operations such as:

- staging;
- commit;
- push;
- Pull Request creation.

Agents may propose commit messages or PR descriptions, but should not independently control repository lifecycle unless explicitly permitted.

---

### 12. Safety Boundary

Define cross-cutting safety constraints.

Consider:

- workspace boundaries;
- sandboxing;
- protected branches;
- approval policies;
- review/fix limits;
- retry limits;
- timeouts;
- secret protection;
- restricted destructive operations;
- no automatic merge unless explicitly in approved scope.

Safety rules must be stable across waves.

---

### 13. Failure Boundary

Define high-level failure categories where useful.

Examples:

- workflow failure;
- provider failure;
- agent execution failure;
- tool failure;
- test failure;
- review failure;
- Git failure;
- authentication failure;
- human rejection.

Describe ownership of recovery decisions.

Do not design detailed retry algorithms.

---

### 14. Cross-Wave Interfaces

Identify architectural contracts that future waves must respect.

This section should make explicit which boundaries are intentionally stable across waves.

Examples:

- orchestration-to-provider interface;
- persistence interface;
- event interface;
- Git integration interface;
- approval interface;
- workflow transition rules.

This is one of the most important outcomes of the document.

---

## Required Document Structure

Use a structure similar to:

# Architecture Overview

## 1. Purpose

## 2. Architectural Context

## 3. Core Architectural Principles

## 4. High-Level System Responsibilities

## 5. Workflow and State Ownership

## 6. Agent Runtime and Provider Boundaries

## 7. Session and Execution Model

## 8. Persistence, Resume, and Idempotency

## 9. Events, Logs, and Observability

## 10. CLI and Artifact Access

## 11. Git and Pull Request Integration

## 12. Safety and Failure Boundaries

## 13. Cross-Wave Architectural Contracts

## 14. Architecture Decisions Deferred to TECHSPECs

## 15. Summary

You may adapt section names slightly if doing so improves clarity.

---

## Explicit Non-Goals

This skill must NOT:

- create a TECHSPEC;
- design a delivery wave in detail;
- decompose coding tasks;
- define implementation tickets;
- create concrete class hierarchies without a strong reason;
- define complete database schemas;
- prescribe detailed algorithms;
- write production code;
- choose unnecessary libraries;
- over-specify provider-specific SDK usage;
- duplicate the PRD;
- change approved product scope.

---

## Global vs Wave-Specific Rule

Use this rule throughout the document:

If a decision must remain stable across multiple waves, it belongs in the architecture overview.

If a decision is needed only to implement one specific wave, it belongs in that wave's TECHSPEC.

When uncertain, prefer leaving implementation detail to the TECHSPEC.

---

## Architecture Quality Criteria

The final document should be:

- concise;
- cross-wave;
- implementation-aware but not implementation-detailed;
- provider-neutral at the core;
- explicit about ownership;
- explicit about boundaries;
- explicit about what is intentionally deferred;
- consistent with the PRD;
- consistent with the approved delivery plan.

A reader should be able to understand the system's stable architecture before reading any individual TECHSPEC.

---

## Validation Before Completion

Before finalizing, verify:

- The document does not introduce new product scope.
- The architecture is compatible with the approved PRD.
- The architecture respects the approved delivery plan.
- Provider-specific concepts do not leak into core domain boundaries.
- Global architectural contracts are explicit.
- Wave-specific implementation detail has been deferred.
- Persistence and resume expectations are clear.
- Git ownership is clear.
- Safety boundaries are clear.
- The document can serve as input to multiple TECHSPECs.

---

## Completion Response

After creating the document, report:

1. The output file path.
2. The major architectural boundaries defined.
3. Any important ambiguity found in the PRD or delivery plan.
4. Any architecture decision intentionally deferred to a wave-specific TECHSPEC.
5. Whether the architecture overview is ready to be used as input for `create-techspec`.

Do not proceed to create a TECHSPEC automatically.