## Review Result

FIX_REQUIRED

## Task

`TASK-001 — Establish the Durable Workflow Core`

## Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `python -m unittest discover -s tests -p 'test_domain.py'` | PASS | 2 tests passed. |
| `python -m unittest discover -s tests -p 'test_store.py'` | PASS | 6 tests passed. |
| `python -m unittest discover -s tests -p 'test_sanitization.py'` | PASS | 2 tests passed. |
| `python -m compileall src` | PASS | All package modules compiled successfully. |
| `python -m unittest discover -s tests` | PASS | 10 tests passed. |
| Focused environment-retention probe | FAIL | `append_event` retained `{"environment":{"PATH":"C:/sensitive-runtime-path"}}`; `create_generation_intent` retained `{"environment":{"HOME":"C:/sensitive-home"}}` in the execution capability report. |

## Acceptance Criteria

| Criterion | Result | Evidence |
|-----------|--------|----------|
| The domain expresses every Wave 1 stage, status, approval decision/policy, role, and specified failure classification without Codex-specific types. | PASS | `test_domain.py` verifies all stages, statuses, approvals, classifications, and the `prd`, `architect`, and `planner` role set. |
| A new database has all required durable records, constraints, WAL, and foreign-key behavior. | PASS | `test_schema_enables_wal_foreign_keys_and_required_tables` verifies WAL, foreign keys, and all seven required tables. |
| Replaying a completed operation key or approval cannot create a duplicate recorded side effect. | PASS | `test_generation_intent_and_approval_replay_are_idempotent` verifies a single execution, artifact, and approval on replay. |
| Artifact revisions are immutable, hash-verified on read, and a modified file results in a typed corruption failure. | PASS | `test_generation_completion_matches_intent_binding` rejects mismatched stage, revision, and destination; `test_artifact_is_revisioned_immutable_and_hash_verified` verifies hash enforcement and tamper detection. |
| Persisted event payloads are sanitized and maintain a strictly increasing sequence for each workflow. | FAIL | Sequences are monotonic and configured secrets are redacted, but raw environment mappings can be retained in event and execution payloads, violating TASK-001's no-raw-environment constraint. |

## Findings

### FINDING-001 — HIGH — Raw environment mappings remain persistable outside configuration snapshots

- Location: `src/engineering_flow/sanitization.py:47-64`; `src/engineering_flow/store.py:246, 414, 516`
- Issue: `sanitize_payload` redacts secret-shaped keys but does not remove `env` or `environment` mappings. The store applies this generic sanitizer to persisted event payloads, execution capability reports, and terminal results.
- Evidence: The focused probe persisted and read back `{"environment":{"PATH":"C:/sensitive-runtime-path"}}` from `append_event`, and `{"environment":{"HOME":"C:/sensitive-home"}}` from `create_generation_intent(..., capability_report=...)`. In contrast, only `create_workflow` uses `sanitize_configuration_snapshot`, which removes those mappings.
- Expected: No persistence path may retain raw environment variables, including events and execution metadata, while still sanitizing configured secret values and credential-shaped data.
- Fix direction: Apply an environment-removing sanitizer to every persisted diagnostic/metadata payload (events, capability reports, terminal results, and any equivalent failure payload), then add focused regression tests for each write path.
- Review provenance: `MISSED_IN_PREVIOUS_REVIEW: yes`; `REGRESSION_FROM_FIX: no`

## Summary

The prior role, generation-intent binding, and configuration-snapshot findings are resolved, and all required automated checks pass. TASK-001 still violates its explicit secret-retention safety constraint because raw environment mappings can persist through event and execution metadata paths. This is an implementation defect within the approved task scope.
