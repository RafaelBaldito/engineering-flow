# Tasks — Wave 3: Workflow Capability Orchestration

## Scope

Implement only the approved Wave 3 canonical lifecycle control plane: versioned
provider-neutral capabilities, durable governance and lifecycle facts,
compatibility, remediation routing, and thin CLI/event access. The scope ends
at persisted Wave 3 lifecycle control; it excludes Wave 2 task-loop mechanics,
Wave 4 final validation and all Git/hosting side effects.

## Execution Order

| Task | Title | Depends On | Status |
| --- | --- | --- | --- |
| TASK-001 | Establish Versioned Lifecycle Persistence Foundations | — | PENDING |
| TASK-002 | Define Capability Contracts and Codex Materialization | TASK-001 | PENDING |
| TASK-003 | Persist Governance Facts and Active Authority Lineage | TASK-001 | PENDING |
| TASK-004 | Orchestrate Canonical Lifecycle Progression | TASK-001, TASK-002, TASK-003 | PENDING |
| TASK-005 | Route Review Remediation and Acceptance Safely | TASK-003, TASK-004 | PENDING |
| TASK-006 | Expose Governed Lifecycle Commands and Observability | TASK-002, TASK-003, TASK-004, TASK-005 | PENDING |
| TASK-007 | Prove Canonical Lifecycle Compatibility and Safety | TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006 | PENDING |

## Coverage

- TECHSPEC §3 and §7 lifecycle versions, historical reads, migrations, durable
  operations, and reconciliation → TASK-001, TASK-004, TASK-007
- TECHSPEC §4 capability schema, resolution, provider-neutral boundaries, and
  Codex Skill/prompt equivalence → TASK-002, TASK-004, TASK-007
- TECHSPEC §5 decision facts, active lineage, revocation, supersession, and
  transactional advancement → TASK-003, TASK-004, TASK-005, TASK-007
- TECHSPEC §6 review findings and deterministic remediation routing → TASK-005,
  TASK-007
- TECHSPEC §7 CLI, correlated events, and safe projections → TASK-006, TASK-007
- TECHSPEC §9–§11 human-attention, safety, validation, and Wave 4 exclusions →
  TASK-001 through TASK-007

## Execution Notes

Use Python 3.13, the repository-local Linux environment, and standard-library
patterns already used by the SQLite/WAL store. The orchestrator remains the
sole lifecycle authority; providers return evidence only. Do not begin a
dependent task until its task review passes. The approved TECHSPEC permits this
task plan only; task-plan approval is still required before registration or any
Developer/Reviewer/Fixer activity.
