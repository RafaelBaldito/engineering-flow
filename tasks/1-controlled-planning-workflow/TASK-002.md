# TASK-002 — Implement the Codex Planning Runtime Adapter

## Objective

Provide the provider-neutral planning runtime contract and its sole Wave 1
Codex CLI adapter, including capability checks, safe process invocation, and
validated structured results.

## Scope

- Implement `runtime.py` contracts for planning capability reports, bounded
  execution requests/results, normalized events, and the `AgentRuntime`
  protocol.
- Implement `codex_cli.py` with injected process dependencies suitable for
  deterministic tests.
- Generate and retain the per-execution final-output JSON Schema specified by
  the TECHSPEC; parse JSONL incrementally, normalize events, and capture the
  `thread.started` provider reference.
- Preflight the configured executable, target Git worktree, required Codex
  non-interactive capabilities, and read-only-planning permission.
- Add subprocess-fixture tests for success, timeout, non-zero exit, malformed
  output, and authentication failure.

## Context

### Required

- `docs/waves/1-controlled-planning-workflow/TECHSPEC.md` §4.1, §5, and §8
- `src/engineering_flow/domain.py`
- `src/engineering_flow/sanitization.py`

### Optional

- `docs/architecture/architecture-overview.md` §6–§7 and §12–§13
- `docs/waves/1-controlled-planning-workflow/TECHSPEC.md` §9

## Requirements

- Keep the core request/result protocol provider-neutral; provider-native
  fields must remain JSON metadata and cannot determine workflow transitions.
- Invoke the configured executable using an argument vector, validated target
  repository as `cwd`, minimal inherited environment, configured timeout,
  read-only sandbox, JSONL output, output schema, and orchestrator-owned final
  output path. Do not use a shell or request write-capable/broad access.
- Reject final results unless all required payload fields are present,
  `artifact_markdown` is non-empty, a terminal success event is observed, and
  the result is within timeout. Invalid output must have enough normalized
  failure detail for orchestration to record an `agent_execution` failure.
- Distinguish authentication failures from provider/tool failures. Authentication
  is confirmed by actual execution rather than preflight alone.
- The adapter may return sanitized normalized evidence but must not write the
  database, artifacts, workflow state, or approval records.

## Constraints

- Use standard-library subprocess and JSON facilities only.
- Keep command syntax/version detection inside the adapter; do not assume a
  model name or silently treat unknown CLI capabilities as supported.
- Do not make any live Codex call in automated tests.

## Acceptance Criteria

- The runtime protocol is usable by orchestration without importing
  Codex-specific types.
- Preflight rejects a missing/unsupported executable, non-Git repository, or
  write-capable planning configuration before planning execution begins.
- The adapter passes the expected safe command vector and working directory,
  translates JSONL events, and associates the thread ID with the logical
  session.
- Structured success produces only the approved payload shape; malformed,
  timed-out, non-zero, and authentication cases are distinguishable failures.
- The adapter makes no persistence or artifact-authority changes.

## Validation

- `python -m unittest discover -s tests -p 'test_runtime.py'`
- `python -m unittest discover -s tests -p 'test_codex_cli.py'`
- `python -m compileall src`

## Dependencies

- TASK-001 — uses shared domain failures and sanitization behavior.

## Out of Scope

- Workflow transitions, approval policy evaluation, configuration-file parsing,
  and CLI command handling.
