# Stage-Approval Progression Bootstrap Contract Correction

## Scope and result

This correction applies the decided normative lifecycle semantics only to the
bootstrap coordinator design and affected Skills. It does not advance a Wave,
create a task plan, alter the Controller or production implementation, or
reinterpret historical evidence.

`APPROVE` accepts the exact active, stage-correct, hash-bound result and
permits its defined canonical successor. `AUTHORIZE` remains required for new
scope, non-canonical actions, external side effects, and policy-defined
high-risk boundaries not implied by canonical predecessor approval.

## Design documents changed

- `docs/research/codex-wave-workflow-coordinator-design.md`

Its binding Skill summary, lifecycle state/transition rules, human-gate list,
approval/authorization distinction, and Planner handoff now require the active
exact-revision TECHSPEC approval for canonical task planning. Its execution
transition now requires the active exact-revision task-plan approval. The
separate task-planning authorization gate was removed without adding an
execution authorization gate.

`docs/research/bootstrap-wave-controller-implementation.md` was inspected and
intentionally unchanged: it already says `TASK_PLAN_APPROVAL`, bound to the
exact current `TASKS.md` hash, is the registration prerequisite and contains
no separate task-planning-authorization contract.

## Skills inspected

- `create-techspec`
- `create-tasks`
- `execute-task`
- `wave-review`
- `fix-wave-review`
- `plan-delivery`

## Skills changed

- `create-tasks`: replaced every bootstrap
  `TASK-PLANNING-AUTHORIZATION` prerequisite with the active, stage-correct,
  exact-Wave/path/SHA-256 TECHSPEC approval. The Skill still stops with the
  generated task set awaiting its separate task-plan approval; it does not
  infer implementation, Wave acceptance, later-Wave, or delivery authority.
- `execute-task`: makes active exact-revision task-plan approval the normal
  canonical entry authority and explicitly rejects missing, stale, revoked,
  superseded, or path/hash-mismatched approval. It explicitly states that no
  separate execution authorization is required.

## Skills intentionally unchanged

- `create-techspec`: already requires a valid active Wave-start authorization
  for a Wave and, after TECHSPEC approval, permits separately initiated
  `create-tasks` without starting execution or another Wave.
- `wave-review`: already makes a PASS Wave acceptance, prohibits starting the
  next Wave, and requires explicit persisted later-Wave authorization.
- `fix-wave-review`: already preserves Wave re-review before acceptance and
  requires both authoritative PASS and a valid active Wave-start authorization
  before a later Wave.
- `plan-delivery`: already preserves Wave-start authorization for every later
  Wave and does not create a duplicate task-planning or execution gate.

## Contract checks

- Old separate `TASK-PLANNING-AUTHORIZATION` references removed/replaced from
  active bootstrap contracts: **YES**.
- Active exact-revision TECHSPEC approval is `create-tasks` authority: **YES**.
- Active exact-revision task-plan approval is `execute-task` authority: **YES**.
- Separate task-execution authorization introduced: **NO**.
- Wave-start authorization preserved: **YES**.
- Next-Wave authorization preserved: **YES**. Wave Review PASS accepts only
  the reviewed Wave and stops; it does not authorize a later Wave.
- Delivery authorization preserved: **YES**. No approval in this flow permits
  commit, push, Pull Request, or other delivery side effects.
- Stale/hash-bound approval requirements preserved: **YES**. Planning and
  execution require current exact path/SHA-256 approval, active lineage, and
  rejection for revocation, supersession, stale revision, or ambiguity.

## Protected artifacts and non-actions

- Wave 3 TECHSPEC changed: **NO**.
- Wave 3 workflow state changed: **NO**.
- Wave 3 authorization/approval evidence changed: **NO**.
- Historical Wave 1/2 artifacts changed: **NO**.
- Controller code changed: **NO**.
- Controller tests changed: **NO**.
- Production code changed: **NO**.
- `TASKS.md` created: **NO**.
- Task planning started: **NO**.
- Wave 3 advanced: **NO**.

## Remaining inconsistencies

No separate `TASK-PLANNING-AUTHORIZATION` reference remains in the active
bootstrap design/Skill contracts reviewed here. The remaining inconsistency is
implementation-level: the Controller and its tests still need the active
approval-lineage/revocation hardening described by the impact analysis before
Wave 3 can be reconciled and resumed. This correction does not alter the
already-corrected normative product documents or historical contracts.

## Exact Controller and test work still required

- Make `TECHSPEC_APPROVAL` evidence explicitly stage/path/hash-bound and
  validate active lineage in `next`, before Planner operation acquisition, and
  during reconciliation/recovery. An active exact TECHSPEC approval must permit
  one `create-tasks` lease without a task-planning authorization.
- Validate active exact `TASK_PLAN_APPROVAL` before registration and Developer
  dispatch; it must bind the current `TASKS.md` hash and must not require a
  separate execution authorization.
- Add revoke/supersede operations with active-lineage validation, or route
  unsupported revoke/supersede requests deterministically to human attention.
  Revalidate approval activity and hashes before dependent dispatch and prevent
  invalidation between action proposal and operation acquisition.
- Preserve atomicity and idempotency for approval/progression, `next`, task
  registration, and recovery; do not produce duplicate Planner leases.
- Clarify the Controller decision API so typed `approve`, `authorize`,
  `revoke`, and `supersede` facts are distinct; `record-authority` currently
  records only `APPROVE`.
- Update focused Controller tests for: missing/wrong/stale/revoked/superseded/
  conflicting TECHSPEC approval blocking planning and recovery; exact
  task-plan approval permitting registration/execution and blocking when
  invalid; Wave-start remaining required; Wave PASS not starting another Wave;
  delivery requiring separate authorization; non-canonical/scope/spec changes
  not reusing old approval; and fresh-host idempotent recovery at every
  revocation boundary. Retain existing transition/hash/idempotency/
  registration/recovery coverage.

## Recommended next step

Implement and test the listed Controller active-lineage and typed-decision
work in a separately authorized scope. Then perform only a read-only Wave 3
status/reconcile check before any Controller-mediated continuation.
