# Engineering Flow V2 — MDS #1 Intake and Feature Contract Implementation Plan

## 1. MDS objective and delivery boundary

Deliver one bounded, vertical V2 slice through the real `engineering-flow` entry point:

```text
inline request -> Intake agent -> validated Feature Contract -> persisted result
                                                        |-> READY
                                                        `-> NEEDS_CLARIFICATION + visible questions
```

The delivery mode is a single MDS implemented in three incremental vertical steps. A separate architecture overview is **NOT REQUIRED**: this slice keeps the repository's established CLI -> orchestrator -> provider-neutral runtime -> Codex adapter and SQLite persistence boundaries. This document supplies the MDS-specific decisions needed to implement within those boundaries.

The slice is complete only when a real initialized repository can run `engineering-flow run --request "..."`, Intake executes through `CodexCliRuntime`, the validated contract and state survive process exit, and the CLI reports either `READY` or `NEEDS_CLARIFICATION`. It does not continue to Plan.

## 2. Relevant current architecture and baseline

The current working tree is the implementation baseline; it includes in-progress canonical-lifecycle changes. Before implementation, run `./scripts/env-preflight`, preserve unrelated dirty changes, and inspect the current versions of the files named below.

- `src/engineering_flow/cli.py` defines `init`, `run`, `status`, approval, resume, intervention, and log commands. Today `run` requires both `--repo` and `--feature-file` and always enters the legacy planning lifecycle.
- `PlanningOrchestrator` in `src/engineering_flow/orchestrator.py` currently drives the V1 path `PRD -> TECHSPEC -> TASK_PLAN -> ...`. Its request-retention, runtime dispatch, failure handling, and event patterns are reusable. `CanonicalLifecycleOrchestrator` is an incomplete, more elaborate V1 Wave/release path and must not be extended for this MDS.
- `WorkflowStore` in `src/engineering_flow/store.py` owns repository-local `.engineering-flow/workflows.sqlite3`, `BEGIN IMMEDIATE` transactions, workflows, sessions, executions, idempotent operations, immutable hash-bound artifacts, and monotonic events. It also retains feature input bytes under `.engineering-flow/workflows/<workflow-id>/input/`.
- `AgentRuntime`/`RuntimeExecutionRequest` in `src/engineering_flow/runtime.py` provide the provider-neutral execution boundary. `CodexCliRuntime` in `src/engineering_flow/codex_cli.py` invokes Codex without a shell, uses a read-only sandbox for non-developer roles, writes a JSON output schema, normalizes events, applies timeouts, and returns structured results.
- `Stage`, `WorkflowStatus`, `Role`, `LifecycleVersion`, `Workflow`, `Artifact`, operation/execution values, and failures live in `src/engineering_flow/domain.py`.
- `status` already verifies artifact hashes before projecting them. `logs` projects persisted events. These projections should be extended, not replaced.
- The only tracked validation command is `.venv/bin/python3 -m unittest discover -s tests -q`. At planning time it passes all 120 tests. There is no separate tracked lint, formatting, typing, or build command.

The conceptual `.ai/*.json` layout in `docs/engineering-flow-v2.md` is not a mandate to add another store. SQLite remains authoritative, with the Feature Contract also retained as an immutable JSON artifact in the existing workflow artifact directory.

## 3. CLI interface decision

`run` gets two explicit, mutually exclusive input modes:

- `--request TEXT` selects the V2 lifecycle and is the canonical input for all new V2 workflows in this MDS.
- `--feature-file PATH` continues to select the existing V1 `PlanningOrchestrator` behavior for backward compatibility.

The parser must reject both options together and reject a run with neither. Selection is based only on the option name; it must not infer a lifecycle from content, a file extension, existing database state, or configuration. This removes V1/V2 ambiguity.

For `run`, make `--repo` optional with a default of the current directory so the required interface works literally from an initialized Git worktree:

```bash
engineering-flow run --request "Allow users to cancel an order before shipment."
```

An explicit `--repo PATH` remains supported in both modes, and all non-`run` commands retain their current repository argument behavior. The inline value must be non-empty after whitespace validation. Engineering Flow itself retains the raw UTF-8 request under the workflow workspace; the user never creates an input file.

`run --request` dispatches to a small V2 Intake orchestration path. `run --feature-file` continues to dispatch to `PlanningOrchestrator` unchanged. `status` chooses its projection from the workflow's persisted lifecycle version, never from CLI flags.

Both normal Intake decisions are successful command executions (exit code 0): `NEEDS_CLARIFICATION` is an expected product outcome, not a provider failure. Existing provider, authentication, persistence, unknown-operation, and invalid-result failures keep the established failure/exit handling.

Human-readable `run` and `status` output for V2 must include:

```text
Intake: READY
```

or:

```text
Intake: NEEDS_CLARIFICATION

Open questions:
- <question>
```

The existing workflow ID should also remain visible so `status` and `logs` can be used after the initial process exits. The JSON status projection should add a stable `lifecycle_version` and an `intake` object containing `outcome`, `feature_contract_artifact_id`, and `open_questions`; existing V1 fields remain intact.

## 4. Minimal Feature Contract design

Persist exactly one JSON Feature Contract artifact at:

```text
.engineering-flow/workflows/<workflow-id>/artifacts/001-feature-contract.json
```

Its exact top-level shape is:

```json
{
  "outcome": "READY",
  "feature": {
    "id": "<workflow UUID>",
    "goal": "Allow users to cancel an order before shipment.",
    "requirements": ["..."],
    "acceptance_criteria": ["..."],
    "constraints": ["..."],
    "out_of_scope": [],
    "assumptions": [],
    "open_questions": []
  }
}
```

`outcome` is the Intake result envelope, not a speculative Feature Contract field. No schema-version, plan, task, model-routing, approval, or future-stage fields are added in this slice. `feature.id` is the workflow UUID: there is no upstream ticket identifier in this input mode, this gives stable identity without another table or identifier generator, and validation must reject a provider payload whose ID differs from the workflow ID.

Add provider-neutral `IntakeOutcome` and immutable `FeatureContract` domain values plus a deterministic parser/validator using the standard library. `CodexCliRuntime` must use a dedicated Intake JSON Schema whenever `Role.INTAKE` is requested; `additionalProperties` is false at both levels and all fields above are required. The domain validator remains the authority after provider-schema validation and enforces:

- every scalar is the expected type and every list contains only non-empty strings;
- `id` and `goal` are non-empty and `id` equals the workflow ID;
- `READY` requires at least one requirement and acceptance criterion and requires no open questions;
- `NEEDS_CLARIFICATION` requires at least one explicit open question; requirements and acceptance criteria may remain partial;
- `REJECTED` is accepted as an Intake outcome with an otherwise structurally valid contract, but this MDS adds no elaborate rejection policy or demonstration flow.

Do not use keyword heuristics such as searching for `PENDING` or `SHIPPED`. Semantic classification belongs to Intake. Deterministic code validates the returned contract and outcome consistency; it does not decide product behavior.

The Intake instruction must tell the read-only agent to inspect the repository when an answer is reasonably discoverable, record safe engineering assumptions when useful, and emit open questions instead of inventing a material product/business decision. It must also prohibit implementation, planning, file mutation, and progression beyond Intake. The supplied workflow ID must be used as `feature.id`.

## 5. Intake outcome and state design

Add `Stage.INTAKE`, `Role.INTAKE`, `IntakeOutcome.READY`, `IntakeOutcome.NEEDS_CLARIFICATION`, and `IntakeOutcome.REJECTED`. Add `WorkflowStatus.READY` and `WorkflowStatus.NEEDS_CLARIFICATION`; reuse the existing `WorkflowStatus.REJECTED`.

Add `LifecycleVersion.V2` and a `lifecycle_version` column/property on the primary workflow record. Existing databases gain the column through the store's current additive schema-upgrade pattern with a non-null legacy default. Existing `create_workflow` callers keep their current legacy/historical default; only `--request` creation explicitly records V2 and starts at `Stage.INTAKE`. Do not represent V2 by adding Intake to `CanonicalStage`, do not write V2 state into the Wave/release-oriented `lifecycle_states` table, and do not route through `CanonicalLifecycleOrchestrator`.

The workflow row is the current V2 state projection. The immutable Feature Contract artifact is the detailed result. The current operation, execution, session, and event tables remain the audit trail. This is sufficient for MDS #1; no new `feature_contracts` or `intake_results` table is needed.

On successful structured output, the store must commit these facts together using the existing generation-completion transaction pattern:

- hash-bound `001-feature-contract.json` artifact linked to the Intake execution;
- completed execution with sanitized structured terminal result;
- completed idempotent generation operation;
- workflow `stage=intake`, `status=ready|needs_clarification|rejected`, and `lifecycle_version=v2`;
- existing completion/artifact events plus an explicit `intake.completed` event containing the outcome and question count, not duplicate full contract prose.

Because a Feature Contract is not approval-gated, add an `ApprovalState.NOT_REQUIRED` value and let the existing generation completion API accept an approval-state argument whose default remains `PENDING` for V1. Intake passes `NOT_REQUIRED`. This is preferable to falsely presenting the artifact as awaiting approval.

The existing request hash/idempotency key must cover the raw-request hash, Intake instruction, stage, and expected output contract. A retry of the same persisted operation must not dispatch a second provider call or create a second revision. Unknown provider outcomes continue to stop for human attention rather than being replayed blindly. Clarification submission and resumption are later slices; MDS #1 only persists and displays the questions.

## 6. REUSE / ADAPT / ADD decisions

| Decision | Classification | Rationale |
|---|---|---|
| CLI command shell, configuration loading, result documents, exit classification | ADAPT | Add explicit `--request` routing and V2 rendering while retaining the existing commands and error model. |
| Raw request retention and hashing | REUSE | Existing workflow input storage already preserves bytes and digest under the product workspace. |
| SQLite database, transactions, operation/execution/session/event records | REUSE | They already provide the authoritative persistence and audit foundation required by V2. |
| Workflow row and additive schema evolution | ADAPT | Record lifecycle version and the new Intake stage/status without inventing a second state store. |
| Artifact table, hash verification, generation intent/completion | ADAPT | Permit a JSON Feature Contract label and `NOT_REQUIRED` approval state; otherwise preserve immutability and linking. |
| Provider-neutral runtime request/result and Codex process controls | ADAPT | Add the Intake role/schema and use the existing read-only execution path. |
| Feature Contract value, Intake outcome, deterministic validation | ADD | V1 has no equivalent structured product contract or outcome semantics. |
| Small V2 Intake orchestrator in `orchestrator.py` | ADD | Keeps Intake out of the V1 stage sequence while reusing the same store/runtime ports. |
| `PlanningOrchestrator` V1 path | REUSE | Preserve it behind `--feature-file`; do not extend it with later V2 stages. |
| `CanonicalLifecycleOrchestrator` and Wave/release governance | REUSE only for historical readability | No MDS changes or routing through this incomplete lifecycle. |

## 7. Exact implementation sequence

### Step 1 — Make a sufficient inline request reach persisted READY

1. **Objective:** establish the explicit V2 boundary and deliver the first complete CLI path for a sufficient request.
2. **Observable outcome:** from an initialized repository, the required READY command invokes the fake runtime in automated coverage (and the real Codex runtime manually), writes a valid JSON Feature Contract, exits 0, and prints `Intake: READY` plus a workflow ID. A subsequent `status` reads the same persisted result.
3. **Why necessary:** this is the earliest useful checkpoint and proves integration before clarification behavior is layered on.
4. **Classification:** **ADAPT** existing vertical infrastructure; **ADD** only the V2 contract and Intake coordinator.
5. **Existing components involved:** parser/result renderer, `WorkflowStore`, workflow/artifact/operation/execution/events, `AgentRuntime`, `CodexCliRuntime`, and failure sanitization.
6. **Expected files/modules affected:**
   - `src/engineering_flow/domain.py`: V2 lifecycle/stage/status/role, outcome, contract value and validator, `NOT_REQUIRED` artifact state.
   - `src/engineering_flow/runtime.py`: allow the provider-neutral Intake request/result.
   - `src/engineering_flow/codex_cli.py`: Intake output schema selection and payload validation through the read-only path.
   - `src/engineering_flow/store.py`: additive workflow lifecycle column, V2 workflow creation, JSON artifact label, approval-state parameter, and atomic Intake transition/event.
   - `src/engineering_flow/orchestrator.py`: a focused `IntakeOrchestrator` that retains input, creates one generation intent, dispatches one read-only Intake request, validates the result, and persists READY without entering Plan.
   - `src/engineering_flow/cli.py`: mutually exclusive inputs, current-directory default for `run`, explicit routing, and Intake projection/rendering.
   - focused tests in `tests/test_domain.py`, `tests/test_runtime.py`, `tests/test_codex_cli.py`, `tests/test_store.py`, `tests/test_orchestrator.py`, and `tests/test_cli.py`.
7. **Persistence/state changes:** add/backfill the workflow lifecycle column; create V2 at `intake/created`, retain inline request and digest, persist execution/operation/events, then atomically store the contract artifact and set `intake/ready`. Existing V1 creation defaults and rows remain readable.
8. **Automated tests:** validate READY contract invariants; assert the Intake schema is selected and malformed output is rejected before success; assert artifact bytes/hash/linkage, lifecycle version, state, events, and idempotent completion; run the CLI with a fake runtime using the exact `--request` interface and verify both immediate text and reopened `status --json` state. Assert no PRD artifact or later-stage execution exists.
9. **Manual validation:** run the READY command in section 10 and then query its workflow with `status`.
10. **Acceptance criteria:** exact inline command works without a user-created feature file; one Intake call occurs read-only; one valid contract is persisted; workflow is V2/INTAKE/READY; output is visible; process exit is 0; no Plan work occurs.

Commit this independently before extending behavior, following `implement -> run -> observe -> validate -> commit -> extend`.

### Step 2 — Surface business ambiguity as persisted NEEDS_CLARIFICATION

1. **Objective:** apply all three Intake decision rules and expose unresolved product/business questions instead of invented behavior.
2. **Observable outcome:** the ambiguous cancellation request exits 0, prints `Intake: NEEDS_CLARIFICATION`, and lists at least one question about the allowed order states. Reopened status returns the same questions from the persisted contract.
3. **Why necessary:** READY alone does not prove the key safety boundary of Intake.
4. **Classification:** **ADAPT** the Step 1 Intake prompt, validator, terminal mapping, and CLI projection.
5. **Existing components involved:** `IntakeOrchestrator`, Intake JSON schema/domain validation, artifact reader/hash verification, `_workflow_payload`, `_print_result`, and existing event projection.
6. **Expected files/modules affected:** `src/engineering_flow/orchestrator.py`, `src/engineering_flow/cli.py`, and only the domain/runtime/store files from Step 1 if cross-field validation or terminal mapping needs completion; corresponding focused test files.
7. **Persistence/state changes:** the same single Feature Contract artifact is stored with non-empty `open_questions`; workflow ends at `intake/needs_clarification`; `intake.completed` records outcome and question count. No placeholder answer, Plan state, approval, or follow-on operation is created.
8. **Automated tests:** use a fake structured Intake result to assert NEEDS_CLARIFICATION requires questions, READY rejects questions, malformed/missing/additional fields fail safely, and the CLI displays persisted questions. Inspect the dispatched instruction to verify all three rules: inspect repository-resolvable facts, permit safe engineering assumptions, and ask about material product decisions. Include the supplied ambiguous example without asserting one brittle exact sentence.
9. **Manual validation:** run the NEEDS_CLARIFICATION command in section 10, then confirm the questions through `status` after the original process exits.
10. **Acceptance criteria:** at least one explicit business question is persisted and shown; no expected behavior is invented; the workflow remains stopped at Intake; no later stage or approval is created. `REJECTED` is accepted by the contract/state mapping but receives no elaborate policy or required CLI scenario.

Commit this independently before compatibility hardening.

### Step 3 — Prove V1 coexistence and close MDS acceptance

1. **Objective:** verify the lifecycle boundary, recovery projections, and repository-wide regression safety, then perform both real CLI demonstrations.
2. **Observable outcome:** `--feature-file` still begins the legacy PRD path; `--request` always begins V2 Intake; both V2 examples are reproducible with the actual installed CLI and persisted state.
3. **Why necessary:** the MDS must not silently reinterpret historical workflows or break current users while introducing the new default input mechanism.
4. **Classification:** **REUSE** V1 behavior and full validation; **ADAPT** only compatibility/projection defects found by the demonstrations.
5. **Existing components involved:** CLI parser/routing, workflow lifecycle version, status/log readers, schema upgrade path, artifact corruption detection, and the existing V1 orchestration tests.
6. **Expected files/modules affected:** normally tests only among `tests/test_cli.py`, `tests/test_store.py`, and existing V1 regression suites; production files listed in Steps 1–2 only if a demonstrated defect requires a minimal correction. No new subsystem.
7. **Persistence/state changes:** none beyond Steps 1–2. Test opening an older database through the additive schema upgrade and confirm its legacy default; never infer or backfill V2 facts for old workflows.
8. **Automated tests:** reject both/neither input flags; preserve explicit `--repo`; verify legacy `--feature-file` still reaches PRD and retains current approval semantics; verify V2 status/log projections after store reopen and artifact tamper detection; run `.venv/bin/python3 -m unittest discover -s tests -q` and require the entire suite to pass.
9. **Manual validation:** perform both section 10 scenarios with the real `CodexCliRuntime`, not a unit-test fake. Inspect `status` and optionally `logs` using the emitted workflow IDs.
10. **Acceptance criteria:** all old and new tests pass; the two input modes are unambiguous; old database rows remain readable; READY and NEEDS_CLARIFICATION work end to end through the real CLI; the change set contains no later V2 stage.

## 8. Automated testing strategy

Tests should follow existing `unittest`, temporary-directory, fake-runtime, and direct-store conventions. Do not add pytest, a JSON Schema package, linting, typing, or other tooling.

Required coverage by layer:

- **Domain:** exact fields and types, workflow-ID binding, READY/non-empty requirements and criteria, READY/no questions, NEEDS_CLARIFICATION/non-empty questions, and all three outcome values.
- **Runtime adapter:** Intake selects its dedicated strict schema, stays read-only, accepts a valid structured payload, rejects malformed JSON/extra fields/wrong nested types, and preserves sanitized normalized evidence.
- **Store:** additive lifecycle-version upgrade, V1 default compatibility, V2 creation at Intake, raw request hash, JSON artifact hash/readback, `NOT_REQUIRED`, atomic terminal status/event, and same-key idempotency.
- **Orchestrator:** sufficient fake result -> READY; ambiguous fake result -> NEEDS_CLARIFICATION; invalid provider result -> existing safe failure path; unknown outcome is not replayed; no later call is dispatched.
- **CLI:** exact quoted `--request` examples, omitted `--repo` resolving to the current initialized worktree, explicit `--repo`, both/neither input errors, visible questions, reopened JSON status, and unchanged `--feature-file` V1 routing.

Agent semantic quality is demonstrated manually; automated tests must inject valid/invalid structured results and test Engineering Flow's deterministic handling rather than depend on live model wording.

## 9. Manual CLI demonstration

Prerequisites: Python 3.13 repository-local environment, authenticated/configured Codex CLI, and an initialized Git worktree. In the target worktree, initialize Engineering Flow once if needed:

```bash
engineering-flow init --repo "$PWD"
```

### READY

```bash
engineering-flow run --request "Allow users to cancel an order before shipment. Only PENDING orders may be cancelled. SHIPPED orders cannot be cancelled."
```

Require exit code 0 and observable output containing:

```text
Intake: READY
```

Capture the printed workflow ID and run:

```bash
engineering-flow status --repo "$PWD" --workflow "<workflow-id>" --json
```

Confirm `lifecycle_version` is `v2`, stage is `intake`, Intake outcome is `READY`, `open_questions` is empty, exactly one Feature Contract artifact exists, and no PRD/Plan/later-stage artifact or execution exists.

### NEEDS_CLARIFICATION

```bash
engineering-flow run --request "Allow users to cancel orders."
```

Require exit code 0 and observable output containing:

```text
Intake: NEEDS_CLARIFICATION
```

The output must include one or more open questions; wording may vary, but at least one must ask for a product/business decision that determines when cancellation is allowed. Use the printed workflow ID with the same `status --json` command and confirm the question survives process exit, the artifact hash verifies, and no Plan or later-stage work exists.

If the model returns an unexpected semantic result, retain the workflow ID, `status`, and `logs` evidence and treat the demonstration as failed; do not weaken deterministic validation or substitute a direct schema/unit invocation.

## 10. Final MDS acceptance criteria

MDS #1 is accepted only when all are true:

1. Real `engineering-flow run --request TEXT` works from the current initialized repository without `--repo` and without a user-created feature file.
2. The V2 route executes Intake through the real provider-neutral runtime/Codex adapter in a read-only sandbox.
3. Intake returns the exact minimal structured Feature Contract shape and deterministic validation accepts only internally consistent outcomes.
4. SQLite authoritatively persists lifecycle version, workflow state, operation, execution, events, raw-request hash, and the hash-bound JSON artifact.
5. The sufficient cancellation request reaches and visibly reports READY.
6. The ambiguous cancellation request reaches and visibly reports NEEDS_CLARIFICATION.
7. One or more persisted open questions are visible immediately and through a later `status` call.
8. REJECTED exists in domain/schema/state mapping without an expanded rejection subsystem.
9. Existing V1 `--feature-file` workflows and historical persisted rows remain readable and retain their behavior.
10. New domain, adapter, store, orchestrator, and CLI behavior has automated coverage and the full existing suite remains green.
11. Manual demonstrations use the real CLI and runtime, not internal service calls.
12. No Plan, task, implementation, verification, review, fix, routing, escalation, parallelism, worktree, bootstrap, PR, or advanced MCP behavior is added.

## 11. Explicitly out of scope

Do not implement or design forward infrastructure for Plan generation, Task Contract, Plan approval, implementation agents, deterministic Verify, Review, Fix, Model Router, model escalation, autonomous or parallel task execution, Git worktrees, greenfield bootstrap, PR automation, advanced MCP input, external ticket systems, clarification submission/resume, full V1 retirement, or the canonical Wave/release lifecycle. Do not finish `CanonicalLifecycleOrchestrator`.

Also excluded are stdin/interactive pre-Intake input and JSON/YAML/Markdown feature files for new V2 workflows. The internally retained request and generated Feature Contract artifact do not change the user input contract.

## 12. Risks and compatibility concerns

- **Lifecycle ambiguity:** mitigated by mutually exclusive CLI flags and a persisted V2 lifecycle version. Never infer version from stage names or artifacts.
- **Dirty in-progress V1 work:** implementation must preserve user-owned changes and avoid coupling Intake to the incomplete canonical orchestrator.
- **Schema evolution:** use the existing additive SQLite upgrade pattern and a legacy default so older databases open without fabricated V2 state.
- **Agent nondeterminism:** strict JSON Schema plus domain cross-field validation prevents malformed or contradictory results from becoming READY. Semantic quality still needs the real CLI demonstration.
- **Artifact approval semantics:** use `NOT_REQUIRED`; do not overload `PENDING` or create a fake approval.
- **Idempotency/recovery:** reuse generation identities and unknown-outcome handling. Do not automatically replay an uncertain provider call.
- **Atomic files:** the current store writes artifact files inside the database completion flow but does not provide crash-safe temporary-file replacement. Preserve current behavior for this MDS and record full atomic file hardening as later reliability work; do not expand this slice solely to redesign artifact IO.
- **CLI output compatibility:** keep existing machine fields and legacy rendering; add the V2 Intake projection only when `lifecycle_version=v2`.
- **Repository exploration:** Intake may read the target repository and instructions but must remain read-only and must not treat implementation details as product decisions.

## 13. Expected final observable behavior

After implementation, an inline sufficient request creates one V2 workflow, one retained raw request, one Intake execution, and one validated Feature Contract, then stops with `Intake: READY`. An inline request missing a material cancellation-state rule creates the same durable evidence, preserves at least one explicit question, and stops with `Intake: NEEDS_CLARIFICATION`. Both results can be reconstructed through `status` and `logs`; neither path generates a PRD, Plan, tasks, code changes, or later-stage execution. Legacy file-based runs continue to use the existing V1 lifecycle.
