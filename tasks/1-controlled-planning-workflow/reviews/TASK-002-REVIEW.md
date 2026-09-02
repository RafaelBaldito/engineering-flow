## Review Result

FIX_REQUIRED

## Task

`TASK-002 — Implement the Codex Planning Runtime Adapter`

## Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `python -m unittest discover -s tests -p 'test_runtime.py'` | PASS | 2 tests passed. |
| `python -m unittest discover -s tests -p 'test_codex_cli.py'` | PASS | 5 tests passed. |
| `python -m compileall src` | PASS | All source modules compiled. |
| `python -m unittest discover -s tests` | PASS | 18 tests passed. |
| Targeted preflight probes | FAIL | A synthetic directory containing only an empty `.git/` directory and a CLI help response without `--output-last-message` both produced an available capability report. |
| Targeted diagnostic-sanitization probe | FAIL | A non-zero process result with `PATH=C:/sensitive-user-profile\\bin` in stderr returned that raw value in `result.metadata["stderr"]`. |
| Targeted JSONL authentication probe | FAIL | A zero-exit `{"type":"error","message":"Authentication required"}` event returned `agent_execution` / `final structured output is missing`, not an authentication failure. |

## Acceptance Criteria

| Criterion | Result | Evidence |
|-----------|--------|----------|
| The runtime protocol is usable by orchestration without importing Codex-specific types. | PASS | `runtime.py` defines provider-neutral request, result, event, capability, and `AgentRuntime` protocol contracts; `test_runtime.py` exercises them with a generic provider. |
| Preflight rejects a missing/unsupported executable, non-Git repository, or write-capable planning configuration before planning execution begins. | FAIL | `codex_cli.py:120-126` treats any `.git` file or directory as a worktree, and `:149-156` does not require `--output-last-message`, although `:217-220` requires it for every execution. Probes showed both cases are accepted. |
| The adapter passes the expected safe command vector and working directory, translates JSONL events, and associates the thread ID with the logical session. | PASS | `test_success_writes_schema_and_uses_safe_command` verifies an argument vector with `--sandbox read-only`, no shell, resolved repository cwd, event translation, and the `thread.started` session reference. |
| Structured success produces only the approved payload shape; malformed, timed-out, non-zero, and authentication cases are distinguishable failures. | FAIL | The output schema checks at `codex_cli.py:301-314` reject extra/missing fields and the fixtures cover malformed, timeout, and non-zero authentication. However, JSONL authentication errors with exit code zero are classified as generic `agent_execution` failures at `:370-377`, instead of `authentication`. |
| The adapter makes no persistence or artifact-authority changes. | PASS | The adapter only creates the request-owned schema file and invokes its injected process dependency; it does not import or call the store/orchestrator and makes no workflow or artifact-authority decision. |

## Findings

### FINDING-001 — HIGH — Preflight accepts unsupported execution prerequisites

- Location: `src/engineering_flow/codex_cli.py:_is_git_worktree` (lines 120-126); `_help_result` (lines 149-156); `_process` (lines 217-220)
- Issue: The preflight accepts a directory with a merely present `.git` marker as a Git worktree and does not verify support for `--output-last-message`, despite always passing that required flag to the executable.
- Evidence: A temporary directory containing only an empty `.git/` directory produced `available=True` and `git_worktree=True`. A help response containing `--json`, `--output-schema`, and `--sandbox read-only`, but no `--output-last-message`, also produced `available=True`.
- Expected: Before launch, verify a real Git worktree and every non-interactive CLI capability the adapter will use, including its final-output flag.
- Fix direction: Use a robust read-only Git worktree validation and include the final-output option in the supported-capabilities contract and tests.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: no`; `REGRESSION_FROM_FIX: no`

### FINDING-002 — HIGH — Raw environment values can escape through returned stderr

- Location: `src/engineering_flow/codex_cli.py:354, 359, 367, 376, 381`; `src/engineering_flow/sanitization.py:sanitize_text`
- Issue: The adapter labels stderr as safe after `sanitize_text`, but that sanitizer redacts configured secrets and credential-shaped values only. It leaves ordinary environment assignments, such as `PATH=...`, intact in result metadata that orchestration can persist.
- Evidence: A non-zero fixture stderr of `PATH=C:/sensitive-user-profile\\bin\nAPI_KEY=top-secret` yielded metadata stderr `PATH=C:/sensitive-user-profile\\bin\nAPI_KEY=[REDACTED]`.
- Expected: Returned normalized evidence must not expose raw environment variables or unredacted stderr that can be persisted or displayed.
- Fix direction: Apply an environment-aware diagnostic sanitizer to stderr and equivalent textual provider evidence, then add regression coverage for environment-style assignments as well as configured secrets.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: no`; `REGRESSION_FROM_FIX: no`

### FINDING-003 — HIGH — Authentication JSONL failures lose their classification

- Location: `src/engineering_flow/codex_cli.py:_normalize_lines` (lines 277-278); `execute_planning` (lines 370-377)
- Issue: Failure-event content is retained as an event but never examined for authentication evidence. When the process exits zero after a provider error event, the adapter reports `agent_execution` with a missing-payload detail rather than the required distinct `authentication` failure.
- Evidence: A fake process returned `{"type":"error","message":"Authentication required"}` with exit code 0; the result was `TerminalState.FAILED`, `FailureClassification.AGENT_EXECUTION`, and `final structured output is missing`.
- Expected: Authentication failures observed during actual execution must be distinguishable from provider/tool and malformed-output failures.
- Fix direction: Classify normalized failure-event diagnostics before the generic final-payload error path, preserving sanitized evidence; cover successful-exit JSONL authentication errors in adapter tests.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: no`; `REGRESSION_FROM_FIX: no`

### FINDING-004 — MEDIUM — JSONL is buffered rather than parsed incrementally

- Location: `src/engineering_flow/codex_cli.py:339-352`
- Issue: The implementation calls `communicate()` to collect all stdout and stderr before splitting and parsing JSONL. This does not satisfy the task's incremental JSONL parsing requirement and buffers an unbounded provider event stream.
- Evidence: `_normalize_lines` accepts a complete `stdout: str`, and is only called after `process.communicate()` returns.
- Expected: Parse provider JSONL as records arrive while retaining bounded sanitized evidence and preserving the configured timeout.
- Fix direction: Consume stdout incrementally with a bounded stderr strategy, normalize each record as it arrives, and add a multi-record streaming fixture.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: no`; `REGRESSION_FROM_FIX: no`

## Summary

The core protocol and basic adapter fixtures are sound, and all required automated checks pass. However, incomplete preflight, unsafe returned diagnostics, lost JSONL authentication classification, and non-incremental JSONL handling violate this task's safety and runtime-contract requirements. The defects are within TASK-002's approved scope.
