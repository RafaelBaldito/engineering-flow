# Bootstrap Human-Approval Handoff Implementation

## Result

**READY_FOR_WAVE_3_RESUME**

Implemented the narrow bootstrap human-approval handoff specified by
`bootstrap-human-approval-handoff-analysis.md`. The implementation changes
only the bootstrap Wave Controller, its Host adapter and CLI, plus focused
bootstrap tests. It does not modify product runtime code, Skills, or any Wave
3 TECHSPEC/task artifact.

## Files changed

- `tools/wave_controller/core.py`
- `tools/wave_controller/host.py`
- `tools/wave_controller/cli.py`
- `tests/bootstrap/test_wave_controller.py`
- `tests/bootstrap/test_wave_controller_host.py`

## Implemented flow

`Controller.approve_pending_human_gate(actor)` accepts only an actor. It
derives the current supported open gate from the persisted lifecycle and maps
it through the Controller allowlist; callers cannot supply a gate, artifact
path, SHA-256 digest, or authority wave.

- For `TECHSPEC_APPROVAL`, it records the normal append-only approval decision
  and uses the existing lifecycle progression to reach `TASK_PLAN_REQUIRED`.
  It does not acquire an operation or dispatch Planner work.
- For `TASK_PLAN_APPROVAL`, it records the normal approval decision, retains
  the existing direct move to `TASK_EXECUTION_REQUIRED`, then invokes the
  existing independent `register_tasks()` importer. Registration remains a
  separate durable write and does not select, acquire, or dispatch a
  Developer.

The Host supplies `approve_confirmed_human_gate(controller, actor)`, a small
adapter intended only for a previously presented, unambiguous affirmative
human response. It retains no separate approval state and performs no prose
interpretation. `run_task_loop` remains limited to Developer, Reviewer, and
Fixer roles.

The supervised recovery CLI is available as:

```text
.venv/bin/python3 -m tools.wave_controller.cli --root <repo> --wave <wave> approve-pending --actor <actor>
```

It has no gate, evidence, artifact, digest, or authority-wave argument. The
existing generic governance CLI commands are unchanged.

## Evidence and recovery behavior

The Controller resolves only `docs/waves/<wave>/TECHSPEC.md` or
`tasks/<wave>/TASKS.md`, requires a regular file, and calculates its SHA-256
itself. It creates exactly one normal authoritative reference with
`human-approved <gate>` as non-authoritative purpose metadata. Existing
reference validation and active-lineage checks continue to rehash artifacts
when authority is used, so drift fails closed.

Repeated calls with the same recorded actor converge idempotently. A retry
after TECHSPEC approval returns the already-reached successor. A retry after
task-plan approval reruns only the idempotent task importer, repairing an
interruption after approval persistence and before registration. Drift,
missing/invalid artifacts, invalid lifecycle, revoked or ambiguous lineage,
and a different recovery actor fail without creating a new approval decision
or dispatching work.

## Validation

- Focused bootstrap tests:
  `.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller tests.bootstrap.test_wave_controller_host -q`
  — **PASS** (`Ran 50 tests ... OK`)
- Full suite:
  `.venv/bin/python3 -m unittest discover -s tests -q`
  — **PASS** (`Ran 101 tests ... OK`)
- `git diff --check` — **PASS**

## Wave 3 safety confirmation

No real Wave 3 task was registered or executed. The live Wave 3 Controller
was read only after validation and reported `TASK_PLAN_REQUIRED` with no
active operation. No Wave 3 TECHSPEC, `TASKS.md`, task file, or control record
was modified.

## Remaining limitation

There is no broader persisted conversational-session orchestrator in this
repository. The new Host adapter is the intended call-site integration point:
a conversation-facing Host must call it only after presenting a known pending
approval request and receiving a later explicit affirmative response.
