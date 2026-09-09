# Stage-Approval Progression Normative Correction

## Scope

This correction adopts the approved normative lifecycle decision in
`stage-approval-progression-impact-analysis.md`. It is documentation/contract
correction only; it neither advances work nor changes implementation or
historical evidence.

## Files changed

- `docs/product/prd.md`
- `docs/DELIVERY-PLAN.md`
- `docs/architecture/architecture-overview.md`
- `docs/planning/workflow-capability-replanning-decision.md`
- this report

## Correction made

The old Delivery Plan §7.1 bootstrap rule requiring a separately persisted,
active `TASK-PLANNING-AUTHORIZATION.md` before `create-tasks` was removed and
replaced.

`APPROVE` now normatively means an identifiable actor accepts the exact active,
stage-correct, hash-bound authoritative artifact as the current stage result
and permits its defined canonical successor under existing policy. Therefore:

- TECHSPEC approval -> task planning: **YES**.
- Task-plan approval -> task registration and bounded autonomous
  execute/review/fix loop: **YES**.
- Separate `TASK-PLANNING-AUTHORIZATION` required: **NO**.
- Separate task-execution authorization required: **NO**.

`AUTHORIZE` remains the explicit decision for new scope, a non-canonical
transition, an external side effect, or another action not implied by canonical
predecessor acceptance. It remains required for Wave starts, later-Wave starts,
delivery, scope/spec changes, exceptional/non-canonical intervention or
remediation, and policy-defined high-risk boundaries.

- Wave-start authorization retained: **YES**.
- Next-Wave authorization retained: **YES**.
- Delivery authorization retained: **YES**.

Wave Review PASS still results in Wave acceptance; Wave acceptance does not
authorize a next Wave. Release acceptance alone still does not authorize
commit, push, or Pull Request creation.

## Protected artifacts and scope

- Wave 3 TECHSPEC changed: **NO**.
- Wave 3 state changed: **NO**.
- Historical artifacts changed: **NO**.
- `TASKS.md` created: **NO**.
- Production code changed: **NO**.

## Inconsistencies remaining

None remain among the corrected normative documents. The implementation/design
documentation, Skills, Controller, and tests identified in the impact analysis
still describe or implement their current contracts and were intentionally not
changed in this correction scope.

## Recommendation for next correction stage

Apply the separately scoped implementation/design correction from the impact
analysis: update the bootstrap coordinator documentation and affected Skills,
then implement and test active hash-bound approval lineage and recovery guards.
After that work is validated, perform only a read-only Wave 3 reconciliation
before any Controller-mediated continuation.
