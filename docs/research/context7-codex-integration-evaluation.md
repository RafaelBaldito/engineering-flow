# Context7 Codex Integration Evaluation

**Date:** 2026-09-05  
**Scope:** Evaluate the installed Context7 Codex plugin as a personal development-productivity capability. This is not a product-design change.

## Decision

Keep Context7 available as an **agent-decided, personal Codex documentation-retrieval aid**. It is useful when a task depends on an external library API whose installed or requested version matters. It must not replace repository-authoritative artifacts, local source inspection, validation, or primary web research where Context7 cannot provide an adequate, version-matched primary source.

Do not make it an Engineering Flow provider/domain capability now. The approved architecture requires `Domain Capability != Codex Skill != Agent Role != Provider / Runtime`; adding a provider-specific documentation service to the product would need a separately approved Wave 3+ capability design, resolution contract, provenance/version record, failure behavior, and provider-neutral equivalent.

## Evidence inspected

| Evidence | Finding | Consequence |
| --- | --- | --- |
| Installed `context7` plugin `1.0.1` manifest | Upstash read-only Developer Tools plugin; it exposes an HTTP MCP server at `https://mcp.context7.com/mcp` and describes version-aware documentation/code examples. | It is suitable for supplemental retrieval, not mutation or workflow authority. |
| Installed `context7-mcp` Skill | Requires library-ID resolution before documentation query; asks for specific, one-concept queries; says to prefer official/primary sources and version-specific IDs. | Follow resolution, source selection, and narrow-query discipline; the Skill does not establish that every answer is complete or exact-version matched. |
| Context7 smoke test | It resolved `/python/cpython` with High reputation and versions including `v3.13.9`; a query against CPython documentation correctly established that `sqlite3.Connection.execute` returns a new `Cursor`. | The capability is available and can retrieve useful official source material. |
| Version-pinned follow-up | The checkout uses Python `3.13.15`, but the resolved CPython catalog offered `v3.13.9`. Its version-pinned response supplied relevant sqlite3 examples but not the explicit return-contract text returned by a previous unpinned query. | Resolution/version match and answer completeness must be checked, rather than inferred from a successful tool call. |
| `AGENTS.md` | Repository artifacts are authoritative; source reads must be minimal and targeted; exact local validation remains required. | Context7 is never an authority for repository behavior or an alternative to reading local contracts/source/tests. |
| Delivery plan and architecture overview | The product is provider-neutral; provider mechanisms belong behind adapters, and Wave 3 owns any capability resolution. | Keep this as a Codex-user tool; do not couple it to current Engineering Flow capability semantics. |
| Existing context/reasoning research | Selected Skills and authoritative inputs already create material context; retrieval should be conditional and measured. Moving required information does not create a meaningful net context saving. | Use only when its external documentation evidence changes a decision; do not retrieve by default or claim quota savings. |

The CPython retrieval source was [`Doc/library/sqlite3.rst` at CPython v3.13.9](https://github.com/python/cpython/blob/v3.13.9/Doc/library/sqlite3.rst). The plugin metadata itself is local installed-state evidence, not a claim about a remote service SLA.

## Default operating policy

| Category | Use cases | Required safeguards |
| --- | --- | --- |
| **USE** | Current, version-sensitive third-party library/framework/SDK APIs; installation/configuration semantics; behavior that differs across supported versions; a narrowly scoped external API question needed to implement or review an approved task. | Resolve the exact library; select the official/primary result; request the installed/requested version where available; query one concept; record the source/version in task evidence when it materially affects behavior; validate against local code/tests. |
| **OPTIONAL** | Python standard-library details when the target interpreter version is known but local `help()`, source, or a small executable probe would not answer efficiently; Codex/OpenAI SDK or CLI usage when the installed/local documentation does not settle the question; common programming techniques where a brief external example might reduce uncertainty. | Prefer the checkout interpreter's `help()`, source, CLI `--help`, or reproducible probe when those are authoritative and cheap. Treat retrieved examples as illustrative, not a compatibility proof. |
| **AVOID** | Repository-local source, approved PRD/plan/TECHSPEC/task/review contracts, current configuration, test behavior, defects, validation results, lifecycle/acceptance decisions, or general programming knowledge that does not depend on a changing external API. | Use the smallest applicable repository artifact/source/test instead. Do not use Context7 merely because a library name occurs in local code. |
| **ESCALATE / FALL BACK** | No exact-version official result; ambiguous/wrong library resolution; results conflict with local source/tests; incomplete documentation; API behavior depends on implementation, release notes, security advisories, cloud service status, pricing, policy, or a specific upstream issue. | Inspect installed source and lockfiles first where applicable. Use direct official documentation/source/release notes, or web research for current multi-source facts, advisories, issues, announcements, and pages not adequately indexed. State uncertainty rather than filling a gap from memory. |

### Topic-specific application

| Topic | Default | Why |
| --- | --- | --- |
| Third-party dependency at a specified version | USE | Version-sensitive API semantics are the strongest match for Context7's resolution and focused retrieval model. |
| Python standard library | OPTIONAL | This repository pins Python 3.13; local interpreter docs/source or a tiny probe may exactly match `3.13.15`, whereas the observed catalog offered `3.13.9`. Use Context7 when it supplies a clearer official reference, but check the version delta. |
| Codex/OpenAI SDK or CLI | OPTIONAL, with official OpenAI source preferred | Context7 may accelerate narrow API lookup; local CLI help, installed package docs/source, and official OpenAI documentation are more authoritative for installed CLI behavior, account/product policy, pricing, and current operational limits. |
| Framework/library API varying by version | USE | Resolve and query the exact version, then corroborate with installed version/lock data and focused validation. |
| Local contracts or source | AVOID | The repository declares these authoritative; external retrieval cannot know approved scope or current checkout behavior. |
| General programming knowledge | AVOID by default | Retrieval usually adds noise without changing the answer. Use it only if the question is actually library-specific. |
| Direct source inspection | Prefer direct source | Installed implementation, local wrapper behavior, generated stubs, and tests decide behavior when documentation and runtime diverge or the precise version is unavailable. |
| Web research | Prefer when needed | Use primary websites/release notes/security advisories/issues for current information outside Context7's indexed docs or where corroboration and publication dates matter. |

## Prompting and context implications

Context7 should normally be **agent-decided** from task evidence: an external, version-sensitive API question is enough to trigger it. A user can explicitly request Context7 to require its use, or explicitly prohibit external retrieval. Task/TECHSPEC instructions may require a documented external source when that evidence is an acceptance need; otherwise, do not add a prompt ritual merely to make the tool visible.

Each use adds at least library resolution plus one targeted documentation response to the working context. Its narrow-query guidance limits this cost, but the retrieval can still be irrelevant, verbose, stale relative to the installed version, or incomplete. It can lower time spent searching when it returns the exact authoritative fragment; it does **not** establish token/quota savings, and it does not reduce the required repository Skill, contract, source, or test context.

## Failure modes and controls

| Failure mode | Control |
| --- | --- |
| Wrong/ambiguous library result | Check package/vendor identity, source reputation, repository URL, and the installed dependency name before querying. Escalate rather than selecting a plausible look-alike. |
| Wrong version or unavailable patch version | Compare against `pyproject.toml`, lockfile, package metadata, and runtime. Prefer local source/probe for exact patch behavior; state any acceptable version gap. |
| Incomplete/ranked snippet | Ask a more precise single-concept query, then open the cited primary source or inspect implementation. Do not infer omitted guarantees. |
| Stale or inconsistent assumptions | Treat returned documentation as evidence with a source/version, not durable truth; corroborate behavior with focused tests. |
| Example mistaken for normative behavior | Separate examples from API contract and exception/version notes. |
| Excess context/latency | Do not invoke for local/general questions; make one resolution and the minimum number of narrow queries; stop once the answer is supported. |
| External source conflicts with repository contract | The approved repository contract wins for this product; raise a spec/implementation discrepancy through the applicable workflow rather than silently changing behavior. |

## Controlled experiment

Run a small, read-only paired experiment before changing the default policy. It tests assistance quality, not quota economics.

### Corpus and controls

Choose 8–12 fixed questions that each have a pre-recorded answer from the exact installed version's primary source and/or a reproducible local probe. Include at least:

1. a Python 3.13.15 stdlib edge case;
2. a version-specific API for a temporary, pinned third-party fixture dependency;
3. a framework deprecation/behavior change between two versions;
4. a Codex/OpenAI SDK or CLI option whose behavior is documented by an official source;
5. an intentionally local-contract question as a negative control, where Context7 should not be used.

Use the same model, reasoning setting, prompt, time budget, and isolated session conditions for each arm. Randomize question order and have a reviewer who does not know the arm score the answers against the answer key.

| Arm | Procedure |
| --- | --- |
| **A — normal reasoning** | Answer from supplied task facts and normal local inspection only; no Context7. |
| **B — Context7-assisted** | Permit one resolve call and up to two narrow documentation queries. Require exact library/version selection and cited source. Local inspection remains allowed when it is the authority. |

### Measures

| Measure | Collection and scoring |
| --- | --- |
| Correctness | Blind 0/1 answer-key score, plus severity of any incorrect conclusion. |
| Source/version accuracy | Score whether cited source is primary, the library identity is correct, and version exactly matches; record justified minor-version gaps separately. |
| Retrieval/search turns | Count resolve, Context7 query, local search, web search, and source-open turns separately. |
| Unnecessary context loaded | Record retrieved chunks/characters and mark a chunk unnecessary if it did not support the final answer; report distribution, not an assumed token saving. |
| Observable latency | Record wall-clock elapsed time from session/tool telemetry where exposed; otherwise mark latency unavailable, never estimate it. |
| Rework from incorrect API assumptions | Count answer corrections, failed focused probes/tests, or reviewer findings attributable to a wrong API claim. |

### Decision rule

Adopt the policy above unchanged unless arm B improves correctness or source/version accuracy on version-sensitive questions without a material rise in unnecessary context, latency, or rework. Keep the negative control as an explicit guardrail: Context7 use there is a failure even if the resulting answer happens to be correct. If results are mixed, retain OPTIONAL rather than expanding automatic use. No outcome authorizes product/provider integration without the separate architecture and delivery decisions described above.

## Recommendation and current impact

The capability should remain enabled as a personal Codex tool and be used selectively under the policy above. It should not change Engineering Flow now: no repository contract, Skill, configuration, architecture, provider capability, or source change is warranted. The only current blocker to stronger automation is lack of the controlled paired evidence and, for any future product integration, the unapproved provider-neutral design/provenance/failure contract.
