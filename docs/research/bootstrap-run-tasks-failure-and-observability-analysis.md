# Bootstrap `run-tasks` failure and observability analysis

## Verdict

**FIX_NOW.** Do not resume `run-tasks` or manually alter the current Controller
state until the narrow bootstrap correction and the explicit recovery path below
exist. This is a bootstrap host/Skill contract failure, not a Wave 3 TECHSPEC or
approved task-plan semantic change. The current TASK-001 work is recoverable as
a **candidate for independent review**, without rerunning Developer, after the
approved plan is restored and the Controller records that explicit recovery.

## Evidence inspected

- Checkout readiness and worktree state: `./scripts/env-preflight` reported
  Python 3.13.15 and the six dirty paths stated in the incident. HEAD is
  `5db661a docs: checkpoint approved Wave 3 task plan`.
- The approved HEAD version of
  `tasks/3-workflow-capability-orchestration/TASKS.md` has SHA-256
  `a686ff9aa5bb60d7e6106d8c8579e711c835d12754f76c4e979344b1e68202e8`.
  The working copy has SHA-256
  `40428d8d339eaaad9a4b722f592df6d8e8a5ac8b21032fe4fc4eadd40ca3963c`.
  Its only difference is TASK-001's status cell, `PENDING` to `IMPLEMENTED`.
- The Controller record registers that former digest as both the task-plan
  approval evidence and `task_plan.sha256`. It has
  `lifecycle_state: TASK_IMPLEMENTATION`, `current_task_id: TASK-001`, a
  Developer active operation `1029fde3-e672-480c-b30e-be4cbbe28e48` dispatched
  at `2026-09-13T18:53:52.722405Z`, all seven runtime task entries `PENDING`,
  no matching Developer result envelope, and zero task attempts. Its last
  completed transition is `BEGIN:1029...`.
- No `codex exec` or `wave-controller ... run-tasks` process was present at
  inspection. The Host's temporary final-message and JSONL files are removed
  by `TemporaryDirectory`, so there is no durable child exit/final-message
  evidence from this invocation.
- Reviewed `tools/wave_controller/core.py`, `host.py`, and `cli.py`, their
  bootstrap tests, the prior task-status reconciliation analysis, and the
  Developer/Reviewer/Fixer Skills.
- Reviewed TASK-001, Wave 3 TECHSPEC §§3, 5, 7, and 9, and the dirty source and
  test diff. The dirty implementation is confined to TASK-001's expected
  `domain.py`, `store.py`, `test_domain.py`, and `test_store.py` areas.
- Read-only validation of that candidate work passed:

  - `.venv/bin/python3 -m unittest discover -s tests -p 'test_domain.py' -q` —
    2 tests, PASS.
  - `.venv/bin/python3 -m unittest discover -s tests -p 'test_store.py' -q` —
    8 tests, PASS.
  - `.venv/bin/python3 -m compileall -q src` — PASS.
  - `git diff --check` — PASS.

## Root causes

### 1. The dispatched Developer was instructed to mutate the approved task plan

`host.build_prompt()` explicitly selected the repository `execute-task` Skill.
That Skill instructed the Developer that a selected task/index status may be
updated, then recommended `IMPLEMENTED` on successful execution (notably its
workflow step 12 and completion section). It also permitted an exception for
status metadata while otherwise calling planning artifacts immutable.

The observed one-line edit is exactly that prescribed `IMPLEMENTED` update.
No Controller code writes `TASKS.md`: the Controller only parses and hashes it.
Accordingly, the immediate writer was the Developer child process, acting on an
internally contradictory generic Skill contract. The Host prompt did not state
the Wave-controller exception or prohibit that edit.

The same incompatible status-update instruction remains in `review-task` and
`fix-task`. Without correcting all three, the same corruption would recur at
review or a fix cycle.

### 2. Two separate state models were in conflict

The Controller's existing model is correct: registration parses a plan whose
initial cells must all be `PENDING`; runtime task records live in the
Controller. Developer completion intentionally leaves the selected runtime
task `PENDING`; only a validated Reviewer `PASS` atomically writes runtime
`status: PASS` and an `accepted_review` receipt. The existing reconciliation
design also expressly says the plan remains the immutable `PENDING`
registration input.

The generic Skills treated the planning table as a mutable progress index.
Thus the Developer changed a second, unauthorized progress representation,
while the Controller correctly did not change its own runtime status. The
runtime `PENDING` entries are not evidence that Developer failed; they are the
specified pre-review state.

### 3. The mutation stranded the durable active operation

`begin_operation()` persistently acquires the Developer lease before the Host
starts the child. That is intentional and necessary for a sole-writer lease.
After `runner()` returns, however, `run_task_loop()` calls `build_envelope()`;
its first substantive operation is `controller.load()`. `load()` verifies all
authoritative hashes, including the approved task-plan digest. The Developer's
edit therefore makes envelope construction raise `ControllerError` before
`complete_operation()` can clear the lease or record an interrupted outcome.
`run_task_loop()` has no exception/finally boundary around runner/envelope/
completion, and the CLI prints only after the loop returns.

This is the deterministic host failure path if the child returned normally.
Because the child transcript/final message was not retained, the available
evidence cannot prove the exact child terminal event or exclude a separate
outer-process termination. Either way, the durable result is the same: a
known active Developer lease with no Controller-accepted outcome. `reconcile()`
correctly refuses to guess such an outcome and returns blocked.

### 4. The Host deliberately buffered all useful progress output

`run_codex()` uses `Popen(..., stdout=PIPE, stderr=PIPE)` followed by one
`communicate(timeout=...)`, then parses the accumulated JSONL only after exit.
The command-line entry point emits one final JSON object only after
`run_task_loop()` returns. It exposes neither dispatch nor completion timing,
and it cannot emit a heartbeat while blocked in `communicate()`. This explains
the absence of incremental terminal output.

## Authority-boundary violation

`TASKS.md` is an approved, hash-bound planning input. Its task identities,
order, dependencies, and initial `PENDING` cells are the plan approved by the
human; they are not a runtime journal. Allowing Developer, Reviewer, or Fixer
to change even a status cell changes the approved artifact and invalidates the
approval binding. It also lets a provider write workflow progress outside the
Controller, contrary to the Controller's sole-writer contract.

The durable source of truth is therefore:

| Fact | Authority | Location |
| --- | --- | --- |
| Planned task identity, order, dependencies, initial state | Approved plan | Immutable `TASKS.md`, SHA-bound in approval/registration |
| Selected task, active role lease, attempts, implementation/review/fix routing, task acceptance | Controller | `WAVE-WORKFLOW-STATE.md` and Controller transitions/receipts |
| Implementation and validation observations | Developer/Fixer evidence | Workspace and bounded result evidence; never an advancement instruction |
| Task acceptance | Controller after validating a Reviewer `PASS` envelope | Runtime task record plus `accepted_review` receipt |

Workspace contents, a changed status cell, a review file by itself, or a
provider's completion prose must never advance or accept work.

## Interrupted-operation diagnosis and TASK-001 recoverability

TASK-001 is **not completed, not accepted, and not safe to redispatch as if no
work happened**. There is no durable Developer envelope and no independent
review. The candidate changes are nevertheless recoverable without rerunning
Developer because all of the following are true:

- the active lease identifies exactly TASK-001 and a known Developer role;
- the only planning-file damage is reversible metadata, while the four source/
  test changes are separate and match the task's expected files;
- the task's three required checks and diff hygiene pass; and
- no child process remains that could race recovery.

That establishes a reviewable candidate, not a trusted execution result. A
Reviewer must still independently validate the complete TASK-001 contract and
may return `FIX_REQUIRED`, `BLOCKED`, or `SPEC_CHANGE_REQUIRED`. A reviewer
`PASS`, accepted by the Controller, remains the only way to mark TASK-001
accepted or unlock TASK-002/TASK-003.

## Proposed safe recovery protocol

Implement the following Controller-owned, explicit recovery operation before
touching this live state. It is intentionally narrower than a general resume
or automatic reconciliation feature.

1. Preserve the current source/test candidate unchanged. Restore only
   `tasks/3-workflow-capability-orchestration/TASKS.md` to its approved
   `5db661a` bytes, then verify the registered and approval SHA-256 exactly
   match. This repairs the invalid input without discarding TASK-001 work.
2. Invoke a new explicit Controller command such as
   `recover-interrupted-developer --operation-id 1029... --task TASK-001
   --mode review-candidate --actor <actor> --checkout-fingerprint <current>`.
   It is permitted only when: the restored plan validates; the active lease is
   exactly that known Developer/task; no matching result envelope exists; and
   the supplied fingerprint matches the checkout captured by the command.
3. In one Controller write, append a recovery receipt containing the prior
   operation ID, task, actor, old input identity, captured candidate identity,
   timestamp, and disposition `REVIEW_CANDIDATE`; clear `active_operation`;
   retain task runtime status `PENDING`; and transition only to
   `TASK_REVIEW_REQUIRED`. This is an explicit operator routing decision, not
   an inference from files or test success.
4. Make it idempotent for the same prior operation ID and candidate fingerprint.
   A different fingerprint, different task/role, existing result envelope,
   invalid plan hash, unknown role, or contradictory prior receipt must reject
   and leave the Controller fail-closed (or enter `HUMAN_ATTENTION` where that
   is the established Controller behavior).
5. Dispatch a fresh independent Reviewer. The normal Controller validation and
   Reviewer result decide the task. Wave Review remains outside `run-tasks`.

For an interrupted operation whose candidate is not explicitly elected for
review, recovery must instead record `ABANDONED`/human attention and require a
separate explicit disposition of the workspace before a fresh Developer lease.
It must not silently clear the lease and redispatch over unknown work.

The Host should additionally catch ordinary runner/envelope exceptions after a
lease is acquired and submit a synthetic interrupted outcome when the
Controller can still validate its inputs. If it cannot load a valid Controller
because an authoritative input changed, it must emit a concise fail-closed
fatal event and leave recovery to the explicit command above. No code can
durably clean up after `SIGKILL`; that is why this explicit recovery operation
is required.

## Minimal correction plan

1. **Skills and bounded prompt.** Remove the task-index status-update steps,
   output allowances, and `IMPLEMENTED`/`PASS` recommendations from
   `execute-task`, `review-task`, and `fix-task` for this Controller-managed
   flow. State unambiguously that `TASKS.md` and `TASK-*.md` are immutable
   approved inputs and runtime progress is Controller-owned. Add the same
   explicit prohibition to the Host's factual role prompt. The reviewer still
   writes only its authorized review artifact.
2. **Controller recovery.** Add the one explicit, hash/fingerprint-bound
   interrupted-Developer-to-review-candidate transition and durable recovery
   receipt described above. Do not generalize it to planner, Wave review, or
   unknown active writers.
3. **Host fail-closed behavior.** Wrap the acquired-operation execution path
   so ordinary failures produce a deterministic interrupted result when
   possible. Detect authoritative-input drift before envelope construction,
   emit a diagnostic event without raw child content, and do not continue the
   loop. Preserve the existing no-Wave-Review boundary.
4. **Host observability.** Replace the fully blocking child-output wait with
   streamed/drained child pipes plus a timer. Retain and parse JSONL internally,
   but never relay provider event payloads, reasoning, token streams, prompts,
   or stderr verbatim.

The Skill/prompt fix prevents this normal mutation path. The hash guard remains
the defense-in-depth detection boundary; it must fail closed if any provider or
external writer still changes an approved input. Strong OS-level per-file
write isolation is not necessary for this minimal bootstrap correction and
would expand the bootstrap surface.

## Proposed `run-tasks` observability behavior

Emit small, structured, newline-delimited Host events to stdout with
`flush=True`; retain one structured final result. Each event includes only a
timestamp, wave ID, task ID when present, role, operation ID, elapsed seconds
where meaningful, and a safe outcome/reason code.

- `task_started` after the Controller selects/acquires a task.
- `role_dispatched` immediately before each Developer, Reviewer, or Fixer
  child starts.
- `heartbeat` every fixed interval (for example 30 seconds) while that child
  is alive, containing role/task/operation and elapsed time only.
- `role_completed` immediately after child termination, including elapsed
  time and safe exit/timeout/result classification.
- `review_result` after a Reviewer result is read and Controller completion is
  attempted, carrying only `PASS`, `FIX_REQUIRED`, `BLOCKED`, or
  `SPEC_CHANGE_REQUIRED` and the Controller outcome.
- `fix_cycle` when `FIX_REQUIRED` routes to Fixer and when that cycle returns
  to review.
- `task_accepted` only after the Controller accepts a Reviewer `PASS`; never
  after Developer/Fixer completion.
- `run_stopped` for human attention, invalid authoritative input, interruption,
  or `TASKS_READY_FOR_WAVE_REVIEW`.

This offers an operator a useful liveness signal without exposing hidden
reasoning or making raw provider output part of the workflow authority.

## Exact implementation scope

- `tools/wave_controller/core.py`: one narrow recovered-interrupted-Developer
  command/transition, receipt validation, and idempotency rules.
- `tools/wave_controller/cli.py`: expose only that explicit command and its
  bounded identifiers/actor/mode/fingerprint parameters.
- `tools/wave_controller/host.py`: prompt prohibition, streamed safe progress
  events/heartbeats/flush, and ordinary-exception cleanup/fail-closed handling.
- `tests/bootstrap/test_wave_controller.py` and
  `tests/bootstrap/test_wave_controller_host.py`: focused Controller, host,
  recovery, and observability tests.
- `.codex/skills/execute-task/SKILL.md`, `review-task/SKILL.md`, and
  `fix-task/SKILL.md`: remove plan-status mutation instructions for this
  Controller-owned workflow.
- A follow-up bootstrap research/remediation record may document the live
  recovery. It is not a task-plan amendment or an implementation acceptance.

## Tests required

- A Developer, Reviewer, and Fixer handoff each state that the approved plan
  is immutable and contain no permission/recommendation to edit task-index
  status.
- Registered plans remain byte-identical through Developer completion,
  `FIX_REQUIRED`, Fixer completion, Reviewer `PASS`, reconciliation, and Wave
  Review handoff; runtime state is the sole progress projection.
- A child-created task-plan hash mismatch is reported fail-closed and cannot
  create an envelope, accept a task, or dispatch another role.
- Ordinary child nonzero exit, timeout, and host-side exception clear a valid
  active lease into deterministic interrupted/human-attention state; unknown
  or invalid Controller inputs are not guessed.
- Interrupted-Developer recovery accepts only the exact known lease and
  restored plan; preserves `PENDING`; emits one receipt; routes to review only
  with explicit operator choice; rejects mismatched operation/task/fingerprint
  and existing/ambiguous results; and is idempotent.
- A recovered review candidate receives a normal independent Reviewer result:
  only Controller-accepted `PASS` creates `accepted_review` and unlocks
  dependencies.
- Fake long-running child tests verify event ordering, heartbeat cadence,
  elapsed times, immediate flushing, omission of raw child stdout/stderr, fix
  cycle reporting, task acceptance reporting, and no Wave Reviewer dispatch.
- Run the two bootstrap test modules, TASK-001's three required checks, then
  the repository full suite:
  `.venv/bin/python3 -m unittest discover -s tests -q`.

## Explicit non-goals

- No change to Wave 3 product requirements, TECHSPEC, approved task-plan
  scope, task identities/dependencies, or planning approval semantics.
- No acceptance inferred from source diffs, test success, an `IMPLEMENTED`
  label, a review file alone, or provider prose.
- No automatic recovery of unknown active operations and no automatic replay
  of Developer work.
- No migration of this bootstrap Controller into the production Wave 3
  runtime/store.
- No provider-session resume, transcript persistence, raw model-token display,
  hidden-reasoning exposure, or new Git/hosting side effect.
- No automated Wave Review or expansion of `run-tasks` beyond the existing
  Developer → Reviewer → Fixer/re-review loop.

## Final conclusion

The bootstrap should be fixed now, then TASK-001 should be recovered through
the explicit review-candidate protocol. The approved `TASKS.md` is restored
exactly; its `PENDING` cells remain planning facts. The Controller records the
interruption and only an independent Reviewer `PASS` can accept the preserved
candidate. This both preserves the valuable existing work and restores the
authority boundary needed to safely continue Wave 3.
