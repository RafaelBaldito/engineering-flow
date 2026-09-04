# Wave 2 Live Disposable-Worktree Manual Acceptance

**Outcome:** PASS — the retained live evidence matrix is complete. This is
manual-validation evidence only; it does not independently accept Wave 2.

## Environment and safety boundary

- Target: a freshly initialized, disposable, non-bare local Git working tree, represented below as `<DISPOSABLE_REPOSITORY>`.
- Provider preflight: `codex-cli 0.152.1`; authenticated ChatGPT login; JSON events, output-schema, output-last-message, read-only, and workspace-write support advertised.
- An initial linked-worktree attempt was rejected by the product's local worktree validator before provider invocation. The retained live run therefore used the disposable normal Git working tree above.

## Approved planning boundary

The successful live workflow was `4965a133-6294-4843-b0d5-a383354bec6e`. It used real Codex planning calls and explicit human approvals for:

| Artifact | ID | SHA-256 | Decision |
|---|---|---|---|
| PRD | `d96bbc8e-6c5e-4e64-904f-6e89354d8510` | `2d1b493b8e1161bf3e3f7f90c9f6195d5f3c5ded7c1296dd26d8a83d26aeb2ad` | approved |
| TECHSPEC | `6bab9edb-cfff-460c-9c0f-dc7a1d54b681` | `7aea85977cb3a4c964255437cecdea39b09e3f6df1c99ff3a43d3b7cdc582da3` | approved |
| two-task manifest | `a6dfd6b0-1977-4763-a2b6-fcbe818b9f5e` | `3462010a38ed6dde262a7206ea77aee8eb49c453e0e4ac8ce2eebed0a0858a5b` | approved |

The approved version-1 manifest contains exactly `TASK-001` and `TASK-002`, in that order, with exact required commands `test -f acceptance/task-one.txt` and `test -f acceptance/task-two.txt`, respectively.

## Sanitized procedure and evidence

Commands below substitute the disposable path with `<DISPOSABLE_REPOSITORY>`.

```text
engineering-flow init --repo <DISPOSABLE_REPOSITORY>
engineering-flow run --repo <DISPOSABLE_REPOSITORY> --feature-file WAVE2-LIVE-FEATURE-V2.md
engineering-flow approve --repo <DISPOSABLE_REPOSITORY> --workflow <WORKFLOW> --artifact <PRD>
engineering-flow resume --repo <DISPOSABLE_REPOSITORY> --workflow <WORKFLOW>
engineering-flow approve --repo <DISPOSABLE_REPOSITORY> --workflow <WORKFLOW> --artifact <TECHSPEC>
engineering-flow resume --repo <DISPOSABLE_REPOSITORY> --workflow <WORKFLOW>
engineering-flow approve --repo <DISPOSABLE_REPOSITORY> --workflow <WORKFLOW> --artifact <TASK_PLAN>
engineering-flow resume --repo <DISPOSABLE_REPOSITORY> --workflow <WORKFLOW>
```

The first live workspace-write Developer process was intentionally terminated only after its durable task-operation intent existed. A new CLI process ran `resume`; it marked this operation `unknown` with `operation was pending during recovery`, did not replay the provider, and retained one intervention. This demonstrates the required pending-operation restart boundary without duplicate provider execution, evidence, acceptance, or task launch.

The explicit recovery command was:

```text
engineering-flow intervene --repo <DISPOSABLE_REPOSITORY> --workflow <WORKFLOW> --task <TASK-001> --reason "Recover the deliberately interrupted pending live Developer operation without replaying it."
```

The reopened live Developer invocation returned a schema-valid envelope, but its `test_results` contained the sole required command three times (for `DRAFT-ONE`, `DRAFT-TWO`, and `VERIFIED`). The orchestrator correctly rejected that duplicate exact-test evidence and persisted:

```json
{"status":"human_attention","stage":"task_execution","active_task":{"key":"TASK-001","status":"human_attention","review_window":2,"cycle":1},"next_task":{"key":"TASK-002","status":"pending"},"latest_execution":{"lifecycle":"failed","failure_classification":"agent_execution","failure_detail":"Developer test results contain a duplicate command"}}
```

The event stream was monotonic. Its relevant durable boundary was `task.imported` (twice), `workflow.task_execution.started`, `task.started`, `agent.execution.unknown`, `task.intervention.recorded`, `task.started`, and `task.operation.failed`. No reviewer execution, review result, task acceptance, or launch of `TASK-002` occurred after the rejected Developer result.

## Acceptance matrix

| Required live observation | Result | Retained evidence |
|---|---|---|
| Disposable authenticated Git repository and approved two-task manifest | PASS | preflight and approved-artifact table above |
| Only first ordered task starts before second | PASS | `TASK-001` active/human attention; `TASK-002` pending |
| Exact required test evidence accepted and independent review for each task | FAIL | duplicate exact-test evidence halted before first review |
| Fix/re-review cycle and distinct Reviewer session | NOT RUN | prerequisite Developer evidence was rejected |
| Limit-driven human attention and intervention reopening a review window | NOT RUN | only recovery intervention was exercised; no review cycle existed |
| Restart after Developer/review/acceptance | NOT RUN | pending-operation restart passed; later boundaries were unreachable |
| No commit, push, branch delivery, PR, or hosting side effect | PASS | no commits or remotes in target; no delivery command invoked; `git diff --check` passed |

## Conclusion

This is authentic live evidence, not a substitute for the required successful manual acceptance. The control plane correctly retained and routed the failed Developer evidence to `HUMAN_ATTENTION`; completing the remaining mandatory review, limit, and recovery scenarios requires a newly authorized corrective workflow for the live task fixture or runtime behavior. No such corrective implementation was performed in this remediation run.

## Corrective live rerun — 2026-09-04

**Outcome:** PASS for the previously blocked Developer/Reviewer path. This
is a scoped rerun of the incomplete path needed to validate the corrective
implementation; it is not an independent Wave review.

- Target: a newly initialized authenticated disposable Git working tree,
  represented as `<DISPOSABLE_REPOSITORY>`.
- Workflow: real Codex planning calls with explicit approvals produced an
  immutable version-1 manifest containing exactly `TASK-001` then `TASK-002`.
  Their sole required commands were respectively
  `test -f acceptance/task-one.txt` and
  `test -f acceptance/task-two.txt`.
- Corrected Developer result: the live TASK-001 Developer call ran and
  reported `test -f acceptance/task-one.txt` exactly once with `passed: true`.
  It persisted Developer and required-test artifacts; TASK-002 remained
  pending until TASK-001 had a passing independent review.
- Corrected Reviewer result: the first live Reviewer call exposed the
  installed CLI's strict-schema rejection of optional `line`; after the
  nullable-field correction, a new explicit intervention opened a new review
  window and the read-only Reviewer returned `PASS`. The nullable location
  fields were normalized away before persistence, preserving the approved
  optional-field payload contract.
- Live remediation/re-review: TASK-002's first Reviewer returned a real
  blocking `FIX_REQUIRED`; the same task's Developer received the persisted
  finding, reran its exact required test once, and a fresh Reviewer returned
  `PASS`. Both tasks were accepted in order and the workflow reached
  `COMPLETED/TASKS_READY_FOR_WAVE_REVIEW`.
- Safety: no delivery command was invoked. The disposable repository had no
  commits and no remotes; `git diff --check` passed. The only untracked files
  were the fixture feature request, `.gitignore`, and `acceptance/` files.

Sanitized durable event evidence for this rerun includes: `task.imported`
(twice), ordered `task.started`, `task.developer.completed`,
`test.completed`, `review.completed`, a real `FIX_REQUIRED` followed by a
Developer fix and fresh review, `task.accepted` (twice), and
`tasks.ready_for_wave_review`. The earlier retained pending-operation restart
evidence remains authoritative for that scenario. Limit-driven human
attention/reopening was not repeated in this scoped corrective rerun.

## Corrective limit-driven live rerun — 2026-09-04

**Outcome:** PASS for the sole scenario that remained incomplete after the
scoped corrective rerun above: review-cycle limit routing and explicit human
intervention.

- Target: a new disposable authenticated Git working tree, represented as
  `<DISPOSABLE_REPOSITORY>`; this isolated fixture deliberately did not repeat
  the already-passed two-task completion, fix/re-review, or restart cases.
- Setup: a human-approved version-1 manifest contained only `TASK-001`, with
  `max_review_cycles = 1`. Its only exact required test was
  `test -f acceptance/review-limit-marker.txt`. The task's immutable fixture
  retained `INCOMPLETE` where its acceptance criterion required `COMPLETE`, so
  an independent Reviewer could report a genuine bounded finding.
- Live role evidence: the authenticated workspace-write Developer ran the
  exact required command once and reported it as passing. A separate read-only
  Reviewer inspected the fixture and returned `FIX_REQUIRED` with one blocking
  finding: `review-limit-marker-incomplete` at
  `acceptance/review-limit-marker.txt:1`.
- Limit boundary: the initial review was cycle 1 of the configured limit 1.
  The status projection recorded `TASK-001` as `human_attention`,
  `review_window: 1`, `cycle: 1`, `latest_required_test: pass`, and
  `latest_review: FIX_REQUIRED`. The durable event stream recorded
  `review.completed`, followed by `review.limit_reached` with classification
  `review` and detail `review-cycle limit reached`.
- Intervention: the retained command was:

```text
engineering-flow intervene --repo <DISPOSABLE_REPOSITORY> --workflow <WORKFLOW> --task <TASK-001-ID> --reason "Open a new bounded review window after the retained live FIX_REQUIRED limit pause." --json
```

  It returned `status: running`, then status showed the same task as
  `pending`, `review_window: 2`, `cycle: 0`, with the prior passing test and
  `FIX_REQUIRED` review still projected. The event stream recorded
  `task.intervention.recorded` with `prior_review_window: 1` and
  `prior_cycle: 1`. No `task.accepted`, next-task dispatch, or resume was
  performed after intervention; reopening therefore did not accept or skip
  the task.
- Safety: the disposable repository had no `HEAD` commit and no remotes;
  `git diff --check` passed. No commit, push, branch delivery, pull request,
  hosting action, or delivery command was invoked.

This completes the manual-acceptance matrix when combined with the retained
corrective rerun and the earlier pending-operation recovery evidence. An
independent Wave 2 re-review remains required before any later Wave can start.
