# Repository-Local Skills: Context-Efficiency Analysis

## Scope and method

This is an analysis of the twelve repository-local Skills under
`.codex/skills/` as they exist on 2026-09-05. It does not propose a product or
Wave 3 redesign. `AGENTS.md`, the approved delivery plan, and the architecture
overview were read only to distinguish repository-global rules from Skill
process authority.

Sizes below use `wc`; the token estimate is a tokenizer-independent
characters/4 proxy, not a claim about an exact model tokenizer. The current
Codex protocol is material to the result: a selected Skill's complete
`SKILL.md` is loaded before it is used. A file that the Skill says is required
must also be loaded. Thus, the whole corpus is not normally injected for one
invocation: the active cost is the selected Skill (about 2.1k--4.6k proxy
tokens), plus applicable repository context. Moving text to an always-required
reference changes its location, not the model-visible instruction budget.

## 1. Current Skill inventory and approximate size

| Skill | Lines | Words | Bytes | Approx. tokens (bytes/4) |
| --- | ---: | ---: | ---: | ---: |
| create-architecture-overview | 506 | 1,665 | 12,501 | 3,125 |
| create-prd | 442 | 1,726 | 12,886 | 3,222 |
| create-tasks | 627 | 2,495 | 18,301 | 4,575 |
| create-techspec | 541 | 2,275 | 17,104 | 4,276 |
| execute-task | 564 | 2,353 | 17,402 | 4,351 |
| final-review | 497 | 1,920 | 14,388 | 3,597 |
| fix-final-review | 322 | 1,088 | 8,264 | 2,066 |
| fix-task | 514 | 2,060 | 15,111 | 3,778 |
| fix-wave-review | 336 | 1,209 | 8,791 | 2,198 |
| plan-delivery | 473 | 1,850 | 13,789 | 3,447 |
| review-task | 605 | 2,489 | 18,501 | 4,625 |
| wave-review | 500 | 2,045 | 14,754 | 3,689 |
| **Total maintenance corpus** | **5,927** | **23,175** | **171,792** | **42,948** |

The descriptions in the Skill catalogue are much smaller than these bodies.
Only a matching Skill is normally selected, so reducing the total corpus is
useful for maintenance but is not, on its own, a runtime context saving.

## 2. Duplication map

### Structural boilerplate

Nine Skills use a near-common frame: Purpose, When to Use, Inputs,
Authoritative Sources, Preconditions, Workflow, Rules, Context Management,
Output, Self-Check/Validation, Completion, and Escalation. The two review and
two acceptance-remediation pairs use a close variant of the same frame. This
is intentional navigational consistency, not automatically removable text:
the actual authority precedence, allowed mutation, outcome set, evidence path,
and stop condition differ by stage.

The following are repeated semantically across several Skills:

| Cluster | Affected Skills | What repeats | Assessment |
| --- | --- | --- | --- |
| Source hierarchy and immutable upstream scope | create-prd, plan-delivery, create-techspec, create-tasks, execute-task, fix-task, review-task, Wave/final review and fixes | User direction is bounded by approved scope; lower artifacts/code are evidence, not permission to rewrite upstream contracts. | Same safety intent, but precedence and the immediate contract differ. Keep the ordered list local. |
| Bounded context | create-prd, plan-delivery, create-techspec, create-tasks, execute-task, fix-task, review-task | “Read first/read only when needed/do not load by default/stop when enough” and targeted source/test guidance. | Shared principle; local manifests and review/change needs are meaningfully different. |
| No automatic next stage / no simulated approval | all planning Skills; execute-task; review/fix Skills; Wave/final review/fix Skills | Stop at the owning stage, do not claim a higher authority. | The exact next authority and forbidden action are stage-specific; retain local. |
| Truthful validation/evidence | create-tasks, execute-task, fix-task, review-task, Wave/final review and fixes | Do not invent/claim unexecuted validation; persist the required evidence. | A small invariant is identical, but required evidence artifact, outcome, and consumer differ. |
| Minimal scoped changes / no unrelated refactor | execute-task, fix-task, fix-wave-review, fix-final-review | Smallest coherent correction; preserve approved behavior. | Similar but not identical: task repair must map to task-review findings; release remediation handles integration and accepted Waves. |
| Acceptance versus remediation | execute-task, fix-task, review-task, fix-wave-review, fix-final-review, wave-review, final-review | Implementation and remediation readiness are not acceptance; review owns acceptance at its layer. | Essential boundary; phrase locally with the exact accepted object. |
| Result Markdown schemas | planning Skills, create-tasks, execute/fix/review, Wave/final review/fix | headings, status line, traceability/validation/findings tables. | Similar visual shape but artifact paths, fields, identifiers, owners, and lifecycle effect differ. |

### Strongest pairwise duplication

An exact nonblank-line comparison (unique matching lines, so it understates
repeated prose and overstates shared headings) found the largest pairs:

| Pair | Exact matching nonblank lines | Semantic common core | Extraction judgment |
| --- | ---: | --- | --- |
| wave-review / final-review | 88 | independent evidence-based acceptance, traceability, validation, finding severity, ownership, durable current review | Share only a carefully parameterized acceptance-audit *reference* if maintenance benefit outweighs risk; no context saving if required. |
| fix-wave-review / fix-final-review | 84 | route findings, make only executable scoped changes, validate, persist remediation, return for independent re-review | Strongest candidate for a shared reference; scope/ownership mappings must remain local. |
| execute-task / review-task | 71 | one-task boundary, bounded context, validation, criteria matrix, evidence, stop rule | Do not extract workflow: execution mutates and review must remain independent. |
| execute-task / fix-task | 66 | one-task bounded edits, tests, validation, diff inspection, escalation | Do not extract workflow: a review finding, rather than task plan, defines repair. |
| fix-task / review-task | 65 | one task, findings/criteria/evidence, status, re-review loop | Do not extract workflow: reviewer cannot modify code and fixer cannot accept. |
| create-tasks / execute-task | 59 | Context Manifest, limited references, task boundary, validation vocabulary | Keep the producer/consumer rules local; only the manifest notation is a possible reference. |
| create-techspec / plan-delivery | 57 | approved scope, bounded repository inspection, future-scope restraint, approval handoff | Keep local because delivery planning deliberately avoids technical design. |

These counts are evidence of duplication, not a safe line-removal estimate.
Many matches are headings or generic sentences; semantic duplication is most
substantial in the two Wave/release pairs.

## 3. Context-loading behavior

### What is already global

`AGENTS.md` appropriately owns repository-wide, stable instructions:

- readiness, Python/CLI, and the one tracked full-validation command;
- canonical Linux/WSL environment;
- authoritative repository artifact locations;
- initial `git status`, targeted search/read discipline, and compact output;
- the high-level implementation/review/fix role separation.

These should not be copied into a new shared Skill reference. They are already
global guidance. `AGENTS.md` deliberately delegates each workflow process to
the matching local Skill; it should not gain status taxonomies, artifact
schemas, review routing, or approval/authorization rules.

### Runtime implication of an extraction

| Reference loading mode | Effect on active model context | Use it? |
| --- | --- | --- |
| Main Skill says “always read shared reference” | Essentially no saving: removed text returns through the reference, plus a pointer and lookup. It may reduce drift only. | Not for context efficiency. |
| Main Skill says “read reference only when condition X applies” | Saves the reference on paths where condition X is false. On the true path the net saving is approximately zero. | Only for genuinely rare, objectively decidable conditions. |
| Main Skill says “consult when useful” | May save tokens but weakens a contract because a model can omit needed guidance. | Not for authority, safety, evidence, or output contracts. |
| Reference is loaded after an initial triage step | Reduces initial working context, but not total visible context for a path that ultimately loads it. | Useful only if the late branch is often avoided or the early triage is materially safer. |

The official OpenAI documentation consulted for this analysis recommends
auditing instructions that can influence agent behavior, but it does not
establish a different automatic lazy-loading behavior for repository-local
references. The practical conclusion above follows the active Codex Skill
protocol in this workspace: full selected `SKILL.md` first; linked material
only when the Skill's routing requires it.

### Current loading instructions that can be simplified

The repeated three-list pattern is useful, but it could be mechanically more
compact without changing behavior:

1. State the immediate contract and the mandatory first reads once.
2. State only stage-specific conditional inputs.
3. Refer to the existing `AGENTS.md` targeted-read rule instead of restating
   a long generic list of unrelated artifacts.

This is a wording consolidation opportunity, not a reason to omit local
context requirements. In particular, the required context for execution,
review, and repair must remain expressed locally because it determines safe
work at that stage.

## 4. Content that must remain Skill-local

The following must not be placed in a generic shared “workflow” reference or
in `AGENTS.md`:

| Local contract | Why it cannot be generalized safely |
| --- | --- |
| Immediate authoritative input and ordered precedence | A PRD source, approved TECHSPEC, selected task, review record, Wave review, and final review have different authority roles. |
| Mutability and allowed change surface | Planning writes a new authoritative artifact; execute/fix may change implementation; review must not; Wave/final remediation have different release/Wave constraints. |
| Scope and completion state | `AWAITING_HUMAN_APPROVAL`, `COMPLETED`, task `PASS`, Wave `PASS`, release `PASS`, and readiness for re-review are not interchangeable. |
| Artifact location, schema fields, IDs, supersession behavior, and consumers | Task-review evidence resolves task dependencies; Wave evidence is input to final review; remediation evidence is explicitly not acceptance. |
| Finding ownership values and routing | `TASK_REVIEW_REQUIRED`, `WAVE_FIX`, `WAVE_REVIEW_REQUIRED`, `RELEASE_FIX`, and planning/spec outcomes deliberately mean different things. |
| Review independence | `review-task`, `wave-review`, and `final-review` must retain explicit no-fix/no-self-acceptance rules. This cannot become an optional shared note. |
| Bootstrap authorization checks | The task-planning authorization is a narrowly scoped historical compatibility contract. It must not be generalized into product-domain governance or mistaken for execution authority. |
| Architecture overview boundaries | Provider-neutrality, orchestration ownership, and the global-versus-Wave distinction are content of that planning process, not a generic Codex convention. |

The delivery plan and architecture confirm why: task acceptance, Wave
acceptance, release acceptance, next-Wave authorization, delivery
authorization, and completion are separate persisted facts; runtime final
validation is evidence, not final review. They also require the distinction
`Domain Capability != Codex Skill != Agent Role != Provider / Runtime`.

## 5. Candidate shared references

These are candidates for evaluation, not implementation instructions. The
“removed” estimate is intentionally conservative and means content that could
leave always-loaded Skill bodies across the listed set, not guaranteed runtime
tokens saved.

| Candidate reference | Affected Skills | Approx. body text removable | Contents and identity basis | Load mode / actual context effect | Change risk |
| --- | --- | ---: | --- | --- | --- |
| `references/acceptance-remediation-core.md` | fix-wave-review, fix-final-review | 140–180 lines, ~1.1–1.5k proxy tokens across both | Generic finding table, executable/non-executable routing discipline, minimum coherent correction, evidence-not-acceptance, re-review requirement, statuses. These rules are semantically identical after substituting the scope mapping. | **Always** for either remediation Skill; **~0 active saving**. | High: a changed generic routing/status rule can incorrectly broaden a Wave fix into release work or vice versa. Local mapping, artifact path, owner names, and forbidden actions must stay in each Skill. |
| `references/acceptance-audit-core.md` | wave-review, final-review | 120–160 lines, ~0.9–1.3k across both | Evidence-based independent audit, traceability method, validation honesty, severity format, current persisted decision, no self-remediation. | **Always**; **~0 active saving**. | High: a generic acceptance gate can blur task/Wave/release authority. Keep all prerequisites, trace chain, finding ownership, PASS criteria, and artifact schema local. |
| `references/evidence-integrity.md` | execute-task, fix-task, review-task, wave-review, final-review, fix-wave-review, fix-final-review | 55–75 lines, ~0.4–0.6k across bodies | Truthful executed-validation reporting, durable evidence, no fabricated evidence, remediation is not acceptance, current record handling. | **Always** for any affected process; **~0 active saving**. | Medium-high: concise generic wording can lose whether an artifact is authoritative, a handoff, or merely remediation evidence. It largely duplicates existing `AGENTS.md` principle plus necessary local precision. |
| `references/output-schema-fragments.md` | create-prd, plan-delivery, create-techspec, create-tasks, review-task, wave-review, final-review, all fixes | 250–380 lines, ~1.8–3.0k across bodies | Markdown skeletons and common finding/validation table formatting only. | Usually **conditional late**; initial context may shrink, but normal successful paths load it, so **near-zero total saving**. | Medium: schema drift or an omitted scope-specific field corrupts persisted evidence. A common template must never define lifecycle semantics. |

No candidate above is recommended as a context-only refactor today. The first
two have credible drift-reduction value, but that is a maintenance decision,
not a runtime context optimization. A source-generation/template mechanism
could reduce authoring drift without becoming an agent-loaded authority, but
that would be a different design and is outside this analysis.

## 6. Progressive-disclosure candidates

Unlike cross-Skill sharing, these may lower active context on an actual branch.
They require a small, explicit routing check in the main Skill; none should be
loaded merely “when useful.”

| Parent Skill | Conditional reference/content | Current likely body reduction | Trigger | Why it is safe only with explicit routing | Caveat |
| --- | --- | ---: | --- | --- | --- |
| create-architecture-overview | Detailed area worksheets for provider/runtime, persistence/resume, observability/Git/CLI, and safety/failure | 180–230 lines, ~1.4–1.8k | Only an area relevant to approved scope | The main Skill retains the global/Wave decision rule, a short relevance checklist, all non-goals, and the requirement to consider applicable areas. | For Engineering Flow itself most areas are relevant, so this does not save much on the current scope; it primarily helps future narrower products. |
| create-tasks | Bootstrap task-planning authorization validation checklist and required-field schema | 45–65 lines, ~0.35–0.5k | Only a bootstrap-governed Wave | `SINGLE` and non-bootstrap scopes do not need the historical contract. Main text must retain that the authorization is required and must be exact when the trigger applies. | Current Engineering Flow Wave work is bootstrap-governed, so no saving on that path. High governance regression risk. |
| create-techspec | Later-Wave predecessor PASS/Wave-start authorization checks | 18–28 lines, ~0.15–0.22k | Only a later Wave | A `SINGLE` scope and first Wave do not need these checks. | Small saving; local wording may be safer than a file lookup. |
| review-task | Re-review-only matrix/provenance procedure | 20–30 lines, ~0.16–0.24k | Only when a prior authoritative review exists | First review has no prior findings to recheck. Main text must preserve independent review and current-record persistence. | A fixed task commonly enters re-review, so the saving is only on first reviews. |
| Output-heavy planning/review Skills | Full output skeleton as a late schema reference | 30–75 lines per Skill | Only after a non-blocked result is ready to persist | The initial scope/authority decision does not need formatting details. | Nearly every successful invocation needs the schema; it reduces early context, not end-to-end context. Do not count it as net savings. |

The architecture catalog is the only sizeable progressive-disclosure candidate.
It warrants an experiment before any extraction because “when relevant” must
not become an excuse to skip a cross-cutting safety or authority boundary.

## 7. Estimated context savings

There are three different metrics that must not be conflated.

| Metric | Current | Best credible change without weakening contracts |
| --- | ---: | --- |
| Repository maintenance corpus | 5,927 lines / ~42,948 proxy tokens | A broad shared-template refactor could remove ~565–795 lines / ~4.2–6.4k from main bodies, but would add references. This is maintenance consolidation, not runtime savings. |
| Typical selected Skill initial load | ~2.1k–4.6k proxy tokens | Conditional extraction can save ~0.15–1.8k only when its branch is not taken; the large 1.4–1.8k case is architecture-overview for a narrow scope. |
| Typical selected Skill complete successful path | ~2.1k–4.6k plus repository context | **Approximately zero** for any content moved into a required or eventually-loaded reference. It can be worse by the routing/pointer text. |

A cautious expected saving from the listed progressive candidates is therefore
small and workload-dependent: roughly 0–0.5k proxy tokens for routine current
Engineering Flow workflow use, and up to ~1.8k for a future narrow architecture
overview. Claiming a larger number would count file reorganization as model
context reduction.

## 8. Option comparison

| Option | Context efficiency | Drift risk | Boundary preservation | Maintenance | Decision |
| --- | --- | --- | --- | --- | --- |
| A. Keep all Skills self-contained | Current cost; no reference lookups | Low cross-file coupling, but duplicated pair edits can drift | Strongest; each process states its own authority | Moderate-high | Viable baseline. |
| B. Shared references for identical contracts | No active saving when mandatory; possible smaller bodies only | Reference is a new high-blast-radius authority | Safe only for narrow, parameter-free invariants | Better only for the genuinely identical pair core | Not sufficient by itself. |
| C. Progressive disclosure inside Skills | Real saving only on false branches; can improve early triage | Moderate if routing is vague | Good if main Skill retains mandatory trigger/stop rules | Moderate | Promising for rare exception detail, not generic boilerplate. |
| D. Hybrid B+C | Preserves selective benefits | Highest design and regression cost unless tightly limited | Good only with explicit parameter mapping and contract tests | Best potential, but unproven | Preferred only after an experiment. |

## 9. Risks and regression scenarios

1. **Authority flattening.** A generic “approved artifact” instruction could
   make code, task status, remediation, and acceptance evidence look
   interchangeable. This would violate persisted-authority ordering.
2. **Reviewer contamination.** A shared execute/review workflow can
   accidentally authorize a reviewer to repair tests or code, ending
   independence.
3. **Remediation becomes acceptance.** A common remediation reference that
   says “resolved” without locally restating the required independent re-review
   can improperly advance a task, Wave, or release.
4. **Wrong routing at a scope boundary.** Parameterizing Wave and release
   owners can route a missing Wave review as a release code fix, or reopen an
   accepted Wave without the required evidence.
5. **Governance leakage.** Moving bootstrap authorization detail into generic
   references can turn historical repository compatibility rules into a
   provider-neutral product-domain rule or broaden literal authorization scope.
6. **Lazy-load omission.** “Consult if useful” creates a silent path where a
   template, escalation rule, or safety constraint is not loaded.
7. **Stale references.** A reference changed without updating the affected
   main Skills can invalidate their local wording or output schemas.
8. **False savings.** Measuring only SKILL.md body sizes will report a win even
   though every normal invocation loads the extracted reference.

Mitigations for any future experiment: one source of truth for only truly
identical prose; explicit condition predicates; local scope/owner/path/status
mapping; a reference-change impact list; and scenario tests that prove no
workflow layer advances from remediation alone.

## 10. Proposed experiment

Run one read-only, isolated prototype before changing production Skill
instructions. Use a copy of `create-architecture-overview` only:

1. Split its fourteen detailed area descriptions into four references by an
   objective relevance checklist; retain purpose, inputs, global-vs-Wave rule,
   non-goals, completion authority, and a mandatory “consider every area”
   checklist in the main prototype.
2. Prepare two fixed prompts: a narrow `SINGLE` product with no provider or
   Git integration, and the current Engineering Flow-style cross-Wave product.
3. Trace which references are loaded, proxy tokens loaded before drafting and
   through completion, artifact completeness, and whether every applicable
   architecture boundary is covered.
4. Have an independent reviewer compare both artifacts to the current Skill's
   acceptance criteria and check the preserved domain/capability/role/provider
   distinction.
5. Accept the pattern only if the narrow case saves at least 25% of selected
   Skill instruction tokens *and* produces no missing applicable boundary; the
   Engineering Flow-style case may legitimately show no saving.

Do not experiment first on review/remediation or bootstrap authorization. Their
scope-sensitive evidence contracts create high regression cost for a result
that cannot produce net context savings when always loaded.

## 11. What must NOT change

- A Skill is not an agent role, domain capability, or provider/runtime.
- `execute-task`, `review-task`, `fix-task`, `wave-review`,
  `fix-wave-review`, `final-review`, and `fix-final-review` remain separate
  processes; review remains independent from implementation and repair.
- Remediation evidence is never acceptance evidence.
- Task, Wave, release, authorization, delivery, and completion facts remain
  distinct, persisted, and authoritative at their existing layers.
- Approved PRD, Delivery Plan, architecture, TECHSPEC, task contract, and
  authoritative review artifacts retain their existing precedence and are not
  silently rewritten by lower layers.
- The delivery-plan bootstrap authorization contract remains repository-local
  compatibility evidence with literal scope; it must not be recast as Wave 3
  product-domain governance.
- No change may redesign Engineering Flow Wave 3, introduce governance, or
  make Codex Skill layout part of the provider-neutral product domain.
- `AGENTS.md` remains concise repository guidance and does not become a
  duplicate workflow specification.

## 12. Recommendation

**Recommendation: EXPERIMENT_FIRST. Preferred option: D, a deliberately
limited hybrid of conditional progressive disclosure and, only if later needed,
a shared maintenance reference for the Wave/release remediation pair.**

Do not refactor now. The audit found real maintenance duplication, especially
in the Wave/release review and remediation pairs, but almost all proposed
cross-Skill references would be mandatory and therefore save no active model
context. First validate one sizeable, truly conditional architecture-overview
prototype. Retain self-contained process-local authority and evidence rules
until that experiment shows measured context reduction with no contract loss.

## Blockers

There is no repository or evidence blocker to the analysis. A refactor decision
is blocked only by missing measurement of actual reference-loading behavior and
by the need to validate any proposed extraction against the preserved workflow
boundaries above.
