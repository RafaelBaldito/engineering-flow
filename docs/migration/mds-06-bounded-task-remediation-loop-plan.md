# Engineering Flow V2 — MDS #6 Bounded Task Remediation Loop Plan

## 1. Status, proposal, and boundary

**Proposal status: AWAITING HUMAN APPROVAL.** This is a planning artifact. It
does not change production code, tests, configuration, persisted data, or Git
history.

The proposed MDS #6 is **Bounded Task Remediation Loop**. It owns the smallest
closed capability missing after MDS #5: safely remediate one immutable,
blocking independent-review result, deterministically validate the mutation,
and obtain a fresh independent review of the repaired repository.

It is deliberately not called merely “FIX.” A write-only Fix step cannot prove
that a finding was resolved; allowing the Fixer to declare success would weaken
the MDS #4 verification and MDS #5 independence boundaries. The smallest
coherent outcome is therefore:

```text
TASK_CHANGES_REQUESTED
  -> FIXING -> FIX_COMPLETED -> VERIFYING
  -> TASK_VERIFIED -> REVIEWING
  -> TASK_REVIEW_PASSED | TASK_CHANGES_REQUESTED | HUMAN_ATTENTION
```

`FIX_COMPLETED` is an operational attempt outcome, not a public task-success
state. The normal Fix invocation runs deterministic VERIFY after durable Fix
completion, as MDS #4 runs VERIFY after durable IMPLEMENT completion. A later,
explicit `resume` starts a new independent REVIEW from `TASK_VERIFIED`; REVIEW
is not appended to the writer invocation. This retains a durable provider
boundary and guarantees the Reviewer never shares a live Fixer session.

The initial MDS #6 policy is intentionally bounded: a review decision consumes
one review cycle; each `CHANGES_REQUESTED` decision below the configured review
limit authorizes exactly one Fix attempt. A post-Fix deterministic verification
failure, a failed/unchanged Fix, an interruption, drift, malformed evidence, or
any ambiguity stops at `HUMAN_ATTENTION`; it does not silently retry a Fix.
This makes `execution.max_review_cycles` an effective, existing upper bound on
normal review/Fix rounds without introducing a second retry policy.

Stopping after a post-Fix VERIFY failure is a deliberate MDS #6 simplification,
**not** a permanent architectural restriction. A later, separately approved
milestone may add bounded, evidence-based retries within the same remediation
cycle. MDS #6 preserves the provenance and attempt boundaries that such a
policy needs, but neither reads nor implements that policy.

## 2. Why this is the correct next milestone

The approved product contract requires a sequential implementation, required
tests, independent review, and remediation loop, with a mandatory review/fix
limit (FR-009 and FR-011–FR-016). MDS #4 explicitly reserved successful
verification as authority for REVIEW rather than dependency release, and bound
verification to a generic producer operation so a future FIX can be reverified.
MDS #5 now persists immutable ordered findings and stops at
`TASK_CHANGES_REQUESTED`; it expressly excludes FIX, acceptance, release of a
dependency, and successor selection.

Thus remediation is the next unowned successor. Adding task acceptance or a
second task now would conflate three independently auditable facts: a Fixer
mutated a checkout, deterministic commands passed, and an independent Reviewer
accepted the task. Extending MDS #6 to dependency scheduling or feature-level
progress would also turn a one-task safety loop into a high-complexity recovery
and selection milestone. Those remain later work.

The historical V1 task/cycle/Fix records remain compatibility evidence only.
MDS #6 must extend the V2 operational records introduced by MDS #3–#5; it must
not import, reinterpret, or route through the legacy loop.

## 3. Lifecycle and exact loop

### 3.1 Normal lifecycle

```text
IMPLEMENT -> VERIFY -> TASK_VERIFIED -> REVIEW
                                      |       \
                                      |        +-> TASK_REVIEW_PASSED (STOP)
                                      v
                         TASK_CHANGES_REQUESTED
                                      |
                                      | resume: one durable FIX intent/dispatch
                                      v
                                   FIXING
                                      |
                         completed + protected state valid
                                      v
                              FIX_COMPLETED
                                      |
                          same invocation, no new writer
                                      v
                                  VERIFYING
                              /               \
                 verification passed           failed/blocked/unknown
                           |                         |
                           v                         v
                     TASK_VERIFIED              HUMAN_ATTENTION (STOP)
                           |
                 later explicit resume only
                           v
                  fresh independent REVIEW
                    /                  \
       TASK_REVIEW_PASSED                TASK_CHANGES_REQUESTED
             (STOP)                       (next allowed round or limit)
```

There is no direct `FIX -> REVIEW`, no `FIX -> TASK_REVIEW_PASSED`, and no
`TASK_CHANGES_REQUESTED -> TASK_VERIFIED`. A passing deterministic VERIFY
establishes only eligibility for a new REVIEW. A later Reviewer decision alone
can create `TASK_REVIEW_PASSED`.

### 3.2 Iteration policy

* The already-persisted first Review has `review_cycle=1`. Every subsequently
  dispatched independent Review increments the cycle only at its durable
  intent, never from an inferred result.
* `max_review_cycles` is read from the validated existing configuration and is
  frozen into each Review/Fix round evidence. If a `CHANGES_REQUESTED` result
  is at the limit, project `HUMAN_ATTENTION` with the retained findings; create
  no Fix intent.
* For a below-limit `CHANGES_REQUESTED` review, exactly one Fix intent may be
  created for that source review. Its idempotency key contains the source
  review-attempt ID and source-result hash. A repeated `resume` cannot create
  a second Fix for those findings.
* The MDS #6 Fix attempt is ordinal 1 within its source-review remediation
  cycle. It either reaches `FIX_COMPLETED` and enters VERIFY, or reaches a
  durable stop. There is no automatic or operator-triggered retry within MDS
  #6. This is a deliberate scope boundary, not an error being silently treated
  as success; a later bounded retry policy may create ordinal 2 only under its
  own explicit eligibility and limit rules.
* A new `CHANGES_REQUESTED` result after re-review is a new frozen source
  review and, only if below the limit, authorizes one new round.

This is a bounded `REVIEW -> FIX -> VERIFY -> REVIEW` loop. It has at most
`max_review_cycles - 1` normal Fixes after the first review, and all provider
dispatches remain explicit invocation boundaries except the deterministic
post-Fix verification commands.

### 3.3 Future bounded retry evolution (explicitly deferred)

Two different loops must remain distinct in the model, policy, evidence, and
operator presentation:

```text
Review remediation cycles (MDS #6 supports this first loop only):
REVIEW -> CHANGES_REQUESTED -> FIX -> VERIFY -> REVIEW

Fix retries within one remediation cycle (future only):
FIX -> VERIFY_FAILED -> FIX -> VERIFY -> ...
```

The first loop creates a new immutable Review result and, when that result is
again `CHANGES_REQUESTED`, a new review-cycle source. The second loop retains
the *same* immutable source Review result and retries a Fix only after a known,
eligible failed verification of the prior Fix. It must not manufacture a new
review cycle, mutate findings, or treat verification failure as review pass.

A future policy may introduce, at minimum, `max_review_cycles`,
`max_fix_attempts_per_review_cycle`, and `retry_on_verification_failure`. It
must freeze the effective policy snapshot and both counters into each Fix/VERIFY
attempt, define exactly which verified failure classifications are retryable,
and keep blocked, unknown, drifted, interrupted, malformed, and
ownership-ambiguous outcomes fail-closed unless a separate policy explicitly
and safely handles them. The second loop is out of scope for MDS #6: there is
no automatic or operator-triggered Fix retry after `VERIFY_FAILED` here.

## 4. Authority and evidence

### 4.1 Fix entry predicate

`FixContinuationService.continue_once(workflow_id)` may create a Fix intent
only after it transactionally revalidates all of the following:

1. The V2 workflow is in `task_execution/task_changes_requested`, not a
   planning-level `changes_requested`, cancelled, failed, or human-attention
   projection.
2. The exact current approved Feature Contract, Plan artifact, approval, Task
   Contract ID, and canonical Task Contract SHA all match MDS #3 authority.
3. Exactly one terminal source `review_attempt` belongs to that task and has
   `CHANGES_REQUESTED`, matching authority, verified producer, verification
   evidence, reviewed repository fingerprint, and immutable result hash.
4. Its durable ordered findings still exist, are immutable, and contain at
   least one blocking finding. The source Review is the current unresolved
   review round; a pass, a different task, stale evidence, or two candidates
   is ambiguity and fails closed.
5. The review-cycle limit has not been reached and no Fix attempt already
   exists for this exact source review/result binding.
6. The repository still equals the source Review's verified fingerprint and
   protected control fingerprint; the tracked verification manifest and its
   canonical commands remain exactly bound and usable before any write intent.
7. A common workspace-operation lease is available for the exact canonical
   repository identity. No unresolved IMPLEMENT, VERIFY, or FIX lease can be
   stolen, timed out, or replaced.

The preflight resolver is read-only; the store repeats the durable predicates
inside `BEGIN IMMEDIATE` while writing the intent and lease. The orchestrator
rereads immutable authority and re-inspects the repository immediately before
provider spawn. Any mismatch produces no provider call.

### 4.2 What the Fixer receives

The Fixer is `Role.DEVELOPER` with `WorkKind.FIX`, workspace-write only, and
gets the smallest sufficient bounded input bundle:

* the hash-verified Feature Contract and exact Task Contract;
* the source Review attempt/result identity and its ordered immutable findings;
* the source verified IMPLEMENT/FIX producer and deterministic verification
  evidence, including the fixed manifest command identities, not raw
  transcript authority;
* the source review Git diff, relevant Task Contract files/patterns, and
  repository rules; and
* a strict Fix-result schema.

The canonical Fix result should contain only a non-empty summary and the exact
ordered IDs of the source **blocking** findings claimed addressed. Its set and
order must exactly match the persisted source blocking findings. This validates
that the Fixer consumed the complete authoritative request, but is advisory
provider evidence—not a finding disposition, task acceptance, or proof of
correctness. Advisory findings are supplied for context and remain visible;
they are not silently erased.

### 4.3 Session decision

Use **Developer continuity when it is safely available**, not a distinct
“Fixer” role or a Reviewer session. The Fix execution is a fresh durable
execution/operation and has a new request hash, but it may resume the exact
original Developer provider session only when the provider advertises the
existing safe Developer-resume mechanism and the persisted original Developer
session is exactly bound to the same task and producer lineage. This satisfies
FR-013 without granting trust to ephemeral conversation state.

The persisted bounded bundle above is authoritative in every case. If provider
resume is unavailable, stale, or incompatible, dispatch a fresh Developer
session with that bundle; do not fail open, borrow a Reviewer session, or
replay unbounded history. The Reviewer after verification always uses a new,
distinct, read-only logical/provider session with no Developer continuity.

### 4.4 Independent proof of resolution

The system proves only this chain, in order:

```text
immutable source findings
  -> source-review binding on one Fix intent
  -> changed repository evidence from that Fix
  -> deterministic bound commands passing against that producer
  -> fresh Reviewer re-evaluates task + diff + prior findings
```

The Fixer never writes review findings, review disposition, `verified`,
`review_passed`, acceptance, dependency state, or a successor selection. The
second Reviewer does not accept the Fixer's claim; it independently reviews the
Task Contract and repaired repository. A `REVIEW_PASSED` result still means no
findings under MDS #5's strict result contract. Any remaining issue must be a
new durable `CHANGES_REQUESTED` result, tied to its own review round.

## 5. Durable model and schema changes

All changes are additive V2 persistence. Existing MDS #3–#5 rows and their
meaning remain intact.

| Record/change | Required durable contents and rule |
| --- | --- |
| `fix_attempts` | UUID; workflow/Plan/Task identities and hashes; source review attempt ID, source reviewer-result SHA, source verified producer operation ID and verification attempt/evidence hashes; remediation-cycle ordinal and Fix-attempt ordinal; frozen review-cycle/config-policy value; request hash; generic operation/execution/session IDs; lease ID; baseline/final repository and protected-control fingerprints; status/outcome, provider result hash, timestamps, abnormal evidence. Uniqueness is `(source_review_attempt_id, source_reviewer_result_sha256, fix_attempt_ordinal)`, not the source review alone. MDS #6 permits only ordinal 1; the shape reserves later bounded retries without weakening MDS #6 idempotency. |
| `fix_attempt_finding_bindings` | One immutable ordered row for every source finding, referencing its immutable `review_findings` row and recording its source ordinal/ID and canonical finding hash. It proves precisely which review evidence the Fix consumed without making a mutable copy authoritative. A constraint/projection requires all source blocking findings. |
| Generic `operations` / `executions` | Add a V2 `fix` operation only; its execution is Developer/FIX, its request hash equals the attempt binding, and its terminal provider result is bounded/sanitized. Existing operation semantics remain unchanged. |
| Common lease | Reuse `workspace_operation_leases` with `operation_kind='fix'`. Its ownership, child identity, exact delete predicate, and UNKNOWN retention must be equivalent to IMPLEMENT/VERIFY, never a new parallel lease protocol. |
| Task/workflow projections | Add only the explicit `fixing` task/workflow projection and, if needed for faithful observation, `fix_completed` as an internal attempt outcome rather than a dependency state. Reuse `verifying`, `verified`, `reviewing`, `review_passed`, and `changes_requested`. Add no accepted/dependency-ready state. |
| Review-round and retry counters | Prefer store-derived counts over mutable counters: count exact V2 terminal normal review attempts for the task and Fix attempts for the exact source-review/result binding. Bind the computed review-cycle, Fix-attempt ordinal, and effective policy snapshot in source/Fix/VERIFY evidence. MDS #6 validates review-cycle policy and requires Fix ordinal 1; it does not evaluate retry policy. |
| Events/read models | Add sanitized `fix.attempt.created`, `fix.attempt.completed`, `fix.attempt.abnormal`, and `fix.verification.started`/handoff events. Project source finding IDs, attempt IDs, cycle/limit, result hashes, classifications, and safe fingerprints—never raw provider transcripts, environment, or secrets. |

The existing verification attempt must be generalized only at its producer
binding seam: it may consume an exact successful `implementation` **or** `fix`
operation with the same task/Plan/authority/repository linkage. It must not
relax MDS #4 command-manifest, sequence, inspection, lease, or terminal
`VERIFIED` predicates. Reverification gets a new verification attempt and never
overwrites the first one.

Each verification attempt must retain the exact producer operation and, for a
Fix producer, its Fix attempt ID and source-review binding through normal joins.
Thus a later retry policy can prove `source review -> Fix ordinal N -> VERIFY`
without relabeling or overwriting any prior attempt. `HUMAN_ATTENTION` remains
the MDS #6 projection for a failed post-Fix VERIFY; it is not persisted as a
claim that a retry is impossible.

## 6. Failure and recovery matrix

| Boundary/observation | Durable outcome | Resume behavior | Dispatch/release rule |
| --- | --- | --- | --- |
| Authority, source findings, limit, manifest, baseline, or lease unavailable before intent | no Fix attempt; safe conflict or human-attention evidence when reconciliation is needed | no automatic action | no writer, verifier, or reviewer dispatch |
| Intent transaction fails | rollback all attempt/operation/execution/lease/event writes | later explicit invocation starts from unchanged source state | no dispatch |
| Intent exists before spawn; owner/child definitely dead and baseline/control state exactly unchanged | recovery classifies the Fix as interrupted/unchanged and projects `HUMAN_ATTENTION` for this MDS | recovery only; no retry | release only in the same exact recovery transaction after durable proof |
| Live, reused, foreign, incomplete, or unobservable writer identity; repository/control drift; corrupt linkage | sticky unknown / `HUMAN_ATTENTION` | recovery is idempotent and only records evidence | retain lease; no signal, steal, retry, or successor |
| Known Fix provider failure with proven unchanged baseline | `HUMAN_ATTENTION` with bounded failure evidence | stop | release only as exact normal terminal result; no hidden retry |
| Fix returns malformed result, changes protected manifest/control state, changes refs/branch, or post-Fix inspection is unavailable | `HUMAN_ATTENTION` | stop | retain lease when ownership/state is uncertain; otherwise classify atomically; never VERIFY |
| Fix completes and repository evidence is valid | durable `FIX_COMPLETED`, then deterministic VERIFY starts in same invocation | VERIFY path is normal MDS #4 machinery with Fix as producer | Fix lease handoff/release and verification lease acquisition must be atomic/ordered so no second writer can enter |
| Post-Fix VERIFY passes | `TASK_VERIFIED` | only a later explicit `resume` can dispatch fresh REVIEW | no Fixer or verifier self-approval |
| Post-Fix VERIFY fails, blocks, interrupts, or is unknown | preserve MDS #4 classification plus `HUMAN_ATTENTION` for MDS #6 boundary | recovery only where MDS #4 permits; no new Fix under this milestone | MDS #4 UNKNOWN/lease rules unchanged; retain producer/source/ordinal evidence for a future bounded retry policy |
| Re-review runtime failure/interruption/drift/ambiguity | existing MDS #5 `REVIEW_FAILED`/`HUMAN_ATTENTION` behavior | its recovery only; no Fix | no duplicate Reviewer dispatch |
| Re-review changes requested below limit | new immutable review round and `TASK_CHANGES_REQUESTED` | later explicit resume may begin exactly one next Fix | no same-invocation Fix |
| Re-review changes requested at limit | `HUMAN_ATTENTION` retaining findings | explicit human intervention required | no Fix or successor |

Recovery is an observation-and-projection operation, never a dispatch path. It
must use the established process-identity and repository-inspection evidence,
be idempotent, preserve raw historical abnormal evidence losslessly, and fail
closed. It must not kill a process, use TTL lease stealing, reset/stash the
worktree, or use a recovery invocation to continue VERIFY, REVIEW, or another
Fix.

## 7. Small implementation slices

No slice below is high complexity. In particular, writer recovery is isolated
from initial execution and from CLI reachability because MDS #4 showed that a
large recovery slice is unsafe.

### Slice 1 — FIX authority, finding binding, and result contract

* **Objective:** Define a pure, fail-closed source-review-to-Fix preflight and
  strict provider evidence schema.
* **Production scope:** `domain.py`; a focused `fix.py` resolver/value objects;
  read-only store projections; narrow runtime request validation for
  Developer/FIX routing and profile selection.
* **Tests:** exact source-review/finding/hash/Task bindings; stale or duplicate
  sources; planning-vs-task changes-requested distinction; cycle-limit boundary;
  strict result parsing; safe path and duplicate finding-ID rejection; no store
  writes or provider calls.
* **Explicit boundaries:** no schema migration, intent, lease, subprocess,
  verification, recovery, CLI, acceptance, or scheduling.
* **Complexity:** low.
* **Dependencies:** MDS #3–#5 only.

### Slice 2 — durable Fix intent, immutable provenance, and legal transitions

* **Objective:** Atomically persist one bound Fix intent and the one-writer
  lifecycle projection without executing a provider.
* **Production scope:** additive schema/migration and `WorkflowStore` methods
  for `fix_attempts`, finding-binding rows, generic operation/execution/session
  linkage, common Fix lease acquisition, idempotency, and
  `TASK_CHANGES_REQUESTED -> FIXING` transition.
* **Tests:** one source review creates one exact intent; every blocking finding
  is bound; altered/deleted/foreign findings fail; duplicate resumes reuse or
  conflict without a second lease; source at cycle limit cannot create intent;
  transaction fault injection rolls back all rows/projections/events.
* **Explicit boundaries:** no provider dispatch, post-Fix state, verification,
  recovery, CLI, task acceptance, or next task.
* **Complexity:** medium.
* **Dependencies:** Slice 1.

### Slice 3 — one workspace-write Fix execution and normal terminal evidence

* **Objective:** Execute exactly one new Developer/FIX request from a durable
  intent and record only a proven normal completed-Fix result.
* **Production scope:** `FixAttemptOrchestrator`; bounded inputs/instruction;
  safe Developer-continuity-or-fresh-session selection; pre/post repository and
  protected-control inspections; provider child ownership; strict result
  validation; normal lease completion/handoff preparation.
* **Tests:** exactly one dispatch; Developer/FIX workspace-write and no Reviewer
  reuse; continuity only for exact advertised Developer lineage; fresh fallback;
  source findings in request; no self-approval; pre/post drift/ref/manifest
  violations; intent before side effect; no duplicate dispatch.
* **Explicit boundaries:** known/unknown interruption recovery, VERIFY routing,
  REVIEW routing, retries, CLI, and task acceptance.
* **Complexity:** medium.
* **Dependencies:** Slices 1–2.

### Slice 4 — Fix abnormal outcomes and recovery safety

* **Objective:** Make unresolved/abnormal FIX ownership safe before any CLI
  continuation can reach it.
* **Production scope:** `FixRecoveryService` and recovery-specific store
  transitions using the existing common-lease/process-identity discipline;
  abnormal evidence envelopes and sticky unknown handling.
* **Tests:** interruption at each durable boundary; live/dead/reused/foreign
  process identity; changed/unreadable repository; corrupt joins; exact normal
  release versus UNKNOWN retention; repeated recovery; fault rollback; mocks
  proving recovery dispatches no Fixer/verifier/reviewer/successor.
* **Explicit boundaries:** process killing, TTL/lease stealing, retries,
  post-Fix verification, CLI routing, cleanup/reset/stash, acceptance.
* **Complexity:** medium.
* **Dependencies:** Slices 2–3.

### Slice 5 — deterministic post-Fix verification and independent re-review handoff

* **Objective:** Compose the only normal remediation loop without weakening
  MDS #4 or MDS #5.
* **Production scope:** generalize the existing producer-operation loader to
  accept a successful exact Fix producer; invoke deterministic verification
  after durable Fix completion; preserve its command/lease/evidence rules;
  expose `TASK_VERIFIED` solely as the later fresh-review entry; enforce the
  review-round limit at review intent/result projection.
* **Tests:** `FIX -> VERIFY` uses a new verification attempt bound to the Fix
  operation; pass requires a later fresh Reviewer invocation; reviewer session
  remains distinct; post-Fix verification failures stop; re-review pass and
  changes-requested paths; limit stops before a next Fix; no acceptance or
  dependency release.
* **Explicit boundaries:** no repair/retry after verification failure, no same-
  invocation re-review, no review-result mutation/disposition UI, multi-task
  selection, or acceptance.
* **Complexity:** medium.
* **Dependencies:** Slices 1–4 and existing MDS #4/#5 recovery contracts.

### Slice 6 — V2 continuation, status, logs, and presentation

* **Objective:** Route explicit V2 continuation through durable MDS #6
  boundaries and make the remediation trail observable.
* **Production scope:** `cli.py`, `presentation.py`, payload/read models, and
  continuation service. `resume` from `TASK_CHANGES_REQUESTED` dispatches at
  most one Fix; active/uncertain Fix routes to recovery only; `TASK_VERIFIED`
  retains MDS #5's separate REVIEW route.
* **Tests:** human and JSON status/logs show source review, finding IDs,
  cycle/limit, Fix and verification outcome, without transcripts/secrets/PIDs;
  noninteractive does not prompt; every recovery route has zero dispatch;
  existing MDS #1–#5 CLI routes remain unchanged.
* **Explicit boundaries:** CLI does not authorize state changes; no finding
  edit/waive action, approval/acceptance, next task, delivery action, or
  automatic retry.
* **Complexity:** low.
* **Dependencies:** Slices 2–5.

### Slice 7 — vertical acceptance and invariant regression

* **Objective:** Prove one bounded MDS #6 loop and non-regression of predecessor
  safety boundaries.
* **Production scope:** focused disposable-repository integration tests, CLI
  tests, and any required manual-acceptance evidence; no new runtime behavior.
* **Tests:** original review changes -> Fix -> passing verification -> fresh
  review pass; repeat changes within limit; limit reached; every abnormal matrix
  stop; immutable finding provenance; no self-approval; idempotency; recovery
  zero-dispatch; full test suite.
* **Explicit boundaries:** no additional lifecycle capability, refactor, or
  task/Wave/release delivery implementation.
* **Complexity:** medium.
* **Dependencies:** Slices 1–6.

## 8. Core invariants

1. Only task-level `TASK_CHANGES_REQUESTED`, never Plan feedback
   `changes_requested`, is an MDS #6 Fix authority.
2. A Fix consumes one exact immutable source Review result and ordered finding
   set; caller-provided finding text, IDs, hashes, or task payload never become
   authority.
3. A source review result can authorize no more than one Fix intent, and a
   provider dispatch is preceded by durable intent and exact lease ownership.
4. Only Developer/FIX receives workspace-write; Reviewer remains fresh,
   distinct, read-only, and unable to resume Developer continuity.
5. The Fixer cannot mark verification, review pass, acceptance, dependencies,
   or a successor state. Its claimed addressed IDs are evidence, not approval.
6. Post-Fix verification uses the unchanged MDS #4 tracked manifest, ordered
   argv, controlled runner, command evidence, and terminal-success rules.
7. A new Reviewer after a passing Fix verification is the only normal proof of
   resolution; it rechecks the Task Contract rather than trusting a disposition.
8. `max_review_cycles` is enforced from durable review evidence before a Fix
   intent and before a new Review intent. MDS #6 permits Fix-attempt ordinal 1
   only; no retries are implicit. Its source-review and ordinal evidence is
   deliberately sufficient for a future separately bounded retry policy.
9. Any uncertain writer ownership, repository/control drift, corrupted
   authority/evidence, or ambiguous recovery is sticky, observable, and fails
   closed; it cannot dispatch, release, or replace work.
10. Intent, attempt/execution/operation, lease, projections, evidence, and
    event updates are atomic at each transition. Exact request hashes and
    idempotency keys prevent duplicate dispatch.
11. Recovery observes and persists only. It never dispatches, kills, steals,
    cleans, retries, verifies, reviews, accepts, or schedules work.

## 9. CLI, status, and logs

`engineering-flow resume` has these MDS #6-specific meanings only:

| Persisted V2 state | Required behavior |
| --- | --- |
| `task_changes_requested`, below limit, coherent source review | preflight then one Fix dispatch; normal successful Fix composes deterministic VERIFY only |
| `fixing` or retained unresolved Fix | recovery only; zero provider dispatch |
| `task_verified` after Fix | preserve MDS #5 route: later explicit resume dispatches one fresh REVIEW |
| `task_changes_requested` at limit, `verification_failed` after Fix, `review_failed`, or `human_attention` | no automatic retry/Fix; present durable evidence and required human boundary |
| `task_review_passed` | stop; MDS #6 does not accept/release/select |

`status`, `logs`, human output, and JSON must make the source review attempt,
finding IDs/count, review-cycle/limit, Fix attempt/operation, continuity mode
as a safe label, repository/result hashes, verification handoff/outcome, and
new review attempt visible. They must say explicitly when a task remains
unaccepted and dependencies remain blocked. They must not expose raw provider
transcripts, command output, environment, secrets, provider session IDs, PIDs,
or protected paths outside existing safe projections.

## 10. Explicitly out of scope

MDS #6 does **not** implement:

* task acceptance, dependency release, selecting or dispatching a successor
  task, parallel/multi-task execution, or feature completion;
* retrying a failed Fix or repairing a post-Fix verification failure. This is
  deferred—not prohibited permanently—to a milestone that defines bounded
  `max_fix_attempts_per_review_cycle` and `retry_on_verification_failure`;
* finding waiver, edit, manual disposition, or a human override workflow;
* Wave review/remediation/acceptance, final feature or release review,
  authorization, commit, push, PR, merge, or delivery;
* a new provider, provider fallback, lease TTL/stealing, process killing,
  worktree reset/stash/cleanup, branch/ref mutation, or manifest policy change;
* migration of historical V1 task cycles or reinterpretation of MDS #1–#5
  persisted outcomes.

## 11. Predecessor invariants preserved

MDS #1–#2 immutable, hash-verified Feature Contract/Plan/approval authority
and their distinct human feedback state remain unchanged. MDS #3 still selects
one task deterministically from the approved Plan, preserves clean-baseline and
writer-lease policy, and does not make provider claims repository truth. MDS
#4 retains its tracked immutable manifest, exact ordered command evidence,
controlled runner, common lease, UNKNOWN retention, producer binding, and
`VERIFIED`-only terminal semantics. MDS #5 retains fresh read-only Reviewer
independence, immutable ordered findings, protected repository/control checks,
recovery-without-dispatch, and the fact that `REVIEW_PASSED` is not acceptance
or dependency release.

All MDS #1–#5 entry routes and status meanings stay compatible. The only new
normal predecessor is the already-existing `TASK_CHANGES_REQUESTED` stop, and
the only new normal writer capability is its bounded, evidence-bound Fix.

## 12. Acceptance criteria

MDS #6 is acceptable only when all of the following are demonstrated:

1. A genuine MDS #5 `CHANGES_REQUESTED` result below the configured limit
   starts one, and only one, durable Developer/FIX attempt bound to its exact
   immutable blocking findings.
2. The Fixer receives workspace-write and bounded authoritative inputs; it can
   use exact Developer continuity when supported, otherwise a fresh bounded
   Developer session; it never receives Reviewer authority.
3. A normal Fix is followed by MDS #4 deterministic verification bound to the
   Fix producer. No path skips it or turns a Fix result into success.
4. Passing verification reaches `TASK_VERIFIED` and only a later explicit
   resume starts a fresh independent read-only Reviewer; a later review pass is
   the sole normal resolution proof.
5. Re-review findings produce a new immutable round; the configured review
   limit blocks a further Fix and requires human attention.
6. Failed, interrupted, drifted, malformed, corrupted, or ambiguous Fix and
   post-Fix verification paths preserve sufficient evidence, perform no silent
   retry, do not duplicate dispatch, and fail closed. The preserved source,
   Fix-attempt ordinal, producer, and VERIFY evidence can support a future
   bounded retry design without changing historical MDS #6 evidence.
7. Recovery is idempotent and zero-dispatch; UNKNOWN ownership retains its
   lease and evidence; every normal lease release is exact and atomic.
8. CLI/status/logs/JSON expose the bounded remediation trail safely and
   accurately, while explicitly reporting no acceptance, dependency release,
   successor selection, or delivery action.
9. Focused slice tests and the repository full test suite pass, including MDS
   #1–#5 regression coverage.

## 13. Human approval decision

One policy decision needs explicit human approval before implementation:

> **Approve the initial strict bound that a post-Fix deterministic verification
> failure stops at `HUMAN_ATTENTION` rather than authorizing another Fix.**

This plan recommends approval. It keeps MDS #6 small, prevents an unbounded
test-driven retry channel, and preserves the existing single `max_review_cycles`
policy. If product policy later requires autonomous remediation of failed
post-Fix verification, that should be a separately designed milestone with an
explicit persisted Fix-attempt limit and retry eligibility contract. The MDS #6
source-review, ordinal, producer, and VERIFY provenance is intentionally shaped
to permit that evolution rather than foreclose it.
