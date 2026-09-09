# Bootstrap Codex Wave Workflow Controller — Design

## Executive decision

Adopt a temporary **thin deterministic Python Wave Controller** invoked by the
Codex Wave Host. It is a small bootstrap program, not a prompted LLM
Coordinator, autonomous agent, Skill, product architecture, or engineering
role. It controls exactly one authorized Wave by reading and validating one
persisted control record and existing authoritative artifacts, then returning
the next permitted action or a deterministic stop.

The Controller never performs engineering work; Codex role subagents use the
existing repository Skills for that work. It does not interpret code quality
or decide whether an engineering result is correct. Its transition rule is
strict: a transition is permitted only when
the required current authoritative artifact and a matching durable result
envelope both exist, their recorded target identity matches the current
checkout identity, and no human gate is pending.  Ambiguity blocks rather than
being repaired by inference.

The bootstrap is deliberately Wave-local and ends at `WAVE_ACCEPTED`. It
neither starts nor authorizes a later Wave, accepts the release, nor performs
Git delivery.

## Goals and non-goals

Goals:

- Remove manual selection, dispatch, and bookkeeping of the complete
  TECHSPEC-to-Wave-acceptance lifecycle for one authorized Wave.
- Preserve the existing Skills and their authoritative Markdown artifacts as
  the engineering contracts and evidence.
- Make a new Codex host able to determine the next valid action from the
  checkout, the control record, and authoritative artifacts alone.
- Preserve independent task and Wave review through a fresh, bounded child.
- Prevent stale checkout evidence, concurrent writers, missing evidence, and
  authority gaps from advancing the lifecycle.

Non-goals:

- Implementing Engineering Flow, a database, provider abstraction,
  `AgentRuntime` abstraction, generic capability registry, event bus,
  workflow DSL, plugin system, Codex SDK integration (unless later proven
  strictly necessary), PR/delivery automation, release lifecycle, or generic
  multi-provider support.
- Revising Skills, AGENTS.md, approved product/delivery/architecture contracts,
  TECHSPECs, task definitions, or historical evidence.
- Replacing `review-task`, `wave-review`, or human approval with Controller
  judgment.
- Strong OS, filesystem, permission, or worktree isolation.  The discovery
  evidence establishes only sufficient conversational isolation with shared
  checkout constraints.

## Existing constraints

The approved PRD, Delivery Plan, and architecture overview require the
orchestrator—not the provider—to own stage progression; distinguish task,
Wave, release, and authorization facts; use sequential task execution; retain
independent review; and reconcile interruptions without duplicated lifecycle
effects.  Wave 2 owns task-loop mechanics and ends at
`TASKS_READY_FOR_WAVE_REVIEW`; Wave 3 owns the eventual product governance.
This design must not pre-implement either boundary.

The existing Skill contracts are binding:

- `create-techspec` creates one approval-ready TECHSPEC and stops.
- `create-tasks` requires the active exact-revision TECHSPEC approval,
  creates its canonical task set, and stops for task-plan approval.
- `execute-task` leaves a task `IMPLEMENTED`/ready for review, never accepted.
- `review-task` alone supplies task-level `PASS`; a `FIX_REQUIRED` record is
  the fixer handoff, and a later PASS supersedes it.
- `fix-task` returns a task to review-ready state, never PASS.
- `wave-review` alone supplies Wave `PASS`, classifies remediation ownership,
  and persists the authoritative Wave review.
- `fix-wave-review` remediates only executable Wave-local findings and returns
  evidence, not acceptance.

The subagent discovery is established bootstrap evidence and is not to be
repeated: Codex CLI 0.153.4 has stable enabled multi-agent support; a child
with `fork_turns="none"` excluded parent conversational context in the
controlled experiment; children nevertheless share cwd, checkout, instructions,
and host capability surface; no spawn worktree selector exists.  Therefore
reviewer isolation is **SUFFICIENT_WITH_CONSTRAINTS**, not strong isolation.

## Proposed architecture and responsibility boundary

```text
Human -- explicit approvals/authorizations only --> Codex Wave Host
Codex Wave Host -- invokes/status/next/result --> Thin Deterministic Python Wave Controller
Python Wave Controller -- bounded state/transition/handoff metadata --> Codex Wave Host
Codex Wave Host -- one bounded dispatch --> fresh role child + existing Skill
Role child -- authoritative engineering evidence --> repository Markdown/code
Codex Wave Host -- result/artifact references --> Python Wave Controller
Python Wave Controller -- validated control record --> next action or stop
```

The distinction is mandatory:

| Workflow stage | Required domain capability | Agent role execution | Current mechanism |
| --- | --- | --- | --- |
| TECHSPEC planning | technical design | Architect | `create-techspec` Skill |
| task planning | task decomposition | Planner | `create-tasks` Skill |
| task implementation | task implementation | Developer | `execute-task` Skill |
| task acceptance review | independent task review | Reviewer | `review-task` Skill |
| task remediation | task finding remediation | Fixer | `fix-task` Skill |
| Wave acceptance review | independent Wave review | Wave Reviewer | `wave-review` Skill |
| Wave-local remediation | Wave finding remediation | Wave Remediator | `fix-wave-review` Skill |

Domain capability is not a Skill name, role, Codex model, or provider/runtime.
The table is a temporary Codex mapping owned by the bootstrap procedure, not a
universal domain registry.

The Controller owns only deterministic workflow mechanics: parsing and
validating persisted Wave state; lifecycle transitions and preconditions;
human-gate detection; dependency readiness; attempt/review-cycle counters;
checkout fingerprint capture and stale-result detection; one writer lease;
atomic control-state persistence; artifact/hash and result-envelope validation;
interruption reconciliation; next-capability determination; and deterministic
handoff metadata construction. Ambiguous evidence or authority yields
`BLOCKED`/`HUMAN_ATTENTION`.

It must not write TECHSPEC content, decompose tasks, implement code, review
code, fix findings, make architectural judgments, approve human gates,
interpret code quality, invent remediation ownership, bypass Skills, perform
release/Git delivery, or call itself an agent. It is the sole writer of the
control record; an LLM must never rewrite workflow state directly.

The Codex Wave Host remains the runtime-facing layer. It invokes the
Controller; requests status/next allowed action; uses Controller-produced
handoff metadata; spawns the required Codex child; selects the requested
model/reasoning tier where supported; waits for completion; returns child
result/artifact references to the Controller; and stops on `HUMAN_ACTION`,
`BLOCKED`, or `WAVE_ACCEPTED`. The Host must not independently re-decide
lifecycle state. If Host prose conflicts with Controller state, Controller
state plus authoritative artifacts win.

## Wave lifecycle/state model

Use the repository terminology where it exists.  The bootstrap has **19
named lifecycle states**; execution states mean an operation has been
dispatched or is awaiting reconciliation, not that a child response itself is
trusted.

The lifecycle is unchanged. Its controlling rule is:

```text
authoritative artifacts + persisted human authority + current checkout identity
+ deterministic Controller transition rules = next permitted workflow action
```

An LLM must not infer transitions independently.

| State | Meaning / next permitted action |
| --- | --- |
| `WAVE_AUTHORIZED` | Valid exact Wave-start authorization recorded; enter TECHSPEC planning. |
| `TECHSPEC_REQUIRED` | Dispatch technical-design capability. |
| `TECHSPEC_EXECUTION` | Reconcile or await Architect result; no other dispatch. |
| `AWAITING_TECHSPEC_APPROVAL` | Stop for explicit human approval of the exact TECHSPEC revision. |
| `TASK_PLAN_REQUIRED` | Validate active exact-revision TECHSPEC approval, then dispatch canonical task decomposition. |
| `TASK_PLAN_EXECUTION` | Reconcile or await Planner result. |
| `AWAITING_TASK_PLAN_APPROVAL` | Stop for explicit human approval of the exact task set. |
| `TASK_EXECUTION_REQUIRED` | Select exactly one dependency-ready unaccepted task. |
| `TASK_IMPLEMENTATION` | Reconcile or await Developer result for that task. |
| `TASK_REVIEW_REQUIRED` | Dispatch a fresh independent task review for the current implemented task. |
| `TASK_REVIEW` | Reconcile or await the Reviewer result. |
| `TASK_FIX_REQUIRED` | Latest valid review is `FIX_REQUIRED`; choose fix capability for that task. |
| `TASK_FIX` | Reconcile or await Fixer result. |
| `TASKS_READY_FOR_WAVE_REVIEW` | Every required task has a current authoritative task-review PASS. |
| `WAVE_REVIEW_REQUIRED` | Validate Wave-review prerequisites and dispatch a fresh Wave Reviewer. |
| `WAVE_REVIEW` | Reconcile or await Wave Reviewer result. |
| `WAVE_REMEDIATION` | Route unresolved Wave findings only under their ownership contract. |
| `WAVE_ACCEPTED` | Authoritative current Wave review is PASS; terminal state. Stop. |
| `HUMAN_ATTENTION` | Evidence, authority, environment, conflict, manual action, or limit requires a human decision/action. Stop. |

`WAVE_ACCEPTED` and `HUMAN_ATTENTION` are terminal for a Controller run.
An approved human intervention can create a new explicitly recorded transition
out of `HUMAN_ATTENTION`; it cannot be inferred from chat.  There is no
`NEXT_WAVE` state.

### Transition table

| From | Preconditions/evidence the Controller verifies | Dispatch or decision | To |
| --- | --- | --- | --- |
| `WAVE_AUTHORIZED` | Exact active Wave-start authorization, predecessor PASS when applicable, no conflicting authorization | Record validated authorization pointers | `TECHSPEC_REQUIRED` |
| `TECHSPEC_REQUIRED` | Wave scope and upstream sources identifiable | Architect / technical-design capability | `TECHSPEC_EXECUTION` |
| `TECHSPEC_EXECUTION` | Envelope is completed, target identity matches, TECHSPEC exists and is scoped; no escalation | Persist result pointer | `AWAITING_TECHSPEC_APPROVAL` |
| `TECHSPEC_EXECUTION` | `BLOCKED` or `SPEC_CHANGE_REQUIRED`, missing/conflicting/stale evidence, interruption | Record blocker; do not retry blindly | `HUMAN_ATTENTION` |
| `AWAITING_TECHSPEC_APPROVAL` | Exact approved revision and approval evidence authenticated by the human process | Record only the evidence reference/hash | `TASK_PLAN_REQUIRED` |
| `TASK_PLAN_REQUIRED` | Exact active TECHSPEC approval is stage-correct and binds the selected Wave, current TECHSPEC path, and hash | Planner / task-decomposition capability | `TASK_PLAN_EXECUTION` |
| `TASK_PLAN_EXECUTION` | Completed matching envelope, task index and definitions exist, no escalation | Persist result pointer | `AWAITING_TASK_PLAN_APPROVAL` |
| `TASK_PLAN_EXECUTION` | Blocked/spec change/missing/conflicting/stale evidence | Stop with reason | `HUMAN_ATTENTION` |
| `AWAITING_TASK_PLAN_APPROVAL` | Exact approved task-set evidence | Record evidence reference/hash | `TASK_EXECUTION_REQUIRED` |
| `TASK_EXECUTION_REQUIRED` | Exact active task-plan approval binds the current task-plan path and hash; select first ordered PENDING/eligible task whose every declared dependency has current authoritative PASS | Developer / task-implementation capability | `TASK_IMPLEMENTATION` |
| `TASK_IMPLEMENTATION` | Completed matching envelope, task is IMPLEMENTED or equivalent ready-for-review evidence, required validation is recorded | Persist envelope | `TASK_REVIEW_REQUIRED` |
| `TASK_IMPLEMENTATION` | Blocked/spec change, missing/stale result, or writer conflict | Stop | `HUMAN_ATTENTION` |
| `TASK_REVIEW_REQUIRED` | Current task implementation identity is stable; no other writer; task has ready-for-review evidence | Fresh Reviewer / independent task-review capability | `TASK_REVIEW` |
| `TASK_REVIEW` | Current authoritative review is PASS and matching envelope/checkouts | Mark task accepted only by evidence | `TASK_EXECUTION_REQUIRED`, or `TASKS_READY_FOR_WAVE_REVIEW` if all tasks PASS |
| `TASK_REVIEW` | Current authoritative review is FIX_REQUIRED and matching envelope/checkouts | Record review reference/findings pointer | `TASK_FIX_REQUIRED` |
| `TASK_REVIEW` | Review is BLOCKED or SPEC_CHANGE_REQUIRED; missing/conflicting/stale evidence | Stop | `HUMAN_ATTENTION` |
| `TASK_FIX_REQUIRED` | Latest applicable review is exact `FIX_REQUIRED`; cycle limit has not required intervention | Fixer / task-remediation capability | `TASK_FIX` |
| `TASK_FIX` | Completed matching envelope and IMPLEMENTED/ready-for-re-review evidence | Increment review attempt; never accept | `TASK_REVIEW_REQUIRED` |
| `TASK_FIX` | FIX_REQUIRED still unresolved, BLOCKED, spec change, limit reached, missing/stale evidence | Stop | `HUMAN_ATTENTION` |
| `TASKS_READY_FOR_WAVE_REVIEW` | Every expected task has current independent PASS; index/review evidence agree; Wave prerequisites validate | Record prerequisite snapshot | `WAVE_REVIEW_REQUIRED` |
| `WAVE_REVIEW_REQUIRED` | Stable checkout identity and complete prerequisite evidence | Fresh Wave Reviewer / independent Wave-review capability | `WAVE_REVIEW` |
| `WAVE_REVIEW` | Current authoritative `WAVE-REVIEW.md` is PASS and identity matches | Record Wave acceptance pointer | `WAVE_ACCEPTED` |
| `WAVE_REVIEW` | FIX_REQUIRED with ownership-routed findings | Record source-review pointer | `WAVE_REMEDIATION` |
| `WAVE_REVIEW` | BLOCKED/SPEC_CHANGE_REQUIRED, missing/stale/conflicting evidence | Stop | `HUMAN_ATTENTION` |
| `WAVE_REMEDIATION` | All actionable findings are `WAVE_FIX` or safely executable manual validation; remediation result is `READY_FOR_WAVE_REVIEW` | Wave Remediator / Wave-local remediation capability | `WAVE_REVIEW_REQUIRED` |
| `WAVE_REMEDIATION` | `TASK_REVIEW_REQUIRED` | Re-enter only the identified task at `TASK_REVIEW_REQUIRED` after reconciliation | `TASK_REVIEW_REQUIRED` |
| `WAVE_REMEDIATION` | `NEW_TASK_REQUIRED`, unavailable manual action/environment, spec change, partial/unresolved remediation | Do not create scope or infer authority | `HUMAN_ATTENTION` |

For a `WAVE_FIX` that changes work owned by an already accepted task, the
Controller must first determine whether the Wave review itself routed a
`TASK_REVIEW_REQUIRED` finding.  If it did, task re-review precedes Wave
re-review.  It must never decide that a code change does or does not need task
acceptance on its own.

## Human gates and acceptance distinctions

The Controller stops and requires explicit persisted human authority at:

1. Wave start: before `WAVE_AUTHORIZED`/TECHSPEC dispatch.
2. TECHSPEC approval: after technical design, for that exact artifact revision.
3. Task-plan approval: after task planning, for that exact task set; it
   permits its canonical bounded execute/review/fix successor.
4. Any `SPEC_CHANGE_REQUIRED`, including an unapproved scope expansion or
   `NEW_TASK_REQUIRED` route without separately supplied authority.
5. Review-cycle-limit intervention, conflicting/missing/stale evidence,
   interrupted/unknown operation, manual validation requiring user action,
   environment blockage, or any unrecoverable ambiguity.
6. The next Wave: always after `WAVE_ACCEPTED`; this Controller has no
   authority or transition to consume it.

Engineering completion means a role completed its bounded work. Task
acceptance means current independent `review-task` PASS. Wave acceptance means
current independent `wave-review` PASS. An approval accepts the exact active
hash-bound result and permits only its defined canonical successor. An
authorization is a human decision to begin new scope, non-canonical work, an
external side effect, or another policy-defined high-risk action; it is not
acceptance. Neither permits a later Wave or delivery without its separately
required authorization.

## Flat subagent topology and role policy

The first bootstrap is flat. The Host dispatches children directly using a
Controller handoff; children must not spawn or supervise agents.

| Role | Fresh child / fork policy | Minimum bounded handoff | Authority and expected evidence | Checkout access | Model / effort |
| --- | --- | --- | --- | --- | --- |
| Architect | Fresh per TECHSPEC; `fork_turns="none"` | Wave ID, approved sources/paths, exact authorized scope, target TECHSPEC path | Writes only TECHSPEC under `create-techspec`; reports `AWAITING_HUMAN_APPROVAL`, BLOCKED, or spec change | Writer, serialized | DEEP: Terra high |
| Planner | Fresh per task plan; `none` | Wave ID, active approved TECHSPEC path+hash and approval evidence, scope/path | Writes only task plan under `create-tasks`; reports approval-ready result or escalation | Writer, serialized | DEEP: Terra high |
| Developer | Fresh per task implementation attempt; `none` | Wave/task IDs, approved task path, required context, dependency PASS references, input identity, validation contract | Writes task-scoped implementation/tests/status only under `execute-task`; returns completed/escalation | Writer, serialized | STANDARD: Terra medium |
| Reviewer | Fresh for every review and re-review; `none` | Explicit reviewer handoff below | Writes only authoritative task review/status permitted by `review-task`; returns decision | Read-only behavior to the extent supported; no code/test edits | DEEP: Terra high |
| Fixer | Fresh per applicable FIX_REQUIRED; `none` | Task ID/path, latest review path+hash/findings, input identity, validation contract | Writes minimal task fix/tests/status under `fix-task`; never PASS | Writer, serialized | STANDARD: Terra medium |
| Wave Reviewer | Fresh for every Wave review/re-review; `none` | Wave ID, bounded authoritative prerequisite references and exact checkout identity | Writes only current authoritative Wave review under `wave-review`; returns decision/ownership | Read-only behavior to extent supported; no code/test edits | DEEP: Terra high |
| Wave Remediator | Fresh per routed Wave remediation; `none` | Wave ID, source Wave-review path+hash, permitted finding IDs/ownership, approved scope | Writes only executable Wave-local fixes/evidence under `fix-wave-review`; never accepts | Writer only when the routed finding permits it, serialized | STANDARD: Terra medium |

FAST (Terra low) is reserved for non-decisive Host diagnostics only; it is not
used for engineering acceptance. These are intended selected tiers,
not assertions about quota, pricing, or actual provider availability.  If a
requested selection cannot be made by the host, record that fact and require
human confirmation before dispatch rather than silently changing the policy.

### Reviewer independence handoff

Every task Reviewer receives a fresh `none` child prompt containing only:

- Wave and task identity;
- approved TECHSPEC and task-definition paths (and hashes when material);
- exact commit HEAD, clean/dirty classification, deterministic working-tree
  diff hash, and changed-file/diff scope captured immediately before dispatch;
- required validation commands and applicable prerequisite evidence paths;
- expected review artifact path and the existing `review-task` output contract.

The Wave Reviewer receives the equivalent Wave identity, approved source paths,
task index/task-review/Wave manual-acceptance prerequisites, exact checkout
identity, and Wave-review artifact contract.

Neither receives developer/fixer conversation, rationale, summaries, suggested
verdict, expected PASS, unrelated host conversation, or a host quality
assessment.  They must disregard non-authoritative developer narrative.  A
re-review is always a different fresh Reviewer child, even if a prior reviewer
was a PASS or FIX_REQUIRED author.

### Deterministic Controller-to-Host handoff

For one permitted operation, the Controller returns structured metadata, not a
reasoning-rich engineering prompt. At minimum it contains `wave_id`, `task_id`,
`required_role`, `required_capability`, required Skill/mechanism reference,
authoritative input paths and hashes, checkout fingerprint, changed paths/diff
identity, required validation, expected authoritative output path,
`fork_turns` policy, intended model/reasoning tier, and `operation_id`.

The Controller does not author natural-language engineering instructions that
need judgment beyond deterministic templates. The Host may wrap this metadata
in a minimal role prompt and invoke the existing Skill. This is a simple
boundary, not a generic prompt framework.

## Single-writer and checkout-identity protocol

There is one mutable checkout and no worktree isolation.  Therefore:

1. The Controller holds one logical active-operation/writer lease in the
   control record. No active writer permits acquisition; a known active writer
   rejects a second writer; an unknown or unresolved writer blocks for
   `HUMAN_ATTENTION`; it is never silently overwritten.
2. A reviewer is dispatched only after no writer is active and the Controller
   captures the validated aggregate checkout fingerprint: `HEAD`; SHA-256 of
   raw porcelain-v2 status bytes; SHA-256 of binary diff-from-`HEAD` bytes; a
   content-hashed untracked-file manifest; a changed-path manifest; and their
   canonical SHA-256 aggregate. The control record stores all components.
3. Reviewers/Wave Reviewers are instructed not to modify production code,
   tests, or unapproved workflow artifacts, consistent with their Skills.  The
   host uses the least write capability it can provide, but this is behavioral
   rather than hard permission isolation in the current shared host.
4. On return, before accepting a review envelope, the Controller recaptures
   identity.  Changes allowed solely for the review artifact/status are
   separately accounted for; any other material checkout or diff change makes
   the review stale.  The result is rejected, recorded `STALE`, and no state
   advance occurs.
5. A writer result is similarly reconciled to its declared input and output
   identities.  Unknown concurrent modification, checkout drift, or an
   untracked material file blocks human attention.

The Controller is the sole writer of the control record. Role children own
only artifacts their existing Skill explicitly permits.  No role may alter an
approval/authorization record, another role's authoritative review, or the
control record itself.

## Persisted bootstrap control record

When implemented, create exactly one canonical current-state file per
supervised Wave:

```text
docs/waves/<wave-id>/bootstrap/WAVE-WORKFLOW-STATE.md
```

This Wave-local location puts temporary governance alongside existing Wave
authorization/TECHSPEC evidence, avoids treating `tasks/` review records as
orchestrator state, and avoids a repository-global runtime-state system.  The
`bootstrap/` directory clearly distinguishes temporary development control from
authoritative product persistence that Wave 3 will later implement.  The file
does not exist until bootstrap implementation.

It is a pointer/index/control record, not a copy of any task plan, finding,
review, or specification.  A concise human-readable Markdown document with one
fenced YAML control block is sufficient.  Its minimum fields are:

```yaml
schema_version: 1
workflow_id: bootstrap-<uuid>
wave_id: <wave-id>
wave_name: <name>
lifecycle_state: <one of 19 states>
current_task_id: <null or TASK-XXX>
attempt: {task_execution: 0, task_review: 0, task_fix: 0, wave_review: 0}
last_completed_transition: <transition-id>
next_capability: <domain capability or HUMAN_ACTION>
required_role: <role or HUMAN>
human_gate: {status: OPEN|SATISFIED|NOT_APPLICABLE, reason: <short>, evidence: []}
authoritative_refs: [{path: <repo-relative>, sha256: <digest>, purpose: <short>}]
checkout_identity: {head: <sha>, status_hash: <sha>, diff_hash: <sha>, untracked_hash: <sha>, changed_paths_hash: <sha>, fingerprint: <sha>}
active_operation: {id: <uuid>, role: <role>, child_task_name: <name>, input_identity: <object>, dispatched_at: <RFC3339>} # or null
last_result_envelope: <envelope or null>
blocker: {classification: <or null>, reason: <short>, required_human_action: <short or null>}
updated_at: <RFC3339>
updated_by: python-wave-controller
```

The record uses atomic replacement by the Controller: a same-directory
temporary file receives complete serialization, flush, file `fsync`,
`os.replace`, then directory `fsync`. An interruption before replace preserves
the prior canonical state. It records the immediately
previous state/transition in a short audit section.  It is not an append-only
event store.  Existing immutable decision and review artifacts retain their
own history.  A control-record hash in the result envelope protects against
accidental stale child completion, but no child is allowed to update it.

### Validated deterministic primitives

The technical spike passed all three primitives in its tested Linux/WSL
disposable fixture:

- **Checkout identity — PASS.** The aggregate fingerprint algorithm above
  detected tracked and untracked material changes; a result tied to an earlier
  fingerprint is rejected as `STALE` when material checkout identity changes.
- **Atomic state replacement — PASS.** Same-filesystem, same-directory temp
  serialization, file `fsync`, `os.replace`, and directory `fsync` retained
  the preceding canonical state when interrupted before replace.
- **Single-writer lease — PASS.** The logical active-operation record allowed
  acquisition only without an active writer, rejected a known active writer,
  and blocked an unknown/unresolved writer.

These experiments validate the tested Linux/WSL fixture, not every filesystem,
Git edge case, or concurrent-process failure mode.

## Durable result-envelope contract

Child terminal prose alone has no transition authority.  For every child
terminal event, the Controller creates or updates the `last_result_envelope`
in the state record only after inspecting the referenced artifact and checkout.
It contains only references and compact facts:

```yaml
envelope_version: 1
operation_id: <must equal active_operation.id>
scope: {wave_id: <id>, task_id: <null or TASK-XXX>}
role: <Architect|Planner|Developer|Reviewer|Fixer|Wave Reviewer|Wave Remediator>
attempt: <integer>
child_task_name: <host child task identity>
input_checkout_identity: {head: <sha>, status_hash: <sha>, diff_hash: <sha>, untracked_hash: <sha>, changed_paths_hash: <sha>, fingerprint: <sha>}
output_checkout_identity: {head: <sha>, status_hash: <sha>, diff_hash: <sha>, untracked_hash: <sha>, changed_paths_hash: <sha>, fingerprint: <sha>}
terminal_status: COMPLETED|PASS|FIX_REQUIRED|BLOCKED|SPEC_CHANGE_REQUIRED|INTERRUPTED|STALE|INVALID
authoritative_artifacts: [{path: <repo-relative>, sha256: <digest>, purpose: <short>}]
validation: [{command: <command>, outcome: PASS|FAIL|NOT_RUN, evidence_ref: <artifact/path>}]
review_decision: <PASS|FIX_REQUIRED|SPEC_CHANGE_REQUIRED|BLOCKED|null>
recorded_at: <RFC3339>
```

For an implementation/fix that has no required standalone execution-report
artifact, the envelope references the task definition/status evidence and the
captured checkout identity; the Controller records validation references
without copying arbitrary prose.  For reviews, the authoritative persisted
review artifact is mandatory.  For planning, TECHSPEC/task-plan output and its
approval-ready status are mandatory.  For Wave remediation, the remediation
artifact is mandatory but never proves acceptance.

An envelope is `INVALID` when required fields, artifact hash, scope, role,
attempt, or decision disagree.  It is `STALE` when input/output identities do
not meet the state transition's identity rule.  Both prevent advancement.

## Recovery, reconciliation, and idempotency

At every Controller invocation—and before any new dispatch—perform
reconciliation in this order:

1. Parse and validate the state schema, Wave identity, state/role pairing,
   active-operation identity, artifact paths, and all stored hashes.
2. Recompute checkout identity and read only the current Wave's authorization,
   TECHSPEC/task plan, task status/index, applicable task reviews, and Wave
   review/remediation evidence required by the claimed state.
3. Treat current authoritative artifacts as stronger than the control pointer.
   Reconstruct the furthest unambiguous permitted state, but never cross a
   missing human gate or infer a human decision.
4. If the state says implementation is required but matching IMPLEMENTED
   evidence exists, move to `TASK_REVIEW_REQUIRED`; if it says review is
   required but matching current PASS exists, move to the next eligible task or
   `TASKS_READY_FOR_WAVE_REVIEW`.  Record reconciliation as the transition.
5. If a host vanished after child completion, match operation ID, role, scope,
   input identity, artifacts, and output identity before recording its envelope.
   If that proof is absent, mark the operation `INTERRUPTED`/`INVALID` and
   stop. Do not rerun a completed writer operation when completion is
   ambiguous.
6. If a referenced revision/diff is stale, an artifact is missing, competing
   current artifacts disagree, a reviewer result cannot be tied to its target,
   or a writer may have run concurrently, enter `HUMAN_ATTENTION`.

Dispatch is idempotent only after reconciliation proves no completed matching
operation exists.  Never retry a writer following an unknown/interrupted
operation merely because the state says it was required.  A fresh host does not
need parent-session continuity; child names are diagnostic metadata, not the
source of truth. A completely new Codex session can conceptually run
`wave-controller status`, `wave-controller reconcile`, and `wave-controller
next` and receive an unambiguous answer without prior chat history. These are
interface examples only, not proposed CLI commands.

## Failure handling and Wave-review remediation

The Controller may retry only a pre-dispatch failure (for example, no child
was created) or a deterministic read-only verification that changed no
checkout state.  It may redispatch a completed capability only after a
validated envelope/artifact proves the earlier operation did not complete or
the human has explicitly resolved the ambiguity.  It may reconcile whenever
evidence is complete and unambiguous.  It blocks for all unknown writer state,
artifact conflict, stale identity, human-gate absence, limit, external/manual
dependency, or scope/specification question.

Wave review routing is mechanical from the persisted authoritative finding
ownership; it is not quality judgment:

| Wave-review ownership/outcome | Controller route |
| --- | --- |
| `PASS` | `WAVE_ACCEPTED`; stop. |
| `WAVE_FIX` | Dispatch Wave Remediator only for executable scoped findings; require `READY_FOR_WAVE_REVIEW`, then a fresh Wave Reviewer. |
| `TASK_REVIEW_REQUIRED` | Reconcile the named task and dispatch fresh task review; no Wave PASS until fresh Wave re-review. |
| `NEW_TASK_REQUIRED` | `HUMAN_ATTENTION`; task creation/scope authorization is not implicit. |
| `MANUAL_VALIDATION_REQUIRED` | Dispatch only if the existing procedure is safely executable without new human/external authority; otherwise human attention. |
| `ENVIRONMENT_BLOCKED` | Human attention; do not code around environment acceptance. |
| `SPEC_CHANGE_REQUIRED` | Human attention; upstream approval process must decide. |
| `FIX_REQUIRED` with mixed ownership | Execute only the explicitly executable subset; if anything unresolved remains, human attention or the specified task-review route. |

Every successful remediation returns to a fresh independent `wave-review`.
Neither remediation evidence nor task PASS is Wave acceptance evidence.

## Wave 3 supervised-pilot plan

Wave 3 is the first intended real supervised pilot only after its normal
Wave-start authorization is valid.  This document neither grants that
authorization nor starts Wave 3.  The pilot sequence is:

1. Implement this temporary Controller and its one control record without
   changing existing Skills/contracts; initialize its Wave 3 state only after
   the human records valid Wave-start authorization.
2. Have a Host reconstruct from the state file, approvals, and checkout, then
   stop at TECHSPEC approval and task-plan approval until real human decisions
   are persisted.
3. Run each approved Wave 3 task sequentially through Developer and a fresh
   `none` Reviewer; permit the normal fix/re-review loop only if naturally
   produced.
4. Before accepting one review result, deliberately alter the recorded target
   identity in a controlled non-engineering test fixture or make an allowed
   harmless checkout-identity change **outside the real Wave 3 implementation
   flow**, then prove stale rejection and restore/reconcile before continuing.
   Do not inject defects into Wave 3 to force a fix path.
5. Prove writer leasing by attempting a second Controller operation while a
   test writer lease is active; it must refuse before spawning.  Do not run
   concurrent real writers.
6. After all task PASS evidence exists, dispatch a fresh `none` Wave Reviewer.
   Route any natural remediation only through its ownership contract, then
   require fresh Wave re-review.
7. On authoritative PASS, record `WAVE_ACCEPTED` and verify the next host
   reports STOP/HUMAN AUTHORIZATION REQUIRED FOR NEXT WAVE, with no dispatch.

If the natural pilot has no `FIX_REQUIRED`, test the developer→reviewer→fixer
→fresh re-review branch in a disposable repository/fixture with an approved
bounded test contract, not by seeding a defect in Wave 3.  Likewise test stale
identity and writer lease in a disposable fixture when it cannot be safely
observed without disturbing real Wave evidence.

### Pilot acceptance criteria

The pilot passes only if all applicable evidence shows:

1. A fresh host reconstructs the next valid action without parent chat.
2. TECHSPEC and task-plan human gates stop exactly as required.
3. Developer and each Reviewer are separate `fork_turns="none"` children with
   bounded handoffs.
4. Any natural FIX_REQUIRED reaches a fresh Fixer then a different fresh
   Reviewer; otherwise the disposable fixture proves the branch.
5. A deliberately stale identity is rejected and cannot advance state.
6. A second writer is prevented before dispatch.
7. All task PASS evidence, not implementation completion, triggers Wave review.
8. The Wave Reviewer is a fresh `none` child with no developer rationale.
9. Any natural Wave remediation follows recorded ownership and returns to
   fresh Wave review.
10. Only authoritative Wave-review PASS yields `WAVE_ACCEPTED`.
11. `WAVE_ACCEPTED` produces no later-Wave dispatch or authorization.
12. Audit shows every role modified only files its Skill allowed.

## Abandon/fallback criteria

Abandon the shared-host/subagent approach for stronger isolation or a separate
process/worktree design if any of these occurs:

- a reviewer can receive parent/developer conversational material despite
  `fork_turns="none"` and the bounded handoff;
- host permissions cannot keep a reviewer from making material unauthorized
  modifications and that risk cannot be procedurally tolerated;
- checkout identity cannot reliably distinguish review artifacts from material
  concurrent changes;
- a fresh host cannot deterministically reconcile state/evidence without chat;
- child completion cannot be durably tied to the correct scope/checkout;
- repeated Controller recovery produces ambiguous writer operations; or
- the pilot needs true filesystem, credential, worktree, or permission
  isolation beyond the observed shared-host surface.

The fallback is a separately launched Codex process with independently chosen
permissions and, where required, a separate worktree/container—not a more
complex in-host controller.

## Relationship to future Engineering Flow

This bootstrap prototypes, but does not redesign, future product concepts:

| Bootstrap concept | Likely future product concept |
| --- | --- |
| Wave control record | persisted lifecycle state |
| evidence/hash preconditions | transition validation and idempotency |
| deterministic capability/role handoff | handoff manifest |
| Host child dispatch | runtime dispatch |
| result envelope | normalized execution result/evidence |
| reviewer prompt identity | handoff manifest and reviewer isolation |
| reconciliation pass | interruption recovery |
| explicit stops | human approval/authorization gates |

The Controller may prototype persisted lifecycle state, deterministic
transition validation, reconciliation, result envelopes, handoff manifests,
human gates, and stale detection. Wave 3 remains responsible for actual
product-level capability/lifecycle-governance decisions. Its approved future
TECHSPEC remains the place to decide product schemas, persistence,
provider-neutral concerns if any, audit model, and migration. The bootstrap
must be retired or explicitly migrated only after that product capability
exists; it must not become the future implementation by accident.

## Remaining integration risks

These are unvalidated integration risks, not blockers to implementing the
minimal Controller. Relevant ones must pass before the real Wave 3 pilot.

1. **Reviewer behavioral write restraint.** The active collaboration
   spawn interface has no per-child sandbox/permission selector.  Required
   experiment: confirm the Host can practically provide an acceptable
   least-privilege reviewer context; otherwise use the separate-process
   fallback.
2. **Reviewer artifact-only checkout allowance.** The validated fingerprint
   does not yet prove that review artifact/status-only changes can always be
   distinguished from material drift in integrated operation.
3. **Integrated Controller + Codex subagent recovery.** Recovery, result
   envelopes, and lease state must be exercised across an actual Host/child
   interruption boundary.
4. **Git/repository edge cases.** Unusual paths, symlinks, submodules, and
   repository-policy edge cases were outside the disposable fixture.
5. **Actual dispatch availability.** Terra tier names
   are the current personal policy.  Required pre-dispatch check: record
   whether the host supports the intended explicit model/effort; do not claim
   the choice was applied when it was not.

## Recommended implementation sequence

1. Define the small Python Controller state, fingerprint, transitions, and
   handoff responsibilities plus the state-record template
   at the proposed Wave-local path; do not alter existing Skills.
2. Implement deterministic artifact, authorization/hash, dependency, and
   checkout-identity verification before any dispatch capability.
3. Implement the one-operation writer lease and envelope persistence.
4. Implement reconciliation and stale/invalid blocking before automated
   progression.
5. Add bounded role handoff templates, always spawning fresh `none` children.
6. Exercise the integrated dry-run, including reviewer artifact allowance,
   behavioral isolation, recovery, and remediation-loop tests.
7. Only then use the human-authorized Wave 3 pilot; stop at its acceptance.

## Recommendation

**PROCEED_TO_CONTROLLER_IMPLEMENTATION.** The three required deterministic
primitives passed and the remaining items are integration risks rather than a
new implementation blocker. Implementation of the minimal Controller may
begin. An integrated dry-run remains required before Wave 3, and reviewer
behavioral isolation remains a later validation gate before the real Wave 3
pilot.
