# Engineering Flow V2 — MDS #3 Single Task Execution Plan

## 1. Purpose

MDS #3 crosses the first repository-mutation boundary in Engineering Flow V2.
It proves one bounded transition and then stops:

```text
PLAN_APPROVED
      |
      v
validate the exact approved Plan and READY Feature Contract
      |
      v
select one executable Task Contract deterministically
      |
      v
acquire one target-workspace writer lease and capture a clean baseline
      |
      v
IMPLEMENT (one provider dispatch)
      |
      v
capture repository truth and persist the attempt result
      |
      v
STOP — verification has not run
```

The milestone executes **at most one Task Contract per CLI invocation**. A
successful writer return means only that one implementation attempt completed
and its resulting working tree passed MDS #3 execution-integrity checks. It
does not mean that the task is verified, reviewed, accepted, done, or that the
feature is complete.

This document is the complete planning artifact for MDS #3. It makes no
production or test change.

## 2. Current baseline

The baseline was verified on 2026-09-26 in the canonical Linux checkout:

- repository: `/home/bal/projects/engineering-flow`;
- branch: `main`;
- HEAD: `d896953b4a9710cb4ccea17d4df8bd156d219fe2`;
- `git status --short`: empty before this document was created;
- `./scripts/env-preflight`: `READY`, Python 3.13.15, editable package, CLI
  available, Git clean;
- `.venv/bin/python3 -m unittest discover -s tests -q`: **176 tests passed**;
- no registered submodules were present.

The implemented V2 path is currently `INTAKE -> PLAN -> PLAN_APPROVED` and
stops. Its important properties are:

- SQLite is authoritative for workflows, executions, operations, artifacts,
  approvals, clarification lineage, Plan change requests, events, and selected
  workflow context.
- Canonical Feature Contract and Plan JSON artifacts are immutable, have UUID,
  revision, SHA-256, and execution provenance, and are hash-verified on read.
- A Plan embeds its workflow identity, revision, and the exact READY Feature
  Contract artifact UUID/SHA. `Plan.parse()` validates strict task shapes,
  contiguous stable IDs `T1`, `T2`, ..., repository-relative context paths,
  independent complexity/risk, and dependencies that refer only to earlier
  tasks.
- V2 approval validates the highest current Plan revision and its exact bytes,
  records an approval against the artifact UUID, changes the workflow to
  `plan/plan_approved`, and does not create task rows or invoke a Developer.
- `approve` and interactive approval are authorization-only operations.
  Existing `resume` returns a `PLAN_APPROVED` V2 workflow unchanged.
- V2 `cancel`, terminal `reject`, feedback/revision, clarification, selected
  workflow, TTY/non-TTY/JSON, and progress behavior are already explicit.
- The runtime is provider-neutral at the orchestrator boundary. The Codex
  adapter already recognizes `read-only` and `workspace-write`, uses
  `subprocess.Popen(..., shell=False)`, streams bounded JSONL/progress, writes a
  schema-constrained final result, and terminates/kills its owned child on
  `KeyboardInterrupt` or timeout.
- Configuration currently enables workspace-write for the older V1 Developer
  path, but V2 never requests it. The current adapter selects workspace-write
  only for `Role.DEVELOPER`; planning and review remain read-only.
- The older V1 task subsystem has task/cycle/artifact/operation primitives and
  a Developer/Verify/Review/Fix loop. Its task manifest is not the V2 Plan
  schema, its task UUID rows duplicate imported task definitions, and its
  lifecycle advances beyond MDS #3. It is compatibility evidence, not the V2
  implementation architecture.
- The bootstrap Wave Controller experiments demonstrate binary-safe checkout
  fingerprints, atomic file replacement, reviewer write restraint, stale
  result rejection, exact interrupted-writer recovery, and a single active
  writer lease. They use a separate Markdown controller and host protocol and
  must not be promoted wholesale into production.

The existing SQLite `BEGIN IMMEDIATE` transactions and process-local
`threading.RLock` protect store writes, but the lock does not protect the Git
workspace across CLI processes. Existing V1 pending-operation reconciliation
also marks a task unknown without comparing the repository before and after.
MDS #3 therefore needs a V2-specific mutation boundary.

## 3. MDS boundary

### In scope

- enter implementation only from an exact valid V2 `PLAN_APPROVED` authority;
- recover Task Contracts directly from the approved canonical Plan;
- deterministically select one dependency-ready Task Contract;
- require and persist a clean Git baseline;
- acquire one durable writer owner for the target workspace;
- dispatch one write-enabled Codex implementation operation;
- capture the resulting filesystem/Git truth;
- persist one operational implementation attempt and task projection;
- classify success, known failure, interruption, safety violation, and unknown
  recovery state;
- show the result through `resume`, `status`, logs, human output, and JSON;
- stop without dispatching another task or any verification/review operation.

### Milestone stop

MDS #3 ends after the first selected Task Contract reaches
`IMPLEMENTATION_COMPLETED`, a retryable unchanged failure is recorded, or an
unknown/human-attention boundary is recorded. The roadmap remains:

```text
MDS #3  Single Task Execution
MDS #4  Deterministic Verification
MDS #5  Review + Fix
MDS #6  Autonomous Feature Loop
```

## 4. Architecture decision summary

| Decision | MDS #3 choice |
| --- | --- |
| CLI entry | `engineering-flow resume` from `plan/plan_approved`; `approve` still stops without mutation. |
| Task authority | Task payload is read from the exact approved Plan JSON. No imported/mutable V2 task definition is created. |
| Stable task identity | Composite `(workflow UUID, Plan artifact UUID, Task Contract id)`; the canonical task-payload SHA-256 is an additional integrity binding. |
| Selection | Domain selector validates the whole graph, filters pending tasks whose dependencies are `VERIFIED`, and chooses the lowest numeric `T<N>` identity. |
| Dependency completion | Only `VERIFIED` satisfies a dependency. `IMPLEMENTATION_COMPLETED` does not. MDS #3 can therefore select a root task only. |
| Task states | `PENDING`, `IMPLEMENTING`, `IMPLEMENTATION_COMPLETED`, `IMPLEMENTATION_FAILED`, `IMPLEMENTATION_UNKNOWN`, plus reserved `VERIFIED`; MDS #3 has no transition that writes `VERIFIED`. |
| Workflow after success | `task_execution/implementation_completed`; never `COMPLETED`. Presentation always says verification has not run. |
| Repository policy | Git worktree required; attached branch and existing HEAD required; all staged, tracked, and non-ignored untracked changes rejected; ignored files allowed. |
| Nested Git | Registered submodules/gitlinks and nested repositories are unsupported and rejected before dispatch in MDS #3. |
| Repository evidence | Canonical root/Git dirs, branch, HEAD, porcelain-v2 bytes hash, binary diff hash, untracked content manifest hash, changed-path manifest/hash, and local Git-config hash. |
| Writer ownership | Durable non-expiring SQLite lease keyed by canonical workspace identity; unique acquisition in `BEGIN IMMEDIATE`; never stolen by timeout. |
| Retry bound | Maximum one implementation provider call per invocation; no hidden retry. A later `resume` retries only after an unchanged, definitely-ownerless result. |
| Runtime permission | Only an IMPLEMENT/Developer request gets Codex `workspace-write`; no `--add-dir`, bypass flag, commit, push, branch change, or global permission change. |
| Routing | Provider-neutral `efficient`, `balanced`, `strong` profile selected deterministically from task complexity/risk; Codex model/reasoning mappings live in configuration. |
| Result authority | Git/filesystem inspection is code truth. Agent `summary`/`changed_files` is advisory operational metadata. |
| Result storage | Task state and attempts are operational SQLite records linked to generic operation/execution records; they are not canonical artifacts and do not mutate Plan JSON. |
| Commits | Neither agent nor orchestrator commits. Any HEAD/ref/branch change is a safety violation and requires human attention. |

No blocking product decision remains for implementation.

## 5. Execution authority

### 5.1 Exact authorization predicate

`ImplementationOrchestrator.resume_once(workflow_id)` may select or dispatch a
writer only if all of the following are true in one revalidated authority
snapshot:

1. The workflow exists, has `lifecycle_version=v2`, belongs to the repository
   containing the selected `.engineering-flow` database, has `stage=plan`, and
   has `status=plan_approved`.
2. The workflow is not `cancelled`, `rejected`, `changes_requested`,
   `awaiting_approval`, `failed`, or otherwise outside this exact entry state.
3. Exactly one highest-revision `Stage.PLAN` artifact is current. It is the
   artifact whose approval state is `APPROVED`.
4. Exactly one approval row exists for that artifact and its decision is
   `APPROVED`; no approval or Plan identity from an earlier revision is used.
5. No open Plan change request targets the current Plan or remains without a
   replacement.
6. `read_artifact()` proves the Plan bytes match its persisted SHA-256.
7. Strict JSON parsing succeeds. Embedded Plan ID, workflow UUID, revision,
   and Feature Contract binding match generation intent and artifact rows.
8. The bound Feature Contract is the exact latest successfully persisted
   Intake artifact; its bytes match its SHA-256; strict parsing returns
   `READY`; it has requirements and acceptance criteria and no open questions.
9. The Plan is still the latest Plan and the approval is still current when
   the store transaction creates the attempt/lease. A preflight read is not
   sufficient authority for a later dispatch.

The store exposes a narrow `load_approved_v2_plan_authority()` projection with
workflow, Feature Contract artifact, Plan artifact, approval, and parsed Plan.
It does not accept caller-supplied hashes as truth. Immediately before attempt
creation, the store repeats all database predicates in `BEGIN IMMEDIATE`; the
orchestrator re-reads and hashes artifact bytes before spawning the provider.
Any mismatch fails closed without a provider call.

### 5.2 Persisted binding

Every implementation attempt records:

- workflow UUID;
- READY Feature Contract artifact UUID and SHA-256;
- Plan artifact UUID, SHA-256, revision, and embedded Plan ID;
- approval UUID;
- selected Task Contract ID;
- SHA-256 of the task's canonical JSON (`json.dumps(task.as_payload(),
  sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as
  UTF-8);
- attempt sequence and request hash.

The request hash covers all identities above, repository baseline fingerprint,
requested execution profile, implementation output-contract version, and exact
instruction. Reusing an operation key with a different request hash conflicts.

Authority failure before dispatch records a sanitized safety/authority event
and moves the workflow to `HUMAN_ATTENTION` only when durable reconciliation is
needed (for example artifact corruption or ambiguous approval). A simple wrong
entry command conflicts without changing state. No implementation attempt is
counted unless a provider dispatch intent is created.

## 6. Task Contract authority and deterministic selection

### 6.1 No second task definition

The approved Plan remains the sole Task Contract authority. MDS #3 must not use
V1 `import_task_plan()`, V1 `tasks.definition_json`, or a new copied payload.
Operational task rows store identity and state only.

The exact task payload is recovered on every selection/status/dispatch by:

1. loading and hash-verifying the approved Plan artifact;
2. parsing the entire Plan through `Plan.parse()`;
3. finding exactly one `TaskContract.id` equal to the operational identity;
4. recomputing its canonical payload hash and comparing it with any persisted
   task-state/attempt binding.

Missing, duplicate, malformed, or hash-mismatched identity is authority
ambiguity. It produces no provider call and requires human attention. Although
the current parser already enforces unique contiguous IDs and backward-only
dependencies, selection validates these properties defensively rather than
assuming historic bytes were valid.

### 6.2 Operational task projection

Add a V2-specific `task_implementation_states` table rather than changing the
V1 `tasks` contract:

```text
task_implementation_states
  id                    TEXT PRIMARY KEY              -- UUID
  workflow_id           TEXT NOT NULL REFERENCES workflows(id)
  plan_artifact_id       TEXT NOT NULL REFERENCES artifacts(id)
  plan_sha256            TEXT NOT NULL                -- 64 lowercase hex
  task_contract_id       TEXT NOT NULL
  task_contract_sha256   TEXT NOT NULL                -- canonical task payload
  status                 TEXT NOT NULL
  selected_at            TEXT NULL
  updated_at             TEXT NOT NULL

  UNIQUE(workflow_id, plan_artifact_id, task_contract_id)
```

Absence of a row means `PENDING`. State rows are projections of operational
history, not Task Contract copies. `status` permits only:

- `pending`;
- `implementing`;
- `implementation_completed`;
- `implementation_failed`;
- `implementation_unknown`;
- `verified`, reserved so the selector has an explicit dependency-satisfaction
  value; only MDS #4 or later may create it.

MDS #3 must not create `verified` or expose an operator shortcut that does.

### 6.3 Selection algorithm

The provider never selects tasks. A pure domain function receives the parsed
Plan plus exact operational states and returns a typed selection outcome:

1. Build a map by Task Contract ID. Reject a missing/duplicate/invalid ID or a
   dependency reference absent from the map.
2. Detect a cycle with deterministic graph traversal even though the current
   parser's earlier-task rule already prevents cycles.
3. Pending candidates are tasks with no row, `pending`, or
   `implementation_failed` whose latest attempt is explicitly retry-safe.
   `implementing`, `implementation_completed`, and `implementation_unknown`
   are not pending.
4. A dependency is satisfied only by future persisted `VERIFIED` evidence.
   Neither provider success nor `implementation_completed` satisfies it.
5. Executable candidates are pending candidates whose dependencies are all
   satisfied.
6. Sort candidates by the numeric component of the contractually validated
   `T<N>` identity and choose the smallest. This is explicit contract order,
   not incidental JSON array order or LLM judgment.

Outcomes are:

| Condition | Outcome |
| --- | --- |
| One executable task | Select it. |
| Multiple executable tasks | Select lowest numeric `T<N>` deterministically. |
| Invalid reference, duplicate/missing ID, or cycle | `HUMAN_ATTENTION`; no attempt. |
| Dependency not `VERIFIED` | Task remains pending and is not executable. |
| At least one task is `IMPLEMENTATION_COMPLETED` and remaining tasks are dependency-blocked | Stop at `AWAITING_VERIFICATION`; no provider call. |
| All tasks are `IMPLEMENTATION_COMPLETED` but not verified | Stop at `AWAITING_VERIFICATION`; workflow is not complete. |
| All tasks are eventually `VERIFIED` | MDS #3 does not advance or complete the workflow; this is a later-milestone boundary. |
| No task is executable for any other internally consistent reason | Persist a bounded `no_executable_task` event and stop without guessing. |

Because MDS #3 creates no `VERIFIED` evidence, it can dispatch only a
no-dependency/root task. After one success the dirty, unverified workspace and
`IMPLEMENTATION_COMPLETED` state prevent a second MDS #3 writer. This preserves
the future transition `IMPLEMENTATION_COMPLETED -> VERIFY -> VERIFIED`.

## 7. State model

### 7.1 Workflow transitions

Add workflow statuses `IMPLEMENTING`, `IMPLEMENTATION_COMPLETED`, and
`IMPLEMENTATION_FAILED`. Reuse existing `HUMAN_ATTENTION`; do not use
`COMPLETED`.

```text
plan / PLAN_APPROVED
  |  authority + clean baseline + lease + attempt intent
  v
task_execution / IMPLEMENTING
  |-- success + changed + structural checks pass
  |       -> task IMPLEMENTATION_COMPLETED
  |       -> workflow IMPLEMENTATION_COMPLETED
  |
  |-- provider failure/interruption + unchanged + owner stopped
  |       -> task IMPLEMENTATION_FAILED
  |       -> workflow IMPLEMENTATION_FAILED (safe explicit retry)
  |
  `-- changed failure, safety violation, uncertain owner, or unreadable state
          -> task IMPLEMENTATION_UNKNOWN
          -> workflow HUMAN_ATTENTION
```

`IMPLEMENTATION_COMPLETED` is a resumable milestone boundary, not a terminal
feature status. Update `is_terminal_workflow_status()` accordingly:
`PLAN_APPROVED` ceases to be terminal once MDS #3 is installed, while
`IMPLEMENTATION_COMPLETED` is a normal stop boundary that later milestones may
continue. `CANCELLED`, `REJECTED`, and true `COMPLETED` remain terminal.

### 7.2 Provider result is not task state by itself

The orchestrator applies task/workflow transitions only after repository
inspection. A structured provider success with no material repository change
is `implementation_failed/no_changes`, not completed. A provider failure with
material changes is unknown, not a safe failure. A successful provider result
with HEAD/branch/config/control-state violation is unknown/human-attention.

## 8. Repository safety contract

### 8.1 Supported repository boundary

MDS #3 supports one existing, non-bare Git worktree whose canonical
`git rev-parse --show-toplevel` exactly equals `Workflow.repository_path` and
the repository containing `.engineering-flow`. It requires:

- an existing commit at `HEAD` (unborn repositories are rejected);
- an attached local branch (`git symbolic-ref --short -q HEAD` succeeds);
- a canonical worktree path, resolved Git dir, and resolved common Git dir;
- no registered gitlinks/submodules (`git ls-files --stage` mode `160000`);
- no nested `.git` directory/file below the root other than the root worktree
  marker and the control workspace's excluded runtime area.

Linked worktrees can satisfy the identity checks, but MDS #3 does not create
or coordinate worktrees. Non-Git repositories, bare repositories, detached
HEAD, submodules, and nested repositories fail before writer dispatch.

### 8.2 Clean-tree policy

Immediately before writer dispatch, this exact command-equivalent must be
empty:

```text
git status --porcelain=v2 -z --untracked-files=all --ignore-submodules=none
```

Therefore all of the following block implementation:

- unstaged tracked modifications or deletions;
- staged additions/modifications/deletions;
- conflict entries;
- non-ignored untracked files or directories.

Ignored files do not make the tree dirty. This is necessary because the
repository-local `.engineering-flow/` workspace is ignored and contains the
control database/runtime outputs. The policy never stashes, resets, cleans,
overwrites, commits, or otherwise disposes of human changes. The CLI explains
that the human must reconcile them.

### 8.3 Baseline identity

Introduce a production `RepositoryInspector` that runs Git without a shell,
uses byte output and `-z` forms, and returns a versioned value:

```text
RepositorySnapshot v1
  canonical_root
  git_toplevel
  git_dir
  git_common_dir
  head_sha
  branch_name
  detached                  -- always false at an accepted baseline
  status_sha256             -- raw porcelain-v2 -z bytes
  diff_sha256               -- git diff --binary HEAD bytes; staged included
  untracked_manifest_sha256 -- sorted path + content SHA-256 records
  changed_paths             -- complete sorted normalized paths in persisted evidence
  changed_paths_sha256
  local_git_config_sha256   -- worktree/common local config bytes or explicit missing marker
  fingerprint               -- SHA-256 of the normalized fields above
```

At a clean baseline, status/diff/untracked/changed-path evidence is empty but
still persisted. Untracked file contents are hashed after paths are obtained
from Git. Symlinks are hashed from `lstat` metadata and link-target bytes and
are never followed outside the root. Tracked files are not all rehashed: clean
index/worktree evidence, HEAD, and Git's own comparison are sufficient and
avoid the bootstrap experiment's expensive full `path_hashes` map. Persist the
complete changed-path list; presentation shows at most the first 100 paths plus
the total count.

The accepted baseline snapshot is stored in the attempt before `Popen`. After
the process ends, capture the same shape plus actual changed paths. Persist the
final snapshot and a bounded summary by porcelain status category. Do not
persist a full binary diff or file contents.

### 8.4 Post-execution integrity checks

Before classifying the provider result, require:

1. the active lease UUID/attempt still matches;
2. canonical root, Git top-level, Git dir/common dir identity are unchanged;
3. branch name and attached state equal baseline;
4. HEAD SHA equals baseline (there was no commit, reset, checkout, or rebase);
5. local repository/worktree Git configuration hash is unchanged;
6. the exact approved Feature Contract, Plan, approval, task binding, and
   started attempt still validate;
7. the post-attempt Git snapshot can be captured deterministically;
8. on claimed success, at least one material tracked or non-ignored untracked
   path changed.

HEAD or branch movement is always a safety violation even if the resulting
files look correct. Do not reset it automatically. A provider-created commit,
branch switch, local Git-config change, repository replacement, or unreadable
post-state yields `IMPLEMENTATION_UNKNOWN` plus `HUMAN_ATTENTION`.

The clean baseline plus exclusive Engineering Flow writer lease makes the
result attributable to this attempt inside the MDS #3 cooperative local
threat model. It cannot prove that an unrelated human process did not edit the
checkout concurrently; detected identity drift fails closed.

### 8.5 Control-state and path scope

Codex workspace-write is rooted at the canonical target repository and gets no
additional writable directory. The request and prompt prohibit edits to
`.engineering-flow`, `.git`, paths outside the root, commits, branch changes,
pushes, and unrelated files. Safety does not rely on that prompt alone:

- output schema/final-message files use an exact per-attempt runtime directory;
- before dispatch, snapshot the immutable authority rows/bytes and a manifest
  of control files outside that allowed runtime directory;
- while the provider runs, the parent writes no workflow database state;
- after child termination and before completion writes, re-open/validate
  SQLite integrity, exact authority rows, configuration, canonical artifact
  bytes, and the control-file manifest;
- changes outside the allowed attempt runtime outputs are a safety violation.

This is not a hostile-code security sandbox. Codex's workspace-write sandbox
is the OS/provider boundary; postchecks are detection and fail-closed controls.
MDS #3 does not attempt to prevent every symlink, kernel, Git hook, global Git
config, or malicious subprocess attack. It never supplies `--add-dir`,
`danger-full-access`, or a sandbox-bypass flag. A later hardening milestone may
move control state outside the writable root or add stronger OS isolation if
real evidence requires it.

Self-hosting uses the same rules. Implementation changes to this Engineering
Flow checkout are permitted only when it is deliberately the target, but all
automated/manual MDS #3 acceptance writer runs use disposable temporary Git
repositories so development state is not put at risk.

## 9. Writer ownership and concurrency

### 9.1 Lease schema

Add a durable local `workspace_writer_leases` table:

```text
workspace_writer_leases
  repository_key          TEXT PRIMARY KEY
  lease_id                TEXT NOT NULL UNIQUE          -- UUID
  attempt_id              TEXT NOT NULL UNIQUE REFERENCES implementation_attempts(id)
  workflow_id             TEXT NOT NULL REFERENCES workflows(id)
  canonical_root          TEXT NOT NULL
  owner_instance_id       TEXT NOT NULL                 -- this CLI process UUID
  owner_pid               INTEGER NOT NULL
  owner_host_id           TEXT NOT NULL
  owner_boot_id           TEXT NULL
  provider_pid            INTEGER NULL
  provider_process_start  TEXT NULL                     -- Linux /proc start token
  provider_process_group  INTEGER NULL
  acquired_at             TEXT NOT NULL
  updated_at              TEXT NOT NULL
```

`repository_key` is SHA-256 of normalized canonical root, resolved Git dir, and
resolved common Git dir. One row means ownership is active or unresolved. A
lease has no automatic expiry and no timeout-based stealing.

### 9.2 Acquisition protocol

1. Perform read-only authority, graph, runtime capability, and repository
   preflight.
2. In one `BEGIN IMMEDIATE` transaction, repeat database authority and selected
   task predicates, reject any existing repository lease, allocate attempt
   sequence/UUID and generic operation/execution records, create the task state
   as `IMPLEMENTING`, insert the lease, and set workflow
   `task_execution/implementing`.
3. Re-capture repository/control baseline after acquisition. If it differs or
   is dirty, finalize as not-dispatched, restore task pending, record the
   refusal, and delete the matching lease in one transaction.
4. Persist the final baseline on the attempt, then spawn exactly one provider
   process. Persist its PID/process-group/start token as soon as `Popen`
   returns. The runtime exposes this through a narrow ownership callback; it
   does not decide lifecycle.

A second `resume` observes the unique lease and returns conflict/human
attention before any writer spawn. SQLite locking serializes competing
acquisitions; the second transaction revalidates rather than trusting its
earlier preflight.

### 9.3 Release and recovery

- Normal terminal child: inspect repository, persist attempt/task/workflow
  result, and delete only the matching lease atomically.
- Child definitely stopped but workspace changed/violated: release ownership
  atomically with `IMPLEMENTATION_UNKNOWN/HUMAN_ATTENTION`; the dirty state and
  task status prohibit redispatch.
- Child may still be running or process identity cannot be proven: retain the
  lease and block all writers.
- No code path deletes a lease merely because it is old or its owner CLI PID is
  absent.

For the initial Linux/WSL runtime, “definitely stopped” requires the persisted
host/boot identity to match and the exact PID plus process-start token to be
absent, or a successful owned process-group termination followed by `wait()`.
PID absence alone without matching host/boot evidence is insufficient. On an
unknown host, boot, or inaccessible process table, recovery remains blocked
for explicit human reconciliation.

This is a single-machine/local-checkout lease, not a distributed scheduler.

## 10. Implementation runtime and model routing

### 10.1 Provider-neutral request

Extend the runtime request with an `implementation` execution purpose and a
provider-neutral requested profile. Keep `Role.DEVELOPER` and
`WorkKind.DEVELOP`; do not enable FIX/REVIEW/VERIFY for this V2 path. The
orchestrator asks for:

```text
workspace_write
json_events
output_schema
output_last_message
owned_process_cancellation
```

Only IMPLEMENT receives workspace-write. Intake, Planner, future Reviewer, and
status remain unchanged/read-only.

### 10.2 Codex invocation

The Codex adapter starts a fresh bounded invocation with:

- `codex exec --json --sandbox workspace-write`;
- explicit configured `--model` and
  `-c model_reasoning_effort=<configured value>`;
- canonical target root as `cwd`/`-C`;
- one exact `--output-schema` and `--output-last-message` location;
- `--ephemeral` for MDS #3 because no fix/session continuation is needed;
- `shell=False`, minimal environment, no `--add-dir`, no worktree creation, no
  approval/sandbox bypass, and the existing timeout.

Start the process in its own process group/session. Timeout or Ctrl+C sends
TERM to the owned group, waits a short bounded grace period, sends KILL if
needed, and waits again. Stdout remains parsed as bounded JSONL; stderr remains
sanitized and bounded; provider prose is not printed by default. Progress uses
the existing provider-neutral sink.

### 10.3 Small routing slice

Add provider-neutral profiles `efficient`, `balanced`, and `strong`. Select a
profile using the maximum severity of complexity and risk:

| Task complexity/risk | Profile |
| --- | --- |
| both `low` | `efficient` |
| either `high` | `strong` |
| otherwise | `balanced` |

The domain returns only the profile. A new validated configuration table maps
each profile to a Codex model identifier and reasoning effort. The initial
Codex mapping is explicit:

```toml
[implementation_profiles.efficient]
model = "gpt-5.6-luna"
reasoning = "low"

[implementation_profiles.balanced]
model = "gpt-5.6-terra"
reasoning = "medium"

[implementation_profiles.strong]
model = "gpt-5.6-sol"
reasoning = "medium"
```

These exact names occur only in configuration/template data, not in domain or
selection logic. Luna is the cost-efficient implementation tier, Terra is the
normal balanced tier, and Sol is reserved for high-complexity or high-risk
tasks. GPT-6 Astra is intentionally outside the default MDS #3 routing policy.
Runtime preflight checks the selected mapping before lease acquisition. `init`
writes this table for new repositories. Existing repositories without it
receive one actionable configuration error naming the required table; `resume`
never silently rewrites configuration. Tests supply the table explicitly, so
existing non-implementation lifecycle behavior is otherwise unchanged. No
automatic model escalation is introduced.

Persist requested profile/model/reasoning and actual provider/model/reasoning
when Codex events report them; absent actual telemetry remains `NULL`, never an
invented value. No model escalation or automatic retry exists in MDS #3.

## 11. Implementation context and prompt contract

### 11.1 Authoritative package

The writer receives fresh context, not conversation history or Planner
transcripts:

- exact READY Feature Contract artifact path/UUID/SHA;
- exact approved Plan artifact path/UUID/SHA/revision;
- exact selected Task Contract serialized from that Plan plus its payload hash;
- dependency IDs and their persisted states (in MDS #3, an executable root has
  no dependencies);
- canonical repository root and captured baseline identity;
- selected profile and output contract;
- repository `AGENTS.md` discovered by Codex and applicable repository
  architecture/ADR guidance referenced by repository instructions or task;
- Task Contract `relevant_files`, patterns, constraints, and verification
  commands as pointers, not a copied repository dump.

The agent may explore the repository as needed. The orchestrator does not
preload every source file or full conversation. Before dispatch it verifies
the exact Feature Contract/Plan inputs by hash. Repository files are mutable
working context and are represented by the clean baseline fingerprint.

### 11.2 Instruction and structured result

The implementation instruction states:

```text
Implement exactly the selected approved Task Contract.
Modify only the target working tree as necessary and follow repository AGENTS.md.
Do not implement another task or later milestone.
Do not commit, push, switch/create/delete branches, rewrite Git history,
change Git configuration, modify .git/.engineering-flow, or touch paths outside
the repository. Do not discard pre-existing work.
Return only the structured implementation result.
```

The MDS #3 output schema is deliberately small:

```json
{
  "summary": "string",
  "changed_files": ["repository/relative/path"],
  "notes": ["string"]
}
```

Claims are sanitized, bounded, and persisted as provider metadata. Their paths
must be normalized and inside the root, but they do not prove mutation or
limit Git inspection. The actual Git changed-path set is authoritative.
Commands/tests the agent happens to run are implementation activity only; the
orchestrator neither requires nor records them as deterministic VERIFY
evidence.

## 12. Attempt persistence model

### 12.1 Attempt schema

Add `implementation_attempts` and link each row one-to-one to existing generic
operation/execution evidence:

```text
implementation_attempts
  id                         TEXT PRIMARY KEY             -- attempt UUID
  workflow_id                TEXT NOT NULL REFERENCES workflows(id)
  execution_id               TEXT NOT NULL UNIQUE REFERENCES executions(id)
  operation_id               TEXT NOT NULL UNIQUE REFERENCES operations(id)
  lease_id                   TEXT NOT NULL UNIQUE
  feature_artifact_id        TEXT NOT NULL REFERENCES artifacts(id)
  feature_sha256             TEXT NOT NULL
  plan_artifact_id           TEXT NOT NULL REFERENCES artifacts(id)
  plan_sha256                TEXT NOT NULL
  plan_revision              INTEGER NOT NULL
  plan_id                    TEXT NOT NULL
  approval_id                TEXT NOT NULL REFERENCES approvals(id)
  task_contract_id           TEXT NOT NULL
  task_contract_sha256       TEXT NOT NULL
  sequence                   INTEGER NOT NULL CHECK(sequence > 0)
  request_hash               TEXT NOT NULL
  requested_profile          TEXT NOT NULL
  requested_provider         TEXT NOT NULL
  requested_model            TEXT NULL
  requested_reasoning        TEXT NULL
  actual_provider            TEXT NULL
  actual_model               TEXT NULL
  actual_reasoning           TEXT NULL
  provider_operation_ref     TEXT NULL
  provider_session_ref       TEXT NULL
  started_at                 TEXT NULL
  finished_at                TEXT NULL
  status                     TEXT NOT NULL
  result_classification      TEXT NULL
  baseline_repository_json   TEXT NULL
  final_repository_json      TEXT NULL
  workspace_changed          INTEGER NULL CHECK(workspace_changed IN (0,1))
  changed_paths_json         TEXT NULL
  diff_summary_json          TEXT NULL
  agent_result_json          TEXT NULL
  usage_json                 TEXT NULL
  error_classification       TEXT NULL
  error_detail               TEXT NULL
  created_at                 TEXT NOT NULL
  updated_at                 TEXT NOT NULL

  UNIQUE(workflow_id, plan_artifact_id, task_contract_id, sequence)
```

Attempt statuses are `preparing`, `running`, `succeeded`, `failed`,
`interrupted`, and `unknown`. Result classification carries precise values
such as `completed_changed`, `failed_unchanged`, `interrupted_unchanged`,
`failed_changed`, `interrupted_changed`, `safety_violation`,
`owner_uncertain`, and `recovered_unknown_unchanged`.

The generic `operations` row is an idempotent dispatch intent. The generic
`executions` row retains provider lifecycle, terminal result, capability
report, provider references, failure class, and usage. The attempt extension
retains repository/authority facts that do not belong in the generic runtime
contract.

### 12.2 Provider attempt is not Task revision

Attempt sequence increments operational history only. Retry attempt 2 binds to
the same immutable Plan artifact, Task Contract ID, and task payload hash. It
does not create Plan revision 2, a Task Contract revision, or a copied task.
Changing the Task Contract requires a new Plan revision and explicit approval;
the old Plan's attempt history remains immutable evidence.

### 12.3 Atomic boundaries

- Intent transaction: task `IMPLEMENTING`, workflow `IMPLEMENTING`, generic
  operation/execution, attempt, and lease appear together.
- Start transaction: accepted baseline and local process ownership become
  durable before meaningful provider work proceeds.
- Completion transaction: final evidence, execution/operation terminal state,
  attempt classification, task/workflow state, event, and safe lease release
  commit together.
- Crash before completion leaves a durable running/unknown attempt and lease;
  it never looks like success.

Canonical Plan/Feature Contract artifacts remain immutable. Implementation
results are operational records only. Repository files remain the authority
for code.

## 13. Success, failure, and interruption semantics

### 13.1 Decision matrix

| Provider/owner outcome | Repository evidence | Persisted result | Retry |
| --- | --- | --- | --- |
| Structured success, child stopped | changed; root/HEAD/branch/config/authority valid | attempt `succeeded/completed_changed`; task/workflow `IMPLEMENTATION_COMPLETED`; release lease | No; next boundary is VERIFY. |
| Structured success, child stopped | unchanged | attempt `failed/failed_unchanged`; task/workflow `IMPLEMENTATION_FAILED`; release lease | Later explicit `resume` only. |
| Known provider failure/timeout, child stopped | exact baseline unchanged | attempt `failed/failed_unchanged`; task/workflow `IMPLEMENTATION_FAILED`; release lease | Later explicit `resume` only. |
| Known provider failure/timeout, child stopped | changed | attempt `unknown/failed_changed`; task `IMPLEMENTATION_UNKNOWN`; workflow `HUMAN_ATTENTION`; release lease | Never automatic. |
| Ctrl+C, termination confirmed | unchanged | attempt `interrupted/interrupted_unchanged`; task/workflow `IMPLEMENTATION_FAILED`; release lease; CLI exits interrupted | Later explicit `resume` only. |
| Ctrl+C, termination confirmed | changed or safety violation | attempt `unknown/interrupted_changed`; task `IMPLEMENTATION_UNKNOWN`; workflow `HUMAN_ATTENTION`; release lease | No. |
| Ctrl+C/exception | child termination not proven | attempt `unknown/owner_uncertain`; task unknown; workflow human attention; retain lease | No writer until ownership reconciled. |
| Any terminal result | HEAD/branch/repository/config/control authority changed or final inspection fails | attempt `unknown/safety_violation`; task unknown; workflow human attention | No reset or retry. |

### 13.2 What success may claim

Human and JSON output may say:

> IMPLEMENT completed for T1. Repository mutation passed MDS #3 structural
> safety checks. Verification has not run.

It must not say `VERIFIED`, `REVIEWED`, `ACCEPTED`, `DONE`, `FEATURE COMPLETE`,
or workflow `COMPLETED`.

## 14. Crash recovery and retry

### 14.1 Restart reconciliation

Before considering a new writer, `resume` reconciles an existing lease and
attempt:

1. Revalidate lease/attempt/workflow/Plan/task binding.
2. Determine whether the exact persisted provider process identity is alive.
3. If alive or uncertain, return blocked/human-attention and retain the lease.
4. If definitely stopped, capture current repository/control identity.
5. If it equals the accepted baseline exactly, mark the old attempt
   `unknown/recovered_unknown_unchanged`, task/workflow
   `IMPLEMENTATION_FAILED`, release the lease, and stop this invocation. Do not
   dispatch a replacement in the same invocation.
6. If it differs, mark `IMPLEMENTATION_UNKNOWN/HUMAN_ATTENTION`, persist the
   candidate snapshot, and release only because the writer is proven stopped.
7. If inspection cannot prove either case, retain the lease.

This handles:

- started attempt + dead writer + unchanged workspace: safe boundary for a
  later retry;
- started attempt + dead writer + changed workspace: human attention;
- started attempt + unresolved ownership: no duplicate writer;
- provider success + changed workspace + crash before completion record:
  provider outcome remains unknown, so the diff alone cannot be promoted to
  success; human attention is required;
- persisted final-output JSON without a durable terminal execution record:
  advisory evidence only, never sufficient for success.

### 14.2 Retry policy and budget

The per-invocation dispatch budget is exactly one. It is enforced in the
orchestrator, not the prompt:

- no retry after provider failure;
- no retry after invalid structured output;
- no retry after Ctrl+C/recovery reconciliation;
- no Task #2;
- no Verify, Review, or Fix call;
- no model escalation.

A later `resume` may create a new attempt only when the prior attempt is
terminal, ownership is released, the workspace equals the original clean
baseline, the task is `IMPLEMENTATION_FAILED`, and exact Plan authority is
still active. Changed or unknown work requires explicit future reconciliation,
not blind redispatch. Attempts and usage metadata prepare for a later global
budget engine without implementing it now.

## 15. CLI and presentation

### 15.1 Entry behavior

No new command is added.

- `engineering-flow approve`: validates and records the exact Plan approval,
  prints that implementation has not started, and exits.
- `engineering-flow resume` from `plan/plan_approved`: invokes
  `ImplementationOrchestrator.resume_once()`, which may reconcile or dispatch
  one selected task, persist the result, and stop.
- `resume` from `implementation_failed`: may start one retry only after the
  safe-retry predicate passes.
- `resume` from `implementation_completed`: reports awaiting verification and
  dispatches nothing.
- `resume` from `human_attention` with changed/unknown implementation or an
  unresolved lease dispatches nothing.
- all existing Intake/Plan-feedback resume routes remain unchanged.

Approval and mutation are separate invocations. This preserves the current
MDS #2.2 contract and prevents an approval prompt from unexpectedly starting a
writer.

### 15.2 Output modes

TTY uses the existing progress abstraction with the selected task label:

```text
Implementing T1 · Add health command
✓ IMPLEMENT completed · 42.3s

Changed
  src/...
  tests/...

Implementation completed.
Verification has not run yet.
```

Non-TTY emits bounded start/terminal lines and one final human document. JSON
emits exactly one stdout document with no prompt, ANSI, progress, or provider
chatter; progress stderr remains empty in JSON mode. Changed paths are sorted
and bounded; no diff bodies are printed.

### 15.3 Status projection

`engineering-flow status` remains read-only and shows:

- approved Plan artifact UUID/SHA/revision/embedded ID and approval;
- each Plan task in canonical `T<N>` order with operational implementation
  state (default pending);
- selected/executed Task Contract ID and objective;
- attempt count and latest attempt UUID/classification/timestamps/profile;
- baseline/final HEAD and branch summaries;
- whether the workspace changed and a bounded changed-file list/count;
- active/unresolved writer ownership without raw PIDs in concise human output;
- retry-safe versus human-attention state;
- fixed `verification: NOT_RUN` after implementation.

Verbose/JSON may include hashes, provider operation reference, requested versus
actual profile metadata, and full bounded repository snapshot fields. It does
not dump diffs, stderr, prompts, or hidden provider reasoning.

## 16. Observability

Append sanitized events at durable boundaries:

- `implementation.selection.completed`;
- `implementation.preflight.rejected`;
- `implementation.attempt.created`;
- `implementation.writer.acquired`;
- `implementation.provider.started`;
- normalized `agent.runtime.*` events already accepted by policy;
- `implementation.repository.captured`;
- `implementation.completed`, `implementation.failed`,
  `implementation.interrupted`, or `implementation.unknown`;
- `implementation.writer.released` or `implementation.writer.unresolved`;
- `implementation.recovery.reconciled`.

Events carry IDs, classifications, elapsed duration, profile, usage when
reported, changed-path count, and snapshot fingerprints. They never carry raw
provider content, full diffs, secrets, or unbounded stderr. Attempt rows answer
which task/model/profile ran, why it ran, whether the workspace changed, and
whether a retry is safe.

## 17. Implementation slices

Each slice ends with focused tests plus the full authoritative suite and leaves
the repository coherent. No slice automatically continues into the next.

### Slice 1 — Approved authority and one deterministic selection

**Objective:** make exact V2 Plan approval consumable without copying Task
Contracts or dispatching a writer.

**Changes:**

- domain: task implementation states, canonical task payload hash, graph
  validator/selection outcomes, explicit numeric Task ID ordering;
- store: authority projection and `task_implementation_states` schema/read
  APIs; no V1 task import changes;
- orchestrator: pure authority+selection service that stops before mutation;
- status projection: approved Plan tasks show `pending` and selected candidate
  in tests/internal result only; CLI `resume` is not wired to a writer yet.

**Invariants:** only the highest exact approved V2 Plan is selectable; stale,
tampered, rejected, cancelled, changes-requested, and unapproved workflows fail
closed; dependency satisfaction requires `VERIFIED` evidence.

**Focused tests:** authority cases; exact task recovery/hash; missing/duplicate
IDs; invalid dependency/cycle; one/multiple/no executable tasks; all
implemented; explicit numeric ordering.

**Stopping boundary:** a deterministic candidate can be observed in tests but
no provider process or repository write can occur.

**Suggested checkpoint:** `feat(mds3): bind one task selection to approved v2 plan`

### Slice 2 — Clean baseline, durable attempt, and exclusive fake writer

**Objective:** prove mutation attribution and operational persistence with an
injected fake runtime before enabling real Codex writes.

**Changes:**

- repository inspector/snapshot and clean/nested-repository policy;
- `implementation_attempts` and `workspace_writer_leases` schemas;
- atomic acquire/start/complete/fail store methods linked to generic
  operations/executions;
- implementation orchestrator end-to-end with one injected fake writer;
- task/workflow implementation states and repository-truth classification.

**Invariants:** clean baseline required; one lease per workspace; one dispatch;
attempt intent precedes mutation; success requires actual changes and unchanged
HEAD/branch/identity; no commit/reset/stash.

**Focused tests:** clean/dirty/staged/untracked/ignored policies; branch/HEAD
baseline; nested/submodule rejection; second writer rejection; fake success;
success-without-change; provider failure unchanged/changed; no Task #2.

**Stopping boundary:** safe behavior is demonstrable entirely with fake local
writers; production Codex V2 dispatch remains disabled.

**Suggested checkpoint:** `feat(mds3): persist single-writer implementation attempts`

### Slice 3 — Bounded Codex IMPLEMENT runtime and routing

**Objective:** connect the proven orchestrator boundary to one scoped
write-enabled Codex call.

**Changes:**

- runtime: implementation purpose/profile and owned-process callback/contract;
- config: validated provider profile mappings and compatibility diagnostics;
- Codex adapter: implementation schema, explicit model/reasoning,
  workspace-write, ephemeral fresh process, process group, one-call output;
- orchestrator: authoritative context package, prompt, request hash, and
  provider result normalization.

**Invariants:** only Developer IMPLEMENT is writable; all other roles stay
read-only; exact task/profile/baseline binds the request; agent claims are not
repository truth; no retries or continuation.

**Focused tests:** low/medium/high and risk escalation profile mapping;
requested/actual telemetry; safe argv/cwd/environment; no bypass/add-dir;
structured output; fake subprocess success/failure; one provider call.

**Stopping boundary:** programmatic V2 orchestration can run one real-capable
IMPLEMENT request; no CLI entry or automatic follow-on phase exists.

**Suggested checkpoint:** `feat(mds3): add scoped codex implementation dispatch`

### Slice 4 — Interruption, crash reconciliation, and safety violations

**Objective:** make every writer exit/restart path fail closed according to
workspace mutation evidence.

**Changes:**

- process-group TERM/KILL/wait behavior and ownership identity persistence;
- restart lease reconciliation and exact unchanged comparison;
- post-execution HEAD/branch/config/control-authority checks;
- result matrix implementation and recovery events.

**Invariants:** no second writer while ownership is live/uncertain; unchanged
failure/interruption alone is retry-safe; changed or safety-violating outcome
is unknown/human-attention; no automatic rollback or inferred success.

**Focused tests:** Ctrl+C unchanged/changed/unconfirmed; crash with dead/live/
uncertain owner; success before completion-record crash; agent commit, branch
switch, Git config change, repository identity change, control-state tamper;
lease release only when ownership is resolved.

**Stopping boundary:** API-level recovery is restart-safe; human CLI still does
not trigger production mutation.

**Suggested checkpoint:** `feat(mds3): reconcile interrupted repository writers`

### Slice 5 — Resume/status UX and compatibility closure

**Objective:** expose exactly one implementation through the existing CLI and
close presentation, regression, and disposable-smoke readiness.

**Changes:**

- CLI services/routing: `resume` from `PLAN_APPROVED` only; approval remains a
  stop; JSON call budget one;
- presentation: task-labeled progress, changed summary, explicit NOT_RUN
  verification, retry/human-attention guidance;
- status/log JSON projections and bounded human/verbose output;
- compatibility corrections only where proven by the complete test matrix.

**Invariants:** one command/one task/one writer; no Verify/Review/Fix/commit;
JSON is one document; V1 and all clarification/Plan feedback/cancel paths are
unchanged.

**Focused tests:** CLI resume, approval separation, TTY/non-TTY/JSON, status,
selection and call counts, cancellation/rejection/revision/V1 regression, all
176 baseline tests plus new coverage.

**Stopping boundary:** MDS #3 acceptance is ready; do not start MDS #4.

**Suggested checkpoint:** `feat(mds3): expose single task implementation via resume`

## 18. Test strategy

Use `unittest`, temporary Git repositories, injected clocks/process identity,
fake runtimes/processes, and no sleeps. Test deterministic behavior before any
manual provider smoke.

### A. Authority

- `PLAN_APPROVED` V2 workflow required.
- Exact latest Plan artifact/UUID/hash/revision/approval and latest READY
  Feature Contract are required.
- Stale/tampered/superseded/changes-requested/unapproved Plan is rejected.
- Cancelled, rejected, clarification, pending approval, V1, and cross-repository
  workflows cannot implement.
- Authority is rechecked in the attempt/lease transaction and again before
  spawn.

### B. Selection

- One root selects exactly once.
- Multiple roots select lowest numeric `T<N>`.
- Array position alone cannot change selection.
- Invalid/missing/duplicate dependency and cycle fail closed.
- Non-`VERIFIED` dependency blocks; `IMPLEMENTATION_COMPLETED` is insufficient.
- All implemented means awaiting verification, not workflow completion.
- Exactly one Task Contract and no successor is dispatched.

### C. Working tree and baseline

- Clean tracked/index/untracked state is accepted.
- Dirty tracked, staged, conflict, and non-ignored untracked state is rejected.
- Ignored files are allowed and excluded from material code mutation.
- HEAD, attached branch, repository/Git dirs, status/diff/untracked hashes, and
  local Git config are persisted.
- Detached/unborn/non-Git/nested/submodule cases are rejected.

### D. Writer ownership

- Concurrent second `resume` cannot acquire or dispatch.
- Unknown or mismatched lease ownership remains fail-closed.
- Age/PID absence alone does not steal a lease.
- Safe terminal completion releases only the matching lease.
- Different repositories can own independent leases.

### E. Success

- One writer call and one selected task.
- Real fake-writer filesystem changes override agent claims.
- HEAD/branch/config remain unchanged and no commit exists.
- Baseline/final snapshots, changed paths, profile, usage, attempt, generic
  execution/operation, and task result persist atomically.
- Workflow is `IMPLEMENTATION_COMPLETED`, verification is `NOT_RUN`, Task #2 is
  not called, and no VERIFY/REVIEW/FIX occurs.

### F. Provider failure without changes

- Failure/timeout and exact unchanged snapshot persist
  `IMPLEMENTATION_FAILED/failed_unchanged`.
- Lease releases after child termination is proven.
- The same invocation does not retry; a later resume can retry once.

### G. Provider failure with changes

- Partial mutation persists final evidence and
  `IMPLEMENTATION_UNKNOWN/HUMAN_ATTENTION`.
- No reset/stash/cleanup or automatic retry occurs.

### H. Ctrl+C

- Owned process group receives TERM then bounded KILL/wait if needed.
- Confirmed unchanged interruption is safe for later resume.
- Changed interruption is human attention.
- Unconfirmed termination retains the lease and blocks duplicate writers.
- CLI interruption is traceback-free and durable.

### I. Crash/restart

- Started attempt and definitely dead owner reconcile against baseline.
- Exact unchanged recovery releases to a retryable boundary but does not retry
  in the reconciliation invocation.
- Changed recovery is human attention.
- Live/uncertain ownership blocks.
- Provider output or diff without durable completion cannot become success.

### J. Safety violations

- Commit/HEAD change, branch switch/detach, Git config change, repository
  identity change, control-artifact/database authority tamper, path escape, and
  unreadable final state all fail closed without rollback.

### K. CLI/presentation

- `resume` from `PLAN_APPROVED` starts exactly one task.
- `approve` does not implement in the same invocation.
- TTY progress is transient and bounded; non-TTY is line-oriented.
- JSON is one document with empty progress stderr and no ANSI/prompt/chatter.
- `status` exposes Plan/task/attempt/change/attention/NOT_RUN facts without a
  giant diff.

### L. Compatibility

- Intake clarification/recovery, Plan feedback/revisions/stale approval,
  cancellation, explicit rejection, selected workflow, derived Markdown, V1
  planning/task lifecycle, existing runtime schemas, and all 176 existing
  tests remain green.

Each slice runs targeted modules first, then:

```text
.venv/bin/python3 -m unittest discover -s tests -q
```

## 19. Manual acceptance smoke (document only)

Do not run this smoke while planning. After all deterministic tests pass,
create a disposable temporary Git repository, never the development checkout:

1. Add a committed `README.md`, a tiny Python/text file, `.gitignore`, and a
   minimal `AGENTS.md`; initialize Engineering Flow.
2. Use a trivial two-task feature whose first root task adds one small behavior
   and whose second task depends on `T1`.
3. Run Intake/Plan, inspect the Plan, and approve it.
4. Confirm `git status --porcelain=v2 -z --untracked-files=all` still shows no
   implementation mutation after approval (apart from ignored control state).
5. Run `engineering-flow resume` once with the inexpensive configured profile
   selected by the task's low complexity/risk.
6. Inspect `git diff --binary HEAD` and confirm exactly the first Task Contract
   was attempted, repository HEAD/branch did not change, and no commit exists.
7. Run `engineering-flow status` and confirm task 1 is
   `IMPLEMENTATION_COMPLETED`, verification is `NOT_RUN`, task 2 remains
   pending/dependency-blocked, and attempt/baseline/change metadata is visible.
8. Run `resume` again and confirm it dispatches neither task 2 nor VERIFY
   because the first implementation awaits MDS #4.
9. Remove the disposable repository after retaining only the intended manual
   acceptance report, if one is required by the implementation workflow.

Keep the feature tiny and use one provider call. Do not commit, push, create a
PR, or introduce a deliberate failure in a non-disposable repository.

## 20. Risks and mitigations

| Risk | Mitigation / accepted limitation |
| --- | --- |
| Duplicate writer | Unique durable repository lease in an immediate SQLite transaction; no expiry stealing; exact process ownership recovery. |
| Partial mutation | Clean baseline and post snapshot; changed failure/interruption becomes unknown/human-attention; no blind retry or cleanup. |
| Stale Plan execution | Re-parse/hash exact highest approved Plan and READY source at preflight, intent transaction, and pre-spawn; bind every attempt to IDs/hashes. |
| Dirty human work overwritten | Reject every staged/tracked/non-ignored untracked change; never stash/reset/clean. Ignored files are outside clean policy. |
| Agent-created commit | Require unchanged HEAD/branch; classify violation unknown; do not reset. |
| Branch/Git config change | Persist and compare branch/ref and local config evidence; human attention on drift. |
| Crash between mutation and completion persistence | Started attempt and lease precede spawn. Restart compares against baseline; changed state is unknown, unchanged may become retry-safe. |
| Provider success but missing local record | Never infer success from diff or final-output file. Changed candidate requires human attention. |
| Provider failure after writes | Filesystem truth overrides failure label; changed workspace is unknown/non-retryable. |
| False success from agent self-report | Require actual Git mutation and structural invariants; reported paths are advisory only. |
| Runaway retries/cost | One provider dispatch per invocation, one task, no escalation/Verify/Review/Fix; persist usage and attempts. |
| Self-hosting damage | Same safety rules, but acceptance uses disposable repositories only. |
| Control state inside writable repository | Exact control manifest/authority revalidation detects unexpected changes. Accepted MVP limitation: this is detection under a cooperative workspace-write sandbox, not hostile isolation. |
| External human/process edits during writer | Lease prevents Engineering Flow writers, not arbitrary processes. Post fingerprint detects drift but attribution is limited to the cooperative local model. |
| Huge repository/untracked hashing cost | Hash only Git-reported non-ignored untracked contents and Git diff/status evidence; persist bounded paths, not all tracked-file hashes or diff blobs. |
| Future MDS #4 integration | `IMPLEMENTATION_COMPLETED` is explicitly unverified; only future `VERIFIED` satisfies dependencies; attempt and final snapshot provide the verification baseline. |
| V1 schema collision | New V2-specific state/attempt tables; no reuse/import of V1 task definitions or cycle semantics. |
| Model availability/config drift | Exact Codex names live in validated configuration; capability/preflight fails before lease/spawn; requested versus actual metadata is explicit. |

## 21. Non-goals

MDS #3 explicitly excludes:

- deterministic VERIFY, including orchestrated tests/build/lint/format/typecheck;
- semantic REVIEW;
- FIX or any review/fix loop;
- autonomous execution of all tasks or feature completion;
- parallel task execution;
- worktree creation or worktree-based task isolation;
- automatic commits, pushes, branches, PRs, or delivery;
- generalized distributed locks/scheduling;
- generic rollback, automatic stash, reset, clean, or mutation repair;
- a complete hostile-code/security sandbox;
- a full centralized budget/token engine;
- automatic model escalation or multi-attempt provider loops;
- provider expansion beyond the existing Codex-first adapter;
- migration of V1 task manifests/cycles into V2;
- mutable Task Contract copies or Plan JSON execution annotations.

## 22. Resolved decisions

| Required decision | Resolution |
| --- | --- |
| Clean working tree | Required immediately before dispatch. |
| Untracked files | Every non-ignored untracked path is dirty and blocks; ignored files are allowed. |
| Task state names | Pending, implementing, implementation completed, implementation failed, implementation unknown. |
| Workflow after implementation | `task_execution/implementation_completed`, never workflow completed. |
| Task ordering | Numeric stable `T<N>` identity after full graph validation. |
| Dependency satisfaction | Only future `VERIFIED`; implementation completion is insufficient. |
| Writer ownership | Durable non-expiring SQLite workspace lease with exact local process identity; no TTL stealing. |
| Attempt persistence | V2 implementation-attempt extension linked to generic operation/execution plus identity/baseline/final evidence. |
| Safe retry | Only a terminal unchanged attempt with definitely stopped owner; later explicit resume, one call. |
| Interrupted recovery | Cancel owned process group; unchanged can later retry, changed is human attention, uncertain owner retains lease. |
| Runtime write permission | Codex workspace-write only for IMPLEMENT, rooted at target repository, no added directories/bypass. |
| Model routing | Efficient/balanced/strong from max(complexity, risk); exact model/reasoning in config. |
| CLI entry | Existing `resume`; approval remains authorization-only. |

There are no unresolved blocking decisions. The accepted security limitation is
explicit: MDS #3 provides cooperative scoped execution, exclusive Engineering
Flow ownership, and deterministic detection; it is not a complete malicious
code containment system.

## 23. Acceptance criteria

MDS #3 is complete only when all are true:

1. Only a local V2 workflow with the exact current hash-valid READY Feature
   Contract and exact highest explicitly approved Plan can create an
   implementation intent.
2. Every attempt persists workflow, Feature Contract, Plan, approval, Task
   Contract, request, profile, baseline, provider, final repository, and result
   identities described above.
3. The Task Contract is recovered from the immutable Plan; no mutable duplicate
   definition or Plan mutation exists.
4. Graph validation and numeric-ID selection are deterministic and provider
   independent; at most one root task is selected.
5. Only `VERIFIED` can satisfy a dependency; MDS #3 never produces it.
6. A Git worktree with existing HEAD, attached branch, no nested/submodule
   boundary, and no staged/tracked/non-ignored untracked change is required.
7. A baseline snapshot answers exactly which repository state authorized the
   writer, and a final snapshot/diff summary records actual mutation.
8. A durable lease prevents two Engineering Flow writers in one target
   workspace; stale/uncertain ownership is never silently stolen.
9. One invocation makes zero or one implementation provider call, never a
   second task, retry, Verify, Review, or Fix call.
10. Only IMPLEMENT receives workspace-write. Planning/review behavior and V1
    compatibility are unchanged.
11. Provider success becomes `IMPLEMENTATION_COMPLETED` only with material
    changes and unchanged repository/HEAD/branch/config/authority invariants.
12. Success leaves working-tree changes intact, creates no commit, preserves
    approved Plan authority, stops, and explicitly reports verification not
    run.
13. Provider failure/interruption with exact unchanged workspace is durably
    retryable only by a later explicit resume.
14. Provider failure/interruption with changed workspace, or any safety
    violation, is `IMPLEMENTATION_UNKNOWN/HUMAN_ATTENTION` and never blindly
    retried or reverted.
15. Ctrl+C terminates the owned process when possible, inspects state, persists
    the correct branch of the result matrix, and retains ownership when
    termination cannot be proven.
16. Restart reconciliation never infers success from a diff/provider file and
    never dispatches over live/uncertain ownership.
17. TTY, non-TTY, JSON, status, and logs expose bounded accurate state without
    raw provider chatter or giant diffs; JSON remains exactly one document.
18. Authority, selection, working-tree, ownership, success/failure,
    interruption, crash, safety, CLI, and compatibility tests in section 18
    pass deterministically.
19. The full repository test command passes and a later documented disposable
    real-provider smoke proves the one-task/no-commit/no-VERIFY boundary.
20. No behavior from MDS #4, #5, or #6 is implemented as part of MDS #3.
