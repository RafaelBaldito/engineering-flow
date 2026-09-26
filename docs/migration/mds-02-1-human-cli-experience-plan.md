# Engineering Flow V2 — MDS #2.1 Human CLI Experience Implementation Plan

## 1. Objective

MDS #2.1 makes the implemented V2 Intake-and-Plan slice usable as one human-oriented command without changing its authority model:

```text
engineering-flow run "Add a version command..."
    -> INTAKE
    -> PLAN when Intake is READY
    -> concise Plan review
    -> one human approval/rejection prompt when interactive
    -> PLAN_APPROVED or REJECTED
    -> STOP
```

The default CLI expresses user intent; a V2 workflow coordinator owns state-machine progression. Normal use must not require copying workflow or artifact UUIDs or manually resuming between `READY` and `PLAN`. Explicit `--workflow`, `--artifact`, `resume`, `approve`, `reject`, `status`, `logs`, and `intervene` remain available as operator controls.

This is a planning-only MDS. It does not execute Task Contracts or begin MDS #3. Approval remains an exact decision on the immutable, hash-verified canonical JSON Plan and stops at `plan/plan_approved`.

## 2. Current verified baseline

Repository inspection and `.venv/bin/python3 -m unittest discover -s tests -q` establish a clean baseline of **144 passing tests**.

### 2.1 Implemented V2 behavior

- `IntakeOrchestrator` creates a V2 workflow, retains `request.txt`, calls a read-only Intake runtime, validates `FeatureContract`, and atomically completes at `intake/ready`, `intake/needs_clarification`, or `intake/rejected` with `001-feature-contract.json`.
- `V2PlanOrchestrator.resume()` is the only V2 successor. From exactly `intake/ready`, it verifies the Feature Contract, calls the read-only Planner, validates `Plan` and every `TaskContract`, and persists `002-plan.json` at `plan/awaiting_approval`.
- V2 approval and rejection re-read and hash-verify both the current Plan and its exact Feature Contract source. They validate revision, stage, pending state, ownership, Plan identity, and source UUID/SHA binding before `record_approval()` atomically records the decision and workflow transition.
- Approval stops at `plan/plan_approved`; rejection stops at `plan/rejected`. Neither path creates legacy task rows or dispatches Developer/Reviewer work.
- V1 remains routed through `PlanningOrchestrator`; `CanonicalLifecycleOrchestrator` is separate unfinished V1/canonical work and is not part of this MDS.

### 2.2 CLI and output

- `cli.py` uses `argparse`. V2 creation currently requires `run --request TEXT`; the positional request form does not exist.
- `status`, `resume`, `approve`, `reject`, `logs`, and `intervene` require both `--repo` and `--workflow`. Decisions additionally require `--artifact`.
- `run --request` stops after Intake. A separate `resume` is required to enter Plan, and approval is another command.
- `_workflow_payload()` is the current shared projection. It hash-verifies every canonical artifact. For V2 Plan it includes the complete canonical Plan in JSON.
- `_print_result()` mixes data projection and terminal presentation. Default output prints command/status metadata, the entire Plan contract, every artifact UUID, and every task field after `resume`, decisions, and `status`.
- JSON output is a single sorted JSON document, but `run`, `approve`, and `reject` do not currently expose `--json`. There is no verbose mode or color policy.

### 2.3 Runtime progress

- `RuntimeProgressEvent(kind, stage, elapsed_seconds, message)` and an optional `progress_sink` already form a provider-neutral transient progress boundary.
- `CodexCliRuntime._stream_process()` concurrently drains stdout/stderr, normalizes JSONL, uses an injectable monotonic clock, emits safe heartbeats, and maps only `thread.started` to the fixed message `Agent session started`. Sink exceptions are swallowed.
- Raw provider JSONL remains normalized evidence; arbitrary messages, prompts, tool payloads, stderr, and reasoning are not forwarded as progress.
- `V2PlanOrchestrator` emits Plan start/completion/failure events around the runtime call. `_progress_renderer()` is hard-coded to `PLAN`, prints one line per event, and only exists for TTY stderr.
- Intake uses the compatibility `execute_planning()` call without a sink. It also marks execution running only after the provider returns, so Intake is silent and its running boundary differs from Plan.

### 2.4 Persistence and recovery

- `.engineering-flow/workflows.sqlite3` is authoritative. It stores workflows, immutable artifact metadata/hashes, approvals, sessions, executions, idempotent operations, and monotonic events under additive schema migration.
- Canonical Plan JSON lives at `.engineering-flow/workflows/<workflow-id>/artifacts/002-plan.json`. There is no Plan Markdown projection.
- There is no selected-workflow table, pointer, or workflow-list API. The only workflow lookup is by UUID.
- `complete_generation()` binds the requested stage/revision/path, writes immutable bytes, hashes them, then records artifact/execution/operation/workflow/event changes in one SQLite transaction. Filesystem and SQLite are coordinated but are not a true cross-resource transaction.
- Pending/unknown operations and durable state already support fail-closed recovery. MDS #2.1 must compose with these boundaries rather than create conversational state.

### 2.5 Dependency and compatibility constraints

- `pyproject.toml` requires Python 3.13 and currently has no runtime dependencies. `pytest` is optional development-only, while tracked tests use `unittest`.
- Linux/WSL with `.venv/bin/python3` is canonical. The only full validation command is the unittest discovery command above.
- CLI adapters must delegate lifecycle policy to orchestration. Rendering must remain outside domain and persistence logic.

## 3. Problems observed in real smoke testing

The implementation is correct but exposes internal recovery and audit identifiers as mandatory interaction:

1. The user must copy a workflow UUID after `run`.
2. The user must know that `READY` requires `resume` to start Plan.
3. The user must copy the Plan artifact UUID for approval.
4. The user must understand stage/status combinations to know the next legal action.
5. The same complete Plan structure is repeatedly dumped into the terminal.
6. Plan shows live progress, but Intake can wait silently for the same provider.
7. The canonical Plan is excellent machine evidence but poor as the only human review document.
8. Automation safety is implicit: command behavior is not designed around stdin/stdout/stderr TTY combinations.

The solution is a thin human-experience layer plus a small V2 workflow coordinator. It is not a new lifecycle, a replacement store, or a weakened approval API.

## 4. UX principles

1. **Intent first:** `run REQUEST` means “advance this feature until a real human boundary.”
2. **Orchestrator owns progression:** CLI rendering and prompts report or submit intent; they do not choose legal successors.
3. **Happy path simple, recovery explicit:** UUID-free commands use persisted context only when safely resolvable; explicit IDs always remain available.
4. **One authority:** JSON artifacts, database state, and existing SHA/source-binding checks remain canonical. Markdown and terminal views are derived.
5. **Fail closed:** no ambiguous workflow or artifact is silently selected and no prompt is issued without a fully verified Plan.
6. **Machine-safe by construction:** JSON mode never prompts, animates, emits ANSI, or writes progress noise.
7. **Progress is stage-neutral:** Intake, Plan, and future agent-backed stages use one safe event vocabulary and renderer contract.
8. **Meaning without color:** symbols, words, stage names, and statuses carry the meaning; color is optional enhancement.
9. **Future composition:** the coordinator can add IMPLEMENT/VERIFY/REVIEW/FIX state handlers later, but this MDS stops after the Plan decision.

## 5. Target happy path

### 5.1 Command contract

Add the preferred positional request while preserving existing forms:

```text
engineering-flow run "Add a version command..."
engineering-flow run --request "Add a version command..."   # compatible alias
engineering-flow run --feature-file feature.md               # unchanged V1 route
```

The positional request, `--request`, and `--feature-file` are mutually exclusive; exactly one is required. `--repo` continues to default to `.` for `run` and should default to `.` for human/operator commands in this MDS.

For a V2 request, `run`:

1. creates the workflow and records it as the repository's selected workflow;
2. executes Intake with progress;
3. if Intake is `READY`, advances directly to Plan with no manual resume;
4. if Plan reaches `AWAITING_APPROVAL`, verifies and renders the concise Plan plus Markdown path;
5. prompts only when the invocation is eligible for interaction;
6. submits the selected decision through the same artifact-bound orchestration method used by explicit commands;
7. prints the final decision state and stops.

The coordinator returns at all real boundaries: clarification, rejection/failure/human attention, non-interactive approval wait, or Plan decision. It must have an explicit dispatch table and a maximum number of internal transitions per invocation so a future bad transition cannot spin. The MDS #2.1 path needs at most Intake and Plan; use a small defensive cap (for example, 8 transitions), not a product execution budget.

### 5.2 State behavior

| Durable state reached | `run` behavior |
| --- | --- |
| `intake/ready` | Automatically dispatch Plan in the same process. |
| `intake/needs_clarification` | Show numbered questions and stop; no Plan call. |
| `intake/rejected`, `failed`, `human_attention` | Show concise terminal/attention state and stop. |
| `plan/awaiting_approval`, interactive | Show verified summary/path and prompt. |
| `plan/awaiting_approval`, non-interactive | Show/return pending boundary and stop successfully without prompting. |
| `plan/plan_approved` | Print approval and `No implementation has started.`; stop. |
| `plan/rejected` | Print rejection acknowledgement; stop. |

No `resume` occurs after approval in MDS #2.1 because there is no successor. When MDS #3 adds one, the coordinator can continue its state dispatch after approval without changing the `run` command or presentation contract.

## 6. Advanced CLI contract

### 6.1 Commands retained

Retain all existing commands and explicit selectors:

```text
status, resume, approve, reject, logs, intervene
--workflow ID
--artifact ID
```

For this MDS, make `--workflow` optional for `status`, `resume`, `approve`, and `reject`. Keep it required for `logs` and `intervene`: log history and task intervention are advanced, potentially high-volume/high-impact operations and are not needed by the new daily path. This is a deliberate minimal boundary, not a future prohibition.

Make `--artifact` optional for `approve` and `reject`. Explicit values always override inference and are still checked by existing guards. `reject --reason TEXT` remains required for the explicit command.

### 6.2 Safe workflow resolution

Resolution order is exact:

1. If `--workflow` is present, use it. Do not modify the repository's selected workflow context.
2. Otherwise load the repository's persisted selected-workflow pointer.
3. If a valid pointer exists, use exactly that workflow even if another workflow is newer. Never scan for a “better” candidate.
4. For an older database with no pointer:
   - `status` or `resume`: resolve only when the database contains exactly one workflow;
   - `approve` or `reject`: resolve only when exactly one workflow is awaiting an approval decision;
   - zero candidates is `not_found`; more than one is `conflict` with a concise list of candidate workflow IDs/stage/status and an instruction to pass `--workflow`.
5. A dangling/corrupt pointer is a persistence error. Do not fall through and guess.

The pointer identifies the workflow selected by the most recent successful `run` creation in that repository; it does not mean “newest unfinished row.” Multiple unfinished workflows are therefore safe: the explicit persisted selection wins. Starting a new run deliberately replaces the pointer. Explicitly inspecting a historical workflow does not unexpectedly change it.

The pointer remains after `PLAN_APPROVED`, rejection, failure, completion, or interruption so `engineering-flow status` continues to describe what the user just operated. Process interruption after workflow creation also leaves enough context for UUID-free `status`/`resume`. A future explicit `use` command is unnecessary for this MDS because `--workflow` is the escape hatch.

### 6.3 Safe artifact resolution

When `--artifact` is absent:

1. resolve the workflow as above;
2. require that its persisted state is awaiting approval;
3. ask the lifecycle-specific orchestrator to resolve its exact current pending artifact;
4. for V2, require one latest `Stage.PLAN` artifact whose revision equals the workflow projection, whose approval is pending, whose bytes match its SHA, whose Plan identity parses, and whose Feature Contract artifact UUID/SHA and READY contents verify;
5. pass that artifact to the existing atomic decision path.

The CLI must not independently choose `artifacts[-1]`. If zero, multiple, stale, noncurrent, cross-workflow, tampered, or already decided candidates are representable, fail before mutation. V1 inference may use the corresponding existing current-stage approval guard; it must not reuse V2 Plan assumptions.

### 6.4 Backward compatibility

- Every currently valid explicit command remains valid.
- Existing `--request` and V1 `--feature-file` routing remain valid.
- Existing exit-code meanings remain. Ambiguous automatic resolution uses `EXIT_CONFLICT`; no candidate uses `EXIT_NOT_FOUND`.
- Do not remove UUIDs from `--verbose`, `--json`, or error diagnostics merely because default output hides them.

## 7. Output and rendering design

### 7.1 Separate projection from presentation

Refactor `cli.py` without moving policy into it:

- orchestration returns authoritative `Workflow`/decision results;
- projection functions build stable command documents from verified store data;
- a presentation module renders those documents in `human`, `verbose`, or `json` mode;
- a progress renderer consumes only safe `RuntimeProgressEvent` values;
- prompt handling converts a human answer into an approve/reject service call.

Likely add `src/engineering_flow/presentation.py` and keep `cli.py` responsible for parsing, service wiring, and exit codes. Domain, store, and runtime must never import Rich or terminal streams.

### 7.2 Output modes

| Mode | Contract |
| --- | --- |
| Default human | Concise workflow/stage/status, current outcome, compact task rows, task count, approval state, elapsed stage results, Plan Markdown path, and next-action text. Hide UUIDs unless an ambiguity/error requires them. Never dump full arrays/contracts. |
| `--verbose` | Everything in concise mode plus workflow/artifact IDs and hashes, strategy, assumptions, verification strategy, all task fields, artifact/execution metadata, and recorded decision reason. Still excludes raw provider JSONL, prompts, arbitrary payloads, reasoning, and unsafe stderr. |
| `--json` | Exactly one stable JSON document on stdout using the existing top-level result fields and full verified projections. No prompt, ANSI, spinner, or progress on either stream. Preserve existing keys and semantics; additions such as `plan_markdown_path`, `next_action`, and context-resolution metadata are additive. |

Expose `--json` for `run`, `approve`, and `reject` as well as existing machine-readable commands. Expose `--verbose` on human state/result commands and make it mutually exclusive with `--json`. `logs --json` retains its current line-free single-document behavior; human logs remain line-oriented and are not routed through a spinner.

Default Plan output should resemble:

```text
✓ Plan generated · 40.3s

Workflow
  Stage      PLAN
  Status     AWAITING_APPROVAL

Plan
  Revision   1
  Tasks      2
  Approval   PENDING

Tasks
  T1  Implement version CLI command
      low complexity · medium risk
  T2  Add automated coverage
      low complexity · low risk · depends on T1

Plan
  .engineering-flow/workflows/<id>/artifacts/002-plan.md
```

### 7.3 Rich versus internal ANSI

**Recommendation: adopt Rich as the single runtime presentation dependency.**

An internal ANSI renderer would preserve the zero-dependency package, but MDS #2.1 needs more than colored strings: terminal capability detection, width-aware tables, a replace-in-place live status, stream control, `NO_COLOR`, dumb-terminal handling, and deterministic capture in tests. Reimplementing those behaviors would create a second terminal framework inside `cli.py` and add platform edge cases.

Rich already provides `Console` terminal/dumb-terminal detection, `no_color`, `Live`/`Status`, redirected-stream behavior, and StringIO/capture testing. Its use must be confined to `presentation.py`; no Rich types cross orchestration/runtime/domain APIs. Add a conservative compatible version range to `[project].dependencies` during implementation after verifying it under Python 3.13. Do not add a TUI/curses abstraction.

### 7.4 Color and terminal policy

- green: successful/READY/approved/completed;
- yellow: waiting, pending approval, clarification, human attention;
- red: failed/rejected/timed out/interrupted;
- cyan/blue: active stage;
- dim: IDs, hashes, secondary metadata.

Every styled value includes a word/symbol conveying the same meaning. Instantiate explicit stdout and stderr consoles so tests and redirection are controllable. Honor `NO_COLOR`; add `--no-color` for deterministic operator control. `--no-color` affects only presentation, never JSON. Treat `TERM=dumb`/unsupported ANSI as plain text. Do not offer `--force-color` in this MDS because forced escapes are hazardous in captured logs.

## 8. Human-readable Plan Markdown design

### 8.1 Authority and location

Keep `002-plan.json` as the only Plan artifact row and the only approval identity. Add a deterministic derived sibling:

```text
.engineering-flow/workflows/<workflow-id>/artifacts/002-plan.md
```

`002-plan.md` is not inserted into `artifacts`, receives no artifact UUID/revision/approval state, is not included in the canonical Plan SHA, and is never accepted as input to approval. Call it a **projection** in code and user text, not a second artifact.

### 8.2 Deterministic renderer

Add a pure `render_plan_markdown(plan: Plan) -> str` function, likely in `src/engineering_flow/plan_markdown.py`. It consumes only the already validated immutable `Plan` value and emits stable UTF-8 with LF newlines, fixed section/field order, fixed bullet/number formatting, and one trailing newline.

The projection contains:

1. Plan title, revision, and non-authoritative source note;
2. strategy;
3. assumptions;
4. verification strategy;
5. one task section in canonical task order containing objective, dependencies, complexity, risk, relevant files, existing patterns, requirements, acceptance criteria, verification, and constraints.

Empty allowed arrays render consistently as `None.` rather than disappearing. Dynamic timestamps, terminal width, artifact UUID decorations not already in the Plan, and provider metadata are excluded so equal Plan JSON always produces equal Markdown bytes.

### 8.3 Creation, recovery, and tampering

- Generate the projection immediately after canonical Plan validation and successful JSON persistence.
- Treat it as a reconstructible cache, not a cross-resource transaction participant. A Markdown write failure must not roll back or invalidate an already authoritative JSON Plan.
- Use a workspace-confined temporary sibling plus `os.replace()` for atomic replacement.
- A human `run`, `resume`, or `status` that needs the projection first verifies/parses canonical JSON, deterministically recomputes Markdown, and compares bytes. If missing, recreate it. If edited/tampered, replace it with the canonical projection and optionally report `Plan view regenerated from canonical JSON` in verbose diagnostics.
- `--json` status remains observation-only: report expected `plan_markdown_path` and `projection_state` (`current`, `missing`, or `modified`) without repairing it. This avoids surprising writes in machine inspection.
- If projection repair fails, preserve the workflow and JSON Plan, show a warning/path failure, and do not issue an interactive approval prompt in that invocation. The user can retry or inspect `--verbose`/`--json`; explicit artifact-bound approval remains available.

Status and run display a repository-relative projection path when possible and an absolute path only when the repository relationship cannot be established.

## 9. Workflow-wide progress and observability

### 9.1 Event ownership

Reuse `RuntimeProgressEvent` and the optional sink. Define and document the safe event vocabulary:

| Producer | Event kinds | Meaning |
| --- | --- | --- |
| Orchestrator/coordinator | `started`, `completed`, `failed`, `timed_out`, `interrupted` | Stage lifecycle around one bounded call. |
| Runtime adapter | `activity`, `heartbeat` | Fixed provider-neutral activity and elapsed liveness. |

The stage field drives all labels; no renderer hard-codes Plan. Runtime activity messages must come from an allow-list of fixed translations such as `Agent session started`, never from provider text. Unknown kinds/messages render as no-op. Sink failure is caught at every producer boundary and cannot change execution or persistence.

### 9.2 Intake adaptation

Give `IntakeOrchestrator.run()`/its internal execution a sink, call `start_execution()` immediately before dispatch as Plan already does, use the generalized runtime call with `progress_sink`, and emit Intake start/terminal events. Preserve the same request hash by excluding the transient sink. Do not alter the Feature Contract schema or outcomes.

Factor the duplicated orchestration timing/emission into a small provider-neutral helper only if it leaves state transitions in each orchestrator. Do not make the terminal renderer the helper.

### 9.3 TTY and non-TTY behavior

- Interactive stderr terminal: use one live line, for example `⠋ PLAN · Agent running · 37s`; replace it with a durable terminal line such as `✓ PLAN completed · 40.3s`.
- Non-TTY stderr in human mode: emit stable start and terminal lines only. Suppress periodic heartbeat/activity churn; never use carriage returns or ANSI.
- JSON mode: provide no progress sink and emit no progress on stdout or stderr.
- A stage transition first finalizes the previous live display, then starts the next.
- Elapsed time uses injected monotonic time and is presentation-only. Durable events and workflow correctness never depend on it.

Future IMPLEMENT/REVIEW/FIX runtime calls can supply the same sink; deterministic VERIFY may emit the same stage lifecycle events from orchestration without pretending it is an agent call. No future stage is implemented here.

## 10. Selected workflow resolution

### 10.1 Persistence choice

Persist an explicit repository-local **selected workflow context** in SQLite rather than deriving “latest” from timestamps. Add an additive singleton table such as:

```text
repository_context(
    singleton_key PRIMARY KEY CHECK singleton_key = 'current',
    selected_workflow_id REFERENCES workflows(id),
    updated_at NOT NULL
)
```

The database is already repository-local, so another repository key is unnecessary. Update this row in the same transaction that creates a workflow. Provide `get_selected_workflow()` and narrowly scoped resolution/list APIs; the CLI must not query private connections.

This strategy is safer than “most recently updated unfinished workflow”: progress, status repair, or an old explicit action must not silently steal the selected workflow context, and terminal/rejected workflows must remain inspectable after the process exits.

### 10.2 Ambiguity and lifecycle rules

- New `run`: new workflow becomes selected atomically.
- Multiple unfinished workflows: current pointer selects one; without a pointer, fail closed unless the action-specific fallback has exactly one candidate.
- Completion/rejection/approval/failure: retain pointer.
- Process interruption: retain pointer and let normal durable recovery/resume rules apply.
- Historical workflow operation with explicit UUID: explicit value wins for that invocation and does not rewrite the selected workflow context.
- Explicit `--workflow`: always overrides automatic resolution.
- Wrong lifecycle/stage for the requested action: report the current state and legal next action; do not search for another workflow.
- Older database: create the table additively. Do not manufacture a pointer from timestamps. Use only the exact-one fallbacks in section 6.

## 11. Interactive and non-interactive behavior

### 11.1 Interaction eligibility

Add `--non-interactive` to `run`. It is useful even with detection because a script may inherit a controlling TTY. There is no `--interactive` force flag.

Approval prompting is enabled only when all are true:

1. stdin is a TTY;
2. stdout is a TTY;
3. `--json` is absent;
4. `--non-interactive` is absent;
5. a recognized CI environment indicator is not truthy.

stderr TTY controls dynamic progress only; redirected stderr does not disable a safe prompt when stdin/stdout remain terminals. If stdout is redirected or stdin is piped, the command never reads input. `--json` implies non-interactive and conflicts with `--verbose`.

### 11.2 Approval prompt

After verified Plan rendering:

```text
Approve this plan? [Y/n]
```

- Enter, `y`, or `yes`: approve the exact verified current Plan.
- `n` or `no`: ask for a non-empty rejection reason, then reject the same exact Plan.
- Any other value: reprompt locally with a short valid-choice message; do not call orchestration.
- The artifact ID used by the decision is captured from the verified Plan boundary displayed immediately before the prompt and is revalidated by orchestration at submission time. A concurrent/stale change therefore conflicts rather than approving another artifact.

### 11.3 EOF, interruption, and process safety

- EOF while waiting for approval/reason: leave `plan/awaiting_approval` unchanged, print the explicit `approve`/`reject` recovery command, and return the normal human-boundary result.
- Ctrl+C while waiting for approval: print `Approval left pending`, leave state unchanged, and exit 130.
- Ctrl+C during an agent call: the Codex adapter terminates the owned subprocess, drains bounded output, and re-raises cancellation; orchestration records the in-flight operation as unknown/human attention using existing recovery semantics; the renderer clears its live line; CLI exits 130. Never record success or a decision.
- Interruption between Plan persistence and Markdown creation may leave a missing projection; the recovery behavior in section 8 reconstructs it.
- Non-interactive/CI execution reaches `awaiting_approval`, emits no prompt, and exits successfully because a requested workflow advanced to a legitimate human boundary. JSON communicates `next_action: approve_or_reject`.

## 12. Clarification behavior

### 12.1 MDS #2.1 boundary

Do **not** add interactive clarification answers in MDS #2.1. The current model has one retained raw request, one `001-feature-contract.json`, one Intake revision expected by Plan, and no contract for answer provenance or multiple Intake revisions. Appending answers to the prompt or conversation would create hidden state; overwriting the Feature Contract would violate immutability.

When Intake returns `NEEDS_CLARIFICATION`, the same `run` process:

1. completes Intake progress;
2. prints numbered persisted `open_questions`;
3. states that no Plan was generated;
4. stops without reading stdin in either interactive or non-interactive mode;
5. keeps the workflow selected for UUID-free `status`;
6. instructs the user to refine the request and start a new run in MDS #2.1.

This is an explicit smaller safe slice. It still fixes silent Intake waiting and provides clear questions, but does not pretend that the current persistence model can continue a clarification conversation.

### 12.2 Required later clarification slice

A follow-up MDS #2.2 should define, before implementation, immutable clarification-round input artifacts, actor/timestamp/question binding, revised Feature Contract numbering/source lineage, Plan binding to the latest READY revision, an answers-file path for automation, and a deterministic maximum round count. The persisted artifacts—not chat history—must be authoritative. This later design must also resolve the current `001-feature-contract.json`/`002-plan.json` naming assumption before adding revisions.

No unresolved product question may be defaulted, inferred from EOF, or supplied by the model.

## 13. Persistence implications

### 13.1 Schema changes

The only required database change is the additive current-context singleton table. No Plan, Markdown, conversation, task, or execution-stage table is added. Older databases acquire the empty table on open and retain all historical rows unchanged.

### 13.2 Canonical and derived files

- Canonical: request input, Feature Contract JSON, Plan JSON, their hashes/rows, approvals, executions, operations, and events.
- Derived: Plan Markdown and terminal/JSON projections.
- Approval identity remains only the canonical Plan artifact UUID plus verified bytes/source binding.
- The Markdown path may be reported in projections but never stored as approval evidence.

### 13.3 Events and telemetry

Transient progress is not durable evidence. Existing `stage`/`agent.runtime.*`/completion events remain authoritative. Do not persist spinner refreshes or heartbeat ticks. It is acceptable to add one sanitized coordinator-boundary event only if needed for recovery; presentation events are not needed.

### 13.4 Failure modes

- Context write failure rolls back workflow creation.
- Context read ambiguity/corruption produces no transition.
- Projection failure leaves canonical Plan valid but suppresses the interactive prompt for that invocation.
- Renderer/progress failure never changes workflow execution.
- Prompt EOF/Ctrl+C never creates an approval row.
- JSON/Feature Contract tampering continues to fail through existing hash checks before projection or decision.

## 14. Incremental implementation steps

Each step is a Minimum Demonstrable Slice and ends with focused tests, a real CLI observation, full validation where warranted, and a commit checkpoint. The implementation process is `implement -> run -> observe -> validate -> commit -> extend`.

### Step 1 — CLI presentation foundation

**Objective:** introduce explicit output modes and concise default rendering without changing lifecycle behavior.

**User-visible behavior:** current explicit `status/resume/approve/reject` commands produce a compact plain/Rich human view; `--verbose` exposes complete safe details; current JSON documents remain machine-parseable; `NO_COLOR`/`--no-color` work.

**Likely files:** `pyproject.toml`, `src/engineering_flow/cli.py`, new `src/engineering_flow/presentation.py`, `tests/test_cli.py`, possibly a focused `tests/test_presentation.py`.

**Responsibilities:** CLI selects mode and builds consoles; presentation renders already projected data; orchestrators/store/runtime are unchanged.

**Automated tests:** concise output excludes full contract/UUID noise; verbose contains all safe Plan fields; JSON exact parsing and prior keys; TTY/non-TTY; color enabled/disabled; `NO_COLOR`; narrow terminal; renderer exception isolation where appropriate.

**Manual demonstration:** run current explicit V2 status in default, verbose, JSON, and `NO_COLOR=1` modes.

**Acceptance:** default is scannable, verbose retains inspectability, JSON has exactly one document, no state transition changes.

**Out of scope:** automatic progression, UUID inference, Markdown, Intake progress.

**Checkpoint:** `mds-02.1 step 1: add human CLI presentation modes`.

### Step 2 — Workflow-wide progress

**Objective:** make Intake and Plan use the same stage-neutral progress path and single-line TTY renderer.

**User-visible behavior:** both stages immediately announce work, show one updating TTY status, and finish with elapsed time; non-TTY emits stable start/end lines; JSON stays silent.

**Likely files:** `src/engineering_flow/runtime.py`, `codex_cli.py`, `orchestrator.py`, `presentation.py`, `cli.py`; tests in `test_runtime.py`, `test_codex_cli.py`, `test_orchestrator.py`, and `test_cli.py`.

**Responsibilities:** runtime supplies safe provider liveness; each orchestrator supplies stage lifecycle; presentation owns dynamic/static rendering; store persists no heartbeat.

**Automated tests:** Intake progress propagation; Plan regression; fake-clock heartbeats; fixed activity mapping; single-line TTY behavior; non-TTY start/end only; sink exceptions; timeout/failure/interruption; no real sleeps or raw payload leakage.

**Manual demonstration:** invoke a real Intake then Plan and observe the same visual language for both.

**Acceptance:** silent Intake is eliminated, Plan behavior is not weakened, progress failure cannot fail execution.

**Out of scope:** future stages, durable heartbeat telemetry, provider prose streaming.

**Checkpoint:** `mds-02.1 step 2: generalize workflow progress`.

### Step 3 — Deterministic Plan Markdown projection

**Objective:** provide a durable human review view derived only from verified Plan JSON.

**User-visible behavior:** Plan completion creates `002-plan.md`; human results/status link to it; missing/edited projections are detected and repaired from JSON.

**Likely files:** new `src/engineering_flow/plan_markdown.py`; small store/workspace helper in `store.py`; `orchestrator.py`, `cli.py`, `presentation.py`; tests in `test_domain.py` or new projection tests, `test_store.py`, `test_orchestrator.py`, `test_cli.py`.

**Responsibilities:** pure renderer formats validated domain value; persistence helper confines/atomically replaces derived path; orchestrator triggers initial generation; human presentation ensures/reports projection; approval ignores it.

**Automated tests:** golden deterministic bytes; every required field; Unicode/newlines; missing recreation; manual-edit replacement; JSON status observation without repair; write failure keeps JSON authoritative and prevents auto-prompt; approval identity unchanged.

**Manual demonstration:** inspect Markdown, edit/delete it, run human status, and confirm canonical regeneration while JSON SHA/UUID remain unchanged.

**Acceptance:** one canonical source of truth, deterministic readable projection, no second approval identity.

**Out of scope:** user-authored Markdown edits, Markdown import, a projection database row.

**Checkpoint:** `mds-02.1 step 3: add derived Plan Markdown`.

### Step 4 — Selected workflow and current Plan resolution

**Objective:** remove UUID copy/paste where repository context is explicit and safe.

**User-visible behavior:** `status`, `resume`, `approve`, and `reject` work without `--workflow`; decisions work without `--artifact`; ambiguities fail with actionable candidates; explicit selectors retain precedence.

**Likely files:** `src/engineering_flow/store.py`, `orchestrator.py`, `cli.py`, `domain.py` only if a small resolution result value is useful; tests in `test_store.py`, `test_orchestrator.py`, `test_cli.py`.

**Responsibilities:** store persists/loads context and provides bounded candidate queries; lifecycle orchestrators resolve and validate the current approvable artifact; CLI handles optional arguments and actionable errors.

**Automated tests:** atomic pointer creation/update; retain after all terminal states/interruption; multiple unfinished workflows with pointer; old DB no pointer with zero/one/multiple candidates; stale pointer; explicit override; V1 compatibility; omitted/explicit artifact; wrong/stale/tampered/cross-workflow Plan; no mutation on conflict.

**Manual demonstration:** create a V2 Plan then run `status`, `approve`, and a second-workflow ambiguity scenario without copying IDs; repeat one explicit historical command.

**Acceptance:** no arbitrary timestamp selection, exact Plan checks remain intact, old databases open additively.

**Out of scope:** global cross-repository context, workflow aliases, `logs`/`intervene` inference.

**Checkpoint:** `mds-02.1 step 4: persist safe selected workflow context`.

### Step 5 — One-command V2 happy-path coordinator

**Objective:** compose Intake, automatic READY-to-Plan progression, review, and interactive decision under `run REQUEST`.

**User-visible behavior:** the required happy path completes through `PLAN_APPROVED` or `REJECTED` in one interactive command; non-interactive execution stops safely at approval; no manual resume is needed.

**Likely files:** `src/engineering_flow/orchestrator.py` (new narrow V2 coordinator/facade), `cli.py`, `presentation.py`, possibly `__init__.py`; tests in `test_orchestrator.py` and `test_cli.py`.

**Responsibilities:** coordinator owns state dispatch/transition cap; existing Intake/Plan orchestrators own their contracts; CLI owns TTY eligibility and prompts; existing decision service owns approval/rejection.

**Automated tests:** positional/request compatibility; READY automatically plans exactly once; prompt yes/default approval; `n` plus reason rejection; invalid-answer reprompt; non-interactive/CI/piped/JSON no prompt; future-boundary stop; exact artifact revalidation; no task/Developer calls; state survives reopen.

**Manual demonstration:** run the end-to-end scenario in section 16 and then UUID-free status.

**Acceptance:** one command reaches and decides the Plan boundary interactively, approval stops, and automation never hangs.

**Out of scope:** clarification answers and every post-approval stage.

**Checkpoint:** `mds-02.1 step 5: compose the V2 human happy path`.

### Step 6 — Recovery, clarification boundary, and compatibility closure

**Objective:** close interruption/EOF/failure behavior and prove V1/older-database compatibility across the complete slice.

**User-visible behavior:** Ctrl+C/EOF leave honest recoverable state; `NEEDS_CLARIFICATION` shows concise numbered questions and stops; errors always state the next safe command.

**Likely files:** minimal corrections in modules touched above; tests across `test_cli.py`, `test_codex_cli.py`, `test_orchestrator.py`, and `test_store.py`; documentation/help text.

**Responsibilities:** adapter terminates owned process; orchestrator records unknown/human attention; CLI maps prompt interruption and exit 130; Intake contract remains authoritative.

**Automated tests:** Ctrl+C during call and prompt; EOF at decision/reason; missing/tampered projection at prompt; provider timeout; process reopen; clarification stop; V1 full path; pre-context database; full 144-plus regression.

**Manual demonstration:** abort a real call, inspect/resume safely, demonstrate clarification output, run V1 explicit smoke, and complete the final smoke suite.

**Acceptance:** no orphan provider, false success, accidental decision, duplicate call, or V1 regression; full suite passes.

**Out of scope:** clarification submission/revision and MDS #3.

**Checkpoint:** `mds-02.1 step 6: close human CLI recovery and compatibility`.

## 15. Automated test matrix

Use current `unittest`, temporary repositories/databases, injected streams/consoles, fake runtimes/processes, and injected monotonic clocks. Never sleep in a test.

| Area | Required assertions |
| --- | --- |
| Default concise output | Shows stage/status/task summary/path/next action; omits full lists and routine UUIDs. |
| Verbose output | Includes all safe Plan fields, identities, hashes, artifacts, execution metadata, and reason. |
| JSON stability | One stdout document, no stderr/progress/prompt/ANSI; existing keys/values preserved and additions are deterministic. |
| Color/no-color | Semantic styles on supported TTY; words/symbols remain; `NO_COLOR`, `--no-color`, dumb terminal, and non-TTY contain no color escapes. |
| TTY combinations | Test stdin/stdout/stderr independently; prompt eligibility follows section 11; stderr selection controls only dynamic progress. |
| Progress | Fake clock proves heartbeat schedule and elapsed terminal result; TTY updates one line; non-TTY has bounded lines; sink failure is harmless. |
| Intake progress | Started/activity/heartbeat/completed and all failure outcomes are stage-labeled `INTAKE`. |
| Plan progress regression | Existing safe activity, timeout, payload privacy, and read-only behavior remain. |
| Markdown determinism | Same validated Plan yields byte-identical complete Markdown; no volatile fields. |
| Markdown missing/tampered | Human access repairs atomically; JSON reports state without repair; JSON artifact UUID/hash/approval remain unchanged. |
| Selected workflow | New run atomically selects; terminal/interrupted state retains; explicit override does not mutate; dangling pointer fails. |
| Ambiguity | No pointer plus multiple candidates returns conflict and IDs; no mutation or provider call. |
| Older database | Additive context table creation; no inferred timestamp pointer; exact-one fallback works; historical lifecycle remains readable. |
| Current Plan resolution | Only exact current pending stage artifact resolves; zero/multiple/stale/decided fail. |
| Approval safety | Hash, revision, stage, workflow ownership, Feature Contract UUID/SHA/READY binding all revalidate; no implementation starts. |
| Rejection safety | Same guards as approval; non-empty reason; durable rejection; no redispatch. |
| Interactive approval | Enter/y/yes approves displayed Plan once; stale race conflicts. |
| Happy-path rejection | n/no plus reason rejects once and stops. |
| Ctrl+C | During agent call terminates child and records recoverable unknown/attention; during prompt leaves pending; exit 130. |
| EOF | Leaves approval pending, prints recovery instruction, never inserts approval. |
| Non-interactive | `--non-interactive`, JSON, CI, piped stdin, or redirected stdout never reads input and stops awaiting approval. |
| Clarification | Persisted questions display; no Plan/provider successor; no invented answer; current status resolves. |
| V1 compatibility | Existing feature-file, explicit status/resume/approve/reject/logs/intervene and task-loop tests remain unchanged; optional inference uses lifecycle-specific guards. |
| Baseline regression | Run `.venv/bin/python3 -m unittest discover -s tests -q`; all existing 144 tests plus new coverage pass. |

Tests should inspect semantic render output after ANSI stripping rather than brittle full-screen snapshots. Use a small number of golden assertions only for deterministic Markdown and stable JSON structures.

## 16. Manual smoke tests

### 16.1 Primary interactive happy path

From a clean initialized disposable repository/worktree:

```bash
.venv/bin/engineering-flow run \
  "Add a version command to the engineering-flow CLI that prints the installed package version and add automated coverage."
```

Expected conceptual terminal:

```text
Engineering Flow

-> INTAKE
   Agent running ...
✓ Requirements ready · <elapsed>

-> PLAN
   Agent running ...
✓ Plan generated · <elapsed>

Plan
  Revision   1
  Tasks      <n>
  Approval   PENDING

Tasks
  T1  ...
      low complexity · medium risk

Plan
  .engineering-flow/workflows/<id>/artifacts/002-plan.md

? Approve this plan? [Y/n]
> y

✓ Plan approved
No implementation has started.
```

Then:

```bash
.venv/bin/engineering-flow status
.venv/bin/engineering-flow status --verbose
.venv/bin/engineering-flow status --json >status.json 2>status.err
```

Verify selected workflow resolution, `plan/plan_approved`, approved canonical JSON, valid Markdown projection, parseable JSON, empty JSON stderr, no task rows, no Developer/Reviewer execution, and no production-file changes.

### 16.2 Interactive rejection

Run another sufficient request, answer `n`, enter a reason, and verify `plan/rejected`, one rejection approval row, unchanged Plan JSON, and UUID-free status. Attempt explicit later approval and confirm conflict without event mutation.

### 16.3 Non-interactive/CI

```bash
.venv/bin/engineering-flow run --non-interactive "Add a version command..."
.venv/bin/engineering-flow status
.venv/bin/engineering-flow approve
```

Verify run stops at `awaiting_approval` without reading stdin and the later explicit intent safely resolves the exact current Plan. Repeat with `run --json` and redirected streams.

### 16.4 Ambiguity and advanced controls

Open an older/no-context database containing two workflows and run `status`; verify a conflict lists both candidates and requests `--workflow`. Then use explicit workflow/artifact IDs and prove the existing advanced path still works.

### 16.5 Projection recovery

Delete, then manually edit `002-plan.md`; human status must reconstruct canonical bytes each time. Confirm `002-plan.json` hash and approval identity never change. Make the projection directory unwritable and verify the Plan stays valid but interactive auto-prompt is suppressed.

### 16.6 Clarification and interruption

Run an intentionally ambiguous product request and confirm numbered questions, no Plan, and no stdin answer prompt. Interrupt a separate real Intake/Plan call with Ctrl+C; confirm exit 130, no false artifact/approval, recoverable human-attention/unknown evidence, and a usable UUID-free status.

### 16.7 V1 compatibility

Run a small `--feature-file` workflow with explicit identifiers through its existing approval/resume behavior. Confirm its lifecycle, artifact formats, task behavior, and logs are unchanged.

## 17. Acceptance criteria

MDS #2.1 is complete only when all are true:

1. `engineering-flow run "request"` is the preferred V2 entry point and existing request/feature-file forms remain valid.
2. A READY request advances through Intake and Plan in one invocation without manual resume.
3. Interactive eligible invocations show a verified concise Plan/Markdown view, prompt once, and persist approval or reasoned rejection on the exact canonical Plan.
4. Approval ends at `plan/plan_approved` with explicit confirmation that no implementation started.
5. Non-interactive, piped, redirected, CI, and JSON invocations never unexpectedly wait for stdin.
6. Default, verbose, and JSON output obey section 7 and never expose raw provider content or unsafe stderr.
7. Intake and Plan share provider-neutral, best-effort, stage-wide progress; TTY uses a replace-in-place line and non-TTY remains bounded/line-oriented.
8. `002-plan.md` is deterministic, complete, reconstructible, and never becomes canonical or approval-bound.
9. UUID-free workflow commands use an explicit persisted selected workflow context or exact-one fallback; all ambiguity fails closed.
10. UUID-free decisions resolve only a fully verified current pending artifact and preserve all MDS #2 approval/source-binding guarantees.
11. Ctrl+C, EOF, projection failure, provider failure, and process interruption create no accidental decision or false completion.
12. `NEEDS_CLARIFICATION` clearly presents persisted questions and stops without invented answers or hidden conversation state.
13. V1, older databases, explicit advanced commands, artifact tamper detection, and recovery semantics remain compatible.
14. No Task Contract is executed and no IMPLEMENT/VERIFY/REVIEW/FIX work occurs.
15. All existing 144 tests plus new tests pass, `git diff --check` passes, and the manual smoke tests succeed.

## 18. Out of scope

- IMPLEMENT or Task Contract execution;
- deterministic VERIFY implementation;
- REVIEW, FIX, or their loops;
- parallel scheduling, worktrees, commits, pushes, Pull Requests, or merge;
- multi-provider execution, full model routing, fallback, escalation, or optimization;
- execution budgets/circuit breakers except the coordinator's defensive transition cap;
- interactive clarification submission, Feature Contract revision, or answer artifacts (deferred to MDS #2.2);
- redesign/retirement of V1 lifecycle;
- completing or repurposing `CanonicalLifecycleOrchestrator`;
- raw token/tool/reasoning streaming, dashboards, curses/TUI, daemon, or external telemetry;
- changing Plan/Task Contract schemas or weakening read-only planning;
- making Markdown canonical, independently versioned, or independently approved.

MDS #3 remains the first implementation/execution milestone.

## 19. Risks and failure modes

- **CLI refactor changes machine output:** preserve existing JSON fields and exit codes, add fields only, and assert byte/structure behavior in focused tests.
- **Rich leaks ANSI to pipes:** create explicit consoles, rely on terminal detection, honor `NO_COLOR`/`--no-color`, and test every stream combination.
- **Live renderer corrupts prompts:** stop/finalize the live display before writing summaries or reading input; keep progress on stderr and results/prompts on controlled consoles.
- **Selected workflow context selects the wrong workflow:** persist the pointer on creation, never derive newest-by-time when it exists, never rewrite it during explicit historical access, and fail on missing/corrupt/ambiguous fallback.
- **Implicit artifact weakens approval:** keep resolution inside lifecycle-specific orchestration and call the same full validation immediately before the atomic decision.
- **Plan projection drifts:** render only from parsed canonical `Plan`, compare deterministic bytes, overwrite manual edits, and exclude it from artifact/approval tables.
- **Projection I/O blocks review:** keep JSON valid and recoverable, surface the error, suppress only automatic prompting, and retain explicit operator controls.
- **Progress reveals provider data:** accept only fixed event kinds and allow-listed messages; never forward `NormalizedEvent.payload`, stderr, prompts, tool output, or final prose.
- **Cancellation leaves Codex running:** explicitly terminate the owned process on `KeyboardInterrupt`, then persist unknown/human-attention before exiting 130.
- **Automatic loop dispatches too far:** use explicit state handlers, a defensive cap, and a hard MDS #2.1 stop at `PLAN_APPROVED`/`REJECTED`; assert no Developer/Reviewer requests or task rows.
- **Clarification scope creep:** stop after questions until immutable answer/revision lineage is separately designed.
- **Older database behavior changes:** additive table creation only; do not infer a pointer from `updated_at`; retain explicit UUID commands and historical lifecycle defaults.
- **Concurrent processes race between display and approval:** capture the displayed artifact identity but revalidate state/hash/source in the decision transaction path; a race yields conflict, not wrong approval.

## 20. Open decisions

There are no blocking design decisions for MDS #2.1. Plan approval itself authorizes these explicit choices:

1. adopt Rich only in the presentation boundary;
2. persist a repository selected-workflow pointer rather than derive recency;
3. keep `logs` and `intervene` explicitly workflow-addressed in this slice;
4. add `--non-interactive` and use conservative TTY/CI detection;
5. treat Markdown as a repairable derived cache;
6. defer clarification answer submission/revision to MDS #2.2.

If stakeholders require same-process clarification answers in MDS #2.1, that is a scope change requiring the Intake revision/source-lineage design before implementation; it must not be improvised in the CLI.

## 21. Expected final CLI experience

Daily use:

```text
$ engineering-flow run "Add a version command..."
-> INTAKE · Agent running
✓ Requirements ready · 18.2s
-> PLAN · Agent running
✓ Plan generated · 31.7s

Plan: 2 tasks · approval pending
  T1  Implement version command       low complexity · medium risk
  T2  Add automated coverage          low complexity · low risk · depends on T1

Review: .engineering-flow/workflows/<id>/artifacts/002-plan.md
? Approve this plan? [Y/n] y
✓ Plan approved
No implementation has started.

$ engineering-flow status
Workflow
  Stage      PLAN
  Status     PLAN_APPROVED
  Approval   APPROVED
```

Automation:

```text
$ engineering-flow run --json "Add a version command..."
{"command":"run",...,"stage":"plan","status":"awaiting_approval","next_action":"approve_or_reject"}
```

Advanced/recovery use remains explicit and auditable:

```text
engineering-flow status --workflow <uuid> --verbose
engineering-flow resume --workflow <uuid>
engineering-flow approve --workflow <uuid> --artifact <uuid>
engineering-flow reject --workflow <uuid> --artifact <uuid> --reason "..."
engineering-flow logs --workflow <uuid> --json
engineering-flow intervene --workflow <uuid> --task <uuid> --reason "..."
```

The visible interface becomes intent-oriented while the existing workflow UUIDs, artifact UUIDs, immutable JSON, SHA verification, source binding, revision checks, persistence, and recovery controls remain fully intact.

## Closure

Implemented:

- presentation modes and workflow-wide progress;
- deterministic, derived Plan Markdown projection;
- persisted selected-workflow context and current pending Plan resolution;
- one-command V2 Intake-to-Plan human decision boundary;
- recovery and compatibility hardening, including interrupted provider calls.

Validation:

- 166 unit tests pass.

Known follow-up:

- Repeated live smoke tests observed Planner output violating contiguous Task ID validation. Validation intentionally remains fail-closed. Planner structured-output/prompt reliability should be investigated separately before MDS #3.
