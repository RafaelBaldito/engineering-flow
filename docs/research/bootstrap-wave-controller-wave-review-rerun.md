# Bootstrap Wave Controller Wave Review rerun

## Purpose

Execute the narrow live bootstrap path enabled by public `register-tasks`: approved task plan through accepted tasks and a fresh Wave Reviewer, plus an isolated Wave Reviewer material-drift rejection. This was not a complete integrated dry-run.

## Baseline

Production checkout was clean at `2e85417d2607a34cf6211d7d58441e8e0b4b0ffb` (`2e85417`). `./scripts/env-preflight` reported `READY` using repository-local Python 3.13.15.

## Environment

Linux/WSL. Controller commands used the public CLI with `PYTHONPATH=/home/bal/projects/engineering-flow` and `/home/bal/projects/engineering-flow/.venv/bin/python3`. The one-time disposable initial `WAVE_AUTHORIZED` records used the Controller's existing `initial`/`save` bootstrap facility; every subsequent lifecycle transition used public Controller operations. Reviewer Python validation was constrained with `PYTHONDONTWRITEBYTECODE=1`.

## Disposable fixtures

- `/tmp/wc-wave-review-primary` — two-task live positive-path fixture (`wr-live`).
- `/tmp/wc-wave-review-drift` — separate two-task material-drift fixture (`wr-drift`).

Both were independent Git repositories with a committed empty `README.md` baseline and deliberately minimal untracked Wave artifacts. They are removed during cleanup.

## Task-plan approval and registration

Primary authoritative plan: `tasks/wr-live/TASKS.md`.

- Persisted authority: public `record-authority --gate TASK_PLAN_APPROVAL --decision APPROVE --actor fixture-human --authority-wave wr-live`, with evidence containing the exact `TASKS.md` SHA-256.
- `register-tasks` result: `{"status":"REGISTERED","task_count":2,"wave_id":"wr-live"}`.
- Persisted order/dependencies read by a fresh process: `TASK-ONE` (none), then `TASK-TWO` (`TASK-ONE`).

An attempted `register-tasks` before public `next` had advanced the satisfied approval gate returned `INVALID: task registration is not permitted in the current lifecycle state`; it made no state change. The subsequent public `next` and `register-tasks` completed legitimately.

## Accepted task set

Both registered tasks followed the normal public Developer then Reviewer lifecycle and completed with Controller-accepted `PASS` review envelopes.

- `TASK-ONE`: `tasks/wr-live/reviews/TASK-ONE-REVIEW.md` — PASS.
- `TASK-TWO`: `tasks/wr-live/reviews/TASK-TWO-REVIEW.md` — PASS.

After the second completion, `status` returned `TASK_EXECUTION_REQUIRED`; fresh `reconcile` deterministically advanced to `WAVE_REVIEW_REQUIRED` and returned the Wave Review action. No task was manually accepted.

## Wave Review readiness

A fresh Controller process recognized both registered task records as `PASS`, no remediation was pending, and `reconcile`/`next` returned `ACTION_REQUIRED`, role `Wave Reviewer`, state `WAVE_REVIEW_REQUIRED`. The exact expected artifact was `docs/waves/wr-live/WAVE-REVIEW.md` under this fixture's Controller contract.

## Fresh Wave Reviewer

Child identity: `/root/wave_reviewer_live`.

It was dispatched with `fork_turns="none"`. The factual handoff contained only the Wave scope, PRD/delivery-plan/architecture/TECHSPEC paths, registered task order/dependency, the two authoritative task PASS paths, fixture checkout HEAD `eae206ce8e2e549ebcb529e42679fdf44f33459b`, input fingerprint `59d91bafa48144b9f4280ca38fcc911951f45fc2fc6368279b974cebbcb90914`, expected artifact path, and `PYTHONDONTWRITEBYTECODE=1` validation environment. No developer rationale, task-review reasoning, host conclusion, suggested verdict, or suggested finding was supplied.

## Wave Reviewer write restraint

PASS. Comparison of the Controller's pre-review path snapshot to the child output snapshot showed only `docs/waves/wr-live/WAVE-REVIEW.md` plus the Controller-owned control record changed. No source, test, or task-review path changed.

## Wave Reviewer no-bytecode validation

PASS. A post-review `find` for `__pycache__` content and `*.pyc` produced no paths. The child's reported validation used the supplied no-bytecode environment.

## Wave Review PASS

FAIL. The independent fresh reviewer persisted `docs/waves/wr-live/WAVE-REVIEW.md`, but its verdict was `FIX_REQUIRED`, with one blocking finding: the approved canonical `TASKS.md` remains required by `register-tasks` to use `PENDING`, while the independent Wave Review skill requires task-index status to agree with the authoritative PASS task reviews.

The public Controller completion result was `{"status":"COMPLETED","state":"WAVE_REMEDIATION","wave_id":"wr-live"}`. No Controller acceptance of Wave Review PASS occurred.

## WAVE_ACCEPTED

NOT_EXERCISED. Since independent Wave Review PASS was not produced, `WAVE_ACCEPTED`, its fresh-process recovery, and stopped-at-acceptance behavior were not reachable without remediation or a Controller/specification change, both outside this experiment.

## Wave Reviewer material-drift rejection

PASS. The separate `wr-drift` fixture legitimately progressed through public task-plan approval, `register-tasks`, accepted task lifecycle, and a public active Wave Reviewer operation. It contained expected artifact `docs/waves/wr-drift/WAVE-REVIEW.md`; then the only unauthorized material mutation was `tests/test_fixture_feature.py` (an appended source comment in its test method). The result envelope was built against the actual resulting checkout.

Public `complete-operation` rejected it exactly as:

`{"reason":"invalid result envelope: review operation changed unauthorized paths","status":"HUMAN_ATTENTION","wave_id":"wr-drift"}`

Fresh `status` reported `HUMAN_ATTENTION`; fresh `next` repeated that reason. The Wave was not accepted and did not advance.

## Production repository integrity

No production Wave, including Wave 3, was used or modified. No Controller implementation, `tests/bootstrap`, `src/engineering_flow`, Skills, prior reports, commit, push, or PR changed. The only intended persistent change is this report.

## Failures / blockers

FAIL — live positive acceptance. The new public registration operation legitimately populated Controller state and allowed aggregation to Wave Review, but it leaves the approved task index immutable at its parser-required `PENDING` values. The required independent Wave Review contract treats that task-index/PASS-artifact disagreement as blocking. Consequently a legitimate independent `PASS → Controller → WAVE_ACCEPTED` run cannot be obtained under both current contracts.

## Remaining risks

- A successful independent Wave Review PASS, Controller acceptance, and fresh-host `WAVE_ACCEPTED` recovery remain unexecuted because of the demonstrated contradiction.
- The material-drift rejection was demonstrated with a valid active Controller Wave Review lease and expected artifact, but not with a fresh child reviewer in that negative fixture.

## Recommendation

NEEDS_CONTROLLER_FIX
