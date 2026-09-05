# Environment Preflight Design

**Status:** Design only; no implementation is authorized by this document.  
**Date:** 2026-09-05  
**Decision:** **ADOPT**

## 1. Problem and objective

Engineering Flow needs one fast, repository-owned command that answers a deliberately narrow question before an agent or developer begins work:

> Is this checkout ready to begin Engineering Flow development?

Today that answer is reconstructed from `AGENTS.md`, `pyproject.toml`, shell paths, and ad hoc commands. The environment audit found that this previously led to a WSL Python 3.12 / Windows-format virtual-environment mismatch despite a project requirement for Python 3.13. That is exactly the kind of failure a preflight should identify before expensive work begins.

The command is a **read-only readiness gate**, not a bootstrapper, test runner, host-health checker, or replacement for task-specific validation. It must use only repository-owned code and standard operating-system/Python facilities, have no network dependency, and complete in well under a second in the normal case.

## 2. Current verified repository/environment facts

The facts below were inspected in this checkout on the design date. They are evidence for the design, not new host requirements beyond the repository contract.

- `AGENTS.md` defines Linux/WSL as canonical and names `.venv/bin/python3` as the required interpreter and `.venv/bin/engineering-flow` as the application CLI. It requires Python 3.13 and directs agents to start work with `git status --short`.
- `pyproject.toml` declares `engineering-flow`, `requires-python = ">=3.13,<3.14"`, no third-party runtime dependencies, a `src` package layout, and the `engineering-flow = "engineering_flow.cli:main"` console entry point.
- The current repository root is a Git worktree at `/home/bal/projects/engineering-flow`, on `main`, and was clean before this design artifact was created.
- The current `.venv/bin/python3` is executable, reports Python 3.13.15, and imports `engineering_flow` from this checkout's `src/engineering_flow` directory. `.venv/bin/engineering-flow --help` succeeds and exposes the existing application commands.
- There is no committed Makefile, tox/nox configuration, formatter/linter/type-checker configuration, dependency lockfile, or alternate validation entry point. `AGENTS.md` names the full validation command as `.venv/bin/python3 -m unittest discover -s tests -q`.
- The environment audit is an important historical input: it recorded an earlier WSL execution plane with Python 3.12 and a Windows-format `.venv`. Its proposed broader readiness report included Docker and Codex, but also explicitly recommended a small deterministic base and keeping host integrations outside the repository contract.

## 3. Proposed checks

The preflight should evaluate checks in dependency order, retain every independently useful result, and return a stable check identifier with each result. A failed prerequisite makes dependent checks `SKIP`, rather than generating noisy secondary failures.

| ID | Check | Result required for `READY` | Rationale |
|---|---|---|---|
| `repo.root` | Locate the repository root from the script location; require `pyproject.toml` and `src/engineering_flow/__init__.py`. | The command is running from its own intact Engineering Flow checkout. | Avoids a passing result for a copied script or an arbitrary directory. |
| `repo.metadata` | Read `[project]` with stdlib `tomllib`; require name `engineering-flow`, a non-empty version, the declared console entry point, and `requires-python`. | Metadata needed by later checks is present and recognizable. | Keeps the readiness contract aligned with the tracked project metadata. |
| `git.worktree` | Invoke `git -C <root> rev-parse --show-toplevel --is-inside-work-tree`; require the reported top level to be the script's root. | This is a usable Git worktree for this checkout. | `AGENTS.md` makes Git state part of every work session. It supports both a normal checkout and `git worktree`. |
| `git.baseline` | Run `git status --porcelain=v1 -uno`; count entries and retain at most the first ten paths. | Always informational if Git itself works. | A dirty tree is often intentional and does not make the environment unusable, but agents must know their starting baseline. Untracked files are intentionally not enumerated: `-uno` avoids noise from local environments and generated files. |
| `venv.path` | Require an executable `<root>/.venv/bin/python3`. When absent, identify a detected `.venv/Scripts/python.exe` as a likely Windows-format environment. | Linux/WSL repository-local virtual environment exists. | This is the canonical runtime in `AGENTS.md`; no ambient interpreter fallback is permitted. |
| `python.contract` | Execute only that venv interpreter and compare `sys.version_info` to the simple bounded Python spec from `pyproject.toml` (currently `>=3.13,<3.14`). Require `sys.prefix` to resolve to `<root>/.venv`. | Correct Python minor version and a real repository-local venv. | Detects an incompatible interpreter, a symlink/activation mistake, and cross-platform venv reuse. The implementation may support only simple comma-separated `<`, `<=`, `>`, and `>=` integer version clauses; changing `requires-python` outside that subset must update this script in the same change. |
| `package.binding` | Under the venv interpreter, use `importlib.metadata` to locate distribution `engineering-flow`, import `engineering_flow`, and require its resolved module path to be within `<root>/src/engineering_flow`. | The project is installed and bound to this checkout (normally editable installation). | Import success alone can be produced by `PYTHONPATH`; this catches no installation, an installation from another checkout, and a stale non-editable wheel. |
| `cli.entrypoint` | Require executable `<root>/.venv/bin/engineering-flow`; run it with `--help`, capturing output, and require exit zero. | The console-script entry point can be resolved by the canonical invocation path. | This is the final, cheap proof that the documented application CLI is usable. It does not run a workflow or create application state. |

`READY` requires every check except `git.baseline` to pass. The preflight must continue after a failure where doing so is safe, so an invalid Python version and an unresolved CLI can be reported together. It must never create a venv, install a package, alter Git state, write a log, or invoke the application beyond `--help`.

## 4. Explicit non-goals

The following are deliberately excluded. Adding them would make the command slower, host-specific, network-dependent, or a substitute for actual validation.

- Running unit tests, import coverage, smoke workflows, database migrations, or any full/targeted validation.
- Creating, repairing, upgrading, activating, or deleting a virtual environment; running `pip install`; checking `pip`, build backends, package indexes, or dependency freshness. This project has no declared runtime dependencies today.
- Network, DNS, Git remote, GitHub, credentials, Codex authentication/version/health, MCP, plugin, browser, Docker, container, editor, shell, PATH, disk-space, CPU, memory, antivirus, or operating-system diagnostics.
- Requiring a particular absolute repository location, filesystem type, shell configuration, WSL distribution, Windows installation, Git branch, remote, upstream, or clean worktree.
- Enumerating a full diff, untracked files, Git history, submodules, stashes, Git configuration, signing configuration, or repository integrity. Those are separate diagnostics when needed.
- Linting, formatting, type checking, lockfile enforcement, CI equivalence, or adding any of those tools as an implied requirement.
- Validating Engineering Flow workflow artifacts or workflow state. Use the existing application `status`/`logs` commands and the applicable workflow Skill for that work.

## 5. Proposed implementation

Use a two-file, repository-owned launcher with no new third-party dependency:

```text
scripts/env-preflight              # small POSIX-sh executable launcher
tools/env_preflight.py             # stdlib-only implementation
```

The executable shell launcher is the canonical entry point. It resolves its own directory to the checkout root and invokes `python3 tools/env_preflight.py` solely to run the diagnostic. If no runnable host `python3` exists, the launcher emits the same bounded `ERROR` result for `runner.python` and exits with the environment-failure code. It must not fall back to the venv because detecting that venv is a primary job of the preflight.

The Python implementation must remain compatible with a reasonably old host Python sufficient to use `tomllib` (Python 3.11+). It reads metadata using `tomllib`, uses `pathlib`, `subprocess` with argument arrays and timeouts, `sys`, `importlib.metadata`, and `json`. It must never use shell interpolation. The selected venv interpreter, not the launcher interpreter, is the only interpreter used to inspect the project package and CLI.

This split is smaller and more reliable than making `env-preflight` a new `engineering-flow` subcommand: a missing package or broken console entry point would otherwise prevent the tool from explaining that very failure. It is also less scope than a Makefile/task runner or a new dependency-management tool.

Do not add a JSON dependency or a bootstrap command as part of this change. Keep the internal result model as a small list of records (`id`, `status`, `message`, optional bounded `detail`) so human and JSON renderers use identical facts and can be unit tested without subprocess-heavy integration tests. The implementation should include focused tests for each failure class by injecting command/file probes, plus a current-environment integration test only where stable.

## 6. Canonical invocation

From any directory in the checkout:

```sh
./scripts/env-preflight
```

The launcher must determine the root from its own resolved location, so callers do not need to `cd` to the root. It must provide an opt-in machine interface:

```sh
./scripts/env-preflight --json
```

There is no `engineering-flow env-preflight` command in the initial design. After the launcher is proven, an application-level alias can be considered only if it preserves the standalone command's ability to diagnose a missing package or CLI.

## 7. Exit codes and bounded output contract

Exit codes are process-level readiness categories; individual check IDs supply the exact remediation target.

| Exit code | Meaning |
|---:|---|
| `0` | `READY`: all required checks passed. A dirty baseline may be present and is reported as `WARN`. |
| `2` | `USAGE`: unsupported preflight option or malformed invocation. |
| `20` | `NOT_READY`: one or more required repository, Git, venv, Python, installation, or CLI checks failed. |
| `70` | `PREFLIGHT_ERROR`: the preflight itself could not complete deterministically (for example no host Python for the launcher, unreadable metadata, or an unexpected internal exception). |

Human output has a maximum of twelve lines: one summary line, at most one line per failing or warning check, and no successful-check lines unless `--verbose` is later intentionally added. A successful clean run is exactly one line:

```text
READY root=/path/to/engineering-flow python=3.13.15 package=editable cli=ok git=clean
```

A dirty successful run adds one bounded warning line, for example `WARN git.baseline dirty=3 paths=src/a.py,tests/test_a.py,docs/note.md`. Paths are relative, comma-separated, and capped at ten; append `+N more` when needed.

On `NOT_READY`, print `NOT_READY failed=<n>`, then one stable line per failure in dependency order, with a single actionable remedy. Never print tracebacks, `--help` output, a package list, environment variables, full Git status, or captured subprocess output by default. Captured stderr is trimmed to one sanitized line of at most 240 characters and appears only when it materially distinguishes the failure. `--json` emits exactly one JSON object on stdout and no other stdout text, with `schema_version`, `state`, `root`, `checks`, and `exit_code`; diagnostics remain on stderr only for a launcher-level failure.

The process must use short timeouts for Git and CLI probes (for example two seconds) and treat a timeout as a check failure. It must not retain a raw-log file: output is intentionally small enough that an owner can rerun the one failed command manually when deeper diagnostics are warranted.

## 8. Failure examples

```text
NOT_READY failed=1
FAIL venv.path expected executable .venv/bin/python3; create a Linux/WSL Python 3.13 venv for this checkout
```

```text
NOT_READY failed=2
FAIL python.contract found=3.12.3 required=>=3.13,<3.14; recreate .venv with a compatible Python
SKIP package.binding blocked_by=python.contract
```

```text
NOT_READY failed=2
FAIL package.binding distribution engineering-flow is not installed in .venv; install this checkout into its venv
SKIP cli.entrypoint blocked_by=package.binding
```

```text
NOT_READY failed=1
FAIL cli.entrypoint .venv/bin/engineering-flow did not run successfully; reinstall this checkout into its venv
```

```text
READY root=/home/bal/projects/engineering-flow python=3.13.15 package=editable cli=ok git=dirty
WARN git.baseline dirty=2 paths=docs/research/environment-preflight-design.md,src/engineering_flow/cli.py
```

For a Windows-format venv encountered from Linux/WSL, the `venv.path` failure should say `found .venv/Scripts/python.exe; do not reuse a Windows venv from Linux/WSL`, rather than attempting to execute it.

## 9. Interaction with AGENTS.md and future validation tooling

`AGENTS.md` remains the authority for runtime, validation, workflow boundaries, and context discipline. When implementation is approved, it should name `./scripts/env-preflight` as the first readiness command and continue to name `.venv/bin/python3 -m unittest discover -s tests -q` as full validation. The preflight must not reproduce the workflow Skills or replace their source-of-truth rules.

The relationship is intentionally sequential:

```text
env-preflight (environment and checkout readiness, read-only)
  -> task/workflow-specific work
    -> targeted or full validation (behavioral correctness)
```

A successful preflight says only that the prescribed interpreter, installed checkout, CLI, and basic Git worktree are usable. It does not claim tests pass, a change is correct, a workflow is valid, or a host integration is available. Future formatters, linters, type checks, lockfiles, or a validation wrapper should be added to the full-validation contract only after an approved quality policy. They should not be silently folded into preflight.

Git belongs in preflight only as a bounded baseline: confirm that this is the expected worktree and report dirty tracked state. It must not make a dirty worktree a failure, because developers commonly begin an approved continuation with legitimate changes and `AGENTS.md` asks them to inspect that fact rather than discard it.

## 10. Risks/trade-offs

- A POSIX launcher intentionally makes the first contract Linux/WSL-specific, matching `AGENTS.md`. Windows-native support should be added only with an equivalent tracked launcher and explicit testing; it must not cause Linux work to silently use Windows executables.
- Requiring a source-bound editable install is stricter than merely importing a package. That strictness prevents a developer from editing one checkout while invoking a wheel installed from another, which is a materially worse failure mode for agent work.
- The `tomllib` launcher dependency means a severely old or absent ambient Python yields `PREFLIGHT_ERROR` instead of a detailed venv diagnosis. The shell fallback still makes the missing runner explicit. This is preferable to bundling a parser or accepting an unverified metadata contract.
- `git status -uno` intentionally omits untracked files. This keeps output useful in repositories with local artifacts, but a user who needs to inspect untracked work must still run `git status --short` as prescribed by `AGENTS.md`.
- The preflight cannot prove an editable-install mechanism was used in every installer implementation; requiring the imported module to resolve under this checkout's `src` is the observable invariant that matters.
- The Python requirement parser is intentionally narrow. A future complex `requires-python` expression needs a corresponding, reviewed preflight update rather than a packaging-library dependency.
- Timeouts can produce a conservative false negative on a severely overloaded host. That is appropriate: a development agent should not begin expensive work when its core local probes cannot complete promptly.

Host-specific matters remain outside the repository contract: OS installation and patching, WSL distribution and filesystem placement, shell/PATH composition, Codex authentication/state/sandbox/plugins/MCPs, Docker integration, editor setup, credentials, network reachability, CPU/memory/disk capacity, and global Python provisioning. The preflight reports only what the checkout needs; it must not grow into a general machine diagnostic tool.

## 11. Recommendation

**ADOPT.** Implement the standard-library Python preflight behind a small repository-owned POSIX launcher, with `./scripts/env-preflight` as the canonical command. It directly prevents the documented high-cost interpreter/venv and installation/CLI failures, preserves a single bounded Git baseline warning, and deliberately leaves tests and host integrations to their proper contracts.
