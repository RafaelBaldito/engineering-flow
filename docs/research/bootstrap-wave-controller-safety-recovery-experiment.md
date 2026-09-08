# Bootstrap Wave Controller safety/recovery experiment

## Purpose

Live, focused validation of bootstrap Wave Controller safety and recovery mechanics only. No production Wave, Developer/Reviewer/Fixer quality, remediation loop, or Wave Review was exercised.

## Baseline

Production checkout started clean at `604497da69bba5788ac71ea5c914ff1ede9a2f48` (`604497d`). `./scripts/env-preflight` returned `READY` with Python 3.13.15 and the editable package/CLI available.

## Environment

Linux/WSL; Controller invoked as `PYTHONPATH=/home/bal/projects/engineering-flow .venv/bin/python3 -m tools.wave_controller.cli`. Fixture initialization used the Controller's existing `initial`/`save` bootstrap facility; all scenario lifecycle actions used only the public CLI. No control record was manually edited after initialization.

## Disposable fixtures

- `/tmp/wc-safety-s1` — stale-result case.
- `/tmp/wc-safety-gates` — human gate, authority, and restart recovery cases.
- `/tmp/wc-safety-s6` — unresolved writer case.

Each was a minimal independent Git repository with one committed `README.md`, and all were removed after this experiment.

## S1 stale-result rejection

**PASS.** `begin-operation --operation-id s1-old` legitimately acquired Developer operation `s1-old` for `TASK-1`; its input fingerprint was `ea6b3e0efce64595eac13df396a18a891e1e4d07b986bfb4999c1097436d50d9`. An envelope was captured with that operation's input identity and the then-current output identity. A newer legitimate checkout condition was then created by adding `LEGITIMATE-NEWER-CONDITION.txt` before submitting that old envelope through `complete-operation`.

Exact response: `{"reason":"stale result","status":"HUMAN_ATTENTION","wave_id":"safety-s1"}`. A subsequent `status` returned `HUMAN_ATTENTION` with `active_operation: null`; it did not advance to task review. The persisted result was marked stale by the Controller's validation path.

## S2 human-gate stop

**PASS.** In `WAVE_AUTHORIZED` with no recorded authority, `status` returned `WAVE_AUTHORIZED` and public `next` returned `{"gate":"WAVE_START_AUTHORIZATION","status":"HUMAN_ACTION"}`. No operation was acquired or dispatched. This is the Wave-start human gate, and the next action explicitly requested authority rather than crossing it.

## S3 explicit human-authority persistence

**PASS.** Public command used:

`record-authority --gate WAVE_START_AUTHORIZATION --decision APPROVE --actor safety-human --evidence /tmp/safety-evidence.json --authority-wave safety-gates`

The evidence list contained the SHA-256-bound fixture artifact `APPROVAL-EVIDENCE.txt`; the Controller returned `{"gate":"WAVE_START_AUTHORIZATION","status":"RECORDED","wave_id":"safety-gates"}`. A fresh CLI process read persisted `WAVE_AUTHORIZED` state and `next` returned `ACTION_REQUIRED` for Architect/`technical-design`, transitioning legitimately to `TECHSPEC_REQUIRED`. Thus the fresh process recognized the persisted approval and progression became allowed without manual state editing.

## S4 invalid-authority rejection

**PASS.** At the still-open Wave-start gate, the isolated invalid case used the correct gate and evidence but `--authority-wave wrong-wave`. Exact public response: `{"reason":"authority wave does not match controller wave","status":"INVALID"}`. Fresh `status` remained `WAVE_AUTHORIZED` with no active operation; `next` still returned `HUMAN_ACTION` for `WAVE_START_AUTHORIZATION`. The invalid record was not accepted and did not advance the lifecycle.

## S5 fresh-host recovery

**PASS.** After the legitimate persisted approval, a public Architect operation `s5-architect` was acquired and completed against a SHA-256-bound `docs/waves/safety-gates/TECHSPEC.md`. Completion returned `{"state":"AWAITING_TECHSPEC_APPROVAL","status":"COMPLETED","wave_id":"safety-gates"}`.

A completely fresh CLI process then ran `status`, `reconcile`, and `next` against the same fixture. It recovered `AWAITING_TECHSPEC_APPROVAL` with no active operation. Both `reconcile` and `next` returned `{"gate":"TECHSPEC_APPROVAL","status":"HUMAN_ACTION","wave_id":"safety-gates"}`. It neither duplicated the completed Architect work nor crossed the new human gate; the legitimate next action was stable from repository artifacts alone.

## S6 unresolved-writer behavior

**PASS.** Public `begin-operation --operation-id s6-writer` legitimately acquired Developer writer `s6-writer` for `TASK-6`, persisted in `TASK_IMPLEMENTATION`, and was intentionally left unresolved. A fresh process reported that active writer in `status`; `reconcile` returned `{"reason":"active operation requires resolved result","status":"BLOCKED","wave_id":"safety-s6"}`, and `next` returned `{"reason":"operation is active","status":"BLOCKED","wave_id":"safety-s6"}`. A second public acquisition returned `{"reason":"known active writer","status":"REJECT"}`. The lease was neither cleared nor bypassed and no conflicting writer began.

## Production repository integrity

No production Wave was used. No Controller, `tests/bootstrap`, `src/engineering_flow`, Wave 3, Skill, or prior experiment artifact changed. No commit or push occurred. The only intended persistent change is this report.

## Failures / blockers

None.

## Remaining risks

This focused experiment does not validate role quality, remediation loops, reviewer output restraint, Wave Review, or production-Wave execution. It validates only the six listed Controller safety/recovery behaviors.

## Recommendation

READY_FOR_WAVE_REVIEW_EXPERIMENT
