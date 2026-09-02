---
description: |
  Perform the final project-level acceptance audit after all planned
  delivery scopes and tasks have completed task-level review. Validate
  end-to-end traceability from approved requirements through delivery
  plans, technical specifications, tasks, implementation, and tests.
  Detect missing implementation, specification drift, integration
  defects, and undocumented scope. Produce PASS, FIX_REQUIRED,
  SPEC_CHANGE_REQUIRED, or BLOCKED with evidence-based findings. Do not
  fix code or silently change approved specifications.
name: final-review
---

# Final Review

## Purpose

Perform an independent final audit of the complete approved delivery.

Unlike `review-task`, which validates one implementation task, this
skill verifies that the project as a whole is coherent, complete,
integrated, and traceable.

The final review answers two complementary questions:

1.  Was everything that was approved actually delivered?
2.  Is everything that was delivered consistent with what was approved?

The review must validate the full chain:

`PRD → Delivery Plan → Architecture → TECHSPEC(s) → Tasks → Code → Tests`

Not every project will contain every artifact. The review must adapt to
the approved delivery mode and repository conventions without inventing
missing ceremony.

## When to Use

Use this skill when:

-   all planned `SINGLE` tasks have completed task-level review; or
-   all planned Waves intended for the current release have completed
    their task-level reviews;
-   the project or release is believed to be implementation-complete;
-   a final acceptance audit is requested before declaring delivery
    complete;
-   a previously failed final review has been remediated and needs
    re-review.

Do not use this skill when:

-   implementation tasks are still intentionally pending;
-   individual task defects are already known and have not been
    remediated;
-   the request is to implement or fix code;
-   the request is only to review one task;
-   product or technical planning is still actively changing.

## Inputs

### Required

-   approved PRD;
-   approved delivery definition for the release:
    -   `SINGLE`, or
    -   the set of Waves included in the release;
-   repository implementation state.

### Conditionally Required

When present in the approved workflow:

-   approved Delivery Plan;
-   approved architecture documentation or ADRs;
-   approved TECHSPEC(s);
-   task indexes and task specifications;
-   task review status/evidence.

### Optional

Load when necessary:

-   `AGENTS.md`;
-   repository README;
-   validation configuration;
-   deployment or runtime configuration;
-   relevant operational documentation;
-   previous final-review findings when performing re-review.

## Authoritative Sources

Use the following precedence unless the user explicitly establishes
another authority:

1.  current explicit user instructions authorized to define final-review
    scope;
2.  approved PRD;
3.  approved Delivery Plan;
4.  approved architecture decisions and ADRs;
5.  approved TECHSPEC(s);
6.  approved task specifications;
7.  explicit repository constraints and conventions;
8.  implementation and tests as delivery evidence.

Lower-level artifacts and code must not silently redefine approved
upstream scope.

Task-level `PASS` is evidence, but it does not guarantee project-level
acceptance. Integration and traceability must still be verified.

## Preconditions

Before beginning final acceptance:

-   [ ] the release boundary can be identified;
-   [ ] required approved specification artifacts are available;
-   [ ] all tasks expected for the release have a known status;
-   [ ] no intentionally incomplete delivery scope is being presented as
    complete;
-   [ ] repository state represents the release being reviewed.

If required artifacts or release boundaries cannot be established,
report `BLOCKED`.

If approved artifacts contradict each other in a way that prevents final
acceptance, report `SPEC_CHANGE_REQUIRED`.

## Workflow

### 1. Establish the final-review boundary

Determine exactly what is being accepted.

For `SINGLE`, identify the complete approved delivery scope.

For `WAVES`, identify which approved Waves belong to the release under
review.

Record:

-   included product requirements;
-   included delivery scopes;
-   explicitly deferred requirements or Waves;
-   non-goals;
-   applicable global constraints.

Do not treat intentionally deferred work as missing implementation.

### 2. Build the traceability map

Construct a working traceability map from approved requirements to
delivery evidence.

For each applicable requirement, trace where possible:

`Requirement → Delivery Scope → TECHSPEC → Task(s) → Implementation → Test/Validation`

The map is an audit mechanism and does not need to become a permanent
artifact unless repository conventions require it.

Flag broken links such as:

-   approved requirement with no delivery scope;
-   delivery scope with no technical realization;
-   TECHSPEC decision with no task coverage;
-   task with no implementation evidence;
-   implemented behavior with no approved source;
-   important behavior with no meaningful validation evidence.

### 3. Verify delivery-plan completion

For `WAVES`:

-   confirm every Wave included in the release reached its intended
    demonstrable outcome;
-   confirm dependencies between Waves are satisfied;
-   verify no required release behavior was left only in a future
    outline.

For `SINGLE`:

-   confirm the approved complete delivery boundary was implemented.

Do not require future Waves that are explicitly outside the release
boundary.

### 4. Verify task completion and review state

Inspect task indexes/statuses and review evidence.

Confirm that every required implementation task is:

-   implemented;
-   independently reviewed;
-   accepted with `PASS`, unless the repository uses an equivalent
    approved state.

Identify:

-   `PENDING` tasks;
-   `IMPLEMENTED` but unreviewed tasks;
-   unresolved `FIX_REQUIRED`;
-   `BLOCKED`;
-   `SPEC_CHANGE_REQUIRED`;
-   tasks missing from expected coverage.

A release cannot receive final `PASS` while required task-level blockers
remain.

### 5. Audit requirements completeness

Review every applicable PRD requirement.

Determine whether each requirement is:

`DELIVERED`

Implementation and validation evidence support it.

`PARTIAL`

Some required behavior exists but the approved requirement is not fully
satisfied.

`MISSING`

No sufficient implementation evidence exists.

`DEFERRED`

Explicitly outside the current approved release boundary.

`NOT_VERIFIABLE`

Available evidence is insufficient to determine delivery.

Do not infer delivery merely from task names or documentation claims.

### 6. Audit implementation drift

Inspect implementation for behavior that materially exceeds or
contradicts the approved scope.

Look for:

-   undocumented user-visible behavior;
-   implementation of deferred/future scope;
-   incompatible contract changes;
-   architectural divergence;
-   unapproved dependencies or integrations;
-   changed assumptions not reflected upstream.

Not every incidental implementation detail requires documentation.

Report drift when it materially affects product behavior, architecture,
security, compatibility, operations, or future maintenance.

### 7. Verify architecture coherence

When architecture documentation or ADRs exist, verify that the
integrated system respects them.

Check relevant cross-cutting concerns such as:

-   component boundaries;
-   dependency direction;
-   shared contracts;
-   persistence strategy;
-   integration boundaries;
-   configuration;
-   security boundaries;
-   global error-handling conventions.

Do not invent architecture requirements that were never approved.

### 8. Run project-level deterministic validation

Run the broadest applicable repository-native checks needed for final
acceptance.

Depending on the project, this may include:

-   full test suite;
-   integration tests;
-   end-to-end tests;
-   lint;
-   type checking;
-   build/import checks;
-   migration/database checks;
-   packaging checks;
-   established security/static analysis;
-   runtime smoke tests.

Prefer repository-defined commands.

Never claim a check passed unless it was actually executed.

Record failures and unavailable checks explicitly.

### 9. Validate end-to-end behavior

Task-level tests may pass while integrated behavior fails.

Where the product exposes a meaningful complete flow, validate the
primary approved flow end to end.

Examples:

-   input → processing → persistence → retrieval;
-   request → service → database → response;
-   ingestion → indexing → retrieval → generated response;
-   CLI command → application behavior → output.

Use the product's actual approved flow rather than creating artificial
end-to-end scenarios.

### 10. Review cross-cutting quality

Evaluate project-level concerns that may not belong to a single task.

Consider when applicable:

-   error handling across boundaries;
-   configuration consistency;
-   security hygiene;
-   secrets handling;
-   dependency consistency;
-   startup/runtime behavior;
-   persistence/integration consistency;
-   observability;
-   documentation required to operate the solution;
-   backward compatibility;
-   migration coherence.

Focus on material acceptance risks rather than style preferences.

### 11. Review delivery documentation

Verify that documentation required for use, execution, or evaluation
matches the delivered implementation.

Depending on the project this may include:

-   README execution instructions;
-   required environment variables;
-   setup commands;
-   database/bootstrap steps;
-   example usage;
-   operational limitations.

Documentation defects are blocking when they prevent the approved
product from being reliably run, evaluated, or operated as required.

### 12. Classify findings

Use the same severity model as task review.

`CRITICAL`

-   severe security, data-loss, correctness, or release-level
    specification failure that makes acceptance unsafe.

`HIGH`

-   major approved requirement missing;
-   primary flow broken;
-   required Wave incomplete;
-   significant architecture or integration violation;
-   critical project-level validation failure.

`MEDIUM`

-   real integration, quality, testing, documentation, or
    maintainability issue that should be resolved before final
    acceptance.

`LOW`

-   concrete non-blocking improvement.

Each material finding must include:

-   identifier;
-   severity;
-   category;
-   affected requirement/scope when applicable;
-   location;
-   issue;
-   evidence;
-   expected state;
-   recommended remediation direction.

Do not create duplicate findings for the same root cause.

### 13. Determine remediation ownership

For each blocking finding, determine where the correction belongs.

Use:

`TASK_FIX`

The approved specification is correct and implementation must be
corrected.

`NEW_TASK_REQUIRED`

The approved scope contains required work that was never represented by
an implementation task.

`SPEC_CHANGE_REQUIRED`

Approved artifacts are contradictory, incorrect, or must change before a
valid implementation decision can be made.

`BLOCKED`

External context, infrastructure, or evidence prevents resolution.

The final review identifies remediation ownership but does not implement
it.

### 14. Determine final outcome

Return `PASS` only when:

-   all applicable approved requirements are delivered;
-   all required tasks have passed independent review;
-   included delivery scopes are complete;
-   project-level deterministic validation passes;
-   primary integrated behavior is validated where applicable;
-   no `CRITICAL`, `HIGH`, or `MEDIUM` blocking finding remains;
-   no material undocumented scope drift remains.

Return `FIX_REQUIRED` when defects can be corrected without changing
approved upstream specifications.

Return `SPEC_CHANGE_REQUIRED` when final acceptance requires changing
approved product, delivery, architecture, or technical specifications.

Return `BLOCKED` when reliable final acceptance cannot be completed.

### 15. Produce the final-review report

Return a concise but complete audit result.

Do not fix implementation.

Do not modify approved specifications.

Do not automatically create tasks or invoke remediation skills.

## Rules

### MUST

-   review the complete approved release boundary;
-   verify both missing implementation and implementation drift;
-   maintain requirement-to-evidence traceability;
-   verify task review completion;
-   run applicable project-level validation;
-   validate integrated behavior when applicable;
-   inspect cross-cutting architecture and quality concerns;
-   distinguish implementation defects from specification defects;
-   classify findings by severity and remediation ownership;
-   base acceptance on evidence;
-   stop after producing the final-review result.

### MUST NOT

-   modify production code;
-   modify tests to make validation pass;
-   silently fix findings;
-   change the PRD;
-   change the Delivery Plan;
-   change architecture decisions;
-   change TECHSPECs;
-   create implementation tasks automatically;
-   accept required tasks that remain unreviewed;
-   treat task-level `PASS` as sufficient evidence of complete project
    acceptance;
-   invent requirements not present in approved scope;
-   fail deferred scope that is explicitly outside the release boundary;
-   claim validation passed when it was not executed;
-   automatically invoke another workflow stage.

### SHOULD

-   use traceability to focus repository inspection;
-   prefer repository-native validation commands;
-   use task review evidence rather than repeating every task-level
    investigation;
-   focus deeper inspection on integration boundaries and cross-cutting
    behavior;
-   keep findings actionable and non-duplicative;
-   distinguish blocking findings from release notes and future
    improvements;
-   keep final acceptance evidence understandable without chat history.

## Context Management

Final review necessarily has a broader Context Surface than task-level
skills, but context should still be loaded progressively.

Read first:

-   approved PRD;
-   approved Delivery Plan when applicable;
-   task indexes/statuses for included delivery scopes;
-   `AGENTS.md` when present.

Then load as needed:

-   relevant TECHSPEC sections;
-   architecture overview and applicable ADRs;
-   individual task specifications;
-   task review evidence;
-   implementation files associated with traceability gaps or
    integration paths;
-   relevant tests;
-   repository validation configuration;
-   README/runtime documentation.

Do not load by default:

-   future Waves outside the release;
-   unrelated historical specifications;
-   obsolete review history;
-   complete repository history;
-   every source file merely for completeness.

Use task-level `PASS` results to reduce redundant deep inspection, while
still verifying project-level integration and traceability.

## Output

Do not modify production artifacts.

Update final status metadata only if the repository explicitly defines
such a convention.

Return:

``` markdown
## Final Review Result

<PASS | FIX_REQUIRED | SPEC_CHANGE_REQUIRED | BLOCKED>

## Release Scope

- Delivery mode: <SINGLE | WAVES>
- Included scopes: <scope(s)>
- Deferred scopes: <if any>

## Traceability Summary

| Requirement | Delivery Scope | Task(s) | Evidence | Status |
|-------------|----------------|---------|----------|--------|
| FR-001 | ... | ... | ... | DELIVERED / PARTIAL / MISSING / DEFERRED / NOT_VERIFIABLE |

## Task Review Summary

- Total required tasks: <n>
- PASS: <n>
- Pending/unreviewed: <n>
- FIX_REQUIRED: <n>
- BLOCKED: <n>
- SPEC_CHANGE_REQUIRED: <n>

## Project Validation

| Check | Result | Evidence |
|-------|--------|----------|
| `<command or check>` | PASS / FAIL / NOT RUN | <concise evidence> |

## End-to-End Validation

- <flow> — PASS / FAIL / NOT RUN — <evidence>

## Findings

### FINAL-001 — <Severity> — <Title>

- Category: <Requirements | Integration | Architecture | Validation | Documentation | Scope Drift | Security | Other>
- Ownership: <TASK_FIX | NEW_TASK_REQUIRED | SPEC_CHANGE_REQUIRED | BLOCKED>
- Requirement/Scope: <identifier when applicable>
- Location: `<path:symbol-or-line>` or artifact
- Issue: <what is wrong>
- Evidence: <concrete evidence>
- Expected: <approved expected state>
- Remediation direction: <concise guidance>

## Non-Blocking Notes

- <optional LOW findings or release observations>

## Summary

<concise final acceptance rationale>
```

For `PASS`, the Findings section may be omitted when no findings exist.

Do not create a separate report file unless repository conventions
explicitly require one.

## Validation

Before completing, verify:

-   [ ] the release boundary is explicit;
-   [ ] every applicable approved requirement has a traceability status;
-   [ ] deferred requirements are explicitly approved as outside the
    release;
-   [ ] required tasks have known review states;
-   [ ] task-level blockers were not ignored;
-   [ ] relevant architecture constraints were checked;
-   [ ] project-level validation was actually run when possible;
-   [ ] primary integrated behavior was validated when applicable;
-   [ ] documentation required to run/evaluate the product was checked;
-   [ ] implementation drift was considered;
-   [ ] findings contain concrete evidence;
-   [ ] remediation ownership is identified;
-   [ ] implementation and specification defects are distinguished;
-   [ ] no code, tests, tasks, or approved specifications were modified;
-   [ ] no remediation stage was started automatically.

## Completion

Return `PASS` when the complete release is accepted.

A final `PASS` means:

-   approved release requirements are delivered;
-   implementation is traceable to approved specifications;
-   required task-level reviews are complete;
-   integrated validation is satisfactory;
-   no blocking final-review finding remains.

Return `FIX_REQUIRED` when one or more blocking defects can be corrected
within the existing approved specifications.

For each `FIX_REQUIRED` finding, identify whether remediation belongs to
an existing task (`TASK_FIX`) or requires an explicitly approved new
task (`NEW_TASK_REQUIRED`).

Do not create or execute remediation automatically.

## Escalation

Return `BLOCKED` when:

-   the release boundary cannot be established;
-   required specification or review artifacts are unavailable;
-   repository state does not represent a reviewable release;
-   mandatory project-level validation infrastructure is unavailable and
    prevents a reliable acceptance decision;
-   critical delivery evidence cannot be obtained.

Return `SPEC_CHANGE_REQUIRED` when:

-   approved requirements contradict each other;
-   Delivery Plan and PRD cannot be reconciled;
-   approved architecture and TECHSPEC decisions conflict materially;
-   delivered behavior can only be accepted by changing approved scope;
-   a missing implementation requirement exposes a genuine upstream
    specification gap rather than a task-decomposition omission.

When escalating:

1.  identify the exact affected requirement or approved artifact;
2.  provide concrete implementation, traceability, or validation
    evidence;
3.  explain why implementation-only remediation is insufficient;
4.  identify the minimum upstream decision required.

Do not change approved artifacts merely to make the delivered
implementation appear compliant.
