# WSL CLI Tooling Prioritization

**Date:** 2026-09-05  
**Scope:** Personal WSL terminal and Codex development environment analysis. This is not a repository dependency decision and does not change Engineering Flow, its Skills, workflow contracts, validation command, or Wave 3.

## Recommendation

Adopt only **`fd`** and **`jq`** now, as personal WSL tools. Keep the already working `rg`, `gh`, and `tmux`. Everything else is either deferred until an observed need arises or rejected because native shell/Python/Git tools already meet the present need.

The environment is a working Linux/WSL Python 3.13 checkout with a repository-local `.venv`, a single declared full-validation command, native bounded-output discipline, adopted Context7, `rg`, authenticated Linux `gh`, and `tmux`. Docker's Windows shim is on `PATH`, but its WSL integration is disabled, so Docker is not currently usable from this WSL distribution.

## Inspection basis

- `git status --short`: clean worktree.
- `./scripts/env-preflight`: passed (`python=3.13.15`, editable package and CLI working).
- Repository tooling: `pyproject.toml` has no runtime dependencies; no tracked formatter, linter, type-checker, pre-commit, Makefile, justfile, Dockerfile, or Compose configuration exists. The authoritative full validation remains `.venv/bin/python3 -m unittest discover -s tests -q`.
- Commands found: `rg` 15.2.0, `gh` 2.100.0, Git 2.43.0, `tmux`, `fdfind` 9.0.0, and `jq` 1.7. `gh auth status` succeeds. `docker` resolves to Docker Desktop's Windows shim but reports that WSL 2 integration is disabled.
- `fd` implementation: Ubuntu package `fd-find` installed `fdfind` 9.0.0 at `/usr/bin/fdfind`; user-local `~/.local/bin/fd` symlinks to it. `command -v fd` returned `/home/bal/.local/bin/fd`; `fd --version` returned `fdfind 9.0.0`.
- `jq` implementation: installed through APT as `jq-1.7` at `/usr/bin/jq`.
- Commands absent: `fzf`, `bat`, `tree`, `eza`, `zoxide`, `direnv`, `uv`, `pipx`, `just`, `ruff`, `mypy`, and `pre-commit`.

`rg --files`, `find`, `sed`, `head`, `tail`, shell pipelines, Python's standard library, Git, and `gh --json`/built-in `--jq` remain sufficient alternatives where stated below. Native bounded-output discipline is already the primary control; no output-proxy tool is proposed.

## Tool decisions

| Tool | Installed / classification | Practical value and Codex effect | Bounded inspection, overlap, and cost | Scope / future capability |
|---|---|---|---|---|
| `fd` | `fd-find` installed — **ADOPTED** | Fast, readable file discovery for a developer and Codex: `fd -e py`, `fd -a TASK- tasks/`, and scoped document lookup. It complements content-first `rg`; it is especially useful when filenames, extensions, or path filters are known. | Reduces discovery noise when paired with `-d`, `-e`, or a narrow root. `find` and `rg --files` suffice but are less ergonomic for repeated path queries. One small OS package; no runtime dependency. | Personal WSL only. A future Flow context-manifest/readiness capability may use equivalent path selection internally, but must not require the user's `fd`. |
| `jq` | APT installed — **ADOPTED** | Shapes small JSON results from local diagnostics, `gh api`, future CLIs, and data files without writing throwaway Python. Codex benefits directly when a command exposes JSON but needs a few fields. | Use only after an upstream limit/field selection. `gh --jq` already covers its own JSON, but not all JSON commands. Python can parse JSON, at higher ceremony. One small OS package; no project dependency. | Personal WSL only. A future Flow machine-readable readiness/evidence interface could emit bounded JSON; it must not depend on `jq`. |
| `fzf` | Missing — **ADOPT_LATER** | Good interactive history, file, branch, and log selection for the developer. Codex normally names exact paths/commands, so direct benefit is low. | Can narrow an interactive list, but its preview bindings can produce noisy output and it overlaps shell completion/history. Shell setup/key bindings add small ongoing complexity. | Personal-only convenience; no Flow capability implied. Adopt only if interactive navigation is repeatedly awkward. |
| `bat` | Missing — **NOT_NEEDED** | Syntax-highlighted interactive file viewing only; Codex gets no material benefit. | `sed -n`, `head`, and `tail` better express bounded line ranges and avoid ANSI/color handling. Adds an alias/configuration choice. | Personal-only; no Flow role. |
| `tree` | Missing — **NOT_NEEDED** | Occasional human hierarchy glance, but no recurring repository need. | Unbounded trees are exactly the kind of context noise the current discipline avoids. `fd -d 2` (if adopted) or `find -maxdepth` is more controllable. | Personal-only; no Flow role. |
| `eza` | Missing — **NOT_NEEDED** | Cosmetic `ls` enhancement; no meaningful Codex advantage. | Overlaps `ls`/`find`, produces divergent icon/color output, and needs alias decisions. | Personal-only; no Flow role. |
| `zoxide` | Missing — **ADOPT_LATER** | Faster interactive directory jumping can help once many WSL worktrees/projects are active. Codex uses explicit working directories, so no direct gain. | Does not improve repository inspection; overlaps `cd`, shell history, and `pushd`/`popd`. Requires shell-hook setup and a learned database. | Personal-only. Reconsider after a demonstrated multi-worktree navigation burden. |
| `direnv` | Missing — **NOT_NEEDED** | Automatic per-directory environment loading is unnecessary for the present single `.venv` contract. | It can hide environment changes and requires approving/maintaining `.envrc` files. Explicit `.venv/bin/...` commands and `env-preflight` are more deterministic. | Do not make Flow depend on developer shell state. Reconsider only for a separately approved multi-project secrets/config workflow. |
| `uv` | Missing — **NOT_NEEDED** | Fast Python environment/package tooling, but this dependency-free project already has a functioning repository-local `.venv` and prescribed interpreter. | Overlaps `venv`/`pip`; adopting it now creates a second environment/lockfile policy with no approved migration. | Personal-only if ever used. A future project packaging decision requires explicit design, not personal-tool adoption. |
| `pipx` | Missing — **ADOPT_LATER** | Clean isolation for future personal Python CLI utilities. It has no current target: the recommended immediate tools are OS packages, and project tools belong in the project environment only if approved. | Avoids global `pip` pollution but adds another tool-install/update path. Native venv is sufficient today. | Personal-only; never a Flow runtime dependency. |
| `just` | Missing — **NOT_NEEDED** | No present command matrix warrants a task runner. The repository has one explicit preflight and one full validation command. | Overlaps shell scripts and documented commands; a justfile would become another contract to maintain and risks obscuring exact validation. | A future Flow CLI can expose stable commands directly; do not introduce `just` preemptively. |
| `ruff` | Missing — **ADOPT_LATER** | Could provide fast linting/formatting after a concrete, approved code-quality policy exists. Codex may benefit from deterministic checks then. | Currently overlaps no approved repository rule and would require version/configuration plus deciding whether it gates validation. Python/unittest handles current declared validation sufficiently. | Potential future Flow capability only as an optional quality-check adapter with explicit policy and output contract. |
| `mypy` | Missing — **ADOPT_LATER** | Useful only when type-checking policy, coverage boundary, and configuration are explicitly chosen. | Adds annotations/configuration, dependency resolution, and possible third-party stubs. Existing tests and runtime checks are the current contract. | Potential optional future validation adapter; never silently impose a type policy. |
| `pre-commit` | Missing — **NOT_NEEDED** | No approved hooks or quality tools exist to run. Client-side hooks can surprise multi-agent or noninteractive commits. | Overlaps explicit validation and needs hook/environment/version maintenance. Git hooks alone are sufficient if a narrowly justified hook later appears. | A future Flow delivery gate should run deterministic checks directly, rather than rely on a developer-local hook. |
| `tmux` | Present — **KEEP_EXISTING** | Valuable for the developer: persistent panes for server/tests/logs and concurrent worktrees. Codex's own agent orchestration does not require it, but it helps attended multi-agent observation. | Does not itself bound output; use separate panes/log files and focused commands. Minimal existing operational cost. | Personal WSL utility only. A future Flow handoff/run-observability feature should be terminal-independent. |
| `ripgrep` (`rg`) | Present — **KEEP_EXISTING** | Core tool for both developer and Codex content discovery, targeted filenames (`rg --files`), and line-addressable bounded searches (`-n`, `-m`, globs). | Directly supports the adopted bounded-context discipline. It overlaps some `fd` path enumeration, but not content search; keep both roles distinct. Already available through Codex's path; no new action. | Personal/tooling baseline only; product code must not assume it is installed. |
| GitHub CLI (`gh`) | Present and authenticated — **KEEP_EXISTING** | Adds hosted GitHub PR, issue, review, check, and Actions state that Git lacks; useful to both developer and Codex with explicit repo, `--limit`, selected `--json` fields, and built-in `--jq`. | Bounded GitHub queries are already documented. It overlaps `jq` only for `gh` JSON filtering. Auth and remote-write authority are the operational cost; writes remain explicit. | Personal WSL tool. A future provider-neutral controlled-delivery/reconciliation adapter is possible only through normal product planning. |
| Docker CLI / WSL integration | Windows shim present; unusable in WSL — **ADOPT_LATER** | No Dockerfile/Compose/container validation is present, so enabling integration would not serve the current repository. It may matter for future projects that genuinely need containers. | Native Python/venv and unittest solve current validation. Enabling integration adds daemon lifecycle, images, disk use, and a container/host trust boundary. | Personal WSL integration only when a concrete container workflow appears. A future Flow environment capability may report container readiness but must treat Docker as optional. |

## Prioritized adoption plan

### Tier 1: adopted and operational

1. **`fd`** — installed through Ubuntu package `fd-find`; `/usr/bin/fdfind` is exposed as `fd` through `~/.local/bin/fd`. Use it for explicitly scoped filename/path discovery; preserve `rg` for content discovery.
2. **`jq`** — installed through APT at `/usr/bin/jq`. Use it to project already-bounded JSON results; prefer `gh --json` plus `gh --jq` for GitHub-only requests.

No aliases, repository configuration, validation changes, or Engineering Flow integration are required for either tool.

### Tier 2: useful later

- **`fzf`** — only after repeated interactive file/history/branch selection friction.
- **`zoxide`** — only after many WSL projects/worktrees make directory navigation measurably annoying.
- **`pipx`** — only when a separate personal Python CLI genuinely needs isolated installation.
- **`ruff`** — only with an approved repository quality policy, pinned/configured behavior, and one canonical validation integration.
- **`mypy`** — only with an approved type-checking boundary and configuration.
- **Docker WSL integration** — only when a project has a real container build, service, or validation requirement; verify it before treating Docker as available.

### Tier 3: skip unless a concrete need appears

- **`bat`**, **`tree`**, **`eza`** — cosmetic or less bounded alternatives to present shell patterns.
- **`direnv`** — automatic directory-local environment state conflicts with the current explicit venv/preflight approach.
- **`uv`** — no migration need while the required `.venv` workflow works.
- **`just`** — no command-automation gap exists.
- **`pre-commit`** — no approved hook policy or checks exist.

## Strongest productivity and Codex-specific wins

- **Productivity:** `fd` makes intentional path discovery compact and readable; `jq` prevents one-off JSON-parsing scripts. `tmux` remains the existing aid for attended concurrent work.
- **Codex-specific:** `rg` remains the primary bounded repository-inspection tool. `fd` supplies the missing filename/path counterpart, while `jq` turns limited JSON into exact facts. `gh` already supplies bounded hosted-GitHub state. None replaces the existing discipline of limiting results before filtering them.

## Potential future Engineering Flow capabilities

These are product ideas only, not authorized work: an optional environment/capability report that detects available tools; a provider-neutral GitHub delivery/reconciliation adapter; a deterministic optional quality-check adapter for an approved linter/type checker; a terminal-independent run/handoff evidence view; and a safe worktree coordinator if concurrent task work proves to need it. Each must use declared interfaces and fallbacks rather than require personal WSL tools.

## Blockers

None for Tier 1; it is fully adopted and operational. Docker is explicitly blocked from WSL use until Docker Desktop WSL integration for this distribution is intentionally enabled and verified. Tier 2 quality tools are blocked on an approved repository quality policy; no such policy or configuration currently exists.
