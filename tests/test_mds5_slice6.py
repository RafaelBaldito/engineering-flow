"""MDS #5 Slice 5.6 vertical acceptance and invariant regression coverage."""

import json
import unittest

from engineering_flow import cli
from engineering_flow.domain import (FailureClassification, Role, ValidationFailure,
    WorkKind, WorkflowStatus)
from engineering_flow.repository import control_state_fingerprint
from engineering_flow.review import (ReviewAttemptOrchestrator, ReviewContinuationService,
    ReviewRecoveryService)
from engineering_flow.runtime import RuntimeExecutionResult, TerminalState
from tests import test_mds5_slice3 as slice3


class RecordingReviewer:
    provider = "slice6-reviewer"

    def __init__(self, result):
        self.result = result
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return self.result(request)


class NeverReviewer:
    provider = "slice6-never"

    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        raise AssertionError("recovery must never dispatch a Reviewer")


class Mds5Slice6AcceptanceTests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare

    passed = slice3.Mds5Slice3Tests.passed
    changes = {"outcome": "CHANGES_REQUESTED", "summary": "Correct both guards.", "findings": [
        {"id": "R-2", "severity": "blocking", "category": "correctness",
         "description": "Second guard.", "path": "source.py", "line": 2,
         "requirement_reference": "acceptance 2"},
        {"id": "R-1", "severity": "advisory", "category": "maintainability",
         "description": "First note.", "path": "source.py", "line": 1,
         "requirement_reference": "acceptance 1"},
    ]}

    def verified(self):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        return workflow, verification

    def retained(self):
        workflow, verification = self.verified()
        preflight = ReviewAttemptOrchestrator(self.store, NeverReviewer())._resolver().resolve(
            workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        intent = self.store.create_review_intent(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256,
            authority_sha256=preflight.authority_sha256,
            verification_evidence_sha256=preflight.verification["verification_evidence_sha256"],
            request_hash=preflight.request_hash,
            repository_fingerprint=preflight.verification["repository_fingerprint"],
            protected_control_sha256=control_state_fingerprint(self.root))
        return workflow, verification, intent

    def assert_no_out_of_scope_work(self):
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM operations WHERE kind IN ('fix','commit','push','pr')").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM task_cycles").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM events WHERE type LIKE 'wave.%' OR type LIKE 'final.%'").fetchone()[0], 0)

    @staticmethod
    def result(payload):
        return lambda request: RuntimeExecutionResult("slice6-reviewer", request.logical_session_id,
            "fresh-reviewer-provider-session", "review-execution", TerminalState.SUCCEEDED, payload)

    def test_resume_happy_path_is_one_independent_read_only_durable_review(self):
        workflow, verification = self.verified()
        runtime = RecordingReviewer(self.result(self.passed))

        self.assertEqual(cli._continue_review(workflow.id, store=self.store, runtime=runtime).status,
            WorkflowStatus.TASK_REVIEW_PASSED)
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        developer = self.store.get_session(
            self.store.get_execution(verification.producer.execution_id).session_id)
        self.assertEqual((request.role, request.work_kind), (Role.REVIEWER, WorkKind.REVIEW))
        self.assertIn("read_only", request.required_capabilities)
        self.assertEqual(request.continuity_bundle, {})
        self.assertIsNone(request.resume_provider_session_id)
        self.assertNotEqual(request.logical_session_id, developer.logical_session_id)
        self.assertEqual(request.developer_logical_session_id, developer.logical_session_id)
        attempt = self.store.list_review_attempt_projections(workflow.id)[0]
        self.assertEqual((attempt["status"], attempt["outcome"], attempt["summary"], attempt["findings"]),
            ("terminal", "REVIEW_PASSED", "Contract is satisfied.", []))
        payload = cli._workflow_payload(self.store, self.store.get_workflow(workflow.id))
        self.assertEqual(payload["plan"]["implementation"]["review"]["latest_attempt"]["outcome"],
            "REVIEW_PASSED")
        self.assert_no_out_of_scope_work()

    def test_resume_changes_requested_retains_ordered_findings_and_stops(self):
        workflow, _ = self.verified()
        runtime = RecordingReviewer(self.result(self.changes))

        self.assertEqual(ReviewContinuationService(self.store, runtime).continue_once(workflow.id), "dispatched")
        attempt = self.store.list_review_attempt_projections(workflow.id)[0]
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_CHANGES_REQUESTED)
        self.assertEqual([finding["finding_id"] for finding in attempt["findings"]], ["R-2", "R-1"])
        self.assertEqual([finding["ordinal"] for finding in attempt["findings"]], [1, 2])
        self.assert_no_out_of_scope_work()

    def test_known_provider_failure_fails_closed_without_findings(self):
        workflow, verification = self.verified()
        failed = RecordingReviewer(lambda request: RuntimeExecutionResult("slice6-reviewer",
            request.logical_session_id, None, None, TerminalState.FAILED, None,
            failure_classification=FailureClassification.PROVIDER, failure_detail="provider exited"))
        self.assertIsNone(ReviewAttemptOrchestrator(self.store, failed).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.REVIEW_FAILED)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
        self.assert_no_out_of_scope_work()

    def test_malformed_result_becomes_human_attention_without_findings(self):
        workflow, verification = self.verified()
        malformed = {"outcome": "REVIEW_PASSED", "summary": "not valid", "findings": [{"bad": True}]}
        runtime = RecordingReviewer(self.result(malformed))
        self.assertIsNone(ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
        self.assert_no_out_of_scope_work()

    def test_drift_prevents_reviewer_execution(self):
        workflow, verification = self.verified()
        runtime = RecordingReviewer(self.result(self.passed))
        (self.root / "source.py").write_text("drift\n")
        with self.assertRaisesRegex(ValidationFailure, "drifted"):
            ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
                task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(runtime.requests, [])
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 0)

    def test_stale_verified_authority_prevents_reviewer_execution(self):
        workflow, verification = self.verified()
        self.store._connection.execute("UPDATE verification_attempts SET authority_sha256=?", ("0" * 64,))
        runtime = RecordingReviewer(self.result(self.passed))
        with self.assertRaisesRegex(ValidationFailure, "stale|inconsistent"):
            ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
                task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(runtime.requests, [])
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 0)

    def test_recovery_is_zero_dispatch_idempotent_and_unproven_results_fail_closed(self):
        workflow, _, intent = self.retained()
        self.store._connection.execute("UPDATE executions SET terminal_result=? WHERE id=?",
            (json.dumps(self.passed), intent["execution_id"]))
        runtime = NeverReviewer()
        continuation = ReviewContinuationService(self.store, runtime)
        self.assertEqual(continuation.continue_once(workflow.id), "ambiguous_evidence")
        self.assertEqual(ReviewRecoveryService(self.store).recover(workflow.id), "already_terminal")
        self.assertEqual(continuation.continue_once(workflow.id), "not_reviewable")
        self.assertEqual(runtime.requests, [])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
        self.assert_no_out_of_scope_work()
