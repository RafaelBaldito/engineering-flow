# Engineering Flow
## Product Vision & Technical Foundation

**Status:** Concept / Pre-PRD
**Purpose:** Source document for formal PRD generation.

**Lifecycle governance:** This pre-PRD vision preserves early conceptual
workflow material. The approved `docs/product/prd.md`,
`docs/DELIVERY-PLAN.md`, and required architecture overview govern the canonical
planning order, acceptance hierarchy, authorization gates, and Git/PR delivery
responsibilities. Where an early diagram here differs, the approved artifacts
control.

---

# 1. Product Overview

Engineering Flow is an **agent-agnostic software engineering workflow orchestration engine** designed to automate the software development lifecycle from an initial requirement to a review-ready Pull Request.

The system coordinates specialized AI coding agents through a deterministic and observable workflow while keeping humans involved only at configurable decision points.

The primary goal is to remove the developer from the repetitive operational orchestration currently required when working with AI coding agents.

Instead of manually invoking skills, transferring context, requesting reviews, sending findings back for correction, repeating review/fix cycles, committing changes, pushing branches, and creating Pull Requests, the developer should be able to initiate a workflow and allow Engineering Flow to coordinate these activities automatically.

The long-term product vision is:

> **Describe the feature. Review the Pull Request.**

---

# 2. Problem

Modern coding agents such as Codex, Claude-based coding agents, and Devin are capable of performing increasingly sophisticated software engineering tasks.

However, using these agents effectively still requires significant manual orchestration.

A typical AI-assisted development workflow currently looks like:

```text
Developer
    ↓
Generate PRD
    ↓
Review PRD
    ↓
Generate TECHSPEC
    ↓
Review TECHSPEC
    ↓
Decompose tasks
    ↓
Execute task
    ↓
Review implementation
    ↓
Review finds problems
    ↓
Send findings to developer agent
    ↓
Fix
    ↓
Review again
    ↓
Repeat
    ↓
Commit
    ↓
Push
    ↓
Create Pull Request
```

The coding agent is capable of doing the engineering work, but the human developer is still acting as the **workflow engine**.

The developer must repeatedly:

- determine the next step;
- invoke the appropriate skill or agent;
- provide the correct context;
- wait for execution;
- interpret results;
- transfer review findings;
- request fixes;
- restart reviews;
- control retries;
- execute Git operations;
- track workflow state.

Engineering Flow exists to automate this orchestration.

---

# 3. Product Hypothesis

If the software development process can be represented as a controlled workflow, most operational interactions between the developer and coding agents can be automated.

The developer defines:

```text
WHAT needs to be built
```

Engineering Flow determines:

```text
WHAT should happen next
```

The selected AI engineering agent determines:

```text
HOW the engineering work should be performed
```

This establishes a fundamental architectural separation:

```text
Engineering Flow
      =
CONTROL PLANE

Agent Runtime
      =
EXECUTION PLANE
```

---

# 4. Core Architectural Principle

Engineering Flow is **not a coding agent**.

Engineering Flow is an **orchestration layer for coding agents**.

The project should not initially attempt to recreate capabilities already provided by mature engineering-agent harnesses.

Engineering Flow responsibilities include:

- workflow orchestration;
- state management;
- state transitions;
- agent selection;
- execution policies;
- approval gates;
- retries;
- failure handling;
- review/fix loops;
- workflow persistence;
- resume/recovery;
- Git lifecycle;
- Pull Request lifecycle;
- observability;
- auditability.

Agent runtime responsibilities may include:

- software engineering reasoning;
- repository exploration;
- filesystem access;
- code modification;
- shell execution;
- test execution;
- debugging;
- code review;
- implementation fixes;
- Skills;
- MCP integrations;
- context management internal to the agent;
- other provider-specific capabilities.

Core principle:

> **Engineering Flow decides what must happen. The selected agent decides how to perform the engineering work.**

---

# 5. Agent-Agnostic Architecture

Engineering Flow must not be architecturally coupled to a single AI coding agent.

The initial implementation will support Codex, but Codex should be treated as the **first Agent Provider**, not as part of the core domain.

Conceptually:

```text
                 Engineering Flow

                        │
                        ▼

                  Agent Runtime

                        │

          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼

        Codex          Claude        Devin
       Provider        Provider      Provider
```

Future providers should be able to integrate without requiring changes to the core workflow engine.

---

# 6. Initial Provider Strategy

## V1

The first supported provider will be:

```text
Codex
```

Reasons:

- strong software engineering harness;
- repository awareness;
- filesystem capabilities;
- shell execution;
- test execution;
- Skills;
- MCP support;
- sandbox capabilities;
- structured integration possibilities;
- suitable for autonomous software engineering workflows.

The initial implementation should therefore optimize for a high-quality Codex integration while maintaining provider-neutral boundaries inside the core.

---

# 7. Future Providers

Future versions may support additional engineering agents such as:

```text
Claude-based coding runtimes
Devin
Other autonomous coding agents
Future agent harnesses
```

These providers may expose different:

- execution models;
- authentication mechanisms;
- session models;
- tool capabilities;
- sandbox models;
- event systems;
- context models;
- permission systems;
- APIs.

Engineering Flow should not assume that every provider behaves exactly like Codex.

---

# 8. Agent Runtime Abstraction

The core system should interact with an abstract runtime contract.

Conceptually:

```python
class AgentRuntime:

    def start_session(...):
        ...

    def execute(...):
        ...

    def cancel(...):
        ...

    def resume(...):
        ...

    def get_status(...):
        ...
```

Potential implementations:

```text
AgentRuntime

├── CodexRuntime
├── ClaudeRuntime
├── DevinRuntime
└── FutureRuntime
```

The exact interface must be defined during the TECHSPEC.

The important architectural rule is:

> Provider-specific SDKs and protocols must not leak unnecessarily into the Workflow Engine.

---

# 9. Provider Adapter Layer

Each provider should be implemented through an adapter.

Possible structure:

```text
providers/

├── base/
│   ├── runtime.py
│   ├── session.py
│   ├── events.py
│   └── capabilities.py
│
├── codex/
│   ├── runtime.py
│   ├── session.py
│   ├── events.py
│   └── mapper.py
│
├── claude/
│   └── ...
│
└── devin/
    └── ...
```

The Workflow Engine communicates only with the provider abstraction.

For example:

```text
Workflow Engine
      ↓
AgentRuntime
      ↓
CodexRuntime
      ↓
Codex SDK / App Server
      ↓
Codex Harness
```

A future provider could use a completely different integration:

```text
Workflow Engine
      ↓
AgentRuntime
      ↓
DevinRuntime
      ↓
Devin integration
```

without modifying the workflow itself.

---

# 10. Capability Model

Not every provider will support the same functionality.

Therefore, Engineering Flow should eventually expose provider capabilities.

Conceptually:

```python
class AgentCapabilities:

    supports_shell: bool

    supports_file_read: bool

    supports_file_write: bool

    supports_session_resume: bool

    supports_streaming: bool

    supports_structured_output: bool

    supports_mcp: bool

    supports_skills: bool

    supports_sandbox: bool
```

This allows the Workflow Engine to validate whether a provider is capable of executing a particular stage.

Example:

```text
Task requires:

filesystem write
shell
tests
session resume

        ↓

Provider capability validation

        ↓

compatible → execute

incompatible → reject / select another provider
```

The full capability-routing system does not need to be implemented in V1, but the architecture should allow it.

---

# 11. Provider Selection

Initially, the project may use one global provider:

```yaml
agent:
  provider: codex
```

Later, providers may be selected per role:

```yaml
agents:

  prd:
    provider: claude

  architect:
    provider: claude

  planner:
    provider: codex

  developer:
    provider: codex

  reviewer:
    provider: claude
```

This would enable heterogeneous engineering workflows.

For example:

```text
Requirement
    ↓
Claude
PRD
    ↓
Claude
Architecture
    ↓
Codex
Implementation
    ↓
Claude
Review
    ↓
Codex
Fix
```

This is a future capability and should not increase the scope of V1.

---

# 12. Provider Fallback

Future versions may support fallback policies.

Example:

```yaml
developer:

  primary:
    provider: codex

  fallback:
    provider: devin
```

Potential reasons for fallback:

- provider unavailable;
- rate limit;
- execution failure;
- unsupported capability;
- repeated failure;
- user-defined policy.

Fallback is explicitly outside the initial MVP.

---

# 13. Agent Roles

Engineering Flow should distinguish between:

```text
Provider
Agent Role
Skill
Session
Execution
```

These concepts are different.

## Provider

Technology executing the AI workload.

Examples:

```text
Codex
Claude
Devin
```

## Agent Role

Responsibility inside the engineering workflow.

Examples:

```text
PRD Agent
Architect
Planner
Developer
Reviewer
```

## Skill

Reusable instructions or domain knowledge.

Examples:

```text
create-prd
create-techspec
decompose-tasks
execute-task
review-task
```

## Session

Persistent interaction context maintained with a provider.

## Execution

A specific unit of work performed inside a session.

This separation should remain explicit throughout the architecture.

---

# 14. Skill Is Not Agent

A Skill should not automatically become an independent agent.

A Skill represents:

```text
capability
+
instructions
+
process knowledge
```

An Agent represents:

```text
role
+
runtime
+
context
+
capabilities
+
execution
```

Therefore:

```text
create-prd
create-techspec
decompose-tasks
execute-task
review-task
```

may remain Skills used by specialized agent roles.

---

# 15. Initial Agent Roles

The initial workflow should contain approximately the following roles.

## PRD Agent

Responsible for transforming the initial feature description into product requirements.

## Architect

Responsible for architecture and TECHSPEC generation.

## Planner

Responsible for decomposing the approved specification into executable tasks.

## Developer

Responsible for implementing tasks and fixing review findings.

## Reviewer

Responsible for independently validating implementation against:

- task requirements;
- acceptance criteria;
- TECHSPEC;
- code quality;
- tests;
- repository conventions.

---

# 16. Sessions and Context Isolation

Each role should receive appropriate execution context.

Example using the initial Codex provider:

```text
Codex Runtime

├── PRD Session
├── Architect Session
├── Planner Session
│
├── Developer TASK-001 Session
├── Reviewer TASK-001 Session
│
├── Developer TASK-002 Session
└── Reviewer TASK-002 Session
```

Provider-neutral domain terminology should preferably use:

```text
AgentSession
AgentExecution
AgentEvent
```

rather than embedding provider terminology such as:

```text
CodexThread
CodexTurn
```

inside the core.

The Codex adapter may internally map:

```text
AgentSession
      ↓
Codex Thread
```

and:

```text
AgentExecution
      ↓
Codex Turn
```

---

# 17. Developer Context Continuity

The Developer session should preferably survive implementation and subsequent fix cycles.

Example:

```text
Developer Session

Execution 1
Implement TASK-001

      ↓

Review FAIL

      ↓

Execution 2
Fix findings

      ↓

Review FAIL

      ↓

Execution 3
Fix remaining finding
```

This preserves useful implementation context.

---

# 18. Independent Reviewer

The Reviewer should use an independent session whenever practical.

Flow:

```text
Developer Session
      ↓
implementation
      ↓
repository
      ↓
Reviewer Session
      ↓
independent evaluation
```

This helps prevent the implementation agent from simply validating its own reasoning.

---

# 19. Model and Reasoning Configuration

Providers may expose model selection and reasoning configuration differently.

The provider-neutral configuration may represent intent:

```yaml
agents:

  prd:
    provider: codex
    model: configured-model
    reasoning: medium

  architect:
    provider: codex
    model: configured-model
    reasoning: high

  planner:
    provider: codex
    model: configured-model
    reasoning: medium

  developer:
    provider: codex
    model: configured-model
    reasoning: high

  reviewer:
    provider: codex
    model: configured-model
    reasoning: high
```

The provider adapter is responsible for translating this configuration into the provider-specific execution model.

Provider-specific capabilities that cannot be normalized cleanly should remain provider-specific.

Engineering Flow should avoid creating an artificial lowest-common-denominator abstraction.

---

# 20. Workflow

The primary workflow is:

```text
INPUT
  ↓
PRD
  ↓
PRD APPROVAL
  ↓
ARCHITECTURE / TECHSPEC
  ↓
TECHSPEC APPROVAL
  ↓
TASK DECOMPOSITION
  ↓
PLAN APPROVAL
  ↓
TASK EXECUTION
  ↓
TEST
  ↓
REVIEW
  ↓
┌─────────────────────────────┐
│                             │
PASS                         FAIL
│                             │
│                            FIX
│                             │
│                           TEST
│                             │
│                           REVIEW
│                             │
└─────────────────────────────┘
              ↓
          TASK DONE
              ↓
          NEXT TASK
              ↓
       ALL TASKS DONE
              ↓
       FINAL VALIDATION
              ↓
            COMMIT
              ↓
             PUSH
              ↓
        PULL REQUEST
              ↓
         HUMAN REVIEW
```

---

# 21. Approval Gates

Human-in-the-loop is a first-class feature.

Each stage may support policies such as:

```text
REQUIRED
AUTOMATIC
CONDITIONAL
```

Initial example:

```yaml
approval:

  prd: required

  techspec: required

  task_plan: required

  implementation: automatic

  review_fix_loop: automatic

  commit: automatic

  push: automatic

  pull_request: automatic

  merge: required
```

This creates two clear zones:

```text
PRD
 ↓
HUMAN APPROVAL

TECHSPEC
 ↓
HUMAN APPROVAL

TASK PLAN
 ↓
HUMAN APPROVAL


────── AUTONOMOUS ENGINEERING ZONE ──────

IMPLEMENT
 ↓
TEST
 ↓
REVIEW
 ↕
FIX
 ↓
COMMIT
 ↓
PUSH
 ↓
PR


──────────── HUMAN GATE ─────────────────

FINAL PR REVIEW
```

---

# 22. Review/Fix Loop

The autonomous review/fix cycle is one of the central features of Engineering Flow.

Current manual process:

```text
Execute
 ↓
Review
 ↓
Developer reads finding
 ↓
Developer manually sends finding
 ↓
Fix
 ↓
Developer manually requests another review
```

Engineering Flow:

```text
IMPLEMENT
    ↓
REVIEW
    ↓
  FAIL
    ↓
   FIX
    ↓
REVIEW
    ↓
  PASS
```

Pseudo-flow:

```python
implementation = developer.execute(task)

for attempt in range(max_review_cycles):

    review = reviewer.review(task)

    if review.status == "PASS":
        complete_task()
        break

    developer.fix(review)

else:
    require_human_intervention()
```

A maximum number of cycles is mandatory.

Example:

```yaml
review:
  max_cycles: 3
```

When exceeded:

```text
NEEDS_HUMAN_ATTENTION
```

---

# 23. Structured Review Contract

Reviews should produce structured results whenever supported.

Example:

```json
{
  "status": "FAIL",

  "findings": [
    {
      "severity": "HIGH",
      "category": "resource-management",
      "file": "src/example.py",
      "line": 81,
      "description": "Database connection is not closed.",
      "blocking": true
    }
  ]
}
```

The orchestrator should not need to interpret arbitrary prose to determine whether implementation passed.

---

# 24. State Machine

Workflow state must be explicitly represented.

Potential states:

```text
CREATED

PRD_GENERATING
PRD_APPROVAL

TECHSPEC_GENERATING
TECHSPEC_APPROVAL

PLANNING
PLAN_APPROVAL

TASK_PENDING
TASK_IMPLEMENTING
TASK_TESTING
TASK_REVIEWING
TASK_FIXING
TASK_COMPLETED

FINAL_VALIDATION

COMMITTING
PUSHING
CREATING_PR

COMPLETED

NEEDS_HUMAN_ATTENTION
FAILED
CANCELLED
```

State transitions belong to the Workflow Engine.

Agents must not arbitrarily determine workflow transitions.

---

# 25. Workflow Persistence

Workflow state cannot exist only in memory.

Engineering Flow must support:

```text
start
 ↓
execute
 ↓
process interruption
 ↓
restart
 ↓
resume
```

Each workflow receives an identifier:

```text
WF-2026-0001
```

Persisted information may include:

```text
workflow_id
project
repository
branch

current_stage
current_task

approval_status

selected_provider
agent_sessions

review_cycles
retry_count

timestamps
errors

git_state
pull_request
```

SQLite is a strong candidate for V1.

---

# 26. Git Lifecycle

Git lifecycle should belong to Engineering Flow rather than being freely controlled by an AI agent.

Agents perform engineering work.

The orchestrator controls workflow transactions.

Example:

```text
Developer
   ↓
implementation

Reviewer
   ↓
PASS

Tests
   ↓
PASS

Engineering Flow
   ↓
git add
   ↓
git commit
   ↓
git push
```

Agents may generate:

- commit message;
- PR title;
- PR description.

The Workflow Engine executes the actual lifecycle according to configured policies.

---

# 27. Pull Request as Primary Deliverable

The principal output of a successful workflow is:

> **A review-ready Pull Request.**

The generated PR should summarize information such as:

```text
Summary

Requirements

Technical approach

Tasks implemented

Files changed

Tests executed

Review cycles

Review findings resolved

Known limitations

Human review notes
```

The Pull Request becomes the main handoff back to the developer.

---

# 28. Observability

Observability is a core requirement.

Engineering Flow should make it possible to understand what happened during an autonomous workflow.

Example:

```text
WF-001

├── PRD
│   └── PASS
│
├── TECHSPEC
│   └── PASS
│
├── Planning
│   └── 6 tasks
│
├── TASK-001
│   │
│   ├── Developer
│   │   ├── files inspected
│   │   ├── files modified
│   │   ├── commands
│   │   └── tests
│   │
│   └── Reviewer
│       └── PASS
│
└── TASK-002
    │
    ├── Developer
    ├── Reviewer → FAIL
    ├── Fix
    └── Reviewer → PASS
```

---

# 29. Provider-Neutral Event Model

Provider-specific events should be translated where useful into domain events.

Examples:

```text
workflow.started
workflow.completed

stage.started
stage.completed

agent.session.started
agent.execution.started
agent.execution.completed
agent.execution.failed

command.started
command.completed

file.changed

test.started
test.completed

review.started
review.failed
review.passed

fix.started
fix.completed

approval.requested
approval.accepted
approval.rejected

git.commit.created
git.push.completed

pull_request.created

workflow.failed
```

Example event:

```json
{
  "workflow_id": "WF-2026-0001",
  "task_id": "TASK-003",
  "role": "developer",
  "provider": "codex",
  "session_id": "abc123",
  "execution_id": "exec-02",
  "event": "command.completed",
  "timestamp": "...",
  "payload": {
    "command": "pytest",
    "exit_code": 0
  }
}
```

Provider-specific raw events may additionally be preserved for diagnostics.

---

# 30. CLI

V1 should expose a simple CLI rather than requiring a web interface.

Conceptual commands:

```bash
engflow init
```

```bash
engflow run feature.md
```

```bash
engflow status WF-001
```

```bash
engflow resume WF-001
```

```bash
engflow approve WF-001
```

```bash
engflow reject WF-001
```

```bash
engflow logs WF-001
```

Potential future command:

```bash
engflow providers
```

which could display available providers and capabilities.

---

# 31. Project Configuration

A target repository may contain:

```text
.engflow/
    config.yaml
```

Conceptual example:

```yaml
project:
  name: example-api

provider:
  default: codex

workflow:
  max_review_cycles: 3
  max_execution_retries: 2

approval:
  prd: required
  techspec: required
  tasks: required
  commit: automatic
  push: automatic
  pull_request: automatic
  merge: required

agents:

  prd:
    provider: codex
    reasoning: medium

  architect:
    provider: codex
    reasoning: high

  planner:
    provider: codex
    reasoning: medium

  developer:
    provider: codex
    reasoning: high

  reviewer:
    provider: codex
    reasoning: high

git:
  commit_on_task_success: true
  push_on_workflow_success: true
```

V1 may simplify this configuration substantially.

---

# 32. Workflow Artifacts

Important engineering artifacts should be preserved.

Possible structure:

```text
.engflow/

workflows/
└── WF-001/
    │
    ├── input.md
    ├── prd.md
    ├── techspec.md
    │
    ├── tasks/
    │   ├── TASK-001.md
    │   ├── TASK-002.md
    │   └── TASK-003.md
    │
    ├── reviews/
    │   ├── TASK-001-review-01.json
    │   ├── TASK-002-review-01.json
    │   └── TASK-002-review-02.json
    │
    └── workflow.json
```

The final storage strategy should be defined during TECHSPEC creation.

---

# 33. Context Management

Engineering Flow should not blindly send the complete workflow history to every agent.

Each role receives the context required for its responsibility.

Example:

```text
PRD
 ← initial requirement
 ← relevant project context

TECHSPEC
 ← PRD
 ← architecture
 ← repository

Planner
 ← PRD
 ← TECHSPEC

Developer
 ← TASK
 ← acceptance criteria
 ← TECHSPEC
 ← repository

Reviewer
 ← TASK
 ← acceptance criteria
 ← TECHSPEC
 ← implementation/diff
 ← repository

Fix
 ← TASK
 ← existing developer context
 ← review findings
```

The provider may independently explore the repository when its harness supports that capability.

---

# 34. Definition of Done — Task

A task is not completed simply because an agent stopped executing.

Conceptually:

```text
TASK DONE
    =
implementation completed

AND

required tests passed

AND

review passed

AND

blocking findings = 0
```

The exact quality gates should be formalized in the PRD and TECHSPEC.

---

# 35. Definition of Done — Workflow

Conceptually:

```text
WORKFLOW DONE
    =
PRD approved

AND

TECHSPEC approved

AND

task plan approved

AND

all tasks completed

AND

required tests passing

AND

reviews passing

AND

Git state valid

AND

branch pushed

AND

Pull Request created
```

Merge is not part of autonomous V1 completion.

---

# 36. Failure Handling

Engineering Flow should distinguish between different failure classes.

Examples:

```text
Agent failure
Provider failure
Tool failure
Test failure
Review failure
Git failure
Authentication failure
Human rejection
Workflow failure
```

Different failures require different responses.

Example:

```text
temporary provider failure
        ↓
retry

implementation causes test failure
        ↓
Developer fix

review finds blocking issue
        ↓
Developer fix

maximum review cycles reached
        ↓
human intervention

Git authentication failure
        ↓
workflow paused

human rejects TECHSPEC
        ↓
return to specification stage
```

---

# 37. Idempotency

External operations must be protected against accidental duplication.

Example:

```text
commit created
      ↓
process crashes
      ↓
workflow resumed
```

Engineering Flow must recognize that the commit already exists rather than create another one.

The same principle applies to:

- push;
- Pull Request creation;
- approvals;
- task completion;
- workflow completion.

---

# 38. Safety and Operational Guardrails

Potential safeguards include:

- sandbox policies;
- Reviewer read-only access;
- workspace boundaries;
- maximum review cycles;
- maximum execution retries;
- timeout policies;
- protected branches;
- prohibited destructive commands;
- secret protection;
- log sanitization;
- explicit repository validation;
- merge disabled by default;
- provider permission validation.

---

# 39. Initial Technical Architecture

Conceptual project structure:

```text
engineering-flow/

├── src/
│
│   ├── cli/
│   │
│   └── ...
│
│   ├── core/
│   │   ├── workflow/
│   │   ├── agents/
│   │   ├── policies/
│   │   └── events/
│
│   ├── providers/
│   │
│   │   ├── base/
│   │   │   ├── runtime.py
│   │   │   ├── session.py
│   │   │   ├── capabilities.py
│   │   │   └── events.py
│   │   │
│   │   └── codex/
│   │       ├── runtime.py
│   │       ├── session.py
│   │       ├── mapper.py
│   │       └── events.py
│
│   ├── integrations/
│   │   ├── git/
│   │   └── github/
│
│   ├── persistence/
│   │   └── sqlite/
│
│   └── telemetry/
│       └── ...
│
├── skills/
│
├── tests/
│
├── pyproject.toml
└── README.md
```

This is an architectural hypothesis, not a final TECHSPEC.

---

# 40. Logical Architecture

```text
┌──────────────────────────────────────────────┐
│                  USER / CLI                  │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│              WORKFLOW ENGINE                 │
│                                              │
│ State Machine                                │
│ Approval Gates                               │
│ Policies                                     │
│ Retry / Recovery                             │
│ Task Lifecycle                               │
│ Provider Selection                           │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│              AGENT ABSTRACTION               │
│                                              │
│ AgentRuntime                                 │
│ AgentSession                                 │
│ AgentExecution                               │
│ AgentCapabilities                            │
│ AgentEvent                                   │
└──────────────────────┬───────────────────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
┌──────────────┐ ┌───────────┐ ┌───────────┐
│    CODEX     │ │  CLAUDE   │ │   DEVIN   │
│   Provider   │ │ Provider  │ │ Provider  │
│     V1       │ │  Future   │ │  Future   │
└──────┬───────┘ └───────────┘ └───────────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│               CODEX HARNESS                  │
│                                              │
│ Models                                       │
│ Agent Loop                                   │
│ Shell                                        │
│ Filesystem                                   │
│ Skills                                       │
│ MCP                                          │
│ Sandbox                                      │
└──────────────────────────────────────────────┘

              +

┌──────────────────────────────────────────────┐
│             INTEGRATION LAYER                │
│                                              │
│ Git                                          │
│ GitHub                                       │
│ Persistence                                  │
│ Telemetry                                    │
└──────────────────────────────────────────────┘
```

---

# 41. MVP Scope

## Included

- Python;
- CLI;
- Workflow Engine;
- state machine;
- Agent Runtime abstraction;
- Codex provider;
- PRD generation;
- TECHSPEC generation;
- task decomposition;
- sequential task execution;
- Developer role;
- independent Reviewer role;
- automated review/fix loop;
- tests;
- configurable review limit;
- approval gates;
- workflow persistence;
- resume;
- structured logging;
- Git commit;
- Git push;
- Pull Request creation;
- workflow artifact preservation.

## Explicitly excluded from V1

- Claude provider;
- Devin provider;
- provider fallback;
- intelligent provider routing;
- multi-provider workflows;
- dashboard;
- cloud deployment;
- distributed workers;
- message broker;
- multi-user support;
- complex parallel task execution;
- semantic long-term memory;
- sophisticated cost optimization;
- marketplace of Skills.

Important distinction:

> The architecture should support future providers, but V1 should implement only Codex.

This prevents premature abstraction from increasing MVP complexity.

---

# 42. Primary MVP Validation

The MVP must prove one central hypothesis:

> **Can Engineering Flow take a feature through the complete engineering lifecycle and produce a review-ready Pull Request without requiring the developer to manually orchestrate implementation, review and fix cycles?**

The primary validation path is:

```text
Feature
   ↓
PRD
   ↓
TECHSPEC
   ↓
Tasks
   ↓
Implementation
   ↓
Review ↔ Fix
   ↓
Tests
   ↓
Git
   ↓
Pull Request
```

---

# 43. Validation Project

The current MBA project should not be used as the primary validation project because it is already close to completion.

After Engineering Flow reaches a functional MVP, a new small project should be created specifically to validate it.

The validation project should contain enough engineering complexity to exercise:

- API development;
- persistence;
- business rules;
- tests;
- multiple tasks;
- architecture decisions;
- code review;
- fix cycles;
- Git operations;
- Pull Request creation.

Potential examples:

```text
Task Management API
```

or:

```text
Personal Finance API
```

The purpose of this project is not primarily its business value.

It exists to test Engineering Flow under a realistic software engineering workload.

---

# 44. Metrics

The event model should eventually allow measurement of:

- workflow duration;
- duration per stage;
- duration per task;
- review cycles;
- first-pass review rate;
- agent executions;
- retries;
- failures;
- human interventions;
- tests executed;
- files changed;
- provider usage;
- model usage;
- reasoning configuration.

A particularly important product metric is:

## Human Touches per Workflow

Example:

```text
Manual workflow

20 human interactions
```

versus:

```text
Engineering Flow

PRD approval
TECHSPEC approval
Plan approval
Final PR review

= 4 human interactions
```

Long-term target:

```text
Feature request
+
Final PR review
```

---

# 45. Future Evolution

## V1 — Autonomous Engineering Loop

```text
Requirement
→ PRD
→ TECHSPEC
→ Tasks
→ Implementation
→ Review/Fix
→ PR
```

Goal:

> Eliminate manual workflow orchestration.

---

## V2 — Reliability

Potential additions:

- stronger recovery;
- checkpointing;
- richer policies;
- better context management;
- advanced observability;
- dynamic model/reasoning configuration;
- improved quality gates.

Goal:

> Make autonomous execution reliable.

---

## V3 — Multi-Agent Provider Support

Potential additions:

```text
Codex
Claude
Devin
```

including:

- provider capability discovery;
- provider selection;
- per-role providers;
- provider fallback;
- provider comparison.

Goal:

> Make Engineering Flow agent-agnostic in actual execution, not only architecture.

---

## V4 — Parallel Engineering

Potential support for independent tasks:

```text
            TASK GRAPH

        ┌──────┼──────┐
        ▼      ▼      ▼
     TASK-A  TASK-B  TASK-C
        │      │      │
        └──────┼──────┘
               ▼
          integration
```

Potential isolation mechanisms:

- Git branches;
- Git worktrees;
- isolated workspaces.

Goal:

> Reduce workflow execution time.

---

## V5 — Platform

Potential evolution:

- dashboard;
- multiple repositories;
- multiple teams;
- remote workers;
- workflow templates;
- analytics;
- CI/CD integrations;
- issue tracker integrations;
- organizational policies.

These are future possibilities rather than current commitments.

---

# 46. Dogfooding

The initial version of Engineering Flow will necessarily be developed using a partially manual AI-assisted engineering workflow.

Once the MVP is operational, Engineering Flow should increasingly be used to develop Engineering Flow itself.

```text
Engineering Flow
       │
       ▼
develops
       │
       ▼
Engineering Flow
```

This creates a strong dogfooding scenario and provides real-world validation of the architecture.

---

# 47. Portfolio Value

Engineering Flow should demonstrate substantially more than basic LLM integration.

Technical areas demonstrated include:

- AI Engineering;
- Agentic Systems;
- Software Architecture;
- Provider Abstraction;
- Adapter Pattern;
- Workflow Orchestration;
- State Machines;
- Human-in-the-loop;
- Coding Agent Harness Integration;
- Context Management;
- Structured Outputs;
- Retry Strategies;
- Failure Recovery;
- Idempotency;
- Observability;
- Event-driven concepts;
- Git automation;
- GitHub integration;
- CLI design;
- Persistence;
- Testing;
- SDLC automation.

The project should therefore be positioned as:

> **AI-powered software engineering infrastructure**

rather than:

> **an LLM wrapper**

---

# 48. Repository Identity

## Recommended repository name

```text
engineering-flow
```

The name intentionally avoids references to a specific provider.

Avoid names such as:

```text
codex-engineering-flow
codex-workflow
codex-orchestrator
```

because Codex is an implementation/provider choice rather than the identity of the product.

---

# 49. GitHub Description

Recommended:

> **Agent-agnostic orchestration engine for autonomous software engineering workflows, from requirements to review-ready pull requests.**

Alternative, slightly more descriptive:

> **Agent-agnostic software engineering workflow orchestrator that automates specifications, planning, implementation, review/fix loops, and pull request delivery.**

The first version is recommended because it is shorter and communicates the architectural positioning clearly.

---

# 50. Elevator Pitch

> **Engineering Flow is an agent-agnostic software engineering orchestration engine that coordinates AI coding agents across requirements, specification, planning, implementation, testing, autonomous review/fix loops, and Git workflows to produce review-ready Pull Requests with configurable human approval gates.**

---

# 51. North Star

The long-term product vision is:

> **Describe the feature. Review the Pull Request.**

Engineering Flow exists to automate the engineering orchestration between these two moments.

---

# 52. Architectural North Star

Engineering Flow should own:

```text
WORKFLOW
STATE
POLICIES
APPROVALS
ORCHESTRATION
OBSERVABILITY
GIT LIFECYCLE
```

Providers should own:

```text
ENGINEERING REASONING
CODE EXPLORATION
IMPLEMENTATION
DEBUGGING
CODE ANALYSIS
```

The relationship should remain:

```text
                   ENGINEERING FLOW
                    Control Plane
                         │
                         │
                  Agent Contract
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
       Codex          Claude          Devin
     Execution       Execution       Execution
       Plane           Plane           Plane
```

---

# 53. Final Product Definition

Engineering Flow is not:

- another coding agent;
- another LLM wrapper;
- a replacement for Codex;
- a replacement for Claude;
- a replacement for Devin.

Engineering Flow is:

> **The orchestration layer that coordinates engineering agents through a controlled, observable and configurable software development lifecycle.**

The initial implementation uses Codex.

The architecture remains provider-neutral.

Future providers can be added through adapters without redesigning the core workflow.

---

# 54. Purpose of This Document

This document is intentionally not the final PRD or TECHSPEC.

It should serve as input for the formal PRD generation process.

It contains:

```text
PRODUCT VISION
+
PROBLEM DEFINITION
+
PRODUCT BOUNDARIES
+
CORE REQUIREMENTS
+
ARCHITECTURAL PRINCIPLES
+
TECHNICAL HYPOTHESES
+
MVP BOUNDARIES
+
FUTURE DIRECTION
```

The PRD generation process should refine product requirements without prematurely locking implementation details that belong to architecture or TECHSPEC.

Recommended subsequent flow:

```text
THIS DOCUMENT
      ↓
PRD
      ↓
GLOBAL ARCHITECTURE
      ↓
TECHSPEC
      ↓
WAVES
      ↓
TASK DECOMPOSITION
      ↓
IMPLEMENTATION
```

The PRD should preserve the fundamental product intent:

> **Automate the operational orchestration of AI-assisted software engineering while keeping the underlying engineering agent replaceable.**
