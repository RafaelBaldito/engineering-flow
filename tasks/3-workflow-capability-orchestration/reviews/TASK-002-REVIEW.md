## Review Result

PASS

## Task

`TASK-002 — Define Capability Contracts and Codex Materialization`

This re-review supersedes the prior `FIX_REQUIRED` record.

## Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `./scripts/env-preflight` | PASS | Python 3.13.15, editable package, and CLI were ready. The checkout was dirty with the implementation/review state under review. |
| `.venv/bin/python3 -m unittest discover -s tests -p 'test_runtime.py' -q` | PASS | 5 tests passed. |
| `.venv/bin/python3 -m unittest discover -s tests -p 'test_codex_cli.py' -q` | PASS | 21 tests passed. |
| `.venv/bin/python3 -m compileall -q src` | PASS | Completed successfully. |
| `.venv/bin/python3 -m unittest discover -s tests -q` | PASS | 110 tests passed. |
| `git diff --check` | PASS | No whitespace errors reported. |

## Acceptance Criteria

| Criterion | Result | Evidence |
|-----------|--------|----------|
| Each canonical lifecycle capability has a stable ID, schema/version, role, supported lifecycle versions, required evidence, and policy placement. | PASS | `CapabilityId`, `DomainCapability`, and the 13-entry `CANONICAL_CAPABILITIES` provide the provider-neutral ID, schema, lifecycle support, role, inputs/outputs/evidence, and human-policy placement for every §4 family. |
| Resolution deterministically returns a single compatible binding or a structured failure for unknown capability, version/schema/role mismatch, or unsupported provider permission. | PASS | `CapabilityRegistry.resolve()` returns only one `CapabilityBinding` or `UNKNOWN_CAPABILITY`, `INCOMPATIBLE`, or `UNSUPPORTED_PROVIDER`; duplicate canonical IDs are rejected at construction. The runtime tests cover compatible, role-mismatch, unsupported-provider, and duplicate-definition cases. |
| Codex Skill and prompt/template descriptors are adapter-local and dispatch is rejected when their declared normalized contracts are not equivalent. | PASS | `CodexMechanismDescriptor` is confined to `codex_cli.py`; canonical execution calls `materialize_capability()` before preflight/subprocess construction, verifies ID/schema/role/input/output/evidence equivalence, and carries the validated descriptor's kind/reference/version/digest into the dispatched instruction. Tests prove both rejection without subprocess creation and descriptor materialization in the invocation. |
| Existing planning and Wave 2 role runtime behavior remains compatible. | PASS | `ExecutionContract.LEGACY` preserves unbound existing requests while canonical bindings are validated as an all-or-nothing set. The full 110-test suite passed. |

## Recheck of Prior Blocking Findings

| Prior finding | Result | Evidence |
|---------------|--------|----------|
| FINDING-001 — canonical dispatch could bypass materialization | RESOLVED | `CodexCliRuntime.execute()` obtains the descriptor before capability preflight and passes it through `_process()` to `_instruction_for()`. The dispatch test captures all materialized descriptor fields, and the missing-descriptor test verifies no subprocess is started. |
| FINDING-002 — duplicate capability definitions were silently selected by insertion order | RESOLVED | `CapabilityRegistry.__init__()` rejects duplicate IDs and `test_capability_registry_rejects_duplicate_definitions` passes. |

## Summary

All acceptance criteria are satisfied. The previously blocking materialization path now propagates the validated adapter-local descriptor into the Codex invocation, and duplicate canonical capability definitions are rejected deterministically. Required and full validation pass.
