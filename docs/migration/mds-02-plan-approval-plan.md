# Engineering Flow V2 — MDS #2 Plan and Approval Implementation Plan

## 1. MDS objective and boundary

Extend the implemented V2 lifecycle by one bounded vertical slice:

```text
Feature Contract READY
        ↓ resume
       PLAN
        ↓
strict JSON Plan containing Task Contracts
        ↓
PLAN / AWAITING_APPROVAL
        ↓ human decision on the exact Plan artifact
   PLAN_APPROVED or REJECTED
```

This MDS proves that a READY Feature Contract can drive a real, read-only Planner invocation; that the resulting Plan and Task Contracts are deterministically validated, hash-bound, persisted, and inspectable; and that one durable human decision controls further progression. Approval is a stop state. It must not import tasks into an execution queue, invoke a Developer, modify product files, or begin implementation.

The delivery consists of three independently demonstrable vertical steps. It preserves the explicit V1/V2 lifecycle boundary and does not use or extend `CanonicalLifecycleOrchestrator`.

## 2. Inspected implementation baseline

This plan is based on the repository after MDS #1, not only on `docs/engineering-flow-v2.md`.

- `src/engineering_flow/cli.py` exposes `init`, `run`, `status`, `approve`, `reject`, `resume`, `intervene`, and `logs`. `run --request` creates V2; `run --feature-file` remains V1. `resume` is already the command meaning “continue this persisted workflow,” while `approve` and `reject` require both a workflow UUID and artifact UUID.
- `IntakeOrchestrator` in `src/engineering_flow/orchestrator.py` owns the current V2 path. It retains the raw request, creates a generation intent, invokes the runtime read-only, validates `FeatureContract`, and atomically persists the artifact and `intake/ready`, `intake/needs_clarification`, or `intake/rejected`. It deliberately has no successor today.
- `PlanningOrchestrator` owns the historical V1 `PRD -> TECHSPEC -> TASK_PLAN` lifecycle. Its approval guards are useful patterns, but its stage sequence and automatic transition toward task execution must not be used for V2.
- `CanonicalLifecycleOrchestrator`, `lifecycle_states`, scopes, governance decisions, Waves, and release governance belong to the unfinished canonical V1 work. They are not part of this MDS.
- `WorkflowStore` uses `.engineering-flow/workflows.sqlite3` as the authoritative state store. It already provides additive schema upgrades, `BEGIN IMMEDIATE` transactions, workflow rows, sessions, executions, idempotent generation operations, immutable hash-bound artifacts, approvals, and monotonic events.
- `complete_generation()` can atomically complete an execution/operation, write an immutable artifact, set its approval state, update the workflow projection, and append completion events. `record_approval()` atomically records one decision per artifact, updates the artifact approval state, and applies a supplied workflow transition.
- The artifact table uniquely binds `(workflow_id, stage, revision)`. The approval table has a unique `artifact_id` foreign key. Existing V1 orchestration additionally rejects a decision unless the workflow is awaiting approval and the supplied artifact is the latest artifact for the current stage.
- The existing `tasks` table and `import_task_plan()` are V1/Wave-2 execution infrastructure. Their contract is Markdown containing an `engineering-flow-task-plan` JSON block with `key`, `title`, `instructions`, acceptance criteria, required tests, and context paths. The table has no first-class dependencies, complexity, risk, requirements, constraints, or existing-pattern context, and import requires an already approved `Stage.TASK_PLAN` artifact. It therefore cannot cleanly represent the V2 Task Contract without distorting either contract.
- `AgentRuntime`, `RuntimeExecutionRequest`, `RuntimeExecutionResult`, and `NormalizedEvent` are the provider-neutral execution boundary. Every non-Developer role is dispatched by `CodexCliRuntime` with the `read-only` sandbox.
- `CodexCliRuntime` already starts `codex exec --json` with piped stdout/stderr and `_stream_process()` reads stdout JSONL incrementally on a background-reader queue. `_normalize_line()` creates `NormalizedEvent` values as lines arrive. However, those events are accumulated in a private list and returned only when `execute()` finishes; orchestration then persists them. No callback reaches the CLI during execution, so the terminal is silent while Codex runs.
- Repository evidence shows trustworthy Codex lifecycle records including `thread.started`, `turn.started`, typed `item.completed`, and terminal `turn.completed`. Only session/terminal facts are currently interpreted. Arbitrary item payloads may contain agent prose or final output, so this MDS must not render raw JSONL or infer labels such as “Inspecting tests.”
- An execution intent and `stage.started`/`agent.execution.started` events are persisted before dispatch. In the MDS #1 Intake path, the execution row is changed to `RUNNING` only after runtime return; the V2 Plan path should correct this ordering for its own execution by calling `start_execution()` immediately before dispatch, then update the provider execution ID after return when known.
- `status` verifies every artifact hash before projecting it. V2 status currently adds only the Intake outcome, Feature Contract artifact ID, and questions. Human output lists artifact IDs/stages/revisions/approval states. JSON output is already a single stable stdout document.
- Current tests use `unittest`, fake runtimes/processes, temporary Git repositories, store reopen checks, artifact tamper checks, and injected `Popen` factories. `StreamingProcess` already proves incremental JSONL consumption. The only full validation command is `.venv/bin/python3 -m unittest discover -s tests -q`; at planning time all 131 tests pass.

## 3. Current MDS #1 baseline

The implemented V2 entry point is:

```bash
.venv/bin/engineering-flow run --repo . --request "..."
```

It creates a `LifecycleVersion.V2` workflow at `Stage.INTAKE`. A valid Feature Contract is stored as `001-feature-contract.json` with `ApprovalState.NOT_REQUIRED`. A sufficient request ends at `intake/ready`; an ambiguous request ends at `intake/needs_clarification` with persisted questions. Reopening through `status --json` verifies the artifact hash and reconstructs this state.

MDS #2 does not change Intake classification, Feature Contract shape, its artifact, its normal terminal states, or `run --feature-file` routing. It adds an explicit successor only for the already persisted combination `lifecycle_version=v2`, `stage=intake`, `status=ready`.

## 4. Exact V2 lifecycle transitions

The workflow row remains the current V2 state projection. Add `Stage.PLAN` and `WorkflowStatus.PLAN_APPROVED`; reuse `RUNNING`, `AWAITING_APPROVAL`, `REJECTED`, `FAILED`, and `HUMAN_ATTENTION`.

| From | Trigger | Durable transition | Provider call |
| --- | --- | --- | --- |
| `v2 / intake / ready` | `resume` | `plan / running`, then `plan / awaiting_approval` after valid persistence | Exactly one read-only Planner call |
| `v2 / plan / awaiting_approval` | `resume` | No change; return current state | None |
| `v2 / plan / awaiting_approval` | `approve` targeting current Plan artifact | `plan / plan_approved` | None |
| `v2 / plan / awaiting_approval` | `reject` targeting current Plan artifact | `plan / rejected` | None |
| `v2 / plan / plan_approved` | `resume` | No change; report that implementation belongs to a later MDS | None |
| `v2 / plan / rejected` | `resume` | No change | None |
| `v2 / intake / needs_clarification` or `v2 / intake / rejected` | `resume` | No change | None |
| `v2 / plan / running` with an incomplete persisted operation after process loss | `resume` | Reuse current reconciliation policy: mark the operation unknown and stop at human attention | None |

Provider timeout or deterministic provider/contract failure ends at `plan/failed` using the existing failure classification and no Plan artifact or approval. An exception that leaves the remote outcome unknowable ends at `plan/human_attention`, consistent with Intake. This MDS does not add automatic retries or Plan regeneration.

`PLAN_APPROVED` is deliberately a workflow status, not a new successor stage. `COMPLETED` would incorrectly imply that the feature workflow is complete, and `READY` would not preserve the human decision. Keeping `stage=plan` and `status=plan_approved` is the smallest explicit persisted boundary for the next MDS.

## 5. CLI interface decisions

### 5.1 Entering Plan

Use the existing command with its existing meaning:

```bash
.venv/bin/engineering-flow resume --repo . --workflow <workflow-id>
```

This is preferable to overloading `run`, because the READY Feature Contract already exists in a prior process and `resume` is the repository's command for advancing persisted work. It also keeps MDS #1's promise that `run --request` stops at Intake. `--regenerate` remains V1-only and must be rejected for V2.

The CLI must load the workflow first and route by its persisted `lifecycle_version`: V2 actions go to the V2 orchestrator; historical/V1 actions retain `PlanningOrchestrator`. Flags never infer lifecycle.

Add `--json` to `resume`. In JSON mode, stdout contains exactly one final result document and all live progress is disabled. No `--plan` command and no new top-level command are needed.

### 5.2 Inspecting the Plan

Reuse:

```bash
.venv/bin/engineering-flow status --repo . --workflow <workflow-id>
.venv/bin/engineering-flow status --repo . --workflow <workflow-id> --json
```

For a V2 Plan, status must verify and parse the current Plan artifact and add a `plan` projection. JSON output contains the complete validated Plan object plus `artifact_id`, `sha256`, `revision`, and `approval_state`. Human output shows:

- Plan identity, revision, and artifact UUID needed for the decision;
- strategy, assumptions, and overall verification strategy;
- every Task Contract, including dependencies, complexity, risk, relevant files/patterns, requirements, acceptance criteria, verification, and constraints;
- `Waiting for human approval.`, `Plan approved. No implementation has started.`, or the rejection state as applicable.

The successful `resume` result should use the same projection, so the user can inspect immediately or reopen it later with `status`.

### 5.3 Human decisions

Keep the current explicit commands and exact artifact target:

```bash
.venv/bin/engineering-flow approve --repo . --workflow <workflow-id> --artifact <plan-artifact-id>
.venv/bin/engineering-flow reject --repo . --workflow <workflow-id> --artifact <plan-artifact-id> --reason "..."
```

Approval prints `Plan approved.` and `No implementation has started.` Rejection prints the rejected state and reason acknowledgement. Neither command invokes a runtime. Existing V1 command behavior remains unchanged.

## 6. Minimal structured Plan representation

Persist one canonical UTF-8 JSON artifact at:

```text
.engineering-flow/workflows/<workflow-id>/artifacts/002-plan.json
```

Its exact shape is:

```json
{
  "plan": {
    "id": "<workflow-id>:plan:r1",
    "workflow_id": "<workflow-id>",
    "revision": 1,
    "feature_contract": {
      "artifact_id": "<feature-contract-artifact-uuid>",
      "sha256": "<64 lowercase hex characters>"
    },
    "strategy": "Concise repository-specific implementation strategy.",
    "assumptions": ["Assumption used by this implementation strategy."],
    "verification_strategy": [".venv/bin/python3 -m unittest discover -s tests -q"],
    "tasks": [
      {
        "id": "T1",
        "objective": "One bounded implementation outcome.",
        "context": {
          "relevant_files": ["src/example.py"],
          "existing_patterns": ["Follow the validator pattern in Example.parse()."]
        },
        "requirements": ["Required behavior."],
        "acceptance_criteria": ["Observable acceptance condition."],
        "verification": ["Exact command or deterministic inspection."],
        "constraints": ["Do not modify unrelated modules."],
        "depends_on": [],
        "complexity": "low",
        "risk": "medium"
      }
    ]
  }
}
```

There is no Markdown control block, summary duplicate, approval recommendation, task status, model choice, estimated duration, implementation result, review field, or speculative scheduler metadata. The artifact table supplies the generated artifact UUID, source execution, approval state, and creation time; those facts must not be duplicated inside provider output.

The deterministic content ID `<workflow-id>:plan:r1` makes provider output identity checkable before the artifact UUID exists. `feature_contract.artifact_id` and `sha256` bind the Plan to the exact immutable input. Artifact revision `1` and embedded revision `1` must agree. Plan revision/regeneration is outside this MDS, but using the existing revision mechanism now makes stale decisions mechanically rejectable.

## 7. Exact Task Contract

Each item in `plan.tasks` is the V2 Task Contract. It contains only fields needed for future bounded execution:

| Field | Meaning |
| --- | --- |
| `id` | Plan-local stable ID, exactly `T1`, `T2`, ... in array order. |
| `objective` | One concise implementation outcome. |
| `context.relevant_files` | Existing repository-relative files the future implementer should load. New files belong in requirements, not as fictional context paths. |
| `context.existing_patterns` | Concrete repository patterns or symbols to follow. |
| `requirements` | Behavior and implementation obligations for this task. |
| `acceptance_criteria` | Observable conditions that establish task completion. |
| `verification` | Exact repository commands or deterministic checks appropriate to the task. |
| `constraints` | Task-specific prohibitions or boundaries; may be empty. |
| `depends_on` | IDs of earlier tasks required first. Present from this MDS even though execution remains future and initially sequential. |
| `complexity` | Reasoning/work volume: `low`, `medium`, or `high`. |
| `risk` | Consequence/uncertainty if wrong: `low`, `medium`, or `high`. |

Complexity and risk are independently required enums. The validator must not infer one from the other or reject combinations such as low complexity/high risk.

Do not create rows in the current `tasks`, `task_cycles`, or `task_artifacts` tables in MDS #2. The Plan artifact already persists the contracts before approval, while the current tables embody a different V1 execution contract and omit required V2 fields. Importing on approval would also blur the required “approval stops before implementation” checkpoint. A later implementation MDS can explicitly adapt task persistence from this approved, hash-bound Plan.

## 8. Deterministic validation rules

Add provider-neutral immutable `Plan`/`TaskContract` values and one authoritative parser. Codex JSON Schema is the first shape constraint; domain validation remains authoritative.

1. The root contains exactly `plan`; every object has `additionalProperties: false`; every listed field is required.
2. All scalar text is a non-empty string after whitespace checking. Arrays contain only non-empty strings. Exact duplicate values within one array are rejected.
3. `plan.id` equals `<workflow-id>:plan:r<expected-revision>`, `workflow_id` equals the current workflow UUID, and `revision` equals the generation intent/artifact revision.
4. `feature_contract.artifact_id` and `sha256` exactly equal the verified current Intake artifact. The Intake artifact must be `Stage.INTAKE`, revision 1, `NOT_REQUIRED`, and parse as `READY` with no open questions.
5. `strategy` is non-empty. `assumptions` may be empty. `verification_strategy` is non-empty.
6. `tasks` is a non-empty array. IDs are exactly the contiguous sequence `T1` through `Tn` in array order and are case-sensitive.
7. Each task has non-empty `objective`, `requirements`, `acceptance_criteria`, and `verification`. `constraints`, `relevant_files`, and `existing_patterns` are arrays and may be empty only when genuinely inapplicable; no placeholder values such as `TBD` satisfy planning instructions.
8. Every relevant file is a normalized POSIX repository-relative path, contains no `.`/`..` escape, resolves inside the repository, exists as a file at Plan validation time, and is unique within the task. Absolute paths are rejected.
9. Every `depends_on` value is unique, refers to an existing task, is not self-referential, and refers only to an earlier task in the ordered array. The earlier-only rule gives a deterministic topological order and mechanically excludes cycles while retaining DAG-ready dependencies.
10. `complexity` and `risk` are independently one of `low`, `medium`, or `high`.
11. The Plan must not contain implementation/review results, approval claims, task runtime statuses, or provider control fields because the strict schema has no such properties.
12. Validation failure fails the Plan execution safely: no artifact, approval, or task records are created; execution failure evidence is persisted using the existing sanitized path.

The Plan JSON Schema should be selected only for `Role.PLANNER + Stage.PLAN`. Historical Planner requests continue to use the existing planning output schema.

## 9. Planner instruction responsibilities

The V2 Plan instruction must give the Planner the verified Feature Contract path, artifact UUID, SHA-256, workflow UUID, expected Plan ID/revision, repository root, and strict output responsibility. It must direct the Planner to:

- read the Feature Contract and treat it as authoritative for what is being built;
- inspect the actual repository before decomposing work, including applicable `AGENTS.md`, architecture, similar implementation, tests, configuration, and relevant skills/context where useful;
- answer how the Feature Contract should be implemented in this repository, directly, without inserting PRD, Tech Spec, Wave, or release-governance stages;
- produce a small ordered/dependency-aware set of precise Task Contracts with bounded context and verification;
- record only implementation assumptions that do not change product behavior;
- keep complexity and risk independent;
- avoid credentials and unrelated material;
- make no repository modifications, implementation edits, commits, approvals, state transitions, or follow-on agent calls;
- return only the strict Plan JSON payload.

The request hash must cover the verified Feature Contract artifact ID and SHA-256, Planner instruction, `stage=plan`, revision, and Plan output-contract version. The progress callback is transient UI plumbing and must not enter the request hash or persisted terminal result.

Read-only enforcement is layered: the Planner role selects Codex `--sandbox read-only`; the instruction forbids mutation; automated adapter tests assert the command; orchestration supplies only verified authoritative input; and manual acceptance checks that no tracked implementation file changed. The runtime-created schema/final-output files under `.engineering-flow` are application workspace evidence, not Planner-authored implementation changes.

## 10. Persistence and state design

SQLite remains authoritative. No `.ai/*.json`, Plan table, V2 task table, or state sidecar is added.

### Plan generation

1. Guard `v2/intake/ready`; verify/read the READY Feature Contract and obtain its artifact UUID/hash.
2. Create the existing generation intent for `Stage.PLAN`, revision 1, `Role.PLANNER`, and destination `002-plan.json`. This persists session, execution intent, idempotent operation, `stage.started`, and `agent.execution.started`.
3. Set workflow to `plan/running`, call `start_execution()` before provider dispatch, and emit the transient progress start event.
4. Invoke the runtime read-only. Collect the terminal result and normalized provider events. Persist sanitized normalized events using the established `agent.runtime.<type>` event family.
5. Validate the final payload against the exact workflow/revision/Feature Contract/repository.
6. In one `complete_generation()` transaction, write/hash the Plan artifact, complete operation/execution, set artifact approval to `PENDING`, set workflow to `plan/awaiting_approval`, and append `plan.completed` with only Plan ID, revision, task count, and Feature Contract artifact ID.

No individual Task Contract rows are written. Status parses the verified Plan artifact. The existing execution terminal result may retain the canonical final payload as it does for Intake; the immutable artifact remains the approval target.

### Approval and rejection

Reuse the `approvals` row, artifact `approval_state`, approval operation, and events. Add V2 orchestration guards and supply V2-specific transitions to `record_approval()`:

- approval: artifact becomes `APPROVED`; workflow remains `plan` and becomes `plan_approved`; append `approval.recorded` and `plan.approved` atomically;
- rejection: artifact becomes `REJECTED`; workflow remains `plan` and becomes `rejected`; append `approval.recorded` and `plan.rejected` atomically.

The rejection reason is retained by the existing sanitized approval record. No automatic regeneration follows.

## 11. Stale approval and revision protection

Before either decision, the V2 orchestrator must require all of the following:

1. workflow lifecycle is V2;
2. stage/status is exactly `plan/awaiting_approval`;
3. the supplied artifact belongs to that workflow and is `Stage.PLAN`;
4. it is the highest/current Plan revision and its revision equals `workflow.current_artifact_revision` for this one-Plan slice;
5. its approval state is `PENDING` and no approval row already exists;
6. `read_artifact()` passes SHA-256 verification;
7. the parsed Plan identity/revision and Feature Contract UUID/hash binding still validate.

Only then may `record_approval()` commit. Thus an Intake artifact, artifact from another workflow, old Plan revision, replaced/tampered file, duplicate decision, or decision after state change produces a conflict/persistence error without mutation. Approval is bound to the artifact UUID, whose row is bound to immutable bytes by SHA-256 and to the source execution/revision.

## 12. Runtime progress and heartbeat design

### Current behavior

`CodexCliRuntime._stream_process()` already drains both child pipes safely, polls every 0.1 seconds, enforces a monotonic deadline, and normalizes stdout JSONL as each line arrives. The information exists incrementally inside the adapter, but neither the runtime protocol nor request has a callback. `RuntimeExecutionResult.events` is returned only at process completion, and orchestration persists those events only afterward. This buffering boundary—not lack of streaming—is why the Bash terminal appears frozen.

### Minimal provider-neutral addition

Add a small immutable `RuntimeProgressEvent` value and optional callable sink at the runtime request boundary. It needs only:

```text
kind: started | heartbeat | activity | completed | failed | timed_out
stage
elapsed_seconds
message: optional fixed safe label
```

The V2 orchestrator accepts an optional sink, emits stage start only after durable `plan/running`, passes the sink into `RuntimeExecutionRequest`, and emits terminal completion/failure only after the matching durable state transition. `CodexCliRuntime` emits heartbeats while its existing stream loop waits and may map `thread.started` to a fixed `activity` label such as `Agent session started`. It must never forward raw payloads, item text, prompts, tool arguments/output, stderr, or reasoning to the renderer.

For this MDS, do not invent semantic messages from `turn.started` or `item.completed`. The observed JSONL does not provide a stable provider-neutral guarantee that an item means “Inspecting repository” versus final prose. A reliable elapsed-time heartbeat is the primary signal. Later adapters can map trustworthy native events to the same normalized abstraction without changing orchestration or CLI rendering.

Progress delivery is best-effort and non-authoritative. Heartbeats are not written to SQLite, avoiding high-volume audit noise. Durable `stage.started`, `agent.execution.started`, normalized runtime events, terminal execution state, `artifact.created`, and `plan.completed` remain the reconstructable history. Sink/rendering failure must not fail provider execution; sanitize and ignore sink exceptions.

### Timing and timeout

Use `time.monotonic()` for elapsed durations and deadlines; never wall-clock timestamps. Default heartbeat interval: 10 seconds. Emit the first heartbeat at 10 seconds and every 10 seconds thereafter, without a separate sleeping thread: the existing stream poll loop compares the injected monotonic clock with the next deadline. The final renderer may show tenths of a second.

Make the monotonic clock and heartbeat interval injectable in focused tests. Tests advance a fake clock/scripted stream; they must not sleep for ten real seconds.

If Codex emits no JSONL, heartbeats continue until completion or the existing configured timeout. On timeout the existing kill/result classification remains authoritative, no Plan is created, the workflow becomes failed, and the CLI renders a terminal timed-out/failure line with elapsed duration. If an exception makes the provider outcome unknown, the workflow becomes human-attention and the renderer must not print success.

## 13. CLI rendering, stdout/stderr, and machine output

Create a small CLI-owned renderer passed as the optional sink. `CodexCliRuntime` must never call `print()`.

- **Interactive terminal:** enable only when `sys.stderr.isatty()` and `--json` is absent. Write progress to stderr, flushing each line. Use stable line-oriented output (no carriage-return animation): `→ PLAN started`, `  Codex running... 10s`, and `✓ PLAN completed (24.8s)`. A fixed `Agent session started` line is permitted when that normalized activity event occurs.
- **Redirected/non-TTY output:** disable transient progress. Emit only the existing final command result on stdout. This keeps scripts and captured logs deterministic rather than adding timing-dependent lines.
- **JSON mode:** `resume --json` writes exactly one JSON document to stdout and writes no progress to either stream. `status --json` and `logs --json` never execute an agent and remain clean JSON.
- **Tests:** injected streams/TTY predicates, fake clock, and captured stdout/stderr verify rendering independently. Existing CLI tests using `StringIO` remain quiet because it is non-TTY. Assert heartbeat text never enters result documents, event payloads, artifacts, or database state.
- **Failures:** render `✗ PLAN failed (...)` or `✗ PLAN timed out (...)` to interactive stderr only after the orchestrator has persisted the failure/attention outcome; normal final error/status output remains stdout under current CLI conventions.

Using stderr protects human progress from normal stdout result data, while the TTY/JSON gates protect machine behavior even more strongly.

## 14. REUSE / ADAPT / ADD decisions

| Component/decision | Classification | Decision |
| --- | --- | --- |
| V2 lifecycle boundary and MDS #1 Intake | ADAPT | Evolve the focused V2 orchestrator to own Plan; do not alter Feature Contract behavior. |
| `resume` command | ADAPT | Route persisted `v2/intake/ready` to Plan; retain all V1 semantics. |
| `status`, `approve`, `reject` commands | ADAPT | Add V2 Plan projection/decision routing while preserving command shapes. |
| Workflow row | ADAPT | Add `Stage.PLAN` and `WorkflowStatus.PLAN_APPROVED`; reuse existing statuses otherwise. |
| SQLite artifacts, generation intents, sessions, executions, operations, events | REUSE | They already provide identity, hashing, idempotency, evidence, and process-exit persistence. |
| Existing artifact/approval revision binding | ADAPT | Add V2-specific current-Plan guards and hash/content verification before decision. |
| `approvals` table and `record_approval()` | REUSE | One artifact-bound decision is exactly the required human gate. |
| Strict Plan/Task Contract domain values and schema | ADD | No current value represents the V2 contract. |
| Plan artifact | ADD | One immutable `002-plan.json`; no Plan table. |
| Existing `tasks`/task-cycle/task-artifact tables | REUSE only as future-compatible historical infrastructure | Do not write them in MDS #2; their V1 shape is not the V2 Task Contract. |
| Runtime request/result and incremental JSONL reader | ADAPT | Add optional progress sink and heartbeat emission; retain terminal semantics. |
| Provider-neutral progress event | ADD | Minimal ephemeral contract needed to cross the runtime boundary safely. |
| CLI progress renderer | ADD | Terminal concern owned by CLI, not runtime/orchestration. |
| Raw normalized provider event persistence | REUSE | Persist sanitized events after return as today; do not display raw payloads. |
| `PlanningOrchestrator` V1 path | REUSE | No V2 Plan stages or behavior added. |
| `CanonicalLifecycleOrchestrator`/canonical governance | REUSE only for historical compatibility | No changes and no V2 routing. |

No database table or column is required. Existing databases accept new enum text without schema migration, and historical rows retain their recorded lifecycle version.

## 15. Incremental implementation steps

### Step 1 — READY Feature Contract to persisted Plan with live progress

**Objective:** make `resume` execute one real read-only Planner call from a READY V2 Feature Contract, show trustworthy interactive progress, and stop with a validated Plan awaiting approval.

**Observable outcome:** the user runs `resume`, immediately sees `→ PLAN started`, receives a 10-second heartbeat while Codex runs, then sees Plan completion and the structured tasks. Reopened status reports `v2/plan/awaiting_approval`, the same hash-verified Plan/Task Contracts, and a pending Plan artifact. No product file or execution task row is changed.

**Why necessary:** this is the earliest end-to-end proof of both new product value and the operational progress fix; schema classes without a real CLI/provider path would not validate the slice.

**Classification:** **ADAPT** CLI/V2 orchestration/runtime/store use; **ADD** Plan contracts, Plan schema, provider-neutral progress event, and CLI renderer.

**Existing components reused:** MDS #1 Feature Contract validator/artifact; workflow row; generation intents; session/execution/operation/events; `complete_generation`; `AgentRuntime`; read-only `CodexCliRuntime`; incremental JSONL reader; status hash verification; failure sanitization.

**Expected files/modules affected:**

- `src/engineering_flow/domain.py`: `Stage.PLAN`, `WorkflowStatus.PLAN_APPROVED`, Plan/Task Contract values and deterministic parser.
- `src/engineering_flow/runtime.py`: optional progress sink and minimal normalized progress value.
- `src/engineering_flow/codex_cli.py`: strict Plan schema selection, heartbeat/activity emission from the existing stream loop, injectable monotonic timing; no printing.
- `src/engineering_flow/orchestrator.py`: evolve the MDS #1 V2 orchestrator to guard/resume READY, construct the Planner request, validate and persist Plan, and stop awaiting approval. Do not touch `CanonicalLifecycleOrchestrator`.
- `src/engineering_flow/store.py`: add `Stage.PLAN` to artifact destination/generation guards as necessary; reuse tables and transactions. Do not adapt/import V1 task manifests.
- `src/engineering_flow/cli.py`: persisted-lifecycle routing, `resume --json`, Plan status/result projection, and TTY stderr renderer.
- `src/engineering_flow/__init__.py`: export new provider-neutral public values only if consistent with current exports.
- focused coverage in `tests/test_domain.py`, `tests/test_runtime.py`, `tests/test_codex_cli.py`, `tests/test_store.py`, `tests/test_orchestrator.py`, and `tests/test_cli.py`.

**Persistence changes:** no schema change. Create Plan generation session/execution/operation, persist running state, then one `Stage.PLAN` revision-1 artifact with `PENDING` approval and `plan/awaiting_approval`. Persist the source binding in Plan JSON and the existing source-execution/artifact metadata. Do not create task rows.

**Automated tests:** strict shape/additional-property checks; identity/source/revision checks; all Task Contract rules; earlier-only dependencies; independent complexity/risk combinations; canonical existing file paths; read-only Planner command; precise instruction responsibilities; request hash input binding; idempotent generation; artifact/store reopen/tamper behavior; progress callback propagation; 10/20/30-second fake-clock heartbeats; safe `thread.started` mapping; no raw item/reasoning rendering; TTY stderr output; no progress for non-TTY or `--json`; timeout/failure/unknown outcomes with no artifact/approval/task rows.

**Manual CLI validation:** perform Demonstration A in section 17, wait long enough to observe a heartbeat when the real call exceeds ten seconds, inspect status, and run `git status --short` to confirm only `.engineering-flow` ignored runtime state changed.

**Acceptance criteria:** exactly one read-only Planner execution occurs; visible progress begins before the long wait; one valid JSON Plan exists and survives process exit; tasks are inspectable and dependency-aware; workflow is waiting for approval; artifact is pending; no implementation/runtime task work starts.

Commit this checkpoint before Step 2: `implement -> run -> observe -> validate -> commit -> extend`.

### Step 2 — Exact Plan approval stops at PLAN_APPROVED

**Objective:** reuse the artifact approval mechanism for a single V2 gate and persist a durable approval stop state.

**Observable outcome:** after inspecting status, the user approves the displayed Plan artifact UUID. A fresh process reports `v2/plan/plan_approved`, artifact approval `approved`, and `No implementation has started.` Runtime call count and task-row count do not increase.

**Why necessary:** Plan generation alone does not prove that human authority gates progression or survives process exit.

**Classification:** **REUSE** approval persistence; **ADAPT** V2 routing/guards/transition and output.

**Existing components reused:** CLI `approve` syntax, immutable artifact UUID/hash/revision, `approvals` table, unique decision constraint, `record_approval()` transaction, operations/events, status/log projections.

**Expected files/modules affected:**

- `src/engineering_flow/orchestrator.py`: V2 `approve` guard and `plan_approved` transition.
- `src/engineering_flow/cli.py`: lifecycle-aware approval dispatch and approved-stop rendering.
- `src/engineering_flow/store.py`: normally no structural change; only a minimal generalization if required to name `plan.approved` in the existing atomic transition.
- focused tests in `tests/test_orchestrator.py`, `tests/test_store.py`, and `tests/test_cli.py`.

**Persistence changes:** one existing approval row and approval operation; Plan artifact becomes approved; workflow becomes `plan/plan_approved`; `approval.recorded` and `plan.approved` are durable. No new generation, execution, task, cycle, or task-artifact record.

**Automated tests:** correct current artifact approves atomically; state reopens after store/CLI process exit; duplicate decision conflicts without mutation; wrong-workflow/Intake/noncurrent artifact conflicts; artifact tamper blocks approval; Plan binding is revalidated; `resume` after approval is idempotent and dispatches no runtime; V1 approvals retain their existing transitions.

**Manual CLI validation:** perform Demonstration B in section 17, then reopen with `status --json` and inspect logs. Confirm the latest execution remains the Planner execution and `tasks` remains empty.

**Acceptance criteria:** one exact Plan artifact is approved; approval survives restart; workflow clearly says implementation may begin only in a later MDS; no implementation begins.

Commit this checkpoint before Step 3.

### Step 3 — Rejection, stale-decision protection, and compatibility closure

**Objective:** complete the second human decision path, prove stale/repeated decisions fail closed, and close repository-wide compatibility and failure coverage.

**Observable outcome:** a separate waiting workflow can be rejected with a reason and reopens at `v2/plan/rejected`; `resume` does not regenerate it. Attempts to decide an Intake artifact, another workflow's artifact, a tampered Plan, or an already decided Plan fail without state/event mutation. V1 and older databases still behave as before.

**Why necessary:** durable approval is incomplete without a safe rejection/staleness boundary and regression proof.

**Classification:** **ADAPT** V2 rejection/guards; **REUSE** persistence, compatibility defaults, and full validation.

**Existing components reused:** CLI `reject --reason`, `ApprovalDecision.REJECTED`, approval uniqueness, artifact hashing, conflict exit code, additive database compatibility, V1 regression suites.

**Expected files/modules affected:** normally `src/engineering_flow/orchestrator.py`, `src/engineering_flow/cli.py`, and focused tests; production modules from Steps 1–2 only if a demonstrated safety/compatibility defect requires a minimal correction. No new subsystem.

**Persistence changes:** one existing rejection approval row; Plan artifact becomes rejected; workflow remains `plan` with status `rejected`; append `approval.recorded` and `plan.rejected`. No replacement revision.

**Automated tests:** rejection reason persistence; reopen; no regeneration/provider call on resume; stale, cross-workflow, wrong-stage, duplicate, and post-rejection decisions; no event mutation on rejected conflicts; legacy database open/default lifecycle behavior; V1 `--feature-file`, resume, approve, reject, task import/execution tests unchanged; all Step-1 progress/failure safety tests; full 131-plus suite.

**Manual CLI validation:** perform Demonstration C and the V1 smoke test in section 17. Run full validation.

**Acceptance criteria:** rejection is durable and terminal for this MDS; stale approval is impossible through public commands; machine output remains clean; provider timeout/failure leaves no approvable Plan; all V1 and MDS #1 behavior passes unchanged.

## 16. Automated testing strategy

Use only current `unittest` conventions and injected fakes.

| Requirement | Primary coverage |
| --- | --- |
| Strict Plan schema and Task Contract parsing | `test_domain.py`, `test_codex_cli.py` |
| Dependencies/order/cycle exclusion | `test_domain.py` |
| Separate complexity/risk enums | `test_domain.py` |
| Feature Contract UUID/hash/revision binding | `test_domain.py`, `test_orchestrator.py`, `test_store.py` |
| Planner read-only and no implementation | `test_codex_cli.py`, `test_orchestrator.py`, `test_cli.py` |
| Plan artifact persistence/reopen/hash verification | `test_store.py`, `test_cli.py` |
| Waiting-approval transition | `test_orchestrator.py`, `test_cli.py` |
| Exact/stale artifact approval | `test_orchestrator.py`, `test_cli.py` |
| Rejection and no regeneration | `test_orchestrator.py`, `test_cli.py` |
| No implementation after approval | assert no Developer/Reviewer request and no task/cycle/task-artifact rows |
| Progress propagation | `test_runtime.py`, `test_codex_cli.py`, `test_orchestrator.py` |
| CLI TTY rendering and stderr selection | `test_cli.py` with injected streams/TTY predicate |
| JSON/non-TTY cleanliness | parse exact stdout JSON; assert stderr empty |
| Timeout/hang safety | scripted fake process + fake monotonic clock, no real sleep |
| V1 and MDS #1 compatibility | existing full suite plus explicit routing/state assertions |

Run targeted files after each step, then the sole full repository validation:

```bash
.venv/bin/python3 -m unittest discover -s tests -q
```

Do not introduce pytest, snapshot frameworks, terminal emulators, or timing-based sleeps.

## 17. Real CLI demonstrations

Use a disposable clean Git worktree or intentionally preserve any existing user changes. Initialize once if needed:

```bash
.venv/bin/engineering-flow init --repo .
```

### Demonstration A — real Planner, progress, persistence, inspection

Create a READY Feature Contract using the real MDS #1 path:

```bash
.venv/bin/engineering-flow run --repo . --request "Allow users to cancel an order before shipment. Only PENDING orders may be cancelled. SHIPPED orders cannot be cancelled."
```

Capture the printed workflow UUID as `WORKFLOW_ID`, verify Intake READY, then enter Plan explicitly:

```bash
.venv/bin/engineering-flow resume --repo . --workflow "$WORKFLOW_ID"
```

In a TTY, observe at least:

```text
→ PLAN started
  Codex running... 10s
✓ PLAN completed (<elapsed>s)
```

If the real call completes in under ten seconds, the start and completion lines are sufficient; automated fake-clock coverage proves scheduled heartbeats. The final output must list the Plan artifact and all Task Contracts and end waiting for approval.

Reopen in a new process:

```bash
.venv/bin/engineering-flow status --repo . --workflow "$WORKFLOW_ID"
.venv/bin/engineering-flow status --repo . --workflow "$WORKFLOW_ID" --json
.venv/bin/engineering-flow logs --repo . --workflow "$WORKFLOW_ID" --json
git status --short
```

Prove `lifecycle_version=v2`, `stage=plan`, `status=awaiting_approval`, Feature Contract binding, pending Plan artifact, complete task fields, durable Plan/runtime events, and no tracked implementation change. Record the Plan artifact UUID as `PLAN_ARTIFACT_ID`.

Also prove machine mode does not emit progress:

```bash
.venv/bin/engineering-flow resume --repo . --workflow "$WORKFLOW_ID" --json >resume.json 2>resume.err
```

Because the workflow is already waiting, this is idempotent and makes no provider call; `resume.json` must be one parseable JSON object and `resume.err` empty.

### Demonstration B — approval without implementation

```bash
.venv/bin/engineering-flow approve --repo . --workflow "$WORKFLOW_ID" --artifact "$PLAN_ARTIFACT_ID"
.venv/bin/engineering-flow status --repo . --workflow "$WORKFLOW_ID" --json
.venv/bin/engineering-flow resume --repo . --workflow "$WORKFLOW_ID"
```

Prove `stage=plan`, `status=plan_approved`, Plan artifact approval `approved`, a durable approval event, unchanged Planner execution count, empty legacy `tasks`, and explicit output that no implementation started. The final resume is a no-op.

### Demonstration C — rejection and stale protection

Create a second READY workflow and resume it to a Plan, then:

```bash
.venv/bin/engineering-flow reject --repo . --workflow "$REJECT_WORKFLOW_ID" --artifact "$REJECT_PLAN_ARTIFACT_ID" --reason "Revise the task boundaries before implementation."
.venv/bin/engineering-flow status --repo . --workflow "$REJECT_WORKFLOW_ID" --json
.venv/bin/engineering-flow resume --repo . --workflow "$REJECT_WORKFLOW_ID"
```

Prove durable `plan/rejected`, no provider redispatch, and no new Plan. Attempting to approve the rejected artifact must return the existing conflict exit behavior and leave events unchanged.

### V1 compatibility smoke

Use a small existing feature file:

```bash
.venv/bin/engineering-flow run --repo . --feature-file /path/to/feature.md
```

Prove it still creates a historical workflow at PRD and follows the existing V1 approval/resume behavior, with no V2 Plan projection or progress regression.

## 18. Final MDS acceptance criteria

MDS #2 is complete only when all are true:

1. Only `resume --workflow` can advance a persisted `v2/intake/ready` workflow into Plan.
2. The Planner receives the exact verified Feature Contract and runs through Codex in a read-only sandbox.
3. Interactive users receive immediate stage-start feedback and monotonic 10-second heartbeats during a long provider call.
4. No raw provider JSONL, stderr, prompt, tool payload, final prose, or hidden reasoning is streamed to the terminal.
5. The strict Plan JSON and every Task Contract pass deterministic validation, including exact source binding, dependencies, context paths, complexity, and risk.
6. One hash-bound Plan artifact is persisted with pending approval; no V1 task/execution rows are imported.
7. Human and JSON status expose enough Plan detail to make an informed decision after process exit.
8. Approval/rejection require the exact current pending Plan artifact and verify its hash/content binding.
9. Approval persists `plan/plan_approved` and stops; rejection persists `plan/rejected` and stops.
10. No Developer/Reviewer execution, implementation edit, task cycle, test execution, review, fix, or automatic regeneration occurs.
11. Provider failure, timeout, and unknown outcome leave no approvable Plan and persist a safe state.
12. `resume --json`, non-TTY output, `status --json`, and `logs --json` remain free of progress noise.
13. A fresh process reconstructs Plan and decision state from SQLite/artifacts and detects artifact tampering.
14. V1 `--feature-file` workflows, older databases, and all MDS #1 READY/NEEDS_CLARIFICATION behavior remain supported.
15. The complete repository test suite passes and the real CLI demonstrations succeed.

## 19. Explicitly out of scope

- implementation/Developer execution or task import;
- Verify, Review, Fix, or task acceptance;
- Plan regeneration/revision after rejection;
- clarification submission/resume;
- autonomous or parallel task scheduling;
- model routing/escalation beyond invoking the configured existing runtime;
- PRD, Tech Spec, Wave, release governance, or work on `CanonicalLifecycleOrchestrator`;
- deterministic project verification execution (the Plan records future verification only);
- Git worktrees, commits, pushes, PRs, greenfield bootstrap, or advanced MCP input;
- full V1 migration/retirement;
- raw token/tool streaming, chain-of-thought, full telemetry/accounting, TUI/curses, daemon, WebSocket, dashboard, or external monitoring;
- new authoritative `.ai` files, Plan/task tables, or background workers.

## 20. Risks and compatibility concerns

- **Accidental V1 routing:** current CLI sends every `resume`/decision to `PlanningOrchestrator`. Mitigate by loading the workflow first and branching only on persisted lifecycle version; retain V1 tests unchanged.
- **Misusing V1 task persistence:** its Markdown parser and columns are not the V2 schema. Keep Task Contracts inside the Plan artifact for this MDS and assert no task rows.
- **Approval accidentally starts execution:** V1's final task-plan approval transitions toward Wave 2. V2 must have its own decision transition to `plan_approved` and no call to `_resume_task_execution()` or `import_task_plan()`.
- **Stale/tampered approval:** an artifact UUID alone is insufficient if the file is not re-read. Require latest revision, pending state, hash verification, parsed identity, and source binding before transaction.
- **Progress leaks provider content:** current `NormalizedEvent.payload` can include agent messages. Map only fixed lifecycle facts and heartbeat; never hand raw payloads to the CLI renderer.
- **Pipe deadlock/regression:** preserve the current concurrent stdout/stderr draining loop. Add heartbeat checks inside it rather than returning to blocking `communicate()`.
- **Timing-flaky tests:** inject monotonic time and interval; do not sleep.
- **Callback changes execution semantics:** make the sink optional/best-effort and exclude it from hashing/persistence. Existing runtimes/fakes that ignore it remain valid where structural typing permits; update shared fakes deliberately.
- **Global `current_artifact_revision`:** it is not stage-specific. This MDS has exactly one Plan revision and explicitly validates against the latest `Stage.PLAN` artifact as well as the row. Future regeneration must revisit this carefully.
- **Provider timeout:** current adapter kills the subprocess and returns a distinct timed-out terminal state. Retain this behavior, keep heartbeats bounded by the same monotonic deadline, and never print completion on timeout.
- **Schema evolution:** adding enum values requires no SQLite DDL, but every conversion/mapping and artifact-label switch must recognize `plan`. Legacy persisted values must continue parsing unchanged.

## 21. Expected final observable behavior

```text
$ engineering-flow run --repo . --request "Allow users to cancel an order before shipment. Only PENDING orders may be cancelled. SHIPPED orders cannot be cancelled."
command: success
workflow: <workflow-id>
status: ready
stage: intake
Intake: READY

$ engineering-flow resume --repo . --workflow <workflow-id>
→ PLAN started                         # stderr, interactive TTY
  Codex running... 10s                 # stderr
  Codex running... 20s                 # stderr
✓ PLAN completed (24.8s)               # stderr
command: success                       # stdout
workflow: <workflow-id>
status: awaiting_approval
stage: plan
Plan: <workflow-id>:plan:r1 revision=1
Plan artifact: <artifact-id> approval=pending
Strategy: ...
Tasks:
  T1 ... complexity=medium risk=low depends_on=[]
  T2 ... complexity=low risk=medium depends_on=[T1]
Waiting for human approval.

$ engineering-flow approve --repo . --workflow <workflow-id> --artifact <artifact-id>
command: success
workflow: <workflow-id>
status: plan_approved
stage: plan
Plan approved.
No implementation has started.
```

After either process exits, `status --json` reports the same hash-verified structured Plan and decision. The approved workflow has no Developer execution and cannot advance further in this MDS.
