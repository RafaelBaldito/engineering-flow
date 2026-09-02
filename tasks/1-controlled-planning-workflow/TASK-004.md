# TASK-004 — Deliver Configuration and the CLI Control Surface

## Objective

Expose the completed planning workflow through validated repository-local
configuration and stable `engineering-flow` commands, with safe, inspectable
human interaction.

## Scope

- Implement `config.py` to read and validate
  `.engineering-flow/config.toml`, resolve/canonicalize paths, and expose the
  approved provider, approval, timeout, and read-only-planning settings.
- Implement `cli.py` and the `engineering-flow` console entry point for
  `init`, `run`, `status`, `approve`, `reject`, `resume`, and `logs`.
- Implement `init` Git-worktree validation, application workspace creation,
  normative initial config, and non-destructive `.gitignore` update.
- Compose the configuration, store, orchestrator, and Codex runtime at the CLI
  boundary; format normal and JSON output, map typed failures to stable
  non-zero exit codes, and ensure output/log diagnostics are sanitized.
- Add configuration, command-level integration, and full-suite tests; document
  the manual disposable-repository acceptance procedure without running a live
  Codex workflow in automated validation.

## Context

### Required

- `docs/waves/1-controlled-planning-workflow/TECHSPEC.md` §4.1–§4.2, §7–§9
- `src/engineering_flow/orchestrator.py`
- `src/engineering_flow/codex_cli.py`
- `pyproject.toml`

### Optional

- `docs/architecture/architecture-overview.md` §9–§10 and §12–§13
- `README.md`

## Requirements

- Reject invalid configuration, invalid paths, non-Git repositories, and
  write-capable planning settings before a provider process begins. Never store
  credentials in config or include them in command arguments, persisted data,
  or output.
- Generate exactly the normative initial configuration from TECHSPEC §4.2 with
  all three approval policies set to `required`; preserve existing `.gitignore`
  entries when adding the application directory entry.
- Support exactly the stable command forms and required options in TECHSPEC §7.
  Approval/rejection commands require exact workflow and artifact identifiers.
- Keep CLI code a thin adapter: it delegates all transition decisions to the
  orchestrator and reports persisted state rather than inferring it from
  provider output.
- JSON mode must emit one document containing command result, workflow ID,
  status, stage, and error code. Both output modes must preserve secret
  redaction and distinguish all specified error categories.
- Status/log operations must expose authoritative persisted state, monotonic
  events, `--after` filtering, and artifact corruption failures without
  mutating the workflow.

## Constraints

- Use `argparse`, `tomllib`, and other standard-library facilities only.
- `init` must never create a branch, commit, push, open a PR, or run target
  repository scripts/tests.
- Do not add task execution, test/review lifecycle, Git delivery, another
  runtime provider, or a UI/service.

## Acceptance Criteria

- `engineering-flow init --repo PATH` rejects non-worktrees and otherwise
  creates the approved workspace/config while preserving `.gitignore` content.
- All specified commands parse their stable forms, call orchestration services,
  and return stable success/error results in text and JSON modes.
- A CLI-driven fake-runtime workflow displays state and logs, blocks each next
  stage until its required approval, preserves artifacts, and reaches the
  Wave 1 terminal state without task execution.
- Invalid config, path traversal, stale approval decisions, provider/auth
  failures, persistence corruption, and human-attention states produce the
  correct non-zero classified outcome with no secret leakage.
- The complete automated suite passes without live credentials or Codex calls;
  documented manual acceptance covers authenticated execution, three approvals,
  interruption/resume, status/log evidence, and absence of delivery actions.

## Validation

- `python -m unittest discover -s tests -p 'test_config.py'`
- `python -m unittest discover -s tests -p 'test_cli.py'`
- `python -m unittest discover -s tests`
- `python -m compileall src`
- Manual acceptance in a disposable Git repository, using authenticated Codex,
  following TECHSPEC §9 (not part of automated tests).

## Dependencies

- TASK-003 — orchestration service APIs and planning lifecycle behavior.

## Out of Scope

- Any Wave 2 or Wave 3 functionality, including task execution/review/fix,
  commits, pushes, pull requests, and merge automation.
