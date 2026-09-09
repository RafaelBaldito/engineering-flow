# Technical Specification — Wave 3: Workflow Capability Orchestration

## 1. Scope

Wave 3 makes the approved canonical lifecycle executable under Engineering
Flow control. It introduces provider-neutral capability selection and durable
governance facts for planning, acceptance, authorization, and remediation.
It builds on Wave 1's historical planning records and Wave 2's task-level
runtime/evidence interface.

This Wave does not reimplement Wave 2 task execution, test gating, review, or
fix limits. It does not stage, commit, push, create a Pull Request, or merge;
those external delivery responsibilities remain Wave 4.

## 2. Requirements Traceability

| Area | Wave 3 outcome |
| --- | --- |
| FR-001–005 | Canonical stage progression, conditional architecture routing, and stage-scoped capability requests. |
| FR-006–010, FR-033–035 | Durable approval, acceptance, authorization, actor/audit, and remediation-routing facts. |
| FR-017–021 | Provider-neutral domain capabilities resolved to the sole configured Codex runtime without domain coupling to Skills. |
| FR-022–025, FR-030–032 | Versioned persistence, recovery/idempotency, CLI/status, and correlated lifecycle events. |

## 3. Current-State and Compatibility

The existing planning and task-loop records remain valid only according to
their recorded lifecycle contract. Wave 3 adds a canonical lifecycle version;
it must read historical records without inferring absent delivery-plan,
architecture, authorization, or acceptance facts. New canonical workflows use
explicit versioned records and migrate only by an idempotent, auditable
compatibility operation. A failed, partial, or ambiguous migration leaves the
historical record intact and pauses for human attention.

Wave 2 remains the authority for task-local selection, required-test evidence,
independent Reviewer PASS, and bounded fix/re-review. Wave 3 consumes its
accepted-task evidence as input to Wave review; it does not reinterpret a task
plan's initial `PENDING` cells as runtime acceptance.

## 4. Canonical Lifecycle and Capability Resolution

The orchestrator alone evaluates policy and transitions:

```text
Workflow Stage -> Required Domain Capability -> Capability Resolution
               -> AgentRuntime / Provider -> provider-specific mechanism
```

`DomainCapability` is a stable identifier plus schema/version and required
outcome contract. It is not a Skill path/name, role, provider, model, session,
or prompt. `AgentRole` is the bounded responsibility requested by the stage;
`AgentRuntime`/provider executes that request; the adapter chooses its native
mechanism.

The registry defines canonical capabilities for PRD, delivery planning,
architecture overview, TECHSPEC, task planning, task execution/review/fix,
Wave review/remediation, final review/remediation, and delivery preparation.
Each definition declares supported lifecycle versions, role, input/output
schemas, evidence requirements, and whether human policy precedes or follows
the capability. Resolution receives the workflow lifecycle version, stage,
configured provider/runtime, repository constraints, and capability ID. It
must either return one compatible binding or a structured unsupported/invalid
outcome; no provider fallback or autonomous routing is introduced.

For Codex, a binding records an adapter-local mechanism descriptor: either a
repository Skill reference or a bounded prompt/template reference, its
adapter-controlled version/digest, and the normalized contract version it
satisfies. The adapter verifies declared equivalence before dispatch: same
capability ID, compatible schema/version, role constraints, required inputs,
and required output/evidence semantics. Provider-specific names and paths stay
in adapter configuration/execution metadata, never in canonical capability or
lifecycle records. A mismatch is non-dispatchable and routes to human
attention.

## 5. Governance Records and State Rules

Persist immutable, append-only decision/evidence records linked to workflow,
scope (release/Wave/task), lifecycle version, operation ID, and predecessor
facts. Decision types are approval, rejection, Wave acceptance, release
acceptance, Wave-start authorization, delivery authorization, revocation, and
supersession. Each carries decision/status, identifiable actor, timestamp,
exact scope, authoritative artifact/evidence references with hashes, and
affected decision IDs where applicable. No external identity technology is
selected in this Wave.

An authorization/acceptance is active only if its evidence validates, scope
matches, it has not been revoked, and no later valid supersession applies.
Revocation and supersession are explicit records; they never delete history.
They must atomically invalidate only downstream actions dependent on the
affected fact, retain completed evidence, emit an audit event, and require
fresh authority before redispatch. Conflicts, duplicate active authorities, or
uncertain ordering pause for human attention.

Stage advancement validates the required active governance fact and structured
capability result in one transaction. Provider output is evidence, never an
instruction to advance. Wave review PASS is required for Wave acceptance;
accepted included Waves gate final review; final-review PASS gates release
acceptance; release acceptance plus an active delivery authorization is only a
precondition consumed later by Wave 4.

## 6. Remediation Routing

Structured review results carry a decision, blocking findings, scope, evidence
references, and operation identity. Task `FIX_REQUIRED` stays on the Wave 2
task-local route. Wave review or final review `FIX_REQUIRED` is evaluated by a
deterministic routing policy: route to an eligible owning prior scope only
when finding ownership and required authority are unambiguous; otherwise enter
human attention. A remediation result invalidates the affected acceptance and
causes the applicable review to be repeated. Routing cannot silently reopen a
future Wave, manufacture authorization, or bypass a human gate.

## 7. Persistence, Events, CLI, and Idempotency

Add versioned persistence entities for capability definitions/bindings,
capability requests/results, lifecycle state, decision records, actor/audit
metadata, remediation routes, and migration receipts. Store immutable evidence
references/hashes; retain provider-native metadata only in sanitized adapter
execution records. Existing persistence remains readable through its recorded
version.

Every lifecycle recording or provider dispatch has a durable operation key and
request fingerprint. Repeated identical requests return the recorded result;
same key with different input rejects; uncertain external outcomes reconcile
to known evidence or human attention. Transactions atomically persist state,
decision/result, and correlated event.

Extend the CLI as thin clients for status/log inspection and authorized
approve, reject, authorize, revoke, supersede, resume, and intervention
commands. Commands identify the target scope and evidence; they do not accept
free-form agent prose as authority. Emit provider-neutral workflow, stage,
capability, decision, authorization, acceptance, remediation, session,
execution, test, and review events. Status/log projections expose authoritative
facts and sanitized correlation IDs, never secrets or provider-only control
data.

## 8. Components and Responsibilities

| Component | Responsibility |
| --- | --- |
| Orchestration core | Lifecycle policy, capability requirement/resolution, transition validation, gates, and remediation routing. |
| Capability registry/resolver | Versioned domain contracts and compatible runtime binding selection. |
| Codex adapter | Mechanism mapping/equivalence checks, native execution, and normalized evidence translation. |
| Persistence/store | Atomic lifecycle, governance, evidence, migration, idempotency, and event facts. |
| CLI | Validated command input and authoritative status/log presentation. |

## 9. Error Handling and Safety

Missing/invalid evidence, incompatible lifecycle/capability versions,
unavailable permissions, invalid state transitions, conflicting authorities,
unknown execution outcome, or ambiguous remediation ownership must not advance
the lifecycle. They produce a classified event and `HUMAN_ATTENTION` with the
required human action. Maintain repository/workspace, timeout/retry, secret
sanitization, and independent-review controls already owned by their relevant
layers.

## 10. Validation Strategy

- Unit-test capability schema validation, resolver compatibility, Codex
  Skill/prompt equivalence rejection, and separation of capability/role/runtime.
- Test lifecycle transitions, conditional architecture routing, historical
  read compatibility, and migration idempotency/rollback behavior.
- Test actor/audit completeness; revocation/supersession precedence; exact
  scope/evidence hashing; and that missing facts are never inferred.
- Integration-test Wave 2 evidence consumption, Wave/release review
  remediation routing, resume/reconciliation, duplicate-operation protection,
  CLI/event correlation, and human-attention failures.
- Regression-test that no Wave 4 Git/hosting side effect is callable from this
  Wave and that a delivery authorization record alone has no side effect.

## 11. Risks, Assumptions, and Boundaries

The exact storage schema and migration mechanics must fit the repository's
existing SQLite/WAL conventions; implementation must inspect those seams before
choosing table-level details. Codex mechanism equivalence is contractual, not
semantic proof of identical model output. V1 continues to use one configured
Codex provider and no fallback.

This TECHSPEC deliberately contains no task decomposition. Downstream tasks
should be bounded around registry/contracts, governance persistence, lifecycle
routing, adapter mapping, and CLI/events, using the named sections rather than
loading unrelated Wave documentation.
