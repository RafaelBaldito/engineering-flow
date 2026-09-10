# Bootstrap Supervised Capability Completion Correction

## Result

**READY_FOR_WAVE_3_RESUME**

## Root cause

Wave 3 was correctly persisted in `TASK_PLAN_REQUIRED` after an exact,
historical `TECHSPEC_APPROVAL` by `Human`.  The supervised, manually run
`create-tasks` capability wrote the canonical task plan outside the Controller,
so it never acquired a Planner lease or submitted a completion envelope.  The
normal transitions `TASK_PLAN_REQUIRED -> TASK_PLAN_EXECUTION ->
AWAITING_TASK_PLAN_APPROVAL` therefore never occurred.

`approve_pending_human_gate()` only had TECHSPEC-recovery logic at
`TASK_PLAN_REQUIRED`.  An attempt to submit Rafael Alves's later task-plan
approval there compared that new actor with the old TECHSPEC approver and
rejected it.  The historical TECHSPEC decision is valid and was not changed.

## Correction

The Controller now exposes the narrow
`report_supervised_capability_completion()` operation, with a Host adapter and
the public CLI command:

```text
wave-controller --wave <wave-id> report-supervised-completion
```

It has no caller-selected lifecycle state, capability, artifact path, or hash.
It is accepted only when the current state is `TASK_PLAN_REQUIRED`, there is no
active operation, and the active exact TECHSPEC approval remains valid.  Its
only supported capability is the current dispatch mapping:

```text
Planner / task-decomposition / create-tasks
```

The Controller validates exactly `tasks/<wave-id>/TASKS.md`: it must exist and
parse as the canonical Execution Order task plan.  It atomically persists a
Controller-owned supervised-completion receipt containing the fixed capability
identity and artifact hash, then transitions to
`AWAITING_TASK_PLAN_APPROVAL` and opens `TASK_PLAN_APPROVAL`.  A repeated report
is idempotent only when that persisted canonical artifact still matches; missing
or changed bytes fail closed.

Artifact existence by itself is still insufficient.  `next()` continues to
offer Planner work at `TASK_PLAN_REQUIRED` even if a file exists.  Only the
explicit supervised Host/operator report is allowed to assert that the known
current capability completed.  The later human approval remains separately
recorded against the exact current `TASKS.md` hash, preserving hash-bound
governance.

The `TASK_PLAN_REQUIRED` recovery branch still supports an idempotent replay of
the persisted TECHSPEC approval by its recorded actor.  A different actor is
now rejected with the state-correct instruction to report task-plan completion
first, rather than treating that later approval as TECHSPEC recovery.  After
the report, `approve-pending --actor "Rafael Alves"` records the distinct
`TASK_PLAN_APPROVAL` and uses the existing registration path.

## Wave 3 compatibility and safety

This is compatible with the current Wave 3 record: no state file, TECHSPEC, or
task-plan file was manually edited.  The intended recovery is to invoke the
new report command against the existing `TASK_PLAN_REQUIRED` record, then hand
off the already explicit human task-plan approval through `approve-pending`.
The Controller remains the sole control-record and lifecycle writer.

No real Wave 3 task was registered, selected, acquired, dispatched, or
executed during this correction.  The existing untracked Wave 3 task artifacts
were not modified.

## Validation

Focused bootstrap tests:

```text
.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller tests.bootstrap.test_wave_controller_host -q
Ran 54 tests in 7.015s
OK
```

The focused cases cover TECHSPEC recovery/idempotency, no transition from
`TASKS.md` alone, supervised Planner completion and repeat idempotency, a
different task-plan approval actor, missing/malformed/drifted artifacts,
absence of Developer acquisition/dispatch, the public CLI/Host adapters, and
the unchanged automated Planner completion path.

Full suite:

```text
.venv/bin/python3 -m unittest discover -s tests -q
Ran 101 tests in 8.891s
OK
```
