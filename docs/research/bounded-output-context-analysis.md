# Bounded Output and Model-Visible Context Analysis

**Date:** 2026-09-05  
**Scope:** Read-only assessment of current Engineering Flow development output and context practices. No source, Skill, `AGENTS.md`, Codex configuration, or workflow-contract change is proposed.

## Recommendation

Adopt **bounded native-output discipline first**. The smallest safe strategy is: compact readiness/status; targeted search with a match cap; line-ranged reads; `git diff --stat` and path-scoped diff before complete diffs; targeted tests before full validation; and concise success summaries. Keep long raw output addressable outside the immediate agent turn and retrieve it only for a failure or a specific review question.

Do not introduce RTK yet. Native commands already support a controlled experiment, and another filtering layer would make provenance and diagnosis harder to evaluate. A deterministic repository helper is justified only if measurements show agents repeatedly need it or routinely fail to apply the native discipline.

This assessment uses `gpt-5.6-terra` / medium as requested. Lines and bytes below describe text exposed to an agent, not model tokens, quota, billing, or account savings.

## Evidence inspected

- `AGENTS.md`: initial short status, targeted searches/reads/tests, diff-stat or changed-file inspection before raw diffs, and detailed logs only for diagnosis.
- `scripts/env-preflight` and `tools/env_preflight.py`: compact results, a ten-path tracked baseline, a sanitized one-line diagnostic capped at 240 characters, and one-object JSON.
- Current CLI, store, Codex runtime adapter, test invocation behavior, and local Skills.
- Prior research on Skills context efficiency, environment preflight, model/reasoning policy, Context7, and the development environment audit.

Selected local Skills are necessary active instruction context rather than shell-output waste: each is loaded in full when selected and ranges from 8,264 to 18,501 bytes (322--627 lines); all twelve total 171,792 bytes. The prior Skills analysis correctly finds that moving required text to a reference produces little end-to-end context reduction.

## Current controls and output gaps

| Surface | Current control | Gap / risk | Default |
| --- | --- | --- | --- |
| Preflight | One-line READY; ten paths; 240-character diagnostic; one JSON object | No raw probe retention by design | Fully visible; rerun exact failed probe |
| Full unittest | Required command has `-q` | Tests emit CLI chatter | Summary on pass; raw only on failure |
| Focused tests | Skills require narrow useful checks first | No standardized launcher/summary | Fully visible if short, else summary + raw pointer |
| Git status | Guide says short status; preflight uses porcelain `-uno` and ten paths | Agent-facing short status is unbounded in a dirty/untracked tree | Fully visible when small; bounded paths when noisy |
| Git diff/show | Guide says stat/paths first | Raw diff/show is unbounded | Stat/path list, then selected hunks |
| `rg` and reads | Guide says search before large reads/ranges | Broad search and whole files readily flood context | Restrict path/matches, then read ranges |
| CLI status/logs | Usually concise human results; JSON supported | `logs` returns every event after `--after`, including full payloads | Human status; event delta and specific payload only |
| Provider/runtime | JSONL parsed incrementally; stderr is sanitized/tail-capped at 4,000 chars | Normalized event count/payload size is not visibly budgeted; tail can omit an early cause | Persisted events plus concise terminal summary |
| Review/remediation | Durable current records are required | Markdown/JSON evidence fields have no size limits | Full current authoritative evidence; summarize inventories |

The current product persists sanitized normalized events, terminal metadata, task results, and reviews. It does not appear to retain a raw provider stderr/stdout transcript: stderr is tail-capped and stdout is normalized into events. Future raw-log retention would need explicit redaction, access, retention, and integrity design; it must not silently broaden sensitive persistence.

## Measured baseline

Measurements are command output in this clean checkout.

| Operation | Current/native | Bounded native alternative | Result |
| --- | ---: | ---: | --- |
| Full required suite | 45 lines, 1,096 bytes; 101 tests in 8.255 s | Capture output; expose command, exit, duration, final unittest summary | 41 stdout lines were test-internal CLI output, not unittest verbosity |
| `git show HEAD` | 116 lines, 13,702 bytes | `git show --stat --oneline HEAD`: 3 lines, 165 bytes | 98.8% fewer bytes; stat identifies whether a hunk read is needed |
| Broad research search | 240 lines, 61,061 bytes | `rg -n -m 5` against a named file: 5 lines, 351 bytes | 99.4% fewer bytes; later hits may still matter |
| Full policy read | 428 lines, 30,688 bytes | First 100 lines: 100 lines, 6,221 bytes | 79.7% fewer bytes; follow-on ranges required when needed |
| Clean short status | 0 lines | no smaller useful alternative | No current waste; dirty-tree risk is latent |
| Readiness | 1 line, 98 bytes | already bounded | Keep visible |

A deliberately failing `.venv/bin/python3 -m unittest discover -s tests-does-not-exist -q` produced 21 stderr lines / 1,124 bytes and ended with the actionable cause, `ImportError: Start directory is not importable: 'tests-does-not-exist'`. A tail preserved this particular cause, but that does not make tail-only failure handling generally safe. A failing CLI status against an uninitialized repository was one actionable 111-byte line.

## Output classification

### Keep fully visible

- Preflight result; exit code; exact command or durable command ID; test count/duration/final PASS or FAIL.
- A short focused-test failure.
- Small short status, diff-check errors, diff stats, changed paths.
- The exact contract clause, source line, diff hunk, assertion, event, or review finding supporting the active decision.
- Current authoritative review/remediation/manual acceptance evidence. Console summaries cannot replace it.

### Summarize by default

- Successful full suite: command, exit, duration, count, final result; omit repeated test-internal CLI output.
- Successful CLI status/logs: workflow status/stage, active task, event count and latest sequence/type; not every event payload.
- Raw show/diff: stat, paths, and selected hunks.
- Searches: hit/file counts and first relevant locations.
- Provider progress: terminal state, IDs, usage where present, failure class, short sanitized diagnostic.
- Evidence inventories: current artifact IDs/outcomes and validation summaries, with authoritative paths.

### Persist/retrieve only on failure or a concrete question

- Long successful test stdout/stderr.
- Full provider JSONL and stderr, subject to sanitization/security policy.
- Complete CLI event payloads beyond a relevant sequence.
- Complete raw diffs/search results/generated JSON.

### Bound mechanically with native commands

- `rg -n -m N PATTERN path`, then `sed -n 'start,endp'` around a hit.
- `git diff --stat` / `git diff --name-only`, then `git diff -- path`; `git show --stat` before raw history.
- Short status normally; when noisy, tracked-only porcelain plus a bounded path list, explicitly noting excluded untracked files.
- `head`/ `tail` as previews only when full captured output remains addressable.
- `engineering-flow logs --after SEQUENCE`, from a known last sequence.
- Captured full suite plus concise success outcome; failure first expands a summary, selected failure, then raw output.

### Dangerous to truncate

- Tracebacks or multi-test failure before test identity, exception, assertion, and relevant stack location are known. Cause may be at head, middle, or tail.
- Provider startup/authentication/sandbox failures and malformed JSONL. The existing 4,000-character stderr tail is a safety bound, not proof that early causes are dispensable.
- Integrity/hash, persistence/migration, resume/retry ordering, secret-sanitization, and security failures. Collapse repetition only after preserving all unique locations/correlation IDs.
- Wave/final acceptance evidence. A summary indexes evidence but cannot replace its review.
- Structured arrays where omitted counts/order establish lifecycle correctness; use selectors, not text truncation.

## Agent discipline improvements

No repository change is needed to:

- Narrow the question before search; restrict paths and initial match count.
- Search headings/identifiers before reading; expand only to cited line ranges.
- Begin review with status/stat/paths and inspect selected hunks; use `git diff --check` when applicable.
- Run targeted validation before the required suite; summarize a successful suite rather than paste chatter.
- Track the last event sequence and use `logs --after`; prefer human CLI output unless JSON is required.
- Record command, exit, duration, concise outcome, and safe raw-log retrieval location in evidence.
- On failure, expand in order: summary, selected test/event/location, then raw log if ambiguity remains.

## Repository-tooling candidates

These are candidates only, not approved implementation work.

1. A validation wrapper: run the exact required command, capture sanitized stdout/stderr, print command/exit/duration/final unittest summary, and on failure show unique failing-test diagnostics plus raw retrieval path.
2. A diff-summary helper: status/stat/name list and explicit path/range expansion; never judge semantic sufficiency or hide `git diff --check`.
3. A concise CLI logs projection: count/latest sequence/types/failures plus explicit delta/detail retrieval, retaining current redaction and schema guarantees.
4. A command run ledger: concise summary and raw-log pointer correlated with task/review, not raw output copied into review prose.

## Proposed experiment

Run at one fixed revision in a disposable clean worktree, with the same prompt, environment, exact validation requirements, and `gpt-5.6-terra`/medium setting. Make no configuration, Skill, source, or contract change.

| Operation | A: current/native | B: bounded native discipline | Record |
| --- | --- | --- | --- |
| Readiness/status | Preflight and short status | Same, compact result; document tracked-only fallback | exposed lines/bytes, conclusion, latency |
| Locate rule | Broad `rg`, whole matching file | Path-restricted `rg -m`, hit-centered ranges | lines/bytes, files, retrieval turns, clause found |
| Inspect change | Raw show/diff | Stat/name list, one path-scoped hunk | lines/bytes, intent/hunk found, added reads |
| Validate success | Required suite pass-through | Capture; expose exit/duration/count/final summary | lines/bytes, pass evidence, latency, retrievals |
| Diagnose failure | Non-importable test dir above, or seeded disposable failure | Exit/summary plus bounded head+tail; raw retrieval if ambiguous | diagnosis correctness, root-cause visibility, retrieval turns, latency |
| Inspect logs | Fixture workflow with several events, full JSON logs | Recorded sequence + `logs --after`, selected payload | lines/bytes, event/correlation correctness, retrieval turns |

Capture stdout/stderr separately and use `wc -lc` on text passed to the agent. Record command-output and tool-result truncation separately. Required evidence is available/not available; diagnosis is correct only when it identifies the actual failing command/test/event and cause.

Adopt B only if it materially lowers exposed text across search/read/diff/success-validation while retaining all required evidence and no worse controlled-failure diagnosis. If B repeatedly needs raw retrieval or misses unique failures, refine that command class before considering a helper.

## Estimated benefit, RTK, and blockers

The main measured opportunities are broad search (60,710 fewer bytes), raw commit diff (13,537 fewer bytes), and whole-document read (24,467 fewer bytes). Full-suite noise is modest now (1,096 bytes) but will grow with integration coverage; clean status and preflight are already negligible. These are workload-dependent exposed-text estimates, not quota savings.

**RTK should be tested only after the native paired experiment.** If native discipline retains evidence and diagnosis with few retrievals, RTK has no demonstrated gap. If broad output remains a measured recurring offender after native discipline and helper evaluation, compare RTK against this same corpus, including provenance, diagnostics, latency, redaction, and raw-log recovery.

No blocker prevents the read-only experiment. Blockers to tooling/RTK adoption are: no paired measurements; no approved raw-log retention/redaction/access design; no identified non-production multi-event workflow fixture for the log row; and no evidence that agent discipline alone is insufficient. Current scope prohibits addressing those by changing repository contracts now.

