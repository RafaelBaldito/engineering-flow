# Engineering Flow V2 — MDS #2.2 Human Feedback Loops Implementation Plan

## 1. Objective

MDS #2.2 closes the two human-feedback gaps left after MDS #2.1:

1. Intake asks and persists one necessary clarification at a time, re-evaluating the Feature Contract after every answer until it is `READY`.
2. A human can request changes to a Plan without terminating the workflow; feedback is persisted and produces a new immutable Plan revision that must be approved explicitly.

The target contract is:

> `PLAN_APPROVED` means the requirements were clarified as necessary, the Planner proposed an implementation, the human had an opportunity to request changes, and the human approved this exact Plan revision.

This is a planning-only milestone. It does not execute a Task Contract, create V2 task rows, invoke Developer/Reviewer work, or begin MDS #3.

## 2. Current behavior

The verified committed baseline has 166 passing tests and a clean worktree. V2 currently provides:

- one immutable raw request at `input/request.txt`;
- one Intake generation at revision 1 and `001-feature-contract.json`;
- `READY`, `NEEDS_CLARIFICATION`, and `REJECTED` Intake outcomes;
- automatic `READY -> PLAN` progression in the `run --request` happy path;
- one strict canonical Plan at revision 1 and `002-plan.json`;
- one derived `002-plan.md` projection;
- exact Plan approval or terminal rejection;
- selected-workflow recovery, progress, concise/verbose/JSON rendering, and explicit operator commands.

Current `NEEDS_CLARIFICATION` output displays every `open_questions` item and exits. There is no persisted answer or Intake continuation. Current interactive `n` at the Plan prompt asks for a rejection reason and records terminal `plan/rejected`.

SQLite is authoritative. The existing `artifacts` table already supports `UNIQUE(workflow_id, stage, revision)`, immutable UUID/SHA identity, and multiple revisions in principle. `operations` records a generation intent revision and destination. Two implementation assumptions prevent safe V2 revision loops today:

- Intake and Plan orchestration use fixed revision-1 paths;
- `workflows.current_artifact_revision` is global across stages, while V2 guards assume it identifies the current Plan.

The repository-local database inspected at planning time matches `store.py`: no clarification or Plan-feedback table exists, and persisted V2 examples use revision-1 `001-feature-contract.json` and `002-plan.json` artifacts.

## 3. Problems discovered through real CLI testing

### 3.1 Intake stops instead of clarifying

For an ambiguous request, Intake may return several candidate questions. Displaying that original list and stopping makes the user restart from the raw request and treats stale questions as a queue. It cannot account for one answer resolving several questions, invalidating another, or exposing a new product decision.

### 3.2 Terminal output is not durable input

Questions and answers cannot be reconstructed from stdout, stdin history, or provider conversation state. A terminal close after an answer currently loses the answer and forces a new workflow.

### 3.3 Plan `No` has the wrong meaning

The normal approval prompt maps `No` directly to an `approvals` row with decision `REJECTED`, changes the Plan artifact to rejected, and terminates the workflow. It cannot distinguish “revise this proposal” from “cancel this feature.”

### 3.4 Revision primitives exist but current-selection rules do not

Artifact revision uniqueness, generation intents, UUIDs, hashes, and strict parsing can support revisions. Fixed filenames, exact-one Intake lookup, latest-Plan projection assumptions, and the global `current_artifact_revision` projection cannot.

### 3.5 Failure after human input is not recoverable as a loop

If feedback were stored and a replacement generation then failed, current V2 `resume()` would return immediately for every workflow already at `Stage.PLAN`. There is no durable record proving which Plan was targeted or whether a replacement was completed.

## 4. Design principles

1. **Persist human intent before provider work.** The question is durable before prompting; the answer or Plan feedback is committed before re-evaluation/replanning begins.
2. **One question, then re-evaluate.** Persist only the first question from the current validated `NEEDS_CLARIFICATION` contract as the active question. Never enqueue the remainder.
3. **Workflow state, not conversation history.** Store clarification and change-request records explicitly. Provider threads and terminal text are not authority.
4. **Immutable canonical revisions.** Every successful Intake or Plan revision gets a new artifact UUID, SHA, revision, and path. Existing canonical bytes are never overwritten.
5. **Stage-local current authority.** For V2, current Feature Contract and current Plan are resolved from the highest successfully persisted revision for that stage plus lifecycle/feedback guards. The legacy global revision column remains for compatibility but is not V2 decision authority.
6. **Same strict validation.** Revised Feature Contracts and Plans use their existing domain schemas and validators. No task-ID, dependency, path, complexity, risk, identity, or source-binding rule is weakened.
7. **Distinct change and cancellation semantics.** A change request is not an approval rejection. Explicit `reject` remains the terminal advanced action.
8. **Thin interaction layer.** CLI prompts call application/orchestration methods. They do not write tables, choose revisions, construct provider context, or infer recovery policy.
9. **Machine-safe modes.** JSON never prompts and emits exactly one document. Non-TTY input is never read implicitly.
10. **Bounded calls.** One command may cross several human/provider boundaries, but hard per-invocation provider-call limits prevent accidental infinite loops.
11. **V2 only.** Historical/V1 behavior, artifact formats, and lifecycle routing are unchanged.

## 5. Intake clarification lifecycle

The V2 Intake lifecycle becomes:

```text
raw request + answered clarification records + latest Feature Contract
                              |
                              v
                            INTAKE
                              |
             +----------------+----------------+
             |                                 |
   NEEDS_CLARIFICATION                       READY
             |                                 |
  persist first current question              PLAN
             |
       ask exactly once
             |
     persist human answer
             |
       re-run INTAKE
```

Detailed rules:

1. Initial Intake still reads the immutable raw request.
2. A validated `NEEDS_CLARIFICATION` Feature Contract is persisted as an immutable Intake artifact.
3. In the same completion transaction, persist only `open_questions[0]` as the active clarification. The other questions remain evidence inside that Feature Contract but are not scheduled for prompting.
4. Interactive presentation asks that exact persisted question.
5. A non-empty answer is stored transactionally before any provider call.
6. Re-evaluation receives the raw request, latest Feature Contract, and ordered answered clarification records. The request hash covers their stable IDs/content and source artifact UUID/SHA values.
7. The next validated Feature Contract is a new Intake artifact. Completion links the answered clarification to that result artifact.
8. If it is still `NEEDS_CLARIFICATION`, its first question becomes the next active clarification in the same transaction. It may differ from every question in the prior artifact.
9. Only a latest valid `READY` Feature Contract with no open questions can enter Plan.

The `FeatureContract` JSON shape does not need a conversational field. Artifact revision/UUID/SHA plus the clarification lineage table establish revision identity and provenance. `feature.id` remains the workflow UUID.

For a minimal explicit non-conversational adapter, add mutually exclusive `resume --answer TEXT` and later `resume --feedback TEXT` inputs. `resume --answer` is valid only when the selected/explicit V2 workflow has exactly one unanswered active clarification. It stores one answer and advances until the next durable boundary. This also provides a future automation seam without making `--json` prompt-driven.

## 6. Clarification persistence model

Add one workflow-specific table; do not add a generic messages/chat table:

```text
clarifications
  id                                  TEXT PRIMARY KEY
  workflow_id                         TEXT NOT NULL REFERENCES workflows(id)
  sequence                            INTEGER NOT NULL CHECK(sequence > 0)
  source_feature_contract_artifact_id TEXT NOT NULL REFERENCES artifacts(id)
  question                            TEXT NOT NULL
  answer                              TEXT NULL
  actor                               TEXT NULL
  result_feature_contract_artifact_id TEXT NULL REFERENCES artifacts(id)
  created_at                          TEXT NOT NULL
  answered_at                         TEXT NULL
  completed_at                        TEXT NULL

  UNIQUE(workflow_id, sequence)
  UNIQUE(source_feature_contract_artifact_id)
  UNIQUE(result_feature_contract_artifact_id)
```

Invariants enforced by narrow store methods:

- source/result artifacts belong to the same workflow and `Stage.INTAKE`;
- `question` and submitted `answer` are non-empty after whitespace checking;
- exactly one clarification can originate from one Feature Contract revision;
- at most one clarification per workflow is unanswered or answered-but-not-completed;
- an answer changes only `NULL -> value`; identical replay is idempotent and a different replay conflicts;
- `result_feature_contract_artifact_id` changes only `NULL -> newly committed artifact`;
- sequence is allocated monotonically within the workflow transaction;
- sensitive/provider diagnostic material is never stored in these fields.

Add immutable provider-neutral `Clarification` domain/projection values. Store APIs should be narrow, such as `get_active_clarification()`, `list_clarifications()`, and `answer_clarification()`. Intake completion needs a domain-specific transactional path that may both link the answered record and create the next question; do not add a general transaction callback framework.

JSON/status projects the ordered clarification records and a `current_clarification` summary. Human default output shows only the active question and recovery action; verbose output may include IDs, source/result artifact identity, actor, and timestamps.

## 7. Clarification recovery

Recovery is driven only by SQLite and immutable artifacts:

| Durable evidence | `resume` behavior |
| --- | --- |
| Active clarification has `answer IS NULL` | Interactive mode asks the same stored question; non-interactive/JSON reports it and stops. |
| Answer exists and `result_feature_contract_artifact_id IS NULL` | Re-run Intake using the persisted answer; do not prompt for it again. |
| Result artifact exists and contains `NEEDS_CLARIFICATION` | Use the next clarification created with that artifact; never revive old unasked questions. |
| Latest result is `READY` | Enter Plan through the existing coordinator path. |
| Known failed/invalid re-evaluation with an answered incomplete record | Preserve `intake/failed`; `resume` starts a new bounded generation attempt from the same persisted context. |
| Interrupted/unknown read-only re-evaluation with no result artifact | Mark the old operation unknown, retain `human_attention` evidence, and allow an explicit `resume` to start a new attempt from the same persisted context. |

Generation-attempt revisions may have gaps because `next_generation_revision()` already reserves revisions across failed intents. Gaps are valid; uniqueness and monotonicity matter, not contiguous artifact numbers.

No duplicate workflow is created on `resume`. The original request path/hash is unchanged. Answer submission is idempotent. A process loss after answer commit but before dispatch is therefore indistinguishable from an intentional pause and resumes safely.

## 8. Plan revision lifecycle

The Plan lifecycle becomes:

```text
Plan rN / AWAITING_APPROVAL
            |
       +----+----+
       |         |
    approve      request changes
       |         |
PLAN_APPROVED    persist feedback + mark rN CHANGES_REQUESTED
                 |
                 v
              REPLAN
                 |
       valid Plan rN+1 / AWAITING_APPROVAL
```

Add `WorkflowStatus.CHANGES_REQUESTED` and `ApprovalState.CHANGES_REQUESTED`. Do not add an `ApprovalDecision` for change requests: the `approvals` table remains terminal approval/rejection evidence.

Transitions:

| From | Trigger | Durable result |
| --- | --- | --- |
| `plan/awaiting_approval`, current Plan `PENDING` | approve exact Plan | Existing exact approval path -> `plan/plan_approved`. |
| `plan/awaiting_approval`, current Plan `PENDING` | request changes | Insert change request, set target Plan `CHANGES_REQUESTED`, set workflow `plan/changes_requested`; no approval row. |
| `plan/changes_requested` with open feedback | replan | `plan/running`, then new valid Plan `PENDING` and `plan/awaiting_approval`. |
| open feedback + known generation/validation failure | failure | `plan/failed`; target Plan and feedback remain immutable/open; no replacement artifact. |
| open feedback + interrupted/unknown generation | interruption | existing unknown execution evidence plus `plan/human_attention`; feedback remains open and explicit `resume` may retry read-only generation. |
| `plan/awaiting_approval` | explicit `reject` | Existing terminal `plan/rejected`; no replan. |

The interactive approval prompt changes only its `No` branch: it asks for non-empty change feedback and invokes the request-changes service. It never invokes terminal `reject`. The explicit `engineering-flow reject ... --reason ...` command remains the deliberate terminal action at an approval boundary.

## 9. Plan feedback persistence model

Add one narrow table:

```text
plan_change_requests
  id                           TEXT PRIMARY KEY
  workflow_id                  TEXT NOT NULL REFERENCES workflows(id)
  sequence                     INTEGER NOT NULL CHECK(sequence > 0)
  target_plan_artifact_id      TEXT NOT NULL UNIQUE REFERENCES artifacts(id)
  feedback                     TEXT NOT NULL
  actor                        TEXT NOT NULL
  replacement_plan_artifact_id TEXT NULL UNIQUE REFERENCES artifacts(id)
  created_at                   TEXT NOT NULL
  completed_at                 TEXT NULL

  UNIQUE(workflow_id, sequence)
```

`request_plan_changes()` atomically:

1. revalidates the exact current pending Plan using the existing approval authority checks;
2. inserts the non-empty feedback record;
3. changes only the target artifact's approval state to `CHANGES_REQUESTED`;
4. changes the workflow to `plan/changes_requested`;
5. appends a sanitized `plan.changes_requested` event.

No `approvals` row is created. Duplicate identical submission for the same target is idempotent; different feedback for the same target conflicts. A workflow can have only one open change request because a second request requires a new pending Plan.

Successful revised-Plan completion atomically writes the new artifact row, sets `replacement_plan_artifact_id`, closes the change request, and returns the workflow to `awaiting_approval`. If provider execution or validation fails, the replacement field remains `NULL`, which is the authoritative recovery test.

The full exact feedback is provided to the Planner from this table, not from logs, Markdown, or terminal history. JSON/status exposes ordered change requests; default human output shows the current revision and whether a replacement is pending.

## 10. Plan revision artifact/identity model

Reuse the existing artifact table, UUIDs, hashes, execution linkage, `(workflow_id, stage, revision)` uniqueness, and embedded Plan identity:

```text
plan.id       = <workflow-id>:plan:r<N>
plan.revision = N
artifact.revision = N
```

Introduce one deterministic stage/revision path helper with legacy-compatible revision-1 names:

| Stage/revision | Canonical JSON | Derived Markdown |
| --- | --- | --- |
| Intake r1 | `001-feature-contract.json` | none |
| Intake r2+ | `001-feature-contract-rNNN.json` | none |
| Plan r1 | `002-plan.json` | `002-plan.md` |
| Plan r2+ | `002-plan-rNNN.json` | `002-plan-rNNN.md` |

For example, Plan revision 2 is `002-plan-r002.json`; it never overwrites `002-plan.json`. Zero padding gives deterministic lexical ordering, while SQLite revision remains authoritative.

Every revised Plan keeps the existing strict schema and binds to the exact latest `READY` Feature Contract artifact UUID/SHA. No feedback or Markdown field is added to canonical Plan JSON. Revision provenance is represented by the change-request target/replacement links and the generation execution/request hash.

The replanning runtime request contains only:

- exact latest `READY` Feature Contract path, UUID, and SHA;
- exact target canonical Plan path, UUID, SHA, and revision;
- exact persisted change-request ID and feedback;
- repository path/instructions and the existing read-only planning contract;
- expected new Plan ID/revision and the unchanged strict output contract.

The request hash includes all of those stable identities plus the output-contract version. It does not include progress callbacks or terminal presentation.

`Plan.parse()` applies the same identity, source binding, Task Contract, dependency, repository path, complexity, and risk rules for every revision. Invalid output completes the attempt as failed but creates no artifact and does not set the change request's replacement link.

The highest successfully persisted `Stage.PLAN` revision is the current Plan. V2 projection and decision code must stop comparing it to the cross-stage `workflows.current_artifact_revision`; retain that column unchanged for V1 compatibility. The latest Plan Markdown view is selected by exact Plan revision and always regenerated from that revision's verified JSON.

## 11. Approval/rejection semantics

Approval remains a decision on one immutable artifact UUID and verified bytes. Before recording it, orchestration must require:

- V2 `stage=plan` and `status=awaiting_approval`;
- supplied artifact belongs to the workflow and is `Stage.PLAN`;
- it is the highest successfully persisted Plan revision;
- it is `PENDING` and has no existing approval;
- embedded ID/revision equal its artifact revision;
- its Feature Contract binding resolves to the exact latest valid `READY` Intake artifact;
- all existing Plan/Task validation succeeds.

After feedback on r1, r1 is `CHANGES_REQUESTED` and cannot be approved. After r2 exists, latest-revision guards reject r1. If r3 exists, r2 is stale. Omitted `--artifact` resolves only the unique current pending Plan through these same checks.

Terminal `reject` remains explicit and reasoned. The interactive `No` path never calls it. In MDS #2.2, explicit rejection is supported at `awaiting_approval`; cancellation while a provider operation is actively running remains an operator interruption/recovery concern rather than a new cancellation subsystem.

## 12. Interactive vs non-interactive/JSON behavior

### Interactive human mode

- At an unanswered clarification: render `? <question>`, read one line, require non-empty text, persist it, then re-evaluate.
- If the next Intake revision still needs clarification: render only its newly persisted active question.
- At a pending Plan: render the verified current revision and ask `Approve this plan? [Y/n]`.
- `Enter/y/yes`: approve exact displayed revision.
- `n/no`: ask `What should be changed?`, require non-empty feedback, persist it, generate the replacement, render its new revision, and ask again.
- Invalid yes/no or empty answer/feedback may be reprompted locally without provider calls or persistence.

### Non-TTY or explicitly non-interactive mode

- Never read stdin implicitly.
- Stop successfully at an unanswered clarification or pending approval and print the exact recovery action.
- If an answer/feedback was already persisted before process loss, `resume` may perform the provider re-evaluation/replan and then stop at the next human boundary.
- `resume --answer TEXT` and `resume --feedback TEXT` submit exactly one explicit human input. They are mutually exclusive, boundary-checked, selected-workflow-aware, and compatible with `--json`.

### JSON mode

- Never prompts, renders progress, emits ANSI, or writes extra documents.
- Returns exactly one stable document containing current clarification history/active question, Plan revision metadata/change requests, and `next_action`.
- Explicit `--answer` or `--feedback` is an input parameter, not a conversational exchange; the command still returns one document.
- JSON observation (`status --json`) never repairs derived Markdown.

No latest-workflow scan is introduced. Omitted workflow IDs use the persisted `selected_workflow_id`; explicit selectors retain precedence and existing fail-closed behavior.

## 13. Progress behavior

Reuse `RuntimeProgressEvent`, the existing optional sink, and `ProgressRenderer` for every Intake re-evaluation and Plan revision. Each provider call emits the same fixed stage lifecycle:

```text
✓ INTAKE completed
? clarification
✓ INTAKE completed
...
✓ PLAN revision 1 completed
? changes requested
✓ PLAN revision 2 completed
```

Revision/question labels are presentation context derived from persisted state, not new provider event payloads. Persist only meaningful domain events such as `clarification.created`, `clarification.answered`, `plan.changes_requested`, and replacement linkage. Do not persist heartbeat/spinner refreshes or expose raw provider prose, reasoning, tool payloads, or stderr.

JSON supplies no progress sink. Non-TTY human progress remains bounded start/terminal lines per provider call. TTY finalizes the live renderer before every prompt.

## 14. Safety/bounds

- Maximum **5 Intake provider invocations per CLI invocation**, including the initial Intake call. Reaching the cap persists the current question/answer boundary and exits with `next_action: resume`; it is not a workflow failure.
- Maximum **3 Planner provider invocations per CLI invocation**, including the initial Plan call. Reaching the cap leaves the newest pending Plan or open feedback durable and exits with `next_action`.
- These are local defensive limits, not the future centralized budget/circuit-breaker system. A deliberate later `resume` gets a fresh per-invocation allowance.
- Known provider failure, timeout, or invalid output creates no artifact. Existing sanitized execution/failure evidence is retained; answered clarification or open Plan feedback remains recoverable.
- An unknown interrupted read-only operation is marked unknown before retry eligibility. Explicit `resume` may make a new attempt because Intake/Planner cannot mutate product files; it never reuses an unknown operation as success.
- Ctrl+C before human-input commit leaves the question or Plan pending and exits 130. Ctrl+C after commit preserves the answer/feedback. Ctrl+C during a provider call terminates the owned child using existing adapter behavior and leaves recoverable unknown evidence.
- EOF before answer/feedback commit leaves state unchanged and prints a recovery command. EOF after a `No` but before feedback does not create a change request.
- All answer/feedback writes, state changes, artifact-state changes, result links, and completion events use `BEGIN IMMEDIATE` transactions and idempotent uniqueness guards.
- Projection write failure never invalidates canonical JSON. It suppresses automatic approval prompting for that invocation as today.
- V1 routing and behavior are not altered.

## 15. Incremental implementation steps

Each step is independently testable, produces a real CLI slice, ends with the full repository validation where warranted, and stops before the next step's behavior.

### Step 1 — Clarification persistence and one-answer continuation

**Objective:** add immutable Intake revisions, explicit clarification lineage, and one safe answer/re-evaluation operation.

**Demonstrable CLI slice:** an ambiguous `run --json` persists one active question. `resume --answer "API HTTP" --json` persists that answer, invokes Intake once, and returns either a new single question or `READY`; a fresh `status --json` shows the same ordered records.

**Files expected to change:**

- `src/engineering_flow/domain.py`: `Clarification` value/invariants as needed.
- `src/engineering_flow/store.py`: additive table, revision-aware canonical paths, transactional clarification creation/answer/result linkage, stage-local artifact resolution.
- `src/engineering_flow/orchestrator.py`: resume/answer Intake from persisted context; latest Feature Contract validation; no interactive loop yet.
- `src/engineering_flow/cli.py`: boundary-checked `resume --answer` and JSON projection.
- `src/engineering_flow/codex_cli.py`: normally schema regression tests only; Feature Contract schema remains unchanged.
- `tests/test_domain.py`, `tests/test_store.py`, `tests/test_orchestrator.py`, `tests/test_cli.py`, and focused adapter tests if needed.

**Checkpoint acceptance:** question precedes promptability, answer precedes provider dispatch, old Feature Contracts remain immutable, one answer can yield a different/new question or `READY`, and Plan is never invoked before `READY`.

### Step 2 — Interactive clarification loop and recovery/mode closure

**Objective:** compose repeated one-question interactions under `run`/`resume` with mode policy, bounds, progress, and interruption recovery.

**Demonstrable CLI slice:** `run --request "Faca um CRUD de usuarios"` asks one question, re-evaluates after each answer, and either asks the next current question or proceeds to Plan. Killing and resuming before/after an answer restores the correct boundary without re-entering the request.

**Files expected to change:**

- `src/engineering_flow/orchestrator.py`: bounded coordinator dispatch across clarification states and READY-to-Plan.
- `src/engineering_flow/cli.py`: interactive eligibility, prompt orchestration, selected-workflow resume, EOF/Ctrl+C mapping.
- `src/engineering_flow/presentation.py`: one-question prompt, clarification recovery text, current-state rendering.
- `src/engineering_flow/runtime.py` only if a small provider-neutral progress annotation is proven necessary; no new progress architecture.
- tests in `test_orchestrator.py`, `test_cli.py`, `test_presentation.py`, and existing progress/runtime suites.

**Checkpoint acceptance:** all Intake cases in section 16 pass, JSON/non-TTY never prompt, the per-invocation Intake cap stops cleanly, and the MDS #2.1 READY happy path is unchanged.

### Step 3 — Plan feedback persistence and one revision lifecycle

**Objective:** distinguish request-changes from terminal rejection and generate one strictly validated replacement Plan through an explicit service/CLI path.

**Demonstrable CLI slice:** from Plan r1, `resume --feedback "Use PascalCase instead of snake_case" --json` persists feedback, leaves r1 immutable, creates a distinct current Plan revision, and returns to `awaiting_approval`. Restart after feedback commit continues the same request.

**Files expected to change:**

- `src/engineering_flow/domain.py`: `CHANGES_REQUESTED` workflow/artifact states and `PlanChangeRequest` value.
- `src/engineering_flow/store.py`: additive table, atomic request/change-state write, replacement link, revision-aware Plan/Markdown paths, latest-stage helpers.
- `src/engineering_flow/orchestrator.py`: request-changes guard, revised Planner context/hash, known-failure and restart behavior, exact-latest approval guard.
- `src/engineering_flow/plan_markdown.py`: revision-specific canonical source note/path without changing derived authority.
- `src/engineering_flow/cli.py`: `resume --feedback`, current revision/change-request projection.
- `src/engineering_flow/presentation.py`: concise change-request/revision state.
- `tests/test_domain.py`, `tests/test_store.py`, `tests/test_orchestrator.py`, `tests/test_cli.py`, `tests/test_plan_markdown.py`, and `tests/test_codex_cli.py`.

**Checkpoint acceptance:** r1 bytes/UUID/SHA remain unchanged, valid r2 has a distinct identity/path, invalid replacement output leaves no artifact/link, restart resumes open feedback, stale approval fails, and explicit terminal reject still works at an approval boundary.

### Step 4 — Interactive Plan revision loop and compatibility closure

**Objective:** make normal interactive `No` mean request changes, repeat within bounds, and close recovery/V1/MDS #2.1 regressions.

**Demonstrable CLI slice:** one interactive `run` can clarify, generate Plan r1, accept feedback, display Plan r2, and approve exactly r2. Non-TTY/JSON stops at each human boundary, and explicit `reject` remains terminal.

**Files expected to change:**

- `src/engineering_flow/orchestrator.py`: bounded multi-revision coordinator and final recovery reconciliation.
- `src/engineering_flow/cli.py`: interactive revision loop and exact displayed-artifact capture.
- `src/engineering_flow/presentation.py`: “What should be changed?” prompt, revised decision/result/recovery language.
- minimal corrections in `store.py`, `plan_markdown.py`, or `codex_cli.py` only when demonstrated by closure tests.
- comprehensive tests across `test_cli.py`, `test_presentation.py`, `test_orchestrator.py`, `test_store.py`, and compatibility suites.

**Checkpoint acceptance:** every section-16 test and section-17 smoke passes; 166 existing tests remain green; no V2 task execution or MDS #3 behavior exists.

## 16. Test matrix

Use current `unittest` conventions, temporary Git repositories/databases, injected fake runtimes, fake TTY streams, and fake monotonic clocks. Do not use sleeps.

### Intake clarification

| Case | Required assertion |
| --- | --- |
| One question at a time | Only the persisted first question is prompted; remaining old list items are not queued. |
| Answer persistence | Answer and timestamp commit before the next runtime request. |
| Re-evaluation | Runtime receives raw request, latest Feature Contract, and ordered answered records. |
| Answer eliminates old questions | A later contract may omit all remaining prior questions and become READY. |
| New question emerges | A later contract may ask a question absent from the prior list; that exact question becomes active. |
| Eventual READY | Latest READY revision has no questions and is the sole source allowed into Plan. |
| Planner ordering | Planner call count remains zero until READY; then exactly one initial Plan call occurs. |
| Restart before answer | Same question/ID reappears; no new workflow/artifact/clarification. |
| Restart after answer | Answer is not requested again; re-evaluation uses it. |
| Duplicate submission | Same answer is idempotent; different second answer conflicts without mutation. |
| Failed/invalid Intake revision | No result artifact/link; prior artifacts and answer survive; resume can make a new bounded attempt. |
| Ctrl+C/EOF | Before commit leaves unanswered; after commit preserves answer; provider interruption leaves unknown evidence and no false result. |
| Non-TTY | No stdin read; active question and recovery command emitted. |
| JSON | One document, empty progress stderr, full persisted clarification state, no prompt. |
| Selected workflow | UUID-free resume targets only the persisted selected workflow; explicit selector still wins. |
| Bound | Sixth Intake provider call in one invocation is not dispatched; resumable boundary is reported. |

### Plan revision

| Case | Required assertion |
| --- | --- |
| Interactive No | Creates `CHANGES_REQUESTED`, not approval decision `REJECTED`. |
| Feedback-before-Planner | Store record/state mutation is observable before runtime dispatch. |
| r1 immutability | r1 UUID, SHA, bytes, revision, and derived-view source remain unchanged. |
| Distinct r2 | r2 gets new artifact/execution UUID, revision 2 in the success path, embedded r2 ID, and revision-specific path. |
| Same validation | Revised Plan passes every existing identity/source/task/dependency/path/complexity/risk rule. |
| Invalid r2 | No Plan artifact or replacement link; r1 remains valid historical evidence; workflow is failed with open feedback. |
| Restart after feedback | Open change request with no replacement drives replanning without re-entry or duplicate record. |
| Restart after r2 | Current r2 and pending approval reopen without provider redispatch. |
| Exact approval | Approval row targets r2 artifact UUID and verified bytes. |
| Stale approval | r1 after feedback, r1 after r2, and r2 after r3 all fail closed without event/state mutation. |
| Multiple cycles | r1 -> feedback 1 -> r2 -> feedback 2 -> r3 -> approval preserves both feedback links and all artifacts. |
| Ctrl+C/EOF | No feedback record before complete input; committed feedback survives; interrupted replanning has no false replacement. |
| Non-TTY | Pending Plan never reads stdin; explicit feedback option is boundary-checked. |
| JSON | One document, no prompt/progress/ANSI, current Plan plus revision/change-request metadata. |
| Terminal reject | Explicit `reject` at pending approval remains terminal and never replans. |
| Bound | Fourth Planner provider call in one invocation is not dispatched; current boundary remains recoverable. |

### Compatibility and no-execution proof

| Case | Required assertion |
| --- | --- |
| MDS #2.1 happy path | Sufficient request still reaches Plan r1 and approves in one interactive invocation. |
| Progress | Intake/Plan revisions use existing provider-neutral events; raw provider content remains hidden. |
| Markdown | Each selected Plan revision has deterministic derived Markdown; JSON inspection does not repair; Markdown never approves. |
| Selected workflow | Existing pointer/update/explicit-selection rules remain intact. |
| Existing JSON keys | Additions are backward-compatible; every command remains a single document. |
| V1 | Feature-file planning, approvals, rejection/regeneration, task lifecycle, and artifacts are unchanged. |
| No implementation | V2 task/task-cycle/task-artifact row counts and Developer/Reviewer call counts remain zero after `PLAN_APPROVED`. |
| Full baseline | `.venv/bin/python3 -m unittest discover -s tests -q` passes. |

## 17. Manual smoke scenarios

Use the repository-local CLI in a disposable initialized repository and inspect `git status --short` after each scenario.

### 17.1 Interactive clarification to approval

```bash
.venv/bin/engineering-flow run --repo . --request "Faca um CRUD de usuarios"
```

Verify one question is shown, each answer is followed by a new Intake call, old questions are not blindly replayed, READY alone starts Plan, and approval ends at `plan/plan_approved` with no implementation.

### 17.2 Clarification recovery before and after answer

Start an ambiguous run, terminate at the question, then:

```bash
.venv/bin/engineering-flow resume --repo .
```

Verify the same question. In another run, submit an answer and terminate before re-evaluation; `resume` must preserve the answer and continue without asking it again.

### 17.3 Non-interactive and JSON clarification

```bash
.venv/bin/engineering-flow run --repo . --request "Faca um CRUD de usuarios" --json >result.json 2>result.err
.venv/bin/engineering-flow resume --repo . --answer "API HTTP" --json >answer.json 2>answer.err
```

Verify each stdout is one JSON object, stderr is empty, no prompt occurs, and persisted clarification state is complete.

### 17.4 Interactive Plan revisions

Run a sufficient request, answer `n`, provide `Use PascalCase instead of snake_case.`, inspect revision 2, then approve it. Verify r1/r2 JSON and Markdown files coexist; only r2 has an approval row.

### 17.5 Feedback recovery and invalid replacement

Persist feedback, terminate before Planner dispatch, and resume. Separately make a fake/controlled provider return an invalid revised task sequence. Verify r1 remains readable, no replacement artifact/link exists, failure is visible, and a later resume uses the same feedback.

### 17.6 Multiple revisions and stale decisions

Create r1, r2, and r3 through two change requests. Attempt explicit approval of r1 and r2; both must conflict. Approve r3 and reopen with `status --json` to prove exact binding.

### 17.7 Explicit terminal rejection and V1 regression

At a pending V2 Plan, run:

```bash
.venv/bin/engineering-flow reject --repo . --reason "Cancel this feature."
```

Verify terminal rejection and no replan. Then run a historical `--feature-file` workflow through its established path and confirm no conversational behavior or artifact naming changes.

## 18. Acceptance criteria

MDS #2.2 is complete only when all are true:

1. Every human clarification question is persisted before display and exactly one is active.
2. Every answer is persisted before Intake re-evaluation and survives restart.
3. Intake re-evaluates after each answer; it never treats an earlier list as a fixed queue.
4. All successful Feature Contract revisions are immutable, hash-verified, ordered, and linked through clarification records.
5. Planner cannot run until the latest Feature Contract is strictly `READY` with no open questions.
6. Interactive `No` means request changes, not terminal rejection.
7. Plan feedback is persisted against the exact target artifact before replanning.
8. Every successful replacement Plan has a distinct immutable artifact/revision/path and passes unchanged strict validation.
9. Failed/invalid replacement generation never replaces or corrupts the last valid Plan and leaves deterministic recovery evidence.
10. Approval binds to the exact highest current pending Plan revision; every stale revision fails closed.
11. Explicit terminal `reject` remains available and does not replan.
12. Restart before/after question, answer, feedback, revised Plan, or approval reconstructs the correct boundary without duplicate workflows or records.
13. Non-TTY and JSON never prompt; JSON remains one document and reports the full persisted feedback state needed for recovery.
14. Per-invocation Intake/Planner limits, provider failure, invalid output, Ctrl+C, and EOF cannot create silent loops or false success.
15. Progress continues through the existing provider-neutral model without provider-content leakage.
16. Selected-workflow resolution removes routine UUID copying without any latest-workflow heuristic.
17. Derived Markdown corresponds to the selected current Plan revision and never becomes authority.
18. V1 and all MDS #2.1 behavior remain compatible.
19. `PLAN_APPROVED` satisfies the product principle in section 1 and no implementation has started.
20. All existing 166 tests plus new coverage pass, `git diff --check` passes, and the manual smokes succeed.

## 19. Explicit out-of-scope

- MDS #3, Task Contract import/execution, IMPLEMENT, VERIFY, REVIEW, FIX, or DONE;
- Developer/Reviewer invocation or any production-code modification by the workflow;
- a general chat/message/conversation-history subsystem;
- a generalized workflow engine or broad state-machine rewrite;
- centralized global budgets, token accounting, or circuit breakers beyond the two local call caps;
- Planner task-ID redesign, validation weakening, or general provider-reliability work;
- V1 conversational clarification or V1 Plan revisions;
- editing canonical JSON/Markdown in place, Markdown import, or Markdown approval identity;
- command picker, slash commands, menus, workflow browser, TUI/full-screen UI, daemon, or dashboard;
- Plan revision diff generation beyond showing revision identity and current Plan;
- parallelism, worktrees, commits, pushes, PRs, or provider expansion.

## 20. Post-MVP UX backlog

Future work may add a human-oriented `engineering-flow` interactive shell that:

- infers the current repository;
- accepts free-text requests without `--request`;
- resumes the selected workflow at startup;
- offers command pickers, slash commands, menus/selects, richer Plan diffs, and a workflow browser;
- considers a full TUI only if real usage justifies it.

Its required boundary is:

```text
Interactive UI --+
                 +--> Application / Workflow layer
Traditional CLI -+
```

The future shell must call the application/workflow layer directly and must not shell out to the traditional CLI. MDS #2.2 does not design or implement that shell.

## 21. Known Planner reliability follow-up

Real-provider smokes have sometimes returned non-contiguous Task IDs, although the most recent smoke produced valid `T1` and `T2 depends on T1` output. MDS #2.2 retains fail-closed contiguous-ID validation for initial and revised Plans.

Improving Planner prompt/schema adherence, provider retries, or task-ID reliability is a separate backlog concern. It must not weaken validation, change task identity, or expand this milestone unless a narrowly revision-specific defect is proven during implementation.

## Planning status

`AWAITING_HUMAN_APPROVAL`

There are no blocking open product decisions. Approval of this plan authorizes the explicit choices above: two narrow additive tables, `CHANGES_REQUESTED` workflow/artifact states, revision-aware legacy-compatible filenames, stage-local V2 current-artifact resolution, `resume --answer/--feedback` as minimal explicit inputs, and per-invocation limits of five Intake calls and three Planner calls.
