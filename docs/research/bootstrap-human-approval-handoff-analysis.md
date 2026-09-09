# Bootstrap Human-Approval Handoff Analysis

## Decision

**FIX_NOW.** Add one narrow, deterministic approval handoff to the bootstrap Codex Host/Controller boundary. It must accept an already explicit human approval signal, derive the only permissible artifact reference from the Controller's current open gate, persist the normal Controller approval, and perform the existing canonical successor mechanics. It is a small bootstrap correction, not a new approval provider, RPC protocol, terminal automation, or workflow framework.

The human continues to decide whether to approve. The code only converts that explicit decision into the existing append-only, exact-revision Controller fact. It must never infer approval from artifact existence, a child result, or ambiguous conversational text.

## 1. Root cause of the Wave 3 gap

`create-tasks` correctly created the canonical Wave 3 task set and stopped for human approval, as its Skill requires. The human then explicitly said "aprovo", but the bootstrap Host has no approval-response entry point: its only public workflow loop is `run_task_loop`, which starts *after* task registration and dispatches only Developer, Reviewer, and Fixer roles.

Meanwhile, the Controller correctly requires a persisted `APPROVE` governance decision. Its generic public CLI requires the caller to supply the gate, actor, evidence-file JSON, and `--authority-wave`; `Controller.approve()` requires the evidence list as well. Nothing bridges the human's conversational approval to that API. Thus no `TASK_PLAN_APPROVAL` decision was written, the state correctly remained `TASK_PLAN_REQUIRED`/the task-plan approval boundary was not crossed, and `register-tasks` correctly rejected the request.

This is integration omission, not a defect in the exact artifact/hash guard. The same omission exists at `TECHSPEC_APPROVAL`.

## 2. Current flow versus desired flow

| Current supervised flow | Desired supervised flow |
| --- | --- |
| Skill writes `TECHSPEC.md` or `TASKS.md` and stops. | Same. |
| Human says an explicit approval. | Same; approval remains a human act. |
| Host has no action for the reply. A human/operator must discover and run generic governance CLI with hand-built JSON/hash/wave. | Conversation-facing Host recognizes the reply only as an explicit approval of the currently presented gate and calls the narrow handoff. |
| Controller validates supplied evidence and persists the decision. | Controller itself resolves its fixed target, reads its bytes, derives SHA-256, validates the open gate, and persists the identical kind of decision. |
| Operator separately advances/continues and separately calls `register-tasks`. | The handoff advances only the canonical successor; task-plan registration is internally chained and recovery-safe, with no normal-user command. |

The Host must present the gate and artifact identity when asking for approval, so an approval reply is associated with one known pending request. A bare approval without a pending, unambiguous Host request, an explicit rejection, or a request to modify the artifact must not call the handoff.

## 3. Ownership of the handoff

**Conversation-facing bootstrap Codex Host** owns receipt of the human signal: it asks for the particular open approval, retains the locally known actor provenance, accepts only an explicit affirmative response, and invokes the narrow Controller operation. It does not choose a gate from prose, construct an artifact path, calculate a hash, or write the control record.

**Controller** owns all deterministic authority mechanics: it verifies that an approval gate is open for its own wave, maps that gate to its one canonical target, derives evidence, appends the decision, validates active approval lineage, changes lifecycle only through existing canonical transitions, and imports the task index. It remains the sole control-record writer.

**CLI** should expose the same narrow operation as a supervised recovery/operator entry point, but not as normal UX. It takes only `--actor` (with the Controller's already-selected `--wave`); it must not accept `--gate`, `--evidence`, or `--authority-wave` for this operation. Existing generic `approve`, `record-authority`, and `register-tasks` remain available for forensic/compatibility use and retain their strict inputs.

**Skills** remain unchanged in responsibility. `create-techspec` and `create-tasks` must still stop at `AWAITING_HUMAN_APPROVAL` and must never invoke or simulate approval. The Host acts only after a later human message.

## 4. Evidence derivation

Add a Controller-owned operation conceptually named `approve_pending_human_gate(actor)`. It may support only the current open `TECHSPEC_APPROVAL` or `TASK_PLAN_APPROVAL`; it is not a generic authorization or approval API.

1. Load and validate the control record and identify `GATES[lifecycle_state]`. Reject anything other than the two approval gates.
2. Resolve the target using the existing allowlist in `_approval_target()`: `docs/waves/<wave>/TECHSPEC.md` for TECHSPEC approval and `tasks/<wave>/TASKS.md` for task-plan approval.
3. Resolve with `_inside(root, target)`, require a regular file, read its bytes once, and compute SHA-256 with the existing hashing rule.
4. Construct exactly one Controller-owned reference, for example `{ "path": target, "sha256": digest, "purpose": "human-approved <gate>" }`. The purpose string is non-authoritative metadata; path and digest are the authority binding.
5. Call the existing typed approval recording path with `authority_wave_id` fixed to `self.wave_id`, then revalidate the active approval before the successor action.

There is no caller-selected path, digest, wave, or gate. The Controller's existing `_validate_refs()` and `_active_approval()` continue to re-read and hash the artifact whenever approval is used; mutation after approval therefore invalidates authority rather than silently carrying it forward.

## 5. TECHSPEC approval behavior

For an open `AWAITING_TECHSPEC_APPROVAL`, the handoff records the exact current `TECHSPEC.md` approval under the existing append-only governance lineage. It then performs the existing `next()` transition to `TASK_PLAN_REQUIRED`, which again validates the active current TECHSPEC approval. It must stop there: do not acquire or dispatch Planner work automatically. This preserves the Skill rule that human approval completes `create-techspec` and that task creation is a separately initiated bounded action.

An idempotent replay for the unchanged artifact returns the existing decision and reports the already-reached successor state/action. A changed TECHSPEC cannot replay as approval; it requires a new explicit approval cycle (and normal revocation/supersession semantics where applicable).

## 6. TASK PLAN approval behavior

For an open `AWAITING_TASK_PLAN_APPROVAL`, the handoff records the exact current `TASKS.md` approval. It retains the Controller's existing direct transition to `TASK_EXECUTION_REQUIRED`, then invokes the existing `register_tasks()` importer. Registration still parses only the canonical Execution Order table and persists the ordered `PENDING` Controller task records plus the exact plan path/hash. It does not execute, select, acquire, or dispatch a Developer.

The resulting normal-user outcome is: human approves the task plan; the task set becomes registered; the Host can subsequently start its existing bounded task loop. If the task plan is malformed, missing, or changes before import, the approval fact is not converted into executable work and the failure remains visible/actionable. No weaker artifact check is introduced.

## 7. Task registration: automatically chained, still a separate Controller transition

Registration should be **automatically chained inside the narrow handoff**, but remain the separate `register_tasks()` Controller transition and separate atomic control-record write. This is the smallest safe UX correction:

- It makes the normal task-plan approval handoff complete without asking the human to discover a second plumbing command.
- It preserves the existing importer as the sole parser/registrar and does not make approval itself imply arbitrary task content.
- It avoids changing the lifecycle model, task selection, or execution policy.
- Its separate durable writes make an interruption recoverable: an approval may be durable before registration, but never produces a Developer action until the existing registration succeeds.

Do not fold plan parsing or task creation into approval, and do not call `next()` after registration as part of this handoff. That avoids automatic Developer selection/dispatch and preserves explicit Host initiation of the task loop.

## 8. Idempotency and recovery

The new operation must be safe to retry after a duplicated human message, Host retry, process crash, or CLI retry:

- Same open gate, same current bytes, same actor: reuse the existing deterministic decision ID (`IDEMPOTENT`), not a second approval.
- TECHSPEC: if approval is already active, converge through `next()` to `TASK_PLAN_REQUIRED`; never redispatch Planner work.
- Task plan: if approval is already active and `task_plan`/`tasks` exactly match current `TASKS.md`, `register_tasks()` returns `IDEMPOTENT`; otherwise it rejects conflict or drift without mutation.
- A crash after persisted approval but before registration is repaired by a retry/resume of this handoff, which calls only the idempotent importer. A crash after registration is likewise harmless.
- A changed, revoked, superseded, missing, ambiguous, wrong-wave, or malformed artifact never gets silently re-approved. Return `HUMAN_ATTENTION` or the existing deterministic invalid result, preserving the historical decision.

The Host must store no separate approval state. The control record and authoritative bytes remain sufficient for recovery.

## 9. Required changes by file/component

| File/component | Minimal change |
| --- | --- |
| `tools/wave_controller/core.py` | Add the narrowly scoped pending-human-approval method and private evidence builder. Reuse `_approval_target`, `_hash`, `_record_decision`, `_active_approval`, `next`, and `register_tasks`; do not change generic evidence validation or authorization gates. Return structured decision/registration/successor results. |
| `tools/wave_controller/host.py` | Add a small explicit-human-approval adapter used by the conversational/supervised Host. Its inputs are a `Controller` and confirmed actor; it calls the Controller method and returns its structured result. Keep `run_task_loop` limited to Developer/Reviewer/Fixer. |
| `tools/wave_controller/cli.py` | Add a narrow `approve-pending --actor ...` wrapper for supervised recovery. It receives neither evidence nor authority-wave. Keep existing low-level commands unchanged for compatibility. |
| `tests/bootstrap/test_wave_controller.py` | Add Controller/CLI tests for both gates, deterministic references, drift, idempotency, retry after the two write boundaries, invalid pending state, and no dispatch. |
| `tests/bootstrap/test_wave_controller_host.py` | Test that only a supplied explicit approval signal reaches the adapter, and that its results do not invoke Codex, acquire an operation, or run tasks. |
| Conversation Host integration (currently not represented by a broader Python session orchestrator) | At the point it receives the human reply to a known pending approval prompt, call the Host adapter. This is a call-site integration, not a new persistent service. |
| Skills / Wave 3 TECHSPEC / Wave 3 task plan / `src/engineering_flow/` | No change for this bootstrap correction. |

## 10. Required tests

Focused disposable-fixture tests should prove:

1. `approve_pending_human_gate` at TECHSPEC derives exactly the canonical TECHSPEC path and current SHA-256, appends one approval decision, and ends at `TASK_PLAN_REQUIRED` without Planner acquisition/dispatch.
2. The same behavior at task-plan approval derives exactly `TASKS.md`, records one decision, registers the parsed ordered plan, and leaves no active operation or Developer dispatch.
3. The public narrow CLI needs only `--wave` and `--actor`; attempts to select a gate/path/hash/wave through it are impossible, while the generic CLI remains compatible.
4. Byte changes before approval bind the new bytes; byte changes after approval fail active-approval/registration checks and cannot start work.
5. Missing, non-file, malformed TASKS table, wrong lifecycle, ambiguous lineage, revoked/superseded approval, and invalid actor fail closed.
6. Duplicate Host/CLI calls are idempotent and write neither a duplicate decision nor duplicate tasks.
7. Simulated interruption after approval persistence and before registration resumes to exactly one registered task set; interruption after registration is equally idempotent.
8. Existing tests still demonstrate that Wave-start authorization, later-Wave authorization, release/delivery authorization, and reviewer lifecycle behavior are untouched.

Run focused bootstrap tests and then the repository's required full command: `.venv/bin/python3 -m unittest discover -s tests -q`.

## 11. Compatibility impact on current Wave 3

No Wave 3 artifact is changed by this analysis or by the proposed correction. The current control record shows the earlier exact `TECHSPEC_APPROVAL` and `TASK_PLAN_REQUIRED`; the present untracked Wave 3 task directory is left untouched. The correction does not register the current task set, does not execute any task, and does not reconstruct an approval from the prior "aprovo" message.

After implementation, a human must explicitly approve the then-current `tasks/3-workflow-capability-orchestration/TASKS.md` through the normal conversation-facing Host. The Controller will hash that exact current file at that time. If it differs from what was reviewed, the Host must present it for review again; it may not reuse the old utterance. Wave-start, next-Wave, release acceptance, and delivery authorization are outside the narrow method and remain explicit, separate governance actions.

## 12. Recommendation and estimate

**Recommendation: FIX_NOW.** The gap blocks the intended supervised bootstrap UX and is present at both standard approval gates. The correction is bounded: roughly one small Controller method plus a Host adapter and CLI wrapper, with focused Controller/Host tests (approximately 150–250 lines of production and test change combined, depending on result-shape coverage). It requires no product-runtime work, no Skill/TECHSPEC/task-plan amendment, no provider abstraction, and no lifecycle redesign.

