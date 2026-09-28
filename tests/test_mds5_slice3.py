import unittest

from engineering_flow.domain import Role, ValidationFailure, WorkKind, WorkflowStatus
from engineering_flow.review import ReviewAttemptOrchestrator
from engineering_flow.runtime import RuntimeExecutionResult, TerminalState
from tests import test_mds4_slice3 as mds4


class RecordingReviewer:
    provider = "recording-reviewer"

    def __init__(self, payload, *, mutate=None):
        self.payload, self.mutate, self.requests = payload, mutate, []

    def execute(self, request):
        self.requests.append(request)
        if self.mutate:
            self.mutate()
        return RuntimeExecutionResult(self.provider, request.logical_session_id, "reviewer-provider-session",
            "reviewer-execution", TerminalState.SUCCEEDED, self.payload)


class Mds5Slice3Tests(unittest.TestCase):
    setUp = mds4.Mds4Slice3RunnerTests.setUp
    tearDown = mds4.Mds4Slice3RunnerTests.tearDown
    prepare = mds4.Mds4Slice3RunnerTests.prepare

    passed = {"outcome": "REVIEW_PASSED", "summary": "Contract is satisfied.", "findings": []}
    changes = {"outcome": "CHANGES_REQUESTED", "summary": "Correct the guard.", "findings": [{
        "id": "R-1", "severity": "blocking", "category": "correctness",
        "description": "The guard misses an input.", "path": "source.py", "line": 1,
        "requirement_reference": "acceptance 1"}]}

    def verified(self):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        return workflow, verification

    def run_review(self, payload, **kwargs):
        workflow, verification = self.verified()
        runtime = RecordingReviewer(payload, **kwargs)
        result = ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        return workflow, verification, runtime, result

    def test_pass_is_one_fresh_read_only_reviewer_dispatch_without_developer_continuity(self):
        workflow, verification, runtime, result = self.run_review(self.passed)
        self.assertEqual(result.outcome, "REVIEW_PASSED")
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        developer_session = self.store.get_session(self.store.get_execution(verification.producer.execution_id).session_id)
        self.assertEqual((request.role, request.work_kind), (Role.REVIEWER, WorkKind.REVIEW))
        self.assertIn("read_only", request.required_capabilities)
        self.assertEqual(request.continuity_bundle, {})
        self.assertIsNone(request.resume_provider_session_id)
        self.assertEqual(request.developer_logical_session_id, developer_session.logical_session_id)
        self.assertNotEqual(request.logical_session_id, developer_session.logical_session_id)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_REVIEW_PASSED)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM operations WHERE kind='fix'").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM task_cycles").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)

    def test_changes_requested_is_terminal_and_does_not_start_fix_or_successor(self):
        workflow, _, runtime, result = self.run_review(self.changes)
        self.assertEqual(result.outcome, "CHANGES_REQUESTED")
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_CHANGES_REQUESTED)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 1)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM operations WHERE kind IN ('fix', 'commit', 'push', 'pr')").fetchone()[0], 0)

    def test_malformed_reviewer_result_is_not_a_normal_terminal_result(self):
        malformed = {"outcome": "REVIEW_PASSED", "summary": "no", "findings": [{"bad": True}]}
        workflow, verification = self.verified()
        runtime = RecordingReviewer(malformed)
        self.assertIsNone(ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256))
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)

    def test_pre_dispatch_repository_drift_refuses_before_dispatch(self):
        workflow, verification = self.verified()
        (self.root / "source.py").write_text("drift\n")
        runtime = RecordingReviewer(self.passed)
        with self.assertRaisesRegex(ValidationFailure, "drifted"):
            ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
                task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(runtime.requests, [])
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 0)

    def test_post_dispatch_repository_drift_never_becomes_a_normal_review_result(self):
        workflow, verification = self.verified()
        runtime = RecordingReviewer(self.passed, mutate=lambda: (self.root / "source.py").write_text("drift\n"))
        self.assertIsNone(ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256))
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
