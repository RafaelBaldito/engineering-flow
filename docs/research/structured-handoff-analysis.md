# Structured Handoff Analysis

**Decision scope:** independent Codex sessions now, repository-local Skill
workflows, and future Engineering Flow runtime/provider orchestration.

**Recommendation:** **EXPERIMENT_FIRST** — trial **Option D**, a generated,
short-lived structured pointer manifest for one real implementation → review →
fix/re-review sequence. Do not make it authoritative, add it to the product
domain, or change Skills/contracts until the trial shows that it removes a
measurable discovery step without causing stale-pointer failures.

The repository would benefit materially from a *small navigation and freshness
check*, not from a second workflow-state system. The benefit is strongest for a
fresh session that must select the active scope or understand a multi-artifact
remediation history. It is small or negative when a session has already been
given one selected task: the task's Context section and the selected Skill are
already the correct bounded handoff.

## 1. Current handoff model

Engineering Flow already has a durable, layered model.

- `AGENTS.md` establishes source precedence, readiness/validation commands,
  role separation, and a bounded-discovery rule. It directs task work to the
  task index, selected task, and review/remediation evidence rather than chat
  history.
- The approved Delivery Plan and architecture distinguish task, Wave, release,
  authorization, and delivery facts. The architecture explicitly assigns
  lifecycle state/evidence to persistence and says provider output is evidence,
  not a transition instruction.
- `create-tasks` requires every task to contain a Required/Optional Context
  manifest and says an executor must not need chat history. `execute-task`,
  `review-task`, and `fix-task` then load the selected task first and limit
  additional context. This is an effective task-local context index.
- The review record is already a structured role handoff in the one place it
  matters most: `review-task` requires a current durable review result, and a
  `FIX_REQUIRED` record must contain the findings needed by `fix-task` without
  reconstructing the review. Wave and release remediation Skills likewise take
  the authoritative review artifact as their entry point and persist only
  remediation evidence, not acceptance.
- `TASKS.md` indexes ordering/status; `WAVE-REVIEW.md`, remediation records,
  and manual-acceptance records preserve higher-level evidence. Their prose is
  authoritative for the facts they record. Existing Engineering Flow runtime
  state/evidence also survives interruption and is exposed through CLI
  `status`, `logs`, and `resume` for workflows it owns.

This model is deliberately artifact-first. It has no standardized one-screen
answer to the preliminary question, “which exact artifact set should this new
session open before it chooses a role/action?” A session can derive that answer
from the artifacts, but must often inspect an index, statuses, review records,
and plan/authorization rules first.

## 2. Evidence from existing workflows

### What already works

Both historical task plans are unusually usable as execution handoffs.

- Wave 1's four tasks and Wave 2's five tasks each name an objective, bounded
  scope, dependencies, explicit out-of-scope material, validation commands,
  and narrow Required Context. For example, Wave 2 TASK-003 points only to
  selected TECHSPEC sections plus the three implementation components it owns;
  it does not require the full PRD, Delivery Plan, or repository.
- The Skills enforce the same progressive loading: `execute-task` and
  `review-task` explicitly prohibit default loading of full planning history,
  future-Wave material, all source, and all tests. `fix-task` starts with the
  selected task, latest `FIX_REQUIRED` review, `AGENTS.md`, and files cited by
  findings.
- The final current task-review records use stable paths and state when they
  supersede prior `FIX_REQUIRED` conclusions. Wave 2's `TASKS.md` and all five
  current task reviews agree on `PASS`; Wave 2's authoritative Wave review is
  also `PASS`.

Therefore a new implementation, review, or fix session *with an explicit
selected task* should use the existing task/Skill contract, not an additional
handoff file.

### Concrete discovery that remains

The following are real repository patterns, not hypothetical missing
capabilities.

| Existing evidence pattern | Discovery a fresh session must perform | Small pointer-manifest value |
| --- | --- | --- |
| Wave 1 has a historical `FINAL-REVIEW.md` marked superseded and BLOCKED, while the later authoritative `WAVE-REVIEW.md` is PASS. Current detailed task-review files say they supersede former `FIX_REQUIRED` results. | Determine that the historical final review is not release acceptance and must not override the current Wave PASS; then locate the stable current evidence. | Point to the exact current Wave-review record and label the historical final review as excluded/superseded evidence. This avoids an erroneous broad reread, but does not replace the review record. |
| Wave 2 manual acceptance retains an initial incomplete live run, a corrective rerun, and a limit-driven corrective rerun. The Wave remediation record says the last missing scenario is resolved; the subsequent Wave review records the resulting PASS. | Reconstruct that the initial “FAIL/NOT RUN” matrix is historical, the corrective entries together close it, remediation is not acceptance, and the independent Wave review is the current acceptance fact. | Point to the manual-acceptance record, remediation record, and current Wave review in one ordered list, with the Wave review as the state authority. |
| The current repository state has accepted Wave 2 but no Wave 3 TECHSPEC/task set. The Delivery Plan permits later technical design only under its separate predecessor-PASS and active Wave-start-authorization conditions. | Search the plan, authorization directory, current Wave review, and Wave 3 document absence before deciding whether there is an executable next task. | State `no executable task selected` and point to the Wave 2 PASS, Delivery Plan gate, and authorization/TECHSPEC locations. It must say the expected action is verification/request of the next authorized design step, not manufacture authorization. |
| Historical task reviews record unavailable `python` aliases and Python 3.12 substitutions, while the current `AGENTS.md` now defines the canonical repository-local Python 3.13 command and `env-preflight` is healthy. | Decide which validation convention is current rather than treating old evidence commands as an operational instruction. | Point to current `AGENTS.md` for commands, while retaining old review evidence as evidence of what was actually run. |

The first three cases show selection and interpretation work, not a defect in
the underlying authoritative artifacts. The development-environment audit made
the same distinction: persisted artifacts mitigate reconstruction when loaded
selectively, while a standardized one-screen manifest was an inferred way to
avoid repeated scan-and-summarize work. Its then-observed lack of `AGENTS.md`
and preflight is no longer current; those two improvements now reduce the
remaining need.

## 3. Problems actually observed

1. **Cross-artifact currentness is discoverable but not indexed.** Historical
   Wave 1 evidence contains a superseded `FINAL-REVIEW.md`; Wave 2 acceptance
   depends on an ordered relationship among manual acceptance, remediation,
   and re-review. The current artifact says what it supersedes, but a fresh
   agent must locate it first.
2. **Current scope selection is a separate question from task execution.** A
   task index gives task status, but it does not declare an active role, exact
   starting artifact set, or whether an upstream authorization/design gate
   blocks the next task. In the present repository, every historical task is
   PASS, so no task is selected by the index alone.
3. **Current operational instructions and historical validation evidence are
   intentionally different.** Old evidence is immutable historical proof;
   `AGENTS.md` is the live repository convention. A fresh agent needs a cheap
   way to avoid treating a historical command as current procedure.
4. **The audit identified likely independent-session reconstruction cost, but
   no measured repeated-session failure or stale-handoff incident exists in
   this checkout.** This limits the justification for a permanent mechanism.

Not observed: a lack of task context manifests; a lack of durable review
handoffs; a need to copy requirements/findings into another file; an inability
of the current product runtime to preserve its own workflow state; or a reason
to introduce a new approval, acceptance, or authority transition.

## 4. Option comparison

Ratings are relative to this repository and assume a handoff is used only at a
role/session boundary, never appended to every artifact.

| Option | Context/token impact | Reliability | Duplication/drift risk | Human readability | Independent-session usability | Future automation value | Implementation/maintenance cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A. No new mechanism** | Lowest permanent cost; fresh sessions spend variable discovery context. | High for facts, because artifacts are authoritative. | None. | High for individual documents; lower for cross-artifact state. | Good after scope is supplied; moderate when scope/currentness must be selected. | Low; parsers must infer Markdown state. | None. |
| **B. Small Markdown handoff/index** | Small per handoff, but prose can grow and repeat facts. | Medium; useful navigation, weak deterministic freshness checking. | Medium/high unless strictly reference-only and routinely updated. | Highest. | Good for people and ad hoc Codex use. | Low/medium; Markdown needs conventions/parsing. | Low initial, recurring human upkeep. |
| **C. Small machine-readable manifest** | Very small and deterministic. | Medium/high only if validated against repository state. | Medium; a hand-authored manifest can become a competing status record. | Low without a renderer. | Good for an agent/tool given a known path; less friendly for a human. | High. | Medium: schema, generation/validation, lifecycle/retention rules. |
| **D. Hybrid: generated structured pointer manifest; existing Markdown remains authoritative** | Small, bounded pointer list; eliminates only selection/discovery reads. | High when a freshness guard rejects commit/worktree/source-digest mismatch; facts remain verified by opening sources. | Lowest structured option: generated references, no copied content. | Good when accompanied by a short generated summary or inspected as JSON; Markdown remains primary. | Highest for a fresh session: exact scope, source paths, state reference, next bounded action, and stale detection. | High: deterministic inputs for a future provider-neutral orchestrator/adapter. | Medium initially; low per handoff once generation is deterministic. |

Option A remains correct for a selected task and for ordinary single-session
work. Option B is attractive but risks becoming another narrative artifact that
drifts precisely at remediation/re-review transitions. C improves automation
but is too easy to misread as authoritative state. D is preferred *only if*
generation and freshness validation are demonstrated; otherwise retain A.

## 5. Minimum information required by a fresh session

The minimum question is not “what happened?” but “what may I safely open and
do now?” The following references suffice:

1. **Scope identity:** `scope_kind` (`task`, `wave`, `release`, or
   `research`) and exact `scope_id`/path. This prevents an agent selecting a
   neighboring Wave or an already accepted task.
2. **Expected bounded action:** a neutral `next_role` plus `action` (for
   example, task implementation, task review, task fix, Wave review, or
   design-gate verification), and `actionability` (`ready` or `blocked`). This
   is a navigation instruction, never an authorization.
3. **Authoritative input references:** an ordered list of repository-relative
   paths, each with a purpose such as `contract`, `state`, `finding`,
   `authorization_evidence`, or `repository_instruction`. The agent opens
   these sources; it does not trust duplicated contents.
4. **Observed state reference:** the current status/result value *and* exact
   authoritative path/section from which it was derived. This can be checked
   rather than independently governing state.
5. **Freshness snapshot:** `HEAD` commit, a clean/dirty worktree summary (and
   changed paths if dirty), and SHA-256 for each authoritative reference when
   its exact revision matters. A mismatch invalidates the handoff and sends the
   agent back to source discovery.
6. **Blocking/evidence references:** an empty array when none, otherwise
   paths/IDs only; no copied findings. Validation reference(s) are optional and
   present only when they justify the expected next action.

These fields answer exact scope, inputs, state, next action, and whether the
snapshot can be trusted. A title, prose summary, model, prompt, session ID,
Skill name, raw transcript, copied requirements, copied findings, full lifecycle
state, approval decision, or provider-native data is not required.

## 6. Proposed representation, if any

For the experiment, use one generated JSON document such as
`.engineering-flow/handoffs/<id>.json`, retained only while it names a live
handoff and ignored/archived according to an explicit retention rule. The path
is illustrative, not a current repository convention or product schema.

```json
{
  "schema_version": 1,
  "created_at": "2026-09-05T00:00:00-03:00",
  "scope": {"kind": "task", "id": "TASK-003", "path": "tasks/<wave>/TASK-003.md"},
  "next": {"role": "reviewer", "action": "review_task", "actionability": "ready"},
  "state_ref": {"observed": "COMPLETED", "path": "tasks/<wave>/TASKS.md", "selector": "TASK-003 status"},
  "authoritative_inputs": [
    {"path": "AGENTS.md", "purpose": "repository_instruction", "sha256": "..."},
    {"path": "tasks/<wave>/TASK-003.md", "purpose": "contract", "sha256": "..."}
  ],
  "blocker_refs": [],
  "validation_refs": [],
  "freshness": {"head": "<commit>", "worktree": "clean", "changed_paths": []}
}
```

Generation may derive paths/status from a selected task and its current review
or from an explicitly selected Wave/release artifact. It must never infer an
approval, acceptance, authorization, or state transition from a predecessor
PASS. A consumer must reject the manifest on a failed freshness/digest check,
then re-read the authoritative artifacts. The manifest cannot itself create or
change lifecycle state, update `TASKS.md`, replace a review, or authorize any
action.

The `next.role` labels are repository-session navigation labels. They must not
become a provider-neutral Engineering Flow domain enum, and a Codex Skill path
or name must not be stored in product-domain state. A Codex adapter could map a
future provider-neutral capability to a repository Skill or bounded prompt, as
the architecture already permits, but that mapping belongs in the adapter.

## 7. Relationship to existing Skills and authoritative artifacts

The manifest would be a front-door index, not a new workflow step.

- `create-tasks` remains the owner of task Context manifests. A generated
  handoff can reference a selected task, but must not expand or rewrite its
  Required Context.
- `execute-task` remains limited to one approved selected task; it decides
  implementation evidence, not the next review's acceptance.
- `review-task` remains independent and its stable current record remains the
  durable `FIX_REQUIRED` handoff to `fix-task`.
- `fix-task`, `fix-wave-review`, and `fix-final-review` retain their respective
  authoritative finding records and may not use a pointer manifest to mark
  anything resolved or accepted.
- `wave-review` and `final-review` remain distinct acceptance authorities.
  A manifest may point to a PASS or blocking artifact but never collapses or
  crosses those boundaries.

For the current repository-local workflow, a handoff generator should consume
only known repository paths and explicit selected-scope input. It should not
parse arbitrary prose to decide governance. If exact source status cannot be
determined mechanically, it should emit no handoff rather than a guessed one.

## 8. Personal Codex benefit

The immediate productivity gain is modest but concrete:

- A fresh Codex reviewer/fixer can validate it has the intended task, current
  review/finding record, checked-out revision, and minimal sources before
  reading broad history.
- A Wave-level session can begin from the current acceptance/remediation chain
  rather than discovering historical/superseded reports through filenames and
  prose.
- Snapshot validation makes stale terminal summaries visible early, reducing
  accidental work against a changed worktree.

It will not materially speed a coherent same-thread implementation/debugging
loop, and it cannot compensate for reading the selected task, changed code, or
authoritative review findings. Its likely token saving is model-visible file
discovery and unneeded historical reading, not a demonstrated reduction in
provider billing/quota. Measure selection turns, extra files opened, stale
manifest rejections, and raw context bytes in the trial before claiming more.

## 9. Future Engineering Flow product benefit

The future product case is stronger but belongs to normal Wave planning.

Wave 3 is already responsible for canonical lifecycle execution, capability
resolution, durable approval/acceptance/authorization/audit state, compatibility,
and remediation routing. A provider-neutral handoff/context projection could
eventually let an orchestrator pass a deterministic bounded request to any
adapter and make run state inspectable. The architecture already distinguishes
workflow state from provider memory and identifies provider-neutral sessions,
executions, events, and capabilities.

That product projection should be derived from authoritative persistence and
validated evidence, versioned with lifecycle compatibility, and emitted by the
orchestrator/CLI. It should not be modeled as a user-maintained repository file
or as Codex session state. Its exact schema, capability mapping, storage, event
semantics, recovery, and human actor/audit interactions are Wave 3 TECHSPEC
decisions, not this analysis's proposal.

## 10. What must NOT be implemented now

- No source code, CLI command, provider adapter behavior, database schema, or
  Engineering Flow lifecycle schema change.
- No modification to `AGENTS.md`, repository-local Skills, current task plans,
  historical Wave 1/Wave 2 contracts, reviews, remediation evidence, or manual
  acceptance records.
- No approval, authorization, acceptance, governance, or transition gate;
  especially no inference from a task/Wave PASS.
- No replacement, duplication, or automatic mutation of `TASKS.md`, task
  reviews, Wave reviews, final reviews, or authoritative Markdown artifacts.
- No requirement that every task/session create a handoff, no permanent
  repository-wide index, no transcript capture, and no provider/Codex-specific
  concept in the provider-neutral domain.
- No broad workflow-state schema, dashboard, worktree manager, or automation
  framework hidden behind the word “handoff.”

## 11. Risks of over-engineering

1. **Competing authority:** a status field copied into a manifest can be read
   as more authoritative than the cited review or runtime state. Freshness
   rejection and reference-only content are mandatory mitigations.
2. **Drift at the most sensitive point:** hand-authored files become stale
   after a fix/re-review or an intervention. Generate or retain Option A; do
   not adopt a prose checklist that must be manually synchronized.
3. **Context tax:** a manifest per task, review, and command can become another
   folder agents must always read. Produce it only for an explicit
   independent-session boundary and retire it after consumption/supersession.
4. **Authority collapse:** “next action” can accidentally sound like approval
   or blur implementation/review/fix/Wave/release boundaries. Use a
   non-authoritative navigation label and source links only.
5. **Provider lock-in:** persisting Codex Skills, prompt formats, or session IDs
   in product state would violate the architecture's domain/capability/provider
   separation.
6. **Premature product design:** a repository productivity experiment does not
   establish a Wave 3 product requirement or a durable product schema.

## 12. Recommendation

**EXPERIMENT_FIRST; preferred option D.** Run one bounded, opt-in experiment
only when the next independent cross-role workflow actually occurs. Generate a
reference-only manifest before review and before any required fix/re-review;
have fresh sessions validate freshness, open only listed authoritative sources,
and record whether an additional source had to be discovered. Compare against a
similar current-model handoff.

Adopt Option D for repository-local personal use only if it reliably removes
the observed cross-artifact selection work, has zero authority confusion, and
does not become stale after the measured boundaries. Otherwise keep Option A.
Defer any Engineering Flow runtime/provider implementation to a future,
authorized Wave 3 scope after the experiment supplies evidence of a
provider-neutral recurring need.
