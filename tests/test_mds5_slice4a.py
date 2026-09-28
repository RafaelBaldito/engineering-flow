import unittest
from unittest import mock

from engineering_flow.domain import FailureClassification, WorkflowStatus
from engineering_flow.review import ReviewAttemptOrchestrator
from engineering_flow.runtime import RuntimeExecutionResult, TerminalState
from tests import test_mds4_slice3 as mds4


class AbnormalReviewer:
    provider = "abnormal-reviewer"

    def __init__(self, result=None, error=None, mutate=None):
        self.result, self.error, self.mutate, self.requests = result, error, mutate, []

    def execute(self, request):
        self.requests.append(request)
        if self.mutate:
            self.mutate()
        if self.error:
            raise self.error
        return self.result


class Mds5Slice4AClassificationTests(unittest.TestCase):
    setUp = mds4.Mds4Slice3RunnerTests.setUp
    tearDown = mds4.Mds4Slice3RunnerTests.tearDown
    prepare = mds4.Mds4Slice3RunnerTests.prepare

    def verified(self):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        return workflow, verification

    def run_review(self, runtime):
        workflow, verification = self.verified()
        result = ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        return workflow, result

    def assert_stopped(self, workflow, runtime, classification, outcome):
        self.assertEqual(len(runtime.requests), 1)
        row = self.store._connection.execute("SELECT status,outcome,abnormal_classification FROM review_attempts").fetchone()
        self.assertEqual(tuple(row), ("terminal", outcome, classification))
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM operations WHERE kind IN ('fix','commit','push','pr')").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM task_cycles").fetchone()[0], 0)

    def test_known_provider_failure_projects_review_failed_without_findings_or_retry(self):
        runtime = AbnormalReviewer(RuntimeExecutionResult("abnormal-reviewer", "s", None, None,
            TerminalState.FAILED, None, failure_classification=FailureClassification.PROVIDER,
            failure_detail="provider exited"))
        workflow, result = self.run_review(runtime)
        self.assertIsNone(result)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.REVIEW_FAILED)
        self.assert_stopped(workflow, runtime, "provider_runtime_failure", "REVIEW_FAILED")

    def test_interruption_is_human_attention_and_is_not_redispatched(self):
        runtime = AbnormalReviewer(error=KeyboardInterrupt())
        workflow, verification = self.verified()
        runner = ReviewAttemptOrchestrator(self.store, runtime)
        with self.assertRaises(KeyboardInterrupt):
            runner.run_once(workflow.id, task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assert_stopped(workflow, runtime, "interrupted", "HUMAN_ATTENTION")
        with self.assertRaises(Exception):
            runner.run_once(workflow.id, task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(len(runtime.requests), 1)

    def test_malformed_result_is_human_attention_without_synthesized_findings(self):
        runtime = AbnormalReviewer(RuntimeExecutionResult("abnormal-reviewer", "s", None, None,
            TerminalState.SUCCEEDED, {"outcome": "REVIEW_PASSED", "summary": "bad", "findings": [{"bad": True}]}))
        workflow, result = self.run_review(runtime)
        self.assertIsNone(result)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assert_stopped(workflow, runtime, "malformed_result", "HUMAN_ATTENTION")

    def test_repository_drift_is_human_attention_not_a_review_finding(self):
        runtime = AbnormalReviewer(RuntimeExecutionResult("abnormal-reviewer", "s", None, None,
            TerminalState.SUCCEEDED, {"outcome": "REVIEW_PASSED", "summary": "ok", "findings": []}),
            mutate=lambda: (self.root / "source.py").write_text("drift\n"))
        workflow, result = self.run_review(runtime)
        self.assertIsNone(result)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assert_stopped(workflow, runtime, "protected_state_drift", "HUMAN_ATTENTION")

    def test_control_state_drift_is_human_attention_not_a_review_finding(self):
        runtime = AbnormalReviewer(RuntimeExecutionResult("abnormal-reviewer", "s", None, None,
            TerminalState.SUCCEEDED, {"outcome": "REVIEW_PASSED", "summary": "ok", "findings": []}),
            mutate=lambda: (self.root / ".engineering-flow" / "control-state").write_text("drift\n"))
        workflow, result = self.run_review(runtime)
        self.assertIsNone(result)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assert_stopped(workflow, runtime, "protected_state_drift", "HUMAN_ATTENTION")

    def test_inconsistent_durable_ownership_fails_closed(self):
        runtime = AbnormalReviewer(RuntimeExecutionResult("abnormal-reviewer", "s", None, None,
            TerminalState.SUCCEEDED, {"outcome": "REVIEW_PASSED", "summary": "bad", "findings": [{"bad": True}]}))
        workflow, verification = self.verified()
        real = self.store.finish_review_abnormal_attempt
        def corrupt_then_finish(attempt_id, **kwargs):
            self.store._connection.execute("UPDATE operations SET related_record_id='wrong' WHERE kind='review'")
            return real(attempt_id, **kwargs)
        with mock.patch.object(self.store, "finish_review_abnormal_attempt", side_effect=corrupt_then_finish):
            self.assertIsNone(ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
                task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM events WHERE type='review.attempt.unsafe'").fetchone()[0], 1)

    def test_abnormal_terminal_event_fault_rolls_back_all_owned_projections(self):
        runtime = AbnormalReviewer(RuntimeExecutionResult("abnormal-reviewer", "s", None, None,
            TerminalState.FAILED, None, failure_detail="provider exited"))
        workflow, verification = self.verified()
        real = self.store._event_unlocked
        def fail_event(*args, **kwargs):
            if args[2] == "review.attempt.abnormal":
                raise RuntimeError("abnormal fault")
            return real(*args, **kwargs)
        with mock.patch.object(self.store, "_event_unlocked", side_effect=fail_event):
            with self.assertRaisesRegex(RuntimeError, "abnormal fault"):
                ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
                    task_contract_id=verification.producer.task_contract_id,
                    task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(self.store._connection.execute("SELECT status,outcome FROM review_attempts").fetchone()[:], ("reviewing", None))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.REVIEWING)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
