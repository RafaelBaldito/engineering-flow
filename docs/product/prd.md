# Product Requirements Document - Engineering Flow

**Status:** Approved

**Authoritative source:** `docs/product/vision.md`

**Product version covered:** V1 (MVP)

## 1. Overview

Engineering Flow is an agent-agnostic software-engineering workflow orchestration engine. It takes a feature request through controlled requirements, specification, planning, implementation, testing, review/fix, and Git delivery stages to produce a review-ready Pull Request (PR).

Engineering Flow is the workflow **control plane**. The selected coding-agent provider is the engineering-work **execution plane**. The product must automate operational orchestration while retaining explicit human decision points.

**North star:** "Describe the feature. Review the Pull Request."

## 2. Problem and Opportunity

Coding agents can perform sophisticated engineering work, but a developer still commonly acts as the workflow engine: selecting the next stage, transferring context and review findings, restarting reviews, managing retries, tracking state, and performing Git operations. This repetitive orchestration prevents an otherwise capable agent workflow from being autonomous.

Engineering Flow addresses this by controlling the lifecycle and policies around coding-agent work, so the developer primarily defines the desired feature, approves planned engineering artifacts where required, and reviews the resulting PR.

## 3. Goals

- Automate the operational orchestration required to move a feature from input to a review-ready PR.
- Provide a deterministic, observable, resumable workflow with controlled state transitions.
- Keep humans in control through configurable approval gates.
- Automate bounded implementation, test, independent review, and fix cycles after planning is approved.
- Deliver V1 through a high-quality Codex integration without making Codex part of the core product identity.
- Preserve workflow evidence and lifecycle history for auditability and recovery.

## 4. Non-Goals

Engineering Flow is not:

- a coding agent, an LLM wrapper, or a replacement for any coding-agent provider;
- an autonomous merge system; merge must remain human-gated in V1;
- a V1 multi-provider workflow, provider-routing, or provider-fallback product;
- a dashboard, cloud service, distributed-worker system, message-broker system, or multi-user platform;
- a system for complex parallel task execution, semantic long-term memory, sophisticated cost optimization, or a skills marketplace.

## 5. Users and Actors

### Primary user: Developer / workflow owner

Starts a workflow from a feature request, supplies required approvals or rejections, monitors progress, intervenes when required, and reviews the final PR.

### Engineering roles coordinated by the product

- **PRD role:** turns feature input into product requirements.
- **Architect role:** produces the technical specification after PRD approval.
- **Planner role:** decomposes an approved specification into executable tasks.
- **Developer role:** implements tasks and remediates review findings.
- **Reviewer role:** independently validates work against the task, acceptance criteria, technical specification, tests, and repository conventions.

Provider, role, skill, session, and execution are distinct concepts. A skill is reusable process knowledge, not automatically an independent agent.

## 6. V1 Scope

### In scope

- A Python, command-line product for orchestrating a target repository's engineering workflow.
- Feature input through PRD generation, TECHSPEC generation, task decomposition, sequential task execution, testing, review/fix cycles, Git commit and push, and PR creation.
- Configurable approval gates, review-cycle limit, execution-retry policy, and other permitted workflow policies.
- Explicit workflow state, persisted workflow history, interruption recovery, and resume.
- A Codex provider integration as the only V1 provider.
- Independent review, structured review outcomes when supported, structured logging, workflow artifacts, and lifecycle observability.
- Safety controls for repository, provider, execution, and secret handling.

### Out of scope

- Claude, Devin, or any other provider integration.
- Provider fallback, capability-based provider routing, and heterogeneous per-role provider execution.
- Complex or parallel execution of independent tasks.
- Web dashboard, cloud deployment, distributed workers, message brokers, multi-user collaboration, long-term semantic memory, advanced cost optimization, or skills marketplace.

## 7. Functional Requirements

### Workflow orchestration

- **FR-001:** The product must accept a feature request and coordinate the lifecycle: PRD; PRD approval; TECHSPEC; TECHSPEC approval; task plan; task-plan approval; sequential task execution; testing; review/fix cycles; final validation; commit; push; and PR creation.
- **FR-002:** The product must own workflow progression and state transitions. Providers may perform engineering work but must not arbitrarily advance the workflow.
- **FR-003:** The product must represent workflow lifecycle state explicitly, including progress through planning and task stages, completion, cancellation, failure, and a state requiring human attention.
- **FR-004:** The product must manage the roles required by the V1 lifecycle: PRD, Architect, Planner, Developer, and independent Reviewer.
- **FR-005:** The product must provide each role the context needed for its responsibility and must avoid indiscriminately sending the complete workflow history to every role.

### Approval and intervention

- **FR-006:** The product must support approval policies of required, automatic, and conditional at applicable workflow stages.
- **FR-007:** In the initial V1 policy, PRD, TECHSPEC, and task-plan approval must require human approval before the workflow proceeds; implementation and the review/fix loop may proceed automatically after plan approval.
- **FR-008:** The product must allow the workflow owner to approve or reject approval requests and must record the resulting decision.
- **FR-009:** The product must require human intervention when the configured maximum review/fix cycles is reached. A maximum review-cycle limit is mandatory.
- **FR-010:** Merge must remain human-gated and outside autonomous V1 completion.

### Task execution and review

- **FR-011:** The product must execute approved tasks sequentially in V1.
- **FR-012:** For each task, the product must coordinate implementation, required tests, independent review, and remediation of failed review findings until the task passes or intervention is required.
- **FR-013:** The Developer role should retain useful context across implementation and subsequent fix cycles for the same task.
- **FR-014:** The Reviewer role must use an independent session whenever practical and must not be treated as self-review by the Developer role.
- **FR-015:** A task may be marked complete only when implementation is complete, required tests pass, review passes, and there are no blocking review findings.
- **FR-016:** The product must consume a review pass/fail result without requiring workflow control to infer pass/fail from arbitrary prose. Review results must be structured when the provider supports structured results.

### Provider support

- **FR-017:** V1 must support Codex as its sole coding-agent provider.
- **FR-018:** The product must treat Codex as a provider integration, not as the core workflow domain or product identity.
- **FR-019:** The product must maintain provider-neutral boundaries for workflow interaction, sessions, executions, events, and applicable capabilities so future providers can be added without redesigning the workflow.
- **FR-020:** The product must preserve provider-specific behavior that cannot be usefully normalized instead of forcing a lowest-common-denominator experience.
- **FR-021:** The product must validate that the selected provider has the permissions and capabilities required by an execution before allowing that execution to proceed, to the extent supported in V1.

### Persistence, recovery, and artifacts

- **FR-022:** The product must assign each workflow a unique identifier and persist enough state to determine the workflow's current stage, task, approvals, selected provider, relevant sessions, review/retry progress, errors, Git state, and PR state.
- **FR-023:** The product must support recovery from interruption: a workflow can be started, interrupted, restarted, and resumed without losing its controlled lifecycle state.
- **FR-024:** The product must preserve the feature input, generated planning artifacts, task definitions, review outputs, and workflow record for each workflow.
- **FR-025:** The product must protect external and lifecycle operations against accidental duplication when resuming or retrying, including approvals, task and workflow completion, commits, pushes, and PR creation.

### Git and PR delivery

- **FR-026:** The product, rather than an agent acting freely, must control the Git lifecycle according to configured policies.
- **FR-027:** After all required tasks, tests, reviews, and final validation have passed, the product must create a commit, push the branch, and create a PR according to approved workflow policy.
- **FR-028:** A completed V1 workflow must result in a review-ready PR that summarizes requirements, technical approach, implemented tasks, changed files, tests, review cycles and resolved findings, known limitations, and human-review notes when available.
- **FR-029:** A workflow may be marked complete only after required approvals, task completion, required test and review passes, valid Git state, branch push, and PR creation. Merge is excluded.

### Operations and user interaction

- **FR-030:** The V1 command-line interface must enable initialization, workflow run, status inspection, resume, approval, rejection, and workflow-log access.
- **FR-031:** The product must expose enough workflow progress and event history for a user to understand what occurred during autonomous operation, including stages, task outcomes, agent work, test activity, review/fix cycles, approvals, and Git/PR lifecycle outcomes.
- **FR-032:** The product must classify failures sufficiently to distinguish agent, provider, tool, test, review, Git, authentication, human-rejection, and workflow failures, and apply the appropriate configured response (for example retry, fix, pause, return to an earlier stage, or human intervention).

## 8. Non-Functional Requirements

- **NFR-001 - Determinism and control:** Workflow progression must be policy-controlled and auditable; state transitions must not depend on agents making uncontrolled lifecycle decisions.
- **NFR-002 - Resilience:** Interrupted workflows must be recoverable and resumable without duplicate lifecycle side effects.
- **NFR-003 - Observability:** The system must provide structured logs and provider-neutral workflow events sufficient to reconstruct workflow progress and measure outcomes.
- **NFR-004 - Auditability:** Persisted workflow state and artifacts must support examination of approvals, executions, reviews, failures, retries, Git activity, and PR delivery.
- **NFR-005 - Context discipline:** Context supplied to each role must be relevant to that role's responsibility, limiting unnecessary context transfer.
- **NFR-006 - Safety:** Autonomous operation must be bounded by configurable review/retry limits and protective repository, provider, workspace, command, secret, and logging controls.

## 9. Constraints and Product Principles

- **CON-001:** V1 is a Python CLI product.
- **CON-002:** V1 implements only Codex, while the product's core domain remains provider-neutral and able to accommodate future provider adapters.
- **CON-003:** The selected agent owns engineering reasoning and engineering execution; Engineering Flow owns workflow, state, policies, approvals, observability, auditability, and Git/PR lifecycle control.
- **CON-004:** V1 task execution is sequential.
- **CON-005:** Provider fallback, intelligent routing, and multi-provider workflows are excluded from V1.
- **CON-006:** Review must be independent whenever practical; reviewer access should be read-only.
- **CON-007:** The product must enforce operational safeguards, including workspace boundaries, protected-branch handling, prohibited destructive commands, timeout and retry limits, secret protection, log sanitization, explicit repository validation, and disabled-by-default merge automation.

## 10. Primary User and System Flow

```text
Feature request
  -> PRD -> human approval
  -> TECHSPEC -> human approval
  -> task plan -> human approval
  -> sequential implementation -> tests -> independent review
       -> review failure: fix -> tests -> review (within configured limit)
  -> final validation -> commit -> push -> review-ready PR
  -> human PR review / merge decision
```

If a review limit is exceeded or an unrecoverable/approval-blocking condition occurs, the workflow must pause in a human-attention state rather than continuing autonomously. An interruption may be resumed from persisted state once the blocking condition is resolved.

## 11. Acceptance Criteria

- **AC-001:** Given a feature request, a workflow owner can progress through PRD, TECHSPEC, and task-plan stages, and each stage waits for the required approval before the next stage starts.
- **AC-002:** After task-plan approval, the system processes tasks one at a time and, for each task, runs implementation, required tests, and independent review.
- **AC-003:** When review fails, the system supplies the findings for remediation and repeats test and review steps; when the configured cycle limit is reached, it stops for human attention.
- **AC-004:** A task is completed only when its required tests and review pass and it has no blocking findings.
- **AC-005:** A process interruption followed by restart and resume continues the identified workflow from persisted progress and does not duplicate completed commits, pushes, PRs, approvals, or completion records.
- **AC-006:** A user can inspect workflow status and logs sufficient to identify the current/previous stage, task results, approvals, failures, retries, review cycles, and Git/PR outcomes.
- **AC-007:** A successful workflow produces a pushed branch and a review-ready PR containing the required delivery summary; it does not merge automatically.
- **AC-008:** The MVP's validation project demonstrates the complete lifecycle with sufficient complexity to exercise API development, persistence, business rules, tests, multiple tasks, architecture decisions, review/fix cycles, Git operations, and PR creation.

## 12. Success Measures

The primary MVP validation is whether Engineering Flow can produce a review-ready PR from a feature without the developer manually orchestrating implementation, review, and fix cycles.

The product must enable measurement of workflow duration; duration by stage and task; review cycles; first-pass review rate; agent executions; retries; failures; human interventions; tests run; files changed; provider usage; model and reasoning configuration. The key product metric is **human touches per workflow**, with V1 aiming to concentrate required interactions around PRD, TECHSPEC, and task-plan approvals plus final PR review.

## 13. Risks and Product-Level Dependencies

- V1 depends on a functional Codex integration with the permissions and capabilities needed for repository work, tests, session handling where supported, and controlled execution.
- Autonomous Git and PR delivery depend on validated repository state, branch protections, and authenticated repository access.
- Providers differ in execution, session, capability, sandbox, event, permission, and API models; the V1 experience must not assume identical behavior from future providers.
- Review quality and incomplete remediation can prevent workflow completion; bounded cycles and human intervention are required safeguards.
- A realistic, new validation project is required because the current MBA project is too close to completion to serve as primary MVP validation.

## 14. Assumptions

- The workflow owner has authority to approve/reject planning artifacts and review the final PR.
- The target repository can be validated before autonomous work begins and offers the Git/hosting credentials required for approved delivery actions.
- Required engineering skills and repository conventions can be made available to the selected provider.
- Exact provider contracts, storage strategy, configuration schema, command syntax, state representation, event payloads, and quality-gate mechanics will be defined in the TECHSPEC; they are not fixed by this PRD.

## 15. Open Questions

- Which approval policy settings beyond the V1 initial policy must be configurable in the MVP, and what are their defaults?
- Which exact quality gates constitute final validation beyond passing required task tests and reviews?
- What repository-hosting systems, other than the PR capability assumed by the vision, are in scope for the first release?
- What recovery and retry policies are appropriate for each failure class, and which require a human decision before retry?
- What minimum Codex capabilities and permissions must be verified before a workflow can begin?

## 16. Requirement Traceability

| Source vision area | PRD coverage |
| --- | --- |
| Product definition, problem, hypothesis, control/execution separation | Overview; Problem; Goals; CON-003 |
| Provider strategy, roles, sessions, context | FR-004 through FR-005; FR-013 through FR-021; CON-002, CON-006 |
| Workflow, approvals, review/fix, state | FR-001 through FR-016; AC-001 through AC-004 |
| Persistence, Git/PR lifecycle, idempotency | FR-022 through FR-029; AC-005, AC-007 |
| CLI, observability, artifacts, failure handling | FR-030 through FR-032; NFR-002 through NFR-004; AC-006 |
| Safety guardrails | NFR-006; CON-007 |
| MVP boundaries, validation, metrics, future direction | Scope; Non-Goals; Success Measures; AC-008 |
