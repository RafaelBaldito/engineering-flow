# Engineering Flow

## Runtime and validation

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

- Start with `git status --short`, then locate and load only the files needed for the selected scope. Search before opening large files; prefer line ranges and bounded search results.
- Keep tool output small: use targeted tests where appropriate, `git diff --stat` or changed-file lists before full diffs, and request detailed logs only to diagnose a specific failure.

## Platform scope

- Treat Linux/WSL as the canonical development environment for this checkout. Do not use or share a Windows virtual environment from Linux; if the expected Linux venv is unavailable, surface that mismatch rather than silently substituting an interpreter.
