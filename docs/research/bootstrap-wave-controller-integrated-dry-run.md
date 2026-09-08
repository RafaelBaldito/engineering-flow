# Bootstrap Wave Controller integrated dry-run

## Purpose

Validate the implemented bootstrap Controller against the live Codex Host and
real role subagents, using only disposable repositories. This is integration
validation, not a Wave 3 start or product change.

## Scope / non-goals

The experiment covered Controller CLI dispatch, lease acquisition, real
Developer execution, result submission, a fresh Reviewer dispatch, a human
gate, and the checkout/artifact boundary. It did not alter any production
Wave, `src/engineering_flow/`, Skills, architecture, approvals, or existing
workflow artifacts. It stopped on two deterministic Controller defects; it
did not bypass them by editing a state record or forcing later transitions.

## Environment

- Linux/WSL checkout; `./scripts/env-preflight` reported Python 3.13.15,
  editable package, CLI available, and a clean production checkout at start.
- Controller invocation used
  `PYTHONPATH=/home/bal/projects/engineering-flow .venv/bin/python3 -m tools.wave_controller.cli --root <fixture> --wave integration <command>`.
- Controller handoffs requested `Terra` / `medium` for Developer and `Terra`
  / `high` for Reviewer. The collaboration runtime did not expose a literal
  `Terra` model selector; both real children ran with requested `medium`
  reasoning. Observed dispatch is therefore **FALLBACK**, not a model-tier
  validation.

## Disposable fixture

The primary disposable root was
`/tmp/bootstrap-wave-controller-integrated.KSHvSI` (fixture repositories:
`fixture`, `passflow`, and `human-gate`). It contained a trivial
`normalizer.py`, three unit tests, a tiny normalization specification, and two
approved fixture task files. All fixture control records were written by the
Controller initialization API into that disposable root only.

## Controller invocation

`next` from an initialized `TASK_EXECUTION_REQUIRED` fixture returned a
structured Developer handoff: role `Developer`, capability
`task-implementation`, Skill `execute-task`, task `TASK-PASS`, a checkout
fingerprint, `fork_turns: none`, and medium reasoning metadata. `begin-operation
--operation-id pass-dev` returned `ACQUIRED`.

## Developer dispatch

A real fresh Developer child used the existing `execute-task` Skill contract
and implemented `normalise` with a type guard and
`" ".join(value.split()).lower()`. It ran
`python3 -m unittest discover -s tests -q`; 3 tests passed. Its final changed
path was only `normalizer.py` (apart from the Controller state file).

While that operation was active, a second Controller acquisition returned
`{"status":"REJECT","reason":"known active writer"}`. No concurrent
writer was dispatched.

### Blocking lifecycle finding: selected task is not persisted

The first ordinary task dispatch exposed a concrete defect. `next()` selected
`TASK-PASS` in its returned handoff, but did not persist `current_task_id`.
`begin-operation()` then reloaded the state and persisted an active operation
with `task_id: null`. The Host submitted an otherwise valid Developer envelope
scoped to the Controller handoff's `TASK-PASS`; `complete-operation` returned
`HUMAN_ATTENTION` with `invalid result envelope: envelope scope does not
match`. This is a Controller authority/lifecycle defect, not a child failure.

A separately initialized fixture with `current_task_id: TASK-PASS` was used
only to continue probing the reviewer runtime boundary; this was fixture setup
through the Controller API, not a state edit to advance the failed scenario.
There a second real Developer completed and the Controller accepted its
envelope, reaching `TASK_REVIEW_REQUIRED`.

## Reviewer isolation

The Reviewer was dispatched as a new child with `fork_turns="none"` and a
factual handoff limited to task/spec paths, changed path, validation command,
checkout, role, and required artifact path. It returned `PASS` and created
only `tasks/integration/reviews/TASK-PASS-REVIEW.md`; `normalizer.py` and the
tests were unchanged across review.

The first marker probe was invalid: the Host accidentally included the literal
marker in the question asking whether it was visible, and the Reviewer
truthfully answered visible. It is not evidence of parent-context leakage.
Because the lifecycle defect had already blocked authoritative continuation,
no second clean marker probe was run. Reviewer parent-marker isolation is
therefore **FAIL (not validly demonstrated)**, not a claim of runtime leakage.

## Reviewer artifact allowance

Reviewer write restraint behavior was observed: the only reviewer-created
path was the required task-review artifact. However the Controller cannot
safely distinguish that allowed mutation from a material implementation
mutation. `_validate_envelope` only requires that the submitted whole-checkout
output fingerprint equal the current fingerprint and that listed artifacts
hash correctly. It has no deterministic allowed-path/diff policy and no
comparison of changed implementation paths. Thus the same mechanism would
accept an envelope whose output includes both the review artifact and a source
edit. Classification: **NEEDS_CONTROLLER_FIX**.

## PASS path

Developer execution and transition to `TASK_REVIEW_REQUIRED` passed only in
the separately initialized probe scenario. The first normal Controller path
could not accept its task-scoped Developer result because of the persisted
task-ID defect. A valid Controller-accepted task-review PASS and task
acceptance were not reached; no claim of PASS-path success is made.

## FIX_REQUIRED path

Not exercised. The mandatory task loop was not safely reachable after the
normal lifecycle defect, and the experiment did not manually force state.

## Stale result test

Not exercised end-to-end in this run. The existing focused tests cover stale
rejection, but they are not substituted for this integration requirement.

## Single-writer test

PASS. A second `begin-operation` during the real Developer operation returned
`REJECT` before any second child was dispatched.

## Fresh-host recovery

Not exercised after a durable valid transition because the authoritative normal
path entered `HUMAN_ATTENTION` on the task-ID defect. No state was manually
repaired.

## Human gate

PASS. An independent disposable fixture initialized at `WAVE_AUTHORIZED`
returned `{"status":"HUMAN_ACTION","gate":"WAVE_START_AUTHORIZATION"}`
from `next`; the Host stopped. The current CLI exposes no action to persist a
human authorization/approval, so no gate was crossed by inference.

## Wave Reviewer

Not reached. No Wave review, Wave remediation, next Wave, or release lifecycle
was started.

## Model/reasoning dispatch

Requested: Developer `Terra`/medium; Reviewer `Terra`/high. Observed: real
children accepted `medium` reasoning, while the runtime interface did not
provide the requested `Terra` selector. Classification: **FALLBACK**.

## Failures / blockers

1. `begin-operation` loses the task selected by `next`, producing a null active
   task ID and rejecting the Controller's own task-scoped handoff result.
2. The Controller has no deterministic artifact-only checkout rule; a Review
   artifact can be hash-validated, but material code drift in the same output
   identity is not rejected.
3. The CLI has no explicit human-approval persistence command. It correctly
   stops at the gate, but full approved lifecycle continuation cannot be driven
   through the public Controller interface.

## Remaining risks

Mandatory integration coverage remains incomplete: clean parent-only marker
probe, FIX_REQUIRED -> Fixer -> fresh Reviewer loop, stale envelope rejection,
fresh-host recovery, and Wave Reviewer/WAVE_ACCEPTED. The incomplete coverage
is intentional after authoritative Controller defects, not a manual state
bypass.

## Recommendation

NEEDS_CONTROLLER_FIX
