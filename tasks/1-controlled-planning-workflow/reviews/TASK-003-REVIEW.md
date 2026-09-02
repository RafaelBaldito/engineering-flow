## Review Result

FIX_REQUIRED

## Task

`TASK-003 — Implement Controlled Planning Orchestration`

## Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p 'test_orchestrator.py'` | PASS | 11 tests passed. |
| `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -p 'test_planning_workflow.py'` | PASS | 1 test passed. |
| `.\\.venv\\Scripts\\python.exe -m compileall src` | PASS | Completed successfully. |

## Acceptance Criteria

| Criterion | Result | Evidence |
|-----------|--------|----------|
| Fake runtime advances PRD → TECHSPEC → task plan only after each required exact approval, then completes at `READY_FOR_WAVE_2`. | PASS | `test_required_workflow_is_sequential_and_context_is_scoped` and `test_full_approval_flow_is_idempotent` pass; approval transition code is in `orchestrator.py`. |
| Required, automatic, and conditional policies record the correct waiting and decision evidence. | PASS | Policy handling at `orchestrator.py:568-620`; conditional and automatic paths are covered by the targeted tests. |
| Requests contain only bounded authoritative inputs and prior-artifact hashes. | PASS | `_approved_inputs` and `_prompt` at `orchestrator.py:396-422`; the sequential workflow test verifies one, two, then three inputs and input hashing. |
| Interrupted, repeated, and rejected operations preserve evidence without duplicate completed artifacts, approvals, or operations. | FAIL | A retry of a retriable failed generation reuses the completed operation and execution record, then overwrites its recorded failure; see FINDING-001. Workflow creation can also persist a workflow before its required feature evidence is written; see FINDING-002. |
| Unknown, non-retriable, and authentication outcomes persist a safe failure or `HUMAN_ATTENTION` state rather than advancing. | PASS | `orchestrator.py:517-567` routes unknown and authentication outcomes safely; targeted tests cover unknown and retry eligibility. |

## Findings

### FINDING-001 — HIGH — Retried generation overwrites a completed failed operation and execution

- Location: `src/engineering_flow/orchestrator.py:281-285`, `src/engineering_flow/orchestrator.py:459-467`, `src/engineering_flow/store.py:382-404`, `src/engineering_flow/store.py:486-518`
- Issue: Resuming a retriable failure passes the same stage revision to `create_generation_intent`. Because the failed operation was already marked `COMPLETED`, the store returns that existing operation and execution. The orchestrator executes the provider again anyway, and `complete_generation` later changes that original failed execution to `COMPLETED` and replaces the operation's related record with the new artifact.
- Evidence: `fail_generation` sets the operation to `COMPLETED` at `store.py:533-561`; `create_generation_intent` returns any existing operation at `store.py:382-404`; `complete_generation` then writes a success lifecycle and terminal result to that same execution at `store.py:515-518`. Thus the durable failure classification/detail is lost and a provider call occurs under an already completed idempotency key.
- Expected: A completed operation key must return its recorded outcome. An eligible retry must have a distinct durable intent/execution (and an unambiguous idempotency identity) while retaining the prior failed execution and operation evidence.
- Fix direction: Model an eligible retry as a new recorded attempt with a unique operation identity/revision or add a durable attempt identity that preserves the first failed operation; do not reuse or mutate completed records.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: no`; `REGRESSION_FROM_FIX: no`

### FINDING-002 — HIGH — Workflow creation commits before required feature-request evidence exists

- Location: `src/engineering_flow/orchestrator.py:137-149`, `src/engineering_flow/store.py:257-281`
- Issue: `create_workflow` commits the `workflows` row and `workflow.created` event before it writes the feature-request file. The feature hash is not recorded at creation either. If the write fails or the process stops in that gap, a durable workflow exists with no verbatim input evidence or creation-time hash.
- Evidence: `store.create_workflow()` opens and commits its transaction before `orchestrator.py` calls `destination.write_bytes(content)`. The workflow schema at `store.py:88-98` has no feature-input hash column, and `workflow.created` stores only the provider at `store.py:279-280`.
- Expected: Creation must retain the feature request verbatim, hash it, and record the workflow creation as one recoverable creation unit; a persisted workflow must not exist without its authoritative input evidence.
- Fix direction: Extend the durable creation boundary to record the feature input path/hash and coordinate file creation with the transaction/recovery semantics, including a regression test for an input-write interruption.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: no`; `REGRESSION_FROM_FIX: no`

### FINDING-003 — MEDIUM — Required malformed-result and stale-decision regressions are not tested

- Location: `tests/test_orchestrator.py`
- Issue: The task explicitly requires deterministic tests for malformed results and stale/duplicate approval protection, but the targeted suite has no test that supplies an invalid final payload or attempts approval/rejection of a stale/already-decided artifact.
- Evidence: The test file exercises happy-path gating, policies, capability safety, selected interruption boundaries, rejection regeneration, unknown outcomes, and retry classifications; it contains no malformed-payload test and no stale/duplicate decision test. `_valid_payload` and `_validate_current_approval` are therefore unprotected by the task-owned regression suite.
- Expected: The required acceptance scenarios must be covered by deterministic fake-runtime tests, proving that malformed results create no artifact and stale/already-decided decisions are conflicts without mutation.
- Fix direction: Add focused tests for invalid payload shapes/types and for stale and duplicate approval/rejection attempts, asserting persisted state and evidence remain unchanged.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: no`; `REGRESSION_FROM_FIX: no`

## Summary

The targeted tests and compile check pass, and the normal gated workflow is implemented. However, durable retry/idempotency evidence is overwritten on a retriable failure, workflow creation is not an atomic/recoverable feature-input creation boundary, and required regression scenarios are absent. The task is not ready to accept.
