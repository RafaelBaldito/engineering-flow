---
name: wave-review
description: |
  Perform an independent acceptance audit of one completed delivery Wave after
  all tasks in that Wave have completed task-level implementation and review.
  Validate traceability from the approved Wave scope and TECHSPEC through tasks,
  implementation, tests, task-review evidence, and the Wave's demonstrable
  outcome. Produce PASS, FIX_REQUIRED, SPEC_CHANGE_REQUIRED, or BLOCKED with
  evidence-based findings. Persist the authoritative Wave review artifact.
  Do not fix code, re-review tasks, start another Wave, or silently change
  approved specifications.
---

# Wave Review

## Purpose

Perform an independent acceptance audit of one completed delivery Wave.

Unlike `review-task`, which validates one implementation task, this skill
verifies that the Wave as a whole is coherent, complete, integrated, and
traceable.

Unlike `final-review`, which validates the complete approved release across all
included Waves, this skill is strictly scoped to one Wave.

The Wave review answers two complementary questions:

1. Was everything approved for this Wave actually delivered?
2. Is everything delivered in this Wave consistent with the approved Wave scope?

The review must validate the chain:

`Delivery Plan → Architecture → Wave TECHSPEC → Tasks → Task Reviews → Code → Tests → Wave Outcome`

Do not evaluate future Waves except where a dependency boundary must be checked.

## When to Use

Use this skill when:

- all implementation tasks for the target Wave are believed complete;
- all required task-level fixes are believed complete;
- the Wave is ready for an acceptance gate before the next Wave;
- a previously failed Wave review has been remediated and needs re-review.

Do not use this skill when:

- individual task defects are already known and have not been remediated;
- required tasks are intentionally pending;
- the request is to review one task;
- the request is to fix code;
- the request is to accept the full release;
- the target Wave cannot be identified.

## Inputs

### Required

- target Wave identifier;
- approved Delivery Plan or equivalent delivery definition;
- approved TECHSPEC for the target Wave;
- repository implementation state.

### Conditionally Required

When present in the approved workflow:

- approved PRD;
- approved architecture documentation or ADRs;
- task index for the Wave;
- task specifications;
- task-review artifacts;
- Wave manual-acceptance procedure;
- runtime/provider acceptance requirements.

### Optional

Load when necessary:

- `AGENTS.md`;
- repository README;
- validation configuration;
- deployment/runtime configuration;
- previous Wave review;
- remediation evidence from `fix-wave-review`.

## Authoritative Sources

Use the following precedence unless the user explicitly establishes another
authority:

1. current explicit user instructions authorized to define Wave-review scope;
2. approved PRD;
3. approved Delivery Plan;
4. approved architecture decisions and ADRs;
5. approved Wave TECHSPEC;
6. approved task specifications;
7. explicit repository constraints and conventions;
8. implementation, tests, and persisted review evidence.

Lower-level artifacts and code must not silently redefine approved upstream
scope.

Task-level `PASS` is required evidence, but it does not by itself prove Wave
acceptance.

## Preconditions

Before beginning Wave acceptance, verify:

- [ ] the target Wave is explicit;
- [ ] the approved Wave boundary can be identified;
- [ ] the approved Wave TECHSPEC is available;
- [ ] all tasks expected for the Wave have a known status;
- [ ] required task-review evidence exists;
- [ ] repository state represents the Wave being reviewed;
- [ ] no intentionally incomplete work is being presented as complete.

If the Wave boundary or required approved artifacts cannot be established,
report `BLOCKED`.

If approved artifacts contradict each other in a way that prevents valid Wave
acceptance, report `SPEC_CHANGE_REQUIRED`.

If any required task is not independently accepted, the Wave cannot receive
`PASS`.

## Workflow

### 1. Establish the Wave boundary

Identify exactly what is being accepted.

Record:

- Wave identifier and name;
- approved Wave objective;
- included requirements/capabilities;
- dependencies from earlier Waves;
- explicitly deferred work;
- non-goals;
- applicable architecture constraints;
- demonstrable Wave outcome.

Future Waves are outside the review boundary unless required to understand an
approved dependency contract.

### 2. Build the Wave traceability map

For each applicable Wave requirement or TECHSPEC obligation, trace where
possible:

`Requirement → TECHSPEC → Task(s) → Task Review → Implementation → Test/Validation`

Flag broken links such as:

- approved Wave behavior with no task coverage;
- task with no implementation evidence;
- implementation with no approved Wave source;
- important behavior with no meaningful validation evidence;
- task status inconsistent with its latest authoritative review artifact.

### 3. Verify task completion and review evidence

Inspect the Wave task index and task-review artifacts.

Every required task must be:

- implemented;
- independently reviewed;
- accepted with `PASS`, or an equivalent approved state.

Do not infer task acceptance from `TASKS.md` alone.

When the task index and the latest persisted task-review artifact disagree,
report a finding with ownership `TASK_REVIEW_REQUIRED`.

Do not perform the missing independent task review yourself.

### 4. Verify Wave implementation completeness

Evaluate whether the integrated implementation satisfies the approved Wave
TECHSPEC and intended demonstrable outcome.

Identify:

- missing implementation;
- partial implementation;
- unapproved behavior;
- broken integration between Wave tasks;
- incomplete persistence/state transitions;
- provider/runtime integration defects where the Wave requires them.

### 5. Verify architecture coherence

Check only architecture decisions applicable to the target Wave.

Consider:

- component boundaries;
- dependency direction;
- provider-neutral contracts;
- persistence/resume/idempotency;
- event and observability boundaries;
- safety and failure boundaries;
- Git/PR boundaries when applicable.

Do not introduce requirements that belong only to future Waves.

### 6. Run Wave-level deterministic validation

Run the broadest repository-native checks necessary for the Wave.

Depending on the project, this may include:

- full or relevant test suite;
- integration tests;
- end-to-end tests;
- lint;
- type checking;
- build/import/compile checks;
- packaging checks;
- runtime smoke tests.

Never claim a check passed unless it was actually executed.

Record unavailable checks explicitly.

### 7. Validate the Wave end-to-end outcome

Validate the primary approved flow delivered by this Wave.

Prefer the Wave's documented manual-acceptance or end-to-end procedure.

If the approved TECHSPEC requires a live provider/runtime validation, it is
required acceptance evidence.

If it cannot be executed because of external tooling, credentials,
infrastructure, or environment dependencies, report
`ENVIRONMENT_BLOCKED`.

If the procedure exists but simply has not been run and can be performed in the
current environment, report `MANUAL_VALIDATION_REQUIRED`.

### 8. Review Wave documentation

Verify documentation required to execute, evaluate, or continue from this Wave.

Check when applicable:

- manual acceptance;
- runtime prerequisites;
- environment variables;
- CLI commands;
- expected outputs;
- known limitations;
- handoff assumptions for the next Wave.

### 9. Classify findings

Use these severities:

`CRITICAL`
- severe correctness, security, data-loss, or Wave-level acceptance failure.

`HIGH`
- major approved Wave requirement missing;
- primary Wave flow broken;
- required acceptance validation failed or unavailable;
- significant architecture/integration violation.

`MEDIUM`
- real integration, validation, documentation, maintainability, or quality
  problem that should be resolved before Wave acceptance.

`LOW`
- concrete non-blocking improvement.

Each material finding must include:

- identifier;
- severity;
- category;
- ownership;
- affected requirement/scope when applicable;
- location;
- issue;
- evidence;
- expected state;
- remediation direction.

Do not create duplicate findings for the same root cause.

### 10. Determine remediation ownership

Use exactly one primary ownership value per blocking finding:

`WAVE_FIX`

The approved Wave specification is correct and implementation, tests,
non-approved documentation, or Wave-local evidence preparation must be corrected
within the current Wave.

`TASK_REVIEW_REQUIRED`

The implementation may already be correct, but required independent task-review
evidence is missing, stale, or contradictory.

`NEW_TASK_REQUIRED`

Approved Wave scope contains required implementation work that was never
represented by an implementation task.

`MANUAL_VALIDATION_REQUIRED`

The implementation is reviewable, but required acceptance evidence must be
produced by executing an approved manual/live validation procedure.

`ENVIRONMENT_BLOCKED`

External tooling, credentials, infrastructure, sandboxing, runtime availability,
or local environment prevents required validation or remediation.

`SPEC_CHANGE_REQUIRED`

An approved PRD, Delivery Plan, Architecture, or Wave TECHSPEC decision must
change before the Wave can be validly accepted.

The Wave review identifies remediation ownership but does not perform
remediation.

### 11. Determine Wave outcome

Return `PASS` only when:

- all approved Wave requirements are delivered;
- every required task has authoritative independent `PASS` evidence;
- Wave-level deterministic validation passes;
- required manual/live acceptance evidence exists;
- the Wave's primary integrated outcome is validated;
- no `CRITICAL`, `HIGH`, or `MEDIUM` blocking finding remains;
- no material scope drift remains.

Return `FIX_REQUIRED` when one or more blocking findings can be remediated within
the existing approved Wave scope without changing approved upstream
specifications.

Return `SPEC_CHANGE_REQUIRED` when acceptance requires changing approved
product, delivery, architecture, or Wave technical specifications.

Return `BLOCKED` when reliable Wave acceptance cannot proceed because required
external context, environment, infrastructure, credentials, or independent
evidence is unavailable.

### 12. Persist the Wave review

The Wave review MUST be persisted.

Default authoritative artifact:

`tasks/<wave>/reviews/WAVE-REVIEW.md`

If the repository has an explicit equivalent convention, use that convention
and report the exact path.

The persisted artifact is the authoritative Wave-review record.

Do not leave findings only in console output.

On re-review, update or supersede the authoritative Wave-review artifact so the
current acceptance state is unambiguous. Preserve historical evidence only when
the repository has an explicit history/versioning convention.

## Rules

### MUST

- review exactly one Wave;
- preserve Wave boundary;
- verify task-review evidence;
- verify task-index/review consistency;
- maintain Wave requirement-to-evidence traceability;
- run applicable Wave-level validation;
- validate integrated Wave behavior;
- classify remediation ownership;
- persist the authoritative Wave-review artifact;
- base acceptance on current evidence;
- stop after producing the Wave-review result.

### MUST NOT

- modify production code;
- modify tests to make validation pass;
- silently fix findings;
- run `review-task`;
- run `fix-task`;
- run `fix-wave-review`;
- create implementation tasks automatically;
- change approved PRD, Delivery Plan, Architecture, or TECHSPEC;
- start the next Wave;
- run `final-review`;
- accept a task whose authoritative review is not `PASS`;
- claim validation passed when it was not executed;
- evaluate future Wave implementation as if it were current-Wave scope.

### SHOULD

- use task-review `PASS` evidence to avoid redundant task-level investigation;
- focus deeper inspection on integration and cross-task behavior;
- distinguish stale evidence from actual code defects;
- distinguish missing manual validation from environment failures;
- keep the persisted review understandable without chat history.

## Output

Persist `WAVE-REVIEW.md` with this structure:

```markdown
## Wave Review Result

<PASS | FIX_REQUIRED | SPEC_CHANGE_REQUIRED | BLOCKED>

## Wave Scope

- Wave: <identifier and name>
- Objective: <approved outcome>
- Included scope: <scope>
- Deferred scope: <if any>

## Traceability Summary

| Requirement/Decision | Task(s) | Review Evidence | Implementation/Test Evidence | Status |
|---|---|---|---|---|
| ... | ... | ... | ... | DELIVERED / PARTIAL / MISSING / DEFERRED / NOT_VERIFIABLE |

## Task Review Summary

- Total required tasks: <n>
- PASS: <n>
- Pending/unreviewed: <n>
- FIX_REQUIRED: <n>
- BLOCKED: <n>
- SPEC_CHANGE_REQUIRED: <n>
- Evidence conflicts: <n>

## Wave Validation

| Check | Result | Evidence |
|---|---|---|
| `<command or check>` | PASS / FAIL / NOT RUN | <concise evidence> |

## End-to-End Validation

- <flow> — PASS / FAIL / NOT RUN — <evidence>

## Findings

### WAVE-001 — <Severity> — <Title>

- Category: <Requirements | Integration | Architecture | Validation | Documentation | Scope Drift | Security | Review Evidence | Environment | Other>
- Ownership: <WAVE_FIX | TASK_REVIEW_REQUIRED | NEW_TASK_REQUIRED | MANUAL_VALIDATION_REQUIRED | ENVIRONMENT_BLOCKED | SPEC_CHANGE_REQUIRED>
- Requirement/Scope: <identifier when applicable>
- Location: `<path:symbol-or-line>` or artifact
- Issue: <what is wrong>
- Evidence: <concrete evidence>
- Expected: <approved expected state>
- Remediation direction: <concise guidance>

## Blocking Conditions

- <blocking conditions, or `None.`>

## Non-Blocking Notes

- <optional LOW findings or observations>

## Summary

<concise Wave acceptance rationale>
```

For `PASS`, Findings may be omitted if none exist.

After persisting the artifact, the console completion response must contain only:

1. Wave review status;
2. authoritative artifact path;
3. number of blocking findings;
4. recommended next workflow action.

## Completion

A Wave `PASS` means the Wave is accepted and may proceed to the next approved
workflow stage.

Do not start that stage automatically.
