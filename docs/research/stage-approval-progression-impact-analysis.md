# Stage-Approval Progression Impact Analysis

## 1. Executive Decision

**Decision: ACCEPT_WITH_CHANGES.** Approval of the exact authoritative artifact should accept that stage result and permit its canonical successor. Remove the bootstrap-only separate `TASK-PLANNING-AUTHORIZATION` gate and do not add a separate execution authorization after task-plan approval. This removes duplicate human questions without weakening new-scope, non-canonical, or external-side-effect decisions.

The correction is prospective lifecycle-contract and Controller work. It does not amend the approved Wave 3 TECHSPEC or rewrite history.

## 2. Current Lifecycle Contract

The PRD already defines the normal sequence as TECHSPEC approval, task planning, task-plan approval, then automatic bounded task execution (FR-001 and FR-007). Delivery Plan §7.1 is the exception: before `create-tasks`, it requires a separately persisted active `TASK-PLANNING-AUTHORIZATION.md`, hash-bound to the approved TECHSPEC, and says that authority cannot be inferred from TECHSPEC approval. It permits only task-set creation and stops at task-plan approval.

This was introduced as **bootstrap governance compatibility**, protecting literal, append-only Markdown authority before Wave 3 product persistence existed. The bootstrap coordinator design repeats it: `create-tasks` requires separate authorization and `TASK_PLAN_REQUIRED` validates it. The Wave 3 start authorization also limits itself to TECHSPEC creation and excludes task planning.

There is no corresponding separate task-execution authorization in the PRD, Delivery Plan, architecture, Wave 3 TECHSPEC, controller, or product runtime. The required normal gate is task-plan approval. The controller immediately advances `TASK_PLAN_APPROVAL` to `TASK_EXECUTION_REQUIRED`, then hash-validates and registers `TASKS.md`. A new execution gate would be an unsupported new requirement.

The separate task-planning artifact addressed a bootstrap concern—do not enlarge a narrow Wave-start authorization—but after a human approves the exact TECHSPEC for its defined successor, it asks no independent question.

## 3. Problem Observed During Wave 3 Dogfooding

The persisted Wave 3 state contains a satisfied `TECHSPEC_APPROVAL` of the exact `TECHSPEC.md` SHA-256 and transition `AWAITING_TECHSPEC_APPROVAL->TASK_PLAN_REQUIRED`. Controller `next` maps that state to the Planner/`create-tasks` capability. No operation has started and no `TASKS.md` exists.

This is a **documentation/controller contract mismatch combined with an obsolete authority requirement**. It is not a missing guard: the controller deliberately has no task-planning-authorization parser, record, or guard. Adding one would preserve the redundant question.

## 4. Proposed Approval Semantics

`APPROVE` means that an identifiable actor accepts the exact hash-bound current authoritative artifact as the result of its stage and permits the orchestrator to run its defined canonical successor under existing policies.

Use **one approval fact** (model A). Its semantics include canonical progression. A correlated transition/event may be persisted atomically for audit and idempotency, but is derived state, not a second authority fact. Model B adds lineage/synchronization hazards without another human decision.

An approval is usable only while active, scope/stage-correct, exact-revision/hash-bound, and not revoked or superseded. Validate this both at transition and at dispatch/recovery.

## 5. Proposed Authorization Semantics

`AUTHORIZE` explicitly permits an action or scope not implied by acceptance of its canonical predecessor. It remains required for:

- starting each independently bounded Wave, including every later Wave after predecessor acceptance;
- active delivery authorization for commit, push, and PR side effects after release acceptance;
- scope/spec changes, exceptional remediation/rerouting, intervention, and other non-canonical transitions;
- policy-specific high-risk boundaries already supported by authoritative contracts.

Wave Review PASS is the current contract's deterministic condition for Wave acceptance, not another human approval. It never starts a later Wave; a later Wave still requires explicit authorization.

## 6. Target Human-Gate Lifecycle

```text
AUTHORIZE_WAVE
-> create TECHSPEC
-> AWAITING_TECHSPEC_APPROVAL
-> APPROVE exact TECHSPEC
-> create task plan
-> AWAITING_TASK_PLAN_APPROVAL
-> APPROVE exact task plan
-> autonomous sequential execute/review/fix loop
-> Wave Review/remediation
-> Wave acceptance on authoritative PASS
-> STOP; separately authorize another Wave
```

The next orchestration action may be immediate or occur on resume/`next`; timing is not a human gate. Task-plan approval remains necessary because the plan is a new result. No extra approval is invented for Wave acceptance.

## 7. Revocation / Supersession / Artifact Revision Semantics

Decisions remain append-only historical evidence. Revocation/supersession never deletes artifacts, operations, reviews, or acceptance evidence; it blocks reliance on the affected active fact, emits audit evidence, and requires a human route before redispatch.

| Situation | Required result |
| --- | --- |
| TECHSPEC approval revoked before planning | Stop at task-planning boundary; require a fresh active approval of the same current revision or a revised TECHSPEC and approval. |
| Revoked after `TASKS.md`, before task-plan approval | Do not approve/execute the plan. Preserve draft evidence; normally regenerate/reapprove from the newly approved TECHSPEC. |
| Task-plan approval revoked before execution | Block registration/dispatch; preserve history; require fresh approval of the exact plan. |
| Revoked after execution begins | Stop new dispatch/fix/review advancement. Preserve completed evidence and require human attention to reapprove, replace, or change scope. |
| Artifact hash/revision changes | Approval is stale and unusable; the revision follows its normal approval boundary. |
| Approval superseded | Resolve one active lineage for scope and revision. Prior fact stays historical; ambiguity pauses for human attention. |

Revocation is not a time machine: it prevents future dependent progression. Undoing completed work requires explicit intervention/remediation. Fresh-host recovery must compute the same active lineage.

## 8. Historical and Lifecycle Compatibility

Wave 1 and Wave 2 remain accepted historical records under their own contracts; do not reconstruct new governance facts. Wave 3 bootstrap state is schema v1 and already has the required exact TECHSPEC approval, no task plan, and no task work. Corrected policy can consume it without migration or state editing.

The target product already needs lifecycle-version compatibility. Record this as a new lifecycle contract/policy version for new product records and preserve read-only behavior for prior versions. It requires no migration to fabricate a derived progression authority. The Wave 3 governance schema must support active approval lineage, revocation, and supersession. Bootstrap v1 needs compatible interpretation only.

Future Wave 4 still needs its own start authorization and, later, delivery authorization. Markdown bootstrap evidence is never silently converted into target-product records.

## 9. Bootstrap Controller Impact

The controller already implements desired canonical transitions:

- a satisfied `AWAITING_TECHSPEC_APPROVAL` advances to `TASK_PLAN_REQUIRED` and exposes `create-tasks`;
- `record_authority(TASK_PLAN_APPROVAL)` atomically advances to `TASK_EXECUTION_REQUIRED`; `register_tasks` binds exact approved `TASKS.md` before Developer dispatch.

Therefore do not add a task-planning authority guard at `TASK_PLAN_REQUIRED` or an execution-authorization guard at `TASK_EXECUTION_REQUIRED`. Update handoff/contract wording to name TECHSPEC approval as the Planner prerequisite and task-plan approval as registration/execution prerequisite.

Required hardening:

- make satisfied approval evidence explicitly stage/path/hash-bound and validate it in `next`, before `begin_operation`, and before registration;
- add revocation/supersession commands and active-lineage validation, or make unsupported requests deterministically enter human attention;
- revalidate approval activity/hashes on reconciliation and before dependent dispatch; current hash checking catches byte drift but cannot represent revocation;
- preserve idempotency for repeat approval, `next`, registration, and recovery; do not create duplicate planner leases;
- prevent a gate from becoming invalid between action proposal and operation acquisition.

`record-authority` currently records only `APPROVE` despite its generic name. Rename it at the product boundary or add typed decision operations separating approve, authorize, revoke, and supersede. This is clarity/future contract work, not a reason for a second human decision.

## 10. Product Runtime Impact

`src/engineering_flow` is the older planning runtime. Its `approve` transaction records one artifact approval and `_approval_transition` selects the next stage; approved inputs are hash-validated. That already matches one-decision canonical progression, but it has no Wave scope, authorization/acceptance model, revocation/supersession lineage, or canonical Wave lifecycle.

Wave 3 implementation must add/version scope-aware state guards; governance decisions and active lineage; revision dependencies; capability requests/results; Wave/release acceptance; explicit Wave-start/delivery authorizations; atomic decision-plus-transition events; recovery; and idempotency. CLI `approve`, `authorize`, `revoke`, `supersede`, `resume`, `status`, and `logs` need typed target/scope/evidence inputs. Events should distinguish approval, derived canonical progression, authorization, revocation, supersession, stale approval, and human attention. Existing approval storage can remain compatibility input but is insufficient alone.

## 11. Skill Impact Matrix

| Skill | Classification | Impact |
| --- | --- | --- |
| `create-techspec` | REVIEW_DURING_IMPLEMENTATION | Ensure approval enables canonical task planning while Wave-start remains distinct. |
| `create-tasks` | CHANGE_REQUIRED | Replace separately valid task-planning authorization with active exact TECHSPEC approval; retain stop at task-plan approval. |
| `execute-task` | REVIEW_DURING_IMPLEMENTATION | Confirm task-plan approval is the sole normal execution gate. |
| `review-task`, `fix-task` | NO_CHANGE | They own task acceptance/remediation, not entry authority. |
| `wave-review`, `fix-wave-review` | REVIEW_DURING_IMPLEMENTATION | Retain PASS acceptance/non-canonical remediation and no implied next-Wave authority. |
| `plan-delivery` | REVIEW_DURING_IMPLEMENTATION | Avoid recreating duplicate successor authorizations. |
| `final-review`, `fix-final-review` | NO_CHANGE | Release acceptance/delivery separation is unchanged. |

## 12. Documentation Impact Matrix

**Normative:** amend `docs/product/prd.md`, `docs/DELIVERY-PLAN.md` (remove/replace §7.1), `docs/architecture/architecture-overview.md`, and `docs/planning/workflow-capability-replanning-decision.md` to make approval-to-canonical-successor semantics explicit while retaining Wave-start and delivery authorization.

**Implementation/design:** amend `docs/research/codex-wave-workflow-coordinator-design.md` and `docs/research/bootstrap-wave-controller-implementation.md`; then update code/test contracts.

**Explanatory:** align `docs/product/vision.md` only as needed; its precedence notice makes it non-controlling.

**Untouched historical artifacts:** Wave 1/2 TECHSPECs, acceptances, authorizations, task/review evidence; Wave 3 start authorization, approved TECHSPEC, and persisted state/evidence. Wave 3 TECHSPEC needs **no amendment/reapproval**: it distinguishes approval and authorization, requires active hash-bound facts and atomic advancement, lists no task-planning authorization decision, and scopes Wave 3 to lifecycle/governance. This is a superseding lifecycle-policy correction, not a TECHSPEC edit.

## 13. Test Impact

Minimum additions/changes:

- active exact TECHSPEC approval permits one create-tasks lease without `TASK-PLANNING-AUTHORIZATION`; missing approval blocks it;
- stale/revoked/superseded/conflicting/wrong-scope TECHSPEC approval blocks planning and recovery;
- active exact task-plan approval permits registration/execution without execution authorization; missing/stale/revoked approval blocks both;
- Wave-start remains required; Wave PASS cannot start another Wave; release acceptance plus delivery authorization remains required for delivery;
- scope/spec change and non-canonical remediation cannot reuse old approval;
- fresh-host recovery has identical results and repeat approval/progression/registration/recovery is idempotent;
- revocation at every point in §7 preserves history and blocks only future dependent progression.

Update, do not discard, existing bootstrap transition/hash/idempotency/registration/recovery tests. Add product-level transaction/event and lifecycle-version compatibility tests.

## 14. Current Wave 3 Recovery Path

After contract correction and Controller guard/test validation, Wave 3 can continue from `TASK_PLAN_REQUIRED` without manual state editing, historical reconstruction, or a new task-planning authorization. The persisted approval binds the exact current TECHSPEC and no Planner operation/task plan exists.

Safe procedure: (1) approve/persist normative correction without editing Wave 3 evidence; (2) update and validate Controller/Skills/tests; (3) perform read-only status/reconcile confirming the same hash and no active operation; (4) permit normal `next`/create-tasks dispatch. If TECHSPEC bytes change, the approval is stale and return to TECHSPEC approval.

## 15. Risks / Non-Goals

This must not make approval permission for arbitrary later work. The successor is singular, canonical, hash-bound, and policy-governed. Do not infer Wave-start, delivery, scope-change, intervention, or remediation authority; reinterpret history; edit the approved TECHSPEC; create tasks; or advance Wave 3 during this analysis.

## 16. Recommended Change Sequence

1. Adopt the decision and amend PRD/Delivery Plan/architecture/replanning contract; remove §7.1's separate bootstrap artifact requirement.
2. Update bootstrap coordinator documentation and affected Skills while retaining Wave-start, non-canonical, and delivery authority.
3. Implement hash-bound active approval lineage/atomic transitions in the Controller and revocation/supersession support or deterministic human-attention handling.
4. Add focused tests and run full validation.
5. Read-only reconcile existing Wave 3 evidence, then resume only through Controller dispatch.
6. Implement the corresponding versioned product governance model with historical read compatibility.

## 17. Final Recommendation

Do not retain separate `TASK-PLANNING-AUTHORIZATION`; do not create a separate task-execution authorization after `TASK_PLAN_APPROVAL`. TECHSPEC approval authorizes canonical creation of the hash-bound Wave task plan. Task-plan approval authorizes registration and the bounded autonomous task execute/review/fix loop. Explicit authorization remains for Wave starts, later-Wave starts, external delivery, and genuinely non-canonical or policy-defined high-risk decisions.

The existing approved Wave 3 TECHSPEC needs no amendment/reapproval. Wave 3 is recoverable from `TASK_PLAN_REQUIRED` without manual state editing, but it is not safe to resume until the conflicting normative/bootstrap contract, Controller safeguards, and focused tests are corrected and validated.

ACCEPT_WITH_CHANGES

