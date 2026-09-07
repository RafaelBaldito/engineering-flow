# Codex subagent workflow discovery

**Recommendation: EXPERIMENT_FIRST.** Codex CLI 0.153.4 has an enabled, stable `multi_agent` capability and the active model environment exposes collaboration tools that can create named child agents, select a bounded parent-history fork, monitor agents, send follow-ups, interrupt them, and receive their terminal result. A child created with `fork_turns="none"` did not receive a parent-only marker in the controlled experiment. That makes the proposed host/coordinator/developer/reviewer/fixer bootstrap feasible with constraints. It is not strong isolation, because the child still shares the checkout, current directory, project instructions, and available tool/configuration surface.

The recommended initial implementation is a deliberately narrow pilot with persisted Markdown state and a fresh reviewer child for every review/re-review. Do not use the default full-context fork for an independent review.

## Scope and evidence labels

- **OBSERVED locally** means a command, active model tool contract, or controlled run in this environment established it.
- **DOCUMENTED officially** means official OpenAI documentation established it; it is supplemental to local behavior.
- **INFERRED** is a conclusion from the observed facts.
- **UNKNOWN** means this discovery did not establish it.

## Inspected environment

| Item | Finding | Evidence |
| --- | --- | --- |
| Repository | `/home/bal/projects/engineering-flow`; clean before the requested artifact | **OBSERVED locally:** `git status --short`, `./scripts/env-preflight` |
| Codex binary | `/home/bal/.local/bin/codex` resolving to the 0.153.4 standalone release | **OBSERVED locally** |
| Version | `codex-cli 0.153.4` | **OBSERVED locally:** `codex --version` |
| Default local model/effort | `gpt-5.6-terra`, `medium` | **OBSERVED locally:** non-secret `~/.codex/config.toml` fields |
| Feature state | `multi_agent`: stable, `true`; `multi_agent_v2`: stable, `false` | **OBSERVED locally:** `codex features list`; no flag changed |
| Model metadata | `gpt-5.6-terra`, `gpt-5.6-sol`, and `gpt-6-astra` advertise multi-agent version `v2`; all list low through ultra effort levels | **OBSERVED locally:** `codex debug models --bundled` |
| Local app-server daemon | No reachable daemon control socket at inspection time | **OBSERVED locally:** `codex app-server daemon version`; this is not evidence that agent collaboration is unavailable in the active host |

`codex --help` also exposes `agents` (browse sessions on the shared local app-server daemon), `fork`, `resume`, `queue`, `features`, `debug`, `mcp`, `plugin`, and experimental app-server commands. The `agents` command has no noninteractive `list` subcommand in this release.

Official OpenAI guidance says that models can be prompted to delegate to subagents through collaboration tools, including parallel delegation, but describes this as harness behavior to tune rather than an isolation guarantee. [Model guidance: subagent delegation](https://developers.openai.com/api/docs/guides/latest-model#subagent-delegation) **DOCUMENTED officially.**

## Observed subagent architecture and capabilities

The active model exposes these collaboration operations:

| Capability | Finding |
| --- | --- |
| Spawn | **OBSERVED locally:** `spawn_agent` takes a task name, explicit message, optional model, optional reasoning effort, and `fork_turns` of `none`, `all`, or a positive turn count. |
| Context selection | **OBSERVED locally:** default fork is `all`; `none` is documented in the active tool contract as passing no surrounding context; a positive count passes only the most recent parent turns. |
| Named role/task | **OBSERVED locally:** caller supplies a lowercase task name; no separate role/type selector exists. Role is therefore an explicit bounded task prompt plus repository instruction/skill selection. |
| Parallel/nested work | **OBSERVED locally:** up to four active agents are available in this host, including root; children have the same capability to spawn descendants. |
| Lifecycle | **OBSERVED locally:** `list_agents`, `wait_agent`, `send_message`, `followup_task`, and `interrupt_agent` are available. Follow-up work can wake an idle child. |
| Result collection | **OBSERVED locally:** a child terminal response is delivered to its parent as a named `FINAL_ANSWER`; messages are also delivered in the parent mailbox. |
| Cancellation | **OBSERVED locally:** `interrupt_agent` interrupts a running child, retaining it as a messageable agent. Full terminal-state semantics after interruption were not separately tested. |
| CLI session operations | **OBSERVED locally:** `fork`, `resume`, and `queue` act on persisted interactive sessions; these are distinct from the active model's collaboration tools. |
| Worktree handling | **OBSERVED locally:** there is no spawn parameter for a separate worktree. The experiment child used the same checkout. |
| Per-child sandbox/approval | **OBSERVED locally:** no such spawn parameter is exposed. The standalone CLI can set them for a new/forked CLI session, but that is a different mechanism. |
| Structured result schema | **UNKNOWN:** collaboration results are typed as text content in this host contract, not a caller-defined JSON schema. Persisted Markdown and machine-validated status fields are required if the coordinator needs durable structured transitions. |

There is no observed `/agents` slash command in the noninteractive CLI help. `codex agents` is a CLI command for app-server session browsing. The stable enabled `multi_agent` feature, rather than disabled `multi_agent_v2`, is the locally effective feature signal. The apparent `v2` model metadata should not be treated as proof that the disabled feature is active.

## Inheritance matrix

| Item | `fork_turns="none"` child | Full/partial fork child | Basis and limit |
| --- | --- | --- | --- |
| Explicit task message | Yes | Yes | **OBSERVED locally:** required `message` argument. |
| Parent conversation/reasoning | No surrounding context passed; marker absent in experiment | All by default, or the selected most-recent turns | **OBSERVED locally:** tool contract plus experiment. A model may still see shared files. |
| `AGENTS.md` and project instructions | Yes | Yes | **OBSERVED locally:** experiment child confirmed availability. |
| Repository / worktree | Same working tree | Same working tree | **OBSERVED locally:** experiment child cwd was the repository; no worktree isolation selector. |
| Working directory | Same repository cwd in experiment | Expected same unless host changes it | **OBSERVED locally** for `none`; full-fork variant not run. |
| Model | Parent model inherited when no override is provided; explicit override supported only with non-full context handoff in the active tool contract | **UNKNOWN** whether override is permitted with an all-context fork | **OBSERVED locally:** contract states inherited parent model and optional override semantics. |
| Reasoning effort | Parent effort inherited when no override is provided; explicit override supported under the same constraint | **UNKNOWN** whether override is permitted with an all-context fork | **OBSERVED locally.** |
| Sandbox / approval | Host runtime capability/permission surface appears shared; no per-child selector | Same | **INFERRED** from exposed contract. Do not assume isolation. |
| Environment variables | Child can execute in host environment; exact inherited variable set was not inspected to avoid secret exposure | Same | **UNKNOWN** exact policy. |
| Tools, MCP, plugins | Child reported spawn/lifecycle tools; project instructions available. Exact complete MCP/plugin identity equivalence was not enumerated. | Likely same host surface | **OBSERVED locally** in part; otherwise **UNKNOWN**. |
| Earlier child results | Not automatically part of a fresh child's conversational input | May be present only if included in forked turns or explicit message | **INFERRED** from no-surrounding-context contract; the parent can deliberately transmit results. |

## Context-isolation experiment

### Design

The parent placed `PARENT_CONTEXT_MARKER_7F3A91C2` in parent-only conversation context. It spawned a read-only child with `fork_turns="none"`; the explicit child prompt did not include the marker and prohibited edits/configuration changes. The child was asked to report only whether it could see a `PARENT_CONTEXT_MARKER_*` value, its cwd, instruction availability, exposed model/effort, and collaboration tools.

### Result

| Observation | Result |
| --- | --- |
| Marker result | `NOT_VISIBLE` |
| Child cwd | `/home/bal/projects/engineering-flow` |
| Project instructions | Available |
| Model/reasoning shown to child | Not exposed in its runtime context |
| Collaboration/lifecycle tools | Available |
| Repository modifications | None |

**OBSERVED locally:** the child did not reproduce or report the marker. This corroborates the explicit `fork_turns="none"` contract and is stronger than relying only on its report because the active host's spawn interface itself defines `none` as no surrounding context. It does not prove the absence of every indirect disclosure route: a marker written to a shared file, command history, environment variable, or explicit task would still be accessible if the child could read it.

**INFERRED:** child context is genuinely fresh with respect to parent conversational history when `fork_turns="none"`, while retaining system/developer/project instruction layers and shared local state. It is neither a new OS security principal nor a separate repository.

No `fork_turns="all"` marker experiment was run because the tool contract explicitly defines it as full surrounding context; the independent-review question is resolved by the tested `none` alternative.

## Reviewer-isolation assessment

**Classification: SUFFICIENT_WITH_CONSTRAINTS.**

A reviewer can be given only a handoff naming: authoritative TECHSPEC path, selected task path, repository revision/working tree, changed-file or diff scope, validation command(s), and required structured result. Spawn it with `fork_turns="none"` and do not embed developer explanations, reasoning, suggestions, or outcome. The experiment supports exclusion of unrelated parent conversation and developer reasoning from the reviewer's model conversation.

The classification is not **STRONG** because reviewer and developer share mutable repository state, repository instructions, host-level tools, and potentially the local environment. A developer can bias review indirectly through the diff, task artifacts, validation output, uncommitted files, or any developer-authored prose that the reviewer is told to read. The coordinator must use authoritative artifacts as the handoff source and direct the reviewer to disregard non-authoritative developer narrative.

## Lifecycle and result contract

The host can supervise the following state progression without doing the engineering work:

```text
execute-task child -> IMPLEMENTED artifact/evidence
                       |
                       v
fresh review-task child -> PASS ---------> next approved scope
                       |
                       +-> FIX_REQUIRED -> fresh fix-task child
                                               |
                                               v
                                           fresh review-task child
```

**OBSERVED locally:** parent gets a terminal child response and can inspect status, wait, message, follow up, and interrupt. **INFERRED:** this is enough for a coordinator to advance a persisted state machine, provided it verifies authoritative repository artifacts rather than accepting free-form prose as the state transition.

Minimum durable result envelope, stored in the existing workflow Markdown rather than only a chat result:

```text
task_id, role, attempt, input revision/diff identity,
terminal state, authoritative artifact path, validation command/result,
review decision (when applicable), timestamp, child task name
```

The parent should treat a missing envelope, a stale revision, a child interruption, or a conflicting artifact as `BLOCKED`/needs-human-intervention rather than as a success. **UNKNOWN:** a native structured-output schema, durable child result ID suitable for a workflow database, or automatic child-resume API in this collaboration interface.

## Suitability for the workflow-host architecture

**INFERRED: suitable for an initial bootstrap with the specified boundaries.** The Codex main session can retain lifecycle/control context; a coordinator prompt can limit itself to selecting a dependency-ready state and dispatching role-specific skill work; developer, reviewer, and fixer children can receive bounded factual handoffs. Existing Markdown remains the durable truth and human approvals remain explicit gates.

The coordinator must not implement, review, fix, approve, or change specifications. It should dispatch exactly one state-authorized role action, record/verify the envelope, and stop at human gates. This does not require changing the Engineering Flow product architecture.

### Separate-session/process comparison

A completely separate Codex session/process would add a separate conversation store and independently chosen invocation settings (model, sandbox, approval, cwd/worktree) when launched that way. With a separate worktree/container/user, it can also provide stronger filesystem and environment separation. **INFERRED.**

Separate processes are not necessary for the proposed bootstrap now because `fork_turns="none"` passed the critical conversational marker test. They remain the appropriate fallback if the pilot requires strong reviewer isolation, distinct write permissions, isolated worktrees, recovery independent of parent-session continuity, or audited machine-readable orchestration.

## Risks and minimum constraints for safe adoption

| Risk | Minimum constraint |
| --- | --- |
| Context leakage / reviewer bias | Spawn reviewers and re-reviewers with `fork_turns="none"`; include only the factual handoff; never forward developer rationale or predicted verdict. |
| Shared mutable state | Serialize developer/fixer writes; reviewer starts only after recording the exact revision/diff; prohibit concurrent writers to the same checkout. |
| Model/reasoning inheritance | Specify approved role model/effort explicitly when the spawn interface permits it; record effective intended values in the handoff. Do not rely on defaults. |
| Permission/tool inheritance | Treat child capabilities as host-scoped until independently verified; use the least permissive host context compatible with the role. |
| Stale handoff | Include commit/working-tree/diff identity and reject result envelopes that do not match it. |
| Lost/free-form result | Persist the result envelope and authoritative artifact before advancing; do not transition on prose alone. |
| Parent context growth or loss | Keep control state in persisted Markdown; a replacement host must reconstruct state from repository artifacts. Parent compaction/resume behavior is not a workflow persistence guarantee. |
| Nested-agent limitations | Do not rely on nested agents for the first pilot. The active concurrency limit is four including root; reserve slots and use a flat host-to-role topology. |
| Quota/context | Each child uses model context and tool work. This discovery establishes no quota-saving or cost claim; measure pilot usage and failure modes. |
| Hidden shared channels | Do not place task secrets, markers, or review steering in shared files/environment/command history; use only required authoritative files and the explicit bounded prompt. |

## Adoption gate

**EXPERIMENT_FIRST** is the responsible recommendation. Before broader adoption, run one human-supervised real task through developer -> fresh reviewer -> fixer (only if required) -> fresh re-review. Confirm all four conditions: the reviewer receives a marker-free bounded prompt; the coordinator rejects a deliberately stale diff identity; the persisted result envelope supports resume by a new host; and no child changes workflow/spec artifacts outside its authorized role. Promote to **ADOPT** only if that pilot produces an auditable pass/fix path with no context or state-boundary violation. Use **DO_NOT_ADOPT** for the shared-host method if any reviewer needs hard permission or filesystem isolation that cannot be provided by the host runtime.

