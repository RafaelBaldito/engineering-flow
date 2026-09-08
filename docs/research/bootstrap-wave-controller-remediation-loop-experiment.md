# Bootstrap Wave Controller remediation-loop experiment

## Purpose

Run focused live checks for (1) the Developer-to-review remediation loop and (2) rejection of a Reviewer result that includes material source drift. This is not a whole-Wave lifecycle run.

## Baseline

The production checkout was clean at `f6b54b4e08db67e17a12046c31dc5a41bd9e252f` before the experiment.

## Environment

Linux/WSL; repository-local Python 3.13.15; Controller CLI invoked as `PYTHONPATH=/home/bal/projects/engineering-flow .venv/bin/python3 -m tools.wave_controller.cli`.

## Disposable fixtures

- `/tmp/bootstrap-remediation-a1.agA3qx` — abandoned before any review because its Developer implementation completely met its compact contract; removed.
- `/tmp/bootstrap-remediation-a1.vSodZh` — authoritative A1 attempt.
- `/tmp/bootstrap-remediation-a2.DrlxVh` — isolated A2 material-drift scenario.

Fixture provisioning used the Controller's own state writer to create an initial task-ready fixture. After provisioning, all lifecycle progression, operation acquisition, and result submission used only public CLI commands.

## Controller authority

PASS. A1 Developer and Reviewer leases and completions, and A2 Reviewer lease and invalid completion, were all Controller-mediated. No control record was manually edited and no lifecycle state was manually forced after setup.

## Developer execution

PASS. Fresh child `/root/a1_developer_retry` implemented TASK-001 in A1: `src/list_parser.py` and `tests/test_list_parser.py`. It reported `python3 -m unittest discover -s tests -q` passing (5 tests). Its Controller completion `a1-developer` was accepted and moved to `TASK_REVIEW_REQUIRED`.

## Reviewer #1 FIX_REQUIRED

FAIL. New child `/root/a1_reviewer_1` was dispatched with `fork_turns="none"` and only factual task, checkout, and output-path information. It received neither Developer reasoning nor a suggested defect or verdict. It independently ran `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q`, wrote only `tasks/remediation/reviews/TASK-001-REVIEW.md`, and returned PASS rather than the expected FIX_REQUIRED. The Controller accepted `a1-reviewer-1` and returned to `TASK_EXECUTION_REQUIRED`. Thus no persisted FIX_REQUIRED finding existed to authorize a Fixer.

## Fixer remediation

BLOCKED. The Controller did not enter `TASK_FIX_REQUIRED`, because the fresh Reviewer #1 result was PASS. No Fixer could legitimately be dispatched.

## Reviewer #2 PASS

BLOCKED. No re-review was authorized after Reviewer #1's PASS, so no second Reviewer was dispatched. There is consequently no second Reviewer identity to compare with `/root/a1_reviewer_1`.

## Complete remediation-loop result

FAIL. The live A1 path observed was Developer -> fresh Reviewer PASS, not the required Developer -> fresh Reviewer FIX_REQUIRED -> Fixer -> fresh Reviewer PASS. This is an experiment-design execution failure, not evidence that the Controller failed to process a valid FIX_REQUIRED result.

## Reviewer material-drift rejection

PASS. In separate fixture `/tmp/bootstrap-remediation-a2.DrlxVh`, public `begin-operation` acquired Reviewer operation `a2-reviewer-drift` at checkout A with expected artifact `tasks/drift/reviews/TASK-001-REVIEW.md`. The completion checkout contained:

- `tasks/drift/reviews/TASK-001-REVIEW.md` (the legitimate expected artifact)
- `src/component.py` (material unauthorized mutation, changing `VALUE`)

The envelope accurately used the resulting checkout identity and referenced the legitimate review artifact. `complete-operation` returned exactly:

```json
{"reason":"invalid result envelope: review operation changed unauthorized paths","status":"HUMAN_ATTENTION","wave_id":"drift"}
```

Subsequent `status` returned `{"active_operation":null,"state":"HUMAN_ATTENTION","status":"OK","wave_id":"drift"}`. The lifecycle did not advance as a valid review.

## No-bytecode validation

PASS for Reviewer #1. Its required validation used `PYTHONDONTWRITEBYTECODE=1`; Controller acceptance of the review completion also proves the captured reviewer output differed from its input only at the exact review artifact (the Developer-created pre-existing cache files were unchanged). Reviewer #2 was not exercised.

## Production repository integrity

No Controller implementation, `src/engineering_flow`, Wave 3, Skills, or historical dry-run report was changed. No commit or push was performed.

## Failures / blockers

The selected real Developer implementation did not expose a defect to the independent reviewer; Reviewer #1 legitimately returned PASS. That prevents a Controller-authorized Fixer and fresh Reviewer #2 under the stated rules.

## Remaining risks

The live valid FIX_REQUIRED -> Fixer -> fresh PASS transition remains unexercised. Reviewer #2 freshness and no-bytecode behavior remain unexercised. The material-drift rejection is demonstrated.

## Recommendation

NEEDS_REMEDIATION_EXPERIMENT_RERUN

