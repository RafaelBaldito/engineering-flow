# Bootstrap Wave Controller final smoke rerun

## Purpose

Rerun the bounded integrated composition smoke after the task-plan approval to
registration transition correction. This uses one disposable fixture only; it
does not exercise production Wave 3 or repeat closed negative experiments.

## Baseline

Production was clean at `c39f2ac46e44f5949553d504fe446511470f0e34`
(`c39f2ac`, `fix: align task plan approval with registration`). The
repository-local preflight reported `READY`.

## Prior evidence intentionally not repeated

- `docs/research/bootstrap-wave-controller-safety-recovery-experiment.md`
- `docs/research/bootstrap-wave-controller-deterministic-remediation-experiment.md`
- `docs/research/bootstrap-wave-review-task-authority-contract-fix.md`
- `docs/research/bootstrap-wave-controller-wave-review-acceptance-rerun.md`
- `docs/research/bootstrap-wave-controller-task-plan-registration-transition-fix.md`

Those artifacts remain the evidence for safety/recovery, stale-result
rejection, writer leases, task-registration edge cases, status reconciliation,
Wave Review authority, material-drift rejection, and the focused transition
fix. None of those negative suites was deliberately rerun.

## Environment

Linux/WSL; production `.venv/bin/python3` 3.13.15. The fixture Controller
used the public JSON CLI with
`PYTHONPATH=/home/bal/projects/engineering-flow` and
`PYTHONDONTWRITEBYTECODE=1`. Fixture validation was
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q`.

## Disposable fixture

Exactly one new Git fixture was created at
`/tmp/bootstrap-wave-controller-final-smoke-rerun.eWF48M` with Wave
`smoke`. It contained two tiny greeting tasks and a fixture TECHSPEC. The
Controller control record was initialized for the disposable Wave; after that,
all lifecycle transitions used only public Controller operations. The fixture
was removed during cleanup.

## Task plan and registration

The fixture completed public Wave-start authority, Architect, TECHSPEC
approval, Planner, and then explicit `TASK_PLAN_APPROVAL` for the exact
`tasks/smoke/TASKS.md` SHA-256
`b0381690d7f6ac18a41bd8404093365e405537653115d464abd449a65c84bf0b`.

The approval returned `RECORDED` and persisted
`TASK_EXECUTION_REQUIRED` with the satisfied approval. A fresh Controller
process immediately returned `REGISTERED` for `register-tasks`, without a
manual state edit or a reconcile call. Persisted order was:

1. `TASK-A` — Implement greeting — no dependency.
2. `TASK-B` — Decorate greeting — depends on `TASK-A`.

A fresh Controller saw that identical registration, and public `next`
selected `TASK-A`.

## Task A happy path

Developer identity: `/root/smoke_task_a_developer`. It changed only
`src/greeting.py` and `tests/test_greeting.py`; fixture validation passed
(1 test).

Fresh Reviewer identity: `/root/smoke_task_a_reviewer`, dispatched with
`fork_turns="none"`. Its handoff was factual only and contained no suggested
verdict or Developer rationale. It used `PYTHONDONTWRITEBYTECODE=1`, passed
the fixture suite, wrote only
`tasks/smoke/reviews/TASK-A-REVIEW.md`, and independently returned
`PASS`. The Controller accepted its envelope, persisted the authoritative
PASS receipt, and set Task A runtime status to accepted.

## Task B controlled defect

Developer identity: `/root/smoke_task_b_developer`. It normally implemented
Task B in `src/decorated.py` and its test; validation passed (2 tests).
After the legitimate Developer completion, exactly one fixture-only defect was
injected: `decorated_greeting()` was changed from appending `"!"` to
appending `"?"`.

The deterministic pre-review suite then failed exactly one assertion:
`hello?` was observed where `hello!` was required. The Reviewer was not
told that injection occurred, its location, the changed character, the failed
test result, or an expected finding/verdict.

## Task B first review

Reviewer identity: `/root/smoke_task_b_reviewer_1`, dispatched fresh with
`fork_turns="none"`. It independently identified the incorrect suffix and
returned `FIX_REQUIRED` in
`tasks/smoke/reviews/TASK-B-REVIEW.md`. Its only fixture write was that
authoritative artifact; it used `PYTHONDONTWRITEBYTECODE=1`, and no
`__pycache__` or `.pyc` drift was found. The Controller accepted the
`FIX_REQUIRED` envelope and entered `TASK_FIX_REQUIRED`; Task B was not
accepted.

## Task B remediation

Fixer identity: `/root/smoke_task_b_fixer`. It received Task B, the
authoritative persisted `TASK-B-REVIEW.md` findings, and factual fixture
state only. It changed only `src/decorated.py`, restoring the `"!"`
suffix. The deterministic full fixture suite passed (2 tests), and no task was
marked accepted before re-review.

## Task B fresh re-review

New Reviewer identity: `/root/smoke_task_b_reviewer_2`, distinct from the
first reviewer and dispatched with `fork_turns="none"`. It received factual
task, persisted review, and checkout information, not Fixer reasoning or a
suggested verdict. It used `PYTHONDONTWRITEBYTECODE=1`, wrote only the
authoritative `tasks/smoke/reviews/TASK-B-REVIEW.md`, and independently
returned `PASS`; no bytecode drift was found. The Controller accepted the
envelope and set Task B runtime status to accepted.

## TASKS_READY_FOR_WAVE_REVIEW

PASS. Both registered tasks had Controller runtime `PASS` status and
Controller-validated accepted-review receipts. Public `next` advanced
through `TASKS_READY_FOR_WAVE_REVIEW` to the Wave Reviewer action.

## Wave Review authority consistency

PASS. `TASKS.md` remained the immutable authority for task identity, order,
scope, dependencies, and planning-time `PENDING` values. The Controller was
the runtime-acceptance authority: it supplied accepted status and a matching
PASS receipt for each task. The receipt artifacts were
`tasks/smoke/reviews/TASK-A-REVIEW.md` and
`tasks/smoke/reviews/TASK-B-REVIEW.md`, both with PASS decisions. No
planning-time PENDING marker was treated as runtime status.

## Fresh Wave Reviewer

Child identity: `/root/smoke_wave_reviewer`, dispatched with
`fork_turns="none"`. The factual handoff explicitly separated plan
identity/order/scope from Controller runtime acceptance and the authoritative
task-review artifacts/PASS decisions. It included checkout identity, the
expected `docs/waves/smoke/WAVE-REVIEW.md` path, and
`PYTHONDONTWRITEBYTECODE=1`. It did not include Developer/Fixer reasoning, a
host conclusion, a suggested verdict, or expected findings.

## Independent Wave PASS

PASS. The fresh Wave Reviewer independently ran the two-test fixture suite,
returned `PASS`, and wrote
`docs/waves/smoke/WAVE-REVIEW.md`. Its checkout delta relative to the
Controller lease was exactly that artifact plus the Controller's own state
record; no source, test, task-plan, task-review, or bytecode mutation occurred.

## WAVE_ACCEPTED

The public `complete-operation` accepted the Wave Reviewer PASS envelope and
returned `WAVE_ACCEPTED`.

## Fresh-host recovery

PASS. A completely fresh Controller process returned `WAVE_ACCEPTED` for
`status`, `reconcile`, and `next`. It reopened no task, dispatched no
duplicate Wave Review, and initiated neither final review nor another Wave.

## Workflow stop

PASS. The workflow stopped at Wave acceptance, pending explicit future human
authorization. No commit, push, PR, final-review, or next-Wave action occurred.

## Production repository integrity

Before recording this report, protected production paths were unchanged from
`c39f2ac`: `tools/wave_controller/`, `tests/bootstrap/`,
`src/engineering_flow/`, `.codex/skills/`, and `docs/waves/3/`.
Historical reports were not modified. This report is the sole intended
persistent change; no commit or push was made.

## Failures / blockers

None. The intentional deterministic pre-review test failure was controlled
fixture setup evidence, not a blocker.

## Remaining risks

This remains a deliberately minimal fixture composition smoke. It relies on
the listed separate artifacts for the intentionally un-repeated negative and
recovery scenarios and does not validate production Wave 3 behavior.

## Recommendation

BOOTSTRAP_CONTROLLER_VALIDATED_FOR_SUPERVISED_WAVE_3_PILOT
