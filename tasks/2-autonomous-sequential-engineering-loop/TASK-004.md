# TASK-004 — Expose Execution Policy and Task Lifecycle CLI Controls

## Objective

Make Wave 2 execution policy and persisted task lifecycle safely configurable
and observable through the repository-local configuration and thin CLI.

## Scope

- Extend `config.py` and new-repository initialization with the normative
  `[execution]` table: a positive `max_review_cycles` plus the two required
  true role-permission booleans. Capture this validated policy in a workflow
  snapshot.
- Implement the explicit, non-destructive handling of existing Wave 1 configs:
  missing `[execution]` fails with an actionable message until the owner adds
  normative values; do not rewrite the configuration file implicitly.
- Compose configuration, store, generalized orchestrator, and Codex runtime at
  the CLI boundary, retaining public planning command compatibility.
- Add `intervene --repo PATH --workflow ID --task ID --reason TEXT`, and extend
  JSON status/log projections with the specified ordered task, active task,
  cycle/window, test/review, intervention, and correlated-event evidence.
- Add focused config/CLI tests for migration, parsing, snapshots, human
  intervention input validation, status/log output, error/exit mapping, and
  sanitization.

## Context

### Required

- `docs/waves/2-autonomous-sequential-engineering-loop/TECHSPEC.md` §8–§10
- `src/engineering_flow/config.py`
- `src/engineering_flow/cli.py`
- `src/engineering_flow/orchestrator.py`

### Optional

- `docs/architecture/architecture-overview.md` §9–§10 and §12–§13
- `tests/test_config.py`
- `tests/test_cli.py`

## Requirements

- Validate `max_review_cycles` as a positive non-boolean integer and require
  both execution booleans to be exactly `true`; reject missing, unknown, or
  invalid configuration before a provider process starts. Keep provider timeout
  positive and capture the complete validated policy at workflow creation so
  later file edits do not alter an in-flight run.
- `init` must create the normative `[execution]` values for new repositories.
  For initialized repositories with an otherwise valid legacy configuration,
  return a precise non-destructive migration message rather than modifying the
  file or silently choosing a policy.
- Keep CLI transition-free: `resume` delegates the next permitted Wave 2 action
  to orchestration, while `intervene` records only the required human decision
  through the orchestrator. Validate identifiers/reason and map typed failures
  to the established stable output and exit-code conventions.
- In JSON mode expose ordered task key/title/status, active task, window/cycle,
  latest required-test/review result, and intervention requirement. Extend
  logs only with persisted monotonic task/cycle correlation; never emit raw
  environment, credentials, unredacted diagnostics, or transcripts.
- Preserve all planning forms and their previous status/log behavior, with no
  CLI command that performs Wave acceptance, Git delivery, or merge.

## Constraints

- Use only `argparse`, `tomllib`, and other standard-library modules.
- The CLI must not infer lifecycle state from provider prose or a Git diff.
  It displays persisted authoritative records after hash verification.
- Do not implement review-cycle business rules in the CLI or loosen a policy
  during intervention.

## Acceptance Criteria

- New initialization creates a configuration with the exact Wave 2 execution
  settings, whereas an existing missing table fails clearly without changing
  its bytes.
- Invalid execution policy blocks runtime composition; a valid workflow
  snapshot remains authoritative after the config file is changed.
- `intervene` accepts only a concrete task/reason for a persisted intervention
  boundary and cannot itself accept, skip, or advance a task.
- `status --json` and `logs --json` expose sanitized persisted Wave 2 task and
  review progress with ordered/monotonic correlation, while legacy planning
  workflows retain compatible command behavior.
- CLI/config failures have stable classified output and exit behavior without
  live Codex credentials or task execution in tests.

## Validation

- `python -m unittest discover -s tests -p 'test_config.py'`
- `python -m unittest discover -s tests -p 'test_cli.py'`
- `python -m compileall -q src`

## Dependencies

- TASK-003 — persisted lifecycle service APIs for resume, intervention, and
  task/review status projections.

## Out of Scope

- Runtime adapter implementation, task-plan import rules, orchestrator
  transition policy, Wave acceptance, release review, Git/PR delivery, and UI.
