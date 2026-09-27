# Engineering Flow V2 — MDS #3.1 Interactive Continuation UX Plan

## 1. Motivation and scope

MDS #3 established the repository-mutation boundary: an explicitly approved
V2 Plan may be continued by a later `resume`, which executes at most one
selected Task Contract and stops before verification. Its deliberate UX
boundary was that Plan approval and the writer invocation were separate CLI
invocations.

That boundary is safe but awkward for an interactive user who has just
reviewed and approved the displayed Plan. MDS #3.1 adds a narrow interactive
`run` continuation: after the existing Plan prompt durably approves the exact
displayed Plan, `run` asks separately whether to begin repository mutation in
this invocation. Only an affirmative second confirmation may make the one MDS
#3 implementation attempt. It is a UX continuation only; it does not widen
MDS #3 authority, task selection, mutation, recovery, or milestone scope.

This document is the MDS #3.1 design record. The historical
`mds-03-single-task-execution-plan.md` remains the MDS #3 behavioral contract
and is intentionally not amended to imply that inline continuation was part
of that milestone.

## 2. Behavioral contract

- Inline implementation is available only to interactive `run`, after the
  existing Plan prompt durably approves the exact current Plan and an
  additional `Start implementation now? [y/N]` prompt receives an explicit
  affirmative answer in that invocation.
- Plan approval does not invoke IMPLEMENT. The approval transaction completes
  first, then `run` reloads and revalidates persisted workflow state before it
  presents the start prompt. The resulting persisted `PLAN_APPROVED` state and
  exact immutable authority are the only input to implementation; prompt text,
  a local boolean, and a displayed projection are never authority.
- `no`, blank input, EOF, or an unavailable start prompt leaves the workflow
  `PLAN_APPROVED` with no writer intent, writer lease, implementation attempt,
  provider dispatch, or repository mutation.
- Eligible inline continuation makes zero or one writer dispatch. It uses the
  same selection, authority revalidation, clean-baseline, lease, attempt,
  recovery, and final-state rules as `engineering-flow resume`.
- The command always stops after that gateway returns. It never retries,
  selects a successor, verifies, reviews, fixes, commits, or loops through
  further workflow boundaries.
- A declined Plan prompt, feedback/change-request route, EOF, invalid
  projection, approval failure, a negative/default start response, or any
  non-`PLAN_APPROVED` result dispatches no writer.
- `engineering-flow approve` remains approval-only. An explicit later
  `engineering-flow resume` retains its MDS #3 behavior and remains the path
  for non-interactive approval and safe retry.
- Interactive planning `resume` remains a Plan interaction only. It preserves
  its existing stop-after-approval behavior: it neither shows the start prompt
  nor invokes IMPLEMENT. A later `resume` from an already `PLAN_APPROVED`
  workflow follows the normal MDS #3 implementation route.

## 3. Interactive run flow

Only prompt-eligible interactive `run` (stdin, stdout, and stderr are
terminals; not `--json`) uses this flow:

```text
V2 run reaches current Plan awaiting approval
  -> render the verified current Plan projection
  -> prompt for approve / request changes
  -> approve the exact artifact through V2PlanOrchestrator
  -> re-read persisted workflow state
  -> prompt: Start implementation now? [y/N]
       -> yes: shared MDS #3 implementation gateway exactly once
                -> render the normal terminal implementation result and stop
       -> no / blank / EOF: remain PLAN_APPROVED and stop
```

The existing Plan loop still resolves the pending artifact immediately before
the prompt and uses the existing approval method. On an approve decision, it
must return enough control to the command handler to distinguish a durable
approval from every other loop exit. For `run`, the command handler reloads
the workflow from SQLite and revalidates that it is V2, `stage=PLAN`, and
`status=PLAN_APPROVED` before asking the default-no start question. Only an
explicit `yes` calls the shared gateway. The start response is not persisted.

An interactive planning `resume` may still display, revise, and approve a
Plan, but returns after rendering the durable approval result. It never enters
this start-confirmation flow. Conversely, `resume` invoked when a workflow is
already `PLAN_APPROVED` continues to invoke the normal MDS #3 implementation
path without a new Plan or start prompt.

Prompt presentation is not combined with the writer UI: the approved-plan
message is rendered first, then the existing MDS #3 TTY progress/result
presentation owns writer feedback. Existing no-colour, bounded-path, and
secret-sanitization rules apply. Ctrl+C during the writer remains governed by
the gateway's owned-process termination and durable reconciliation behavior;
there is no special interactive cancellation path.

## 4. Non-interactive fail-closed behavior

Non-TTY and JSON invocations never read an implicit approval or start decision
and never perform inline continuation. When a V2 `run --request` or planning
`resume` reaches `PLAN/AWAITING_APPROVAL`, it returns the existing bounded
document/recovery instruction; the Plan remains pending. JSON continues to
emit exactly one stdout document, with no prompt, ANSI, progress, or provider
chatter.

Piped input is not an interactive approval channel. Supplying `y`, an empty
line, or any other stdin content to a non-TTY command must not create an
approval or a writer attempt. A user or automation must use the existing
explicit `approve` command with the exact artifact and then a separate
`resume`; that `approve` command does not inline execution. There is likewise
no non-interactive form of the `run` start confirmation: automation that has
approved a Plan uses the existing explicit `resume` boundary.

## 5. Shared implementation gateway design

Introduce one CLI/application-level helper owned by the command handler (for
example, `continue_approved_implementation(workflow_id, ...)`). It constructs
the normal progress sink and `CodexImplementationWriter`, invokes exactly one
`ImplementationAttemptOrchestrator.run_once(workflow_id)`, then reloads the
workflow for rendering. Both the existing V2 `resume` implementation branch
and only the affirmative-start branch of interactive `run` call this helper.
The interactive planning `resume` approval branch does not call it.

The helper is deliberately thin. It must not duplicate or pre-decide:

- the exact approved-Plan / READY Feature Contract predicate;
- deterministic task selection or dependency semantics;
- repository inspection, baseline capture, writer-lease acquisition, intent
  persistence, profile routing, provider invocation, or result classification;
- recovery, retry eligibility, or workflow-state transitions.

The gateway remains the sole mutation-dispatch authority. It independently
revalidates all persisted MDS #3 conditions after approval, so a changed Plan,
dirty checkout, conflicting lease, altered authority artifact, or any other
failed precondition produces the ordinary fail-closed outcome with no special
inline exception.

## 6. No durable “start authorized” flag

MDS #3.1 intentionally adds no `start_authorized`, `approved_to_execute`,
prompt-decision, or equivalent durable state. Persisting such a flag would
create a second authority fact whose revocation, binding, replay, and
supersession rules could diverge from the approved Plan.

The durable Plan approval is sufficient to make an implementation attempt
eligible; it does not itself start one. The separate start response decides
only whether this interactive `run` invocation immediately calls the gateway,
and is not reusable authority. A no/blank/EOF response persists nothing beyond
the approval. On process loss between approval and dispatch, or after any
non-affirmative response, the workflow simply remains `PLAN_APPROVED`, and a
later explicit `resume` evaluates the normal MDS #3 predicate. No
reconstruction or inference of an intended inline start is allowed.

## 7. Inherited MDS #3 safety invariants

MDS #3.1 preserves, without weakening, these MDS #3 controls:

- immutable, hash-validated latest READY Feature Contract and exactly approved
  highest Plan revision bind every attempt;
- the Task Contract is recovered from that Plan and selection is deterministic;
- at most one task and one provider writer dispatch occur per gateway call;
- a supported, clean Git worktree and captured baseline are required before
  mutation; HEAD, branch, repository identity, Git configuration, control
  state, and final repository truth are checked afterward;
- an exact durable workspace writer lease prevents concurrent Engineering Flow
  writers, and uncertain ownership is never stolen;
- only Developer IMPLEMENT receives workspace-write; no bypass/additional
  directory permission, commit, rollback, stash, reset, or cleanup is added;
- changed/unknown/interrupted outcomes require human attention as defined by
  MDS #3, while retryable unchanged failures require a later explicit resume;
- `IMPLEMENTATION_COMPLETED` remains unverified, satisfies no dependency, and
  stops before VERIFY, REVIEW, FIX, or a second task.

## 8. Explicit non-goals

MDS #3.1 does not:

- change the historical MDS #3 contract or retroactively redefine its scope;
- add a command, command flag, prompt that grants separate execution
  authority, or durable start-authorization record;
- make explicit `approve` mutating; change interactive planning `resume` into
  an approve-then-start flow; or make non-interactive/JSON commands
  prompt-driven;
- alter MDS #3 retry, recovery, task graph, profile routing, persistence,
  provider-session, repository-safety, or output-schema contracts;
- implement verification, review, remediation, multi-task/autonomous loops,
  commits, pushes, pull requests, worktrees, or automatic cleanup.

## 9. Test plan

Use existing `unittest` CLI tests with a temporary Git worktree and a fake
implementation writer/runtime. Add focused coverage for:

1. Interactive `run --request` reaches a displayed Plan; approval alone
   persists `PLAN_APPROVED` and creates no writer intent, lease, attempt,
   provider call, or mutation until the separate start prompt receives `yes`.
2. An affirmative `Start implementation now? [y/N]` response calls the shared
   gateway once, selects only `T1`, and ends at the normal MDS #3
   implementation result with verification `NOT_RUN`.
3. `no`, blank input, and EOF at the start prompt each retain
   `PLAN_APPROVED`, make zero writer calls, and leave no implementation intent,
   lease, attempt, or repository mutation.
4. Interactive planning `resume` that approves the current or a revised Plan
   stops after approval, does not display the start prompt, and makes zero
   writer calls. A later `resume` from that `PLAN_APPROVED` workflow calls the
   shared gateway once.
5. The explicit `approve` command still records only approval and makes no
   writer call; a later `resume` calls the same shared gateway once.
6. Non-TTY, piped-stdin, and `--json` paths never prompt, approve, or dispatch
   inline; JSON remains one clean document and reports the recovery boundary.
7. Plan-prompt decline, feedback, projection error, approval conflict, and
   failed approval each make zero writer calls.
8. A post-approval, affirmative-start precondition failure (dirty tree,
   stale/tampered authority,
   or active/conflicting lease) proves the gateway revalidation still blocks
   dispatch and preserves MDS #3 classification.
9. The affirmative interactive-run and explicit-resume routes have equivalent persisted
   attempt/lease/selection/result evidence for the same approved workflow.
10. Existing MDS #3 interruption, unchanged failure/retry, changed failure,
   human-attention, presentation, and compatibility tests remain green.

Run focused modules first, then the repository validation command:

```text
.venv/bin/python3 -m unittest discover -s tests -q
```

## 10. Acceptance criteria

MDS #3.1 is complete only when:

1. The original MDS #3 plan remains unchanged and this document is the sole
   MDS #3.1 design artifact.
2. A prompt-eligible V2 `run` durably approves the exact displayed Plan,
   reloads/revalidates it, and then presents `Start implementation now? [y/N]`.
3. Only an affirmative response to that second prompt invokes the normal
   one-task MDS #3 gateway; no, blank, or EOF leaves `PLAN_APPROVED` with no
   writer intent, lease, attempt, provider dispatch, or mutation.
4. Interactive planning `resume` preserves stop-after-approval behavior and
   never presents the start prompt; a later `resume` from `PLAN_APPROVED`
   retains the normal MDS #3 implementation route.
5. The affirmative interactive-run route and explicit `resume` route share one implementation
   gateway; no duplicate dispatch, authority, lease, or result logic exists.
6. Inline continuation depends exclusively on re-read persisted MDS #3
   authority and retains all MDS #3 safety/recovery outcomes.
7. Non-interactive, piped, and JSON invocations fail closed: no prompt, no
   implicit approval, no inline writer dispatch, and JSON remains machine-safe.
8. Explicit `approve` remains approval-only, and no durable “start
   authorized” flag or equivalent second authority is persisted.
9. No VERIFY, REVIEW, FIX, second task, commit, delivery side effect, or other
   out-of-scope behavior is introduced.
10. The focused tests and full repository test command in section 9 pass.
