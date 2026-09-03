# Superseded Historical Evidence — Wave 1 Final Review

**Status:** Superseded historical evidence. This Wave-scoped report is not the
authoritative release-level `final-review` and must not be used as current
release acceptance. Wave 1's authoritative acceptance evidence is
`tasks/1-controlled-planning-workflow/reviews/WAVE-REVIEW.md` with `PASS`.

---

# Historical Wave 1 Final Review — Controlled Planning Workflow

**Review date:** 2026-09-02  
**Repository state reviewed:** `9a05078` (`feat(cli): add planning workflow control surface`); working tree clean before this report was added.  
**Review method:** current-source inspection, current automated validation, current task-review evidence, and a fresh provider-backed run in a disposable Git repository. Historical task-review conclusions were treated as leads only and checked against the current implementation.

## Final Review Result

**BLOCKED**

Wave 1's deterministic implementation validation is broadly successful and its approved boundary is respected. Final acceptance cannot be granted because (1) the required live provider-backed acceptance could not produce usable planning artifacts in the current local Codex read-only environment, (2) the task-review record is internally inconsistent, and (3) usage metrics are incorrectly redacted before persistence. No Wave 2 behavior was reviewed as delivered or started.

## Release Scope

- **Delivery mode:** WAVES
- **Included scope:** Wave 1 — Controlled Planning Workflow.
- **Included outcome:** Feature request through persisted PRD, TECHSPEC, and task-plan artifacts; human approval gates; status/log access; interruption/resume; terminal `READY_FOR_WAVE_2` state.
- **Deferred scopes:** Wave 2 autonomous task execution, tests, independent review, remediation, and review-cycle limits; Wave 3 final validation, commit, push, and PR creation.
- **Non-goals checked:** no task execution/review/fix, repository delivery, alternate provider, UI/service, or merge automation was introduced.

## Traceability Summary

| Requirement | Delivery Scope | Task(s) | Current evidence | Status |
|---|---|---|---|---|
| Planning portions of FR-001–FR-005 | Wave 1 controlled planning/state/context | TASK-001–004 | `domain.py`, `orchestrator.py`, runtime boundary, `test_orchestrator.py`, provider-backed state trace | DELIVERED, subject to final blockers |
| FR-006–FR-008 | Required/automatic/conditional planning approvals | TASK-003–004 | policy/gating tests; live run recorded three exact approval decisions | DELIVERED |
| Planning portions of FR-017–FR-021 | Codex-only provider-neutral planning and capability checks | TASK-002–004 | `runtime.py`, `codex_cli.py`, preflight tests, authenticated CLI preflight | PARTIAL — live sandbox could not read inputs (FINAL-001) |
| Planning portions of FR-022–FR-025 | Persisted workflow, artifacts, resume, idempotency | TASK-001, TASK-003 | SQLite/store tests; fake-runtime integration; live workflow retained input, three revisions, approvals, and 41 ordered events | DELIVERED |
| Planning portions of FR-030–FR-032 | CLI, status/logs, classified failures | TASK-004 | CLI/config tests; live `status --json` and `logs --json` | PARTIAL — persisted token-usage values are redacted (FINAL-002) |
| AC-001 | Human-gated PRD → TECHSPEC → task plan | TASK-003–004 | `test_planning_workflow.py`; live flow reached each pending approval before the next stage | DELIVERED |
| Planning portions of AC-005 and AC-006 | Resume/no duplicate planning side effects; observable state/evidence | TASK-001, TASK-003, TASK-004 | idempotency/resume tests; separate CLI invocations continued the live workflow and `logs` exposed ordered evidence | DELIVERED |
| Applicable NFR-001–NFR-006 and CON-001–CON-007 | Wave 1 control, safety, Python CLI, provider boundary | TASK-001–004 | source inspection, test suite, compile check, no Wave 2/3 code paths; observability metric preservation remains incomplete | PARTIAL — FINAL-002 |

## Task Review Summary

- **Total required tasks:** 4
- **Task-index status:** 4 `PASS` (`tasks/1-controlled-planning-workflow/TASKS.md`)
- **Detailed review artifacts:** 4 `FIX_REQUIRED` (`reviews/TASK-001-REVIEW.md` through `TASK-004-REVIEW.md`)
- **Current implementation check of historical findings:** the relevant current code and regression tests address the environment sanitization, preflight flags/worktree validation, authentication event classification, streaming JSONL, retry attempt identity, feature-input atomic retention, malformed/stale-decision coverage, credential option rejection, and JSON usage-error rendering described in the detailed reviews.
- **Pending/unreviewed:** 0 according to the index; independently verifiable `PASS` evidence is nevertheless inconsistent with the detailed review artifacts (FINAL-003).
- **FIX_REQUIRED:** 4 in the detailed review records; their conclusions are not used as evidence of current defects without source/test confirmation.
- **BLOCKED:** 0 task records.
- **SPEC_CHANGE_REQUIRED:** 0 task records.

## Project Validation

| Check | Result | Evidence |
|---|---|---|
| `./.venv/Scripts/python.exe -m unittest discover -s tests` | PASS | 51 tests passed; 1 Windows symlink test skipped. |
| `./.venv/Scripts/python.exe -m compileall -q src` | PASS | Completed successfully. |
| `git diff --check` | PASS | No whitespace errors. |
| Current repository worktree before report | PASS | `git status --short` returned no entries. |
| `codex exec --help` and `codex login status` | PASS | Required non-interactive options were present; CLI reported authenticated ChatGPT login. |
| Fresh live Codex planning execution | FAIL | Lifecycle mechanics completed, but each planning artifact declared itself blocked because `codex-windows-sandbox-setup.exe` could not be launched (FINAL-001). |

## End-to-End Validation

- **Disposable-repository initialization → PRD → approve → TECHSPEC → approve → task plan → approve → `READY_FOR_WAVE_2`** — **PARTIAL**. Workflow `41995e7d-3965-43d2-ad45-ea87d5ad094d` persisted a feature-input hash, three immutable artifacts, three approval records, and 41 monotonic events; final state was `completed` / `ready_for_wave_2`. The approval boundary was also observed when `resume` was invoked while PRD approval remained pending.
- **Provider-backed artifact usefulness** — **FAIL**. The final payloads were schema-valid but stated that the feature request and prior artifacts could not be read because the local Codex read-only sandbox helper was unavailable. These are not usable PRD/TECHSPEC/task-plan artifacts and were only advanced to inspect state mechanics; they are not evidence of successful planning content.
- **No Wave 2/3 side effects** — **PASS**. The disposable repository had only untracked `.gitignore` and `feature.md`; `git log --all` and `git remote -v` had no delivery activity. No task, test, review, commit, push, or PR action occurred.

## Findings

### FINAL-001 — HIGH — Live Codex planning cannot read authoritative inputs

- **Category:** Integration
- **Ownership:** BLOCKED
- **Requirement/Scope:** Wave 1 provider-backed planning validation; TECHSPEC §§5 and 9; MANUAL-ACCEPTANCE steps 2–5
- **Location:** Disposable workflow `41995e7d-3965-43d2-ad45-ea87d5ad094d`, persisted execution metadata/events 7–10, 20–23, and 33–37
- **Issue:** The authenticated Codex CLI starts and returns schema-valid final payloads, but its read-only sandbox cannot launch `codex-windows-sandbox-setup.exe`. Each agent therefore states that it could not read the authoritative inputs and emits a blocked artifact rather than useful planning content.
- **Expected result:** The provider must read the stage-scoped inputs and generate reviewable PRD, TECHSPEC, and task-plan artifacts in the disposable repository without repository-delivery side effects.
- **Evidence:** The persisted stderr contains `orchestrator_helper_launch_failed` and `helper=codex-windows-sandbox-setup.exe ... error=program not found`; all three generated artifacts state that input access was blocked. The workflow's completed state proves state mechanics only, not a valid planning outcome.
- **Remediation direction:** Restore/repair the local Codex Windows sandbox helper or use an approved functioning read-only Codex environment, then repeat the manual acceptance with substantive artifacts and retain its evidence.

### FINAL-002 — MEDIUM — Numeric provider usage metadata is redacted as though it were secret material

- **Category:** Validation / Observability
- **Ownership:** TASK_FIX
- **Requirement/Scope:** Wave 1 TECHSPEC §5 (`PlanningExecutionResult` usage metadata when available); planning portions of FR-031 and NFR-003
- **Location:** `src/engineering_flow/sanitization.py:24-28, 53-58`; persisted live events 9, 22, and 36 in workflow `41995e7d-3965-43d2-ad45-ea87d5ad094d`
- **Issue:** `_is_sensitive_key` matches the substring `token` in keys such as `input_tokens`, so numeric provider usage counters are persisted as `[REDACTED]`.
- **Expected result:** Credential values and sensitive data are redacted, while non-secret numerical usage metadata remains available for the required workflow observability and measurement.
- **Evidence:** All live `turn.completed` events record `input_tokens`, `cached_input_tokens`, and related numeric counters as `[REDACTED]`, despite the adapter receiving the values. Existing sanitization tests do not cover preservation of usage counters.
- **Remediation direction:** Narrow sensitive-key detection to credential/token-secret fields rather than generic usage-counter names; add regression tests confirming numeric usage fields persist while secrets remain redacted.

### FINAL-003 — MEDIUM — Task-review acceptance evidence is contradictory

- **Category:** Documentation / Process Evidence
- **Ownership:** BLOCKED
- **Requirement/Scope:** Wave 1 task-completion prerequisite; `tasks/1-controlled-planning-workflow/TASKS.md` and `tasks/1-controlled-planning-workflow/reviews/`
- **Location:** `TASKS.md:10-13`; `reviews/TASK-001-REVIEW.md:1-3`, `TASK-002-REVIEW.md:1-3`, `TASK-003-REVIEW.md:1-3`, and `TASK-004-REVIEW.md:1-3`
- **Issue:** The task index records all four tasks as `PASS`, while every detailed independent review artifact still records `FIX_REQUIRED`. Current source and regression tests show the historical findings have largely been remediated, but no detailed re-review or explicit supersession establishes the evidence chain required for final acceptance.
- **Expected result:** Each required task has one unambiguous current independent-review result of `PASS`, or a clearly linked superseding review that explains resolution of earlier findings.
- **Evidence:** The index and detailed review artifacts conflict directly. This final audit independently confirmed the code/test paths for the historical findings but does not replace the missing task-level review decision.
- **Remediation direction:** Perform/record current independent task re-reviews (or create an explicitly superseding review record) after the accepted fixes, then align the task index to that evidence. Do not change product scope.

## Blocking Conditions

1. `FINAL-001`: the local live Codex read-only environment cannot access planning inputs, so required provider-backed acceptance has not demonstrated usable planning artifacts.
2. `FINAL-003`: current task-level PASS evidence is not internally consistent.

`FINAL-002` is an implementation defect to resolve before a future final `PASS`, but it is not the reason this review is classified `BLOCKED` rather than `FIX_REQUIRED`.

## Evidence Used

- Approved scope: `docs/product/prd.md`, `docs/DELIVERY-PLAN.md:52-59`, `docs/architecture/architecture-overview.md`, and `docs/waves/1-controlled-planning-workflow/TECHSPEC.md`.
- Approved Wave 1 task contracts and index: `tasks/1-controlled-planning-workflow/TASK-001.md` through `TASK-004.md`, and `TASKS.md`.
- Current task-review records: all four files in `tasks/1-controlled-planning-workflow/reviews/`.
- Current implementation and tests: `src/engineering_flow/`, `tests/`, passing full unittest suite, compile check, and clean whitespace check.
- Fresh provider-backed evidence: authenticated `codex` preflight and the disposable workflow named in FINAL-001, including persisted status and JSON logs.

## Summary

Wave 1 remains within its approved boundary and has strong deterministic coverage. Its former task-review defects should not be treated as current defects solely because the old review files still say `FIX_REQUIRED`; the current source and tests were checked directly. Nevertheless, final acceptance is **BLOCKED** until the live read-only Codex environment can produce usable artifacts and the task-review record is reconciled. The usage-metric redaction must also be corrected before a subsequent `PASS`. No production code, tests, approved specifications, task plans, or Wave 2 work were modified by this review.
