# Tasks — Wave 2: Autonomous Sequential Engineering Loop

## Scope

Implement the approved Wave 2 task lifecycle only: import the immutable
approved task-plan manifest, execute one task at a time through Developer,
required-test evidence, independent review, bounded remediation, and durable
human intervention. The scope ends at `TASKS_READY_FOR_WAVE_REVIEW`; it
excludes Wave acceptance, Git/PR operations, merge, release final review, and
Wave 3.

## Execution Order

| Task | Title | Depends On | Status |
|------|-------|------------|--------|
| TASK-001 | Establish Durable Task Definitions and Lifecycle Evidence | — | PENDING |
| TASK-002 | Generalize Runtime Contracts and Codex Role Execution | TASK-001 | PENDING |
| TASK-003 | Implement Sequential Task Orchestration | TASK-001, TASK-002 | PENDING |
| TASK-004 | Expose Execution Policy and Task Lifecycle CLI Controls | TASK-003 | PENDING |
| TASK-005 | Prove the End-to-End Durable Task Lifecycle | TASK-001, TASK-002, TASK-003, TASK-004 | PENDING |

## Coverage

- TECHSPEC §4.1–§4.2 task stages, immutable manifest import, task state, and
  ordered selection authority; §7 durable records/artifacts/idempotency →
  TASK-001, TASK-003
- TECHSPEC §4.3 decision rules, intervention behavior, failure routing, and
  resume behavior → TASK-003, TASK-005
- TECHSPEC §5–§6 provider-neutral Developer/Reviewer contracts, capabilities,
  role-scoped context, session continuity/independence, and payload semantics
  → TASK-002, TASK-003
- TECHSPEC §7 transactional evidence, task-correlated operations, recovery,
  canonical artifact paths, and atomic acceptance/advancement → TASK-001,
  TASK-003, TASK-005
- TECHSPEC §8 configuration migration, `intervene`, status/log projections,
  events, and classified failure presentation → TASK-004, TASK-005
- TECHSPEC §9 safety controls → TASK-001 through TASK-004
- TECHSPEC §10 validation strategy and regression/manual-acceptance evidence
  → focused tests in TASK-001 through TASK-004; cross-component lifecycle and
  recovery tests in TASK-005

## Execution Notes

Use Python 3.13 and the standard library only. Preserve Wave 1 planning
commands, artifacts, schema rows, and `READY_FOR_WAVE_2` workflows. The
orchestrator remains the only lifecycle-transition authority; provider output
is untrusted evidence. Do not start a dependent task until its task review has
passed. TASK-005 is integration/acceptance-focused and does not replace the
focused tests owned by preceding tasks.
