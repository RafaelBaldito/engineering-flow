# Controlled Bounded-Output Experiment 2

**Date:** 2026-09-05  
**Fixed revision:** current clean checkout, `34350700184d415df17fd01e33485fce41beb3ed`  
**Model / reasoning:** `gpt-5.6-terra` / `low`  
**Scope:** Read-only comparison of noisy search and multi-file historical-diff inspection. The sole repository write is this result artifact. RTK was not used. No validation or failure-diagnosis experiment was run.

## Method

Each arm was run independently against the fixed revision. “Exposed” is raw command stdout that the arm intentionally presented; line/byte totals were measured from the exact command streams using `wc -lc`. Instrumentation for those totals is not counted as a retrieval turn. A retrieval turn is a subsequent information request after the arm's initial lookup/metadata request. Percent reductions are calculated from bytes; line changes are also shown.

## Operation 1 — noisy repository search

The concept was the broadly occurring term `review`, searched in the specified representative corpus: `docs/research`, `.codex/skills`, `tasks`, and `tests`. A preliminary count established 933 matches in 53 files, making it meaningfully noisy.

| Arm | Command stream | Exposed lines / bytes | Matches / files | Extra retrieval turns | Relevant conclusion | Missed relevant candidate? |
|---|---|---:|---:|---:|---|---|
| A — current/native | `rg -n -i 'review' docs/research .codex/skills tasks tests` | 933 / 141,873 | 933 / 53 | 0 | The corpus contains extensive review-related material, including the bounded-output analysis and prior experiment. | No (complete result set). |
| B — adaptive bounded | `rg -n -i -m 5 'review' docs/research/bounded-output-context-analysis.md docs/research/bounded-output-experiment.md` | 6 / 2,132 | 6 / 2 | 0 | The relevant bounded-output guidance says to use targeted capped search and retain current authoritative review/acceptance evidence; the prior experiment identifies sparse-search overexpansion as the counterexample to avoid. | No for this question: both directly relevant research artifacts were returned. |

The bounded starting paths were justified by the experiment's subject: the two existing bounded-output research artifacts are the authoritative prior analysis for this repository-local question. The initial B output was only six lines, so it was retained as-is: no contextual read or expansion was added. This is the adaptive behavior the previous sparse-search case lacked.

**Noisy-search reduction:** 927 lines (99.4%) and 139,741 bytes (98.5%) less exposed text. The B match cap did not suppress either relevant file; it returned all six matches in the two selected files.

## Operation 2 — multi-file change inspection

The selected real commit was `50c68d1dfebe4497caa8bb0aef0336b3edfa8d23`, **“feat: add deterministic environment preflight.”** It changes six files and 824 inserted lines: `AGENTS.md`, two research documents, the launcher, the standalone implementation, and focused tests.

| Arm | Command stream | Exposed lines / bytes | Files content-inspected | Extra retrieval turns | Change intent understood? | Material cross-file relationship missed? |
|---|---|---:|---:|---:|---|---|
| A — current/native | `git show 50c68d1...` | 871 / 48,312 | 6 / 6 | 0 | Yes: adds a documented, read-only deterministic readiness command, implementation, and tests. | No. |
| B — adaptive bounded | Initial: identity (`git show -s`), `git show --stat --format=`, and `git diff-tree --name-status`; selected inspection: launcher in full plus first 118 lines of implementation and first 105 lines of tests; expansion: zero-context hunks for `AGENTS.md` and implementation note. | 284 / 9,743 | 5 / 6 | 2 | Yes: the documented first readiness command launches host Python, which runs the standalone read-only preflight; focused tests exercise it; the implementation note confirms that linkage. | No. |

The initial B metadata exposed 16 lines / 779 bytes and established identity, size, and all changed paths. The first selected-path retrieval exposed 250 lines / 8,128 bytes for the launcher, implementation interface/bounded-probe design, and focused test harness. A second retrieval was needed to confirm the user-facing `AGENTS.md` entry point and the implementation document's explicit launcher-to-tool relationship; it exposed 18 lines / 836 bytes. The large design document was not opened because its 174 inserted lines supplied rationale already summarized by the commit metadata and was not needed to establish implementation intent or cross-file wiring.

**Multi-file-diff reduction:** 587 lines (67.4%) and 38,569 bytes (79.8%) less exposed text. B inspected content from five of six changed files, leaving only the design rationale unexpanded; no material implementation or documentation relationship depended on that omission.

## Results and recommendation

| Required decision/evidence | Result |
|---|---|
| Evidence lost | None required for either conclusion. |
| Missed candidates or relationships | None. Search B intentionally did not inventory unrelated review hits outside the two relevant research artifacts; diff B did not open the design rationale, which was not material to the change wiring or intent. |
| Extra retrieval turns | Search: 0. Diff: 2 after initial metadata (selected implementation/test paths, then targeted entry-point/documentation confirmation). |
| Did adaptive bounding fix the sparse-search issue? | Yes. The initial B search was small, so it was neither expanded nor given extra context. |
| Was low reasoning sufficient? | Yes. |
| Was escalation to medium needed? | No. |
| Is native bounded discipline ready for adoption? | Yes, for these two operations: begin bounded and adapt only when evidence requires expansion. |
| Should RTK be tested next? | No. Native command discipline was sufficient and repeatable here; no RTK comparison is justified by this result. |
| Blockers | None. |

**Recommendation: ADOPT_NATIVE_DISCIPLINE.** Bounded native commands materially reduced exposed text for both representative operations, preserved all required evidence and relationships, kept extra retrieval low, and avoided the earlier sparse-search regression through the explicit “retain small initial output” rule. This result does not claim token, billing, quota, or weekly-limit savings.
