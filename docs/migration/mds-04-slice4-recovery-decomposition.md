# MDS #4 Slice 4 Remaining Recovery Work — Safety Decomposition

## 1. Status and purpose

**Status: proposed decomposition; no implementation authorization.**

This document decomposes the remaining MDS #4 Slice 4 work after the current
uncommitted implementation's review/fix cycles. It is subordinate to
`docs/migration/mds-04-deterministic-verification-plan.md`. It does not change
that design, approve implementation, or redefine MDS #4 outcomes.

The decomposition is based on inspection of:

- the authoritative MDS #4 design and architecture review;
- the uncommitted changes in `process_identity.py`, `store.py`, and
  `verification.py`;
- existing MDS #4 Slice 1–4 tests, including direct persistence and fault
  injection coverage;
- `cli._continue_approved_implementation`, CLI `resume` routing,
  `ImplementationAttemptOrchestrator.run_once`,
  `PlanningOrchestrator.resume`, and its task-execution path; and
- the verification attempt, command-result, common lease, operation,
  execution, task-state, workflow, and event persistence APIs.

The focused Slice 1–4 suite currently passes 76 tests. Those tests do not prove
the unresolved invariants below: an exact-ID caller can still release without
recovery authority, an exact-match generic lease delete can remove UNKNOWN
ownership, a non-passing command can have a successor, the recovery service is
not on the production path, legacy UNKNOWN evidence can be rewritten
lossily, and the live-owned recovery branch does not persist
`HUMAN_ATTENTION`.

The candidate boundaries are retained. Their safe dependency order is:

```text
4A Persistence Safety Boundary Hardening
  -> 4B Command Recovery State Machine
    -> 4D Legacy Evidence & Recovery Projection
      -> 4C Recovery Production Integration
```

4C is intentionally last. Connecting recovery to production before the lower
boundaries are safe would make the known bypasses reachable from the real CLI.

## 2. Boundary rule and architectural layers

The governing rule is:

> An invariant is enforced at the lowest architectural boundary that can
> prevent every caller from violating it.

The relevant layers, from lowest to highest, are:

1. **SQLite schema and `WorkflowStore` transaction/mutation boundary.** Owns
   durable state-machine legality, exact ownership comparisons, lease retention
   and deletion, atomic projection, and rollback. A higher service cannot make
   an unsafe public store API safe.
2. **Recovery inspection/classification boundary.**
   `VerificationRecoveryService` alone may combine durable context with host,
   boot, process-group, repository, control-state, manifest, and approved
   authority observations. It may classify; it may not dispatch or signal.
3. **Verification execution boundary.**
   `DeterministicVerificationOrchestrator` owns fresh-attempt command execution.
   It may request only transitions accepted by the store state machine.
4. **Composed task coordinator boundary.** Owns the invocation rule: preflight
   before mutation, IMPLEMENT followed by VERIFY after rereading durable
   success, recovery-only invocations, and no same-invocation successor after
   reconciliation.
5. **CLI/presentation boundary.** Routes `resume` to the composed coordinator
   and displays persisted outcomes. It is not a safety authority.

Some invariants require evidence from two layers. In particular, SQLite cannot
observe an operating-system process or inspect Git by itself. The recovery
service must establish those external facts, while the store must reconstruct
all durable authority and be the only boundary able to apply a release. Passing
caller-supplied IDs to a generic delete is not such a split proof.

Direct test-only SQL corruption remains useful adversarial input, but is not a
production API. Recovery must fail closed when it encounters such corruption.

## 3. Global invariant matrix

| Invariant | Owning boundary | Possible bypass APIs/functions in the current tree | Required proof/tests |
| --- | --- | --- | --- |
| UNKNOWN implies the existing verification lease is retained | `WorkflowStore` verification transition and lease APIs | `release_workspace_operation_lease`; `finish_verification_attempt`; any new terminal helper; indirect overwrite through generic workflow/task mutation APIs | Direct calls with exact IDs against an UNKNOWN attempt cannot delete or replace the lease; every failure rolls back; a successor IMPLEMENT/VERIFY/FIX remains blocked |
| Lease release requires complete durable authority plus a permitted terminal transition | `WorkflowStore`, using an externally established recovery decision only through a recovery-specific boundary | `finish_verification_attempt(... interrupted_unchanged)`; `release_workspace_operation_lease`; `record_verification_command_result` clearing child identity; `record_workspace_operation_child`; `record_verification_command_started` | Forged IDs/evidence, incomplete joins, UNKNOWN status, active/ambiguous identity, changed/unreadable repository, invalid command state, and terminal-write faults all retain the lease; only exact normal terminal completion or dead-and-unchanged recovery can release atomically |
| Ambiguity fails closed and preserves all ownership evidence | Store recovery-context/projection APIs; recovery service classifies | `active_verification_recovery_context`; `retain_ambiguous_verification_recovery`; `retain_inconsistent_verification_lease`; `VerificationRecoveryService.reconcile` | Zero/multiple leases or attempts, broken joins, host/boot mismatch, PID reuse, incomplete identity, and inspection failure never signal, dispatch, release, or guess; exact identifiers and observations remain durable |
| Every safety transition is atomic on any exception | `WorkflowStore._transaction` and each store mutation transaction | All verification command/result/UNKNOWN/terminal/recovery projection APIs; event insertion and lease deletion are late failure points | Inject `DomainFailure`, SQLite errors, ordinary `RuntimeError`, and event/delete failures before and after each projection write; assert byte-for-byte logical state and lease ownership are unchanged and no transaction remains open |
| Command N+1 exists only if command N completed successfully under the verification contract | Store-owned command state machine | `record_verification_command_intent`; `record_verification_command_result`; `finish_verification_attempt`; recovery `_validate_command_evidence`; execution loop in `DeterministicVerificationOrchestrator.run` | For every non-passing/unsafe/corrupt result form, direct N+1 persistence is rejected; gaps, duplicates, altered binding, unresolved predecessors, and impossible legacy prefixes fail closed; recovery cannot accept them as a valid prefix |
| `VERIFIED` is possible only after the complete bound command sequence passed | Store-owned terminal state machine | `finish_verification_attempt(... verified)`; incomplete persisted manifest/command binding; caller-provided final inspection | Direct early/empty/out-of-order VERIFIED requests fail; exact final ordinal and every result are validated against the bound sequence and baseline in the same terminal transaction |
| A recovery invocation reconciles only and never dispatches/executes in that invocation | Composed task coordinator | `ImplementationAttemptOrchestrator.run_once`; `_continue_approved_implementation`; `PlanningOrchestrator.resume` / `_resume_task_execution`; CLI `resume`; any call to `DeterministicVerificationOrchestrator.run` after reconcile | With every recovery outcome, mocks prove zero writer, runner, review, FIX, next-task, and fresh-attempt calls; dead-and-unchanged requires a later explicit invocation for a new attempt |
| The real resume and post-IMPLEMENT paths always reach recovery/verification safely | Composed coordinator, routed by CLI | CLI's current status/active-implementation-only branch; `_continue_approved_implementation`; `ImplementationAttemptOrchestrator.run_once`; fallback `PlanningOrchestrator.resume` | CLI and coordinator integration tests cover active VERIFY, UNKNOWN, persisted `IMPLEMENTATION_COMPLETED`, and same-invocation `completed_changed`; no path falls into the legacy agent task loop |
| Recovery evidence is loss-preserving | Store UNKNOWN/recovery merge boundary | `_retain_verification_unknown_unlocked`; `_unknown_observation`; `retain_verification_unknown`; `retain_verification_recovery_unknown`; inconsistent/ambiguous event de-duplication | Pre-fix valid JSON without `original_unknown_evidence`, corrupt raw JSON, partial identity, conflicting later observations, and repeated observations preserve the exact original and append only distinct canonical observations |
| A live exactly-owned verification process durably projects `HUMAN_ATTENTION` while retaining ownership | Recovery service classifies; store atomically projects | `VerificationRecoveryService.reconcile` live branch currently returns without writing; `set_workflow_state`; `cancel_v2_workflow`; task-operation/intervention paths can overwrite workflow state | Live-owned reconciliation writes `HUMAN_ATTENTION` plus bounded evidence/event, changes no attempt/command/lease ownership, is idempotent, rolls back atomically, and blocks every production dispatcher |

## 4. Sub-slice 4A — Persistence Safety Boundary Hardening

### 4A.1 Exact scope

4A makes verification ownership and release safe independently of every
higher-level caller.

It must:

1. Remove verification lease deletion authority from
   `release_workspace_operation_lease`. Prefer removing the unused public API.
   If compatibility requires retaining it, it must reject
   `operation_kind='verification'` and any lease linked to an unresolved
   verification attempt. Exact caller-supplied IDs are not release authority.
2. Split normal verification completion from crash recovery completion.
   `finish_verification_attempt` must not accept
   `interrupted_unchanged`. A recovery-specific store operation must begin from
   one workflow/recovery context, reread the unique lease, attempt, operation,
   execution, task state, command state, and workflow inside its transaction,
   and compare the externally established observation with that exact context.
3. Make the recovery-specific release legal only when the attempt is
   `verifying`, never `unknown`; the exact process identity was classified
   dead; the exact repository/control inspection matches the attempt baseline;
   all durable linkages and lifecycle projections are coherent; and the crash
   position is permitted by the command state machine. The complete recovery
   observation must be persisted in the same transaction that writes
   `interrupted_unchanged` and deletes the lease.
4. Keep all UNKNOWN paths lease-retaining at the store boundary, including
   normal execution uncertainty, recovery uncertainty, ambiguous linkage,
   repository drift, unreadable inspection, and persistence ambiguity.
5. Harden child ownership mutations. `record_workspace_operation_child` must
   not be able to rewrite verification child identity. Verification start
   evidence must be write-once for one unresolved command and must match the
   exact operation/workflow/lease owner chain. Result persistence may clear the
   active child fields only as part of the exact command-result transaction and
   may not erase the historical command identity.
6. Retain the existing common repository-key uniqueness mutex. No recovery or
   release path may replace, steal, age out, or synthesize a lease.
7. Apply rollback on every `BaseException` after `BEGIN`, preserving the
   original exception if rollback also fails. All projection, event, evidence,
   and delete writes named above must share one transaction.
8. Add a common unresolved-verification guard to generic store mutation
   surfaces that could move the same workflow out of its safety projection.
   The audit must include at least `set_workflow_state`, `cancel_v2_workflow`,
   `record_intervention`/`intervene`, task selection/operation creation,
   `accept_task`, `complete_task_cycle`, and planning/task reconciliation
   entrypoints. Safe read-only APIs and the dedicated verification recovery
   projection APIs are exempt.

The recovery decision passed from the recovery service must be a narrow value
object containing the exact observed identity and inspection, not a bag of IDs.
Its type is useful for clarity but is not itself security: the store's durable
reconstruction and transition validation remain mandatory.

### 4A.2 Explicit non-goals

- Defining command-success sequencing or final command completeness; 4B owns
  those state-machine rules.
- Wiring recovery into CLI or production orchestration; 4C owns that work.
- Repairing legacy UNKNOWN envelopes or live-owned projection; 4D owns those.
- Changing process-observer semantics, killing a process, retrying a command,
  or starting a replacement attempt.
- Adding TTLs, lease stealing, cleanup/reset/stash behavior, REVIEW, FIX, next
  task, commit, push, or PR behavior.

### 4A.3 Safety invariants and owning layer

| Invariant | Owner |
| --- | --- |
| UNKNOWN always retains its existing exact verification lease | `WorkflowStore` verification transition APIs |
| A verification lease can be deleted only by exact normal terminal completion or exact recovery completion | `WorkflowStore` operation-specific terminal APIs |
| Recovery release requires coherent durable attempt/lease/operation/execution/task/workflow authority | Recovery-specific `WorkflowStore` transaction |
| Process death and repository stability are established from exact observed evidence, never inferred from IDs | `VerificationRecoveryService` observes; recovery-specific store transaction binds and persists the decision |
| Child identity is write-once while unresolved and historical identity is never cleared | `WorkflowStore` command start/result APIs |
| Ambiguous ownership is never released, reassigned, or signaled | Store retention boundary plus recovery classifier |
| Partial transition failure changes no durable row or event | `WorkflowStore._transaction` and each mutation transaction |

### 4A.4 Existing bypass-capable APIs/functions

- `WorkflowStore.release_workspace_operation_lease` can currently delete an
  exact-match verification lease without inspecting attempt status; this is the
  direct UNKNOWN-retention bypass.
- `WorkflowStore.finish_verification_attempt` currently accepts
  caller-selected `interrupted_unchanged` and releases after matching IDs; it
  does not itself reconstruct recovery authority or prove death/stability.
- The same `finish_verification_attempt` is also the normal release surface for
  `verified`, `verification_failed`, and `verification_blocked`; 4A must make
  its ownership checks operation-complete, while 4B adds command legality.
- `WorkflowStore.record_workspace_operation_child` is generic, does not
  restrict `operation_kind`, and can mutate verification lease child evidence.
- `WorkflowStore.record_verification_command_started` currently permits an
  already-bound unresolved command/lease child identity to be overwritten.
- `WorkflowStore.record_verification_command_result` clears lease child fields
  based on a caller-reported result. It is part of a possible forged-release
  chain unless exact start/result ownership and transition legality are
  enforced.
- `WorkflowStore.set_workflow_state`, `cancel_v2_workflow`,
  `record_intervention`, `accept_task`, `complete_task_cycle`, task-operation
  creation/failure/reconciliation, and other public workflow projection
  mutators can bypass the intended recovery projection unless they reject an
  unresolved verification lease.
- `VerificationRecoveryService.reconcile` is the intended recovery caller but
  currently reaches the generic terminal method for interruption.

`finish_implementation_attempt` is not a verification-lease bypass because its
delete predicate is restricted to `operation_kind='implementation'`; retain
and regression-test that separation.

### 4A.5 Required production changes

- Delete or restrict `release_workspace_operation_lease` as described above.
- Introduce separate store entrypoints for normal execution completion and
  interrupted recovery completion. Use private shared helpers only when they
  preserve the different preconditions.
- Move durable recovery-context reconstruction into the recovery-specific
  transaction. Do not authorize release from a context read earlier by the
  caller without rechecking it transactionally.
- Add exact comparison of repository key, canonical root, workflow, attempt,
  verification operation, execution, task binding, lease, owner, child/command
  identity, and allowed attempt/lifecycle statuses.
- Persist the recovery observation before lease deletion and include it in the
  terminal event. The delete predicate must include all exact ownership fields
  and `operation_kind='verification'`.
- Reject recovery completion for an attempt already marked UNKNOWN even if a
  later observation says dead/unchanged; UNKNOWN is sticky.
- Make verification child start write-once and prohibit the generic child API
  from touching verification leases.
- Add an internal store guard for unresolved verification ownership and call it
  from every audited generic workflow/task mutation surface.
- Preserve the broadened `_transaction` rollback behavior and add fault tests
  to every new transition.

### 4A.6 Required adversarial tests

- Call generic lease release with the exact repository/lease/attempt/owner IDs
  of an UNKNOWN verification attempt; assert rejection and identical lease.
- Repeat for `verifying`, ambiguous, corrupt-linkage, and terminal evidence;
  no generic path may delete a verification lease.
- Call normal completion with `interrupted_unchanged`; assert it is not an
  accepted outcome.
- Forge a recovery decision with correct IDs but alive, missing, reused,
  different-host/boot, mismatched session/group, changed repository, missing
  control fingerprint, unreadable inspection, or stale baseline evidence;
  assert no projection or release.
- Change each durable linkage between recovery read and terminal transaction;
  assert compare-and-transition failure and retained lease.
- Attempt interrupted recovery against an UNKNOWN attempt with exact dead and
  unchanged evidence; assert UNKNOWN and lease are unchanged.
- Attempt to overwrite a verification command's persisted child identity and
  to mutate it through `record_workspace_operation_child`; assert rejection.
- Fault after attempt, execution, operation, task, workflow, event, recovery
  evidence, and lease-delete writes. Test domain, SQLite, and ordinary runtime
  exceptions; assert full rollback and `connection.in_transaction == False`.
- Exercise every audited generic workflow/task mutator while a verification
  lease is unresolved; assert it cannot advance, cancel, accept, dispatch, or
  replace the safety projection.
- Confirm implementation lease completion remains functional and cannot delete
  a verification lease with colliding caller-supplied identifiers.

### 4A.7 Entry assumptions

- Slice 1 manifest/authority validation, Slice 2 attempt/common-lease schema,
  and Slice 3 command runner/evidence exist.
- Repository-key uniqueness remains the common IMPLEMENT/VERIFY mutex.
- Process group identity fields added by the current Slice 4 work are present,
  but their completeness is not trusted until validated.
- No production integration depends on the unsafe release APIs yet.

### 4A.8 Exit criteria

- No public or internal production API can delete a verification lease merely
  from caller-supplied matching IDs.
- UNKNOWN retention is enforced by the store, not by caller convention.
- Normal terminal and recovery terminal APIs have disjoint, explicit allowed
  transitions.
- Recovery terminalization atomically persists its complete decision and
  releases only after durable authority is reconstructed.
- Child ownership evidence cannot be rewritten or erased outside the exact
  command-result transition.
- All new adversarial and rollback tests pass, plus Slices 1–4 and full
  repository validation.

### 4A.9 Dependencies and order

4A has no dependency on the other remaining sub-slices and must be first. 4B
depends on its safe transition primitives. 4D depends on its retention and
atomic projection primitives. 4C must not begin until 4A, 4B, and 4D pass.

## 5. Sub-slice 4B — Command Recovery State Machine

### 4B.1 Exact scope

4B makes the persisted command sequence an enforceable state machine rather
than evidence interpreted only by `VerificationRecoveryService`.

The legal progression is:

```text
bound attempt, no commands
  -> intent(1)
  -> started(1)
  -> terminal passing result(1)
  -> intent(2) ...
  -> terminal passing result(last)
  -> VERIFIED
```

At any ordinal, a known non-passing result stops the sequence and permits only
its matching non-success terminal attempt outcome. An unsafe, corrupt, or
ambiguous result permits only UNKNOWN retention. An unresolved intent permits
reconciliation only. It never authorizes re-execution or a successor command.

4B must:

1. Persist enough immutable command authority at attempt creation to validate
   count, order, IDs, argv, timeouts, and canonical hashes without trusting a
   later caller. Extend the attempt's persisted manifest/command binding with
   the canonical ordered command list or an equivalent normalized child table;
   a single aggregate hash is insufficient to enforce the last ordinal.
2. Centralize command-row validation in a store-owned validator used by intent,
   start, result, normal terminalization, and recovery context loading.
3. Permit intent N only when N is exactly the next bound ordinal and every
   preceding row is terminal `passed` with exit zero, no timeout/output limit,
   a complete safe inspection equal to the attempt baseline/control boundary,
   and coherent historical owner identity. Checking only `result_at` is
   insufficient.
4. Validate result classification and facts when the result is written, not
   only during later recovery. A caller cannot label a nonzero/timeout/unsafe
   result `passed`.
5. Make terminal outcomes correspond to command state: `verified` requires the
   entire bound sequence passed; `verification_failed` requires the first
   known safe non-passing result and no successor; `verification_blocked`
   requires an allowed structural/spawn-blocked position; UNKNOWN-retaining
   conditions cannot be terminalized as known outcomes.
6. Make recovery reject every impossible prefix before process observation or
   repository-based release. Recovery may consume the store's validated state;
   it must not maintain a weaker duplicate state machine.
7. Treat pre-fix command evidence lacking sufficient immutable binding as
   non-authorizing. It may be preserved and routed to UNKNOWN/HUMAN_ATTENTION,
   but must not be guessed, continued, or released as a valid prefix.

### 4B.2 Explicit non-goals

- Process liveness and repository inspection algorithms, except consuming
  their already-defined evidence.
- CLI/coordinator integration, fresh retry policy, or same-invocation flow.
- Legacy UNKNOWN envelope normalization; 4D owns that evidence shape.
- Changing manifest v1, parallel commands, command filters, shell execution,
  environment policy, or raw-output retention.
- Re-executing an unresolved or completed command during recovery.

### 4B.3 Safety invariants and owning layer

| Invariant | Owner |
| --- | --- |
| N+1 requires N to be successfully complete under the full verification contract | `WorkflowStore` command-intent transition |
| Command order and final ordinal come from immutable persisted authority | Verification attempt schema plus `WorkflowStore` |
| Result classification cannot contradict result/inspection facts | `WorkflowStore.record_verification_command_result` |
| A non-passing command has no successor command | Store command state machine |
| `VERIFIED` requires every bound command, in order, passing | Store normal terminal transaction |
| Impossible/corrupt prefixes fail closed before observation or release | Store validated recovery context, consumed by recovery service |

### 4B.4 Existing bypass-capable APIs/functions

- `record_verification_command_intent` currently requires only that N-1 has a
  non-null `result_at`; it accepts N+1 after failed, timed-out, output-limited,
  spawn-blocked, repository-mutated, or internally inconsistent N.
- Its existing-row idempotency branch can return a row without validating the
  whole prefix or whether the attempt may still execute.
- `record_verification_command_result` currently accepts caller-selected
  classifications and inspection mappings without enforcing their semantic
  relationship to exit/timeout/output/repository facts.
- `finish_verification_attempt(... verified)` does not currently prove that
  all bound commands exist and passed.
- `finish_verification_attempt` can similarly accept a failure/block outcome
  inconsistent with the last command position.
- `VerificationRecoveryService._validate_command_evidence` validates each
  completed row's internal facts but currently accepts a prefix containing a
  completed non-passing row followed by a later command.
- `VerificationRecoveryService.reconcile` relies on that prefix and may then
  accept an impossible state as recoverable.
- `DeterministicVerificationOrchestrator.run` normally stops on non-pass, but
  caller correctness is not enforcement and direct store callers bypass it.

### 4B.5 Required production changes

- Extend verification intent persistence to bind the normalized ordered
  commands, transactionally with the attempt and lease. Validate the aggregate
  hash against that normalized list.
- Add one internal parser/validator that returns a typed command-state result:
  `EMPTY`, `UNRESOLVED_N`, `PASSING_PREFIX`, `COMPLETE_PASS`,
  `KNOWN_NONPASS_N`, or `UNSAFE/INCONSISTENT`. It must validate contiguous
  ordinals, uniqueness, exact binding, ownership, inspection, classification,
  and permitted attempt lifecycle.
- Use that validator inside command intent/start/result and terminal/recovery
  APIs. Do not rely on a service-only check.
- For result persistence, derive the durable classification from validated
  facts where possible, or strictly validate the requested classification.
  Persist result and clear exact active child identity atomically.
- Require an exact expected state for each terminal outcome and reject any
  successor after the first non-pass.
- Replace or narrow recovery service `_validate_command_evidence` so it cannot
  diverge from the store state machine. Higher-level checks for current
  manifest, approved authority, and OS/repository observations remain in the
  service.
- Define fail-closed handling for legacy attempts without sufficient bound
  command authority. Preserve rows and lease; project UNKNOWN/HUMAN_ATTENTION
  through the 4A/4D boundaries.

### 4B.6 Required adversarial tests

- For each classification `failed`, `timed_out`, `output_limited`,
  `spawn_blocked`, and `repository_mutated`, persist command N and directly
  request N+1; assert rejection and no new row.
- Repeat with `classification='passed'` but nonzero exit, timeout flag, output
  truncation, unsafe/missing/corrupt inspection, repository mismatch, control
  mismatch, incomplete output hash/bytes, or owner mismatch.
- Attempt ordinal gaps, duplicate IDs at different ordinals, changed argv/hash,
  extra commands beyond the bound list, and an early terminal ordinal.
- Attempt to overwrite an existing intent/start/result through each idempotent
  branch after the prefix becomes non-authorizing.
- Call `verified` with zero commands, a passing prefix shorter than the bound
  list, unresolved last command, non-passing earlier command, or extra row;
  assert atomic rejection and retained lease.
- Call each known failure/block outcome from an inconsistent command position;
  assert rejection.
- Seed impossible prefixes directly with SQL and run recovery. Assert no
  process observer call, no repository-based release, UNKNOWN/HUMAN_ATTENTION,
  and preserved lease/evidence.
- Seed a pre-fix attempt with only aggregate manifest hash and insufficient
  ordered binding. Assert it cannot authorize N+1 or release.
- Prove the valid multi-command path still records commands serially and can
  reach VERIFIED only after the exact last result.
- Fault every command state transition after each write and assert full
  rollback, including child identity and lease timestamp.

### 4B.7 Entry assumptions

- 4A has removed generic verification release and supplied safe normal/recovery
  transition primitives.
- Slice 1 provides canonical manifest commands and hashes.
- Slice 2 provides attempt/command tables and Slice 3 provides serial runner
  behavior and one inspection per terminated command.

### 4B.8 Exit criteria

- Direct store calls cannot create an impossible command prefix.
- Recovery and normal execution consume the same authoritative command-state
  validator.
- N+1 is impossible after any N that is not contractually passing.
- VERIFIED is impossible before the entire bound sequence passes.
- Corrupt or insufficient legacy prefixes retain ownership and fail closed.
- All 4B adversarial tests, prior Slice tests, and full validation pass.

### 4B.9 Dependencies and order

4B follows 4A. 4D follows 4B because its recovery projections must consume the
final fail-closed command-state result. 4C depends on 4B and must not expose a
production resume path to the current permissive command persistence.

## 6. Sub-slice 4D — Legacy Evidence & Recovery Projection

### 4D.1 Exact scope

4D makes all recovery projections durable, idempotent, and loss-preserving for
both current and pre-fix attempts.

It must:

1. On the first post-fix handling of any UNKNOWN attempt whose valid prior
   evidence lacks `original_unknown_evidence`, preserve an exact immutable copy
   of the pre-merge evidence before adding a recovery classification. Do not
   infer fields that were not present. Preserve corrupt raw JSON bytes/text in
   a dedicated envelope.
2. Never overwrite original repository, control-state, process ownership,
   authority, classification, or detail evidence with a later observation.
   Later observations are appended as self-contained records. Exact duplicate
   observations may be idempotently suppressed; distinct observations may not.
3. Persist `HUMAN_ATTENTION` whenever recovery observes an exactly-owned live
   verification process. Preserve the attempt as unresolved, preserve command
   and lease ownership unchanged, and record bounded ownership evidence.
4. Make live-owned, ambiguous-context, inconsistent-linkage, identity-unknown,
   changed-repository, inspection-failure, and legacy-evidence projections
   atomic with their events/evidence.
5. Ensure generic workflow/task mutation guards from 4A prevent production
   dispatch or projection overwrite while unresolved verification ownership
   remains.
6. Expose enough bounded evidence through existing status/log projections to
   distinguish live-owned, UNKNOWN, ambiguous, and interrupted outcomes without
   exposing PIDs, raw environment, secrets, or raw command output.

### 4D.2 Explicit non-goals

- Releasing UNKNOWN leases, repairing corrupt evidence by guessing, or
  converting legacy UNKNOWN to `interrupted_unchanged`.
- Re-running, signaling, adopting, or terminating a live process.
- Command-prefix legality, which 4B owns.
- Production routing/invocation behavior, which 4C owns.
- Broad V1 migration or rewriting historical non-verification records.

### 4D.3 Safety invariants and owning layer

| Invariant | Owner |
| --- | --- |
| Original UNKNOWN evidence is immutable and recoverable after every reconciliation | Store UNKNOWN merge boundary |
| Later observations append information and never replace earlier ownership/safety facts | Store recovery evidence schema/merge helper |
| Corrupt legacy evidence is preserved exactly, not discarded or normalized destructively | Store merge boundary |
| Live exactly-owned recovery persists `HUMAN_ATTENTION` and retains all ownership | Recovery service classification plus dedicated store projection transaction |
| Repeated identical recovery is idempotent; different observations remain visible | Store event/evidence de-duplication |
| Presentation is bounded and non-sensitive | Store read projections plus CLI/presentation |

### 4D.4 Existing bypass-capable APIs/functions

- `_retain_verification_unknown_unlocked` creates
  `original_unknown_evidence` only when there is no prior mapping. A valid
  pre-fix mapping without that field enters the merge branch, allowing later
  reconciliation to change top-level recovery classification without first
  freezing the original envelope.
- The same helper merges selected top-level fields and identity keys; without
  a mandatory original snapshot, historical meaning can become ambiguous.
- `_unknown_observation` omits any future field only if the remainder logic is
  correct; its canonical record is the loss-preserving append boundary and
  must be tested with unknown fields.
- `retain_verification_unknown` and
  `retain_verification_recovery_unknown` both reach the merge helper and can
  expose the legacy gap.
- `retain_ambiguous_verification_recovery` de-duplicates events by exact
  payload, while `retain_inconsistent_verification_lease` currently suppresses
  every later event of the same type regardless of distinct evidence; the
  latter can lose later observations.
- `VerificationRecoveryService.reconcile` returns immediately for
  `ALIVE_OWNED` when the attempt is still `verifying`; it persists neither the
  required workflow projection nor a recovery event.
- `set_workflow_state`, `cancel_v2_workflow`, `record_intervention`, and legacy
  task-execution mutators can overwrite or bypass the recovery projection if
  4A's unresolved-verification guard is absent.

### 4D.5 Required production changes

- Replace ad hoc top-level merging with an explicit evidence envelope, while
  retaining backward-readable fields if required by current presentation.
  At minimum it contains immutable `original_unknown_evidence` and ordered
  `recovery_observations`.
- When a valid legacy mapping lacks `original_unknown_evidence`, copy the exact
  mapping into that field before any merge. Capture its existing durable detail
  from the execution/attempt when available, clearly marking absent legacy
  fields as absent rather than synthesizing them.
- When legacy JSON is invalid or not an object, preserve its exact serialized
  value in the original envelope before appending the new observation.
- Make identity/repository/authority facts observation-local. Convenience
  top-level projections must never overwrite the immutable original.
- Add a dedicated exact-context store method for live-owned projection. It
  updates workflow status to `HUMAN_ATTENTION`, records a bounded idempotent
  event/observation, and exact-compares but does not modify the attempt,
  command, operation, execution, task state, or lease owner/child fields.
- Change inconsistent/ambiguous event de-duplication to suppress only an exact
  duplicate canonical observation, not all future events of the type.
- Update bounded status/log read models for recovery classification and lease
  retention without exposing process IDs.

### 4D.6 Required adversarial tests

- Seed a valid pre-fix UNKNOWN mapping without
  `original_unknown_evidence`; reconcile with dead/unchanged, live-owned,
  changed, and ambiguous observations. Assert the exact pre-merge mapping is
  immutable and every later observation is self-contained.
- Seed corrupt JSON, a JSON scalar/list, malformed `recovery_observations`,
  partial identity, unknown future fields, and conflicting later values. Assert
  no original byte/value is lost.
- Repeat identical recovery and assert no duplicate observation/event; then
  change one material observation field and assert the distinct observation is
  retained.
- Observe `ALIVE_OWNED` on a `verifying` attempt. Assert workflow
  `HUMAN_ATTENTION`, bounded event/evidence, unchanged attempt/command/lease,
  and no signal or dispatch.
- Repeat live-owned recovery and assert idempotence. Inject failures after the
  workflow update, evidence write, and event write; assert total rollback.
- Run generic state, cancellation, intervention, and legacy task-operation
  APIs after live-owned projection; assert they cannot leave
  `HUMAN_ATTENTION` or mutate ownership.
- Verify status/log output distinguishes retained UNKNOWN/live/ambiguous cases
  without PID, process start, raw output, or secret values.

### 4D.7 Entry assumptions

- 4A enforces lease retention, exact projection transactions, and guards
  generic workflow/task mutations.
- 4B returns a single fail-closed command-state classification for recovery.
- Existing databases may contain Slice 3 or earlier Slice 4 UNKNOWN evidence
  without the new envelope.

### 4D.8 Exit criteria

- Every old or new UNKNOWN attempt has a loss-preserving original envelope
  after first post-fix reconciliation.
- No recovery merge overwrites original evidence.
- Live-owned recovery durably yields `HUMAN_ATTENTION` without changing or
  releasing ownership.
- Ambiguous and distinct repeated observations remain auditable; exact repeats
  are idempotent.
- Bounded status/log projections expose classification and retention state but
  no sensitive process evidence.
- All 4D adversarial tests, prior Slice tests, and full validation pass.

### 4D.9 Dependencies and order

4D follows 4A and 4B. It precedes 4C because production routing must not expose
the current non-persisting live-owned branch or lossy legacy merge.

## 7. Sub-slice 4C — Recovery Production Integration

### 4C.1 Exact scope

4C connects the hardened verification boundaries to the real MDS #3
implementation/resume path through one composed task coordinator.

It must:

1. Introduce or extend one coordinator that owns the MDS #4 composed
   invocation. The coordinator, not the CLI, sequences pre-IMPLEMENT
   verification configuration validation, MDS #3 implementation, durable
   producer reload, VERIFY, and recovery boundaries.
2. At the very start of every task-execution invocation, detect unresolved
   verification ownership from the store and call
   `VerificationRecoveryService.reconcile`. If reconciliation returns any
   outcome, reload persisted workflow state and return immediately. It must not
   create a fresh verification attempt or dispatch any writer/command/reviewer
   in that invocation.
3. Before IMPLEMENT dispatch, validate the tracked manifest/configuration and
   runner availability required by the authoritative design. A failed
   verification preflight blocks IMPLEMENT. Preserve the MDS #3 rule that the
   implementation gateway remains the sole mutation gate.
4. After MDS #3 returns `completed_changed`, reread the durable successful
   producer and approved authority, revalidate the unchanged manifest, build
   the full verification preflight, and invoke
   `DeterministicVerificationOrchestrator.run` in the same invocation. Never
   trust only the in-memory writer result.
5. When an invocation begins at an unambiguous persisted
   `IMPLEMENTATION_COMPLETED` boundary with no unresolved verification lease,
   run the same durable revalidation and begin VERIFY without dispatching a new
   IMPLEMENT.
6. Stop after every VERIFY terminal or UNKNOWN outcome. MDS #4 must not enter
   REVIEW, FIX, next task, task acceptance, commit, push, PR, or the older
   agent-based Wave 2 task loop.
7. Route CLI `resume` for active verification ownership, VERIFYING,
   `IMPLEMENTATION_COMPLETED`, VERIFICATION_FAILED, TASK_VERIFIED, and
   verification HUMAN_ATTENTION states through the composed coordinator or
   return their persisted boundary as appropriate. It must not fall through to
   `PlanningOrchestrator._resume_task_execution`.
8. Preserve the single explicit start interaction and display the bound
   verification command IDs/argv before mutation. There is no post-IMPLEMENT
   confirmation.

### 4C.2 Explicit non-goals

- Changing the lower persistence, command state machine, recovery evidence, or
  process classification rules established by 4A/4B/4D.
- Adding automatic retry after interruption/failure/UNKNOWN.
- REVIEW, FIX, task dependency completion, next-task selection, generalized
  Wave 2 migration, or model-based verification.
- Multiple tasks, parallel verification, arbitrary shell commands, commit,
  push, PR, rollback, stash, reset, or cleanup.

### 4C.3 Safety invariants and owning layer

| Invariant | Owner |
| --- | --- |
| Recovery is the first task-execution action when unresolved VERIFY ownership exists | Composed task coordinator |
| A recovery invocation performs reconciliation only and then returns | Composed task coordinator control flow |
| IMPLEMENT cannot start unless verification configuration preflight passes | Composed coordinator before calling MDS #3 gateway |
| VERIFY starts only from reloaded durable `completed_changed` producer authority | Composed coordinator plus existing preflight/store loaders |
| Persisted `IMPLEMENTATION_COMPLETED` resumes VERIFY, not IMPLEMENT or legacy task execution | Composed coordinator and CLI routing |
| Every VERIFY outcome stops MDS #4 with no successor phase | Composed coordinator |
| CLI selects the coordinator but never owns safety decisions | CLI routing |

### 4C.4 Existing bypass-capable APIs/functions

- `cli._continue_approved_implementation` currently constructs
  `ImplementationAttemptOrchestrator`, runs it once, reloads the workflow, and
  never invokes deterministic verification or verification recovery.
- CLI `resume` selects that helper only for `PLAN_APPROVED`,
  `IMPLEMENTATION_FAILED`, or an active implementation lease. Active
  verification leases, `VERIFYING`, `IMPLEMENTATION_COMPLETED`, and
  verification-specific `HUMAN_ATTENTION` currently fall through elsewhere.
- `ImplementationAttemptOrchestrator.run_once` reconciles only implementation
  leases. On successful implementation it persists `completed_changed` and
  returns without VERIFY.
- `PlanningOrchestrator.resume` routes `TASK_EXECUTION` to
  `_resume_task_execution`, which reconciles legacy task operations, selects a
  task, and can dispatch agent DEVELOP/REVIEW/FIX work. This is not the MDS #4
  recovery or verification path.
- `DeterministicVerificationOrchestrator.run` is callable in tests but has no
  production call site.
- `VerificationRecoveryService.reconcile` is likewise not invoked from the
  production CLI/coordinator path.
- `ImplementationSelectionOrchestrator.select_once` can select work if called
  without the composed coordinator's verification-first guard.

### 4C.5 Required production changes

- Add a composed MDS #4 task coordinator or evolve the MDS #3 gateway behind a
  new composition API. Keep MDS #3 implementation internals focused on one
  writer attempt; do not hide verification inside the writer adapter.
- Give the coordinator explicit dependencies for manifest resolver/preflight,
  implementation gateway, verification recovery service, verification
  orchestrator, store, and presentation/progress hooks so integration tests can
  prove zero dispatch.
- Add a store query that classifies the task-execution boundary without
  mutating it: unresolved implementation lease, unresolved verification lease,
  persisted implementation completion awaiting verification, or stable
  terminal verification boundary. The coordinator must reject ambiguous
  combinations.
- Perform pre-IMPLEMENT manifest resolution and runner/configuration checks,
  then pass/bind that exact configuration through the composed flow. After
  implementation, construct full `VerificationPreflight` only from reloaded
  durable producer authority and prove the manifest is unchanged.
- Replace `_continue_approved_implementation` with the composed coordinator
  call and update CLI routing to recognize verification boundaries regardless
  of workflow projection corruption/lag by consulting durable ownership.
- Ensure the coordinator returns immediately after any implementation or
  verification reconciliation result, any non-success implementation result,
  and every verification result.
- Update the implementation-start presentation to show ordered command IDs and
  argv and state that successful IMPLEMENT automatically runs VERIFY.
- Keep status/exit-code classification based on reloaded persisted workflow
  state, not coordinator return guesses.

### 4C.6 Required adversarial tests

- CLI `resume` with an active unresolved verification command invokes recovery
  once and invokes no implementation writer, verification runner, task agent,
  reviewer, FIX, or selector.
- Repeat for every recovery outcome: live-owned, dead/unchanged,
  dead/changed, PID reused, host/boot mismatch, incomplete identity,
  inspection failure, corrupt prefix, zero/multiple contexts, and persistence
  failure. Every invocation stops.
- Dead/unchanged reconciliation terminalizes and returns. A second explicit
  `resume`, not the same invocation, may create one fresh attempt.
- A workflow beginning at persisted `IMPLEMENTATION_COMPLETED` starts VERIFY
  without a writer call and stops after its outcome.
- A normal PLAN_APPROVED invocation resolves/displays configuration before the
  writer, persists completed implementation, reloads producer authority, then
  runs VERIFY in the same invocation.
- Invalid/untracked/changed manifest or unavailable runner before IMPLEMENT
  produces the designed blocked/HUMAN_ATTENTION boundary and zero writer calls.
- Change manifest, approved authority, producer result, repository identity,
  or task binding after IMPLEMENT completion and before VERIFY; assert no
  command spawn and fail-closed projection.
- Crash/fault after implementation terminal persistence but before verification
  intent; later resume enters VERIFY from durable producer evidence.
- Crash/fault after verification intent; later resume reconciles only and does
  not redispatch.
- For VERIFIED, VERIFICATION_FAILED, VERIFICATION_BLOCKED,
  INTERRUPTED_UNCHANGED, and VERIFICATION_UNKNOWN, assert no REVIEW/FIX/next
  task/acceptance and no legacy `_resume_task_execution` call.
- Verify CLI JSON/non-JSON paths and selected-workflow behavior use the same
  coordinator and persisted exit classification.
- Verify the single pre-IMPLEMENT prompt/presentation includes ordered IDs/argv
  and that no post-IMPLEMENT prompt exists.

### 4C.7 Entry assumptions

- 4A proves exact release and atomic retention.
- 4B proves legal command prefixes and terminal outcomes.
- 4D proves loss-preserving evidence and durable live-owned
  `HUMAN_ATTENTION`.
- Existing MDS #3 implementation selection, mutation gate, successful producer
  loader, and post-implementation repository evidence remain authoritative.

### 4C.8 Exit criteria

- Both recovery and deterministic verification have real production call sites
  through one composed coordinator.
- Every unresolved verification invocation reconciles and returns without any
  dispatch.
- Successful IMPLEMENT automatically enters VERIFY only after durable producer
  revalidation; persisted `IMPLEMENTATION_COMPLETED` resumes the same path.
- No MDS #4 outcome can fall into the legacy task agent loop or a successor
  phase.
- CLI integration/adversarial tests, all Slice 1–4 tests, and full validation
  pass.

### 4C.9 Dependencies and order

4C depends on 4A, 4B, and 4D and is last. It is the only sub-slice that makes
the hardened recovery path production-reachable.

## 8. Cross-sub-slice acceptance and review boundaries

Each sub-slice requires its own focused implementation/review cycle. Passing a
later slice must not be used to waive a lower-boundary failure.

For every sub-slice:

- preserve the approved MDS #4 outcome and no-successor semantics;
- add focused adversarial tests before relying on happy-path integration;
- run the affected Slice 1–4 tests and then
  `.venv/bin/python3 -m unittest discover -s tests -q`;
- inspect the final changed-file list to ensure no unrelated workflow surface
  changed; and
- independently review the implementation against this decomposition and the
  authoritative design.

The release-level proof after 4C is:

1. No caller can release retained UNKNOWN ownership.
2. No caller can persist or recover an impossible command prefix.
3. Recovery never dispatches in its classifying invocation.
4. Ambiguous or legacy evidence fails closed without loss.
5. Every recovery projection and terminal transition is atomic.
6. The actual CLI path reaches these boundaries and cannot fall into legacy
   task execution or a successor phase.

## 9. Candidate-boundary decision

No repository evidence requires changing the four candidate boundaries.

One ordering adjustment is required: **4D must precede 4C**, even though its
label sorts after 4C, because production integration must not expose the
current live-owned non-projection or legacy evidence-loss gap. The final order
is **4A -> 4B -> 4D -> 4C**.
