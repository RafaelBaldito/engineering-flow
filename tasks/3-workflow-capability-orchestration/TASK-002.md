# TASK-002 — Define Capability Contracts and Codex Materialization

## Objective

Implement versioned provider-neutral domain capability definitions and
resolution, with a Codex adapter mapping that validates Skill/prompt mechanism
equivalence before any dispatch.

## Scope

- Define registry/resolver contracts for all TECHSPEC §4 capability families,
  their lifecycle-version support, role, schemas, evidence, and human-policy
  placement.
- Extend runtime requests/results and adapter configuration metadata so domain
  capability, role, runtime/provider, and provider-native mechanism remain
  distinct.
- Materialize the sole configured Codex runtime through an adapter-local Skill
  reference or bounded prompt/template reference, version/digest, and
  normalized contract version; reject incompatible bindings.
- Add deterministic resolver/runtime/adapter tests without live Codex calls.

## Context

### Required

- `docs/waves/3-workflow-capability-orchestration/TECHSPEC.md` §4 and §8–§10
- `src/engineering_flow/domain.py`
- `src/engineering_flow/runtime.py`
- `src/engineering_flow/codex_cli.py`

### Optional

- `src/engineering_flow/config.py`
- `tests/test_runtime.py`
- `tests/test_codex_cli.py`

## Requirements

- Resolution inputs are lifecycle version, stage, configured runtime/provider,
  repository constraints, and capability ID. Return exactly one compatible
  binding or structured unsupported/invalid outcome; introduce neither fallback
  nor autonomous provider routing.
- A canonical capability must never contain Skill names/paths, prompts, model,
  session, or provider identifiers. The adapter alone owns native descriptor
  details and verifies matching capability ID, compatible schema/version, role,
  required inputs, and required output/evidence semantics before dispatch.
- Preserve Wave 2 task Developer/Reviewer execution contracts as consumers of
  the registry; do not reimplement task selection, testing, review, or fixes.

## Constraints

- Codex is the only configured V1 runtime, but no Codex-specific type may
  become the lifecycle domain API. Provider mismatch is non-dispatchable and
  routes through the later orchestration human-attention path.
- No persistent authority decision, CLI parsing, external side effect, or
  semantic claim that two model outputs are identical.

## Expected Files/Areas

- `src/engineering_flow/domain.py`, `src/engineering_flow/runtime.py`,
  `src/engineering_flow/codex_cli.py`, and possibly `src/engineering_flow/config.py`
- `tests/test_runtime.py`, `tests/test_codex_cli.py`

## Acceptance Criteria

- Each canonical lifecycle capability has a stable ID, schema/version, role,
  supported lifecycle versions, required evidence, and policy placement.
- Resolution deterministically returns a single compatible binding or a
  structured failure for unknown capability, version/schema/role mismatch, or
  unsupported provider permission.
- Codex Skill and prompt/template descriptors are adapter-local and dispatch
  is rejected when their declared normalized contracts are not equivalent.
- Existing planning and Wave 2 role runtime behavior remains compatible.

## Validation

- `.venv/bin/python3 -m unittest discover -s tests -p 'test_runtime.py' -q`
- `.venv/bin/python3 -m unittest discover -s tests -p 'test_codex_cli.py' -q`
- `.venv/bin/python3 -m compileall -q src`

## Dependencies

- TASK-001 — versioned records and durable request/result persistence.

## Out of Scope

- Governance decisions, stage progression, remediation routing, CLI commands,
  new providers, and delivery operations.
