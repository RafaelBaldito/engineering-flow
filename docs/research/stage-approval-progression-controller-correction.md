# Stage-Approval Progression Controller Correction

## Result

PASS. This bootstrap-only correction implements active, exact approval lineage
for canonical successors without changing the product runtime or Wave 3.

## Files changed

- `tools/wave_controller/core.py`
- `tools/wave_controller/cli.py`
- `tests/bootstrap/test_wave_controller.py`
- this report

## Governance operations

The public CLI now has typed `approve`, `authorize`, `revoke`, and
`supersede` operations. `record-authority` remains a compatibility shim only;
it is no longer the sole public semantic contract. `AUTHORIZE` is restricted
to Wave start. `APPROVE` is restricted to the two canonical artifact gates.

The control record has an append-only `governance_decisions` list. Decisions
carry deterministic identity, operation, gate, Wave, actor, exact evidence,
and (for revocation/supersession) target identity. Existing schema-v1
human-gate records remain read-compatible as one legacy approval fact.

## Guards and lineage

An active approval resolver requires exactly one non-revoked,
non-superseded `APPROVE` for the correct gate and Wave, and requires one exact
reference to the canonical artifact path with its current SHA-256. Multiple
active candidates, malformed supersession, wrong path/scope, absent artifact,
or changed bytes fail closed.

- `next` validates TECHSPEC approval before Planner exposure and task-plan
  approval before Developer exposure.
- `begin-operation` repeats that validation immediately before persisting a
  Planner or Developer writer lease; a prior proposal is not authority.
- `register-tasks` validates the active exact task-plan approval before import.
- `reconcile` obtains its dependent action through the same validation path,
  so fresh hosts derive the same lineage and cannot revive invalid authority.

There is no `TASK-PLANNING-AUTHORIZATION` check and no separate execution
authorization. Wave-start authorization remains distinct. Wave acceptance has
no next-Wave transition, and delivery authorization behavior is unchanged.

## Revocation and supersession

Revocation appends historical evidence and removes only future reliance on its
target. It does not delete plans, registrations, task evidence, or results.
If invalid authority is encountered after dependent work exists, dispatch
stops in `HUMAN_ATTENTION`; no rollback is inferred.

Supersession appends a replacement exact approval and marks its target
historical. Only the replacement is usable. Missing/malformed or ambiguous
lineage routes to `HUMAN_ATTENTION`. Repeating the same typed operation is
idempotent, as are `next`, registration, recovery, and writer-lease rejection.

## Focused tests

The bootstrap suite now covers canonical TECHSPEC approval without planning
authorization; missing, wrong-path, wrong-scope, stale, revoked, and
superseded TECHSPEC authority; acquisition race revalidation; exact task-plan
approval for registration and Developer dispatch; revocation after registered
task evidence; fresh-controller recovery; Wave-start distinction; and typed
operation idempotency. Existing lease, registration, recovery, approval,
delivery-boundary, and Wave-acceptance tests remain in place.

Focused result: `.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller -q` — PASS (40 tests).

Full result: `.venv/bin/python3 -m unittest discover -s tests -q` — PASS (101 tests).

## Scope confirmation

- TASK-PLANNING-AUTHORIZATION dependency remaining: **NO**
- Separate execution authorization dependency remaining: **NO**
- Wave 3 TECHSPEC changed: **NO**
- Wave 3 state changed: **NO**
- `TASKS.md` created: **NO**
- Production runtime changed: **NO**

## Unresolved risks and recommendation

This is intentionally a compact bootstrap lineage model, not a general
governance engine. It supports deterministic one-replacement supersession and
fails closed on ambiguity. Continue Wave 3 only through a read-only Controller
reconcile followed by normal Controller dispatch; do not hand-edit state.
