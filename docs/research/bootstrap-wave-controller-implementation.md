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

`next` returns role, capability, Skill reference, authoritative references, checkout identity, validation/output facts, operation metadata on acquisition, and model/effort policy. Reviewer and Wave Reviewer handoffs always use `fork_turns: none` and contain no developer/fixer rationale or suggested verdict. Their validation environment explicitly sets `PYTHONDONTWRITEBYTECODE=1`; the Host applies it to Python validation so review validation does not create bytecode/cache mutations in the checkout. This prevents transient drift and does not alter the Controller's exact review-artifact-only allowance.

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

## Post-integrated-dry-run corrections

The original implementation was correctly recorded as `READY_FOR_INTEGRATED_DRY_RUN` at that time. The subsequent integrated dry-run exposed three deterministic Controller gaps, corrected without changing the 19-state lifecycle.

- `next` now atomically persists the selected dependency-ready task before returning its Developer handoff. The persisted identity is reused by a fresh Controller invocation and by `begin-operation`; a completed accepted task clears the selection before the next task is selected.
- Checkout identities now retain deterministic path/content snapshots in addition to the spike's aggregate identity. Reviewer and Wave Reviewer leases persist one exact allowed output path. Completion requires the corresponding authoritative review artifact and rejects every other child-caused path mutation, while retaining aggregate stale-result and artifact-hash checks.
- The JSON CLI now exposes `record-authority --gate --decision APPROVE --actor --evidence <json-list> --authority-wave <wave>`. It persists a hashed evidence reference, gate, decision, actor, and timestamp. Wrong/open-state gates, wrong Waves, unsupported decisions, missing actors/evidence, and conflicting replay are rejected; an identical replay is idempotent.

Focused regression coverage is in `tests/bootstrap/test_wave_controller.py`; it covers durable selection/restart, review artifact-only paths and drift, stale checks, writer lease behavior, and explicit authority persistence. Validation for this correction is recorded in `bootstrap-wave-controller-dry-run-fixes.md`.

## Recommendation

READY_FOR_INTEGRATED_DRY_RUN
