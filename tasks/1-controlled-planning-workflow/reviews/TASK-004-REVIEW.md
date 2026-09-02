## Review Result

PASS

## Task

`TASK-004 — Deliver Configuration and the CLI Control Surface`

## Review Scope

Current implementation and approved Wave 1 TECHSPEC §§4.1–4.2 and 7–9. This
review supersedes the prior `FIX_REQUIRED` record for TASK-004.

## Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p 'test_config.py'` | PASS | 8 tests passed; 1 Windows symlink-permission test skipped. |
| `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p 'test_cli.py'` | PASS | 5 tests passed. |
| `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests` | PASS | 52 tests passed; 1 Windows symlink-permission test skipped. No live Codex calls are made. |
| `.\\.venv\\Scripts\\python.exe -m compileall -q src` | PASS | Completed with exit code 0. |
| `git diff --check` | PASS | No whitespace errors. |
| Manual acceptance procedure | PASS | `docs/waves/1-controlled-planning-workflow/MANUAL-ACCEPTANCE.md` documents the required disposable-repository authenticated workflow; it is deliberately excluded from automated execution. |

## Acceptance Criteria

| Criterion | Result | Evidence |
|-----------|--------|----------|
| `engineering-flow init --repo PATH` rejects non-worktrees and otherwise creates the approved workspace/config while preserving `.gitignore` content. | PASS | `is_git_worktree`, `application_path`, and `application_owned_path` validate containment. `test_init_writes_normative_config_and_preserves_gitignore` verifies the exact normative config and preserved entry; link-escape paths are rejected. |
| All specified commands parse their stable forms, call orchestration services, and return stable success/error results in text and JSON modes. | PASS | `build_parser` defines the approved command forms. `_ArgumentParser` routes usage errors through `main`, and `test_json_usage_errors_emit_one_stable_result_document` verifies one JSON document with stable fields/error code. |
| A CLI-driven fake-runtime workflow displays state and logs, blocks each next stage until its required approval, preserves artifacts, and reaches the Wave 1 terminal state without task execution. | PASS | CLI integration tests exercise `run`, `status`, `logs`, exact approvals, `resume`, persisted artifacts, filtering, and `completed/ready_for_wave_2`; the fake runtime performs no task execution or delivery actions. |
| Invalid config, path traversal, stale approval decisions, provider/auth failures, persistence corruption, and human-attention states produce the correct non-zero classified outcome with no secret leakage. | PASS | Config rejects credential-shaped values/arguments and non-single-executable commands before runtime construction. CLI maps typed failures and workflow classifications to stable codes; focused CLI/config tests plus the full suite cover stale approvals, corruption, configuration, provider/auth, and attention paths. Result documents and diagnostics apply sanitization. |
| The complete automated suite passes without live credentials or Codex calls; documented manual acceptance covers authenticated execution, three approvals, interruption/resume, status/log evidence, and absence of delivery actions. | PASS | The full deterministic suite passes without live calls. `MANUAL-ACCEPTANCE.md` specifies the disposable authenticated procedure, three approvals, interruption/resume, evidence checks, and delivery-action absence. |

## Previous Findings Recheck

| Prior finding | Result | Evidence |
|---------------|--------|----------|
| Credential-bearing provider commands could be accepted and persisted. | RESOLVED | `_CREDENTIAL_PATTERN` recognizes credential CLI options; `load_config` rejects them before a database is created. It also requires `provider.command` to be one executable name/path without arguments. `test_provider_command_cannot_include_credential_argument_or_reach_snapshot` passes. |
| JSON-mode usage errors bypassed the stable JSON result contract. | RESOLVED | `_ArgumentParser.error` raises `_ParserUsageError`, and `main` emits `_result_document` when `--json` was requested. The new regression covers invalid `--after` and missing `--workflow`. |

## Non-Blocking Notes

- The external `.gitignore` symlink test is skipped only because this Windows
  environment lacks link-creation permission; the implementation and other
  containment coverage were inspected and the full suite otherwise passed.

## Summary

All TASK-004 acceptance criteria are satisfied by the current implementation.
The prior `FIX_REQUIRED` findings are resolved; no blocking findings remain.
