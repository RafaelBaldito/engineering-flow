# Bootstrap Wave Controller dry-run fixes

## Purpose

Record the focused correction of deterministic temporary bootstrap Controller defects found by the integrated dry-run. This does not start or alter Wave 3, production runtime code, existing Skills, or the approved 19-state lifecycle.

## Dry-run findings addressed

The integrated dry-run found that Developer task selection was not durable across `next` and `begin-operation`; review completion had no exact allowed-path enforcement; and the public CLI could stop at but could not persist a human decision for a gate.

## Root cause — task selection

`next` put the selected task only in the returned handoff. A newly loaded state in `begin-operation` still had `current_task_id: null`, so the operation lease and a valid task-scoped envelope disagreed.

## Correction — task selection

Selecting the first dependency-ready task now atomically persists `current_task_id` before returning the handoff. Selection remains stable while that pending task is current; `begin-operation` copies the handoff identity into the lease. A successful task review clears it before another task can be selected.

## Root cause — review artifact allowance

The aggregate checkout fingerprint proved freshness but did not identify the paths changed during a review. An expected review artifact plus source or test drift could therefore match the submitted final aggregate identity.

## Correction — review artifact allowance

Checkout capture now includes a deterministic path/content snapshot. Reviewer and Wave Reviewer leases carry one exact allowed authoritative output path. Completion requires that path in the hash-validated artifact list and rejects every changed path other than that path (and the Controller's own control record write). Aggregate fingerprint stale protection remains mandatory.

## Human authority CLI gap

The Controller returned `HUMAN_ACTION` correctly, but no public Controller command could record the human decision and its evidence.

## Correction — human authority

`record-authority` persists only an explicit `APPROVE` decision for the currently open gate, bound to the Controller Wave, actor, timestamp, and hash-validated evidence reference. It rejects wrong gates/Waves, malformed decisions, empty actors/evidence, and conflicting replay. Exact replay is idempotent. Reconciliation never invents authority.

## Files modified

- `tools/wave_controller/core.py`
- `tools/wave_controller/fingerprint.py`
- `tools/wave_controller/cli.py`
- `tests/bootstrap/test_wave_controller.py`
- `docs/research/bootstrap-wave-controller-implementation.md`
- this record

## Regression tests

Focused tests cover durable selection through a fresh Controller and operation lease, valid task-scoped Developer completion, no task drift with multiple ready tasks, task and Wave review exact-artifact acceptance, source/test/wrong-artifact rejection, missing artifact rejection, stale-result rejection, artifact hashes, writer lease behavior, public CLI human-authority persistence/restart, rejection cases, idempotent replay, and no inferred authority.

## Focused test result

`.venv/bin/python3 -m unittest tests.bootstrap.test_wave_controller -v` — PASS (23 tests).

## Full repository validation

`.venv/bin/python3 -m unittest discover -s tests -q` — PASS (101 tests).

## State-machine change

None. The approved 19 named lifecycle states are unchanged; only minimal persisted task, operation-output, checkout snapshot, and human-gate evidence facts were added.

## Remaining integration risks

The deterministic corrections are unit-tested, but live Codex behavior remains unvalidated for this corrected build: a complete fresh integrated dry-run, Host/child interruption recovery, clean reviewer parent-context marker probe, the FIX_REQUIRED loop, and real Wave Reviewer dispatch/acceptance. No live Codex/subagent dry-run was rerun in this session.

## Recommendation

READY_TO_RERUN_INTEGRATED_DRY_RUN
