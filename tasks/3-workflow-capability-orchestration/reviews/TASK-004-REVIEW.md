## Review Result

FIX_REQUIRED

This re-review supersedes the prior `FIX_REQUIRED` review record. Its prior
findings on stage-targeted approvals and structured Wave 2 accepted-task
evidence are resolved: `approval_target_stage` is now persisted and checked,
and the Wave 2 handoff uses `has_accepted_task_evidence()`.

## Task

`TASK-004 — Orchestrate Canonical Lifecycle Progression`

## Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `./scripts/env-preflight` | PASS | Repository-local Python 3.13.15 environment and CLI are ready; checkout was already dirty in the Wave 3 implementation paths. |
| `.venv/bin/python3 -m unittest discover -s tests -p 'test_orchestrator.py' -q` | PASS | 29 tests passed. |
| `.venv/bin/python3 -m unittest discover -s tests -p 'test_planning_workflow.py' -q` | PASS | 1 test passed. |
| `.venv/bin/python3 -m compileall -q src` | PASS | Completed without output. |
| `.venv/bin/python3 -m unittest discover -s tests -q` | PASS | 120 tests passed. |
| `git diff --check` | PASS | No whitespace errors reported. |

## Acceptance Criteria

| Criterion | Result | Evidence |
|-----------|--------|----------|
| A canonical workflow follows only legal persisted stages and demands the required active governance fact plus structured capability result at each gated transition. | FAIL | Legal-successor and transactional authority checks exist, but Wave/final-review results are accepted on `outcome == "success"` alone and the required acceptance is checked before the review outcome is recorded. |
| Conditional architecture and exact approval canonical-successor behavior are deterministic; a Wave PASS cannot start another Wave. | FAIL | Delivery-plan routing and exact approval-target filtering are deterministic, but no Wave-review PASS is enforced before the state can enter `FINAL_REVIEW`; arbitrary successful normalized review output can satisfy the capability-result branch. |
| Historical records remain readable without inferred governance, while new canonical workflows persist versioned state and resume without duplicate lifecycle/provider work. | FAIL | Canonical state is versioned and its write operation is idempotent, but `resume()` is a state getter and the canonical class has no durable request/dispatch/reconciliation lifecycle. |
| Any missing or ambiguous authority/evidence/capability outcome is classified, evented, and paused without delivery side effects. | PASS | Invalid state/evidence/capability, unresolved capability, permission denial, unknown outcomes, and unavailable/ambiguous authority route through `_attention()` into an evented `HUMAN_ATTENTION` operation. |

## Findings

### FINDING-001 — HIGH — Review acceptance is gated in the wrong direction and does not require PASS

- Location: `src/engineering_flow/orchestrator.py:105-113, 179-214`; `src/engineering_flow/store.py:2138-2175`
- Issue: Leaving `WAVE_REVIEW` requires a pre-existing `WAVE_ACCEPTANCE`, and leaving `FINAL_REVIEW` requires a pre-existing `RELEASE_ACCEPTANCE`, but the normalized review result is only persisted later in that same transition. Moreover, the result validation only requires `outcome == "success"`; it never requires a review decision of `PASS` or binds the governance acceptance to that review evidence. A manually recorded acceptance with unrelated completed evidence can therefore allow a non-PASS review result to advance to the next lifecycle stage.
- Evidence: `_AUTHORITY_BY_STAGE` maps `WAVE_REVIEW` to `WAVE_ACCEPTANCE` and `FINAL_REVIEW` to `RELEASE_ACCEPTANCE` at lines 111-112; `advance()` validates only `outcome`, capability ID, and schema at lines 179-189 before requiring that authority at lines 195-205. The transition then creates the result/evidence at lines 207-214. Neither the orchestrator nor store searches for a Wave/final review `PASS` field or ties it to the acceptance record.
- Expected: Record and validate a structured Wave/final-review decision before its corresponding acceptance can become active; only a PASS result with its exact evidence may support Wave acceptance or release acceptance. The lifecycle must not enter final review/release preparation from a non-PASS review.
- Fix direction: Model review-result decision/evidence explicitly, validate `PASS` in the canonical result contract, and enforce the proper result-to-acceptance lineage in the transactional gate rather than treating an arbitrary successful provider outcome as a review pass.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: yes`; `REGRESSION_FROM_FIX: no`

### FINDING-002 — HIGH — Canonical resume has no request, dispatch, or reconciliation path

- Location: `src/engineering_flow/orchestrator.py:116-124, 135-243`
- Issue: The canonical orchestrator accepts a caller-supplied completed `normalized_result`; it has no `AgentRuntime`/provider dispatch operation or durable request/dispatch state. `resume()` merely returns `get_lifecycle_state()`. Consequently an interrupted or uncertain canonical provider operation cannot be reconciled to known evidence or safely paused without relying on an external caller to reconstruct it.
- Evidence: The class constructor receives only store/registry/runtime-name configuration, `advance()` begins after a normalized result already exists, and `resume()` at lines 238-243 contains only a state lookup. No canonical orchestration test covers dispatch, interruption, or reconciliation; the sole canonical test covers PRD advancement and a missing delivery-plan authority.
- Expected: Canonical capability work must have durable request/dispatch/result states and a resume/reconciliation path that returns recorded work for identical operations, reconciles known evidence, or records classified human attention without duplicate provider work.
- Fix direction: Introduce the bounded canonical capability-operation lifecycle around the resolved runtime binding and make `resume()` reconcile that durable state before any re-dispatch.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: no`; `REGRESSION_FROM_FIX: no`

## Summary

The implementation now enforces exact stage-targeted approvals, validates
persisted Wave 2 reviewer-PASS evidence, records legal transitions atomically,
and passes the required validation. It remains unsafe to accept because review
PASS/acceptance lineage is not enforced and canonical provider work cannot be
reconciled after interruption.
