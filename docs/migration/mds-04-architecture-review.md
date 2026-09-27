# MDS #4 Deterministic Verification — Architecture Review

## 1. Review result

**REVISE.**

The proposal has the right core direction: verification should be code-owned,
argv-based, non-agentic, hash-bound, non-mutating, durably evidenced, and unable
to advance after an uncertain interruption. The manifest mutation prohibition,
minimal environment, no same-invocation retry, and fail-closed repository checks
are appropriate.

The document is not ready for approval because several contracts contradict one
another or the implemented MDS #3 boundary:

- `resume` as the sole VERIFY entrypoint recreates the manual phase stepping
  that MDS #2.1/#3.1 began removing and is contrary to the product goal of
  minimizing human touches;
- the proposed manifest exception lets IMPLEMENT change the executable policy
  that judges the same implementation;
- a separate verification-lease table does not provide the claimed common
  writer/verifier exclusion invariant;
- exact control-state equality is incompatible with the verifier's own SQLite,
  event, command-result, and runtime-evidence writes;
- the proposal requires an MDS #3 final control fingerprint that MDS #3 does not
  persist in its final repository snapshot;
- configuration errors, interruptions, runner defects, test failures, and
  repository contamination are collapsed into states that route incorrectly;
- `VERIFIED` is treated as dependency completion even though the approved
  product flow requires independent review before a task is complete; and
- the evidence transaction described in section 5 cannot provide the
  per-command durable events and crash reconstruction promised elsewhere.

These are design corrections, not reasons to abandon deterministic VERIFY.
A materially smaller design can preserve the important safety properties.

## 2. Recommended continuation and authority policy

### Decision: automatic VERIFY after successful IMPLEMENT

Successful IMPLEMENT should transition directly into deterministic VERIFY in
the same interactive workflow invocation. There should be no second `Start
verification now?` prompt and no normal requirement for a later `resume`.

The clean authority model is:

1. Plan approval authorizes the immutable Plan, but still performs no mutation.
2. The existing explicit implementation-start action authorizes one bounded task
   execution. Before the writer starts, the coordinator validates and displays
   (in the interactive path) that the task's configured deterministic
   verification pipeline will run automatically after a structurally successful
   implementation.
3. The tracked manifest and selected argv pipeline are resolved and hash-bound
   before IMPLEMENT dispatch. They are repository policy, not authority created
   by the implementation agent.
4. The IMPLEMENT gateway remains the only mutation gate. On
   `completed_changed`, the same coordinator revalidates persisted state and
   calls the VERIFY gateway. VERIFY creates its own durable attempt and lease;
   it does not rely on an in-memory success value.
5. An invocation that begins at an already persisted
   `IMPLEMENTATION_COMPLETED` state may enter VERIFY through `resume`. This is a
   recovery/operator entrypoint, not the mandatory happy-path boundary.
6. A crash after IMPLEMENT completion but before VERIFY intent leaves an
   unambiguous `IMPLEMENTATION_COMPLETED` state; later `resume` starts VERIFY.
   A crash after VERIFY intent follows verification reconciliation rules.
7. No failure, interruption, or recovery reconciliation falls through to a new
   verification attempt in the same invocation.

A post-IMPLEMENT confirmation adds little real authority. The executable
pipeline was already known before mutation, VERIFY is intended to preserve the
repository, and a default-no prompt would turn every task into another human
touch. It also creates awkward behavior for non-TTY automation. If command
execution is not trusted, that trust problem must be resolved before IMPLEMENT
starts, not after the repository has been changed.

For the current interactive UI, the implementation-start presentation should
say that successful implementation is followed by the displayed deterministic
verification command IDs/argv. The prompt may remain a single explicit start
decision; it need not create another persisted authorization flag. Explicit
`approve` remains approval-only. An explicit `resume` from `PLAN_APPROVED`
authorizes the same composed IMPLEMENT-then-VERIFY step for non-interactive
operation.

This policy also establishes the correct extension point for MDS #5/#6:
deterministic and policy-permitted successor phases continue in one coordinator
invocation until a genuine human gate, terminal outcome, configured budget, or
uncertain state is reached.

## 3. Review of the proposed decisions

### 3.1 Verification manifest

**Approve with changes.** A strict repository-owned manifest is substantially
safer and simpler than executing Plan prose or model-produced shell text. The
executable definition must be part of the versioned repository snapshot.

For MDS #4, “versioned” must mean that the exact manifest path is tracked in
the accepted `HEAD`, its blob bytes are readable, and its working-tree bytes
match that blob both before IMPLEMENT and before VERIFY. “Committed or
otherwise already present” is too weak: an ignored or untracked manifest is not
controlled authority.

The proposed path is currently inside a directory that `engineering-flow init`
and this repository ignore wholesale (`.engineering-flow/`). The design must
choose one of these approaches before implementation:

- preferably, narrow the generated ignore rules so
  `.engineering-flow/verification/manifest-v1.json` is an ordinary tracked
  configuration file while databases and runtime directories remain ignored;
  or
- move the manifest to a tracked configuration path outside the runtime/control
  workspace.

Requiring users to remember `git add -f` is not an acceptable product contract.
If the proposed path is retained, the first option must be specified, migrated,
and tested.

The manifest defines command selection, not a security sandbox. `shell=False`
prevents shell-string injection but any executable or script can itself spawn
children, use the network, or mutate accessible files. The plan should state
this directly. Trust comes from the tracked manifest, the human-visible
pre-dispatch pipeline, the controlled environment, and post-execution checks.

For this milestone, remove `when_task_ids`, per-command working directories,
and manifest-provided environment overrides. Task IDs are Plan-local and are a
poor stable key for repository configuration. Run one ordered repository
pipeline for the selected task. A later manifest version can add named
verification profiles if real multi-task use requires them.

### 3.2 Manifest mutation

**Approve the prohibition; remove the exception.** MDS #4 IMPLEMENT must not
create, modify, delete, rename, or replace the manifest. The proposal currently
says both that the implementation does not generate it and that an approved
task may add or change it. Those positions are incompatible.

Bind the manifest blob SHA-256 and selected canonical commands before the
writer is spawned, then prove after IMPLEMENT and before VERIFY that the same
tracked path and bytes remain present. A manifest change is a structural safety
violation regardless of Task Contract wording. A future explicit configuration
workflow may change verification policy before implementation; the task being
judged may not change it.

This control does not prove that implementation cannot change tests or helper
scripts invoked by the fixed pipeline. That broader limitation is inherent in
repository-owned tests and is one reason MDS #5 independent review remains
necessary.

### 3.3 Environment

**Approve a minimal controlled environment, with narrower claims.** Do not
inherit the ambient environment. Construct a new environment containing only
the runner's documented locale/non-interactive values, a configured and
recorded `PATH`, and isolated `HOME`, `TMPDIR`, and common cache locations
outside the repository. Do not support arbitrary manifest environment values
in manifest v1.

Call this environment controlled and reproducible, not absolutely
deterministic. Tool binaries, dependency installations, kernel behavior, time,
and external services remain outside the manifest unless a later toolchain
contract binds them. Record the runner-policy version and resolved executable
for diagnosis; do not turn MDS #4 into a general hermetic build system.

Cache redirection is best effort for supported tools. Arbitrary repository
commands may ignore cache variables. The repository invariant must therefore
define its protected surface precisely rather than promise that no byte under
the root can ever change.

### 3.4 Interrupted verification

**Approve with a distinct interrupted state.** When the exact child/process
group is definitely dead and the protected repository surface exactly matches
the verification baseline, finalize that attempt as
`INTERRUPTED_UNCHANGED`, release the matching lease, and stop the invocation.
A later explicit `resume` may create one new attempt. Reconciliation must never
fall through to retry in the invocation that classified the old attempt.

Do not classify this as `VERIFICATION_FAILED`: no test failure was observed and
MDS #5 Fix must not consume it. If process death, host/boot identity, repository
state, or persistence is uncertain, retain ownership where necessary and route
to `HUMAN_ATTENTION`.

## 4. Required architectural changes

### 4.1 Use one workspace-operation lease domain

Replace `workspace_writer_leases` plus the proposed
`workspace_verification_leases` with one repository-keyed workspace-operation
lease abstraction (for example, a common table with operation kind,
attempt/operation identity, owner identity, and current child identity).

Two tables with independent `PRIMARY KEY(repository_key)` constraints cannot
enforce mutual exclusion between the tables. Application checks in one
`BEGIN IMMEDIATE` transaction can reduce races but unnecessarily duplicate the
ownership and recovery protocol. One lease domain gives the claimed invariant
directly and is the simpler base for future FIX operations. The lease remains
non-expiring and is released only for the exact matching attempt after child
death and terminal persistence are known.

The child identity must be updated per command because a pipeline can spawn
multiple sequential process groups. Between commands the lease remains owned
by the coordinator even when no child exists.

### 4.2 Separate repository evidence from mutable control evidence

Define a `VerificationBaseline` rather than claiming literal equality of all
repository/control bytes. It should contain:

- the MDS #3 repository snapshot fingerprint and structural identity;
- tracked/non-ignored working-tree content, index, HEAD, branch, local Git
  configuration, and changed-path evidence;
- the immutable manifest path/blob/worktree hash;
- immutable Feature Contract, Plan, approval, Task Contract, and producing
  change-operation bindings; and
- an explicit exclusion list for the SQLite database/WAL, the exact current
  verification runtime directory, and other orchestrator-owned volatile files.

MDS #3's persisted final snapshot currently contains the Git repository
snapshot but not a final `control_state_fingerprint`. The proposal must not
require evidence that does not exist. Revalidate immutable authority
semantically and compare the persisted MDS #3 final repository fingerprint.
Do not infer or synthesize a historical final control fingerprint.

Verifier-owned database/event/result writes are expected mutations. The design
must validate that only the expected control records/runtime paths changed,
instead of comparing the control workspace to a byte-identical baseline.

Ignored files are not covered by the current `RepositoryInspector`. Either
state that the protected Git surface is tracked plus non-ignored untracked
content, or introduce a different bounded filesystem contract. A recursive
hash of the whole repository is not recommended: it conflicts with the control
workspace, virtual environments, caches, and the current MDS #3 evidence model.

### 4.3 Check invariants at useful boundaries, not redundantly

Repository inspection after each command is reasonable for a short sequential
pipeline because it stops before a later command can obscure which command
introduced drift. It should be exactly one full protected-surface inspection
after each terminated command. The final command's post-check is also the
pipeline final check; do not immediately repeat it.

Before each spawn, perform a cheap authority/lease check and reuse the prior
full snapshot unless control authority changed. Full Git diff/status and
untracked-content hashing both before and after every command would be
duplicative and can become expensive. Persist timings so the policy can be
revisited from evidence rather than adding a more elaborate incremental
watcher now.

Any protected-surface mutation is a verification safety violation and human
attention, not an ordinary failing test. The verifier must never clean or
restore it.

### 4.4 Correct the state and classification model

Preserve separate facts for implementation and verification. A verification
problem must not rewrite a known completed implementation as
`IMPLEMENTATION_UNKNOWN`.

The minimum classifications are:

| Observation | Attempt/task projection | Routing |
| --- | --- | --- |
| All commands exit zero and invariants hold | `VERIFIED` | MDS #4 stop; later REVIEW may consume it. |
| Command exits nonzero, reaches its configured timeout, or exceeds its output policy; child death and invariants are known | `VERIFICATION_FAILED` | Eligible evidence for MDS #5 Fix. |
| Manifest missing/invalid/untracked/changed, executable cannot start, or runner contract is invalid | `VERIFICATION_BLOCKED` | `HUMAN_ATTENTION`; configuration/runtime correction, not Fix. |
| User/process interruption, child definitely dead, baseline unchanged | `INTERRUPTED_UNCHANGED` | Stop; later explicit `resume` may create a new attempt. |
| Repository/authority drift, corrupt durable evidence, unknown child ownership, or ambiguous persistence | `VERIFICATION_UNKNOWN` | `HUMAN_ATTENTION`; no automatic successor. |

Workflow status is a projection of the active task, not feature completion.
Keep the workflow in the task-execution stage and use unambiguous statuses such
as `VERIFYING`, `VERIFICATION_FAILED`, `TASK_VERIFIED`, and
`HUMAN_ATTENTION`. Avoid a bare workflow `VERIFIED` label that can be mistaken
for feature or Wave acceptance.

### 4.5 Make per-command evidence genuinely durable

Persist a command intent immediately before each spawn and its bounded result
immediately after confirmed child death and repository inspection. Then start
the next command. The terminal attempt transaction records the final task/workflow
projection and releases the lease.

The proposal's single terminal transaction for “all command rows” conflicts
with durable `command.started`/`command.finished` events and loses command-level
crash position. Per-command transactions are acceptable because none of those
rows can independently prove task success. Only the terminal attempt
transaction may write `VERIFIED`.

Store bounded byte counts, truncation/output-limit facts, hashes, timestamps,
exit facts, and safe excerpts. Raw output, if retained as a local file, is
sensitive advisory evidence and must be written atomically with restrictive
permissions after capture. It is never required to reconstruct success. Avoid
claiming those files are immutable merely because a hash is stored.

### 4.6 Fix dependency and future-loop semantics

`VERIFIED` should mean only that deterministic verification passed. It should
authorize entry into REVIEW, not make a task dependency-ready in the eventual
autonomous loop. The approved product contract says a task is complete only
after required tests and independent review pass.

MDS #4 does not dispatch another task, so changing this semantic has no current
execution cost. Reserve a later `ACCEPTED`/`REVIEW_PASSED` task milestone as the
dependency-satisfying state. Otherwise MDS #6 will either run dependent tasks
before review or have to reverse a public MDS #4 invariant.

Verification attempts should bind to the generic operation that produced the
input repository state, not only to `implementation_attempt_id`. In MDS #4 the
producer must resolve to the successful IMPLEMENT operation; MDS #5 can then
reuse the same verification machinery after a FIX operation without replacing
the schema or inventing parallel verification records.

### 4.7 Resolve configuration before mutation

Once MDS #4 is active, validate the tracked manifest, selected pipeline,
environment policy, and runner availability before starting IMPLEMENT. This
avoids knowingly producing an implementation that cannot enter verification
and supplies the trust information needed by the single start decision.

For workflows already completed under MDS #3, VERIFY is eligible only when the
manifest can be proven tracked at the unchanged `HEAD` and unchanged in the
implementation result. A missing manifest is a migration/configuration block,
not a verification failure. The plan should state the operator path explicitly;
silently adding a manifest to the dirty implementation result is prohibited.

## 5. Major simplifications

The following reductions preserve the milestone outcome while avoiding a
premature general CI subsystem:

1. Use one composed workflow coordinator and one verification orchestrator;
   make task selection and manifest parsing pure domain functions rather than
   separate orchestration services.
2. Use one common workspace-operation lease table/protocol for IMPLEMENT,
   VERIFY, and future FIX.
3. Manifest v1 contains only `version` and an ordered non-empty list of
   `{id, argv, timeout_seconds}`. Use repository-root cwd for every command.
   Remove task filters, custom cwd, and manifest environment overrides.
4. Use one runner-level environment policy version with isolated temporary
   directories. Do not build ecosystem-specific cache configuration into the
   manifest.
5. Perform one full repository check after each command, with the last check
   serving as the final check. Do not add filesystem watchers, hostile-code
   attribution, or recursive whole-checkout hashing.
6. Keep only bounded command evidence needed for status, recovery, and later
   Fix. Do not treat raw output files as canonical artifacts or replayable
   results.
7. Use a small outcome taxonomy that distinguishes test failure, blocked
   configuration, safe interruption, and unknown contamination. Do not add a
   separate task-state rewrite for every runner detail.
8. Keep MDS #4's stop after the one task's VERIFY outcome, but do not encode
   that milestone stop as a mandatory CLI invocation boundary. The coordinator
   can compose later REVIEW/FIX phases without redesigning authority.

## 6. Approval conditions

The revised plan is approval-ready when it:

1. specifies automatic same-invocation VERIFY after successful IMPLEMENT and
   retains `resume` for persisted boundaries/recovery;
2. requires a tracked `HEAD` manifest, resolves the current ignore-path
   conflict, binds it before writer dispatch, and forbids IMPLEMENT mutation
   without exception;
3. replaces the separate verification lease with a true common lease domain;
4. defines the protected repository surface and expected control-state writes
   using evidence MDS #3 actually persists;
5. adopts the corrected failure/block/interruption/unknown classifications;
6. persists command intent/result incrementally while reserving `VERIFIED` for
   one terminal transaction;
7. makes review acceptance, not deterministic verification, the future
   dependency-satisfying milestone;
8. uses a producer-operation binding that can support post-FIX re-verification;
   and
9. removes the manifest and runner features that are not needed for the current
   milestone.

No production code or tests were changed by this review.
