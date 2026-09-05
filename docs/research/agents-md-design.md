# Root `AGENTS.md` Design

**Status:** Proposed; no `AGENTS.md` was created or modified by this analysis.  
**Date:** 2026-09-05  
**Primary input:** `docs/research/codex-development-environment-audit.md`, verified against the current checkout where a fact could have changed.

## 1. Current Repository Facts Relevant to `AGENTS.md`

- No root `AGENTS.md`, `CONTRIBUTING.md`, Makefile, justfile, tox/nox configuration, pytest configuration, lint/type-check configuration, or pre-commit configuration is tracked. An instruction file must not imply that any of those entry points exists.
- This is a Python package with `src/` layout. `pyproject.toml` declares Python `>=3.13,<3.14`, no runtime dependencies, and the `engineering-flow` console script.
- The currently verified Linux checkout is `/home/bal/projects/engineering-flow`, on branch `main`. It has a Linux-native `.venv/bin/python3`, currently Python 3.13.15; `.venv/` is ignored rather than tracked.
- The verified application entry point is `.venv/bin/engineering-flow`, which exposes `init`, `run`, `status`, `approve`, `reject`, `resume`, `intervene`, and `logs`.
- The verified full-suite entry point is `.venv/bin/python3 -m unittest discover -s tests -q`. It completed 90 tests successfully in 7.758 seconds during this analysis. The command is useful but emits application output as well as the unittest summary; no tracked summary/raw-log wrapper exists.
- The durable product and delivery artifacts currently live in `docs/product/`, `docs/DELIVERY-PLAN.md`, `docs/architecture/`, `docs/waves/<wave>/`, `tasks/<wave>/`, and `tasks/<wave>/reviews/`. The currently committed artifacts cover Waves 1 and 2; the Delivery Plan defines the broader approved delivery strategy.
- Twelve repository-local Skills in `.codex/skills/` own the lifecycle processes: planning, architecture, TECHSPEC, task decomposition, execution, task review, task fix, Wave review/fix, and final review/fix. Their process details are intentionally more complete than an always-loaded root file.
- The audit's original WSL snapshot found a Windows-mounted checkout, WSL Python 3.12, and a Windows venv. Those are no longer true of this checkout: it is now on the Linux filesystem with a Linux venv matching the declared Python major/minor version. The audit's recommendations for a deterministic preflight/bootstrap/validation wrapper remain **proposed**, not present repository features.

## 2. What Belongs in `AGENTS.md`

The root file should be a small operational index with facts that every independent Codex session needs before selecting its task-specific context:

1. The Linux/WSL Python and CLI/test entry points that have been verified above.
2. A short map to authoritative, persisted documents by scope, without restating them.
3. A routing statement that repository-local Skills own their named workflow process.
4. One sentence preserving separate implementation, review, and remediation roles.
5. Bounded context/output defaults: begin with current repository state; search and read only the selected scope; use line ranges and summary-first Git output.
6. A short platform caveat: use the Linux-native venv for Linux/WSL work and do not substitute a cross-OS virtual environment.

These are high-frequency facts, are actionable from a fresh session, and do not require a prior chat summary.

## 3. What Explicitly Should Not Be Placed in `AGENTS.md`

- PRD requirements, product vision, delivery-Wave definitions, architecture rules, TECHSPEC details, task contracts, review findings, manual acceptance steps, or approval history. The persisted artifacts remain the authority for these.
- A lifecycle recipe, approval gates, artifact schemas, review criteria, remediation routing, or detailed role rules. Those belong in the triggered repository-local Skill and its selected scope artifacts.
- Proposed tooling such as `env-preflight`, `validate`, raw-log run IDs, handoff manifests, JSON-schema capture, `gh`, Docker, RTK, or MCP integrations. None is a tracked canonical entry point today.
- Host-local paths, Codex auth/state, trust and approval rules, plugins, MCP configuration, browser state, credentials, Docker configuration, Windows tools, or a promise of Windows/WSL parity.
- Generic coding style, formatter, linter, type-checker, commit, branch, PR, or release rules not established in the repository.
- Repeated lists of all Skills, their complete triggers, or their instructions. A single directory reference is enough.
- Historical environment remediation from the audit. The new root file should describe the current operational baseline, not carry a migration diary.

## 4. Duplication and Context Risks

Every root instruction line is likely loaded repeatedly. The main risk is turning the file into a second workflow specification: the twelve Skills already contain detailed process, authority, and output requirements, while product artifacts contain the actual approved scope. Duplicating either creates drift and can cause an agent to follow a stale summary over the governing artifact.

The audit measured approximately 5,927 lines of repository Skill content. Copying even abbreviated lifecycle rules into a root file would impose permanent context cost and weaken the deliberate boundaries between implementation, independent review, fixes, Wave acceptance, and final release acceptance. The proposal therefore supplies only a routing rule and a one-line boundary reminder.

Likewise, the audit proposed preflight and validation wrappers, but they do not exist. Naming them as commands would create failed tool calls and discovery churn. The proposal names only the commands exercised in this checkout. The test command's noisy output is a known limitation; it is addressed by bounded tool use rather than inventing a log convention.

## 5. Proposed `AGENTS.md` Content

```md
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
```

## 6. Estimated Size / Line Count

The proposed file is **17 nonblank lines / 27 physical lines including blank lines** (including its Markdown heading and section headings). It is intentionally below a one-screen operational index and contains no table, workflow diagram, or repeated artifact detail.

## 7. Open Questions or Risks

1. The root file cannot make `.venv` reproducible because no tracked bootstrap command or dependency manager workflow exists. A fresh Linux session without it can be told to surface the mismatch, but cannot repair it using a repository-supported command.
2. The Delivery Plan describes four Waves, but committed task/review artifacts are only present for Waves 1–2. The proposed file deliberately uses `<wave>` paths rather than asserting an active Wave or lifecycle state.
3. The test command emits product CLI lines, so output can be noisier than the proposed bounded-output guidance ideally permits. A future validated wrapper can replace that sentence only after it is committed and exercised.
4. The audit's environment inventory is partly historical. Future changes to the venv, Python version, supported CLI commands, or validation tooling must update `AGENTS.md` in the same change that establishes the new canonical entry point.
5. The proposal intentionally says no tracked lint/format entry point exists. If a quality tool is added later, its exact supported invocation should be added only after it becomes part of the repository contract.

## 8. Recommendation

**ADOPT.** The proposed root file is factual in the current Linux checkout, gives independent sessions a reliable first read, routes lifecycle authority to existing local Skills and persisted artifacts, and costs only 27 recurring physical lines. Adoption should be a separate, narrowly scoped change after this design handoff is reviewed.
