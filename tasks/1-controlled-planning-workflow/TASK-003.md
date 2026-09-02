# TASK-003 — Implement Controlled Planning Orchestration

## Objective

Implement the sole transition authority that moves one workflow through PRD,
TECHSPEC, and task-plan generation, records approvals and evidence, and safely
recovers/resumes without uncontrolled duplicate work.

## Scope

- Implement `orchestrator.py` service APIs for creating/running a workflow,
  approving/rejecting an artifact, resuming, status, and log retrieval.
- Construct role- and stage-specific planning prompts and execution requests
  with only the authoritative inputs permitted for that stage.
- Enforce the specified planning state machine, per-stage `required`,
  `automatic`, and `conditional` policies, immutable artifact authority, and
  transition/event recording through the store.
- Implement failure classification, incomplete-operation reconciliation,
  `UNKNOWN` handling, explicit rejected-stage regeneration, and human-attention
  routing as specified.
- Add deterministic fake-runtime unit/integration tests for ordered gates,
  policy tables, context scoping, malformed results, interruption boundaries,
  and resume/idempotency behavior.

## Context

### Required

- `docs/waves/1-controlled-planning-workflow/TECHSPEC.md` §4.2–§4.4 and §6
- `src/engineering_flow/domain.py`
- `src/engineering_flow/store.py`
- `src/engineering_flow/runtime.py`

### Optional

- `docs/architecture/architecture-overview.md` §3–§9 and §12–§13
- `docs/waves/1-controlled-planning-workflow/TECHSPEC.md` §5 and §9

## Requirements

- The orchestrator is the only component that selects the next stage, records
  an approval decision, makes an artifact authoritative, or changes workflow
  status/stage.
- Create a UUID workflow by copying the feature request verbatim, hashing it,
  and recording creation in one transaction. Before every stage, persist
  capability/execution/operation intent and emit the required start events.
- Use exactly these authoritative prompt inputs: feature request for PRD;
  feature request plus approved PRD for TECHSPEC; feature request plus approved
  PRD and TECHSPEC for task plan. Include role, artifact type, output contract,
  scope boundary, and no-transition-authority instruction in each prompt.
- On valid runtime success, atomically record immutable artifact data, provider
  metadata, completion events, `AWAITING_APPROVAL`, and the applicable approval
  decision. Record the waiting state even for automatic decisions.
- Approval/rejection must target the current undecided artifact exactly; stale
  or already decided artifacts are conflicts. Rejection preserves the artifact
  and permits regeneration only through `resume --regenerate` for its current
  rejected stage.
- Resume must reconcile pending work, return completed operation outcomes,
  report pending approval, retry only eligible failed planning work, and never
  skip approval or re-run an unknown provider operation automatically.

## Constraints

- Depend only on the runtime protocol and store APIs; do not import Codex
  adapter details or issue subprocesses directly.
- Do not invoke Developer or Reviewer roles, run repository scripts/tests, or
  perform Git/PR actions.
- Treat runtime payloads and provider prose as untrusted; only a schema-valid
  structured final result can become an artifact.

## Acceptance Criteria

- A fake runtime can drive PRD → TECHSPEC → task plan only after each exact
  required approval, ending at `COMPLETED/READY_FOR_WAVE_2` after task-plan
  approval.
- Required, automatic, and conditional policies produce the correct durable
  waiting and decision records.
- Each execution request has the required bounded context and prior-artifact
  hashes; event history and future-wave documents are absent.
- Interrupted, repeated, and rejected operations preserve prior evidence and
  do not duplicate a completed artifact, approval, or recorded operation.
- Unknown/non-retriable/authentication outcomes leave a safe persisted failure
  or `HUMAN_ATTENTION` state rather than advancing the workflow.

## Validation

- `python -m unittest discover -s tests -p 'test_orchestrator.py'`
- `python -m unittest discover -s tests -p 'test_planning_workflow.py'`
- `python -m compileall src`

## Dependencies

- TASK-001 — durable domain, evidence, and idempotency APIs.
- TASK-002 — provider-neutral runtime contract and execution result behavior.

## Out of Scope

- Command parsing/presentation, TOML configuration I/O, task execution, review,
  Git operations, and PR delivery.
