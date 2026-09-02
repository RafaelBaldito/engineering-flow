# Technical Specification — Wave 1: Controlled Planning Workflow

**Status:** Approved  
**Scope:** Wave 1 only, as defined in `docs/DELIVERY-PLAN.md`.

## 1. Scope

Wave 1 delivers a local Python CLI that creates and resumes a single, durable
planning workflow. A workflow accepts a feature request; generates a PRD,
TECHSPEC, and task plan through Codex; and stops after each artifact until the
applicable approval policy is satisfied. Its successful terminal state is an
approved, immutable task-plan artifact ready for Wave 2.

This wave includes planning-stage state, artifacts, events, logs, approvals,
recovery, idempotency records, CLI interaction, and the Codex planning adapter.
It does **not** implement task execution, tests, review/fix cycles, Git
operations, PR creation, merge automation, parallel execution, another
provider, or a UI/service.

## 2. Requirements Traceability

| Requirement | Wave 1 implementation outcome |
| --- | --- |
| FR-001–FR-005 (planning portions) | Orchestrator owns PRD → TECHSPEC → task-plan progression, records role-specific executions, and supplies only the prior authoritative inputs for each stage. |
| FR-006–FR-008 | Per-stage approval policy and durable human/automatic decisions; the initial defaults require human approval for all three planning artifacts. |
| FR-017–FR-021 (planning portions) | Provider-neutral runtime contracts with one `CodexCliRuntime`; executable/capability preflight precedes planning work. |
| FR-022–FR-025 (planning portions) | SQLite workflow record, immutable artifacts, execution and approval evidence, resume, operation keys, and transactional lifecycle writes. |
| FR-030–FR-032 (planning portions) | `init`, `run`, `status`, `approve`, `reject`, `resume`, and `logs` commands with structured events and classified failures. |
| AC-001; planning portions of AC-005/AC-006 | Required approvals gate every next planning stage; restart/resume preserves state and exposes evidence without duplicate recorded side effects. |
| NFR-001–NFR-006; CON-001–CON-007 | Local Python CLI, explicit control-plane authority, auditable evidence, scoped context, safe read-only planning execution, and sanitized logs. |

## 3. Current-State Context

The repository is an unimplemented Python 3.13 package (`src` package layout is
declared in `pyproject.toml`) with no runtime dependencies or test suite. The
approved PRD, delivery plan, and architecture overview are the authoritative
inputs. This specification therefore establishes the first code and test
conventions; it must preserve the cross-wave contracts in
`docs/architecture/architecture-overview.md` rather than redefine them.

Use the standard library for Wave 1: `argparse`, `dataclasses`, `enum`,
`hashlib`, `json`, `pathlib`, `sqlite3`, `subprocess`, `tomllib`, `uuid`, and
`unittest`. This avoids a persistence, CLI, or logging dependency before the
workflow contract is proven.

## 4. Technical Design

### 4.1 Package and responsibility boundaries

Create `src/engineering_flow/` with these focused modules:

| Module | Responsibility |
| --- | --- |
| `cli.py` | Parse arguments, format command output, map domain failures to stable exit codes, and delegate only to services. |
| `config.py` | Read and validate `.engineering-flow/config.toml`; resolve the target repository and policy defaults. |
| `domain.py` | Enums and immutable value objects: stage, workflow status, approval policy/decision, role, artifact, execution request/result, event, and typed failures. |
| `orchestrator.py` | Sole transition authority. Starts/resumes workflows, selects the next planning action, enforces approvals and idempotency, and records failures. |
| `store.py` | SQLite transactions, artifact file writes, operation records, and queries used by status/log commands. It contains no provider behavior. |
| `runtime.py` | Provider-neutral `AgentRuntime` protocol and planning request/result contracts. |
| `codex_cli.py` | The sole Codex-specific adapter: preflight, `codex exec` process execution, JSONL event translation, thread-ID capture, and output-schema validation. |
| `sanitization.py` | Redacts configured secret values and key/token-like values before they are retained or displayed. |

`cli.py` must not transition a workflow. `CodexCliRuntime` must not write
workflow state or artifact files. Only `orchestrator.py`, through `store.py`,
may advance state, record approval, or declare an artifact authoritative.

### 4.2 Workspace layout and configuration

`engineering-flow init --repo <target-repository>` validates that the resolved
directory is a Git worktree, then creates this application-owned directory in
that target repository:

```text
<repo>/.engineering-flow/
  config.toml
  workflows.sqlite3
  workflows/<workflow-id>/
    input/feature-request.md
    artifacts/001-prd.md | 002-techspec.md | 003-task-plan.md
    runtime/<execution-id>/artifact.schema.json
    logs/events.jsonl
```

`init` must add `.engineering-flow/` to the target repository's `.gitignore`
only after preserving existing entries; the directory contains workflow data and
may contain sensitive engineering context. It must never create a Git branch,
commit, push, or PR.

The initial generated configuration is normative:

```toml
[provider]
name = "codex-cli"
command = "codex"
timeout_seconds = 1800

[approval]
prd = "required"
techspec = "required"
task_plan = "required"

[safety]
allow_read_only_planning = true
```

Allowed policy values are `required`, `automatic`, and `conditional`.
`conditional` consumes the generated artifact's schema-required
`requires_human_approval` boolean: true waits for a human decision; false
records an `AUTO_APPROVED` decision. This is a policy evaluation by the
orchestrator, not an agent transition. Defaults remain `required` for all
planning stages, satisfying the V1 initial policy. Invalid configuration fails
before any provider process begins. Credential values are intentionally absent
from config; Codex authentication remains in its supported local credential
mechanism or a per-process environment supplied by the caller.

### 4.3 State machine and progression

`Workflow.stage` is one of `PRD`, `TECHSPEC`, `TASK_PLAN`, or `READY_FOR_WAVE_2`.
`Workflow.status` is one of `CREATED`, `RUNNING`, `AWAITING_APPROVAL`,
`REJECTED`, `FAILED`, `CANCELLED`, `HUMAN_ATTENTION`, or `COMPLETED`.
Wave 1 uses `COMPLETED` only with stage `READY_FOR_WAVE_2`; it is not overall
V1 completion.

```text
CREATED
  -> RUNNING(PRD generation) -> AWAITING_APPROVAL(PRD)
  -> RUNNING(TECHSPEC generation) -> AWAITING_APPROVAL(TECHSPEC)
  -> RUNNING(TASK_PLAN generation) -> AWAITING_APPROVAL(TASK_PLAN)
  -> COMPLETED(READY_FOR_WAVE_2)
```

For an automatic or conditionally automatic decision, the corresponding
`AWAITING_APPROVAL` state is still recorded before the approval decision and
next transition, preserving a complete audit sequence. `reject` records the
decision, preserves the rejected artifact, and sets `REJECTED`; it does not
silently regenerate. A later `resume --workflow <id> --regenerate <stage>` is
the explicit restart mechanism and may run only for the current rejected stage;
it creates a new artifact revision and returns to the same approval boundary.

`resume` is valid for a persisted nonterminal workflow. It first reconciles
incomplete operation records, then either reports the pending approval, retries
an eligible failed planning execution, or runs exactly the next allowed stage.
It may never skip an approval or regenerate an already authoritative artifact.
Cancellation and retry policy values are outside this wave except that a
non-retriable/unknown provider execution enters `HUMAN_ATTENTION`.

### 4.4 Planning data flow and context discipline

1. `run --repo <path> --feature-file <path>` creates a UUID workflow, copies
   the feature file verbatim into the workflow input directory, hashes it, and
   records `workflow.created` in one transaction.
2. Before each stage, the orchestrator asks the runtime to verify planning
   capabilities, writes a durable execution/operation intent, and emits
   `stage.started` and `agent.execution.started`.
3. The runtime receives only a stage instruction, repository path, and paths
   to authoritative inputs: feature request for PRD; feature request plus
   approved PRD for TECHSPEC; feature request, approved PRD, and approved
   TECHSPEC for task plan. It must not receive the event history or future-wave
   documents as prompt context.
4. On a schema-valid result, the orchestrator writes the generated Markdown to
   the next immutable artifact path, stores its SHA-256 and provider execution
   metadata, closes the operation, emits completion events, and requests or
   records approval according to policy.
5. After task-plan approval, it records `workflow.ready_for_wave_2` and exits;
   it does not invoke any Developer or Reviewer role.

The planning prompt must explicitly state the role, required artifact type,
authoritative inputs, output contract, scope boundary, and that the agent has
no authority to progress the workflow. Artifact content is accepted only from
the final structured result, never from progress text.

## 5. Provider Runtime Contract

The provider-neutral protocol is intentionally small:

```text
verify_planning_capabilities(repository) -> CapabilityReport
execute_planning(PlanningExecutionRequest) -> PlanningExecutionResult
```

`PlanningExecutionRequest` contains workflow/execution IDs, role (`prd`,
`architect`, or `planner`), stage, repository path, authoritative artifact
paths and hashes, prompt text, output-schema path, timeout, and required
capabilities. `PlanningExecutionResult` contains a provider name, logical and
provider session references, terminal state, structured final payload, usage
metadata when available, and normalized events. Provider-native fields remain
inside a JSON metadata field and do not affect state-machine decisions.

`CapabilityReport` must verify: the configured executable exists; the target
is a Git worktree; `codex exec` supports JSON events and an output schema; and
read-only planning is permitted. Authentication is verified by the actual
execution; an authentication failure is classified distinctly and requires
human attention. The report is stored for each execution.

`CodexCliRuntime` invokes the configured executable with an argument vector
(never shell interpolation), target repository as the working directory, a
read-only sandbox, JSONL events, a per-execution JSON Schema, and an
orchestrator-owned final-output path. Current official Codex guidance documents
these non-interactive controls: [`codex exec`](https://learn.chatgpt.com/docs/non-interactive-mode)
uses read-only mode by default, emits JSONL with `--json`, supports a final
response JSON Schema with `--output-schema`, and reports a resumable thread ID.
The adapter parses JSONL incrementally, persists sanitized normalized events,
and associates the `thread.started` ID with the logical session. It must not
request workspace-write or broad sandbox access in Wave 1.

The required final payload schema is:

```json
{
  "artifact_markdown": "string",
  "summary": "string",
  "requires_human_approval": true,
  "approval_reason": "string"
}
```

All fields are required; `artifact_markdown` must be non-empty Markdown. The
result is invalid if it cannot be parsed, fails the schema, has no terminal
success event, or exceeds the configured timeout. Invalid output never becomes
an artifact and is recorded as an `agent_execution` failure.

## 6. Persistence, Events, and Idempotency

Use one SQLite database in WAL mode with foreign keys enabled. All timestamps
are UTC ISO-8601 strings. The minimum durable records are:

| Record | Required fields |
| --- | --- |
| `workflows` | id, repository path, provider, stage, status, created/updated timestamps, selected configuration snapshot, current artifact revision |
| `artifacts` | id, workflow ID, stage, revision, path, SHA-256, source execution ID, approval state, created timestamp; unique `(workflow_id, stage, revision)` |
| `approvals` | id, workflow/artifact IDs, decision (`APPROVED`, `REJECTED`, `AUTO_APPROVED`), actor, reason, timestamp; unique `(artifact_id)` |
| `sessions` / `executions` | logical session ID, role, provider references, request hash, lifecycle, capability report, terminal result/failure classification, timestamps |
| `operations` | idempotency key, kind, workflow ID, status (`PENDING`, `COMPLETED`, `UNKNOWN`), related record, timestamps |
| `events` | monotonic per-workflow sequence, type, stage/artifact/execution correlation IDs, sanitized JSON payload, timestamp |

Use deterministic operation keys: `workflow:<id>:stage:<stage>:revision:<n>:generate`
and `artifact:<id>:approve`. Within one transaction, create the operation intent
and execution record before process launch. In a second transaction, atomically
write the artifact, completion records, state transition, and events. A resume
of a completed key returns the recorded outcome. A process interrupted while a
provider process was active becomes `UNKNOWN` after liveness cannot be proven;
it cannot be re-run automatically, because a second execution could duplicate
unobserved agent activity. The owner must explicitly resume/retry it, producing
a separately recorded execution attempt. Planning has no Git/PR side effects.

Artifact files are append-only by revision and treated as immutable after the
database hash is committed. Artifact display verifies its stored SHA-256 and
raises a corruption failure on mismatch. Events are the source for `logs`;
human-readable output is derived from them rather than being treated as state.

## 7. CLI Contracts and Error Behavior

The console entry point is `engineering-flow`. Stable command forms are:

```text
engineering-flow init --repo PATH
engineering-flow run --repo PATH --feature-file PATH [--provider codex-cli]
engineering-flow status --repo PATH --workflow ID [--json]
engineering-flow approve --repo PATH --workflow ID --artifact ID [--reason TEXT]
engineering-flow reject --repo PATH --workflow ID --artifact ID --reason TEXT
engineering-flow resume --repo PATH --workflow ID [--regenerate prd|techspec|task-plan]
engineering-flow logs --repo PATH --workflow ID [--after SEQUENCE] [--json]
```

Mutation commands require an exact workflow and artifact identifier where an
approval is involved; rejecting/approving a stale or already decided artifact
is a conflict and makes no change. Commands return non-zero codes for usage or
config errors, not-found, invalid transition/conflict, capability/provider/auth
failure, persistence corruption, and human-attention required. JSON mode emits
one document containing command result, workflow ID, status, stage, and error
code; secret values never appear in either output mode.

Failure classifications for this wave are `workflow`, `provider`,
`agent_execution`, `authentication`, `tool`, `human_rejection`, and
`persistence`. The persisted failure determines whether `resume` can continue;
CLI text must not infer a transition from provider prose.

## 8. Security and Operational Controls

- Canonicalize and validate repository, feature-input, and application paths;
  no path supplied by a provider may determine an artifact destination.
- Execute Codex with `cwd` at the validated repository, read-only sandbox, no
  shell, bounded timeout, and a minimal inherited environment. Do not place API
  keys in configuration, command arguments, persisted request data, or logs.
- Treat provider output, feature input, and generated artifact text as
  untrusted data. Store it as evidence, never execute it.
- Sanitize events and displayed diagnostics using configured secret values and
  key/token/password patterns. Do not persist raw environment variables or
  unredacted stderr.
- Use SQLite parameter binding, file permissions appropriate to the platform,
  and a single-writer transaction guard. A locked database is a recoverable
  `persistence` failure, never a reason to create a second database.
- Do not run target-repository scripts, tests, Git mutations, or agent-issued
  commands through Engineering Flow in this wave.

## 9. Validation Strategy

Tests use the standard-library `unittest` runner and a deterministic fake
runtime; no live credentials or live Codex call is required for automated
tests.

| Behavior / risk | Validation |
| --- | --- |
| Ordered, human-gated planning (AC-001) | Unit/integration test a fake runtime through PRD, TECHSPEC, and task plan; verify each next stage is unavailable until the exact prior artifact is approved. |
| Automatic and conditional policy semantics | Table-driven orchestrator tests verify decision records and the conditional payload flag; defaults remain all-required. |
| Artifact authority and context scoping | Test request construction includes only the approved prior artifacts, hashes and feature input; malformed final payload cannot create an artifact. |
| Resume and duplicate protection (AC-005) | Interrupt at intent, runtime, artifact-write, and approval boundaries; restart from the same DB and verify a completed operation/approval/artifact is not duplicated. |
| Status, events, and artifacts (AC-006) | CLI integration tests verify status stage, monotonic event history, preserved immutable artifacts, JSON output, and SHA mismatch detection. |
| Provider adapter | Subprocess fixture simulates `codex exec` JSONL success, timeout, non-zero exit, malformed output, and authentication failure; verify normalized events, thread ID, command vector, and read-only setting. |
| Safety | Tests reject a non-Git repository, invalid configuration, path traversal, write-capable runtime configuration, and secret values in event/CLI output. |

Minimum implementation checks are `python -m unittest discover -s tests` and
`python -m compileall src`. A manual acceptance run in a disposable Git
repository, with authenticated Codex, must demonstrate the three artifacts,
three recorded required approvals, `status`/`logs`, interruption and explicit
resume, and no task execution or Git delivery action.

## 10. Risks, Assumptions, and Open Questions

**Assumptions:** the user has a locally installed/authenticated Codex CLI; the
target repository is a Git worktree; planning can be performed read-only; and
feature requests can safely be stored in the target's ignored application data.
The runtime's exact CLI flags must be checked against the installed Codex
version during capability preflight rather than assumed from a model name.

**Risks:** a process crash after a provider call may leave its completion
unknown; Wave 1 deliberately requires explicit retry rather than claiming it
can deduplicate an unobserved remote execution. Generated artifacts can be
poor quality despite being schema-valid, so required human planning approvals
remain the default safety gate. SQLite is appropriate for one local CLI user;
multi-user/distributed ownership is excluded.

**No blocking open question:** Wave 1 resolves initial approval defaults,
storage, CLI syntax, capability checks, and planning failure handling locally.
Exact task/review retry and final-validation policies, repository-hosting
support, Git mechanics, and the validation project remain Wave 2/3 decisions.

## 11. Implementation Boundaries and Context Surface

Downstream tasks should be decomposed by `domain/store`, `orchestrator`,
`runtime/codex adapter`, `CLI/config`, and tests. Each can reference its named
section plus the architecture overview; none needs future-wave design or broad
repository context. This is a single coherent planning outcome with a bounded
context surface. No decomposition change to the approved delivery plan is
needed.
