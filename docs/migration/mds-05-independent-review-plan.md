# Engineering Flow V2 — MDS #5 Independent REVIEW Implementation Plan

## 1. Status, purpose, and boundary

**Proposal status: AWAITING HUMAN APPROVAL.** This document changes no
production code, tests, configuration, or persisted workflow data.

MDS #5 adds an independent REVIEW phase for one successfully verified V2 task:

```text
IMPLEMENT -> VERIFY -> TASK_VERIFIED
                       -> REVIEWING
                       -> REVIEW_PASSED | CHANGES_REQUESTED
```

`TASK_VERIFIED` is the only normal REVIEW entry. REVIEW revalidates durable
IMPLEMENT and VERIFY authority; it never consumes merely in-memory success, an
implementation-completed task, or failed, blocked, or unknown verification.

The recommended normal entry is `engineering-flow resume` from
`task_execution/task_verified`. REVIEW is a separately durable and recoverable
provider phase; it is not appended to MDS #4's VERIFY invocation.

MDS #5 is one task only. It adds no FIX, task acceptance, dependency release,
next-task selection, multi-task orchestration, feature-level final review,
commit, push, or PR behavior.

## 2. Architecture decisions

MDS #4 already provides the required predecessor evidence: immutable approved
Feature Contract/Plan authority, a successful IMPLEMENT producer bound to its
Task Contract and final repository snapshot, and a complete terminal VERIFY
attempt bound to its manifest, command results, and inspections. MDS #5 must
reuse these V2 records, not import the historical Wave 2 task/cycle/artifact
or review/fix-loop records.

Use task-level operational states `reviewing`, `review_passed`, and
`changes_requested`. Use distinct workflow projections such as `reviewing`,
`task_review_passed`, and `task_changes_requested`, so task findings are not
ambiguous with existing Plan-feedback `changes_requested`. Exceptional
boundaries can project `review_failed` or `human_attention`; neither permits a
successor in MDS #5.

Every Reviewer request must use `Role.REVIEWER` plus `WorkKind.REVIEW`,
read-only runtime permissions, and a fresh logical Reviewer session/execution.
It must not resume a Developer provider session or carry a Developer continuity
bundle. Inputs are limited to the Feature Contract, exact Task Contract,
verified IMPLEMENT/VERIFY evidence, relevant repository rules/files, and Git
diff. The Reviewer receives no write, commit, push, PR, acceptance, or
next-task authority.

The coordinator inspects the protected repository/control state before and
after review and compares it with verified state. Drift is never a normal
review outcome. REVIEW remains read-only and does not expand MDS #4's common
workspace-operation lease model; its persisted `REVIEWING` projection blocks
Engineering Flow's V2 writer progression, while an external mutation fails
closed.

The strict canonical reviewer payload is:

```json
{
  "outcome": "REVIEW_PASSED | CHANGES_REQUESTED",
  "summary": "non-empty conclusion",
  "findings": [{
    "id": "stable identifier",
    "severity": "blocking | advisory",
    "category": "correctness | requirement | architecture | edge_case | maintainability | security | regression_risk",
    "description": "non-empty actionable explanation",
    "path": "repository-relative path or null",
    "line": "positive integer or null",
    "requirement_reference": "Task requirement/acceptance reference or null"
  }]
}
```

All finding fields are present. `REVIEW_PASSED` requires no findings;
`CHANGES_REQUESTED` requires at least one blocking finding. The provider
supplies evidence only; store/orchestration policy determines transitions.

Each review attempt binds the workflow, approved Feature Contract/Plan and
approval hashes, Task Contract, successful IMPLEMENT producer, successful
verification attempt and command evidence, reviewed repository fingerprint,
and canonical reviewer-result hash. Findings are ordered durable records linked
to the exact attempt.

## 3. Implementation slices

The oversized and unsafe slice would be “review persistence, reviewer
execution, recovery, and CLI integration.” It mixes persistence, execution,
recovery, presentation, and lifecycle work. It is explicitly split below;
Slice 4 is isolated because recovery must be safe before `resume` can reach it.

### Slice 1 — REVIEW authority and evidence contract

1. **Objective:** Define a fail-closed, read-only REVIEW input/output contract.
2. **Exact responsibility:** Add a pure `ReviewPreflight`/resolver that accepts
   only an exact V2 task with complete terminal `verified` evidence, hashes all
   authority inputs, validates upstream bindings, and validates reviewer JSON.
3. **Main files/components likely affected:** `domain.py`; new `review.py`;
   read-only `store.py` projections; `runtime.py`/`codex_cli.py` schema seams;
   `tests/test_mds5_slice1.py`.
4. **Acceptance criteria:** deterministic request hashes; rejection before
   dispatch of forged/stale/incomplete/mismatched authority; strict payload and
   repository-relative path validation; no state writes or provider execution.
5. **Explicit exclusions:** schema mutation, intent creation, dispatch, CLI,
   recovery, and FIX.
6. **Dependencies on previous slices:** MDS #4 only.
7. **Complexity/risk assessment:** Low–medium. Do not trust the
   `TASK_VERIFIED` projection without validating terminal verification evidence.

### Slice 2 — durable review attempt, findings, and transitions

1. **Objective:** Persist REVIEW evidence and legal transitions atomically,
   without a live provider.
2. **Exact responsibility:** Add V2-specific review-attempt/finding records,
   linked generic operation/execution records, canonical evidence hashes,
   events, and store-owned `TASK_VERIFIED -> REVIEWING -> REVIEW_PASSED |
   CHANGES_REQUESTED` transitions.
3. **Main files/components likely affected:** `store.py`, `domain.py`, additive
   SQLite migrations, presentation read models, `tests/test_mds5_slice2.py`.
4. **Acceptance criteria:** additive migration; synthetic validated evidence
   creates one intent and one terminal result; findings are immutable and tied
   to verified evidence; pass has none; changes requested retains ordered
   findings; no acceptance/dependency/successor/FIX transition; fault injection
   rolls back rows, projections, operation, execution, and event together.
5. **Explicit exclusions:** subprocesses, prompts, recovery/retry, CLI, FIX,
   and multi-task progression.
6. **Dependencies on previous slices:** Slice 1.
7. **Complexity/risk assessment:** Medium. Do not adapt legacy task-cycle
   persistence because it carries excluded remediation semantics.

### Slice 3 — independent read-only reviewer execution

1. **Objective:** Run exactly one independent Reviewer request and persist a
   validated result.
2. **Exact responsibility:** Implement `ReviewAttemptOrchestrator.run_once`:
   preflight, pre-dispatch inspection, durable intent, fresh Reviewer session,
   one read-only runtime call, post-review inspection, and a Slice 2 transition.
3. **Main files/components likely affected:** new `review.py`, `runtime.py`,
   `codex_cli.py`, `store.py`, repository helpers,
   `tests/test_mds5_slice3.py`.
4. **Acceptance criteria:** new distinct reviewer session, no continuity or
   Developer resume; bounded review inputs; one dispatch per invocation;
   matching pre/post protected state; valid results become durable normal
   outcomes; Reviewer gets no write or delivery authority.
5. **Explicit exclusions:** retries, recovery, CLI routing, FIX, and multi-task
   continuation.
6. **Dependencies on previous slices:** Slices 1–2.
7. **Complexity/risk assessment:** Medium. Reuse provider-neutral runtime
   primitives, not legacy review orchestration.

### Slice 4 — interruption, unknown outcome, and recovery safety

1. **Objective:** Safely reconcile interrupted or ambiguous REVIEW attempts.
2. **Exact responsibility:** Determine whether terminal evidence exists;
   otherwise retain immutable intent/evidence and project known retryable
   `REVIEW_FAILED` or `HUMAN_ATTENTION`. Recovery never dispatches in that
   invocation.
3. **Main files/components likely affected:** `review.py`, `store.py`,
   `process_identity.py` only when a current safe observer is directly usable,
   narrow CLI seams, `tests/test_mds5_slice4.py`.
4. **Acceptance criteria:** intent precedes dispatch; known no-result provider
   failure creates no findings and advances nothing; interruption, corruption,
   ambiguity, and drift become human attention; recovery dispatches no Reviewer,
   Developer, verifier, FIX, or successor; repeated recovery is idempotent;
   uncertain attempts cannot be replaced.
5. **Explicit exclusions:** lease-model redesign, new process-killing policy,
   automatic retries, FIX, cleanup/reset/stash.
6. **Dependencies on previous slices:** Slices 2–3.
7. **Complexity/risk assessment:** High. This is intentionally separate from
   execution and needs fault/adversarial tests before production routing.

### Slice 5 — V2 continuation, status, logs, and presentation

1. **Objective:** Expose REVIEW through the V2 CLI while keeping policy out of
   the CLI.
2. **Exact responsibility:** Route `resume` from `TASK_VERIFIED` to REVIEW and
   active/uncertain attempts to Slice 4 only; project durable state, evidence
   summaries, and findings in `status`, `logs`, human output, and JSON.
3. **Main files/components likely affected:** `cli.py`, `presentation.py`,
   `review.py`, `store.py` projections, CLI integration tests.
4. **Acceptance criteria:** one review from `TASK_VERIFIED`; recovery-only when
   active/uncertain; bounded observability without secrets, raw transcripts,
   PIDs, or environments; outputs explicitly say no FIX, acceptance, dependency
   release, next task, or final review occurred; MDS #1–#4 routes are unchanged;
   JSON remains one document and noninteractive execution does not prompt.
5. **Explicit exclusions:** finding disposition UI, approvals/acceptance, FIX,
   and multi-task continuation.
6. **Dependencies on previous slices:** Slices 1–4.
7. **Complexity/risk assessment:** Medium. Presentation reads durable
   projections; it never reconstructs authority.

### Slice 6 — end-to-end acceptance and invariant regression

1. **Objective:** Prove MDS #5 as a one-task, no-FIX vertical outcome.
2. **Exact responsibility:** Add disposable-repository integration/manual
   coverage for pass, findings, unverified-input refusal, independence, drift,
   interruption/recovery, and MDS #1–#4 regression.
3. **Main files/components likely affected:** `tests/test_mds5_*.py`, existing
   CLI tests, and a manual-acceptance artifact if required by approved workflow.
4. **Acceptance criteria:** pass path IMPLEMENT -> VERIFY -> explicit REVIEW ->
   `REVIEW_PASSED`; finding path reaches `CHANGES_REQUESTED`; both retain
   durable evidence; neither starts FIX, another task, acceptance, final review,
   commit, push, or PR; invalid verification cannot enter REVIEW; focused and
   full suites pass.
5. **Explicit exclusions:** remediation implementation, dependency scheduling,
   release governance, delivery automation.
6. **Dependencies on previous slices:** Slices 1–5.
7. **Complexity/risk assessment:** Low–medium. This is validation and thin
   integration only.

## 4. Invariants and exclusions

MDS #5 must not weaken MDS #4's `VERIFIED` authority, manifest binding,
command-sequence evidence, repository inspection, or unknown-state safety. It
must not alter the approved Plan, accept a task, unblock dependencies, dispatch
a second task, run final feature/Wave/release review, create commits, modify
Git refs, push, or create a PR.

The MDS #5 completion boundary is durable, independently generated REVIEW
evidence and exactly one normal outcome—`REVIEW_PASSED` or
`CHANGES_REQUESTED`—for one previously verified task. Both are stops for a
later MDS that may introduce bounded remediation.
