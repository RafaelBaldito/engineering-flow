The repository has a strong reusable execution and persistence foundation, but its user-facing workflow is still V1. The main gap is not infrastructure; it is that the product currently orchestrates PRD/TECHSPEC/Wave governance instead of the smaller V2 Intake → Feature Contract → Plan → Execute loop.

I analyzed the current working tree, including the uncommitted Wave 3 changes. No files were modified. The full suite passes: 120 tests in 10.356 seconds. Passing tests do not mean the in-progress canonical lifecycle is accepted: its latest task review remains FIX_REQUIRED with two high-severity findings (tasks/3-workflow-capability-orchestration/reviews/TASK-004-REVIEW.md:25).

## 1. Current Architecture

Engineering Flow is a Python CLI with four principal layers:

cli.py exposes init, run, status, approve, reject, resume, intervene, and logs. run requires a feature file and starts the planning pipeline (src/engineering_flow/cli.py:83).

PlanningOrchestrator owns the production lifecycle:
PRD → TECHSPEC → TASK_PLAN → READY_FOR_WAVE_2 → TASK_EXECUTION → TASKS_READY_FOR_WAVE_REVIEW.

WorkflowStore persists workflows, operations, executions, sessions, artifacts, approvals, tasks, cycles, and events in repository-local SQLite under .engineering-flow/. It uses WAL, transactions, hashes, and idempotency keys (src/engineering_flow/store.py:170).

CodexCliRuntime invokes codex exec without a shell, selects read-only or workspace-write sandboxes, validates structured output, normalizes JSONL events, applies timeouts, and captures provider usage (src/engineering_flow/codex_cli.py:420).

After task-plan approval, tasks are imported from an embedded JSON manifest. Execution is ordinal and sequential. Each task goes through Developer → reported tests → independent Reviewer → Fix when required. A single resume invocation performs one persisted action rather than autonomously driving the complete post-approval workflow (src/engineering_flow/orchestrator.py:871).

There are also two overlapping transitional systems:

An in-progress CanonicalLifecycleOrchestrator and governance/capability persistence model for the more elaborate V1 Wave/release lifecycle.
A separate development-only tools/wave_controller with Markdown state, checkout fingerprinting, dependency-aware task selection, a continuous task loop, and hard-coded Codex model policy.

## 2. Keep

These components already align well with V2 and should be evolved rather than replaced:

Layer boundaries. CLI, orchestrator, provider-neutral runtime, Codex adapter, domain values, and persistence are already separated.

SQLite persistence. The existing store is more robust than introducing parallel .ai/*.json files. V2 requires structured external state, not a particular format. SQLite plus immutable artifacts satisfies that direction.

Transactional state changes and events. BEGIN IMMEDIATE, rollback handling, sequenced events, and operation identities are valuable foundations (src/engineering_flow/store.py:521).

Idempotency and recovery concepts. Operations distinguish intent, running, completed, failed, and unknown outcomes.

Artifact hashing and corruption detection. Feature inputs, planning artifacts, task definitions, and evidence are hash-bound.

Sequential task execution. This matches the V2 MVP’s deliberate exclusion of parallel execution.

Implementation/review separation. Reviewer sessions are distinct, use read-only capability, and receive task evidence rather than the Developer transcript.

Structured agent results. JSON schemas and normalized terminal results are appropriate for Feature Contracts, Plans, reviews, and fixes.

Codex process safety. Argument-vector invocation, capability checks, sandbox selection, bounded timeouts, secret sanitization, and normalized provider events should remain.

Task-local continuity. Reusing the Developer’s task context for fixes while keeping reviewers independent is compatible with V2.

CLI shell. init, run, status, approve, resume, intervene, and logs remain useful command concepts; their semantics need adaptation.

Bootstrap checkout fingerprinting concept. The implementation in tools/wave_controller/fingerprint.py:21 can inform V2 hardening, though it should move into the product boundary rather than remain a second controller.

Test coverage and standard-library footprint. The existing 120-test baseline makes incremental migration practical.

## 3. Change

### Workflow/state machine

Replace both V1 stage sets with one versioned V2 lifecycle:

INTAKE → PLAN → WAITING_PLAN_APPROVAL → IMPLEMENT → VERIFY → REVIEW → FIX → … → DONE

with NEEDS_CLARIFICATION, REJECTED, FAILED, CANCELLED, and STOPPED_REQUIRES_HUMAN as explicit outcomes.

The existing Stage and CanonicalStage currently model two different V1 workflows (src/engineering_flow/domain.py:15). Preserve historical readability, but new runs should use a single V2 contract.

### Persisted state

Retain SQLite and the current artifact directory, but add first-class records for:

Feature Contract and Intake outcome;
approved Plan;
current V2 phase and current task;
verification executions and structured results;
global counters and deadlines;
selected/requested/actual model profile;
escalation history.

Configuration snapshots should remain authoritative per run.

Artifact files need atomic replacement semantics. Currently some files are written directly inside a database transaction; interruption can leave a partial or orphaned file even if SQLite rolls back.

### Planning/task model

Replace mandatory PRD → TECHSPEC → task-plan generation with one structured Plan. Optional design material may be generated only for complex work.

The existing task contract preserves useful fields—title, instructions, acceptance criteria, required tests, and context paths—but must add:

requirements;
constraints;
depends_on;
complexity;
risk;
explicit verification steps.

The current task parser has no dependencies, complexity, or risk and selects by ordinal (src/engineering_flow/store.py:104).

### Agent/Codex integration

Keep AgentRuntime and CodexCliRuntime, but make requests carry an execution profile rather than relying on provider defaults. The product adapter currently supplies no model or reasoning arguments.

Model and reasoning selection exists only in the bootstrap host and is hard-coded to one Terra profile (tools/wave_controller/host.py:20). Move the useful invocation mechanism into configurable product policy.

### Implementation/review/fix loop

Retain the current independent reviewer and structured findings. Change the driver so that after plan approval it runs autonomously until completion or a circuit breaker opens.

Verification failures must route to Fix. Today a failed or missing Developer-reported test result pauses for human attention; only reviewer FIX_REQUIRED enters the automatic fix loop (src/engineering_flow/orchestrator.py:919).

### Verification

Move test execution out of the Developer’s self-reported payload. The current system validates that the Developer claims every required command passed, but Engineering Flow itself does not execute those commands (src/engineering_flow/orchestrator.py:1099).

Introduce an orchestrator-owned verifier that executes the approved formatter/linter/type/test/build commands and records command, exit status, duration, and bounded output.

### CLI

Adapt run so its first observable behavior is V2 Intake, rather than immediate PRD generation. Keep approve, but make the primary target the Plan. status and logs should expose V2 phase, task, budgets, profile, attempts, and verification results.

## 4. Remove or Simplify

Mandatory PRD, TECHSPEC, delivery-plan, architecture, Wave-review, final-review, and delivery-preparation stages. These are outside the normal V2 MVP path.

Per-artifact planning approvals. Replace PRD/TECHSPEC/task-plan approvals with one Plan approval gate.

Most Wave/release governance machinery for new V2 runs. Scopes, Wave acceptance, release acceptance, delivery authorization, revocation, supersession, and historical migration logic address the superseded V1 architecture. Keep compatibility readers only as long as existing persisted workflows require them.

The in-progress canonical orchestrator. It is not wired into the product CLI and is currently unsafe around review acceptance and provider reconciliation. Do not finish it as designed merely because work has already been invested.

The separate bootstrap wave controller as an ongoing runtime. Fold only valuable concepts—continuous driving, checkout fingerprints, writer restraint, and model arguments—into the main product, then retire or clearly quarantine the duplicate controller.

Role and state aliases. Aliases such as ACTIVE/IN_PROGRESS, ACCEPTED/COMPLETED, and duplicate historical/canonical types make transitions harder to reason about.

Large always-relevant skill topology. Keep narrowly applicable procedures for planning, implementation, review, and fix, but V2 should not require the full PRD/Wave/final-review skill chain for ordinary work.

This does not require a repository rewrite. The simplification should be implemented beside the historical lifecycle using an explicit V2 lifecycle version, followed by retirement of dead V1 paths after compatibility requirements are resolved.

## 5. Missing

The following V2 MVP capabilities do not currently exist end to end:

Intake reasoning and structured classification of unknowns.
A validated Feature Contract with READY, NEEDS_CLARIFICATION, and REJECTED.
Clarification submission and resumption into Intake.
A single structured Plan and human Plan approval gate.
Dependency-aware product task scheduling.
Task complexity and risk classification.
A product Model Router based on phase, complexity, risk, and attempt.
Configurable logical profiles mapped to exact Codex models and reasoning levels.
Model escalation after failures.
Orchestrator-executed deterministic verification.
Automatic Verify → Fix routing.
Automatic post-approval execution through all tasks.
Global max_agent_calls, total fix cycles, review cycles, task attempts, and elapsed-time limits.
A unified circuit-breaker check through which every agent invocation passes.
STOPPED_REQUIRES_HUMAN with an explicit budget-exhaustion reason.
Aggregated accounting by phase/task/profile.
Clear measured-versus-unavailable token telemetry semantics.
First-pass acceptance, verification-pass, escalation, and intervention metrics.
Product-level checkout fingerprints and stale review detection.
Cross-process single-writer ownership or lease protection.
Atomic artifact-file persistence.
An end-to-end CLI demonstration of the V2 workflow.

## 6. Migration Risks

Two active lifecycle models. Adding a third without explicitly making V2 authoritative would deepen the current ambiguity.

Dirty, partially accepted Wave 3 work. Some persistence/capability pieces are useful, but the latest canonical-orchestration review identifies broken review acceptance ordering and missing dispatch recovery (tasks/3-workflow-capability-orchestration/reviews/TASK-004-REVIEW.md:36).

Schema evolution. Existing .engineering-flow databases must remain readable without inventing V2 facts.

Verification trust boundary. Switching from agent-reported tests to orchestrator-executed commands changes safety, timeout, output-capture, and command-validation requirements.

Budget bypass. Adding autonomous execution before central accounting would make the new loop unsafe.

Concurrent CLI processes. The in-process lock and SQLite writer transaction do not by themselves prevent two processes from dispatching external agents concurrently.

Model availability. Profile names must be stable even when exact Codex model identifiers change.

Over-preserving V1 abstractions. Reusing persistence and runtime infrastructure is valuable; preserving Wave/release governance in the V2 happy path is not.

Insufficient vertical validation. Unit-complete schemas and routers would not satisfy the V2 MDS principle unless reachable through the actual CLI.

## 7. Recommended Migration Order

Introduce the V2 lifecycle alongside historical V1 records. Add only the minimum state and persistence needed for Intake.
Deliver the first MDS through the real CLI: Request → Intake → Feature Contract validation → READY or NEEDS_CLARIFICATION.
Add structured Plan and Task Contracts. Include dependencies, complexity, risk, and verification commands; expose the single Plan approval gate.
Add minimal centralized budgets and execution-profile recording before autonomous agent execution.
Deliver one approved-task slice: Implement → orchestrator-run Verify, stopping with structured evidence.
Add independent Review: Implement → Verify → Review → task accepted.
Add bounded Fix → Verify → Review, model escalation, and automatic sequential progression across all dependency-ready tasks.
Complete accounting/status/log projections and reliability hardening: atomic artifacts, checkout fingerprints, cross-process writer ownership, and recovery tests.
Run a small real feature through the complete CLI workflow, then retire or quarantine superseded V1 canonical and bootstrap paths.

This order preserves the existing store, adapter, task evidence, reviewer independence, and CLI foundation while producing observable V2 behavior early.