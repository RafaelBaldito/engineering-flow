# Bootstrap Wave Controller implementation

## Purpose

This is temporary, deterministic bootstrap infrastructure for coordinating one authorized Wave. It is not the Engineering Flow product runtime.

## Architectural boundary

The Python Controller reads/writes only its Wave-local control record and returns structured mechanics. The Codex Wave Host dispatches and waits for role children; existing Skills perform all semantic engineering work. `src/engineering_flow/` neither imports nor exposes this tool.

## Implemented scope

Schema-v1 state parsing/validation, explicit lifecycle transitions, human gates, task dependency selection, attempt counters, checkout identity, artifact hash checks, result envelopes, logical lease ownership, bounded reconciliation, deterministic next actions, and reviewer-safe handoff facts are implemented. Ambiguity routes to `HUMAN_ATTENTION`.

## Files created / modified

- `tools/wave_controller/__init__.py`
- `tools/wave_controller/core.py`
- `tools/wave_controller/fingerprint.py`
- `tools/wave_controller/cli.py`
- `tests/bootstrap/test_wave_controller.py`
- this record

## CLI surface

`python -m tools.wave_controller.cli --root <repo> --wave <id> status|reconcile|next|begin-operation|complete-operation` emits one JSON result. `begin-operation` accepts optional `--operation-id` and `--child-task-name`; `complete-operation --envelope <json-file>` validates and completes a host-supplied envelope.

## State representation

The canonical file is `docs/waves/<wave-id>/bootstrap/WAVE-WORKFLOW-STATE.md`. It is a concise Markdown document containing one fenced `yaml` block whose content is canonical JSON (JSON is valid YAML); it is a current pointer/index, not an event store.

## Checkout identity

The implementation uses the spike's exact aggregate: HEAD, SHA-256 hashes of raw porcelain-v2 status and binary `diff HEAD`, content-hashed byte-sorted untracked manifest, byte-sorted changed-path manifest, then SHA-256 of canonical compact JSON components. Git byte inputs are kept binary-safe.

## Atomic persistence

State writes serialize a complete same-directory temporary file, flush and fsync it, replace the canonical path with `os.replace`, and fsync its containing directory. An interruption before replace retains the old complete record.

## Writer lease

One `active_operation` is persisted. Known active roles reject a second acquisition; unknown ownership blocks for human attention. A lease is released only by a valid completion transition.

## Result envelope

Schema-v1 envelopes bind operation/scope/role/attempt, input and output identities, terminal status, artifact hashes, validation facts, review decision, and timestamp. Invalid or stale envelopes cannot advance the lifecycle.

## Handoff metadata

`next` returns role, capability, Skill reference, authoritative references, checkout identity, validation/output facts, operation metadata on acquisition, and model/effort policy. Reviewer and Wave Reviewer handoffs always use `fork_turns: none` and contain no developer/fixer rationale or suggested verdict.

## Reconciliation

Reconciliation validates persisted state and artifacts, blocks unresolved ownership, and can apply an already durable, matching completed envelope. It never crosses a human gate or guesses conflict/remediation ownership.

## Tests

Focused command: `.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller -v` — PASS (15 tests).

## Repository validation

`.venv/bin/python3 -m unittest discover -s tests -q` — PASS (101 tests).

## Known limitations

- Reviewer behavioral write restraint is not yet validated.
- Reviewer artifact-only allowance is not yet validated end-to-end.
- Real Codex Host/child interruption recovery is not yet validated.
- Git edge cases remain bounded by the spike assumptions.
- Dispatch-time model/reasoning availability is not yet validated.

## Recommendation

READY_FOR_INTEGRATED_DRY_RUN
