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
-> task planning -> approval -> task execute/review/fix loops
-> Wave review/remediation routing -> Wave acceptance
-> explicit next-Wave authorization -> subsequent Wave(s)
-> after all included Waves are accepted: release final-review/remediation
-> release acceptance -> explicit delivery authorization
-> deterministic orchestrator commit -> push -> PR
-> review-ready Pull Request -> final workflow completion
```

Task acceptance, Wave acceptance, release acceptance, authorization to start a
later Wave, delivery authorization, and completion are separate persisted facts.
Runtime/product final validation is a quality gate; it never substitutes for
release-level `final-review`.

## 7. Bootstrap Governance Compatibility

Until Wave 3 implements the target persisted product capability, append-only
Markdown approvals and authorization artifacts govern the development of
Engineering Flow itself. They authorize only the literal scope they record and
are not inferred from a predecessor PASS or any other artifact. They remain
valid historical/bootstrap evidence; Wave 3 must not fabricate missing records
or reinterpret them as target-product records.

The existing Wave 2 `WAVE-START-AUTHORIZATION.md` remains valid and untouched.
Its scope is only creation of the target Wave TECHSPEC. It neither authorizes
task planning nor expands when the TECHSPEC is approved or validated.

### 7.1 Bootstrap Task-Planning Authorization Contract

Before `create-tasks` creates a Wave task set, there must be one separately
persisted and validated active task-planning authorization. The canonical
artifact is named `TASK-PLANNING-AUTHORIZATION.md`; each decision record is
stored at:

```text
docs/waves/<target-wave>/authorizations/<authorization-id>/TASK-PLANNING-AUTHORIZATION.md
```

This is a contract for a future decision record, not an authorization by
itself. No such artifact may be inferred from this plan, a Wave-start
authorization, TECHSPEC approval, P3 validation, or a predecessor Wave PASS.

#### Scope and required fields

An active authorization has exactly this scope:

> Create the target Wave task set from the specifically bound approved
> TECHSPEC, ending at `AWAITING_HUMAN_APPROVAL`.

It authorizes neither approval of that task set nor task execution, tests or
implementation, task review or fixes, Wave review or acceptance, subsequent
Waves, release review, delivery authorization, commit, push, or Pull Request
creation.

Every `TASK-PLANNING-AUTHORIZATION.md` decision record must contain:

- authorization ID (unique and identical to `<authorization-id>` in its path);
- target Wave identifier (identical to `<target-wave>` in its path);
- explicit human decision;
- identifiable actor;
- RFC 3339 timestamp with offset;
- recorded status and lifecycle linkage: an `AUTHORIZE_TASK_PLANNING` record
  records `ACTIVE`; a revocation records `REVOKED`; `SUPERSEDED` is an
  effective status derived from valid later supersession evidence under §7.1;
- the exact authorized scope above (for an active authorization);
- approved TECHSPEC repository-relative path and SHA-256 digest;
- TECHSPEC approval/status evidence path and SHA-256 digest, with evidence
  that the bound TECHSPEC revision is `Approved`;
- predecessor authoritative Wave-review PASS path and SHA-256 digest when the
  target Wave has a predecessor; or an explicit `NOT_APPLICABLE` rationale
  where no predecessor exists;
- where applicable, the affected/superseded authorization ID, artifact path,
  and SHA-256 digest, plus a human-readable reason.

Paths and digests are evidence fields, not descriptive hints. A digest is the
lowercase SHA-256 of the referenced repository artifact bytes. The TECHSPEC
approval/status evidence may be the bound TECHSPEC only when that artifact
itself authoritatively records its `Approved` status; it must still be cited
and hashed separately.

#### Validation and lifecycle rules

Validation must reject an authorization unless all of the following hold:

- its artifact path, ID, target Wave, actor, human decision, timestamp, and
  required evidence fields are present and internally consistent;
- the selected Wave is exactly the bound target Wave;
- the selected approved TECHSPEC path and freshly computed SHA-256 exactly
  equal the bound path and digest, and the cited approval/status evidence is
  present, hash-matched, authoritative, and establishes `Approved` for that
  exact revision;
- where applicable, the predecessor evidence exists, its freshly computed
  digest matches, and it is the authoritative `PASS` for the predecessor Wave;
- the record is an `ACTIVE` human `AUTHORIZE_TASK_PLANNING` decision with the
  exact scope in §7.1; and
- no other effective `ACTIVE` task-planning authorization exists for the same
  target Wave and bound TECHSPEC path/digest pair.

An authorization is valid only for its bound Wave and TECHSPEC revision. It
cannot be reused for another Wave, a changed TECHSPEC, task-set approval, or
any implementation or later lifecycle action. `create-tasks` may use it only
to create the bound Wave task set and must stop at
`AWAITING_HUMAN_APPROVAL`.

Authorization records are append-only. Never edit, delete, rename, or
overwrite an existing decision record to change its status or evidence. A
revocation is a new decision record at a new authorization ID with human
decision `REVOKE_TASK_PLANNING_AUTHORIZATION`, recorded status `REVOKED`, and
exact affected-record path/ID/digest. A replacement active authorization may
declare human decision `AUTHORIZE_TASK_PLANNING` and exact supersession evidence
for a prior authorization; the affected prior record is then effectively
`SUPERSEDED`. Validators must resolve this lineage before use and reject any
record that is effectively revoked or superseded, including one whose original
immutable record recorded `ACTIVE`. A revocation or supersession record never
itself grants task-planning authority.

Product-level authorization storage and semantics remain owned by Wave 3.

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
