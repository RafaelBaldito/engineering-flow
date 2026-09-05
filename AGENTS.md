# Engineering Flow

## Runtime and validation

- First readiness command: `./scripts/env-preflight`. It is a read-only environment and checkout diagnostic; it does not replace task-specific or full validation.
- This Python project requires 3.13. For Linux/WSL work, use the repository-local Linux environment: `.venv/bin/python3`.
- Application CLI: `.venv/bin/engineering-flow <command>` (`init`, `run`, `status`, `approve`, `reject`, `resume`, `intervene`, `logs`).
- Full validation: `.venv/bin/python3 -m unittest discover -s tests -q`. No other tracked validation, lint, or formatting entry point exists.

## Authoritative persisted context

- Read the smallest applicable source: product requirements in `docs/product/`, delivery scope in `docs/DELIVERY-PLAN.md`, cross-Wave architecture in `docs/architecture/`, and Wave TECHSPEC/manual acceptance in `docs/waves/<wave>/`.
- For task work, use `tasks/<wave>/TASKS.md`, the selected `TASK-*.md`, and its review/remediation evidence under `tasks/<wave>/reviews/`.
- These repository artifacts are authoritative over conversation summaries; do not restate or replace them here.

## Workflow boundaries

- Repository-local Skills in `.codex/skills/` own their respective workflow processes. Read and follow the matching Skill; do not duplicate its process in this file.
- Keep roles independent: implementation executes only its selected approved task; review evaluates without fixing; fixes address authoritative findings and return to review.

## Context discipline

- Start with `git status --short`, then locate and load only the files needed for the selected scope. When output may be large, begin with targeted, bounded inspection; retain initial output when it is already small. Search before opening large files; prefer relevant line ranges and bounded search results.
- Keep tool output small: use targeted tests where appropriate, `git diff --stat` or changed-file lists before large raw diffs, and summarize successful validation while preserving command/result evidence. On failure, progressively expand diagnostics until the cause is established; do not truncate authoritative review/acceptance evidence or diagnostics where truncation could hide a material cause.

## Platform scope

- Treat Linux/WSL as the canonical development environment for this checkout. Do not use or share a Windows virtual environment from Linux; if the expected Linux venv is unavailable, surface that mismatch rather than silently substituting an interpreter.
