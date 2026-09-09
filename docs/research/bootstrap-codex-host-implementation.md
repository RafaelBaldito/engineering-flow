# Bootstrap Codex Host Implementation

## Result

GO_WITH_LIMITS. The bounded bootstrap Codex host implementation is complete and the required disposable end-to-end validation subsequently completed successfully.

The live run proved the intended post-task-plan lifecycle with fresh Codex executions: Task A completed Developer → Reviewer → PASS; Task B completed Developer → Reviewer → FIX_REQUIRED → Fixer → fresh Reviewer → PASS; the Controller then stopped at TASKS_READY_FOR_WAVE_REVIEW without dispatching Wave Review.

The bootstrap remains intentionally limited to task execution/review/fix automation. Wave Review, planning stages, delivery, provider abstraction, session orchestration, and production Engineering Flow runtime integration remain outside this bootstrap scope.

## Files changed

- `tools/wave_controller/host.py`
- `tools/wave_controller/cli.py`
- `tools/wave_controller/core.py`
- `tests/bootstrap/test_wave_controller.py`
- `tests/bootstrap/test_wave_controller_host.py`
- this report

`docs/research/python-codex-execution-bridge-spike.md` was already untracked before this work and was not modified.

## Host and dispatcher

`tools/wave_controller/host.py` is the single small host module. `run_task_loop` is the bounded dispatcher, exposed as `python -m tools.wave_controller.cli --root <repo> --wave <id> run-tasks`.

Role policy is centralized in `ROLE_POLICIES`:

- Developer: `gpt-5.6-terra`, `low`, fresh `codex exec`, `workspace-write`.
- Reviewer: `gpt-5.6-terra`, `medium`, fresh `codex exec`, `workspace-write` subject to the existing Controller exact-artifact contract.
- Fixer: `gpt-5.6-terra`, `low`, fresh `codex exec`, `workspace-write`.

Every invocation has the shape `codex exec --json --strict-config -m gpt-5.6-terra -c model_reasoning_effort=... -C <repo> -s workspace-write --output-last-message <temporary-file> --output-schema <temporary-schema> <small-factual-prompt>`. It uses existing ChatGPT Codex authentication; no API key is read or required. There is no resume path, provider abstraction, API/MCP/RPC layer, session orchestration, or Wave Reviewer dispatch.

Prompts name only the role, repository Skill, Wave/task, task path, review path, TECHSPEC path, authoritative input paths, and checkout fingerprint. They do not contain prior transcripts, reasoning, or a session ID. Reviewer/re-reviewer calls are separate new `codex exec` commands.

## Contracts

The host parses every nonblank `--json` JSONL line, requires `thread.started`/thread ID and a terminal `turn.completed`, retains usage when present, and requires a schema-valid final JSON message. It fails closed on a nonzero exit, timeout, malformed JSONL/final result, missing terminal event, or missing expected artifact. `Popen(start_new_session=True)` plus process-group TERM, short wait, then KILL records timeout deterministically.

The schema-v1 envelope is built from Controller operation facts, fingerprints, checked artifact hashes, process facts, thread ID, timestamp, and the authoritative review-file decision. The model does not construct the envelope. `complete_operation` remains the final acceptance/rejection check; rejection produces `HUMAN_ATTENTION`.

`TASKS_READY_FOR_WAVE_REVIEW` now returns as a terminal Controller result and remains persisted; it no longer transitions to `WAVE_REVIEW_REQUIRED`. Manual Wave Review can still be invoked later by an authorized caller selecting that lifecycle state, but the bootstrap host cannot reach or dispatch it.

## Tests and validation

Focused tests added cover explicit Developer/Reviewer/Fixer command policy, fresh reviewer command shape, repository cwd, factual Skill handoff, valid JSONL success, nonzero/missing-terminal/malformed-JSONL/missing-artifact failure, timeout, FIX_REQUIRED → Fixer → fresh Reviewer, next-task progression, terminal stop, and human-attention stop. Existing Controller tests retain approval, state, fingerprint, and lease coverage.

- Focused: `.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller tests.bootstrap.test_wave_controller_host -q` — PASS, 45 tests.
- Full: `.venv/bin/python3 -m unittest discover -s tests -q` — PASS, 101 tests, rerun after the final output-schema compatibility correction.

Disposable live validation completed successfully in a clean temporary Git repository with two trivial tasks and repository-local tiny Skills.

An earlier attempt exposed an invalid response-schema property and the host was corrected to include `"type": "string"`. Earlier runs were also interrupted by an outer execution-wrapper timeout. A subsequent uninterrupted run completed the full bounded scenario successfully:

- Task A: Developer (`gpt-5.6-terra`, low) → fresh Reviewer (`gpt-5.6-terra`, medium) → PASS.
- Task B: Developer (`gpt-5.6-terra`, low) → fresh Reviewer (`gpt-5.6-terra`, medium) → FIX_REQUIRED.
- Task B remediation: fresh Fixer (`gpt-5.6-terra`, low) → fresh Reviewer (`gpt-5.6-terra`, medium) → PASS.
- Final disposable Controller state: `TASKS_READY_FOR_WAVE_REVIEW`.
- Wave Review launched: NO.
- All observed Codex executions completed with exit code 0 and `timed_out: false`.
- Reviewer executions used distinct fresh Codex thread IDs and did not resume Developer/Fixer sessions.

This validates the complete bounded bootstrap loop required for supervised Wave 3 dogfooding.

## Scope confirmation and risks

- Wave 3 modified: NO.
- Production runtime (`src/engineering_flow`) modified: NO.
- API key required: NO.

Remaining risks are intentionally bounded:

- Codex CLI/config semantics may evolve and should fail closed if the expected JSONL contract changes.
- Fresh Codex executions have a non-trivial baseline context/token cost, so role prompts must remain small and factual.
- Reviewer write discipline remains protected by the existing exact-artifact Controller contract rather than stronger OS-level isolation.

No additional bootstrap infrastructure is recommended.

Recommendation: ACCEPT the bootstrap host for supervised Wave 3 dogfooding with the deliberate scope limit that automation stops at TASKS_READY_FOR_WAVE_REVIEW and Wave Review remains manual.

## Final acceptance

Decision: **GO_WITH_LIMITS**.

The bootstrap host is validated for its intended temporary purpose:

`approved task plan → execute/review/fix/re-review loops → next task → TASKS_READY_FOR_WAVE_REVIEW`.

It is not a replacement for the Engineering Flow runtime and should not be expanded beyond this bounded role.

The next intended use is supervised Wave 3 dogfooding after the Wave 3 task plan is created manually, reviewed by the human, approved, and registered with the Controller.