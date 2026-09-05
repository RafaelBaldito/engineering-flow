# Codex Development Environment Audit

**Audit date:** 2026-09-05  
**Scope:** Analysis and recommendations only. No package, Codex configuration, Skill, MCP, OS, application, documentation, Git, or remote changes were made, apart from creating this requested report.  
**Evidence vocabulary:** **OBSERVED** = inspected directly; **INFERRED** = conclusion drawn from observed facts; **PROPOSED** = future change.  
**Scope labels:** `CROSS_PLATFORM`, `LINUX_WSL`, `WINDOWS`, `PROJECT_LOCAL`, `CODEX_GLOBAL`.

## 1. Executive Summary

This is already a promising environment for durable agentic engineering: Codex CLI is authenticated and healthy; Git is configured; the repository is clean; the Engineering Flow repository has a strong persisted-artifact workflow, twelve deliberately bounded workflow Skills, and a fast, dependency-free 90-test suite. The core problem is not lack of tools.

The largest friction comes from a split execution plane. Codex executes in Ubuntu/WSL, but the canonical repository lives on the Windows-mounted `9p` filesystem and its only `.venv` is Windows-format. The repository declares Python `>=3.13,<3.14`, while WSL exposes Python 3.12. That produces a non-canonical execution path: tests happened to pass with WSL Python 3.12, but the intended WSL interpreter and virtual environment cannot currently be invoked. The same split is visible in two separate Codex installations/configurations, two state stores, duplicated PATH entries, and a Docker Desktop CLI visible from WSL but not integrated with the distro.

The highest-return improvements are therefore:

1. Make a Linux-filesystem worktree plus a WSL Python 3.13 environment the canonical Linux/Codex path; retain the Windows checkout only when a Windows-native tool requires it.
2. Give each repository a small, factual `AGENTS.md` and one deterministic bootstrap/preflight/validation entry point. It should point to durable artifacts, not restate the Skills.
3. Use structured task handoffs and Codex JSON/schema output for independent sessions; reserve same-thread continuation for live debugging or a single implementation task.
4. Reduce repeated Skill boilerplate through shared references and progressive disclosure, without merging distinct authority boundaries such as task review, Wave review, and final review.
5. Treat output reduction as a measurement problem: start with bounded native commands and structured test summaries; only then run a controlled RTK pilot. RTK can reduce shell-output bytes, but it does not establish equivalent reductions in overall Codex quota, reasoning, cost, or latency.

No MCP server is an immediate priority. There are zero MCP servers configured in WSL. GitHub CLI (when its missing WSL binary is intentionally installed) is a simpler, lower-context first choice for GitHub operations. Browser, database, documentation, and repository-intelligence MCPs should be added only for a demonstrated capability gap and scoped to the least-privileged project or profile.

## 2. Current Environment Inventory

| Component | Observed state | Assessment |
|---|---|---|
| Host/execution OS | Windows host; Ubuntu 24.04.4 LTS on WSL2, Linux 6.18; `WSL_INTEROP` is set | A valid Linux-first Codex environment, but cross-OS integration needs a clear authority boundary. |
| Repository location | `/mnt/d/ProjetosAI/engineering-flow` on `9p`/DrvFS | Functional, but not the fast path for Linux Git, Python, test, or dependency operations. |
| Codex, WSL | Standalone Linux `codex-cli 0.152.1`; `doctor` reports 0.153.4 available | Healthy installation and authentication; update is available but should be trialed, not blindly adopted. |
| Codex, Windows | Separate `codex.exe` installation and separate `%USERPROFILE%\\.codex`; Windows configuration has plugins, `node_repl` MCP, notification, and elevated Windows sandbox | Windows and WSL behavior will differ materially. |
| WSL Codex configuration | `gpt-5.6-terra`, reasoning `high`; four trusted project paths; no MCP servers; no marketplace plugins | Simple, but high reasoning is the global default for every task and trusted-path entries include temporary worktrees. |
| WSL safety defaults | `doctor`: restricted filesystem/network and approval `OnRequest` | A good default. The audit runner's more permissive sandbox is not evidence of the user's normal Codex settings. |
| Windows safety | `[windows] sandbox = "elevated"`; several trusted projects | More permissive than WSL; needs explicit use boundaries. |
| Codex observability | `codex doctor`, `doctor --json`, `features`, `debug models`, `exec --json`, `--output-schema`, `--output-last-message`, `resume`, `fork`, `review`; 85 local rollout files / 92 session-index lines | Strong native primitives exist but are not yet standardized into an operating practice. |
| Codex session state | 85 active rollout files, ~60.37 MiB; local state DB integrity checks pass; app server is ephemeral/not running | Healthy, but accumulated session state is an observability and selection burden. |
| Git | Git 2.43.0; clean `main`; GitHub `origin` reachable; one detached temporary worktree exists | Good baseline. No WSL global Git aliases/includes or explicit cross-platform EOL policy were observed. |
| GitHub auth / CLI | Codex ChatGPT login is configured; WSL `gh` binary is absent | Git remote reachability does not prove GitHub CLI authentication. GitHub CLI was not inspectable in WSL. |
| Python | WSL `python3` 3.12.3; project requires 3.13; root `.venv` contains `Scripts/python.exe` and only Windows-format layout | This is the highest reliability issue found. |
| Project validation | 90 `unittest` tests completed successfully in 7.075 seconds using WSL Python 3.12 plus `PYTHONPATH=src`; output includes CLI noise after the test summary | Tests are fast and useful; this result does not validate the declared Python 3.13 target. |
| Project automation config | No Makefile, justfile, tox/nox, pytest config, linter/type-checker config, pre-commit config, or tracked `AGENTS.md` found | Everyday commands and interpreter selection are reconstructed by each session. |
| WSL tools actually resolvable | `rg` (bundled with Codex), Git, tmux; Docker Desktop shims visible but Docker reports WSL integration disabled | `fd`, `jq`, `yq`, `fzf`, `bat`, `tree`, `eza`, `zoxide`, `direnv`, `mise`, `uv`, Poetry, pipx, pytest, ruff, mypy, pre-commit, just, Node, and WSL `gh` were not resolvable in this invocation. |
| WSL PATH | 65 entries, with repeated Codex/local-bin/Git entries and extensive inherited Windows paths | Increases ambiguity and cross-platform executable leakage. |
| Docker | Windows Docker Desktop paths are inherited; `docker` says WSL integration is not enabled | Avoid treating Docker as available to WSL agents until integration is intentional and verified. |
| Repository Skills | Twelve local workflow Skills, 322–627 lines each, about 169 KiB total; no supplementary references/scripts/assets | Rich process guidance, but every selected Skill is long and duplicates policy language. |
| Global/remote Skills visible to this session | Six system Skills plus cached remote/plugin Skills; repository has its own twelve Skills | Keep global capabilities general and repository Skills domain-specific; do not duplicate workflow policy globally. |
| Project architecture | Durable PRD, Delivery Plan, architecture, TECHSPEC, task, review, remediation, and manual-acceptance artifacts; CLI supports `init`, `run`, `status`, `approve`, `reject`, `resume`, `intervene`, and `logs` | A major strength and an excellent foundation for session isolation. |

### Items deliberately not inspected

Authentication secrets, auth files, session transcripts, SQLite contents, browser profiles, GitHub account permissions, and provider billing/quota data were not read. Native Windows tool availability was sampled through `where`; full Windows settings, security controls, WSL resource settings, Docker Desktop settings, CI, branch protections, and user shell startup behavior were not exhaustively audited. No performance benchmark was run, so filesystem and tool-install recommendations are supported by topology plus vendor guidance, not a measured local speedup.

## 3. Current Strengths

- **OBSERVED — Durable workflow evidence.** Engineering Flow persists PRD, delivery, architecture, technical, task, task-review, Wave-review/remediation, and manual-acceptance artifacts. This is much better than relying on recalled chat state.
- **OBSERVED — Skill boundaries are unusually disciplined.** The local Skills distinguish product planning, architecture, technical design, task creation, task execution, task review, Wave review, remediation, and final review. The review Skills explicitly prevent self-acceptance and upstream-scope changes.
- **OBSERVED — Runtime design is defensive.** The application contains capability checks, worktree verification, JSON event normalization, structured output validation, session continuity handling, sanitization, status/log controls, and persisted lifecycle state.
- **OBSERVED — Deterministic validation is fast.** The all-test command completed 90 tests in about seven seconds with only the standard library test runner. That makes frequent targeted/full validation inexpensive.
- **OBSERVED — Core Codex health is good.** `codex doctor` passed 19 checks, including authentication, connectivity, state database integrity, thread inventory agreement, Git, and bundled `rg`.
- **OBSERVED — Native Codex has usable control primitives.** JSONL events, final-message files, JSON Schema-constrained final output, fork/resume, `review`, doctor JSON, and profiles can support reproducible automation without an MCP.
- **OBSERVED — The working tree was clean before this requested report.** That makes independent review and reproducible experiments practical.

## 4. Current Bottlenecks

1. **Interpreter/virtual-environment mismatch — OBSERVED.** The project requires Python 3.13; WSL uses 3.12; `.venv` is a Windows virtual environment and is unusable in Linux. This can yield false confidence, inconsistent dependency resolution, and agent turns spent rediscovering why `.venv/bin/python` fails.
2. **Cross-filesystem I/O — OBSERVED + INFERRED.** The Linux agent works against a `9p` mounted Windows drive. Microsoft explicitly recommends keeping a Linux-tool project in the Linux filesystem and identifies Linux processes operating in `/mnt/...` as the slower cross-filesystem path. [Microsoft WSL filesystem guidance](https://learn.microsoft.com/en-us/windows/wsl/filesystems)
3. **No canonical repository control surface — OBSERVED.** There is no AGENTS.md and no single bootstrap, preflight, test, lint, or status command. Agents must infer interpreter, path, output filtering, and validation conventions.
4. **Split Codex state/configuration — OBSERVED.** Windows and WSL have separate installations, auth/state, Skills, plugins, sandbox configurations, and path semantics. This is reasonable only if their responsibilities are explicit.
5. **High reasoning is default for all WSL Codex tasks — OBSERVED + INFERRED.** It may be appropriate for architecture and independent review, but applies equally to discovery, formatting, status checks, and mechanical fixes unless overridden.
6. **Long, standalone Skills repeat mechanics — OBSERVED.** The twelve local Skills contain repeated authority/precondition/rule/context/output boilerplate. `fix-wave-review` and `fix-final-review`, and `wave-review` and `final-review`, show substantial structural parallelism despite correctly different scopes.
7. **CLI availability ambiguity — OBSERVED.** Inherited Windows PATH entries expose Windows launchers to Linux, while many useful WSL-native commands are absent. Docker is a concrete example: it appears on PATH but fails when invoked.
8. **Stale approval-rule debt — OBSERVED + INFERRED.** Ten WSL allow rules include one-off temporary paths and broad Git add/commit/push patterns. They may be historical, but their value and blast radius cannot be determined from the rule list alone.
9. **Observability is available but not standardized — OBSERVED.** Codex state is healthy and Engineering Flow has logs/status, yet no common per-task execution record or machine-readable environment readiness record was observed.

## 5. Token / Context Consumption Analysis

### What is actually being reduced

| Optimization target | Meaning | Current risks / opportunity |
|---|---|---|
| Tool-output/context size | Bytes/tokens returned from commands to the model | Raw test output contains CLI prints; unbounded `rg`, full diffs, help, logs, and documents can dominate a turn. Use bounded, structured output first. |
| Model input tokens | Prompt, instructions, retrieved files, tool output, conversation history | Twelve lengthy Skills, large docs/code files, repeated discovery, and independent-session reconstruction are plausible contributors. Persisted artifacts already mitigate this when loaded selectively. |
| Model output tokens | The model's prose, plans, and implementation explanations | Long Skill completion templates and repeated restatement can encourage unnecessary narration. Require concise structured outcomes where prose adds no decision value. |
| Reasoning/computation | Hidden model work / latency associated with task complexity | WSL defaults to high reasoning even for low-risk discovery and mechanical work. Match the tier to task risk. |
| Agent turns | Separate model invocations and handoffs | Repeated environment discovery and manually reconstructed validation commands produce avoidable turns. Structured preflight and handoffs reduce this. |
| Weekly quota | Provider-specific billing/plan accounting | Not inspectable here. Tool-output reduction may reduce model input only when output is passed into the prompt; it does **not** by itself prove lower quota use. |

### Observed context surfaces

- **OBSERVED:** Local Skills total about 169 KiB and 5,927 lines. A selected Skill is 322–627 lines before project documents or code are read.
- **OBSERVED:** The repository contains large single files: `store.py` (105 KiB), `orchestrator.py` (56 KiB), the product vision (45 KiB), tests (up to 38 KiB), and TECHSPECs (20–25 KiB). Reading them wholesale is avoidable for most tasks.
- **OBSERVED:** 85 active rollout files average about 727 KiB. Session history can be useful, but broad session recovery or transcript inspection is a large context surface.
- **OBSERVED:** `python3 -m unittest discover -s tests -q` passes but emits workflow/CLI lines after the terse test summary. A wrapper can preserve raw logs outside the model context and return a small status summary.
- **OBSERVED:** The current shell PATH has 65 entries with repeats. This is not a major token cost itself, but it creates repeated diagnostic turns and ambiguous command failures.
- **INFERRED:** Independent sessions are frequent by stated workflow. The durable artifacts are the right answer; a standardized one-screen handoff manifest would eliminate repeated scan-and-summarize steps.

### Native first; RTK only as a measured experiment

RTK is a CLI proxy that compresses command output. Its own documentation correctly limits its claim: it controls command-output bytes, not prompt/system/history/output/reasoning tokens, quota, total cost, or task success. [RTK savings explanation](https://github.com/rtk-ai/rtk/blob/develop/docs/guide/resources/savings-explained.md) It advertises Codex integration through generated AGENTS/RTK instructions rather than a native Codex command interceptor. [RTK supported-agents documentation](https://github.com/rtk-ai/rtk)

For this environment, RTK is **P2 experimental**, not an immediate global dependency, for four reasons:

1. Native bounded commands (`rg -n -m`, `sed -n`, `git diff --stat`, targeted `unittest`, JSONL filtering) solve the most visible local waste without another interception layer.
2. A proxy can hide diagnostic detail, add failure-recovery steps, and create a second behavior to understand; full logs must remain addressable and opt-in.
3. This repository's full test run is already fast and modest. It needs summary discipline more than compression technology.
4. The audit has no provider token/usage telemetry with which to prove savings.

Run a paired, representative experiment before adopting it: same task class, fixed prompt/branch, RTK off/on, record raw output bytes, agent turns, elapsed time, validation result, and any re-reads. Stop if failures become harder to diagnose or total task efficiency does not improve.

## 6. Codex Configuration Analysis

### WSL Codex

**OBSERVED:** The WSL configuration is short: model `gpt-5.6-terra`, `model_reasoning_effort = "high"`, and trusted entries for the repository plus temporary worktree paths. `doctor` reports no MCP servers, no marketplace plugins, file-based ChatGPT auth, native Responses/WebSocket connectivity, restricted filesystem/network, and `OnRequest` approval. The app server is not persistent.

**Assessment:** Retain the restricted / on-request default as the normal interactive configuration. Do not replace it with `danger-full-access` or `never` globally. Prefer named profiles or explicit invocations for read-only discovery/review, normal workspace edits, and explicitly isolated automation. Use `--strict-config` in diagnostics after Codex upgrades.

**OBSERVED:** Version 0.153.4 is available while 0.152.1 is installed. Upgrade is not automatically P0: test upgrade behavior in a disposable repository/worktree using `doctor`, `exec --json`, output schema, project tests, and an existing Engineering Flow manual acceptance path before making it the default.

### Windows Codex

**OBSERVED:** Windows has its own Codex config with the same default model/reasoning, desktop plugins, a `node_repl` MCP, an elevated sandbox, notifications, and multiple trusted Windows projects, including this repository's Windows path. The WSL CLI does not inherit this configuration.

**Assessment:** Treat Windows Codex as a distinct client, not a fallback with assumed parity. Preserve separate auth/state and OS-native executables; share only reviewed, non-secret, cross-platform policy through a versioned template or repository instruction. Do not copy auth, sandbox approvals, SQLite state, transient sessions, Windows plugin paths, or MCP configurations across OS boundaries.

### Approval and trust

The broadest observed WSL allow rules include `git add -A`, commit, `git push origin`, and one-off temporary path operations. **PROPOSED:** review each rule's provenance and remove only rules that are demonstrably obsolete; then make one-purpose, narrow rules for recurring safe commands. A command that mutates arbitrary files or pushes a remote should not acquire global approval merely because it was useful in a past Wave test.

## 7. Skills Analysis

### Current organization

The repository's twelve Skills form a complete staged lifecycle:

`create-prd → plan-delivery → create-architecture-overview? → create-techspec → create-tasks → execute-task → review-task → fix-task? → wave-review → fix-wave-review? → final-review → fix-final-review?`

This is coherent. It reflects the repository's durable artifacts and should remain repository-local. General global Skills should cover generic operations (e.g., skill creation, image generation, OpenAI documentation), not Engineering Flow's approval/traceability rules.

### Duplication that can be reduced without changing behavior

**OBSERVED:** Every local Skill carries similar metadata, source precedence, preconditions, workflow mechanics, `MUST` / `MUST NOT` / `SHOULD`, context-management guidance, output templates, completion, and escalation language. The two remediation Skills and the two acceptance Skills differ primarily in scope-specific nouns, authority, artifact locations, and ownership routing.

**PROPOSED:** extract only genuinely invariant material into local references, for example:

- `references/authority-and-evidence.md` — source precedence, evidence standards, no fabricated validation, approved-scope preservation;
- `references/context-loading.md` — bounded discovery, context manifest pattern, output limits, document slicing;
- `references/review-findings.md` — finding IDs, severity/ownership/status vocabulary;
- `references/artifact-paths.md` — canonical locations and lifecycle artifact names;
- small templates for task, review, remediation, and completion records.

Keep the actual task, Wave, and release authority boundaries in the respective trigger Skill. Do **not** collapse `review-task`, `wave-review`, and `final-review` into one generic review Skill: their independence, acceptance authority, traceability chains, and remediation routing are materially different.

### Progressive disclosure

**PROPOSED:** Keep a front section short enough to select safely (purpose, trigger, exclusions, inputs, output, hard constraints), then reference only the required shared document for the selected task. A 322–627 line Skill can otherwise consume large context before the task contract is even opened. References must be narrow, versioned alongside the Skills, and loaded only if the requested work needs them.

### Missing reusable capabilities

The most useful new reusable items are not more prose Skills:

1. **PROJECT_LOCAL deterministic `env-preflight` command/script**: report OS, repo path class, Git worktree/cleanliness, Python executable/version, venv format, required commands, Docker reachability, Codex version/capabilities, and remediation hints in JSON/human formats.
2. **PROJECT_LOCAL deterministic `validate` command/script**: select interpreter, run targeted/full `unittest`, retain raw log by run ID, and emit a concise structured summary.
3. **PROJECT_LOCAL handoff manifest template**: one short artifact containing objective, authoritative paths, current commit/worktree, changed files, status, validation command/result, known blockers, and next role.
4. **PROJECT_LOCAL context-index convention**: a small task-local manifest lists exact required and optional files. `create-tasks` already describes this concept; make the artifact consistent and machine-checkable.

These reduce repeated prompting, discovery, and LLM reasoning more reliably than adding a generic “be concise” Skill.

## 8. MCP Opportunities

No MCP is currently configured for WSL. The matrix below is intentionally conservative.

| Category / recommendation | Problem solved | Native equivalent / why not MCP first | Productivity and token effect | Security and maintenance | Scope / decision |
|---|---|---|---|---|---|
| GitHub MCP | PR/issue/project metadata, comments, checks, review state | Git + web remote exist; WSL `gh` is missing. Prefer `gh` CLI for explicit, scriptable GitHub operations first. | Can avoid browser context and manual copy/paste; tool schemas/responses can also add context. | OAuth/token and write authority; version/API maintenance. | `CODEX_GLOBAL` only if used across repos; otherwise `PROJECT_LOCAL`. **Defer.** |
| GitHub CLI (not MCP) | Same core operational needs | CLI is lower-complexity, composes with scripts/JSON, and keeps capability explicit. | High for routine `pr`, `run`, `issue`, `api` JSON filtering; low tool-schema overhead. | Token scope still matters; normal CLI update burden. | `LINUX_WSL`, **P1** if GitHub workflow is routine. |
| Filesystem/repository intelligence MCP | Semantic repository search/symbol graph | `rg`, Git, language tooling, task manifests, and direct files are sufficient for this small Python repository. | A service can reduce repeated search only in much larger repos; adds indexing and stale-index risk. | Source-code exposure, index lifecycle, background resource use. | Do not add now. |
| Documentation MCP | Versioned docs/API lookup | Native web search and project-pinned docs are adequate. Use an official docs MCP only when a recurring, authenticated documentation corpus cannot be accessed otherwise. | Can reduce browsing turns, but retrieval payloads often increase context. | Access control, stale corpus, maintenance. | Do not add now. |
| Browser/web MCP | Browser automation | Windows already has browser/computer-use capabilities; WSL has native web capability in supported environments. | Useful only for repeatable UI-only workflows; costly in screenshots and traces. | High data/side-effect risk. | Per-profile, not global default. |
| Database MCP | Schema/data inspection | Use local CLI/client and parameterized scripts for known databases. | Useful for cross-database discovery, otherwise verbose and nondeterministic. | Highest production-data exposure risk. | Project-local and read-only only, if a concrete project requires it. |
| Observability MCP | Query logs/traces/metrics | Start with project JSONL events, local files, and CLI APIs. | Good for remote systems, but queries can return huge payloads. | Production credentials/PII/retention risk. | Per-project, read-only, query-limited only. |
| Test/CI MCP | CI job inspection/retry | `gh run` / vendor CLI and saved artifacts are simpler. | Useful after CLI workflow becomes insufficient. | Workflow-write authority and artifact exposure. | Defer. |

**Conclusion:** Add no MCP solely for “agent intelligence.” First make the existing CLI/JSON/artifact workflow deterministic. For a future GitHub integration, choose CLI before MCP and measure whether issue/PR/check work remains a repeated bottleneck.

## 9. Deterministic Tooling Opportunities

| Operation currently likely to require agent reasoning | Deterministic replacement | Why it matters |
|---|---|---|
| “Can I safely run this repo?” | `env-preflight --json` | Eliminates rediscovery of path, Git, interpreter, venv, Codex, Docker, and tool state. |
| “What exactly changed?” | `git diff --stat`, `--name-only`, selected file diffs, `git status --porcelain=v1` | Avoids a large unfiltered diff until a specific question requires it. |
| “Which documents matter?” | Task context manifest plus `rg -l` / `rg -n -m` | Replaces tree-wide reads with declared authority and line-addressable search. |
| “Did validation pass?” | Deterministic validation wrapper with JSON result and raw-log path | Prevents noisy console logs and makes validation evidence reusable in review. |
| “What workflow state is active?” | Engineering Flow `status` / `logs` plus a stable summary command | The product already models lifecycle state; do not infer it from documents. |
| “Is an artifact structurally valid?” | JSON Schema / front-matter / file-path / status validator | Reduces subjective rechecking and catches missing required evidence early. |
| “What does Codex support here?” | `codex doctor --json`, `codex exec --help`, capability report | Engineering Flow already performs runtime capability checks; expose a compact human-facing report rather than rereading help. |
| “Where are tests?” | `unittest` discovery plus explicit task validation manifest | Avoids test discovery reasoning and accidental wrong interpreter use. |
| “Can this independent session begin?” | Handoff manifest validation against commit/worktree/artifact IDs | Stops stale handoffs and lowers review contamination. |

Deterministic tools should emit a **small success summary** and place detailed raw output in an addressable local file. On failure, show the first actionable failure plus a stable log location; do not silently compress away diagnostics.

## 10. Session & Context Strategy

### Recommended operating model

| Work type | Thread choice | Required context | Handoff / isolation rule |
|---|---|---|---|
| Repository discovery / environment diagnosis | Fresh, read-only thread | Preflight JSON; targeted paths | End with a short observation artifact if it affects later work. |
| PRD, delivery, architecture, TECHSPEC | Fresh phase-owned thread | Approved upstream artifacts only | Persist the output; do not carry exploratory history into implementation. |
| One task implementation | Same thread across short iterative edits/debugs | One approved task, context manifest, relevant code/tests, current diff | Keep continuation only while the implementation problem is active; finish with handoff + validation summary. |
| Independent task review | Fresh thread | Task contract, diff/commit, relevant implementation/tests, validation result | Never reuse developer rationale as primary evidence. |
| Fix after review | Fresh or resumed fix thread, not the original review thread | Authoritative findings, task contract, minimal code/tests | Re-review independently after the fix. |
| Complex debugging | Same thread until hypothesis is resolved | Logs/hypotheses/experiments, capped context | Persist a concise debug ledger before the thread grows too large or a specialist is needed. |
| Architecture/research | Fresh, isolated thread | Explicit research question and source set | Store decisions, alternatives, uncertainty, and citations—not raw research transcript. |
| Final validation/release review | Fresh, independent thread | Accepted Wave artifacts, latest commit, deterministic validation evidence | No developer/reviewer conversation carryover. |

### Practical rules

- Reconstruct from durable artifacts when role independence matters, the task boundary changes, a decision is approved, or the thread is long/contaminated by discarded hypotheses.
- Keep the same thread for a coherent, short implementation/debugging loop where prior commands and failed hypotheses genuinely prevent repeated work.
- Use `codex resume` only for intended continuity; use `fork` when exploring an alternative without mutating the authoritative thread; use `--ephemeral` for throwaway command experiments that should not clutter persistent session selection.
- For automation, prefer `codex exec --json --output-schema <schema> -o <last-message>` and save the execution ID, schema version, raw JSONL location, final structured result, repository commit, and validation run ID.
- Do not treat a conversation summary as authoritative if a repository artifact exists. The artifact is the contract; the summary is a pointer.

## 11. Model / Reasoning Strategy

The installed CLI accepts model and reasoning overrides, but this audit did not obtain a reliable local catalog mapping every model to available reasoning levels. The following is an operating policy, not a claim that a particular tier always costs less or performs better. Validate names/availability with the installed CLI after updates.

| Task class | Recommended default | Reason |
|---|---|---|
| Status, environment discovery, file inventory, JSON validation, formatting, mechanical search | Fast/low reasoning where available; deterministic commands first | High reasoning is usually unnecessary when the answer is machine-verifiable. |
| Small localized edit with a clear contract | Default/medium reasoning | Balances correctness with iteration speed; use task context manifest. |
| Multi-file implementation, non-obvious test failure, design trade-off | Current `gpt-5.6-terra` at high reasoning | The cost is justified by ambiguity and correctness risk. |
| Architecture, cross-Wave design, threat/safety analysis | High reasoning, fresh thread | Requires broad synthesis and durable decisions. |
| Independent review | Same-or-better capability than implementation, medium/high reasoning, fresh thread | Review quality and independence matter more than raw speed. |
| Documentation from approved facts | Fast/default reasoning with a strict template | Avoid spending high reasoning to restate existing artifacts. |
| Deterministic test/status execution | No model choice required | Run the command and pass only a bounded result to the model. |

Set a normal default appropriate for ordinary implementation, then override upward for high-risk work and downward for mechanical work. Do not use lower reasoning to conceal an underspecified task: first improve the task contract and context manifest. Record model/reasoning selection in experimental telemetry before asserting quota savings.

## 12. WSL / Linux Recommendations

1. **Canonical Linux project location.** For Codex/WSL-first work, clone or maintain an authoritative active worktree under the Linux filesystem (for example `~/projects/engineering-flow`) and access it from Windows through `\\wsl.localhost\\…` when needed. Microsoft identifies `/mnt/...` as the slower path for Linux processes and recommends Linux storage for Linux tools. [Microsoft WSL interop guidance](https://learn.microsoft.com/en-us/windows/dev-environment/wsl-interop)
2. **One WSL Python target.** Install/provision Python 3.13 in WSL through the chosen supported mechanism, create a WSL-native virtual environment, and make the bootstrap command reject incorrect interpreter/venv formats. Never reuse a Windows venv from WSL.
3. **Minimize inherited Windows PATH.** Keep only intentional interop entries (for example `wsl.exe`/`explorer.exe` usage is not needed inside Linux; perhaps Git/Docker only if verified) and place Linux-native tools before them. This removes ambiguous launchers and unnecessary failed attempts.
4. **Docker either works or is absent.** If projects need containers, enable Docker Desktop WSL integration for this Ubuntu distribution and verify it with a small readiness command; otherwise remove Docker from the documented agent tool baseline. Docker documents that WSL integration is explicitly enabled per distribution. [Docker Desktop WSL integration](https://docs.docker.com/desktop/features/wsl/)
5. **Use Linux Git and credentials as the Linux authority.** Avoid mixed `git.exe` / Linux Git calls from the same worktree. Keep `core.filemode=false` as observed for the mounted Windows checkout; re-evaluate it for ext4 worktrees rather than copying it blindly.

## 13. Windows Recommendations

1. **Use Windows Codex only for Windows-native work.** Good candidates: desktop/browser/computer-use workflows, PowerShell-specific scripts, Windows UI validation, and a Windows-only repository. Do not assume WSL Skills, MCPs, session state, sandbox policy, or paths apply there.
2. **Treat elevated Windows sandbox and trusted projects as a higher-risk profile.** Keep the ordinary code path in WSL restricted/on-request. Review trusted paths periodically and avoid trusting parent folders such as a whole user directory unless the operating model requires it.
3. **Keep Windows Python environments Windows-native.** The observed `.venv` is a valid Windows Python 3.13 layout, but it should serve Windows command execution only. Use separate `.venv-win` / `.venv-linux` names or a documented external environment directory if one checkout must support both; never create two incompatible `.venv` layouts in the same shared checkout.
4. **Set an explicit cross-platform line-ending policy.** No global EOL policy was observed. Add a project-specific `.gitattributes` only after the intended rules are decided and tested; do not rely on host defaults.
5. **PowerShell modernization is optional.** PowerShell 5.1 was observed. Upgrade/use PowerShell 7 only if Windows automation/scripts need it; it is not a prerequisite for the Codex workflow.

## 14. Cross-Platform Strategy

### Share

- repository source, committed documentation, task/review/handoff artifacts, formatting/line-ending policy, deterministic scripts, test contracts, and non-secret tool version requirements;
- a small repository `AGENTS.md` describing facts that apply on both platforms, with platform-specific links rather than duplicated instructions;
- a versioned sample/manifest for Codex invocation modes, schemas, and output locations.

### Keep environment-specific

- Codex auth, local state databases, sessions/transcripts, approval rules, sandbox policy, plugin caches, browser state, OS executable paths, Python virtual environments, Docker socket/configuration, credential helpers, and local MCP configuration.

### Avoid

- one checkout under `/mnt/d` as the high-frequency build/test location for WSL;
- sharing a `.venv` across operating systems;
- copying Windows `config.toml` into WSL or vice versa;
- using Windows-installed tools incidentally because they appear in WSL PATH;
- treating a Windows Codex plugin/MCP as configured in WSL.

## 15. Engineering Flow Product Opportunities

This section is deliberately separate from personal environment changes. These are **potential product capabilities**, not approved roadmap work or implementation recommendations.

| Product opportunity | Evidence / rationale | Product value |
|---|---|---|
| Runtime readiness / preflight contract | The app already probes Codex capabilities and verifies worktrees; the audit found interpreter, Docker, filesystem, and PATH readiness gaps outside the runtime. | A provider-neutral readiness report could prevent failed workflows before an agent is invoked. |
| Structured context and handoff manifests | Existing Skills teach context manifests and the product persists lifecycle artifacts. | Canonical, machine-checkable handoffs can reduce reconstruction, improve independent reviews, and make run state inspectable. |
| Deterministic evidence validator | The runtime validates structured payloads and persists tasks/reviews, but artifact completeness is still largely process-driven. | Validate required artifacts, status transitions, hashes, test evidence, and provenance before review gates. |
| Execution telemetry / cost-neutral observability | The product normalizes JSON events and has `status`/`logs`; local Codex offers JSONL events. | Provide run timeline, role, model/reasoning metadata, command/test summaries, failures, retries, and context/output byte measurements without claiming billable-token savings. |
| Worktree / isolation manager | The runtime verifies Git worktrees and manual acceptance used disposable worktrees. | A controlled, cleanup-safe worktree lifecycle improves concurrent task isolation and reproducibility. |
| Provider capability matrix | Codex CLI capabilities vary by version and the app already checks them. | Persist capability reports and explain degraded behavior deterministically rather than relying on model interpretation of `--help`. |
| Output-budget protocol | Large logs and verbose tools are a common agent hazard. | Standardize raw-log retention plus concise machine-readable summaries, with a rehydrate-on-failure path. |

Do not turn every personal tool preference into a product dependency. In particular, RTK, shell enhancers, Windows plugins, and GitHub MCPs should remain optional environment integrations unless a product requirement demonstrates a provider-neutral need.

## 16. Quick Wins

All can be completed independently in roughly 30 minutes once implementation is authorized.

1. **R03 — Write a small project `AGENTS.md`**: canonical command entry points, source-of-truth artifacts, scope rules, output caps, platform caveat, and “do not read whole large files unless necessary.” Do not copy the Skills into it.
2. **R07 — Define bounded-command conventions**: add `rg -n -m`, line-range reads, `git diff --stat` before raw diff, `git status --porcelain`, and test-summary/raw-log behavior to the project operating guide.
3. **R04 — Adopt a one-page handoff manifest template** for task implementation/review/fix sessions.
4. **R06 — Review stale Codex allow rules** against current need; remove only verified obsolete one-off entries and avoid broad future patterns.
5. **R17 — Run an isolated Codex 0.153.4 compatibility smoke test** using `doctor --json`, JSONL output, and the project tests before choosing whether to update.

The WSL-native Python 3.13 environment and Linux-filesystem worktree are P0 but may exceed 30 minutes if data migration, tool installation, or organization policy is involved.

## 17. Prioritized Improvement Backlog

`Expected Benefit` uses the requested categories. `Token Impact` is deliberately conservative: it rates likely reduction in model-visible context, not provider quota unless independently measured.

| ID | Recommendation | Evidence | Scope | Type | Priority | Effort | Expected Benefit | Token Impact | Risk |
|---|---|---|---|---|---|---|---|---|---|
| R01 | Make an ext4/Linux worktree the canonical Codex/WSL execution copy; retain Windows copy only for Windows-native tasks. | OBSERVED / PROPOSED | LINUX_WSL | WORKFLOW | P0 | MEDIUM | PRODUCTIVITY, RELIABILITY, DEVELOPER_EXPERIENCE | LOW | Migration/copy divergence if both are edited. |
| R02 | Provision WSL Python 3.13 and a Linux-native venv; make bootstrap reject an incompatible interpreter or Windows venv. | OBSERVED / PROPOSED | LINUX_WSL, PROJECT_LOCAL | TOOL, SCRIPT_AUTOMATION | P0 | MEDIUM | RELIABILITY, PRODUCTIVITY | LOW | Tool/version bootstrap choice must be maintained. |
| R03 | Add a concise, factual project `AGENTS.md` that points to artifacts/scripts and defines output/context discipline. | OBSERVED / PROPOSED | PROJECT_LOCAL | CONFIGURATION, WORKFLOW | P0 | LOW | PRODUCTIVITY, TOKEN_CONTEXT, RELIABILITY | MEDIUM | An overgrown AGENTS file becomes another context tax. |
| R04 | Standardize a structured, short handoff manifest for task, review, fix, and validation sessions. | OBSERVED / PROPOSED | PROJECT_LOCAL | WORKFLOW | P0 | LOW | PRODUCTIVITY, TOKEN_CONTEXT, OBSERVABILITY | MEDIUM | Stale handoffs unless commit/worktree validation is automated. |
| R05 | Use explicit Codex run modes/profiles: read-only discovery/review, normal workspace editing, and isolated automation; retain restricted/on-request as default. | OBSERVED / PROPOSED | CODEX_GLOBAL, LINUX_WSL | CONFIGURATION, WORKFLOW | P0 | LOW | RELIABILITY, SECURITY, DEVELOPER_EXPERIENCE | LOW | Profile drift or accidental wrong mode. |
| R06 | Audit and prune demonstrably obsolete WSL approval rules; replace broad historical allowances with narrow recurring ones. | OBSERVED / PROPOSED | CODEX_GLOBAL | CONFIGURATION | P0 | LOW | SECURITY, RELIABILITY, OBSERVABILITY | NONE | Removing a needed rule introduces a prompt; broad rules are worse. |
| R07 | Establish deterministic bounded-output conventions and validation summaries with raw-log pointers. | OBSERVED / PROPOSED | PROJECT_LOCAL, CROSS_PLATFORM | SCRIPT_AUTOMATION, WORKFLOW | P0 | LOW | TOKEN_CONTEXT, PRODUCTIVITY, OBSERVABILITY | MEDIUM | Over-filtering can hide failures; raw logs must remain accessible. |
| R08 | Add an `env-preflight` command with human and JSON output for path, Git, Python, venv, tool, Docker, and Codex readiness. | OBSERVED / PROPOSED | PROJECT_LOCAL | SCRIPT_AUTOMATION | P1 | MEDIUM | RELIABILITY, PRODUCTIVITY, OBSERVABILITY | LOW | Script requires updates when environment contracts change. |
| R09 | Add one canonical bootstrap/validate interface selecting the interpreter and emitting structured test evidence. | OBSERVED / PROPOSED | PROJECT_LOCAL | SCRIPT_AUTOMATION | P1 | MEDIUM | RELIABILITY, PRODUCTIVITY, TOKEN_CONTEXT | MEDIUM | Do not mask individual test commands or platform-specific failures. |
| R10 | Extract shared Skill policy/templates into references while preserving role-specific trigger/authority sections. | OBSERVED / PROPOSED | PROJECT_LOCAL | SKILL | P1 | MEDIUM | TOKEN_CONTEXT, PRODUCTIVITY, RELIABILITY | MEDIUM | Bad extraction can weaken critical scope boundaries. |
| R11 | Make local Skills progressively disclosed: concise front matter plus only necessary references. | OBSERVED / PROPOSED | PROJECT_LOCAL | SKILL | P1 | MEDIUM | TOKEN_CONTEXT, DEVELOPER_EXPERIENCE | MEDIUM | Agent may fail to load a required reference; use explicit routing. |
| R12 | Adopt a task-based model/reasoning selection policy and log selections in experiments. | OBSERVED / PROPOSED | CODEX_GLOBAL, CROSS_PLATFORM | CONFIGURATION, WORKFLOW | P1 | LOW | PRODUCTIVITY, TOKEN_CONTEXT, DEVELOPER_EXPERIENCE | UNKNOWN | Lower reasoning can harm quality if task contracts are weak. |
| R13 | Simplify WSL PATH and document the intentionally supported Linux tool baseline. | OBSERVED / PROPOSED | LINUX_WSL | CONFIGURATION | P1 | MEDIUM | RELIABILITY, PRODUCTIVITY, DEVELOPER_EXPERIENCE | LOW | Removing an interop path can affect a valid workflow. |
| R14 | Enable and verify Docker WSL integration only if container workflows are actually required; otherwise declare Docker unsupported in WSL baseline. | OBSERVED / PROPOSED | LINUX_WSL | CONFIGURATION, TOOL | P1 | LOW | RELIABILITY, PRODUCTIVITY | LOW | Docker socket broadens host/container trust boundary. |
| R15 | Establish a single Git authority per worktree and test a committed cross-platform EOL policy. | OBSERVED / PROPOSED | CROSS_PLATFORM, PROJECT_LOCAL | CONFIGURATION, WORKFLOW | P1 | MEDIUM | RELIABILITY, DEVELOPER_EXPERIENCE | LOW | A mistaken `.gitattributes` change can churn files. |
| R16 | Document Windows-vs-WSL Codex responsibilities; share only non-secret policy, never auth/state/plugins/sandboxes. | OBSERVED / PROPOSED | CROSS_PLATFORM, CODEX_GLOBAL | ARCHITECTURE, WORKFLOW | P1 | LOW | RELIABILITY, SECURITY, DEVELOPER_EXPERIENCE | LOW | Policy must remain accurate as clients evolve. |
| R17 | Trial the available Codex update in an isolated worktree/profile with a compatibility checklist before normal use. | OBSERVED / PROPOSED | CODEX_GLOBAL | WORKFLOW, EXPERIMENT | P1 | LOW | RELIABILITY, PRODUCTIVITY | UNKNOWN | New version may change behavior or capability detection. |
| R18 | Standardize JSONL/schema/final-message capture and a run ledger for noninteractive Codex work. | OBSERVED / PROPOSED | PROJECT_LOCAL, CODEX_GLOBAL | SCRIPT_AUTOMATION, WORKFLOW | P1 | MEDIUM | OBSERVABILITY, RELIABILITY, TOKEN_CONTEXT | LOW | Captured logs may contain sensitive text; protect retention/access. |
| R19 | If GitHub work is routine, install/use WSL GitHub CLI with least-privilege auth and JSON-filtered commands before considering a GitHub MCP. | OBSERVED / PROPOSED | LINUX_WSL | TOOL | P1 | LOW | PRODUCTIVITY, OBSERVABILITY | LOW | GitHub token and write permissions. |
| R20 | Run a paired RTK experiment after native output controls are in place; adopt only on measured task-level benefit. | PROPOSED | LINUX_WSL, CODEX_GLOBAL | EXPERIMENT, TOOL | P2 | MEDIUM | TOKEN_CONTEXT, PRODUCTIVITY | UNKNOWN | Proxy behavior can obscure diagnostics or add complexity. |
| R21 | Add only `jq` and `fd` (or equivalents) if the preflight confirms repeated JSON/path-discovery friction; do not install a cosmetic shell suite by default. | OBSERVED / PROPOSED | LINUX_WSL | TOOL | P2 | LOW | PRODUCTIVITY, TOKEN_CONTEXT | LOW | Another dependency baseline. |
| R22 | Periodically archive/delete old Codex sessions via supported CLI after defining retention needs; use `--ephemeral` for throwaways. | OBSERVED / PROPOSED | CODEX_GLOBAL | WORKFLOW | P2 | LOW | OBSERVABILITY, DEVELOPER_EXPERIENCE | LOW | Loss of useful history if retention is not deliberate. |
| R23 | Create a deterministic worktree lifecycle helper only after concurrent tasks demonstrably conflict in a shared checkout. | OBSERVED / PROPOSED | PROJECT_LOCAL | SCRIPT_AUTOMATION | P2 | MEDIUM | PRODUCTIVITY, RELIABILITY | LOW | Cleanup bugs or accidental deletion; require safe target checks. |
| R24 | Add formatter/linter/type tooling only when a concrete repository quality policy is approved; integrate it into one validation command. | OBSERVED / PROPOSED | PROJECT_LOCAL, LINUX_WSL | TOOL, SCRIPT_AUTOMATION | P2 | MEDIUM | RELIABILITY, PRODUCTIVITY | LOW | Tool noise/config churn without an agreed standard. |
| R25 | Add GitHub MCP only if CLI/browser workflows leave a measured issue/PR/check gap. | PROPOSED | CODEX_GLOBAL or PROJECT_LOCAL | MCP | P2 | MEDIUM | PRODUCTIVITY, OBSERVABILITY | LOW | Extra credential, schema, maintenance, and write surface. |
| R26 | Add documentation/browser/database/observability MCPs only for a named service and read-only, bounded query contract. | PROPOSED | PROJECT_LOCAL | MCP | P2 | HIGH | PRODUCTIVITY, OBSERVABILITY | UNKNOWN | Sensitive data, huge payloads, stale indexes, maintenance. |
| R27 | Upgrade to PowerShell 7 only if Windows automation requires it. | OBSERVED / PROPOSED | WINDOWS | TOOL | P3 | LOW | DEVELOPER_EXPERIENCE | NONE | Another shell/version to support. |
| R28 | Add fzf, bat, eza, zoxide, or similar shell UX tools only after core workflow is stable. | OBSERVED / PROPOSED | LINUX_WSL | TOOL | P3 | LOW | DEVELOPER_EXPERIENCE | NONE | Cosmetic complexity and divergent command output. |
| R29 | Consider a persistent Codex app server only after JSONL/run-ledger observability and session patterns demonstrate a need. | OBSERVED / PROPOSED | CODEX_GLOBAL | ARCHITECTURE, EXPERIMENT | P3 | HIGH | OBSERVABILITY, PRODUCTIVITY | UNKNOWN | Daemon lifecycle, security, and operational complexity. |
| R30 | Consider product-level environment/readiness, context-manifest, evidence-validator, telemetry, and worktree capabilities only through normal Engineering Flow planning. | OBSERVED / PROPOSED | PROJECT_LOCAL | ARCHITECTURE | P3 | HIGH | PRODUCTIVITY, TOKEN_CONTEXT, RELIABILITY, OBSERVABILITY | MEDIUM | Scope expansion; must not become personal-tool coupling. |

### Priority count

- **P0:** 7 recommendations
- **P1:** 12 recommendations
- **P2:** 7 recommendations
- **P3:** 4 recommendations

## 18. Recommended Experiments

| Experiment | Hypothesis | Method / success criteria | Stop condition |
|---|---|---|---|
| E01: Linux worktree + Python 3.13 | Native Linux filesystem and interpreter reduce friction and make validation canonical. | Duplicate/clone a disposable worktree under ext4; create WSL venv; run preflight and full suite; compare elapsed time and failure/retry count with `/mnt/d`. | Any unexplained source divergence or Windows-only workflow break. |
| E02: Output-contract baseline | Bounded native commands and summarized test logs reduce model-visible output without diagnostic loss. | Run five representative tasks; record command-output bytes, agent re-reads, turns, test outcome. | Agent must repeatedly recover raw logs or misses failures. |
| E03: RTK paired pilot | RTK adds material benefit beyond E02. | Same representative task class, fixed prompts/branches; RTK off/on; record output bytes, elapsed time, turns, validation, raw-log recovery. | No task-level gain, correctness regression, or debugging overhead. |
| E04: Skill progressive-disclosure pilot | Short trigger sections + references preserve scope and reduce loaded context. | Convert one pair only in a branch; independently check trigger correctness, required-reference loading, and output quality. | Any authority/safety rule is missed or reviewers find ambiguity. |
| E05: Codex upgrade smoke test | 0.153.4 remains compatible with Engineering Flow assumptions. | Isolated worktree: `doctor --json`, `exec --json`, schemas, tests, and a known capability check. | Capability contract or structured event parsing changes unexpectedly. |
| E06: GitHub CLI versus MCP | CLI is sufficient for normal GitHub work. | Time ten real read-only issue/PR/check operations with concise JSON queries; document unmet operations. | A recurring operation remains awkward, verbose, or unobservable with CLI. |

## 19. Proposed Target Development Environment

```text
Windows host
  ├─ Windows-native Codex: UI/browser/PowerShell-only work
  │    └─ separate auth, state, sandbox, plugins, native Python venvs
  └─ WSL Ubuntu (canonical engineering execution)
       ├─ ~/projects/<repo>              # ext4 active worktrees
       ├─ Linux Python 3.13 + Linux venv # never the Windows .venv
       ├─ Linux Git + explicit credential/EOL policy
       ├─ Codex restricted/on-request normal profile
       ├─ read-only / edit / isolated-automation invocation modes
       ├─ minimal native baseline: Git, Python, rg; jq/fd only if measured useful
       └─ Docker integration only if containers are an explicit project need

Repository (versioned, cross-platform)
  ├─ concise AGENTS.md → authoritative artifacts and deterministic commands
  ├─ bootstrap / env-preflight / validate commands with JSON summaries
  ├─ task context manifests and structured role handoffs
  ├─ repository-local lifecycle Skills with shared references
  ├─ raw logs retained outside agent context; concise summaries in evidence
  └─ no mandatory MCP or output-compression proxy without measured benefit
```

This target intentionally prefers a small, deterministic base to a large agent plugin/tool stack. The system is easier to reproduce because its decisions are committed as artifacts and scripts, while secrets, state, sandbox, and OS-specific integration stay local.

## 20. Recommended Implementation Sequence

1. **Baseline and protect:** save the current environment evidence; decide the Windows/WSL responsibility boundary; review stale approval rules; retain WSL restricted/on-request defaults.
2. **Make Linux execution real:** establish a disposable ext4 worktree, WSL Python 3.13, Linux-native venv, and one proven full validation command. Do not retire the Windows path until Windows-native needs are tested.
3. **Create deterministic repository entry points:** implement preflight, bootstrap, validate, raw-log/summary handling, and a concise AGENTS.md. Add no MCP and no RTK yet.
4. **Operationalize sessions:** use handoff manifests, independent review threads, JSONL/schema capture for noninteractive runs, and explicit thread lifecycle conventions.
5. **Reduce instruction overhead safely:** refactor shared Skill material and pilot progressive disclosure on one Skill pair, with independent review of scope preservation.
6. **Fill demonstrated gaps only:** add WSL GitHub CLI if needed; enable Docker integration only when containers are used; add `jq`/`fd` only if preflight/task evidence shows repeated friction.
7. **Run controlled experiments:** Codex update compatibility, output baseline, RTK, and GitHub CLI-versus-MCP. Keep only changes with measurable task-level benefits.
8. **Consider product capabilities through formal planning:** convert validated recurring environment/context/evidence problems into Engineering Flow product proposals, not ad hoc workflow changes.

## Appendix A — Inspection Basis

The audit directly inspected: WSL OS/mount state; Codex version, help, doctor, feature inventory, configuration (excluding secrets), login state, MCP/plugin state, session-state health, approval-rule count/content, and command capabilities; Windows Codex config/installation/Skill inventory at a non-secret level; Git config/status/remote/worktrees; project layout, metadata, Skills, artifacts, source capability signals, and test suite; WSL tool resolution and Docker reachability; and native Windows executable presence. The repository test suite was run once with WSL Python 3.12 and completed 90 tests successfully in 7.075 seconds.

The audit used official Microsoft WSL guidance, Docker documentation, and RTK's own documentation only to qualify proposed operational claims. Their content does not establish local performance or provider quota savings.
