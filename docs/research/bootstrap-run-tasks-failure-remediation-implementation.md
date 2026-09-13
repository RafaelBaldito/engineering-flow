# Bootstrap `run-tasks` failure remediation implementation

## Scope and files changed

Implemented the approved narrow bootstrap correction in:

- `.codex/skills/execute-task/SKILL.md`
- `.codex/skills/review-task/SKILL.md`
- `.codex/skills/fix-task/SKILL.md`
- `tools/wave_controller/core.py`
- `tools/wave_controller/cli.py`
- `tools/wave_controller/host.py`
- `tests/bootstrap/test_wave_controller.py`
- `tests/bootstrap/test_wave_controller_host.py`

## Authority boundary

For Controller-managed work, `TASKS.md` and `TASK-*.md` are immutable approved
planning inputs. Developer, Reviewer, and Fixer instructions no longer permit
task-index/status-cell edits. The Controller alone owns runtime progression and
acceptance; a Reviewer still writes its authorized review artifact. The Host
repeats this bounded prohibition in every role prompt.

## Interrupted Developer recovery contract

`recover-interrupted-developer` accepts only an exact active Developer lease,
the exact task ID, `REVIEW_CANDIDATE` disposition, actor, and captured checkout
fingerprint. It revalidates the approved registered task plan and rejects plan
drift, role/task/operation/fingerprint mismatches, an existing result envelope,
and contradictory recovery history. It appends a durable receipt, clears only
the matching lease, leaves the task `PENDING`, and routes only to
`TASK_REVIEW_REQUIRED`. Repeating the same operation/candidate request is
idempotent. The command makes no inference from workspace content or tests.

## Host failure and observability behavior

Ordinary child failures, timeouts, and caught runner exceptions create a
deterministic interrupted outcome through normal Controller completion when
authoritative inputs remain valid, so a valid lease is not silently stranded.
If an authoritative input hash is invalid, the Host emits only a concise
`AUTHORITATIVE_INPUT_INVALID` stop event, creates no envelope, dispatches no
further role, and leaves explicit recovery to the command above.

`run-tasks` writes flushed newline-delimited safe Host events: `task_started`,
`role_dispatched`, periodic `heartbeat`, `role_completed`, `review_result`,
`fix_cycle`, `task_accepted`, and `run_stopped`. Events contain only safe
operational metadata. Provider JSONL, child output/stderr, prompts, reasoning,
and secrets remain internal and are never streamed. Wave Review remains outside
the task loop.

## Tests added

The isolated bootstrap fixtures cover prompt prohibition, immutable-plan bytes
through the Developer/Reviewer/Fixer lifecycle, authoritative-plan drift,
nonzero/timeout/host-error cleanup, exact recovery and rejection/idempotency,
pending recovery routing to an independent Reviewer, Controller-only task
acceptance, safe event ordering/no raw output leakage, fix-cycle events, and
the no-Wave-Review boundary.

## Validation

- Focused bootstrap tests: `.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller tests.bootstrap.test_wave_controller_host -q` — PASS (61 tests).
- Full suite: `.venv/bin/python3 -m unittest discover -s tests -q` — PASS (103 tests).
- `git diff --check` — PASS.

The live Wave 3 incident files and preserved TASK-001 candidate were not
modified. In particular, this remediation did not edit the live control state,
Wave 3 task plan/task files, or the listed domain/store source and tests.

## Readiness verdict

READY_FOR_LIVE_RECOVERY
