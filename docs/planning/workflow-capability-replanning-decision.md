# Workflow Capability Replanning Decision

**Status:** Human-approved planning and architecture decision (P2)
**Decision date:** 2026-09-03
**Applies to:** Engineering Flow V1 delivery planning before Wave 2 implementation

## 1. Relationship to the Prior Analysis

`docs/planning/workflow-capability-replanning-analysis.md` is preserved as the
pre-decision analysis and evidence. It is not this decision and must not be
rewritten to imply that it was itself approved. This artifact records the
human-approved direction derived from that analysis.

## 2. Approved Decisions

### 2.1 Four-Wave delivery structure

1. **Wave 1 — Controlled Planning Foundation** remains implemented and
   accepted historical delivery. Its direct PRD -> TECHSPEC -> task-plan runtime
   was intentionally bounded, is not the future canonical lifecycle, and its
   authoritative PASS evidence remains valid without reconstruction.
2. **Wave 2 — Autonomous Sequential Engineering Loop** retains its approved
   TECHSPEC, task-level execution/review/fix boundary, and runtime abstractions.
   It is not expanded to own general lifecycle orchestration.
3. **Wave 3 — Workflow Capability Orchestration** is a new Wave. It makes the
   canonical lifecycle executable under Engineering Flow control: planning-stage
   expansion, provider-neutral capability orchestration, lifecycle routing,
   Wave/release governance state, persisted acceptance, and authorization.
4. **Wave 4 — Release Readiness & Controlled Delivery** is the replanned former
   Wave 3. It owns runtime/product final validation, release readiness, and
   deterministic commit, push, and Pull Request creation only after authoritative
   release acceptance and active delivery authorization. It does not own general
   capability orchestration or manufacture governance facts.

### 2.2 Provider-neutral capability architecture

The following concepts are distinct and must remain independently modeled:

```text
Domain Capability != Codex Skill != Agent Role != Provider / Runtime
```

The canonical execution direction is:

```text
Workflow Stage -> Required Capability -> Capability Resolution
               -> AgentRuntime / Provider -> provider-specific execution mechanism
```

Engineering Flow chooses the required domain capability and retains lifecycle
authority. The selected runtime/provider materializes the bounded request. For
the Codex provider, a capability may use an existing repository Skill or a
bounded provider-specific prompt/template. That choice is adapter-owned; where
interchangeability matters, equivalence, compatibility, and versioning must be
explicit. Skill paths and names, including `.codex/skills`, are never universal
domain abstractions.

### 2.3 Authorization, actor, and audit boundary

The target product persists explicit, auditable authorization records for human
workflow decisions, including applicable planning approvals, Wave acceptance
facts, next-Wave start authorization, release acceptance, delivery
authorization, and revocation/supersession.

Each decision must be attributable to an identifiable actor and retain its
scope, timestamp, authoritative evidence references, status, and relationship
to any superseded or revoked record. This defines an actor/audit boundary only;
it deliberately does not select external identity or authentication technology.

Markdown authorization artifacts remain valid bootstrap governance evidence for
developing Engineering Flow until the product implements persisted equivalents.
They govern repository development, not the target product persistence model.

### 2.4 Historical lifecycle compatibility

Historical workflow records are interpreted under the lifecycle contract in
force when they were produced. Wave 1 evidence remains valid. Future canonical
workflows use the expanded lifecycle. The product must version the lifecycle
compatibility boundary so historical records can coexist without inventing
missing approvals, delivery planning, architecture decisions, acceptance, or
authorization facts. No retroactive reconstruction is permitted.

## 3. Canonical Target Lifecycle

```text
feature
-> PRD -> approval
-> delivery planning -> approval
-> conditional architecture overview -> approval when required
-> Wave start authorization
-> per-Wave TECHSPEC -> approval
-> task planning -> approval
-> task execute/review/fix loops
-> Wave review/remediation routing -> Wave acceptance
-> explicit next-Wave authorization -> subsequent Wave(s)
-> after all included Waves are accepted: release final-review/remediation
-> release acceptance -> explicit delivery authorization
-> deterministic orchestrator-owned Git commit/push/PR delivery
-> review-ready Pull Request -> final workflow completion
```

Task acceptance, Wave acceptance, release acceptance, next-Wave authorization,
delivery authorization, and final workflow completion are separate facts.
Runtime/product final validation is a quality capability and is not
release-level `final-review` or release acceptance.

## 4. Consequences and Protected Evidence

| Wave | Consequence |
| --- | --- |
| 1 | Preserve accepted historical implementation and authoritative PASS. Do not reinterpret its lifecycle as canonical or fabricate missing governance. |
| 2 | Preserve approved TECHSPEC and task-loop scope exactly. P2 creates no Wave 2 tasks, implementation, authorization change, or TECHSPEC edit. |
| 3 | Own capability resolution, canonical lifecycle routing, planning expansion, compatibility, acceptance/authorization records, Wave/release review-remediation routing, and the actor/audit boundary. No Git/hosting side effects. |
| 4 | Consume active release acceptance and delivery authorization; validate readiness and perform deterministic Git/PR delivery with reconciliation/idempotency. No merge and no creation of acceptance or authorization facts. |

## 5. Decisions Deferred to the Wave 3 TECHSPEC

- exact domain capability identifiers, request/result schemas, resolver and
  registry representation;
- lifecycle-version representation and historical compatibility/read behavior;
- persisted authorization, acceptance, actor/audit, revocation, and
  supersession schemas and transition rules;
- how approval-policy evaluation and conditional architecture routing are
  encoded;
- Codex adapter mapping of a capability to a repository Skill versus a bounded
  prompt/template, including required compatibility/equivalence/version checks;
- detailed Wave/release review-remediation finding ownership and return routing;
- exact CLI, storage migration, event, idempotency, and human-attention details.

## 6. Invariants for Future TECHSPECs

- Engineering Flow alone records lifecycle transitions, approvals, acceptance,
  authorizations, and routing from validated evidence and policy; provider prose
  cannot do so.
- A domain capability is never identified by a Codex Skill path or name.
- Wave 2 remains the sole owner of per-task selection, tests, independent
  review, remediation cycles, and task acceptance mechanics.
- A Wave PASS does not authorize another Wave; release PASS does not authorize
  external delivery; delivery authorization does not itself create release PASS.
- Wave 4 performs no delivery side effect without active, exact, persisted
  release acceptance and delivery authorization, and never merges.
- Historical artifacts remain readable and valid only for their recorded
  lifecycle version; missing historical governance facts are not inferred.
- Bootstrap Markdown evidence remains append-only historical/repository
  governance evidence until superseded by the product capability, never a
  substitute for new product records.
