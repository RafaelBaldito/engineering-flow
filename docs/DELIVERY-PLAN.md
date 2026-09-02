# Delivery Plan

## 1. Delivery Summary

Engineering Flow V1 (MVP) is a Python command-line control plane that takes a feature request through controlled planning, sequential engineering work, independent review and bounded remediation, then produces a review-ready pull request. It preserves human approval of the PRD, TECHSPEC, and task plan; autonomous merge remains excluded.

This plan organizes the approved MVP into three ordered, coherent waves. It does not add product scope or prescribe implementation design.

## 2. Delivery Mode

WAVES

## 3. Decision Rationale

Three waves are appropriate because the MVP has three dependent, independently testable outcomes: a persisted and human-gated planning workflow, an autonomous per-task engineering and review loop, and irreversible external Git/PR delivery.

Delivering this as one scope would require one TECHSPEC and implementation effort to hold workflow control, provider behavior, recovery/idempotency, independent review, and Git-hosting integration in context at once. Splitting it reduces architectural and integration risk without creating artificial technical-layer phases:

- Wave 1 establishes the workflow contract and proves the controlled planning path through an approved task plan.
- Wave 2 uses that approved plan to prove the central autonomous engineering loop, including bounded recovery and review/fix behavior.
- Wave 3 adds the externally visible delivery outcome only after the quality-gated task lifecycle is proven.

Each wave is a vertical user outcome and can be validated without depending on unimplemented future behavior. The dependency order also prevents Git/PR side effects from obscuring failures in the core orchestration lifecycle.

## 4. Requirement Coverage

| Approved requirement area | Delivery destination |
| --- | --- |
| Workflow initiation, controlled progression, lifecycle state, roles, relevant role context (FR-001–FR-005) | Waves 1–3: Wave 1 establishes planning progression and state; Wave 2 completes task-stage progression and role behavior; Wave 3 completes delivery-stage progression. |
| Approval and intervention (FR-006–FR-010) | Waves 1–2: Wave 1 delivers planning approvals and their record; Wave 2 adds review-cycle intervention. Merge remains excluded in every wave. |
| Sequential execution, tests, independent review, remediation, structured outcomes (FR-011–FR-016) | Wave 2 |
| Codex-only provider support with provider-neutral boundaries and capability validation (FR-017–FR-021) | Waves 1–2: Wave 1 establishes provider interaction for planning and execution eligibility; Wave 2 completes session, independent-review, and structured-review use. |
| Persisted workflow, artifacts, recovery, and duplicate-side-effect protection (FR-022–FR-025) | Waves 1–3: Wave 1 covers planning state, artifacts, approvals, and resume; Wave 2 covers task/review progress; Wave 3 completes Git/PR side-effect protection. |
| Controlled Git and PR delivery (FR-026–FR-029) | Wave 3 |
| CLI, observability, failure classification and configured response (FR-030–FR-032) | Waves 1–3: core CLI/status/log visibility begins in Wave 1; task/review outcomes in Wave 2; Git/PR outcomes and related failures in Wave 3. |
| NFR-001–NFR-006 and CON-001–CON-007 | All waves, applied to the lifecycle and integrations introduced by each wave. |
| AC-001 | Wave 1 |
| AC-002–AC-004 | Wave 2 |
| AC-005 | Waves 1–3, completed in Wave 3 |
| AC-006 | Waves 1–3, expanded as lifecycle coverage expands |
| AC-007 | Wave 3 |
| AC-008 | Wave 3, using the approved new validation project after the end-to-end lifecycle is available. |

## 5. Architecture Overview Need

Recommended.

Before Wave 1 is specified, create a concise global architecture overview covering stable cross-wave boundaries: workflow ownership and state transitions; provider-neutral interaction, session, execution, event, and capability boundaries; persistence and idempotency boundaries; CLI and artifact/log access; and Git/PR integration and safety boundaries. It should remain an overview, not a substitute for the selected wave's TECHSPEC.

## 6. Delivery Scopes

### Wave 1 — Controlled Planning Workflow

- **Objective:** Deliver a usable, persisted path from a feature request through PRD, TECHSPEC, and task-plan generation, with required human approvals controlling progression.
- **Included requirements:** Planning portions of FR-001–FR-008; planning-state and role-context portions of FR-002–FR-005; Codex-only, provider-neutral planning interaction and execution eligibility from FR-017–FR-021; planning persistence, artifacts, recovery, and duplicate protection from FR-022–FR-025; applicable CLI, status, logs, and failure handling from FR-030–FR-032; AC-001 and the planning portion of AC-005/AC-006.
- **Boundaries:** Ends when an approved task plan is stored and ready for sequential execution. It does not execute tasks, perform review/fix cycles, commit, push, or create a PR.
- **Dependencies:** Requires the recommended architecture overview and a usable Codex integration with the minimum permissions/capabilities for planning. Wave 2 depends on its approved task-plan artifact, lifecycle records, and resume behavior.
- **Expected outcome:** A workflow owner can initialize and run a workflow, inspect its progress and logs, approve or reject each planning artifact, interrupt and resume it, and obtain an approved task plan without uncontrolled stage advancement.
- **Validation criteria:** Demonstrate a feature request moving through PRD, TECHSPEC, and task-plan stages; verify each required approval blocks the next stage until recorded; restart and resume the identified workflow without duplicating planning side effects; and inspect CLI status/log evidence and preserved artifacts.

### Wave 2 — Autonomous Sequential Engineering Loop

- **Objective:** Execute an approved task plan one task at a time through implementation, required tests, independent review, and bounded remediation.
- **Included requirements:** FR-009 and review-cycle intervention; FR-011–FR-016; task-stage completion of FR-001–FR-005; task/review session and structured-result behavior from FR-017–FR-021; task/review persistence, recovery, artifacts, and duplicate protection from FR-022–FR-025; applicable CLI, observability, and failure handling from FR-030–FR-032; AC-002–AC-004 and the task/review portions of AC-005/AC-006.
- **Boundaries:** Starts only from Wave 1's approved task plan. Ends after all planned tasks have passed their required tests and independent review, or the workflow is safely in a human-attention state. It excludes final commit, push, and PR creation.
- **Dependencies:** Depends on Wave 1's controlled workflow state, approved task artifact, provider boundary, persistence, approval record, CLI visibility, and recovery behavior. Wave 3 depends on its verified task outcomes, review evidence, and final eligible workflow state.
- **Expected outcome:** After task-plan approval, Engineering Flow advances sequentially through the planned tasks, retains useful developer context within a task's fix cycle, records independent review results, and pauses for human attention instead of exceeding the configured review-cycle limit.
- **Validation criteria:** Demonstrate multiple tasks processed in sequence; for each, verify implementation, required tests, independent review, and no blocking findings before completion; demonstrate a review failure followed by remediation and re-review; demonstrate the mandatory cycle limit and human-attention state; and resume an interrupted task/review lifecycle without duplicating completed work or records.

### Wave 3 — Controlled Git and Review-Ready PR Delivery

- **Objective:** Complete a successful quality-gated workflow through final validation, controlled commit and push, and creation of a review-ready PR.
- **Included requirements:** FR-026–FR-029; Git/PR completion of FR-022–FR-025; Git/PR lifecycle visibility and failure handling in FR-030–FR-032; applicable safety constraints; AC-005–AC-008; and the remaining measurement evidence in the success measures.
- **Boundaries:** Starts only after Wave 2 has verified all required task, test, and review outcomes. It creates the configured commit, push, and PR and records the required summary. It never merges automatically and does not add provider, dashboard, parallelism, or cloud scope.
- **Dependencies:** Depends on Wave 2's final eligible state, test/review evidence, and persisted lifecycle history, plus validated repository state, branch policy, authenticated hosting access, and PR capability. Completion requires external Git and hosting operations to be protected against duplication on retry or resume.
- **Expected outcome:** A completed workflow produces one pushed branch and one review-ready PR with the required requirements, approach, task, change, test, review-cycle, limitation, and human-review information, while leaving merge to a human.
- **Validation criteria:** Using the approved new validation project, demonstrate the full lifecycle from feature request to PR; verify final validation gates commit/push/PR creation; verify the PR summary content and CLI/log evidence; verify restart/retry does not duplicate commits, pushes, PRs, approvals, or completion; and verify merge automation remains disabled.

## 7. Cross-Cutting Constraints

- The product remains a Python CLI and uses Codex as the sole V1 provider, while workflow-domain boundaries remain provider-neutral.
- Engineering Flow controls state, policies, approvals, observability, auditability, and Git/PR lifecycle; the provider performs engineering reasoning and execution only within that control.
- Every wave applies context discipline, structured lifecycle evidence, safety controls, bounded retries/timeouts, secret and log protection, workspace/repository validation, protected-branch handling, and prohibited destructive-command controls to the functionality it introduces.
- V1 stays sequential, single-user, local/CLI-oriented, and non-merging. All PRD non-goals remain outside these waves.

## 8. Delivery Risks and Dependencies

| Risk or dependency | Affected waves | Delivery treatment |
| --- | --- | --- |
| Codex permissions, session behavior, event support, and structured review capability | 1–2 | Validate minimum capabilities before executions and preserve provider-specific behavior that cannot be usefully normalized. |
| Controlled recovery and idempotency across interruptions/retries | 1–3 | Establish persisted lifecycle evidence in Wave 1; extend it to task/review work in Wave 2 and external Git/PR effects in Wave 3. |
| Independent review quality and incomplete remediation | 2 | Require independent review whenever practical, structured pass/fail where supported, and a mandatory maximum review-cycle limit with human attention. |
| Repository, authentication, hosting, and branch-protection conditions | 3 | Validate repository and delivery prerequisites before final external operations; retain explicit human merge control. |
| End-to-end validation realism | 3 | Use a new validation project with the PRD-required API, persistence, business-rule, test, multi-task, review/fix, Git, and PR complexity. |

## 9. Open Delivery Questions

The PRD's open questions remain product/technical decisions for the appropriate later stage; they do not prevent this delivery sequencing. In particular, the exact configurable approval defaults, final-validation gates, hosting-system support, failure-class retry policy, and minimum Codex capability set must be resolved in the relevant architecture overview or wave TECHSPEC without expanding approved MVP scope.
