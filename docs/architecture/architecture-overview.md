# Architecture Overview

## 1. Purpose

This is the stable cross-Wave architecture contract for Engineering Flow V1. It
supports the approved four-Wave delivery plan and does not replace a Wave
TECHSPEC. Wave 1's accepted historical planning implementation and Wave 2's
approved bounded TECHSPEC remain valid under their recorded contracts.

Engineering Flow is a Python CLI control plane. It owns lifecycle policy,
evidence, and delivery decisions; an agent runtime performs bounded engineering
work through a provider adapter.

## 2. Four-Wave Context

1. **Wave 1 — Controlled Planning Foundation:** accepted historical direct PRD
   -> TECHSPEC -> task-plan slice; not the future canonical lifecycle.
2. **Wave 2 — Autonomous Sequential Engineering Loop:** approved task-level
   execution, tests, independent review, bounded fix/re-review, and task
   evidence; terminal state is not Wave acceptance.
3. **Wave 3 — Workflow Capability Orchestration:** canonical lifecycle,
   capability resolution, planning expansion, governance records, and
   compatibility.
4. **Wave 4 — Release Readiness & Controlled Delivery:** final validation,
   delivery readiness, and deterministic post-authorization Git/PR side effects.

V1 has one local user and a single configured Codex provider. It excludes
parallel work, provider routing/fallback, distributed workers, dashboard, and
autonomous merge.

## 3. Core Principles

- Engineering Flow decides what must happen next; the selected runtime decides
  how to perform a bounded engineering request.
- Lifecycle transitions, approval, acceptance, authorization, and routing are
  deterministic, policy-controlled, persisted orchestrator decisions. Provider
  output is evidence, never a transition instruction.
- Task acceptance, Wave acceptance, release acceptance, next-Wave
  authorization, delivery authorization, and final completion are distinct,
  durable facts.
- State and evidence survive interruption. Every externally visible or
  lifecycle-recording operation has a durable identity and known-outcome or
  human-attention recovery behavior.
- CLI commands are clients of orchestration services; they do not embed
  workflow business logic.

## 4. Workflow and Governance Ownership

The target lifecycle is:

```text
feature -> PRD -> approval -> delivery planning -> approval
-> conditional architecture overview -> approval when required
-> Wave start authorization -> per-Wave TECHSPEC -> approval
-> task planning -> approval -> task execute/review/fix loops
-> Wave review/remediation routing -> Wave acceptance
-> explicit next-Wave authorization -> subsequent Wave(s)
-> after all included Waves are accepted: release final-review/remediation
-> release acceptance -> explicit delivery authorization
-> deterministic orchestrator commit -> push -> PR
-> review-ready Pull Request -> final workflow completion
```

`final validation` is runtime/product quality evidence. It is neither
release-level `final-review` nor release acceptance.

The orchestrator evaluates the approval policy, validates structured evidence,
and records all authoritative decisions. For human decisions it persists an
auditable record with identifiable actor, scope, timestamp, evidence references,
status, and applicable revocation/supersession relationship. This is an
actor/audit boundary, not a decision to adopt a particular authentication or
identity technology.

## 5. Capability, Role, and Provider Boundaries

The domain distinction is mandatory:

```text
Domain Capability != Codex Skill != Agent Role != Provider / Runtime
```

```text
Workflow Stage -> Required Capability -> Capability Resolution
               -> AgentRuntime / Provider -> provider-specific execution mechanism
```

A domain capability expresses the provider-neutral outcome required by a stage
(for example, delivery planning, task review, Wave review, or release review).
An agent role is a bounded work responsibility. `AgentRuntime`,
`AgentSession`, `AgentExecution`, `AgentEvent`, and `AgentCapabilities` are
provider-neutral execution concepts. None is a lifecycle authority.

The Codex adapter may materialize a resolved capability using a repository Skill
or a bounded prompt/template. That choice, including required mechanism
equivalence, compatibility, and version checks, belongs to the adapter. The core
must not store `.codex/skills` paths or names as its domain capability API.

## 6. Responsibility Boundaries

| Responsibility | Owner | Boundary |
| --- | --- | --- |
| Stage progression, policy, capability selection, approval/acceptance/authorization recording, remediation routing | Orchestration core | Validates evidence and controls state; providers cannot advance it. |
| Engineering reasoning, code changes, tests, reviews, and bounded remediation | Agent runtime execution | Receives role- and stage-scoped requests only. |
| Provider-native sessions, mechanisms, permissions, events, and result translation | Provider adapter | Isolates provider details and returns normalized evidence/metadata. |
| Workflow artifacts, decision records, operation identity, execution history, and resume state | Persistence boundary | Holds authoritative facts and immutable evidence references. |
| Start, inspect, approve/reject/authorize, resume, logs, and artifacts | CLI boundary | Delegates to the orchestrator. |
| Staging, commit, push, PR creation, and reconciliation | Wave 4 controlled delivery integration | Runs only after active release acceptance and delivery authorization. |

Wave 2 alone owns per-task selection, exact required-test validation, reviewer
independence, remediation-cycle limits, and task acceptance mechanics. Wave 3
orchestrates around that interface; it does not duplicate it.

## 7. State, Persistence, and Compatibility

Persistence holds workflow/scope identity and membership, current lifecycle
stage, lifecycle version, capability requests/results, approvals, acceptance
facts, authorizations, actor/audit data, sessions/executions, artifacts,
findings/routing, failures, retries, Git state, and Pull Request state.
Immutable evidence references and hashes support audit and resume.

Historical records are valid according to their recorded lifecycle contract.
Wave 1 remains readable and accepted as its bounded historical path; no delivery
plan, architecture approval, acceptance, or authorization fact may be inferred
when it was not recorded. Future canonical workflows use the expanded lifecycle
behind explicit version compatibility. Bootstrap Markdown governance artifacts
remain valid repository-development evidence until Wave 3 implements product
persistence; they are not retroactively converted into product records.

Resume re-enters the orchestrator from persisted state. Unknown or pending
operations must reconcile to a known outcome or pause for human attention;
resuming may not duplicate approval, acceptance, authorization, commit, push,
or PR work.

## 8. Sessions, Events, and CLI

A logical session is continuity for a role/unit of work; an execution is one
bounded request. Workflow state is orchestrator-owned, not provider memory.
Developer continuity may be task-local. Reviewer sessions remain independent
whenever practical and do not grant task acceptance authority.

Provider-neutral events include workflow, stage, capability, approval,
authorization, acceptance, agent session/execution, test, review, Git, and PR
families. Provider-native metadata remains adapter-owned and is sanitized before
persistence or CLI exposure. The CLI exposes authoritative state, evidence, and
logs rather than deriving progress from agent prose.

## 9. Release Delivery and Safety

Wave 4 validates repository, worktree, branch, authentication, remote, and
hosting readiness before deterministic staging, commit, push, and PR creation.
It consumes an active, exact release acceptance and delivery authorization;
neither a Wave PASS nor final validation permits delivery. Agents may propose
delivery content but never control side effects. Merge stays out of scope.

Cross-cutting controls include workspace/repository validation, protected-branch
handling, restricted destructive actions, runtime permission checks, bounded
timeouts/retries, mandatory review/fix limits, secret protection, sanitized
logs, and idempotency/reconciliation for external operations.

## 10. Cross-Wave Contracts and Deferred Decisions

Future TECHSPECs must preserve the lifecycle, ownership, capability separation,
historical compatibility, independent review, evidence, safety, and delivery
gates above.

Wave 3 TECHSPEC decides the exact capability registry/resolver and schemas;
lifecycle-version and compatibility representation; authorization/acceptance
and actor/audit persistence; revocation/supersession transitions; Codex
Skill-versus-prompt mapping compatibility; remediation routing; and concrete
CLI, events, idempotency, and migration behavior. Wave 4 TECHSPEC decides only
delivery-specific validation, hosting/authentication, Git/PR mechanics, and
reconciliation. No external identity technology is selected here.
