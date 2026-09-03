# Workflow Capability Replanning Analysis

**Status:** Planning analysis only. This is not an approved architectural decision, not an approved Delivery Plan change, and not authorization to change a TECHSPEC, tasks, Skills, production code, or implementation. It is input to a subsequent human decision and planning-alignment step.

**Decision assessed:** Replan the approved three-Wave delivery structure to four Waves before Wave 2 implementation begins.

## 1. Recommendation

**Recommendation: ACCEPT WITH CHANGES.** Insert a new Wave 3, **Workflow Capability Orchestration**, after the approved Wave 2 task loop. Renumber and narrow the current planned Wave 3 as Wave 4, **Release Readiness & Controlled Delivery**.

This is the cleanest way to close a material allocation gap without changing the coherent approved Wave 2 boundary. The PRD requires Engineering Flow to own the full controlled lifecycle: delivery planning, conditional architecture planning, task execution/review/fix, Wave/release acceptance, routed remediation, next-Wave authorization, delivery authorization, and controlled Git/PR delivery. The current runtime owns only the historical Wave 1 PRD -> TECHSPEC -> task-plan slice. The approved Wave 2 TECHSPEC owns only the per-task execution/review/fix loop. The remaining lifecycle controls currently exist as repository Skills and bootstrap governance artifacts, not as executable product capabilities allocated to selected future implementation work.

The target architecture should use this conceptual model:

~~~
Workflow stage
  -> required domain capability
  -> selected agent runtime / provider
  -> provider-specific execution mechanism
~~~

A domain capability is not a Codex Skill. A Skill is reusable instructions/process knowledge, not an agent role. A role is not a provider/runtime. Engineering Flow owns the provider-neutral capability, state, policy, evidence, and transition; a runtime decides how to execute the bounded capability. For Codex, the mechanism may initially use a repository Skill, a bounded prompt/template derived from one, or another Codex-native facility. That must remain adapter detail: the domain must not name or load '.codex/skills' as its universal abstraction.

## 2. Evidence and current-state finding

| Evidence | Finding |
| --- | --- |
| Approved PRD, especially FR-001, FR-033--FR-035 and the primary flow | Requires the canonical lifecycle, distinct task/Wave/release acceptance, persisted authorization, and Git/PR only after release acceptance plus delivery authorization. |
| Approved Delivery Plan | Has three Waves; broadly maps task/Wave evidence to Wave 2 and release readiness/delivery to Wave 3. Bootstrap next-Wave authorization is explicitly manual until the product implements it. |
| Architecture overview | Already assigns lifecycle, acceptance, authorization, and Git ownership to the orchestrator, but still allocates delivery using the three-Wave plan. |
| Wave 1 TECHSPEC and authoritative Wave 1 PASS | Wave 1 was explicitly an intentionally bounded historical direct PRD -> TECHSPEC -> task-plan runtime slice. Its acceptance remains valid and does not commit future workflows to that incomplete sequence. |
| Approved Wave 2 TECHSPEC and task contracts | Wave 2 starts from an approved task plan and ends at TASKS_READY_FOR_WAVE_REVIEW. It expressly excludes Wave acceptance, release final review, starting a later Wave, and Git/PR work. |
| Repository Skill contracts | plan-delivery, create-architecture-overview, wave-review, fix-wave-review, final-review, and fix-final-review are constrained manual development-process procedures. They persist governance artifacts and deliberately stop rather than advance a product workflow. |
| Current source and tests | The implementation is Wave 1 only: Stage ends at READY_FOR_WAVE_2; roles are PRD/Architect/Planner; AgentRuntime exposes planning-only verification/execution; PlanningOrchestrator and CLI drive only PRD, TECHSPEC, and task-plan approvals. There are no records/transitions for delivery planning, architecture overview selection, task work, Wave/release acceptance, authorizations, or Git/PR delivery. |

The Wave 2 TECHSPEC and tasks are present but unimplemented; the working tree contains them as untracked planning artifacts. This analysis does not alter their status or treat their presence as implementation evidence.

### Control allocation today

| Canonical control | Current product runtime | Current repository process |
| --- | --- | --- |
| create-prd, create-techspec, create-tasks | Partially implemented by Wave 1 as a direct historical sequence | Codex Skills provide development-process contracts |
| plan-delivery and conditional create-architecture-overview | Not implemented | Manual Skill invocation and approval |
| execute-task, review-task, fix-task, re-review | Not implemented; allocated to Wave 2 | Manual Skills today; Wave 2 will operationalize the loop |
| wave-review, fix-wave-review, next-Wave authorization | Not implemented; no selected TECHSPEC allocates it | Manual review/remediation Skills and bootstrap WAVE-START-AUTHORIZATION artifacts |
| final-review, fix-final-review, release acceptance | Not implemented; no selected TECHSPEC allocates it | Manual release review/remediation Skills |
| delivery authorization, commit, push, PR | Not implemented; broadly allocated to current Wave 3 | Manual governance gate, with no product delivery code |

Therefore the named planning, Wave, and release controls are currently manual development-process controls, not executable product capabilities. The Delivery Plan's broad wording cannot replace a selected technical allocation when Wave 2 expressly excludes them and current Wave 3 has no TECHSPEC.

## 3. Recommended four-Wave structure

| Wave | Responsibility | Terminal boundary and exclusions |
| --- | --- | --- |
| **1 -- Controlled Planning Foundation** | Retain accepted historical feature input, PRD, TECHSPEC, task-plan artifacts, approval evidence, provider-neutral planning execution, resume, and CLI observability. | Historical READY_FOR_WAVE_2 result. It remains accepted evidence, not the future canonical lifecycle. No task work, acceptance hierarchy, or delivery. |
| **2 -- Autonomous Sequential Engineering Loop** | Retain approved task import, one-at-a-time execution, exact test evidence, independent review, bounded task remediation/re-review, task evidence/idempotency, task-local developer continuity, and human attention. | TASKS_READY_FOR_WAVE_REVIEW. No Wave acceptance, later-Wave decision, release review, delivery authorization, Git, push, or PR. |
| **3 -- Workflow Capability Orchestration (new)** | Make the complete provider-neutral lifecycle executable: capability selection/dispatch, approval and routing policy, cross-Wave/release evidence, acceptance, authorization, and human gates. Reuse Wave 2 runtime abstractions. | No Git/hosting side effects. It may persist release PASS and delivery-authorization decision/request, but cannot commit, push, or create a PR. |
| **4 -- Release Readiness & Controlled Delivery** | Focus the current planned Wave 3 on final runtime/product validation, delivery preflight, deterministic delivery summary, delivery idempotency, and orchestrator commit/push/PR after final-review PASS and explicit authorization. | Never merges. Cannot manufacture final-review PASS or delivery authorization. Must not equate final validation with release acceptance. |

Wave 3 is not a technical-layer ceremony Wave. It delivers the missing user outcome: Engineering Flow executes the canonical workflow instead of depending on a developer manually invoking repository Skills.

## 4. Wave 3 scope: required capabilities and state

Wave 3 should define domain capability IDs, normalized request/result contracts, and a lifecycle capability registry/resolver. It should not define one agent per Skill or a V1 provider-routing product. V1 selects the sole configured Codex runtime under fixed policy; future adapters can execute the same capability without changing lifecycle semantics.

1. **Planning orchestration**

   - Provider-neutral create_prd, plan_delivery, create_architecture_overview, create_techspec, and create_tasks capabilities.
   - Persisted approval requests/decisions and policy evaluation for PRD, delivery plan, conditionally required architecture overview, current-Wave TECHSPEC, and task plan.
   - Conditional architecture routing controlled by the approved delivery-plan artifact, not a hard-coded Skill name or agent prose.
   - Explicit migration/adaptation so future workflows use the canonical sequence while historical Wave 1 workflows/artifacts remain readable and valid.

2. **Task-loop integration**

   - Route an approved task plan to the Wave 2 task lifecycle and consume its persisted task acceptance evidence.
   - Do not duplicate Wave 2 task selection, test matching, cycle limits, reviewer independence, or task remediation mechanics.

3. **Wave acceptance, remediation, and later-Wave authorization**

   - review_wave and remediate_wave requests/results; authoritative review evidence references, structured outcome/finding ownership, and route-back to re-review.
   - Persist Wave acceptance only on normalized authoritative PASS; task completion or provider prose never implies it.
   - Persist explicit human next-Wave authorization, revocation, and supersession after predecessor PASS. Replace bootstrap authorization for product workflows while retaining existing bootstrap artifacts as historical governance evidence.

4. **Release acceptance, remediation, and delivery authorization state**

   - review_release and remediate_release requests/results; release membership, authoritative final-review evidence, finding ownership, and return routing.
   - Persist release acceptance only on final-review PASS after all included Waves pass.
   - Model delivery-authorization request/decision as a separate auditable lifecycle fact. Wave 3 owns this state/gate; Wave 4 consumes it for side effects.

5. **Shared orchestration facilities**

   - Capability request: workflow/scope identity, role, required permissions/capabilities, authoritative input artifact references/hashes, expected output schema, timeout/policy, and idempotency key.
   - Capability result: structured outcome, immutable evidence references/hashes, findings/ownership where relevant, provider session/execution metadata, and sanitized normalized events.
   - Durable stages/scope membership, approvals, acceptance facts, authorizations, routed findings, pending/unknown operations, and provider-neutral correlation IDs.

Generation/review work and human decision work must be distinct. A runtime may create an artifact or conduct a review; only the orchestrator records approval, acceptance, authorization, or routing when structured evidence and policy conditions are satisfied.

## 5. Work reserved exclusively for Wave 4

Wave 4 owns delivery-side effects and their delivery-specific safety/idempotency boundary:

- runtime/product final-validation execution and evidence;
- repository, target, worktree, branch-protection, authentication, remote, and hosting/PR preflight;
- deterministic commit message, staging policy, delivery summary, and PR body derived from authoritative evidence;
- durable intent/completion/reconciliation for commit, push, and PR creation;
- exactly-once/known-outcome behavior through interruption/resume;
- validation that the persisted delivery authorization is active, exact, and usable under policy;
- CLI status/logs for delivery state and failure.

Wave 4 does not own approval of planning, Wave/release acceptance, authorization decisions, or generic lifecycle progression. It consumes Wave 3 facts. Merge remains outside scope.

## 6. Wave 2 TECHSPEC impact

**Classification: remains valid as-is. No revision is required before create-tasks or implementation.**

The approved Wave 2 contract is architecturally sound under the replan. It owns only:

~~~
approved task plan -> execute -> tests -> independent review
                    -> fix -> tests -> re-review
                    -> TASKS_READY_FOR_WAVE_REVIEW
~~~

It establishes exactly the prerequisites Wave 3 needs: provider-neutral roles/requests/results/capabilities/sessions/events; durable operation identity; immutable evidence; and an orchestrator as sole task-transition authority.

Its references to Wave 3 are negative boundaries: it must not start a later Wave or perform release/delivery work. Those remain true after renumbering. Its Section 12 conclusion that no Delivery Plan decomposition concern exists becomes historical planning rationale only; it does not invalidate a technical requirement or task.

A future Wave 3 TECHSPEC may add an adapter/facade that starts the existing task-loop capability from a canonical approved task-plan state rather than requiring all future workflows to follow Wave 1's historical direct path. That is a Wave 3 compatibility concern, not a reason to broaden or amend Wave 2.

## 7. Wave 3 foundation on Wave 2 abstractions

Wave 2 first generalizes the planning-only runtime into provider-neutral role-specific engineering contracts. Wave 3 then adds a capability layer above it:

~~~
CapabilityOrchestrator
  selects required capability from persisted lifecycle state
  validates policy, approval/authorization, and capability preconditions
  creates bounded CapabilityExecutionRequest
       -> AgentRuntime (Codex in V1)
            -> provider-specific mechanism (Skill, prompt/template, or native API)
  validates normalized result and persists evidence
  alone records the next lifecycle transition
~~~

Wave 2 Developer/Reviewer execution becomes implementations of execute_task, review_task, and fix_task. Wave 3 adds planning, acceptance, and remediation capability families using the same session/execution/event, structured-result, capability-preflight, hash, and idempotency principles.

The V1 resolver must be declarative but closed: map every capability to the single configured Codex runtime. It must not introduce provider fallback, cost routing, or heterogeneous provider routing, all of which remain excluded by the PRD.

| Concept | Target-design meaning |
| --- | --- |
| Domain capability | Provider-neutral required outcome, such as review_wave. |
| Skill | Reusable instructions/process knowledge a Codex mechanism may use. |
| Agent role | Bounded execution responsibility, such as Reviewer. |
| Provider/runtime | The execution environment, Codex in V1. |

## 8. Risks and guardrails

| Risk | Required guardrail |
| --- | --- |
| Skill path/name becomes the domain API | Define capability IDs, schemas, inputs, outcomes, and evidence independently; confine Skill invocation/discovery to the Codex adapter. |
| Capability, role, provider collapse | Use separate typed values. A role may perform a capability; a runtime executes a request; neither changes lifecycle state. |
| Prohibited V1 provider routing reappears | Fixed configured Codex mapping only; leave an extension point without exposing routing/fallback behavior. |
| Agent prose advances acceptance | Require schema-checked outcomes, immutable evidence hashes, policy checks, and explicit decision records. |
| Acceptance becomes self-review | Preserve independent reviewer session/access policy for task, Wave, and release reviews where practical; record degradation. |
| Product workflow is confused with Engineering Flow's own manual governance | Keep Skills/bootstrap artifacts as repository-process controls until approved product behavior supersedes them; never retroactively accept earlier Waves through the product. |
| Unsafe/repeated Git side effects | Reserve them to Wave 4 after release PASS and delivery authorization, with stable delivery operation keys and reconciliation. |
| State explosion/remediation ambiguity | Define outcome/finding-ownership matrix and typed pending-approval, human-attention, remediation, Wave-accepted, release-accepted, and delivery-authorized states. |
| Historical Wave 1 migration | Preserve existing stages/artifacts/read behavior; version canonical lifecycle representation and never infer missing delivery-plan/architecture approvals. |
| Review capability or environment unavailable | Persist actionable human-attention/environment-blocked state; never substitute task PASS or final validation for Wave/release acceptance. |

## 9. Artifacts and assumptions that become stale if accepted

“Stale” means an approved alignment update or explicit historical-status note would be needed. It does not authorize an edit now.

| Artifact / assumption | Effect of accepting four Waves | Subsequent alignment |
| --- | --- | --- |
| docs/DELIVERY-PLAN.md §§2--4, §6 Wave 3, §§7--10 | Materially stale: three-Wave rationale, mapping, Wave 3 boundary/dependencies, risks, and sequence assume no orchestration Wave. | Reissue/approve four-Wave plan allocating canonical orchestration to Wave 3 and controlled delivery to Wave 4. |
| docs/architecture/architecture-overview.md §§1--2, §13, §15 | Materially stale only in three-Wave allocation. Stable ownership principles remain valid. | Amend allocation and add stage -> capability -> runtime -> mechanism boundary. |
| Wave 1 TECHSPEC §§1, 3, 9, 11 | Later-Wave numbering references become historical. The approved bounded implementation remains valid. | Preserve acceptance; at most add a non-normative historical mapping note later. |
| Wave 2 TECHSPEC §12 final conclusion | “No Delivery Plan decomposition concern” becomes outdated planning rationale. Core scope remains valid. | No amendment before tasks/implementation; future Wave 3 can carry compatibility cross-reference. |
| Wave 2 TASKS and TASK-001--005 | No technical scope staleness. Future “Wave 3” exclusion labels become numerically stale only. | Do not alter for this decision unless later documentation policy calls for non-substantive renumbering. |
| Approved PRD | No product requirement becomes stale: its lifecycle and distinctions support the proposal and it does not impose a three-Wave plan. | No PRD revision unless the human changes product scope, approvals, or V1 provider policy. |
| Product vision | Pre-PRD/non-authoritative. Its Skill/role distinction supports the proposal. | No canonical change required. |
| plan-delivery and create-architecture-overview Skill contracts | Valid manual governance procedures; stale only if misused as universal product runtime APIs. | Retain; define future Codex mechanism mapping outside domain contracts. |
| wave-review, fix-wave-review, final-review, fix-final-review Skill contracts | Valid manual governance procedures; their stop/no-auto-advance rules show the runtime gap. | Retain; Wave 3 implements equivalent product semantics, not direct Skill dependency. |
| create-prd, create-techspec, create-tasks, execute-task, review-task, fix-task Skill contracts | Useful Codex process knowledge, not agent roles or universal product contracts. | Define normalized capabilities and map to Codex execution mechanism later. |
| Delivery Plan bootstrap authorization assumption | Stale for completed product workflows once Wave 3 persists authorization; remains valid for manual development of Engineering Flow itself. | Specify product/bootstrapping compatibility, never reinterpret existing evidence. |
| Assumption that Wave 1 direct planning is the future canonical path | Stale for new workflows; already identified as historical in approved Wave 1 documents. | Wave 3 implements canonical delivery-plan and conditional-architecture gates. |
| Assumption that current Wave 3 can close lifecycle orchestration and delivery together | Stale; overly broad and side-effect-heavy. | Move delivery/readiness only to Wave 4. |

## 10. Alternatives

1. **Keep three Waves and expand Wave 2:** reject. It violates the approved Wave 2 boundary and combines a focused task loop with all planning/acceptance orchestration.
2. **Keep three Waves and add orchestration to current Wave 3:** reject. It combines canonical modeling, planning-gate migration, Wave/release routing, authorization, final validation, Git, hosting, and irreversible side effects in one late Wave.
3. **Use five Waves, splitting planning orchestration from acceptance/release orchestration:** not materially better. They share one lifecycle model, evidence contracts, authorization model, resolver, and human-gate policy; the split would be artificial.
4. **Use repository Skills as the product engine:** reject. It conflicts with provider-neutral/agent-agnostic design and gives no durable orchestrator control over transitions.

Four Waves are the smallest decomposition that preserves Wave 2, makes the promised canonical workflow executable, and isolates delivery side effects.

## 11. Subsequent planning-alignment step (not performed here)

After explicit human acceptance of this direction, perform one bounded planning-alignment change set before Wave 2 implementation:

1. Approve and update the Delivery Plan: four-Wave names, boundaries, mapping, dependencies, risks, authorization sequence, and Wave 3/4 references.
2. Amend the architecture overview only for cross-Wave allocation and the provider-neutral capability boundary; preserve stable ownership/evidence/safety decisions.
3. Record Wave 1 as accepted historical evidence; do not reopen it or infer missing canonical gates in prior workflows.
4. Record no Wave 2 TECHSPEC/task scope change, plus a future Wave 3 compatibility requirement to adapt to—not expand—the Wave 2 task loop.
5. After Wave 2 PASS and valid authorization, create the Wave 3 TECHSPEC covering catalog, request/result schemas, state/evidence, outcome routing, human decisions, migration, and fixed Codex V1 mapping.
6. Only after Wave 3 PASS/authorization, create a Wave 4 TECHSPEC for final validation and controlled Git/PR side effects consuming Wave 3 acceptance/authorization facts.
7. Decide authority/signing for approvals and authorizations; initial Codex mechanism choice; isolation of product workflow artifacts from this repository's governance artifacts; and release membership model for final review.

## 12. Major blockers requiring human decision

No discovered technical fact blocks the recommendation. The required human decisions are:

- authorize the Delivery Plan change from three to four Waves;
- choose whether Codex capability execution initially invokes Skills, uses bounded prompts/templates, or supports both, while preserving provider-neutral domain contracts;
- approve the actor identity/audit, revocation, and supersession model for product approvals, Wave/release acceptance, next-Wave authorization, and delivery authorization;
- approve compatibility/migration policy for historical Wave 1 records versus future canonical workflows.

Until those decisions and alignment artifacts are approved, Wave 2 remains authorized by its existing approved TECHSPEC, but this proposed replan is not approved.

