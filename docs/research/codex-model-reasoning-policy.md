# Codex Model and Reasoning Policy

**Date:** 2026-09-05  
**Scope:** Analysis and recommendation only. This document does not change Codex
configuration, repository Skills, source code, workflow contracts, approvals, or
authoritative review outcomes.  
**Recommendation:** **EXPERIMENT_FIRST** — adopt the routing rules as an
instrumented pilot, not as an unmeasured global configuration change.

## 1. Current Codex configuration relevant to the decision

### Observed local configuration and controls

The current local Codex CLI is `codex-cli 0.153.4`. Its active user
configuration sets:

```toml
model = "gpt-5.6-terra"
model_reasoning_effort = "high"
```

The repository path is trusted. No repository-specific model or reasoning
profile was found. Consequently, every activity — including `git status`, a
bounded search, and a release audit — currently starts with the same balanced
model at `high` reasoning. This is a safe baseline, but it spends the same
reasoning latency on work with very different failure modes.

The installed CLI supports one-invocation `--model` overrides and configuration
overrides (`-c key=value`), plus named profile layering (`-p`). Its local model
catalog exposes the following usable model/reasoning combinations:

| Model | Catalog description | Supported reasoning efforts |
| --- | --- | --- |
| `gpt-6-astra` | Most capable model for complex, demanding work | low, medium, high, xhigh, max, ultra |
| `gpt-5.6-sol` | Reliable everyday agentic workhorse | low, medium, high, xhigh, max, ultra |
| `gpt-5.6-terra` | Balanced everyday agentic coding model | low, medium, high, xhigh, max, ultra |
| `gpt-5.6-luna` | Fast, affordable agentic coding model | low, medium, high, xhigh, max |
| `gpt-5.5` | Proven prior-generation coding/general model | low, medium, high, xhigh |
| `gpt-5.4-mini` | Small, fast model for simpler coding tasks | low, medium, high, xhigh |

The catalog also contains `gpt-reserve` and `codex-auto-review`; neither is a
recommended Engineering Flow role selection. The latter is an automatic
approval-review model, not evidence that it is suitable for independent
engineering acceptance. The CLI catalog and its model availability are local
observations, not a promise that each selection has identical account access,
price, latency, context window, or quota treatment.

`codex exec` also supports `--output-schema`, `--output-last-message`, JSONL
events, `read-only` and `workspace-write` sandboxes. Engineering Flow already
uses those provider capabilities to separate Developer and Reviewer execution.
Those role and sandbox boundaries are independent of a reasoning setting.

### Repository evidence that constrains the policy

`AGENTS.md` requires the Linux `.venv/bin/python3`, an initial readiness
check, targeted context reads, and the tracked full suite. It also delegates
workflow process authority to the repository-local Skills. The twelve Skills
make the lifecycle deliberately non-interchangeable: planning artifacts,
one-task implementation, task review, task repair, Wave audit/repair, and
release audit/repair each have different inputs, mutation rights, outputs, and
stop conditions.

The approved delivery plan and architecture make this unusually consequential:
the product is a provider-neutral, persisted control plane with distinct task,
Wave, release, authorization, delivery, and completion facts. The current and
next delivery work crosses state, SQLite persistence, structured provider
output, session/recovery, capability mapping, safety, and eventually Git/PR
boundaries. A reasoning policy therefore must route by *risk and scope*, not by
whether the task happens to be called “documentation” or “code.”

Wave evidence supports this distinction. Wave 1 needed a Wave-level fix for
terminal-event failure classification. Wave 2 needed Wave remediation when a
live Developer emitted duplicate exact-test evidence and when strict provider
JSON Schema handling exposed nullable-location incompatibility. Wave 2's
accepted evidence includes ordered task execution, fresh Reviewer sessions,
real `FIX_REQUIRED` → same-Developer repair → fresh review, restart recovery,
and review-limit intervention. These were not simple syntax failures; they are
examples of subtle boundary, evidence, and live-runtime failures that a lower
tier must be escalated away from.

### Evidence limits

The current baseline has passed the documented Wave work at high reasoning. No
paired run in this repository compares model/reasoning tiers on the same
contracts. Thus “lowest safe” below means the lowest **provisional routing
tier** that preserves the required process and has an explicit escalation path;
it is not a demonstrated model-quality guarantee. The experiment in section 11
is required before changing a global default or treating the matrix as a hard
automation policy.

## 2. Workload categories observed in the repository

| Category | Observed work | Dominant failure mode | Typical context |
| --- | --- | --- | --- |
| Deterministic operations | preflight, status, exact test/compile commands, bounded searches | wrong command/interpreter or misreported result | command plus a small local file set |
| Repository reconnaissance | locate an artifact, inspect a focused diff, trace a symbol | missing the relevant source or authority | low to moderate; should be targeted |
| Product and delivery decisions | PRD, delivery mode/Wave boundaries, global architecture | ambiguity or scope leakage becomes an approved upstream defect | PRD/vision, plan, architecture, selected evidence |
| Technical specification and task design | TECHSPEC, task contracts, validation strategy | underspecified interfaces, incorrect boundaries, untestable work | selected approved artifacts plus affected implementation/tests |
| Bounded engineering change | one approved task or a review-directed repair | edge cases across orchestration, persistence, runtime, and tests | selected task/review plus affected modules and tests |
| Independent acceptance | task, Wave, and final reviews | confirmation bias, missed traceability/evidence conflict, incorrect PASS | contract plus implementation, diff, tests, and prior evidence |
| Scope-bound remediation | task/Wave/final fixes | fixing the symptom while violating the approved boundary or treating repair as acceptance | authoritative findings plus the minimal affected contract/code |

The context-efficiency analysis estimates a selected local Skill at about
2.1k–4.6k proxy tokens before authoritative artifacts or source. It also shows
that moving a required instruction to another file does not reduce the context
of a path that still loads it. Therefore a lower reasoning tier must not be
used as an excuse to omit the selected Skill, task contract, review evidence,
or required source/test context.

## 3. Reasoning/risk classification

This policy scores an invocation before it starts. It does not use number of
files alone as a proxy for difficulty.

| Class | Reasoning complexity | Subtle-correctness risk | Context pattern | Stronger-reasoning value |
| --- | --- | --- | --- | --- |
| R0 — deterministic | mechanical interpretation of an exact command/result | low if output is preserved accurately | one command or one known artifact | little; explicit command/result checks matter more |
| R1 — bounded local | straightforward inspection or an isolated, well-specified edit | low to moderate | one contract and a few directly affected files | useful for ambiguity detection, but not continuously high |
| R2 — engineering | multi-step design or implementation inside an approved boundary | moderate to high | selected Skill plus multiple related artifacts/modules/tests | material; catches integration and state/evidence interactions |
| R3 — acceptance/architecture | cross-boundary decisions or independent acceptance | high; a false PASS or wrong architecture is expensive | several authoritative layers, diff/evidence, and cross-module behavior | essential; synthesis, contradiction detection, and adversarial checking dominate |

An activity begins at the lowest tier that fits R0–R3. Any objective escalation
trigger moves it upward before a conclusion or mutation. This avoids a false
choice between “always fast” and “always high.”

## 4. Recommended minimal tier model

Use three named operational tiers. They are intentionally policy labels rather
than new domain capabilities, Skills, workflow states, or user-account plans.

| Tier | Provisional Codex mapping if later configured | Use | Boundaries |
| --- | --- | --- | --- |
| **FAST** | `gpt-5.6-terra` at `low`; only after the pilot may a bounded R0 workload trial `gpt-5.6-luna` at `low` | R0 deterministic operations and narrow, read-only inspection | never makes approval, acceptance, architecture, or substantive review decisions |
| **STANDARD** | `gpt-5.6-terra` at `medium` | routine R1/R2 planning, decomposition, implementation, and scoped repair | selected Skill and authoritative contract still load in full; escalation is mandatory when triggered |
| **DEEP** | `gpt-5.6-terra` at `high` | R3 architecture/acceptance and high-risk R2 work | default for review/acceptance; retain current model family to isolate reasoning as the first variable |

`gpt-6-astra` at `high` or above is an **exceptional escalation**, not a fourth
normal tier. Consider it only after DEEP has insufficiently resolved a
cross-cutting issue, two valid approaches remain materially uncertain, or a
release/safety decision needs a second deep analysis. It should be recorded as
a model escalation, not silently substituted for the policy. `xhigh`, `max`,
and `ultra` are not justified merely by a long prompt, large diff, or a request
to “be careful”; those characteristics first require decomposition and bounded
context.

The proposed everyday default is **STANDARD (`gpt-5.6-terra`, medium)**. FAST
is an opt-in classification for deterministic work, while DEEP is the default
for the designated review/acceptance roles. This is deliberately more
conservative than changing the whole repository to a fast model.

## 5. Activity-to-tier matrix

“Lowest provisional tier” is the normal minimum after initial triage, not an
assertion that a lower model could never succeed. “Lower default + escalation”
means STANDARD or FAST is selected initially only with the listed objective
checks; it never permits bypassing a required review.

| Activity | Complexity / subtle-risk | Typical repository context | Value of stronger reasoning | Lowest provisional tier and default | Lower default + escalation? | Independent reviewer stronger than implementer? |
| --- | --- | --- | --- | --- | --- |
| PRD creation | R2; ambiguity and requirement traceability can poison all later artifacts | vision/brief, current PRD, relevant constraints | high for conflicts, non-goals, measurable acceptance | STANDARD default | Yes; DEEP for ambiguity/conflict, regulated/safety impact, or cross-product dependency | n/a |
| Delivery planning | R2–R3; wrong Wave boundary or dependency leaks scope | approved PRD, current plan, architecture, accepted evidence | high for sequencing, capability ownership, and deferred scope | STANDARD default | Yes; DEEP for cross-Wave change, altered acceptance/authorization, or delivery side effects | n/a |
| Architecture overview | R3; global decisions constrain all Waves | PRD, delivery plan, existing architecture, relevant source/runtime boundaries | essential | DEEP default | No routine lower default; STANDARD only for a narrowly bounded, non-cross-cutting update after explicit triage | n/a |
| TECHSPEC creation | R2; contracts, error behavior, validation, and context surface can be subtly wrong | selected scope, approved PRD/plan, architecture, affected code/tests | high where persistence/runtime/compatibility is involved | STANDARD default | Yes; DEEP for a new global decision, state/persistence/concurrency, provider boundary, migration, security, or substantial multi-module design | n/a |
| Task decomposition | R2; incorrect dependency/order/acceptance context causes downstream rework | approved TECHSPEC, scope authorization, architecture constraints | material for vertical slicing and exact acceptance/validation | STANDARD default | Yes; DEEP for a task touching multiple ownership boundaries, unclear dependencies, or an excessive context surface | n/a |
| Task implementation | R1–R2; well-bounded changes are routine, but integration defects are costly | selected task, immediate source/tests, approved TECHSPEC sections | material for stateful and cross-module behavior | STANDARD default | Yes; DEEP on any R3 trigger or after a failed first diagnosis | **Yes:** review normally uses DEEP even when implementation is STANDARD |
| Task review | R2–R3; false PASS and self-confirmation are high-risk | task contract, TECHSPEC constraints, diff/current code, tests, current evidence | essential for adversarial traceability and missed edge cases | DEEP default | No for acceptance decision; FAST/STANDARD may assist mechanical evidence inventory only, not decide PASS | **Yes — mandatory DEEP for the independent final judgment** |
| Task fix | R1–R2; must repair only authoritative findings without widening scope | reviewed task, findings, affected code/tests | material when root cause differs from stated symptom | STANDARD default | Yes; DEEP for repeat finding, multiple failed attempts, cross-module/state/provider effect, or finding ambiguity | Re-review returns to DEEP |
| Wave review | R3; verifies task evidence, integration, manual acceptance, and Wave boundary | Wave TECHSPEC/manual acceptance, all task records/reviews, implementation/tests, remediation evidence | essential | DEEP default | No; use FAST only for preparatory indexing, never the outcome | n/a; the role itself is independent DEEP |
| Wave remediation | R2–R3; fixes can blur Wave/release ownership or invalidate acceptance evidence | authoritative Wave review, approved Wave scope, affected code/evidence | high for routing and integration findings | STANDARD default | Yes; DEEP for cross-task/system behavior, manual/live validation failure, provider/runtime/state changes, or a disputed finding | Subsequent Wave re-review remains DEEP and independent |
| Final review | R3; release traceability and false release acceptance have the greatest process cost | PRD through all approved scopes, Wave PASS records, implementation, validations, release behavior | essential | DEEP default | No; helper inventory may be FAST, but authoritative verdict remains DEEP | n/a; independent acceptance is intrinsic |
| Final remediation | R2–R3; must preserve accepted Wave boundaries while resolving release blocker | authoritative final review, relevant accepted-Wave evidence, affected code/validation | high for cross-Wave, delivery, and release-risk fixes | STANDARD default | Yes; DEEP for any delivery/auth/security, cross-Wave, repeated, or uncertain root cause | A new final review remains DEEP and independent |
| Simple repository inspection | R0–R1; risk is missing a file or overstating a result | known path, bounded search/diff/status | low | FAST default | Yes; STANDARD if results span more than one ownership boundary or are used to support a decision | n/a |
| Deterministic validation/status/preflight | R0; risk is incorrect invocation, environment mismatch, or false report | exact command and concise output | low | FAST default | Yes; STANDARD if a command fails unexpectedly or output must be diagnosed; DEEP only if failure indicates a high-risk boundary | n/a |

The Wave 2 work should be classified above its labels: a `codex_cli.py` schema
compatibility correction, duplicate exact-test evidence, live review-limit
path, orchestrator recovery, or task acceptance routing is not a “simple fix.”
Those are immediate DEEP triggers for implementation/remediation and always
DEEP for the resulting review.

## 6. Escalation triggers

Escalate before writing an authoritative decision or making the corresponding
edit. Triggers are cumulative: one critical trigger goes directly to DEEP;
several moderate triggers do too.

### Escalate FAST to STANDARD

- The command/result is not exact, exits non-zero, uses an unexpected Python,
  venv, worktree, branch, or provider capability, or produces ambiguous output.
- Inspection expands from a known artifact to two or more modules or an
  upstream authority question.
- The result will be used to justify a design, review verdict, or mutation
  rather than merely report status.

### Escalate STANDARD to DEEP

- A requirement, approved artifact, test, implementation, or review record is
  ambiguous, internally conflicting, stale, or has unclear authority.
- The work changes or interprets a cross-cutting architecture decision, Wave
  boundary, acceptance/authorization lifecycle, compatibility rule, or
  capability/Skill/role/provider distinction.
- The change spans multiple modules with behavior coupling, especially
  orchestrator, store, domain, runtime adapter, CLI, configuration, or tests.
- It affects concurrency, state machines, persistence, migrations,
  idempotency, resume/recovery, retries, event ordering, or evidence hashes.
- It affects provider/runtime contracts, JSON schema/output parsing, sandbox or
  permission behavior, command execution, worktree validation, credentials,
  secret handling, logging/redaction, security, or safety controls.
- It can create a commit, push, PR, external request, delivery state, or any
  irreversible/reconciliation obligation.
- A focused test fails unexpectedly; the root cause is not local and obvious;
  validation disagrees with the implementation claim; or a live/manual
  acceptance path fails.
- A first remediation attempt fails, the same finding recurs, two plausible
  root causes remain, or the review diff is large enough that the selected
  task contract cannot be checked locally.
- A review needs to decide PASS/FIX_REQUIRED, Wave PASS, release PASS, or
  whether a fix remains within the approved scope.

### Escalate DEEP to exceptional `gpt-6-astra` analysis

This is optional and should be rare. Use it for a recorded second opinion only
when DEEP analysis cannot resolve a genuine cross-Wave architecture conflict,
a security/safety-sensitive release decision, a provider/runtime incompatibility
with uncertain semantics, or repeated failed DEEP remediations. Do not use it
to make an already independent reviewer less independent, to compensate for
missing evidence, or to bypass a `BLOCKED`/`SPEC_CHANGE_REQUIRED` outcome.

## 7. Reviewer independence considerations

Reviewer independence is more than a separate prompt. The architecture and
Wave 2 TECHSPEC require fresh independent Reviewer sessions, a read-only
capability, and no provider authority to advance lifecycle state. The Skills
also prohibit review from fixing its own findings and remediation from claiming
acceptance. Keep all of those safeguards unchanged.

Deliberate tier asymmetry improves the chance of useful disagreement:

| Producer | Reviewer/auditor | Policy |
| --- | --- | --- |
| STANDARD implementation or task fix | DEEP task review | Required normal pairing. The reviewer sees the contract/diff/evidence afresh and has more reasoning headroom to look for omissions rather than reproduce the developer's path. |
| STANDARD task decomposition or TECHSPEC | Human approval plus DEEP downstream task/Wave review when applicable | Do not treat shared model family or a high setting as approval. Persisted approval and later independent checks remain decisive. |
| STANDARD Wave/final remediation | DEEP Wave/final re-review | Required. Remediation evidence says ready for review, not accepted. |
| DEEP implementation due to trigger | A fresh DEEP reviewer; use an exceptional model only if a documented second opinion is needed | Do not mirror hidden chain-of-thought, resume the implementer's reviewer context, or let it self-accept. Fresh session, read-only sandbox, contract-first review, and separated logical identity matter more than selecting a different brand of model. |

A different model is not automatically more independent: it can introduce
different blind spots and lower code comprehension. The default should hold
the model family constant (`gpt-5.6-terra`) while varying effort and session/
role boundaries. A targeted Astra second opinion is valuable only for a
recorded high-risk disagreement, not as a replacement for the required fresh
Reviewer or authoritative evidence chain.

## 8. Latency/productivity implications

The expected benefit is **less avoidable reasoning latency and faster
deterministic turnaround**, not a claim that harder work becomes cheap. FAST
should make status, preflight, exact validation, and tightly bounded inspection
more responsive. STANDARD should avoid paying `high` effort for ordinary,
well-specified task work. DEEP remains where rework or a false acceptance would
cost more than an additional reasoning delay.

The largest productivity protection comes from correct escalation, not choosing
FAST aggressively. The repository's full suite is fast (the current
environment preflight is ready, and prior Wave 2 evidence recorded 90 tests on
Python 3.13), so frequent deterministic validation is a better safety/latency
trade than long speculative reasoning. The workflow already minimizes costly
rework by persisting task contracts, findings, validation, and review records.

Expected pilot benefit: routine R0/R1 work should have lower wall-clock
latency and less agent over-analysis; R2/R3 correctness should remain at the
current baseline because they retain STANDARD/DEEP respectively. No numeric
speedup is claimed before measurement. A slower task that avoids one
review/fix/re-review loop may be the more productive route.

## 9. Token/context implications

Reasoning tier, selected model, and model-visible context are separate levers.
Lower reasoning does not make required artifacts disappear. The selected Skill
must still be read in full under the workspace protocol, and its local
authority/precedence, mutation rights, evidence schema, and stop rule remain
necessary. The task-specific context guidance in each Skill is therefore a
safety contract, not optional token trimming.

For all tiers:

- Start with the artifact hierarchy specified by `AGENTS.md` and the selected
  Skill; use `rg`, line-bounded reads, focused diffs, and focused tests before
  broad loading.
- Read only directly affected source and adjacent contracts until evidence is
  sufficient; do not indiscriminately load all docs, all tests, full history,
  or unrelated Waves.
- Keep raw long logs addressable outside the immediate decision context and
  return a bounded status summary; retrieve detail only to diagnose a failure.
- Do not extract or lazily omit Skill-local review, authority, or evidence
  rules merely to lower initial context. The skills-context analysis found
  near-zero end-to-end saving when required content is merely moved to a
  reference.

This policy may reduce wasted reasoning on the same context. It does not,
without separate instrumentation, establish a reduction in prompt tokens,
completion tokens, cached tokens, or total task tokens. Conversely, a lower
tier that causes re-reads, retries, weaker task decomposition, or additional
reviews can consume *more* context across the full lifecycle.

## 10. What can and cannot be claimed about quota savings

### Supportable claims

- The current global `high` setting applies deep reasoning to R0 deterministic
  work, so tier routing has a credible quality/latency optimization hypothesis.
- Targeted context reads and bounded command output can reduce the text placed
  into a model turn when agents would otherwise retrieve irrelevant material.
- Engineering Flow can retain provider usage metadata/events where supplied,
  so per-run measurement may be possible without inferring from prose alone.

### Claims that must not be made

- Do **not** claim that `low`/`medium` reasoning uses less ChatGPT or Codex
  quota, costs less, has a particular price, consumes fewer billing credits,
  or extends a usage limit. The inspected local CLI configuration and model
  catalog expose selection/effort, not account-specific quota accounting or
  billing semantics.
- Do **not** infer quota savings from shorter shell output, a smaller
  `SKILL.md`, fewer visible response words, lower elapsed time, or a model
  catalog description such as “fast” or “affordable.” Those measure different
  things, if they measure anything at all.
- Do **not** compare tiers by provider usage fields unless their schema,
  availability, and relationship to the user's plan are independently
  established for the same account and CLI version.

The correct separation is: (1) quality/latency is measured by success,
rework, verdict accuracy, and elapsed time; (2) context/token efficiency is
measured by retrieved/input/output/usage fields when available; (3) quota or
billing is unknown until an authoritative account-level source establishes its
mapping. A favorable result in (1) or (2) does not prove (3).

## 11. Suggested experiment/measurement plan

Run a reversible, no-configuration-change pilot using explicit per-invocation
selection or isolated profiles. Do not test a lower tier first on a final
review, a release delivery action, a security-sensitive change, or a live
provider/runtime boundary.

1. **Establish baseline.** Select completed, reproducible R0, R1, and R2
   cases from the existing tests/artifacts. For each, capture current
   `gpt-5.6-terra/high` outcome, wall time, agent turns, validation result,
   context artifacts read, tool-output bytes/lines, re-reads/retries, review
   result, and provider usage fields if present. Record unavailable fields as
   unavailable; never fabricate token data.
2. **Pilot FAST only on R0.** Compare Terra/low with the current baseline for
   `env-preflight`, exact deterministic validation/status reporting, and
   bounded known-file inspection. A later optional second comparison may use
   Luna/low, but keep the task, prompt, repo revision, command, sandbox, and
   required output schema fixed. Require exact command selection and factual
   PASS/FAIL reporting.
3. **Pilot STANDARD on bounded R1/R2.** Compare Terra/medium against
   Terra/high for one isolated task decomposition exercise and one small,
   non-stateful implementation or review-directed repair in a disposable
   worktree. Run the same deterministic validation and have a separate
   Terra/high Reviewer evaluate both outputs blind to tier.
4. **Retain DEEP control cases.** Exercise at least one simulated
   persistence/state, provider-schema, or review-limit scenario from the Wave
   2 regression suite. It should remain Terra/high. This confirms the policy
   does not silently downgrade the repository's demonstrated high-risk paths.
5. **Evaluate by role.** Score implementation and review separately. For
   review, measure missed seeded defects, invalid PASS/FIX_REQUIRED verdicts,
   false scope-expansion claims, traceability omissions, and whether a review
   independently identifies defects. Do not average a faster developer turn
   with a weaker reviewer result.
6. **Adoption thresholds.** Promote FAST/ STANDARD only if they have no
   validation regression, no incorrect authoritative outcome, no increased
   review/fix cycle count, and a meaningful median latency or total-turn
   improvement across at least five representative runs per class. Keep DEEP
   for acceptance. Any single false PASS, missed blocking finding, scope
   violation, or high-risk escalation miss rejects that class's downgrade and
   returns it to DEEP/its prior tier pending investigation.
7. **Document scope.** Persist only a concise experiment record: exact model
   and effort, repository revision, task class, escalation decision, metrics,
   validation/review result, and caveats. Do not use hidden reasoning text as
   a metric and do not alter approval/review records merely for the experiment.

The first decision after the pilot is narrow: adopt FAST for R0 and STANDARD
for eligible R1/R2 only if the thresholds pass. The policy does not need an
account-wide configuration change to be useful; a role launcher/profile mapping
can be considered later, separately, after evidence.

## 12. What must NOT change

- Do not change `~/.codex/config.toml`, a Codex profile, project trust,
  sandbox/approval settings, model selection, CLI version, or provider
  capability in response to this analysis.
- Do not change `AGENTS.md`, repository-local Skills, the PRD, Delivery Plan,
  architecture, TECHSPECs, task contracts, review/remediation artifacts, or
  workflow contracts to encode this policy now.
- Do not conflate a policy tier with a domain capability, Codex Skill, agent
  role, provider/runtime, approval, acceptance, authorization, or lifecycle
  state.
- Do not weaken selected-Skill loading, source precedence, scoped context,
  deterministic validation, durable evidence, human approval, or the
  Developer/Reviewer/Fixer/auditor separation to obtain speed.
- Do not let FAST or STANDARD issue task/Wave/release acceptance, make a
  reviewer repair its own finding, make remediation evidence acceptance
  evidence, or allow provider output to advance orchestration state.
- Do not assume model selection changes billing/quota, and do not report it as
  a saving absent authoritative account-level evidence.

## 13. Recommendation

**EXPERIMENT_FIRST.** Keep the present `gpt-5.6-terra/high` configuration
unchanged. Use the three-tier policy as a documented, per-invocation pilot:

- **FAST:** Terra/low for deterministic validation, status/preflight, and
  tightly bounded inspection only.
- **STANDARD (proposed everyday default):** Terra/medium for eligible PRD,
  delivery planning, TECHSPEC/task design, task implementation, and scoped
  remediation.
- **DEEP:** Terra/high for architecture overview, task/Wave/final review,
  final review, and every triggered high-risk design, implementation, or
  remediation path.

This is the smallest practical tier model compatible with current evidence.
It should reduce avoidable latency for routine work while preserving the
repository's strongest control: an independent, fresh, read-only DEEP review
before acceptance. The blocker to adoption is measurement, not a missing CLI
setting: this repository has no controlled evidence yet that lower tiers retain
the current high-reasoning correctness and review quality on representative
Engineering Flow work.
