import json
import unittest
from unittest import mock

from engineering_flow.domain import WorkflowStatus
from engineering_flow.repository import control_state_fingerprint
from engineering_flow.review import ReviewAttemptOrchestrator, ReviewRecoveryService
from engineering_flow.runtime import RuntimeExecutionResult, TerminalState
from tests import test_mds5_slice3 as slice3


class NeverReviewer:
    provider = "never-reviewer"

    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        raise AssertionError("recovery must not dispatch")


class Mds5Slice4BRecoveryTests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare

    passed = slice3.Mds5Slice3Tests.passed

    def retained(self):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        resolver = ReviewAttemptOrchestrator(self.store, NeverReviewer())._resolver()
        review = resolver.resolve(workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        intent = self.store.create_review_intent(workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256, authority_sha256=review.authority_sha256,
            verification_evidence_sha256=review.verification["verification_evidence_sha256"],
            request_hash=review.request_hash, repository_fingerprint=review.verification["repository_fingerprint"],
            protected_control_sha256=control_state_fingerprint(self.root))
        return workflow, verification, intent

    def assert_no_side_effect_work(self):
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM operations WHERE kind IN ('fix','commit','push','pr')").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM task_cycles").fetchone()[0], 0)

    def test_active_attempt_blocks_new_dispatch_and_recovery_dispatches_nothing(self):
        workflow, verification, _ = self.retained()
        runtime = NeverReviewer()
        with self.assertRaises(Exception):
            ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
                task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(runtime.requests, [])
        self.assertEqual(ReviewRecoveryService(self.store).recover(workflow.id), "ambiguous_evidence")
        self.assertEqual(runtime.requests, [])
        self.assert_no_side_effect_work()

    def test_dead_known_unchanged_provider_failure_projects_review_failed(self):
        workflow, _, intent = self.retained()
        self.store._connection.execute("UPDATE executions SET lifecycle='failed',failure_classification='provider',failure_detail='exited' WHERE id=?", (intent["execution_id"],))
        self.assertEqual(ReviewRecoveryService(self.store).recover(workflow.id), "provider_runtime_failure")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.REVIEW_FAILED)
        self.assert_no_side_effect_work()

    def test_unproven_persisted_valid_terminal_result_fails_closed(self):
        workflow, _, intent = self.retained()
        state = self.store._connection.execute("""SELECT o.status,e.lifecycle
            FROM operations o JOIN executions e ON e.id=o.related_record_id WHERE o.id=?""",
            (intent["operation_id"],)).fetchone()
        self.assertEqual(tuple(state), ("pending", "intent"))
        self.store._connection.execute("UPDATE executions SET terminal_result=? WHERE id=?", (json.dumps(self.passed), intent["execution_id"]))
        recovery = ReviewRecoveryService(self.store)
        self.assertEqual(recovery.recover(workflow.id), "ambiguous_evidence")
        self.assertEqual(recovery.recover(workflow.id), "already_terminal")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM events WHERE type='review.attempt.terminal'").fetchone()[0], 0)

    def test_live_or_ownership_uncertain_execution_fails_closed(self):
        workflow, _, _ = self.retained()
        self.assertEqual(ReviewRecoveryService(self.store).recover(workflow.id), "ambiguous_evidence")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)

    def test_repository_drift_fails_closed(self):
        workflow, _, _ = self.retained()
        (self.root / "source.py").write_text("drift\n")
        self.assertEqual(ReviewRecoveryService(self.store).recover(workflow.id), "protected_state_drift")

    def test_corrupt_durable_ownership_fails_closed(self):
        workflow, _, intent = self.retained()
        self.store._connection.execute("UPDATE operations SET related_record_id='wrong' WHERE id=?", (intent["operation_id"],))
        self.assertEqual(ReviewRecoveryService(self.store).recover(workflow.id), "ambiguous_evidence")

    def test_malformed_history_is_preserved_and_exact_repeat_is_suppressed(self):
        workflow, _, _ = self.retained()
        self.store._connection.execute("UPDATE review_attempts SET abnormal_evidence_json='not-json'")
        recovery = ReviewRecoveryService(self.store)
        self.assertEqual(recovery.recover(workflow.id), "ambiguous_evidence")
        evidence = self.store._connection.execute("SELECT abnormal_evidence_json FROM review_attempts").fetchone()[0]
        self.assertEqual(json.loads(evidence)["historical_evidence_raw"], "not-json")
        self.assertEqual(recovery.recover(workflow.id), "already_terminal")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM events WHERE type='review.attempt.abnormal'").fetchone()[0], 1)

    def test_recovery_persistence_fault_rolls_back(self):
        workflow, _, _ = self.retained()
        real = self.store._event_unlocked
        def fail(*args, **kwargs):
            if args[2] == "review.attempt.abnormal":
                raise RuntimeError("recovery fault")
            return real(*args, **kwargs)
        with mock.patch.object(self.store, "_event_unlocked", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "recovery fault"):
                ReviewRecoveryService(self.store).recover(workflow.id)
        self.assertEqual(self.store._connection.execute("SELECT status FROM review_attempts").fetchone()[0], "reviewing")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.REVIEWING)
