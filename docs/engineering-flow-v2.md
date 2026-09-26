# Engineering Flow V2

## Architecture & Migration Strategy

**Status:** Proposed\
**Version:** 2.0\
**Purpose:** Define the target architecture, engineering principles,
workflow, execution policies, and migration strategy for Engineering
Flow.

------------------------------------------------------------------------

# 1. Overview

Engineering Flow is an AI-assisted software engineering orchestration
system designed to automate software development workflows while
maintaining predictable quality, controlled AI usage, traceability, and
human oversight.

The first version explored a relatively detailed pipeline involving
specialized stages such as requirements, PRD generation, technical
specification, task decomposition, workspace preparation, context
preparation, implementation, review, and fixing.

Experience with this approach exposed several problems:

-   excessive context growth;
-   high token consumption;
-   duplicated reasoning between stages;
-   complex prompts and skills;
-   difficult accounting of AI usage;
-   potentially uncontrolled implementation/review/fix loops;
-   increasing orchestration complexity without proportional quality
    improvements.

Engineering Flow V2 simplifies this architecture.

The central principle is:

> Use AI where reasoning is valuable, deterministic tools where
> correctness can be mechanically verified, and persistent artifacts
> instead of conversation history as system memory.

The target workflow is intentionally small:

``` text
REQUEST
   ↓
INTAKE
   ↓
FEATURE CONTRACT
   ↓
PLAN
   ↓
HUMAN APPROVAL
   ↓
IMPLEMENT
   ↓
VERIFY
   ↓
REVIEW
   ↓
FIX
   └────────→ VERIFY
                  ↓
                DONE
```

After plan approval, the normal workflow should be capable of running
autonomously until completion, a configured execution limit is reached,
or human intervention becomes necessary.

------------------------------------------------------------------------

# 2. Core Principles

Engineering Flow V2 follows the principles below.

## 2.1 Minimal orchestration

More agents, skills, prompts, and stages do not automatically produce
better software.

Complexity must be introduced only when it produces measurable
improvements.

Prefer:

``` text
Intake
Plan
Implement
Verify
Review
Fix
```

over deeply nested agent pipelines.

## 2.2 State lives outside the conversation

Conversation context must not be treated as the authoritative state of
the workflow.

Persistent state should live in structured artifacts such as:

``` text
.ai/
    feature.json
    plan.json
    state.json
    review.json
```

and in the repository itself through Git.

The system must be able to resume execution without requiring the entire
previous conversation.

## 2.3 Deterministic validation before AI reasoning

Anything that can be reliably validated by deterministic tooling should
not depend on an LLM.

Examples:

``` text
Formatting     → formatter
Linting        → Ruff / ESLint / equivalent
Typing         → Pyright / mypy / equivalent
Tests          → pytest / dotnet test / equivalent
Build          → compiler/build tooling
Security       → static/security scanners where applicable
```

AI should interpret failures and determine how to correct them.

It should not replace tools capable of proving the same condition
deterministically.

## 2.4 Complexity on demand

Simple features should remain simple.

Engineering Flow should not automatically generate:

``` text
PRD
Technical Specification
Architecture Document
Detailed Design
Task Breakdown
Implementation Plan
```

for every change.

The system should create additional artifacts only when the problem
requires them.

## 2.5 Strong planning, efficient execution

A capable planner should transform ambiguous engineering work into
precise, low-entropy tasks.

This enables less expensive models to execute many implementation tasks
reliably.

Intelligence should be concentrated where uncertainty is high rather
than where work volume is high.

## 2.6 Human control at meaningful boundaries

Human approval should focus on decisions with significant product or
architectural impact.

The primary MVP approval gate is:

``` text
PLAN
 ↓
HUMAN APPROVAL
 ↓
AUTONOMOUS EXECUTION
```

After approval, implementation, verification, review, and fixing should
normally proceed automatically.

Human intervention becomes necessary when:

-   requirements remain ambiguous;
-   an important product decision is missing;
-   an architectural decision exceeds the permitted scope;
-   execution budgets are exhausted;
-   repeated failures occur;
-   the system cannot safely determine how to continue.

------------------------------------------------------------------------

# 3. Target Workflow

## 3.1 Request

The workflow starts with a user request, issue, ticket, prompt, or
feature description.

The request is not assumed to be implementation-ready.

Example:

``` text
Allow users to cancel an order before it has been shipped.
```

------------------------------------------------------------------------

# 4. Intake

The Intake phase determines whether the request contains enough
information to proceed safely.

It does not produce a large PRD.

Its purpose is to convert an informal request into a minimal structured
**Feature Contract**.

Conceptually:

``` text
RAW REQUEST
     ↓
   INTAKE
     ↓
Feature Contract
```

The Intake must distinguish missing information into three categories.

### Resolvable from repository

Information that can be discovered from the existing codebase.

Example:

``` text
Which validation framework does the project use?
```

The agent should inspect the repository instead of asking the user.

### Safe engineering decision

Implementation details that can reasonably be decided by the engineering
agent.

Example:

``` text
Should this helper be private or extracted into another internal function?
```

The agent may decide and record the assumption when relevant.

### Product or business decision

Information that materially changes expected behavior.

Example:

``` text
Can an order be cancelled after payment but before shipment?
```

The system must not invent this behavior.

Execution should transition to:

``` text
NEEDS_CLARIFICATION
```

and wait for human input.

------------------------------------------------------------------------

# 5. Feature Contract

The Feature Contract is the authoritative description of **what must be
built**.

A minimal conceptual schema is:

``` yaml
feature:
  id:
  goal:
  requirements:
  acceptance_criteria:
  constraints:
  out_of_scope:
  assumptions:
  open_questions:
```

Example:

``` yaml
feature:
  id: ORDER-182

  goal:
    Allow users to cancel orders before shipment.

  requirements:
    - Provide an order cancellation operation.
    - Persist the cancelled status.
    - Prevent cancellation after shipment.

  acceptance_criteria:
    - A pending order can be cancelled.
    - A shipped order cannot be cancelled.
    - Cancellation is persisted.

  constraints:
    - Follow the existing project architecture.

  out_of_scope: []

  assumptions: []

  open_questions: []
```

Possible Intake outcomes:

``` text
READY
NEEDS_CLARIFICATION
REJECTED
```

The Feature Contract replaces the requirement for a full PRD for normal
development work.

------------------------------------------------------------------------

# 6. Planning

The Planner answers:

> Given what must be built and how this repository works, how should the
> change be implemented?

Inputs include:

``` text
Feature Contract
Repository
Project instructions
Architecture information
Relevant skills
External context when necessary
```

The Planner explores the repository before decomposing work.

Its output is a structured execution plan containing tasks.

------------------------------------------------------------------------

# 7. Task Contract

Tasks should be sufficiently precise that a smaller implementation model
can execute them with a high probability of success.

A task should contain information similar to:

``` yaml
task:
  id: T03

  objective:
    Add order cancellation to OrderService.

  context:
    relevant_files:
      - src/orders/service.py
      - src/orders/model.py
      - tests/orders/test_service.py

    existing_patterns:
      - Follow the validation approach used by confirm_order().
      - Domain errors derive from OrderError.

  requirements:
    - Only pending orders can be cancelled.
    - Persist status as CANCELLED.

  acceptance_criteria:
    - Pending orders become CANCELLED.
    - Shipped orders raise InvalidOrderState.
    - Existing behavior remains unchanged.

  verification:
    - pytest tests/orders/test_service.py
    - ruff check src/orders
    - pyright src/orders

  constraints:
    - Do not introduce a new service layer.
    - Do not modify unrelated modules.

  depends_on: []

  complexity: low
  risk: medium
```

The Planner is responsible for producing tasks with enough context and
acceptance criteria to minimize unnecessary implementation/review
cycles.

------------------------------------------------------------------------

# 8. Task Dependencies

Tasks should support dependencies from the beginning.

Example:

``` yaml
tasks:
  - id: T1
    depends_on: []

  - id: T2
    depends_on: [T1]

  - id: T3
    depends_on: [T1]

  - id: T4
    depends_on: [T2, T3]
```

Although the MVP executes tasks sequentially, dependency information
makes the model compatible with future DAG scheduling.

------------------------------------------------------------------------

# 9. Human Plan Approval

The Plan represents the main human approval boundary.

The user should be able to inspect:

-   proposed tasks;
-   scope;
-   assumptions;
-   architectural implications;
-   complexity;
-   risk;
-   verification strategy.

After approval:

``` text
PLAN APPROVED
      ↓
AUTONOMOUS EXECUTION
```

Normal execution should not require human approval between every task.

------------------------------------------------------------------------

# 10. Implementation

Implementation executes one approved task at a time.

The implementation agent receives only the context required for that
task.

Typical inputs:

``` text
Feature Contract
Task Contract
Relevant repository state
Project instructions
Applicable skill
```

The implementation agent should avoid unrelated modifications.

------------------------------------------------------------------------

# 11. Verification

Verification is primarily deterministic.

Example:

``` text
IMPLEMENT
    ↓
FORMAT
    ↓
LINT
    ↓
TYPE CHECK
    ↓
TEST
    ↓
BUILD
```

The exact verification pipeline is project-dependent.

Verification produces structured results that subsequent stages can
consume.

If verification fails, the failure is passed to the Fix stage.

------------------------------------------------------------------------

# 12. Review

Review should be logically independent from implementation.

The reviewer should receive a clean context containing primarily:

``` text
Feature Contract
Task Contract
Git diff
Verification results
Relevant architecture rules
```

It should not require the complete implementation conversation.

This reduces context size and limits confirmation bias.

Review should focus on areas deterministic tooling cannot fully prove,
including:

-   correctness;
-   missing requirements;
-   architectural consistency;
-   edge cases;
-   maintainability;
-   security implications;
-   unnecessary complexity;
-   regression risks.

------------------------------------------------------------------------

# 13. Fix Loop

Review or verification failures trigger the Fix phase.

``` text
IMPLEMENT
    ↓
 VERIFY
    ↓
 REVIEW
    │
    ├── PASS ─────────→ DONE
    │
    └── ISSUES
           ↓
          FIX
           ↓
        VERIFY
           ↓
        REVIEW
```

This loop must never be unbounded.

------------------------------------------------------------------------

# 14. Execution Budgets and Circuit Breakers

Budget control is a core orchestration responsibility.

The Orchestrator, not individual agents, owns execution limits.

Initial configuration may resemble:

``` yaml
execution:
  max_agent_calls: 10
  max_fix_cycles: 3
  max_elapsed_minutes: 45

verification:
  max_fix_attempts: 2

review:
  max_review_cycles: 3
```

All AI calls must pass through centralized accounting.

The system must count calls across all execution paths.

Example:

``` text
IMPLEMENT
VERIFY
REVIEW
FIX
VERIFY
REVIEW
FIX
VERIFY
REVIEW
```

If the configured limit is reached:

``` text
STOPPED_REQUIRES_HUMAN
```

The system must not silently continue generating calls.

------------------------------------------------------------------------

# 15. Token and Resource Accounting

Where reliable usage information is available, the system should record
token consumption.

However, token reporting must not be assumed to exist or be accurate for
every provider or harness.

Therefore budget protection must also work using:

-   agent call count;
-   fix cycle count;
-   review cycle count;
-   execution time;
-   task attempts.

Token budget is an additional control when reliable telemetry exists.

The system must never report estimated token usage as exact measured
usage.

------------------------------------------------------------------------

# 16. Observability

Every execution should produce structured telemetry.

Example:

``` text
Run: EF-104

Plan             1 call
Implement        3 calls
Verify           5 executions
Review           3 calls
Fix              1 call

Agent calls      8 / 10
Fix cycles       1 / 3
Elapsed          21m / 45m

Status           DONE
```

Relevant fields include:

``` text
run_id
feature_id
task_id
phase
attempt
model
reasoning_level
requested_profile
actual_profile
duration
result
token_usage
cumulative_usage
```

Observability must make it possible to answer:

> Which model was called?

> Why was it called?

> How many attempts occurred?

> How much time was consumed?

> How many review/fix cycles occurred?

> Was model escalation required?

------------------------------------------------------------------------

# 17. Model Routing

Engineering Flow should not require the same model for every activity.

Model selection is a policy owned by the Orchestrator.

The guiding principle is:

> Spend intelligence where uncertainty is high.

A strong model can be used to produce high-quality plans and reviews
while smaller models perform well-defined implementation tasks.

An initial policy can resemble:

``` text
Intake
    → efficient model / low reasoning

Plan
    → strong model / medium reasoning

Implementation - low complexity
    → efficient model / low reasoning

Implementation - medium complexity
    → balanced model / medium reasoning

Implementation - high complexity
    → strong model / medium reasoning

Verification
    → deterministic tools

Review
    → strong model / medium reasoning

Fix
    → based on failure complexity
```

For the initial OpenAI-oriented configuration, candidate profiles may
include Luna, Terra, and Sol according to availability in the execution
environment.

Exact model identifiers must remain configuration rather than domain
logic.

------------------------------------------------------------------------

# 18. Complexity and Risk

Task complexity and task risk are separate concepts.

Example:

``` text
Add simple DTO
complexity: low
risk: low
```

``` text
Modify concurrency algorithm
complexity: high
risk: high
```

``` text
Database migration
complexity: medium
risk: high
```

The Planner assigns these properties.

The Model Router may use them when selecting an execution profile.

------------------------------------------------------------------------

# 19. Model Escalation

Model routing should support escalation.

Example:

``` text
LOW complexity task
        ↓
efficient model
        ↓
VERIFY
   ┌────┴────┐
 PASS       FAIL
  ↓           ↓
REVIEW    stronger model
              ↓
             FIX
              ↓
           VERIFY
```

Repeated failures may escalate further.

Conceptually:

``` text
Attempt 1
efficient model

Attempt 2
balanced model

Repeated failure
strong model
```

Escalation remains constrained by the global execution budget.

A stronger model must not bypass circuit breakers.

------------------------------------------------------------------------

# 20. Quality Metrics

The goal is not simply for the Reviewer to report zero findings.

Engineering Flow should measure end-to-end quality and efficiency.

Relevant metrics include:

``` text
First Pass Acceptance Rate
Verification Pass Rate
Review Findings
Fix Cycles
Agent Calls
Token Usage
Elapsed Time
Escalation Rate
Human Intervention Rate
```

These measurements should eventually allow empirical comparisons such
as:

``` text
Model/Profile A
vs
Model/Profile B
```

rather than choosing models solely by intuition.

------------------------------------------------------------------------

# 21. Evaluation Strategy

A future evaluation suite should contain representative engineering
tasks such as:

``` text
simple bug
CRUD feature
refactoring
API change
database migration
concurrency bug
security issue
multi-file feature
legacy code modification
architecture-sensitive change
```

The same tasks can be executed using different model policies.

Results can then guide routing decisions.

The objective is to find the lowest-cost execution profile that reliably
maintains the required quality.

------------------------------------------------------------------------

# 22. Project Knowledge Boundaries

Engineering Flow explicitly separates different kinds of knowledge.

## AGENTS.md

Contains minimal persistent instructions specific to the repository.

Examples:

-   important project commands;
-   invariant development rules;
-   verification commands;
-   locations of important documentation;
-   critical restrictions.

It should remain small.

It should not become a complete architecture manual.

## Architecture documentation

`docs/architecture.md` describes the current architecture.

It may contain:

-   major components;
-   module boundaries;
-   dependency direction;
-   important structural principles;
-   runtime topology.

It describes **how the system is organized**.

## Architecture Decision Records

ADRs record significant architectural decisions and their rationale.

Example:

``` text
docs/adr/
    001-modular-monolith.md
    002-postgresql.md
```

ADRs answer:

> Why was this important architectural decision made?

Trivial implementation decisions should not generate ADRs.

## Skills

Skills represent reusable procedures.

Examples:

``` text
plan
database-migration
security-review
project-bootstrap
```

A skill answers:

> How should this type of work be performed?

Skills should be loaded only when relevant.

They should not contain mutable project state.

## MCP

MCP provides access to external information or tools.

Examples may include:

``` text
GitHub
Jira
documentation
databases
observability platforms
external knowledge systems
```

MCP should not be the authoritative source for basic project
architecture or coding conventions.

External tools should be introduced only when they provide clear value
because unnecessary tools also increase context and operational
complexity.

## Executable configuration

Mechanically enforceable conventions belong in executable configuration.

Examples:

``` text
pyproject.toml
Ruff
Pyright
pytest
CI configuration
```

Examples of rules that should normally be enforced by tools rather than
prompts:

``` text
formatting
import ordering
unused imports
typing
test execution
build correctness
```

## Feature Contract

Contains requirements specific to the current feature.

It defines **what must be built**.

It should not duplicate general project architecture.

## Plan and Tasks

Contain execution-specific decisions.

They define **how the current feature will be implemented**.

They are workflow state rather than permanent architecture
documentation.

------------------------------------------------------------------------

# 23. Brownfield Strategy

For an existing repository, the repository itself is the primary source
of implementation patterns.

The agent should inspect:

``` text
existing modules
existing tests
project configuration
similar implementations
architecture documentation
Git history when relevant
```

before introducing new patterns.

The default behavior is:

> Preserve the architecture and conventions already established by the
> repository unless the feature explicitly requires a change.

Brownfield support is part of the natural behavior of the workflow and
does not require a dedicated MVP subsystem.

------------------------------------------------------------------------

# 24. Greenfield Strategy

Greenfield projects require an architectural baseline because no
existing repository conventions exist.

A future `project-bootstrap` capability may establish:

``` text
runtime
framework
project structure
architecture baseline
testing strategy
linting
typing
CI
initial AGENTS.md
architecture documentation
critical ADRs
```

The architecture proposal should receive human approval before
significant implementation begins.

This capability is intentionally deferred until after the core
Engineering Flow is stable.

------------------------------------------------------------------------

# 25. Sequential Execution in the MVP

The initial version executes tasks sequentially.

Example:

``` text
T1
 ↓
Implement
Verify
Review
 ↓
T2
 ↓
Implement
Verify
Review
 ↓
T3
```

Parallel execution is deliberately excluded from the MVP.

Reasons include:

-   simpler state management;
-   easier debugging;
-   reliable resource accounting;
-   easier token accounting;
-   simpler recovery;
-   easier verification of model routing;
-   avoidance of concurrent repository modifications.

The objective is first to make the sequential workflow predictable and
measurable.

------------------------------------------------------------------------

# 26. Parallelism Readiness

Although execution is sequential, tasks should support dependency
information from the beginning.

The Planner may generate a DAG such as:

``` text
       T1
        │
   ┌────┴────┐
   ▼         ▼
  T2        T3
   │         │
   └────┬────┘
        ▼
       T4
```

The MVP scheduler simply chooses one ready task at a time.

Conceptually:

``` python
ready_tasks = graph.get_ready_tasks()
task = ready_tasks[0]
execute(task)
```

This preserves compatibility with future parallel execution without
introducing concurrency today.

------------------------------------------------------------------------

# 27. Future Parallel Execution

Future versions may execute independent tasks concurrently.

Example:

``` text
              BASE COMMIT
                   │
          ┌────────┴────────┐
          ▼                 ▼
      Worktree T2       Worktree T3
          │                 │
       Agent A           Agent B
          │                 │
       Verify            Verify
       Review            Review
          │                 │
          └────────┬────────┘
                   ▼
               Integration
                   ↓
             Integration tests
```

Parallel writers should use isolated Git worktrees or equivalent
workspace isolation.

Future parallel execution should include:

``` text
DAG scheduler
isolated worktrees
max concurrency
global execution budget
conflict detection
integration strategy
integration verification
reconciliation
```

Initial concurrency should remain conservative.

Parallel execution must never bypass the global resource budget.

------------------------------------------------------------------------

# 28. Provider Independence

Engineering Flow should separate workflow orchestration from AI provider
implementation.

Conceptually:

``` text
Orchestrator
     │
 Agent Adapter
     │
 ┌───┼────────────┐
 ▼   ▼            ▼
Codex Claude     Other
```

The domain should reason about execution profiles rather than hard-coded
provider-specific model names.

Example:

``` text
efficient
balanced
strong
```

Provider configuration maps these profiles to actual models.

This preserves the ability to support Codex, Claude, Devin, or future
coding agents without rewriting the workflow engine.

The initial implementation may prioritize Codex.

------------------------------------------------------------------------

# 29. State Machine

The target state machine is conceptually:

``` text
INTAKE
   │
   ├── NEEDS_CLARIFICATION
   │          │
   │        HUMAN
   │          │
   └──────────┘
   │
   ▼
PLAN
   │
   ▼
WAITING_PLAN_APPROVAL
   │
   ▼
IMPLEMENT
   │
   ▼
VERIFY
   │
   ├── FAIL ─────→ FIX
   │                │
   │                └────→ VERIFY
   │
   ▼
REVIEW
   │
   ├── ISSUES ───→ FIX
   │                │
   │                └────→ VERIFY
   │
   ▼
DONE
```

Additional terminal/interruption states may include:

``` text
FAILED
CANCELLED
STOPPED_REQUIRES_HUMAN
```

------------------------------------------------------------------------

# 30. Responsibility Boundaries

## Python Orchestrator

Responsible for:

``` text
state
state transitions
contracts
schema validation
execution policy
model routing
budgets
retries
circuit breakers
persistence
telemetry
recovery
```

It should not attempt to reproduce LLM reasoning.

## AI Agent

Responsible for:

``` text
understanding requirements
repository exploration
planning
implementation
semantic review
failure interpretation
fix generation
```

## Deterministic Tools

Responsible for:

``` text
build
tests
lint
format
typing
static checks
```

This separation is a fundamental architectural principle.

------------------------------------------------------------------------

# 31. Safety and Reliability Requirements

The workflow should eventually guarantee several execution properties.

### Atomic state persistence

State changes must survive process interruption without leaving
corrupted workflow state.

### Reviewer write restraint

Review should not silently mutate implementation while supposedly
evaluating it.

Review and modification are separate responsibilities.

### Checkout fingerprinting

Reviews and execution results should correspond to the repository state
they claim to evaluate.

Stale reviews must be detectable.

### Single writer behavior

The MVP assumes one active writer.

Future concurrency requires explicit workspace isolation and writer
ownership.

### Recoverability

Interrupted execution should be resumable from persisted state whenever
safe.

These properties should be implemented incrementally as part of
hardening.

------------------------------------------------------------------------

# 32. MVP Scope

The first usable Engineering Flow V2 should include:

``` text
1. Simplified workflow/state machine

2. Intake + Feature Contract

3. Planner + structured Task Contract

4. Human plan approval

5. Model Router

6. Sequential task implementation

7. Deterministic verification

8. Independent review

9. Fix loop

10. Model escalation

11. Global budgets and circuit breakers

12. Persistent state

13. Execution telemetry/accounting
```

The MVP intentionally excludes:

``` text
parallel task execution
complex multi-agent topology
automatic greenfield architecture generation
large MCP ecosystem
automatic PR lifecycle
advanced evaluation infrastructure
multiple provider optimization
```

These remain compatible future extensions.

------------------------------------------------------------------------

# 33. Migration Strategy

Migration should be incremental.

Each stage should be implemented, tested, and validated before
advancing.

## Stage 1 --- Baseline and Domain Simplification

Inspect the current Engineering Flow implementation.

Map existing components to the new workflow.

Simplify the state machine toward:

``` text
INTAKE
PLAN
APPROVAL
IMPLEMENT
VERIFY
REVIEW
FIX
DONE
```

Remove or deprecate abstractions that no longer provide value.

## Stage 2 --- Intake and Feature Contract

Implement the structured Feature Contract.

Support:

``` text
READY
NEEDS_CLARIFICATION
REJECTED
```

Ensure business ambiguity is escalated rather than invented.

## Stage 3 --- Planner and Task Contract

Implement structured planning.

Tasks should contain:

``` text
objective
context
requirements
acceptance criteria
verification
constraints
dependencies
complexity
risk
```

Introduce the human plan approval gate.

## Stage 4 --- Model Routing

Introduce execution profiles and provider mapping.

Support routing based on:

``` text
phase
complexity
risk
attempt
```

Keep exact model names configurable.

## Stage 5 --- Execution Loop

Implement:

``` text
IMPLEMENT
VERIFY
REVIEW
FIX
```

with sequential task execution.

After plan approval, execution should normally continue autonomously.

## Stage 6 --- Budgets and Circuit Breakers

Centralize accounting.

Introduce limits for:

``` text
agent calls
fix cycles
review cycles
execution time
task attempts
tokens when reliably available
```

No AI execution path may bypass these controls.

## Stage 7 --- Observability

Persist execution telemetry.

Make it possible to reconstruct exactly what occurred during a run.

Track model routing, attempts, failures, escalation, and cumulative
resource usage.

## Stage 8 --- Reliability Hardening

Implement and validate:

``` text
atomic state writes
recovery
checkout fingerprinting
reviewer write restraint
single-writer guarantees
failure handling
```

## Stage 9 --- Real Feature Validation

Execute the complete workflow against a small real feature.

Expected flow:

``` text
Request
   ↓
Intake
   ↓
Plan
   ↓
Human Approval
   ↓
──────── AUTOMATIC ────────
   ↓
Implement
   ↓
Verify
   ↓
Review
   ↓
Fix if necessary
   ↓
Verify
   ↓
Review
   ↓
Done
```

Measure:

``` text
quality
first-pass acceptance
agent calls
fix cycles
review findings
elapsed time
token usage when available
human intervention
```

Only after this workflow proves stable should significant additional
automation be introduced.

------------------------------------------------------------------------

# 34. Post-MVP Roadmap

Potential future capabilities include:

## Parallel execution

``` text
DAG scheduling
Git worktrees
concurrency limits
integration/reconciliation
```

## Greenfield bootstrap

``` text
architecture baseline
project tooling
initial project structure
architecture approval
```

## MCP integrations

Potential integrations may include:

``` text
GitHub
Jira
documentation providers
databases
observability systems
```

Only integrations with measurable development value should be added.

## Automated PR lifecycle

Potential flow:

``` text
Feature
→ Plan
→ Implement
→ Verify
→ Review
→ Fix
→ Final Review
→ Commit
→ Push
→ Open PR
```

## Provider expansion

Support additional coding agents through adapters and execution
profiles.

## Evals

Build a repeatable benchmark suite for evaluating:

``` text
models
reasoning levels
task quality
routing strategies
cost
quality
latency
```

------------------------------------------------------------------------

# 35. Architectural Direction

Engineering Flow V2 should remain a **small orchestration engine around
capable coding agents**, rather than attempting to reproduce the
intelligence of those agents in Python.

The desired architecture is:

``` text
                   HUMAN
                     │
                  REQUEST
                     │
                     ▼
                  INTAKE
                     │
                     ▼
             FEATURE CONTRACT
                     │
                     ▼
                   PLAN
                     │
               human approval
                     │
                     ▼
              TASK CONTRACTS
                     │
                     ▼
               MODEL ROUTER
                     │
                     ▼
                IMPLEMENT
                     │
                     ▼
            DETERMINISTIC VERIFY
                     │
                     ▼
                  REVIEW
                     │
              ┌──────┴──────┐
              │             │
            ISSUES          PASS
              │             │
              ▼             ▼
             FIX           DONE
              │
              └────────→ VERIFY
```

Supported by four distinct layers:

``` text
PROJECT KNOWLEDGE
AGENTS.md + repository + architecture + ADRs

PROCEDURES
Skills loaded when relevant

EXTERNAL CONTEXT
MCP tools when necessary

ENFORCEMENT
Tests + lint + typing + build + CI
```

The system should optimize for:

> **high-quality plans, precise tasks, efficient implementation,
> deterministic verification, strong independent review, bounded
> autonomous execution, and measurable results.**

The architecture should remain simple until empirical evidence
demonstrates that additional complexity improves those outcomes.

------------------------------------------------------------------------

# 36. Incremental Delivery and Early Validation

Engineering Flow itself must be developed using small, executable
vertical slices.

The objective is to avoid implementing large amounts of orchestration
code before validating that the workflow actually works end-to-end.

Each migration stage should produce the **smallest observable behavior**
that proves the new capability works before additional abstractions or
features are added.

For example, when introducing the Feature Contract, the first milestone
should not implement the complete Intake/Plan architecture.

It should first demonstrate:

``` text
User Request
     ↓
Feature Contract validation
     │
     ├── valid ─────→ READY
     │
     └── incomplete → NEEDS_CLARIFICATION
                          ↓
                     show questions
```

This behavior should be executable from the CLI so that the developer
can immediately observe and validate the interaction.

Only after this works should the next capability be added:

``` text
Valid Feature Contract
        ↓
       PLAN
        ↓
Structured Tasks
```

Then:

``` text
Plan
 ↓
Human Approval
 ↓
Execute ONE Task
 ↓
Verify
```

Then:

``` text
Implement
 ↓
Verify
 ↓
Review
```

And finally:

``` text
Implement
 ↓
Verify
 ↓
Review
 ↓
Fix
 ↓
Verify
```

## Development Rule

Prefer:

> implement → run → observe → validate → commit → extend

over:

> design many components → implement many tasks → integrate everything →
> test the complete system.

Every migration stage should therefore define a **Minimum Demonstrable
Slice (MDS)**.

A stage is not considered complete merely because its classes, schemas,
adapters, or tests exist.

It must expose observable behavior demonstrating that the capability
works through the real Engineering Flow entry point whenever practical.

This principle should also influence task decomposition: prefer a small
number of end-to-end tasks that progressively produce working behavior
instead of many component-oriented tasks that only become executable
after a large integration phase.
