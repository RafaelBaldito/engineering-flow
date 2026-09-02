# Tasks — Wave 1: Controlled Planning Workflow

## Scope

Implement the approved Wave 1 local planning control plane only. The scope ends
when an approved immutable task-plan artifact is recorded at
`READY_FOR_WAVE_2`; it excludes task execution, review/fix cycles, Git/PR
delivery, other providers, and a UI/service.

## Execution Order

| Task | Title | Depends On | Status |
|------|-------|------------|--------|
| TASK-001 | Establish the Durable Workflow Core | — | PENDING |
| TASK-002 | Implement the Codex Planning Runtime Adapter | TASK-001 | PENDING |
| TASK-003 | Implement Controlled Planning Orchestration | TASK-001, TASK-002 | PENDING |
| TASK-004 | Deliver Configuration and the CLI Control Surface | TASK-003 | PENDING |

## Coverage

- TECHSPEC §4.1 domain, store, and sanitization boundaries; §6 persistence,
  events, and idempotency; §8 storage safety → TASK-001
- TECHSPEC §4.1 runtime boundary; §5 provider runtime contract; §8 execution
  safety → TASK-002
- TECHSPEC §4.1 orchestrator boundary; §4.3–§4.4 state progression and
  planning context; approval policy in §4.2; lifecycle recovery in §6 →
  TASK-003
- TECHSPEC §4.1 CLI/configuration boundaries; §4.2 workspace initialization;
  §7 command/error contracts; CLI-facing validation in §9 → TASK-004
- TECHSPEC §9 validation strategy → directly related tests in TASK-001 through
  TASK-004, with the complete suite run in TASK-004

## Execution Notes

Use Python 3.13 and the standard library only. Each task includes the tests
that prove its owned behavior. Do not start a later task until its dependencies
have been reviewed and accepted.
