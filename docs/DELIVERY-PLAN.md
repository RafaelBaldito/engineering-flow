# Delivery Plan

## 1. Delivery Summary

Engineering Flow V1 is a Python CLI control plane that takes a feature request
through governed planning, sequential engineering work, acceptance, and
post-acceptance deterministic Git/PR delivery. This approved plan is the
authority for delivery mode, Wave boundaries, dependencies, and architecture
overview applicability. It does not replace the approved historical evidence
for Wave 1 or prescribe Wave-specific implementation design.

The approved four-Wave decision is recorded in
`docs/planning/workflow-capability-replanning-decision.md`. The earlier
replanning analysis remains evidence, not the decision artifact.

## 2. Delivery Mode and Rationale

**WAVES — four ordered Waves.**

Four Waves isolate four independently demonstrable outcomes: an accepted
historical planning foundation, a bounded autonomous task loop, executable
provider-neutral lifecycle governance, and controlled external delivery. This
separation keeps Wave 2 focused while ensuring that planning, acceptance, and
authorization are product capabilities rather than manual repository process.

## 3. Requirement Coverage

| Approved requirement area | Delivery destination |
| --- | --- |
| Controlled workflow progression and planning artifacts (FR-001–FR-005) | Wave 1 preserves the historical planning slice; Wave 3 implements the canonical planning lifecycle and capability routing. |
| Planning approvals, actor/audit decisions, and intervention (FR-006–FR-010) | Wave 1 historical planning approvals; Wave 2 review-limit intervention; Wave 3 persisted product approval/authorization and governance lifecycle. |
| Sequential execution, test evidence, independent review, and task remediation (FR-011–FR-016) | Wave 2 only. |
| Provider-neutral runtime and applicable capability validation (FR-017–FR-021) | Waves 1–2 establish runtime abstractions; Wave 3 adds domain capability resolution without coupling the domain to Codex Skills. |
| Acceptance hierarchy and authorization gates (FR-033–FR-035) | Wave 2 supplies task evidence; Wave 3 owns Wave/release acceptance and authorization state/routing; Wave 4 consumes active delivery authorization for external delivery. |
| Persistence, recovery, artifacts, and duplicate protection (FR-022–FR-025) | Wave 1 planning records; Wave 2 task records; Wave 3 governance and capability records; Wave 4 Git/PR reconciliation. |
| Controlled Git and PR delivery (FR-026–FR-029) | Wave 4 only. |
| CLI, observability, and failure response (FR-030–FR-032) | Extended by each Wave for the lifecycle it owns. |
| AC-001 | Historical Wave 1 evidence for its bounded planning slice; canonical planning completion is Wave 3. |
| AC-002–AC-004 | Wave 2. |
| AC-005–AC-006 | Incremental across Waves 1–4. |
| AC-007–AC-008 | Wave 4, after Wave 3 governance capability is available. |

## 4. Architecture Overview Applicability

**Required.** The global architecture overview defines stable workflow,
provider-neutral capability, persistence, authorization/actor-audit, safety,
and Git/PR ownership boundaries. It is approved planning context, not a
replacement for a selected Wave TECHSPEC.

## 5. Delivery Scopes

### Wave 1 — Controlled Planning Foundation

- **Boundary:** Preserve the implemented and accepted historical feature -> PRD
  -> TECHSPEC -> task-plan runtime, approvals, artifacts, provider-neutral
  planning execution, resume, and CLI observability.
- **Exclusions:** It is not the canonical lifecycle; it does not execute tasks,
  accept Waves/releases, authorize later work, or deliver Git/PR side effects.
- **Dependency/outcome:** It remains accepted historical evidence and supplies
  the bounded foundation on which Wave 2 was authorized.

### Wave 2 — Autonomous Sequential Engineering Loop

- **Boundary:** Starting from an approved task plan, execute one task at a time
  through implementation, exact tests, independent review, bounded fix and
  re-review cycles, durable evidence, and human-attention routing.
- **Terminal boundary:** `TASKS_READY_FOR_WAVE_REVIEW`; task PASS is not Wave
  acceptance. No Wave/release acceptance, later-Wave authorization, Git, push,
  or PR delivery.
- **Dependency/outcome:** Builds on Wave 1 planning/runtime records and
  provides task-level execution abstractions and evidence consumed by Wave 3.
  Its approved TECHSPEC remains valid as-is.

### Wave 3 — Workflow Capability Orchestration

- **Boundary:** Make the canonical lifecycle executable under Engineering Flow
  control. Own provider-neutral domain capability selection/resolution,
  planning-stage expansion, conditional architecture routing, compatibility for
  historical workflows, Wave/release review-remediation routing, and durable
  approval, acceptance, authorization, actor/audit, revocation, and
  supersession state.
- **Exclusions:** Does not duplicate Wave 2 task-loop mechanics or perform
  Git/hosting side effects. It may record release acceptance and delivery
  authorization, but it cannot commit, push, or create a Pull Request.
- **Dependency/outcome:** Builds on Wave 2 runtime abstractions and makes
  lifecycle decisions/evidence provider-neutral. The Codex adapter may map a
  domain capability to a repository Skill or bounded prompt/template without
  making either the domain abstraction.

### Wave 4 — Release Readiness & Controlled Delivery

- **Boundary:** Own runtime/product final validation, delivery preflight,
  deterministic delivery summary, delivery intent/completion/reconciliation,
  and orchestrator-owned commit, push, and Pull Request creation.
- **Gate/exclusions:** Runs side effects only after authoritative release
  acceptance and an active, exact delivery authorization. It consumes and
  validates those facts; it does not manufacture them, own general capability
  orchestration, or merge.
- **Dependency/outcome:** Builds on Wave 3 governance records and produces the
  review-ready Pull Request and final workflow completion evidence.

## 6. Canonical Lifecycle and Acceptance Boundaries

```text
feature -> PRD -> approval -> delivery planning -> approval
-> conditional architecture overview -> approval when required
-> Wave start authorization -> per-Wave TECHSPEC -> approval
-> task planning (permitted by exact TECHSPEC approval) -> approval
-> task registration and task execute/review/fix loops (permitted by exact task-plan approval)
-> Wave review/remediation routing -> Wave acceptance
-> explicit next-Wave authorization -> subsequent Wave(s)
-> after all included Waves are accepted: release final-review/remediation
-> release acceptance -> explicit delivery authorization
-> deterministic orchestrator commit -> push -> PR
-> review-ready Pull Request -> final workflow completion
```

`APPROVE` accepts the exact active, stage-correct, hash-bound authoritative
artifact as the current stage result and permits its defined canonical successor
under existing policy. `AUTHORIZE` permits new scope, a non-canonical
transition, an external side effect, or another action not implied by canonical
predecessor acceptance. Thus TECHSPEC approval permits canonical task planning,
and task-plan approval permits task registration and the bounded autonomous
execute/review/fix loop; neither requires a separate authorization.

Task acceptance, Wave acceptance, release acceptance, authorization to start a
later Wave, delivery authorization, and completion are separate persisted facts.
Runtime/product final validation is a quality gate; it never substitutes for
release-level `final-review`.

## 7. Bootstrap Governance Compatibility

Until Wave 3 implements the target persisted product capability, append-only
Markdown approvals and authorization artifacts govern the development of
Engineering Flow itself. Authorization artifacts authorize only the literal
scope they record. Approval artifacts have the canonical-progression semantics
in §7.1 and are not inferred from a predecessor PASS or an unrelated artifact.
They remain valid historical/bootstrap evidence; Wave 3 must not fabricate
missing records or reinterpret them as target-product records.

The existing Wave 2 `WAVE-START-AUTHORIZATION.md` remains valid and untouched
as historical evidence. Its recorded scope is not retroactively expanded and
no missing authority record is fabricated.

### 7.1 Bootstrap Canonical-Progression Contract

For prospective bootstrap governance, `APPROVE` of an exact active,
stage-correct, hash-bound TECHSPEC accepts that result and permits
`create-tasks`, its canonical successor. `APPROVE` of the exact resulting task
plan accepts that result and permits task registration plus the bounded
autonomous execute/review/fix loop. A separate
`TASK-PLANNING-AUTHORIZATION.md` is not required and no separate task-execution
authorization is required.

This correction does not infer authority from a Wave-start authorization, a
predecessor Wave PASS, or any historical artifact. `AUTHORIZE` remains required
for starting every independently bounded Wave, including each later Wave after
predecessor acceptance; delivery side effects; scope/spec changes;
exceptional/non-canonical intervention or remediation; and policy-defined
high-risk boundaries. Wave-review PASS deterministically accepts its Wave but
does not authorize a later Wave. Release acceptance does not authorize commit,
push, or Pull Request creation; active delivery authorization remains required.

Approval and authorization evidence remains append-only. Revocation,
supersession, revision change, or inactive/stale evidence blocks reliance on
the affected decision and requires the normal applicable human route.
Product-level persistence and detailed decision semantics remain owned by Wave
3.

## 8. Cross-Cutting Constraints

- The V1 core is provider-neutral, while Codex is the sole configured runtime.
  A domain capability is not a Codex Skill, agent role, or provider.
- Engineering Flow alone controls lifecycle state, acceptance/authorization
  recording, policies, observability, auditability, and Git/PR lifecycle.
- Every Wave retains context discipline, structured evidence, safety limits,
  secret/log protection, repository validation, and idempotent resume.
- V1 remains sequential, local/CLI-oriented, single-user, and non-merging.

## 9. Delivery Risks and Deferred Detail

Wave 3 technical design must resolve capability schemas/resolution, lifecycle
version compatibility, actor/audit record design, authorization transitions,
Codex Skill-versus-prompt adapter equivalence, and remediation routing. Wave 4
then resolves delivery-specific validation, hosting, authentication, and Git/PR
mechanics. Neither Wave may broaden the boundaries above.
