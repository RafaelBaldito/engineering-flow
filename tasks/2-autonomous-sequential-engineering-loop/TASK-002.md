# TASK-002 — Generalize Runtime Contracts and Codex Role Execution

## Objective

Evolve the planning-only runtime boundary into provider-neutral, schema-checked
Developer and Reviewer execution contracts, then implement their safe
role-specific behavior in the Codex CLI adapter.

## Scope

- Generalize `runtime.py` protocol names while retaining planning compatibility;
  define capability verification, task/review requests/results, work kinds,
  structured final payloads, and logical-session continuity data.
- Extend `codex_cli.py` capability preflight to verify executable, non-bare
  worktree, JSON events, output schema/last-message support, and the requested
  `workspace_write` or `read_only` sandbox before every dispatch.
- Implement no-shell Developer execution with workspace-write only when
  requested and verified, and Reviewer execution with read-only only. Retain
  bounded timeout, minimal environment, JSONL normalization, output-schema
  validation, and sanitization.
- Feature-detect installed-Codex resume support. Reuse a verified Developer
  provider session when available; otherwise create a new provider session
  from the persisted bounded continuity bundle and expose the degraded
  continuity fact for persistence. Keep Reviewer sessions distinct.
- Add deterministic contract and subprocess-fixture tests for role capability
  gates, argv/cwd/sandbox behavior, schemas, semantic invalid output, timeout,
  authentication/tool failure, and continuity fallback.

## Context

### Required

- `docs/waves/2-autonomous-sequential-engineering-loop/TECHSPEC.md` §5–§6 and §9
- `src/engineering_flow/runtime.py`
- `src/engineering_flow/codex_cli.py`
- `src/engineering_flow/domain.py`

### Optional

- `docs/architecture/architecture-overview.md` §6–§7 and §12–§13
- `tests/test_runtime.py`
- `tests/test_codex_cli.py`

## Requirements

- The core protocol must refer to provider-neutral role, request, result,
  capability, session, execution, and event concepts. Preserve existing
  planning callers with compatible names/behavior while allowing orchestration
  to require role-specific capabilities through one verification method.
- Require workspace-write, JSON events, structured final output, and a bounded
  timeout for Developer work. Require read-only, JSON events, structured final
  output, and a bounded timeout for Reviewer work. Reject a runtime that cannot
  prove the requested capability; never substitute workspace-write for review.
- Validate the TECHSPEC §6 Developer and Reviewer payload shapes and semantics
  at the adapter boundary. Payload prose and progress JSONL must not control a
  lifecycle decision. Preserve only sanitized provider-native metadata.
- Build every provider invocation as an argument vector with the validated
  repository as `cwd`; keep no shell, minimal environment, configured timeout,
  output schema, and final-output path protections. Do not persist workflow
  state, task artifacts, or acceptance in the adapter.
- Reviewer execution must use a new logical and provider session, never a
  Developer session. Developer continuity must be task-local and include only
  the task contract, prior developer/test evidence, and current findings when
  resume support is unavailable.

## Constraints

- The exact Codex resume syntax is feature-detected from installed help/capability
  evidence; do not hard-code an unverified flag or model assumption.
- Automated tests must use fakes/fixtures, never credentials or a live Codex
  invocation. Continue using only standard-library facilities.
- Do not implement task selection, cycle counting, evidence persistence,
  intervention policy, CLI parsing, Git/PR behavior, or a second provider.

## Acceptance Criteria

- Planning integrations remain usable, while orchestration can create
  provider-neutral Developer and Reviewer requests/results with explicit role
  capabilities and bounded continuity metadata.
- Preflight rejects missing/unsupported executable, invalid worktree, missing
  JSON/schema support, disabled or unavailable workspace-write development,
  and any Reviewer request that cannot be proven read-only.
- Fixture executions show a safe argv and `cwd`, role-appropriate sandbox,
  normalized JSONL events, final payload schema/semantic validation, distinct
  failure classification, and no shell execution.
- A Developer reuses a verified session or records continuity degradation with
  the bounded evidence bundle; every Reviewer gets an independent session.
- The adapter neither advances a task nor writes task database/artifact state.

## Validation

- `python -m unittest discover -s tests -p 'test_runtime.py'`
- `python -m unittest discover -s tests -p 'test_codex_cli.py'`
- `python -m compileall -q src`

## Dependencies

- TASK-001 — Wave 2 roles, failure classifications, and task/cycle evidence
  values used by the generalized contracts.

## Out of Scope

- Task-plan import, lifecycle transitions, review-cycle limits/intervention,
  configuration/CLI presentation, Wave acceptance, and Git/PR delivery.
