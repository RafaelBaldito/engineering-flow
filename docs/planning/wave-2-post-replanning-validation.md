# Wave 2 Post-Replanning Validation (P3)

**Status:** Validation evidence — P3 post-replanning validation
**Date:** 2026-09-03
**Subject:** Approved Wave 2 TECHSPEC, `Autonomous Sequential Engineering Loop`
**Classification:** `VALID_WITH_NON_BLOCKING_NOTES`

## 1. Purpose and authority

This artifact independently validates whether the already-approved Wave 2
TECHSPEC remains a usable implementation contract after the human-approved P2
four-Wave replanning. It is validation evidence only. It does **not** modify,
amend, reinterpret, or supersede the approved Wave 2 TECHSPEC; it does not
authorize task creation, implementation, later-Wave work, acceptance, or
delivery.

Authority was applied in this order: current user direction; the P2 decision;
the approved Delivery Plan and architecture overview; approved PRD; the
approved Wave 2 TECHSPEC; historical Wave 1/authorization evidence; and
current repository source as implementation evidence. `vision.md` and the
repository Skill contracts were used as supporting product/process context, not
as replacement domain contracts.

## 2. Conclusion

`VALID_WITH_NON_BLOCKING_NOTES`

The approved Wave 2 contract remains correctly bounded to:

```text
approved task plan
  -> execute -> exact required-test evidence -> independent review
  -> fix when required -> tests -> independent re-review
  -> TASKS_READY_FOR_WAVE_REVIEW
```

It neither assumes nor implements the full canonical lifecycle now allocated to
Wave 3, and it does not own release readiness or Git/push/PR delivery now
allocated to Wave 4. Its provider-neutral runtime, session, execution, event,
evidence, and operation-identity seams are appropriate foundations for Wave 3
without making Codex Skills a domain API.

No Wave 2 TECHSPEC amendment is required. One documentation-only note is
recorded in the issue register; it is not a technical, scope, or task-design
defect.

## 3. Evidence examined

| Evidence | Validation use |
| --- | --- |
| `docs/planning/workflow-capability-replanning-analysis.md` | P2 rationale, allocation gap, and stated Wave 2 impact. |
| `docs/planning/workflow-capability-replanning-decision.md` | Human-approved four-Wave ownership, capability distinction, authorization hierarchy, and invariants. |
| `docs/product/prd.md` and `docs/product/vision.md` | Product lifecycle, task-loop, state, persistence, provider-neutrality, Skill distinction, and delivery constraints. |
| `docs/DELIVERY-PLAN.md` | Approved Wave 2 boundary, Wave 3/4 ownership, bootstrap authorization rules, and requirement allocation. |
| `docs/architecture/architecture-overview.md` | Stable cross-Wave ownership and provider/capability/persistence boundaries. |
| `docs/waves/2-autonomous-sequential-engineering-loop/TECHSPEC.md` | Contract under validation. |
| `tasks/1-controlled-planning-workflow/reviews/WAVE-REVIEW.md` | Authoritative Wave 1 PASS and foundation evidence. Its SHA-256 matched the value recorded in the Wave 2 authorization: `d4c1d2a444d49de80f7b55adca0146df174e40d6e2731b34a7dc208ca9338083`. |
| `docs/waves/2-autonomous-sequential-engineering-loop/authorizations/wave-2-authorize-2026-09-03T12-59-32-03-00/WAVE-START-AUTHORIZATION.md` | Exact active bootstrap authorization scope. |
| `.codex/skills/execute-task/SKILL.md`, `.codex/skills/review-task/SKILL.md`, `.codex/skills/fix-task/SKILL.md` | Manual process semantics for bounded execution, independent review, structured fix handoff, and re-review; not a product-domain API. |
| `src/engineering_flow/{domain,runtime,orchestrator,store}.py` and tests | Current Wave 1 implementation seams and compatibility baseline. |

## 4. Validation findings

| Validation area | Result | Evidence and conclusion |
| --- | --- | --- |
| 1. Four-Wave scope consistency | PASS | Delivery Plan §5 assigns Wave 2 only the sequential task loop, with terminal `TASKS_READY_FOR_WAVE_REVIEW`. TECHSPEC §§1 and 4 implement precisely that boundary. |
| 2. Wave 1 dependencies | PASS | TECHSPEC §3 depends only on the accepted Wave 1 records: hashed approved task-plan artifact, SQLite/WAL store, operations, sessions, executions, events, and `COMPLETED/READY_FOR_WAVE_2`. Current source exposes those planning records and the Wave 1 PASS hash verifies. |
| 3. Wave 3 runtime/provider foundation | PASS | TECHSPEC §§5–8 generalize the planning runtime into provider-neutral role/request/result/capability/session/execution/event contracts with durable operation identity and normalized evidence. P2 assigns the later capability registry/resolver and capability IDs to Wave 3, which can build above these task-loop seams. |
| 4. Capability-orchestration ownership | PASS | Wave 2 chooses the next task and task-local action only. It does not select canonical lifecycle capabilities, evaluate planning/acceptance policy, route Wave/release remediation, record Wave/release acceptance, or record authorization. Those are expressly excluded in TECHSPEC §§1, 4.1, 6.2, and assigned to Wave 3 by the P2 decision and Delivery Plan. |
| 5. Release/delivery ownership | PASS | TECHSPEC §§1, 5, 6.2, 9, and 10 exclude final review, commit, push, PR, and merge. It records no Git/PR operation. Delivery Plan §5 and architecture §9 reserve readiness, reconciliation, and side effects to Wave 4. |
| 6. State-machine and terminal semantics | PASS | `TASKS_READY_FOR_WAVE_REVIEW` is explicitly terminal for Wave 2 only, not Wave acceptance, next-Wave authorization, Git, or PR activity (TECHSPEC §4.1). `HUMAN_ATTENTION` is the safe terminal/pause route for unresolved task-local conditions. This preserves the P2 acceptance hierarchy. |
| 7. Execute/review/fix loop and limits | PASS | TECHSPEC §4.3 establishes one active task, exact required-test gating before review, fresh reviewer sessions, `FIX_REQUIRED` remediation, counted review windows, and no autonomous limit bypass. This operationalizes the bounded semantics reflected in the execute-task, review-task, and fix-task contracts without importing those Skill names as domain types. |
| 8. Human intervention boundary | PASS | The `intervene` record is limited to task-level review-limit/unknown-outcome recovery and cannot accept, skip, alter evidence, or relax limits (TECHSPEC §4.3). Delivery Plan §3 expressly allocates review-limit intervention to Wave 2; durable general approval/authorization actor-audit semantics remain Wave 3 work. |
| 9. Persistence, resume, idempotency, observability | PASS | TECHSPEC §§7–8 require additive records, immutable hash-verified evidence, stable task operation keys, atomic completion/acceptance/next-task selection, unknown-operation human attention, policy snapshots, correlated events, and sanitized status/log projections. These are task-local contracts and do not preempt Wave 3 governance records or Wave 4 Git/PR reconciliation. |
| 10. Agent/provider neutrality | PASS | Generic task/review contracts and `verify_capabilities(repository, required_capabilities)` retain a sole configured Codex adapter while keeping provider mechanisms out of persistence and state authority (TECHSPEC §§5–6). This matches PRD FR-017–FR-021 and architecture §§5–6. |
| 11. Skills are not universal abstractions | PASS | The TECHSPEC refers to Developer/Reviewer roles, normalized requests/results, and provider capabilities; it neither names `.codex/skills` nor stores Skill paths/names as a lifecycle API. This satisfies P2 §2.2 and architecture §5. Repository Skills remain evidence of process semantics only. |
| 12. Authorization and acceptance hierarchy | PASS, with downstream gate | Task acceptance requires exact tests and structured independent review; Wave/release acceptance and authorization are expressly absent. The bootstrap authorization remains historical/repository governance evidence with literal scope, consistent with P2 §2.3 and Delivery Plan §§6–7. See §6 for its effect on task creation. |
| 13. Decomposability without Wave 3 debt | PASS | The contract divides coherently into durable task evidence/import, runtime/adapter contracts, orchestration/recovery, CLI/policy/observability, and deterministic integration validation. Existing unapproved candidate Wave 2 task artifacts follow that separation and do not assign Wave 3 or Wave 4 behavior to Wave 2; they were inspected only as feasibility evidence, not approved or modified. |
| 14. P2 staleness/contradiction review | PASS, documentation note | No normative scope, state, persistence, or provider contract is contradicted by P2. The one non-normative planning-rationale note is recorded below. |

## 5. Issue register

| ID | Classification | Evidence | Impact | Ownership | Wave 2 TECHSPEC modification required? |
| --- | --- | --- | --- | --- | --- |
| P3-001 | `DOCUMENTATION_ONLY` | The P2 analysis §9 identifies the final sentence of TECHSPEC §12 ("no Delivery Plan decomposition concern") as pre-four-Wave planning rationale. The approved Delivery Plan now documents four Waves. The same §12 still correctly limits Wave 2 decomposition to its bounded vertical outcome and excludes future-Wave delivery design. | No implementation ambiguity or architectural debt: the current four-Wave plan preserves the Wave 2 boundary unchanged. The sentence should be interpreted as historical rationale, not as a claim that the delivery plan still has its former structure. | Documentation alignment only; no Wave owns an implementation change. | No. |

Counts: `BLOCKING_WAVE_2 = 0`; `NON_BLOCKING_WAVE_2 = 0`;
`DEFERRED_WAVE_3 = 0`; `DEFERRED_WAVE_4 = 0`; `DOCUMENTATION_ONLY = 1`.

## 6. Authorization and create-tasks disposition

The existing bootstrap authorization is valid historical evidence, but its
literal authorized scope is **"Create the target Wave TECHSPEC only."** The
P2 decision preserved it without creating a Wave 2 task or implementation
authorization, and Delivery Plan §7 requires bootstrap artifacts to authorize
only their recorded exact scope.

Therefore this P3 validation does not permit `create-tasks` to proceed yet. A
separate active, exact human authorization for task planning is required under
the documented bootstrap hierarchy. This is an intentional governance gate,
not a Wave 2 TECHSPEC defect and not grounds for amendment or replanning.

## 7. Static validation performed

| Check | Result | Evidence |
| --- | --- | --- |
| Wave 1 PASS integrity | PASS | Recomputed SHA-256 exactly matched the value in the Wave 2 authorization. |
| Documentation/contract assertions | PASS | Confirmed all named governing artifacts exist and the TECHSPEC contains its task terminal state, no-delivery boundary, provider-neutrality, and human-attention contract. |
| Current implementation regression suite | PASS | `PYTHONPATH=src python3 -m unittest discover -s tests`: 53 tests passed. |
| Current implementation compile check | PASS | `PYTHONPATH=src python3 -m compileall -q src` exited successfully. |
| Markdown diff whitespace check for pre-existing tracked planning changes | PASS | `git diff --check -- docs/DELIVERY-PLAN.md docs/architecture/architecture-overview.md docs/product/prd.md docs/product/vision.md` produced no errors. |

The repository has no `python` command; the applicable checks therefore used
the available `python3` (3.12.3). No production code, Skills, canonical
planning/product/architecture document, task, or TECHSPEC was modified by this
validation.

## 8. Final determination

- **Wave 2 TECHSPEC classification:** `VALID_WITH_NON_BLOCKING_NOTES`
- **Wave 2 TECHSPEC modification required:** No
- **Create tasks may proceed:** No — pending separate, exact bootstrap task-planning authorization
- **Replan required:** No

The approved Wave 2 TECHSPEC is a valid, bounded implementation contract for
the autonomous sequential engineering loop. It gives Wave 3 reusable
provider-neutral execution/evidence seams while preserving Wave 3 governance
and Wave 4 delivery boundaries.
