# Wave 1 Review Remediation

**Date:** 2026-09-02  
**Scope:** Wave 1 — Controlled Planning Workflow  
**Result:** READY_FOR_WAVE_REVIEW

## Remediation Record

| Original finding ID | Ownership | Status | Affected scope | Required action |
| --- | --- | --- | --- | --- |
| WAVE-001 (live manual-acceptance finding) | WAVE_FIX | RESOLVED | `CodexCliRuntime` terminal-result classification | Prevent successful generated artifact content from being evaluated as authentication-error diagnostics. |

The live acceptance evidence identified that the runtime searched every normalized
JSONL payload for authentication terms. A successful provider event can carry the
structured final artifact, so an artifact that legitimately used the word
"Authentication" was incorrectly returned as an authentication failure.

## Changes Applied

- `src/engineering_flow/codex_cli.py`
  - Added failure-event-scoped diagnostic collection.
  - Authentication matching now considers stderr and payloads from declared
    failure events only; successful event payloads, including structured artifact
    content, are not failure diagnostics.
- `tests/test_codex_cli.py`
  - Added a regression that returns a schema-valid successful artifact containing
    "Authentication" through a provider event and verifies a successful terminal
    result with no authentication classification.

## Validation Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Codex adapter tests | PASS | `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_codex_cli.py'` completed: 9 tests passed. |
| Full automated suite | PASS | `PYTHONPATH=src python3 -m unittest discover -s tests` completed: 53 tests passed. |
| Compile check | PASS | `PYTHONPATH=src python3 -m compileall -q src` completed with exit code 0. |
| Whitespace check | PASS | `git diff --check -- src tests tasks/1-controlled-planning-workflow` completed with no errors. |

## Remaining State

This correction is complete and independently validated by regression and full
suite evidence. It does not constitute Wave acceptance or alter the authoritative
`WAVE-REVIEW.md`; independent Wave re-review is required before acceptance.
