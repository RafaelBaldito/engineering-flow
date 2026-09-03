---
name: final-review
description: |
  Perform the final release-level acceptance audit after every delivery scope
  included in the approved release has completed its Wave-level or equivalent
  acceptance review. Validate end-to-end traceability from approved
  requirements through delivery plans, architecture, technical specifications,
  accepted Waves, implementation, tests, and release-level behavior. Produce
  PASS, FIX_REQUIRED, SPEC_CHANGE_REQUIRED, or BLOCKED with evidence-based
  findings. Persist the authoritative final review artifact. Do not fix code,
  re-review Waves, or silently change approved specifications.
---

# Final Review

## Purpose

Perform an independent final acceptance audit of the complete approved release.

This skill is release-level.

It MUST NOT be used as the acceptance gate for a single Wave when the approved
delivery contains additional Waves.

Use `wave-review` to accept an individual Wave.

Runtime/product `final validation` is a quality gate and source of evidence for
this audit. It is not this release-level `final-review`, and it never replaces
the required authoritative Wave-review PASS for each included Wave.

The final review answers:

1. Was the complete approved release delivered?
2. Are all included delivery scopes accepted and mutually coherent?
3. Does the integrated release satisfy approved product and architecture
   expectations?

The release traceability chain is:

`PRD → Delivery Plan → Architecture → Accepted Wave(s) → TECHSPEC(s) → Tasks → Code → Tests → Release Validation`

## When to Use

Use this skill when:

- all Waves included in the release have completed `wave-review` with `PASS`; or
- a `SINGLE` delivery has completed its equivalent implementation/review gate;
- the release is believed implementation-complete;
- a final release acceptance audit is requested;
- a previously failed final review has been remediated and needs re-review.

Do not use this skill when:

- any included Wave still lacks Wave-level acceptance;
- a Wave has unresolved blocking findings;
- implementation tasks are still intentionally pending;
- the request is to accept one Wave;
- the request is to fix code;
- product or technical planning is still actively changing.

## Inputs

### Required

- approved PRD;
- approved release boundary;
- approved Delivery Plan or equivalent delivery definition;
- repository implementation state;
- authoritative Wave-review evidence for all included Waves.

### Conditionally Required

When present:

- architecture overview and ADRs;
- approved TECHSPECs;
- Wave task indexes;
- task-review evidence;
- release/manual acceptance procedure;
- runtime/provider acceptance evidence.

### Optional

Load when necessary:

- `AGENTS.md`;
- README;
- validation/deployment/runtime configuration;
- previous final review;
- final-review remediation evidence.

## Authoritative Sources

Use this precedence unless explicitly overridden by an authorized user
instruction:

1. current explicit user instructions defining final-review release scope;
2. approved PRD;
3. approved Delivery Plan;
4. approved architecture/ADRs;
5. approved TECHSPECs;
6. authoritative accepted Wave-review artifacts;
7. approved task specifications;
8. repository constraints/conventions;
9. implementation and tests as delivery evidence.

A lower-level artifact cannot silently redefine approved upstream scope.

Wave-level `PASS` is required evidence but does not guarantee release-level
acceptance. Cross-Wave integration and complete release traceability must still
be verified.

## Preconditions

Before beginning final acceptance:

- [ ] release boundary is explicit;
- [ ] every included Wave is identified;
- [ ] every included Wave has authoritative Wave-review `PASS`;
- [ ] required approved specification artifacts are available;
- [ ] repository state represents the release being reviewed;
- [ ] no intentionally incomplete scope is presented as complete.

If any included Wave lacks authoritative `PASS`, report `BLOCKED`.

Do not use final review to perform missing Wave acceptance.

If approved artifacts materially contradict each other, report
`SPEC_CHANGE_REQUIRED`.

## Workflow

### 1. Establish the release boundary

Record:

- release identifier/name when present;
- included requirements;
- included Waves/scopes;
- explicitly deferred Waves/requirements;
- non-goals;
- applicable global constraints.

Do not fail approved deferred work outside the release boundary.

### 2. Verify Wave acceptance evidence

For every included Wave:

- locate the authoritative `WAVE-REVIEW.md` or equivalent;
- verify its current result is `PASS`;
- verify the artifact corresponds to the implementation state represented by the
  release;
- detect contradictory or stale Wave acceptance evidence.

If Wave acceptance evidence is missing, stale, contradictory, or not `PASS`,
report ownership `WAVE_REVIEW_REQUIRED`.

Do not perform the Wave review yourself.

### 3. Build release traceability

Trace applicable requirements through the accepted delivery:

`Requirement → Delivery Scope/Wave → TECHSPEC → Accepted Wave Evidence → Implementation → Release Validation`

Flag:

- approved requirement with no delivered Wave;
- requirement split across Waves but not integrated;
- cross-Wave contract not realized;
- implementation with no approved source;
- critical behavior with no release-level validation evidence.

### 4. Verify delivery-plan completion

Confirm:

- every included Wave reached its approved demonstrable outcome;
- dependencies between included Waves are satisfied;
- no required release behavior exists only in future/deferred scope;
- Wave boundaries compose into the approved release.

### 5. Audit requirements completeness

Classify each applicable PRD requirement:

`DELIVERED`
`PARTIAL`
`MISSING`
`DEFERRED`
`NOT_VERIFIABLE`

Do not infer delivery solely from task or Wave names.

### 6. Audit cross-Wave and release integration

Focus on concerns that cannot be fully proven by a single Wave review:

- shared contracts;
- state transitions across Waves;
- persistence compatibility;
- provider/runtime boundaries;
- configuration consistency;
- event/observability continuity;
- Git/PR/delivery boundaries;
- safety/failure behavior;
- release packaging/startup behavior.

### 7. Audit implementation drift

Identify material behavior that:

- exceeds approved release scope;
- contradicts approved decisions;
- implements deferred/future scope;
- changes public or provider contracts without approval;
- creates security/operational incompatibility.

### 8. Run release-level deterministic validation

Run the broadest repository-native checks needed for final acceptance.

Examples:

- full test suite;
- integration suite;
- release end-to-end tests;
- lint/type checking;
- build/import/compile;
- packaging/install checks;
- migration/database checks;
- established security/static analysis;
- runtime smoke tests.

Never claim a check passed unless executed.

### 9. Validate the complete release flow

Validate the primary complete approved product flow.

This should be broader than any single Wave outcome.

If required live/manual release acceptance is documented, execute or verify its
persisted evidence.

Classify missing executable evidence as `MANUAL_VALIDATION_REQUIRED`.

Classify unavailable external tooling/infrastructure/credentials as
`ENVIRONMENT_BLOCKED`.

### 10. Review release documentation

Verify documentation necessary to run, evaluate, operate, or hand off the
complete release.

Check when applicable:

- README;
- installation/setup;
- environment variables;
- runtime prerequisites;
- provider authentication;
- CLI examples;
- operational limitations;
- release/manual acceptance.

### 11. Classify findings

Severity:

`CRITICAL`
- severe security, data-loss, correctness, or release-level acceptance failure.

`HIGH`
- major approved requirement missing;
- primary release flow broken;
- required Wave not accepted;
- significant architecture/cross-Wave integration violation;
- required release validation failure.

`MEDIUM`
- material integration, validation, documentation, maintainability, or quality
  problem that should be resolved before final acceptance.

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

### 12. Determine remediation ownership

Use one primary ownership value:

`RELEASE_FIX`

The approved release specification is correct and an implementation,
integration, test, configuration, or non-approved documentation correction is
required at release scope.

`WAVE_REVIEW_REQUIRED`

An included Wave lacks current authoritative acceptance evidence or its evidence
is contradictory/stale.

`NEW_WAVE_OR_TASK_REQUIRED`

Approved release scope contains required implementation work that was not
represented in the approved delivery decomposition.

`MANUAL_VALIDATION_REQUIRED`

Required release acceptance evidence must be produced by executing an approved
manual/live validation.

`ENVIRONMENT_BLOCKED`

External tooling, credentials, infrastructure, sandboxing, runtime availability,
or local environment prevents required release validation.

`SPEC_CHANGE_REQUIRED`

Approved PRD, Delivery Plan, Architecture, or TECHSPEC must change before valid
release acceptance.

The final review identifies remediation ownership but does not perform
remediation.

### 13. Determine final outcome

Return `PASS` only when:

- all applicable approved requirements are delivered;
- all included Waves have authoritative `PASS`;
- release-level deterministic validation passes;
- required live/manual acceptance evidence exists;
- primary integrated release behavior is validated;
- no `CRITICAL`, `HIGH`, or `MEDIUM` blocking finding remains;
- no material undocumented scope drift remains.

Return `FIX_REQUIRED` when one or more blocking release-level defects can be
corrected without changing approved upstream specifications.

Return `SPEC_CHANGE_REQUIRED` when acceptance requires changing approved
product, delivery, architecture, or technical specifications.

Return `BLOCKED` when reliable release acceptance cannot be completed.

### 14. Persist the final review

The final review MUST be persisted.

Default artifact:

`reviews/FINAL-REVIEW.md`

If an explicit repository convention defines another release-review path, use
that convention and report it.

The persisted artifact is the authoritative final-review record.

Do not leave findings only in console output.

On re-review, update or supersede the authoritative artifact so the current
release acceptance state is unambiguous.

## Rules

### MUST

- review the complete approved release boundary;
- require accepted Wave evidence for every included Wave;
- verify missing implementation and scope drift;
- maintain requirement-to-release-evidence traceability;
- run applicable release-level validation;
- validate complete integrated behavior;
- classify remediation ownership;
- persist the authoritative final-review artifact;
- base acceptance on current evidence;
- stop after producing the final-review result.

### MUST NOT

- modify production code;
- modify tests to make validation pass;
- silently fix findings;
- run `wave-review`;
- run `review-task`;
- run remediation skills;
- change approved specifications;
- create tasks or Waves automatically;
- accept an included Wave lacking authoritative `PASS`;
- use final review as a substitute for Wave review;
- claim validation passed when it was not executed;
- automatically invoke another workflow stage.

### SHOULD

- use accepted Wave evidence to reduce redundant deep inspection;
- focus deeper inspection on release integration and cross-Wave behavior;
- distinguish missing validation from environment failure;
- keep findings actionable and non-duplicative;
- keep final acceptance evidence understandable without chat history.

## Output

Persist:

```markdown
## Final Review Result

<PASS | FIX_REQUIRED | SPEC_CHANGE_REQUIRED | BLOCKED>

## Release Scope

- Release: <identifier/name if present>
- Delivery mode: <SINGLE | WAVES>
- Included scopes: <scope(s)>
- Deferred scopes: <if any>

## Wave Acceptance Summary

| Wave | Review Artifact | Result | Evidence Status |
|---|---|---|---|
| ... | ... | PASS / ... | CURRENT / STALE / MISSING / CONTRADICTORY |

## Traceability Summary

| Requirement | Delivery Scope | Evidence | Status |
|---|---|---|---|
| FR-001 | ... | ... | DELIVERED / PARTIAL / MISSING / DEFERRED / NOT_VERIFIABLE |

## Release Validation

| Check | Result | Evidence |
|---|---|---|
| `<command or check>` | PASS / FAIL / NOT RUN | <concise evidence> |

## End-to-End Validation

- <release flow> — PASS / FAIL / NOT RUN — <evidence>

## Findings

### FINAL-001 — <Severity> — <Title>

- Category: <Requirements | Integration | Architecture | Validation | Documentation | Scope Drift | Security | Wave Evidence | Environment | Other>
- Ownership: <RELEASE_FIX | WAVE_REVIEW_REQUIRED | NEW_WAVE_OR_TASK_REQUIRED | MANUAL_VALIDATION_REQUIRED | ENVIRONMENT_BLOCKED | SPEC_CHANGE_REQUIRED>
- Requirement/Scope: <identifier when applicable>
- Location: `<path:symbol-or-line>` or artifact
- Issue: <what is wrong>
- Evidence: <concrete evidence>
- Expected: <approved expected state>
- Remediation direction: <concise guidance>

## Blocking Conditions

- <blocking conditions, or `None.`>

## Non-Blocking Notes

- <optional LOW findings or release observations>

## Summary

<concise release acceptance rationale>
```

For `PASS`, Findings may be omitted if none exist.

After persisting the artifact, console output must contain only:

1. final-review status;
2. authoritative artifact path;
3. number of blocking findings;
4. recommended next workflow action.

## Completion

A final `PASS` means the complete approved release is accepted. It is distinct
from delivery authorization and final workflow completion. The deterministic
orchestrator-owned commit, push, and PR actions may occur only after a separate
explicit persisted delivery authorization.

Do not automatically commit, push, open a PR, deploy, or invoke another workflow
stage unless that separate authorized orchestrator step explicitly requests it.
