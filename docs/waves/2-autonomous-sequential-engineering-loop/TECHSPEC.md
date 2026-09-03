# Technical Specification — Wave 2: Autonomous Sequential Engineering Loop

**Status:** Approved  
**Scope:** Wave 2 only, as defined by `docs/DELIVERY-PLAN.md`.

## 1. Scope

Wave 2 extends the accepted Wave 1 local Python control plane from an approved
task-plan artifact to a durable, sequential task lifecycle. It imports that
immutable approved plan, processes one task at a time, and for each task
coordinates Developer implementation, required-test evidence, an independent
Reviewer result, and (when needed) a bounded Developer remediation and
re-review cycle.

The successful Wave 2 runtime outcome is a persisted set of tasks whose
required tests and structured reviews have passed, ready for the independent
Wave-review acceptance process. Any unresolved execution, test, review, or
cycle-limit condition leaves the workflow in a recorded `HUMAN_ATTENTION`
state. It does not commit, push, create a PR, merge, perform release-level
final review, or start Wave 3.

## 2. Requirements Traceability

| Requirement | Wave 2 outcome |
| --- | --- |
| FR-001–FR-005 (task-stage portions) | The orchestrator owns ordered task progression; Developer and Reviewer receive only task-relevant, authoritative evidence. |
| FR-009 | A configured positive review-cycle limit is enforced durably; a failed review at the limit pauses for a recorded human intervention. |
| FR-011–FR-016 | One task is processed at a time through implementation, test evidence, independent structured review, remediation, and re-review; only a passing review with no blocking findings completes it. |
| FR-017–FR-021 (task/review portions) | Provider-neutral task/review contracts are implemented by the sole Codex adapter with capability checks appropriate to write or read-only work. |
| FR-022–FR-025 (task/review portions) | Task definitions, sessions, executions, tests, reviews, operation intents, artifacts, events, and outcomes survive restart without duplicate lifecycle work. |
| FR-030–FR-032; AC-005–AC-006 (task/review portions) | CLI status/logs expose task and review progress; failures are classified and policy-routed. |
| AC-002–AC-004 | Ordered task processing, review-failure remediation/re-review, limit-driven intervention, and completion only after tests and review pass are demonstrable. |

All applicable NFRs and constraints remain in force, particularly sequential
V1 execution, provider-neutral domain boundaries, independent review whenever
practical, sanitized evidence, workspace/repository validation, bounded
operations, and no autonomous merge.

## 3. Current-State Context and Preconditions

Wave 1 already provides `PlanningOrchestrator`, `WorkflowStore`, immutable
hashed artifacts, idempotent operation intents, logical sessions/executions,
SQLite/WAL persistence, normalized events, a thin CLI, and a Codex adapter
that supports read-only planning. A completed Wave 1 workflow has stage
`READY_FOR_WAVE_2`, status `COMPLETED`, and an approved immutable task-plan
artifact. Those records remain authoritative; Wave 2 must not regenerate,
rewrite, or re-approve planning artifacts.

The active Wave-start authorization is valid for this TECHSPEC: Wave 1's
authoritative PASS review is at
`tasks/1-controlled-planning-workflow/reviews/WAVE-REVIEW.md`, its recorded
SHA-256 matches that artifact, and the committed authorization grants only
creation of this document.

Implementation retains the standard-library approach and the package
boundaries established in Wave 1. Existing public planning command forms and
persisted planning workflows remain compatible. Schema changes are additive
SQLite migrations performed by `WorkflowStore` at open time.

## 4. Lifecycle Design

### 4.1 Runtime states

Add `TASK_EXECUTION` and `TASKS_READY_FOR_WAVE_REVIEW` to `Stage`. The latter
is a terminal runtime stage for this Wave only; it is not Wave acceptance and
does not authorize a later Wave, Git, or PR activity. A workflow beginning at
`READY_FOR_WAVE_2` transitions only after successful task-plan import:

```text
COMPLETED(READY_FOR_WAVE_2)
  -> RUNNING(TASK_EXECUTION)
  -> task N: developer -> required tests -> reviewer
       -> PASS/no blocking findings: task accepted -> task N+1
       -> FIX_REQUIRED below limit: developer fix -> tests -> new reviewer
       -> failed tests, unknown result, exhausted limit, safety/provider failure:
          HUMAN_ATTENTION(TASK_EXECUTION)
  -> COMPLETED(TASKS_READY_FOR_WAVE_REVIEW)
```

Only the orchestrator may select a task, dispatch an execution, increment a
cycle, accept a task, or advance to the next task. A provider response is
evidence, never a state-transition instruction. On every call that can drive
work, it first obtains the persisted workflow and task state; it never derives
progress from prose, the current Git diff, or transient provider context.

The execution entry point is the existing `resume --workflow ID`: for a Wave
1-complete workflow, it imports the approved plan and starts Wave 2. For an
in-progress Wave 2 workflow it performs only the persisted next permitted
action. Terminal `TASKS_READY_FOR_WAVE_REVIEW` returns unchanged. This keeps
the existing CLI surface compatible while making the approved task plan the
only start condition.

### 4.2 Task-plan import contract

The approved task-plan Markdown must contain exactly one fenced JSON block
tagged `engineering-flow-task-plan`. It is an immutable manifest embedded in
the authoritative artifact, not a second mutable plan file:

```json
{
  "version": 1,
  "tasks": [
    {
      "key": "TASK-001",
      "title": "Short imperative outcome",
      "instructions": "Bounded implementation objective.",
      "acceptance_criteria": ["Observable criterion"],
      "required_tests": ["pytest -q tests/test_feature.py"],
      "context_paths": ["docs/design.md", "src/package/module.py"]
    }
  ]
}
```

`key`, `title`, and `instructions` are non-empty strings; task keys are unique
and their array order is execution order. `acceptance_criteria` and
`required_tests` are non-empty ordered string arrays. `context_paths` is an
optional ordered list of repository-relative paths. It may name only existing
files within the validated target repository; path escapes, directories,
duplicates after canonicalization, an empty task list, unsupported version, or
malformed JSON reject import before any provider execution. The full Markdown
remains human-readable planning evidence; the manifest is the normative
machine-readable task contract for Wave 2.

Import atomically records each immutable definition and its SHA-256 alongside
the source task-plan artifact ID and hash. Re-import of the same source hash
returns the existing task records. A differing manifest after import is an
artifact-corruption/conflict condition and enters `HUMAN_ATTENTION`; Wave 2
does not reinterpret an approved plan. A legacy or otherwise approved plan
without the manifest also enters `HUMAN_ATTENTION` with an actionable reason;
it is never guessed from headings or agent prose.

### 4.3 Per-task decision rules

Each imported task starts `PENDING`. The orchestrator selects the lowest-order
non-accepted task; it may not dispatch another task while one is active.

1. It runs the Developer for initial implementation (cycle 1) or remediation
   (the current cycle after a review failure).
2. A successful Developer result must report passing evidence for every exact
   `required_tests` command in the task definition. A missing, duplicate,
   mismatched, or failed required test result is a `TEST` failure and pauses
   the task for human attention; the Reviewer is not dispatched.
3. It invokes a fresh independent Reviewer session. A review is a PASS only
   when the structured outcome is `PASS` and it contains no blocking finding.
   That atomic transition marks the task `ACCEPTED` and emits its completion
   event.
4. A `FIX_REQUIRED` review below `max_review_cycles` persists the findings,
   creates a remediation intent for the Developer's task-local session, and
   repeats test evidence then review. A re-review always uses a new Reviewer
   session.
5. A `FIX_REQUIRED` result at the limit is preserved, then transitions to
   `HUMAN_ATTENTION` without dispatching another fix. The initial review
   counts as cycle 1; every completed re-review increments the count. Thus the
   configured limit is never exceeded autonomously.

An explicit human intervention record is required before a limit-paused task
can resume autonomous activity. The CLI command
`intervene --repo PATH --workflow ID --task ID --reason TEXT` records the
actor, timestamp, reason, prior cycle evidence, and a new autonomous review
window. It does not mark the task passed, alter review evidence, skip the
task, or loosen the configured per-window limit. After intervention, `resume`
begins a new Developer remediation attempt and the configured limit again
applies. This is a human decision boundary, not an automatic retry loophole.

Unknown provider outcomes, incomplete pending operations recovered after a
process loss, non-retriable provider/authentication/tool failures, invalid
structured output, and unapproved plan integrity failures also stop at human
attention. A recorded, explicit intervention is required before a subsequent
attempt; no completed operation, task acceptance, test record, or review is
repeated.

## 5. Components and Responsibilities

| Module | Wave 2 change and responsibility |
| --- | --- |
| `domain.py` | Add task stages/statuses, Developer/Reviewer roles, `TEST` and `REVIEW` failure classifications, immutable task/cycle/intervention values, and generic task/review request/result values. |
| `orchestrator.py` | Evolve `PlanningOrchestrator` into a workflow orchestrator (with a compatibility alias if needed). It imports plans, selects exactly one task, builds bounded requests, evaluates structured results, and owns all transitions. |
| `store.py` | Add migrations and transactional queries for task definitions, cycles, task artifacts, intervention records, task-correlated sessions/executions, and task operation intent/completion/recovery. |
| `runtime.py` | Generalize planning-only protocol names to provider-neutral engineering execution contracts while retaining planning compatibility. Define capability, Developer, and Reviewer contracts. |
| `codex_cli.py` | Add feature-detected workspace-write Developer execution and read-only Reviewer execution; preserve no-shell invocation, bounded timeout, JSONL event normalization, output-schema validation, and session references. |
| `config.py` | Add validated execution policy values: positive `max_review_cycles`, positive `timeout_seconds`, and explicit booleans enabling workspace-write Developer work and read-only Reviewer work. The captured workflow snapshot is authoritative for the run. |
| `cli.py` | Extend status/log payloads with task/cycle/intervention summaries and add the `intervene` command; it remains a thin adapter without transition rules. |
| tests | Extend deterministic fakes and integration coverage for the task lifecycle, persistence, sessions, limits, output validation, CLI, and safety policy. |

No Git/PR integration is added. Provider adapters do not persist workflow
state, write task artifacts, declare acceptance, or decide retry/cycle policy.

## 6. Provider, Session, and Structured-Result Contracts

### 6.1 Capability and execution boundary

Replace planning-specific capability verification with
`verify_capabilities(repository, required_capabilities)`. The report records
the available executable, validated non-bare Git worktree, JSON events,
output-schema support, output-last-message support, and the requested sandbox
mode. Capability checks run before every Developer or Reviewer dispatch and
the sanitized report is persisted with its execution intent.

Developer execution requires `workspace_write`, JSON events, structured final
output, and a bounded timeout. Reviewer execution requires `read_only`, JSON
events, structured final output, and a bounded timeout. The Codex adapter must
construct an argument vector without a shell, use the validated repository as
`cwd`, and request only the mode needed by the role. It must reject an adapter
that cannot prove the requested capability; it must not fall back from a
Reviewer to workspace-write.

The logical Developer session is task-local and is reused across the initial
implementation and its fix attempts. The Codex adapter uses a provider resume
mechanism only when verified by the installed CLI; otherwise it opens a new
provider session and receives a bounded continuity bundle (the task contract,
prior Developer result, required-test evidence, and current review findings).
That fallback is persisted as `agent.session.continuity_degraded`. A Reviewer
always receives a distinct logical session and must never receive a Developer
session ID.

### 6.2 Authoritative input and context rules

Developer input contains: the immutable task definition, source task-plan
artifact path/hash, only its declared canonical `context_paths`, relevant
approved planning artifact references, its own previous result and the latest
structured findings when fixing, plus repository path and policy-derived
instructions. It excludes other task definitions, unrelated review history,
and future-Wave/release material.

Reviewer input contains: immutable task definition; required tests; the latest
Developer/test result artifacts; declared context files; and repository path.
It excludes Developer session transcripts and credentials, and uses read-only
access. Both prompts explicitly say that the agent has no authority to select
the next task, record a pass, change the workflow, authorize delivery, or
perform Git delivery.

### 6.3 Normative final payloads

All provider output consumed for lifecycle decisions must be the schema-checked
final payload, not JSONL progress prose. Provider-specific data remains
sanitized metadata.

Developer payload:

```json
{
  "summary": "string",
  "changed_files": ["repository-relative path"],
  "test_results": [
    {"command": "exact required command", "passed": true, "summary": "string"}
  ]
}
```

Each required command must occur exactly once, must have `passed: true`, and
no unrecognized command may be represented as satisfying it. The optional
additional-test results may be retained separately but never replace a
required command. `changed_files` is evidence only and is canonicalized before
display; it does not authorize Git staging.

Reviewer payload:

```json
{
  "outcome": "PASS | FIX_REQUIRED",
  "summary": "string",
  "findings": [
    {
      "id": "stable finding ID",
      "severity": "blocking | non_blocking",
      "description": "string",
      "path": "optional repository-relative path",
      "line": "optional positive integer"
    }
  ]
}
```

`PASS` requires an empty findings array. `FIX_REQUIRED` requires at least one
blocking finding and is the only autonomous-remediation outcome in this Wave.
Non-blocking observations may be preserved only with a PASS when they do not
require remediation; their IDs must remain unique within the payload. Any
schema or semantic violation is an `AGENT_EXECUTION` failure and cannot change
task state.

## 7. Persistence, Artifacts, and Idempotency

Keep the Wave 1 SQLite database, WAL mode, foreign keys, single-writer lock,
UTC timestamps, sanitization, and immutable hash verification. Add additive
migrations for these records:

| Record | Minimum durable fields |
| --- | --- |
| `tasks` | ID, workflow ID, ordinal, key, title, canonical definition JSON/hash, source task-plan artifact ID/hash, status, current review-window/cycle, accepted timestamp; unique `(workflow_id, ordinal)` and `(workflow_id, key)`. |
| `task_cycles` | ID, task ID, review window and number, Developer execution ID, required-test artifact ID, Reviewer execution ID, review artifact ID, outcome, timestamps. |
| `task_artifacts` | ID, task ID, optional cycle ID, type (`definition`, `developer_result`, `test_result`, `review_result`), immutable canonical path, SHA-256, source execution ID, timestamp. |
| `interventions` | ID, task ID, actor, required reason, prior window/cycle, created timestamp. |
| extended sessions/executions/operations | Nullable task/cycle correlation and work kind (`develop`, `fix`, `review`); the existing planning rows remain valid. |

Task evidence lives under the existing workflow workspace, for example:

```text
workflows/<workflow-id>/
  tasks/001-TASK-001/
    definition.json
    cycles/001/developer-result.json
    cycles/001/required-tests.json
    cycles/001/review-result.json
```

The original task-plan artifact remains the source of truth. These files are
normalized evidence, written only by the store to fixed canonical destinations
and verified against recorded hashes before later use or CLI display.

Create a durable pending operation and task-correlated execution before calling
the provider. Use stable keys:

```text
workflow:<workflow-id>:task:<task-id>:window:<n>:cycle:<n>:develop
workflow:<workflow-id>:task:<task-id>:window:<n>:cycle:<n>:fix
workflow:<workflow-id>:task:<task-id>:window:<n>:cycle:<n>:review
```

Within a completion transaction, persist sanitized terminal metadata, the
immutable result artifact, operation completion, task/cycle state, and all
correlated events. Replaying a completed key returns its recorded result.
After restart, a pending or unknown task operation is marked unknown and
routes to human attention rather than launching a second provider call. Task
acceptance and next-task selection occur atomically with their events, so a
resume cannot accept twice or begin two tasks.

## 8. Configuration, CLI, Events, and Failure Behavior

The generated repository-local configuration gains an `[execution]` table:

```toml
[execution]
max_review_cycles = 3
allow_workspace_write_development = true
allow_read_only_review = true
```

`max_review_cycles` is a positive integer. Both booleans must be exactly true
for Wave 2; disabling either is a configuration/safety failure before a
provider process starts. Existing initialized repositories must receive an
explicit, non-destructive configuration migration: a missing `[execution]`
table fails with an actionable message until the owner adds the normative
values. `init` creates it for new repositories. The complete validated policy
is captured in each new workflow snapshot; later config-file changes do not
silently change an in-flight workflow.

CLI adds:

```text
engineering-flow intervene --repo PATH --workflow ID --task ID --reason TEXT
```

`status --json` includes ordered task key/title/status, active task, current
window/cycle, latest test/review outcome, and whether intervention is required.
`logs --json` emits the existing monotonic event stream with task and cycle
correlation. Output never prints raw provider environment, credentials,
unredacted diagnostics, or full session transcripts.

New normalized event categories include `task.imported`, `task.started`,
`task.developer.completed`, `test.completed`, `review.completed`,
`review.fix_required`, `task.accepted`, `review.limit_reached`, and
`task.intervention.recorded`. Provider events remain under
`agent.runtime.*`. All lifecycle events carry workflow plus applicable task,
cycle, artifact, and execution correlation IDs.

Failure classification adds `test` and `review`; provider, authentication,
tool, workflow, persistence, and agent-execution classifications retain their
Wave 1 meaning. A configured retry policy never retries an unknown result and
never bypasses review-cycle limits. Human rejection, task-plan validation,
authentication, corruption, and prohibited capability conditions are visible
as actionable paused/failed states rather than inferred from prose.

## 9. Security and Operational Controls

- Validate the target repository and every task context/result path against
  its canonical root. No provider-supplied path controls artifact destinations.
- Use workspace-write only for the Developer and only after policy/capability
  preflight. Reviewer execution remains read-only. No shell command strings,
  unrestricted environment persistence, or credential values are allowed.
- Treat Developer changed-file claims, test summaries, review findings, and
  all provider text as untrusted evidence. Schema validation, exact test
  matching, and orchestrator policy determine transitions.
- Preserve the existing timeout and minimal-environment controls. A timeout or
  process loss has no implied successful result and routes to human attention.
- Do not let agents invoke product-controlled Git delivery. Wave 2 records no
  commit/push/PR operation and does not broaden destructive-command policy.

## 10. Validation Strategy

Automated validation uses standard-library `unittest` with deterministic fake
runtimes; the suite must not require live credentials or a live Codex call.

| Behavior / risk | Validation |
| --- | --- |
| Sequential execution and task-plan authority (AC-002) | Import a valid approved manifest with multiple tasks; assert one active task, ordered dispatch, immutable source/hash checks, and rejection of malformed/escaping manifests. |
| Required tests and task completion (AC-002, AC-004) | Assert exact required-test evidence is required before review; failed/missing/mismatched results cannot dispatch review or accept a task. |
| Independent structured review (AC-002, AC-004) | Assert distinct Developer/Reviewer logical session IDs, Reviewer read-only capability, semantic payload validation, and PASS/no-blocking-only acceptance. |
| Remediation and limits (AC-003) | Exercise FIX_REQUIRED -> same Developer task continuity -> required tests -> fresh Reviewer; verify cycle counting, limit pause, immutable findings, and explicit intervention before another window. |
| Recovery and duplicate protection (AC-005) | Interrupt before intent, during provider execution, after result artifact write, after review persistence, and after task acceptance; reopen SQLite and verify no duplicate execution, cycle, evidence, task acceptance, or next-task launch. |
| Observability and CLI (AC-006) | Assert status/log task summaries, monotonic correlated events, `intervene` input validation, stable error/exit mapping, and redaction. |
| Codex adapter and safety | Fixture-test capability checks, workspace-write Developer argv, read-only Reviewer argv, JSONL/schema failure, timeout/authentication classification, session-resume feature detection/fallback, and no-shell behavior. |
| Regression | Retain Wave 1 planning tests and verify a formerly completed `READY_FOR_WAVE_2` workflow begins task import only via the new Wave 2 resume path. |

Minimum checks are `python -m unittest discover -s tests` and
`python -m compileall -q src`. Manual acceptance in a disposable Git
repository, with authenticated Codex, must demonstrate two ordered tasks,
passing tests and independent review for each, one review-fix-re-review cycle,
limit-driven human attention, explicit intervention/resume, restart recovery,
and absence of commit, push, or PR side effects.

## 11. Risks, Assumptions, and Open Questions

**Assumptions:** future Wave 1 task-plan generation will emit the specified
manifest; Codex capability preflight can distinguish workspace-write from
read-only use; and a target repository permits the Developer's bounded agent
work under the configured provider sandbox.

**Risks:** an existing approved task plan may lack the manifest and will need
human remediation rather than automatic interpretation; a provider may not
support session resume, in which case bounded persisted continuity is used;
and workspace-write increases execution risk, mitigated by repository
validation, role-specific capability gates, timeouts, and review.

**Open technical question (non-blocking):** the exact Codex CLI resume flag and
capability signal must be feature-detected from the installed version during
implementation. It does not alter the provider-neutral continuity contract or
permit a fallback that loses required persisted evidence.

## 12. Implementation Boundaries and Context Surface

Downstream task decomposition should remain focused on: (1) domain/store
migrations and task-plan import; (2) runtime/Codex contracts; (3) orchestrator
state transitions and recovery; (4) configuration/CLI observability; and (5)
deterministic tests. Each task can reference its relevant numbered sections,
the approved architecture overview, and the named current source modules.
No future-Wave delivery design is required. The Wave remains one coherent
vertical outcome, so no Delivery Plan decomposition concern is identified.
