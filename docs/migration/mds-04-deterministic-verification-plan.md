# Engineering Flow V2 — MDS #4 Deterministic Verification Plan

## 1. Status, purpose, and boundary

**Proposal status: AWAITING HUMAN APPROVAL.** This implementation-ready design
changes no production code or tests.

MDS #4 deterministically verifies one MDS #3 task:

```text
explicit IMPLEMENT start -> validate/bind verification configuration
  -> IMPLEMENT -> completed_changed -> revalidate durable result
  -> VERIFY in the same invocation
  -> VERIFIED | VERIFICATION_FAILED | VERIFICATION_BLOCKED |
     INTERRUPTED_UNCHANGED | VERIFICATION_UNKNOWN / HUMAN_ATTENTION
```

The implementation-start presentation displays ordered command IDs/argv and
states that successful IMPLEMENT automatically runs VERIFY. There is no
post-IMPLEMENT confirmation and no mandatory CLI boundary. `approve` remains
approval-only. `resume` is only for persisted boundaries, recovery, or later
continuation—not the normal VERIFY entrypoint. A crash after persisted
`IMPLEMENTATION_COMPLETED` but before verification intent is recovered by
`resume`; a `PLAN_APPROVED` invocation composes the same IMPLEMENT-VERIFY
path.

MDS #4 is one task only: no REVIEW, FIX, next task, commit/push/PR, or
model-based verification. `VERIFIED` authorizes future REVIEW but does not
satisfy dependencies; only future `REVIEW_PASSED` or `ACCEPTED` does.

## 2. Authority and components

MDS #3 is the predecessor. Its immutable approved Plan remains Task Contract
authority. Reuse its implementation state/attempt, artifact hashes, generic
operation/execution, final repository snapshot, and changed-path evidence; do
not import V1 Verify/task records.

Before the existing IMPLEMENT mutation gate dispatches a writer, validate:

- current Feature Contract, Plan, approval, selected Task Contract, hashes, and
  deterministic selection/predecessor rules;
- tracked manifest, resolved pipeline, controlled-environment policy, and runner
  availability; and
- availability of the common workspace-operation lease.

Any failed verification preflight blocks IMPLEMENT. On `completed_changed`,
the coordinator rereads durable authority/result then invokes VERIFY; it never
trusts an in-memory success alone.

| Component | Responsibility |
| --- | --- |
| Composed task coordinator | One explicit start; preflight; invokes VERIFY after durable IMPLEMENT success. |
| `VerificationManifestResolver` | Pure manifest validation/canonicalization; no spawn authority. |
| `DeterministicVerificationOrchestrator` | Attempt/recovery, lease, boundary checks, serial commands, outcomes. |
| `VerificationCommandRunner` | Concrete argv, `shell=False`, root cwd, controlled environment, limits/process groups; no model. |
| `RepositoryInspector` | Verification baseline and protected-surface inspections. |
| `WorkflowStore` | Intent, lease, command evidence, terminal projection, operations/executions, events. |

Every attempt binds to the generic producer operation that produced the input
repository state. In MDS #4 it is the successful IMPLEMENT operation; a future
FIX can use the same mechanism.

## 3. Manifest and runner contract

The only executable authority is strict JSON at
`.engineering-flow/verification/manifest-v1.json`. MDS #4 must narrow the
`.gitignore` rule `.engineering-flow/` so that this exact configuration file
is ordinarily tracked while SQLite/runtime paths remain ignored. Migrate and
test that rule; users must not need `git add -f`.

Before IMPLEMENT, require the path tracked in accepted `HEAD`, read the blob,
prove matching working-tree bytes, and bind its SHA-256 plus canonical ordered
commands. After IMPLEMENT and before VERIFY, prove the identical tracked path
and bytes remain. Missing, untracked, malformed, or changed manifest is a
structural `VERIFICATION_BLOCKED` condition.

IMPLEMENT cannot create, modify, delete, rename, or replace the manifest,
without exception. A future configuration workflow may change policy before
implementation; a task cannot change policy judging itself.

Manifest v1 permits exactly:

```json
{"version":1,"commands":[{"id":"unit","argv":[".venv/bin/python3","-m","unittest"],"timeout_seconds":120}]}
```

`commands` is a non-empty ordered list. Every entry has a unique non-empty
`id`, non-empty text-token `argv`, and positive integral
`timeout_seconds`; unknown fields/shapes are invalid. v1 has no task filters,
profiles, custom cwd, shell strings, or manifest environment overrides. Every
command runs in canonical repository-root cwd and listed order.

The runner constructs, rather than inherits, an environment: documented
locale/non-interactive values, configured recorded `PATH`, isolated `HOME`,
`TMPDIR`, and supported cache locations outside the repository. It forwards
no ambient secrets/CI values or arbitrary manifest environment. Cache
redirection is best effort. This is controlled/reproducible—not hermetic or
hostile-code containment; `shell=False` prevents shell parsing only.

## 4. VerificationBaseline and repository checks

`VerificationBaseline` uses only evidence MDS #3 persists:

- final `RepositorySnapshot` fingerprint and structural identity;
- HEAD, branch, topology, index/status/diff, local Git configuration, tracked
  and non-ignored untracked-content evidence, and changed paths;
- manifest path, HEAD blob SHA-256, matching working-tree SHA-256; and
- Feature Contract, Plan, approval, Task Contract, producer-operation, and
  completed-implementation bindings.

It explicitly excludes SQLite database/WAL/journal, the current exact
`.engineering-flow/verification-runtime/<attempt-id>/`, and documented
orchestrator-owned volatile paths. MDS #3 does not persist a final
control-state fingerprint: compare its persisted final repository fingerprint
and semantically revalidate authority; never synthesize historical control
equality.

The protected surface is MDS #3's Git surface: tracked content and Git
identity/index/status/diff/configuration plus non-ignored untracked content.
Verifier-owned SQLite/event/result and exact runtime writes are expected control
mutations; no other control paths may change. Never clean, reset, stash,
restore, or edit the workspace.

Before each spawn, cheaply recheck authority and exact lease ownership. After
each terminated command, run exactly one full protected-surface inspection and
persist it with that command result. The last is the final check—do not repeat
it. Any protected-surface mutation/identity drift is safety violation, never
ordinary command failure.

## 5. Lease and evidence persistence

Replace MDS #3's writer-only lease with one repository-keyed
`workspace_operation_leases` domain for IMPLEMENT, VERIFY, and future FIX.
One `repository_key` uniqueness constraint provides mutual exclusion. It
records operation kind, attempt/operation, owner, current child/process-group,
and timestamps; it has no TTL, is never stolen, stays held between commands,
and releases only for exact owner after confirmed death and terminal persistence.

`verification_attempts` records workflow, producer operation, verification
execution/operation, lease, authority hashes, request, manifest/command
binding, baseline/final inspection, status/classification, and timestamps.
`verification_command_results` records ordinal, command/canonical hash, argv,
timeout, durable intent/result times, exit/timeout/output facts, bounded
evidence metadata, post-command inspection, and classification.

1. Before a child, transactionally persist attempt intent, common lease,
   `VERIFYING`, generic execution/operation, and attempt-created evidence.
2. Immediately before every spawn, persist command intent. After confirmed
   death and its one inspection, persist result before another command starts.
3. One terminal transaction writes final evidence/projection, execution/operation
   result, terminal event, and exact lease release.

Per-command evidence supports recovery, but only the terminal transaction can
establish `VERIFIED`. Raw output, if retained, is restrictive-permission,
atomic advisory evidence—not canonical proof.

## 6. Outcomes and recovery

Verification never changes known implementation completion to
`IMPLEMENTATION_UNKNOWN`.

| Observation | Outcome | Routing |
| --- | --- | --- |
| Zero exits and all invariants hold | `VERIFIED` / `TASK_VERIFIED` | Stop; future REVIEW may consume it. |
| Nonzero, timeout, output limit; death/invariants known | `VERIFICATION_FAILED` | Stop; future FIX may consume evidence. |
| Invalid/missing/untracked/changed manifest, unavailable executable, invalid runner contract | `VERIFICATION_BLOCKED` / `HUMAN_ATTENTION` | Configuration/runtime correction, not FIX. |
| Interrupted; child dead; baseline unchanged | `INTERRUPTED_UNCHANGED` | Stop; later explicit `resume` may make a new attempt. |
| Drift, corrupt/ambiguous evidence, unknown ownership, unreadable inspection, persistence ambiguity | `VERIFICATION_UNKNOWN` / `HUMAN_ATTENTION` | No successor; retain lease when required. |

No failed/interrupted attempt retries in its classifying invocation. Recovery
first reconciles persistence: dead/unchanged becomes
`INTERRUPTED_UNCHANGED` and releases its exact lease; live/ambiguous,
changed, or unreadable becomes human attention. No outcome rolls back, modifies,
commits, or changes branch. Workflow statuses are active-task projections:
`VERIFYING`, `VERIFICATION_FAILED`, `TASK_VERIFIED`, or
`HUMAN_ATTENTION`, never feature-level bare `VERIFIED`.

## 7. Validation, acceptance, and exclusions

`status`/`logs` show bounded durable manifest binding, producer operation,
commands/argv, classification/timing, inspection identity, evidence hashes, and
lease/recovery state—never secrets, full environment, raw output, or PIDs.

Validate strict parsing/tracking and ignore migration; pre-IMPLEMENT blocks;
manifest immutability; common IMPLEMENT/VERIFY/FIX lease; argv runner/environment;
one post-command inspection; all outcomes; incremental evidence; terminal-only
success; recovery; producer reuse; and `TASK_VERIFIED` non-dependency
semantics. Run focused tests, then
`.venv/bin/python3 -m unittest discover -s tests -q`. Disposable-repository
manual acceptance proves pass/failure without next task, REVIEW, FIX, commit,
push, PR, or model verification.

Excluded: REVIEW, FIX, model escalation, multi-task/parallel execution,
worktrees, commits/pushes/PRs, rollback/stash/reset/cleanup, Plan regeneration,
V1 migration, arbitrary shell parsing, remote sandboxing, hostile-code
containment, coverage gates, automatic dependency installation, and generalized
CI.
