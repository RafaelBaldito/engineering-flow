# Architecture Overview

## 1. Purpose

This document defines the stable architecture contract for Engineering Flow V1
(MVP). It is the cross-wave reference for the controlled workflow that moves a
feature request to a review-ready Pull Request (PR). It does not replace the
TECHSPEC for Wave 1, Wave 2, or Wave 3.

The product is a Python CLI control plane. A coding-agent provider performs
engineering work in an execution plane; Engineering Flow owns the lifecycle,
policies, evidence, and externally visible delivery decisions.

## 2. Architectural Context

The approved delivery plan has three ordered waves:

1. Controlled planning through an approved task plan.
2. Sequential implementation, testing, independent review, and bounded fixes.
3. Final validation, controlled Git delivery, and creation of a review-ready
   PR.

The same workflow identity, state ownership, provider boundary, persistence
rules, event vocabulary, CLI boundary, and safety rules apply throughout all
three waves. V1 has one local CLI user and one supported provider integration
(Codex); it does not include parallel task execution, provider routing or
fallback, distributed workers, a dashboard, or autonomous merge.

## 3. Core Architectural Principles

- Engineering Flow decides **what happens next**; the selected agent decides
  **how to perform bounded engineering work**.
- Workflow transitions are deterministic, policy-controlled, and recorded;
  agent output alone cannot advance the lifecycle.
- The core domain uses provider-neutral concepts and preserves provider-native
  behavior behind adapters when it cannot be usefully normalized.
- Planning approvals and safety stops are first-class workflow states, not
  informal prompts or log messages.
- Lifecycle state and evidence survive process interruption. Resuming must not
  repeat a completed external or recorded side effect.
- CLI commands are clients of orchestration services; they do not embed
  workflow business rules.
- A task is eligible to complete only after required implementation, tests,
  independent review, and absence of blocking findings.

## 4. High-Level System Responsibilities

| Responsibility | Owner | Boundary |
| --- | --- | --- |
| Workflow progression, stage/task transitions, policies, approvals, retry and review-cycle decisions | Orchestration core | Agents request or report work; they cannot advance lifecycle state directly. |
| Engineering reasoning, repository exploration, code changes, tests, review, and remediation | Agent runtime execution | Work is requested for a specific role, bounded context, and execution. |
| Provider-native sessions, events, permissions, and result translation | Provider adapter | Keeps provider SDK/protocol details out of the core. |
| Workflow record, artifacts, execution history, and idempotency evidence | Persistence boundary | Persists controlled lifecycle facts and references. |
| Commands to run, inspect, approve, reject, resume, and access logs | CLI boundary | Delegates to orchestration services. |
| Staging, commit, push, PR creation, and their duplicate protection | Controlled Git/PR integration | Agents may propose content but do not freely own repository delivery. |

The roles PRD, Architect, Planner, Developer, and Reviewer are workflow
responsibilities. A role is distinct from a provider, skill, session, and
execution.

## 5. Workflow and State Ownership

The orchestrator owns one authoritative workflow lifecycle. Conceptually it
progresses through planning, approval waiting, sequential task work, final
validation, delivery, and terminal states:

```text
created -> planning work -> awaiting required approval
        -> approved next planning work -> approved task plan
        -> task implementation/test/review/fix loop
        -> final validation -> commit -> push -> PR -> completed
```

At every applicable stage, an approval policy is `required`, `automatic`, or
`conditional`. V1's initial policy requires human approval of the PRD,
TECHSPEC, and task plan. Rejection, an exhausted review/fix limit,
unrecoverable failure, cancellation, or a safety stop transitions the workflow
to a recorded waiting, failed, cancelled, or human-attention state rather than
allowing uncontrolled continuation.

The task lifecycle is sequential in V1. The orchestrator decides when a task
may begin, retry, enter remediation, complete, or advance to the next task.
Review failure routes only through the configured bounded remediation loop;
reaching its mandatory maximum requires human intervention. Completion requires
all required approvals, quality gates, Git state, push, and PR creation; merge
is outside workflow completion.

## 6. Agent Runtime and Provider Boundaries

The orchestration core depends on provider-neutral concepts:

- **AgentRuntime:** accepts bounded execution requests, reports availability,
  and manages sessions and execution control.
- **AgentSession:** a persistent logical interaction context associated with a
  role or unit of work.
- **AgentExecution:** one requested unit of work within a session, with a
  lifecycle and result.
- **AgentEvent:** a normalized lifecycle observation emitted by an execution.
- **AgentCapabilities:** declared/verified permissions and abilities relevant
  to a requested execution.

Before starting an execution, orchestration validates the selected runtime's
applicable permissions and capabilities to the extent V1 supports. The core
uses normalized requests, results, pass/fail outcomes where available, and
events; it does not depend on Codex-native names, session identifiers, or SDK
types.

V1 implements Codex through a provider adapter. The adapter translates between
core requests and provider-native session APIs, executions, events, approvals,
capabilities, and results. Provider-specific behavior that cannot be safely
normalized remains adapter-owned and is persisted or surfaced as provider
metadata, rather than reshaping workflow semantics. Future adapters must
implement the same core boundary without requiring workflow redesign.

## 7. Session and Execution Model

A session is logical continuity; an execution is an individual bounded turn or
unit of work. Workflow state is neither: it remains orchestrator-owned and
must not rely solely on a provider retaining context. Provider state is an
adapter concern linked to, but not substituted for, the logical session.

Planning roles receive only the feature input and authoritative artifacts
needed for their stage. For a task, the Developer session should retain useful
context across implementation and subsequent fixes. The Reviewer uses a
separate, independently evaluable session whenever practical, with read-only
access preferred. Review outputs become workflow evidence and remediation
input; they do not grant the reviewer authority to complete a task.

## 8. Persistence, Resume, and Idempotency

The persistence boundary owns enough durable information to reconstruct and
control a workflow after termination. This includes the workflow identifier,
current stage and task, approval requests and decisions, selected provider,
logical and provider session references, execution history, review/fix and
retry progress, failures, artifact references, Git state, and PR state.

Generated artifacts are durable inputs to later stages: feature input, PRD,
architecture and TECHSPEC artifacts, approved task plan, task records, tests,
reviews, logs, and delivery summary. Approval decisions and lifecycle records
are authoritative; agent conversation context is supporting evidence, not the
sole source of truth.

Resume re-enters the orchestrator from persisted controlled state. State
transitions and side effects must have a durable identity or completion record
so retrying or resuming cannot duplicate approval recording, task/workflow
completion, commit creation, push, or PR creation. The concrete storage model,
locking, and idempotency algorithms belong to the relevant wave TECHSPEC.

## 9. Events, Logs, and Observability

The orchestration layer emits provider-neutral, structured lifecycle events and
retains correlated logs and execution metadata. Conceptual event categories
include `workflow.*`, `stage.*`, `approval.*`, `agent.session.*`,
`agent.execution.*`, `test.*`, `review.*`, `git.*`, and `pull_request.*`.

Events communicate lifecycle facts such as started, completed, failed, or
requested, with workflow, stage, task, execution, and provider correlation
where applicable. Adapters map provider-native events into this vocabulary and
may preserve provider-specific metadata. Logs, event history, and future
metrics/tracing all attach to the controlled workflow record. Secret values and
unsafe command or environment data must be sanitized before persistent or CLI
exposure.

## 10. CLI and Artifact Access

The CLI initiates and observes orchestration operations: initialization,
workflow run, status, approval, rejection, resume, and access to logs and
artifacts. It presents the authoritative persisted state and history, rather
than inferring state from provider output.

Artifact storage and display are separate from workflow decision-making. An
artifact becomes an authoritative stage input only once recorded by the
orchestrator under the stage's policy; drafts and provider output alone do not
advance the workflow.

## 11. Git and Pull Request Integration

Git and PR operations are controlled orchestration side effects. After Wave 2
has established a final eligible state and Wave 3's final validation passes,
the controlled integration validates repository, branch, authentication, and
hosting prerequisites before staging, committing, pushing, and creating the
PR according to policy.

Agents may propose commit messages, PR descriptions, changed-file summaries,
and human-review notes. The orchestration layer owns execution and recording of
the Git lifecycle. A successful PR summarizes requirements, technical
approach, implemented tasks, changed files, tests, review cycles and resolved
findings, limitations, and available human-review notes. Commit, push, and PR
creation obey the global idempotency boundary. Merge automation remains
disabled unless separately approved scope changes it.

## 12. Safety and Failure Boundaries

Safety is a cross-cutting policy enforced by orchestration and integrations,
not delegated to agent discretion. Stable controls include explicit target
repository and workspace validation, protected-branch handling, restricted
destructive operations, provider permission validation, bounded timeouts and
retries, mandatory review/fix limits, secret protection, sanitized logs, and
disabled-by-default merge automation.

Failures are recorded distinctly enough to support policy decisions: workflow,
provider, agent-execution, tool, test, review, Git, authentication, and human
rejection. The orchestrator owns the recovery decision under configured policy:
retry when eligible, route review findings to remediation, return to an earlier
controlled stage when permitted, or pause for human attention. An adapter or
agent may report a failure but cannot silently choose a workflow transition.

## 13. Cross-Wave Architectural Contracts

The following contracts are intentionally stable across all delivery waves:

- The orchestration core is the sole authority for workflow, approval,
  task-lifecycle, retry, and completion decisions.
- Provider-neutral runtime, session, execution, event, and capability concepts
  isolate Codex-specific integration behind an adapter.
- Persisted workflow state and artifacts are authoritative for resume;
  lifecycle transitions and external side effects require duplicate protection.
- Structured lifecycle events, correlated logs, and sanitized evidence are the
  observability contract exposed through the CLI.
- Context is role- and stage-scoped; Developer continuity is task-local and
  Reviewer independence is preferred and separately evaluable.
- Git and PR operations are policy-controlled orchestration responsibilities;
  agents do not independently control repository delivery and merge is human
  gated.
- Safety limits and human-attention states take precedence over autonomous
  progress.

Wave 1 establishes these contracts for planning. Wave 2 extends them to task,
test, and review evidence without changing ownership. Wave 3 applies them to
irreversible Git and PR delivery operations.

## 14. Architecture Decisions Deferred to TECHSPECs

The following need wave-specific technical decisions and are deliberately not
fixed here: storage technology and schemas; exact state representation and
transition implementation; configuration and CLI syntax; concrete Codex API
and authentication integration; capability/permission checks; event payloads;
artifact layout; retry and timeout values by failure class; exact quality and
final-validation gates; repository-hosting support; Git command mechanics; and
how the new validation project is exercised.

The PRD also leaves open the V1 approval defaults beyond the initial required
planning gates. Their configuration model and defaults should be resolved in
the relevant TECHSPEC without broadening the approved scope.

## 15. Summary

Engineering Flow is a durable, observable workflow control plane around a
provider-neutral agent-runtime boundary. Its stable contracts keep human
approval, independent review, recovery, safe delivery, and audit evidence
under orchestrator control while allowing provider adapters to evolve. This
overview is ready to guide the Wave 1 TECHSPEC.
