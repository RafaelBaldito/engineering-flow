## Review Result

FIX_REQUIRED

## Task

`TASK-004 — Deliver Configuration and the CLI Control Surface`

## Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `python -m unittest discover -s tests -p 'test_config.py'` | PASS | 7 tests passed; the external `.gitignore` symlink regression was skipped because Windows file-link creation requires an unavailable privilege. |
| `python -m unittest discover -s tests -p 'test_cli.py'` | PASS | 4 tests passed. |
| `python -m unittest discover -s tests` | PASS | 49 tests passed, 1 skipped. |
| `python -m compileall src` | PASS | Completed successfully. |
| `git diff --check` | PASS | No whitespace errors. |
| JSON parsing-failure probe | FAIL | `main(['logs', '--repo', 'missing', '--workflow', 'id', '--after', '-1', '--json'])` raises `SystemExit(2)`, writes no stdout, and writes argparse plain-text usage to stderr. |
| Credential-like provider-command probe | FAIL | A config containing `command = "codex --api-key this-is-a-private-value"` loads successfully; a fake-runtime `run` then persists the value in `workflows.configuration_snapshot`. |
| Disposable-repository authenticated Codex acceptance | NOT RUN | Excluded from automated validation; the required procedure is documented in `docs/waves/1-controlled-planning-workflow/MANUAL-ACCEPTANCE.md`. |

## Acceptance Criteria

| Criterion | Result | Evidence |
|-----------|--------|----------|
| `engineering-flow init --repo PATH` rejects non-worktrees and otherwise creates the approved workspace/config while preserving `.gitignore` content. | PASS | `tests/test_config.py` verifies normative initialization, preservation, non-Git rejection, application/database containment, and the added `.gitignore` link defense. `cli.py:274-286` resolves and contains `.gitignore` before reading or writing it. |
| All specified commands parse their stable forms, call orchestration services, and return stable success/error results in text and JSON modes. | FAIL | JSON-mode parser errors bypass `_result_document()` and do not emit the required JSON result; see FINDING-002. |
| A CLI-driven fake-runtime workflow displays state and logs, blocks each next stage until its required approval, preserves artifacts, and reaches the Wave 1 terminal state without task execution. | PASS | `tests/test_cli.py` drives the fake runtime through three exact approvals to `completed` / `ready_for_wave_2`, and verifies persisted status, artifacts, and filtered logs. |
| Invalid config, path traversal, stale approval decisions, provider/auth failures, persistence corruption, and human-attention states produce the correct non-zero classified outcome with no secret leakage. | FAIL | `provider.command` accepts an API-key flag and arbitrary secret-shaped argument, which the CLI supplies in the persisted configuration snapshot; see FINDING-001. |
| The complete automated suite passes without live credentials or Codex calls; documented manual acceptance covers authenticated execution, three approvals, interruption/resume, status/log evidence, and absence of delivery actions. | PASS | Full automated suite passed without live provider calls; `MANUAL-ACCEPTANCE.md` documents the required disposable-repository authenticated procedure. |

## Findings

### FINDING-001 — HIGH — Credential-bearing provider commands are accepted and persisted

- Location: `src/engineering_flow/config.py:_reject_credentials` and `src/engineering_flow/config.py:load_config`; persistence path `src/engineering_flow/cli.py:299-304` and `src/engineering_flow/store.py:281-312`
- Issue: Configuration validation permits a provider command such as `codex --api-key this-is-a-private-value`. The string does not match the current credential-value pattern, is returned as `FlowConfig.provider_command`, and its complete value is placed into `FlowConfig.snapshot`, then persisted in `workflows.configuration_snapshot` when `run` begins.
- Evidence: The credential probe loaded that configuration successfully. With `CodexCliRuntime` replaced by the task's fake runtime, `run` returned zero and the SQLite configuration snapshot contained `this-is-a-private-value`. `_CREDENTIAL_PATTERN` only recognizes a credential key followed by `=` or `:`, a Bearer value, or `sk`/`pk` tokens; it does not recognize CLI flag syntax. `sanitize_configuration_snapshot()` likewise does not redact `--api-key VALUE`.
- Expected: Configuration must reject credentials before a provider process begins. Credentials must not appear in configuration, command arguments, persisted data, or output, per TASK-004 and TECHSPEC §§4.2 and 8.
- Fix direction: Constrain `provider.command` to a single executable name/path (not a command line), and explicitly reject credential-related CLI option syntax. Add regression coverage proving a representative API-key argument is rejected and never reaches a workflow snapshot.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: yes`; `REGRESSION_FROM_FIX: no`

### FINDING-002 — HIGH — JSON mode does not produce a JSON result for usage errors

- Location: `src/engineering_flow/cli.py:63-99` and `src/engineering_flow/cli.py:331-358`
- Issue: `argparse` handles invalid and missing arguments by printing its own text error and raising `SystemExit` before `main()` builds a result document. This happens even when a supported JSON-mode command includes `--json`.
- Evidence: Invoking `logs --repo missing --workflow id --after -1 --json` produced `SystemExit(2)`, no stdout, and plain-text usage/error output on stderr. No document contained `command_result`, `workflow_id`, `status`, `stage`, or `error_code`.
- Expected: TECHSPEC §7 requires JSON mode to emit one document containing the command result, workflow ID, status, stage, and error code, and requires non-zero usage/config errors to be stably classified.
- Fix direction: Route parser failures through the CLI result formatter when JSON output was requested, while retaining the normal argparse UX for text mode. Add tests for invalid `--after` and a missing required argument on JSON-capable commands.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: yes`; `REGRESSION_FROM_FIX: no`

## Non-Blocking Notes

- The prior external `.gitignore` link finding is resolved in `cli.py:274-286`. Its regression test is present but could not execute in this Windows environment because file symlink creation is not permitted.

## Summary

The previous `.gitignore` containment defect is fixed, and all deterministic suite/build gates pass. However, credential material can still be accepted and persisted through `provider.command`, and JSON-mode usage failures violate the stable JSON error contract. Both defects are within TASK-004 scope and require correction before acceptance.
