import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from engineering_flow import cli
from engineering_flow.domain import WorkflowStatus
from engineering_flow.presentation import OutputMode, render_result
from engineering_flow.review import (ReviewAttemptOrchestrator, ReviewContinuationService,
    ReviewRecoveryService)
from engineering_flow.repository import control_state_fingerprint
from engineering_flow.runtime import RuntimeExecutionResult, TerminalState
from tests import test_mds5_slice3 as slice3


class RecordingReviewer:
    provider = "slice5-reviewer"

    def __init__(self, payload):
        self.payload, self.requests = payload, []

    def execute(self, request):
        self.requests.append(request)
        return RuntimeExecutionResult(self.provider, request.logical_session_id, "provider-session",
            "execution", TerminalState.SUCCEEDED, self.payload)


class NeverReviewer:
    provider = "never"

    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        raise AssertionError("recovery must not dispatch")


class Mds5Slice5CliTests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare
    passed = slice3.Mds5Slice3Tests.passed

    changes = {"outcome": "CHANGES_REQUESTED", "summary": "Correct both guards.", "findings": [
        {"id": "R-2", "severity": "blocking", "category": "correctness", "description": "Second guard.",
         "path": "source.py", "line": 2, "requirement_reference": "acceptance 2"},
        {"id": "R-1", "severity": "advisory", "category": "maintainability", "description": "First note.",
         "path": "source.py", "line": 1, "requirement_reference": "acceptance 1"},
    ]}

    def verified(self):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        return workflow, verification

    def retained(self):
        workflow, verification = self.verified()
        preflight = ReviewAttemptOrchestrator(self.store, NeverReviewer())._resolver().resolve(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        self.store.create_review_intent(workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256,
            authority_sha256=preflight.authority_sha256,
            verification_evidence_sha256=preflight.verification["verification_evidence_sha256"],
            request_hash=preflight.request_hash, repository_fingerprint=preflight.verification["repository_fingerprint"],
            protected_control_sha256=control_state_fingerprint(self.root))
        return workflow

    def payload(self, workflow):
        return cli._workflow_payload(self.store, self.store.get_workflow(workflow.id))

    def assert_no_excluded_work(self):
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM operations WHERE kind IN ('fix','commit','push','pr')").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM task_cycles").fetchone()[0], 0)

    def test_task_verified_resume_dispatches_exactly_one_reviewer(self):
        workflow, _ = self.verified()
        runtime = RecordingReviewer(self.passed)
        self.assertEqual(ReviewContinuationService(self.store, runtime).continue_once(workflow.id), "dispatched")
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_REVIEW_PASSED)
        self.assert_no_excluded_work()

    def test_active_review_resume_recovers_only_with_zero_dispatch(self):
        workflow = self.retained()
        runtime = NeverReviewer()
        self.assertEqual(ReviewContinuationService(self.store, runtime).continue_once(workflow.id), "ambiguous_evidence")
        self.assertEqual(runtime.requests, [])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assert_no_excluded_work()

    def test_resume_cli_routes_verified_workflow_to_review_gateway(self):
        workflow, _ = self.verified()
        self.store.set_selected_workflow_id(workflow.id)
        args = cli.build_parser().parse_args(["resume", "--repo", str(self.root), "--json"])
        calls = []
        plan = SimpleNamespace(runtime=NeverReviewer())
        config = SimpleNamespace(repository_path=str(self.root))
        with (mock.patch.object(cli, "load_config", return_value=config),
              mock.patch.object(cli, "_services", return_value=(self.store, None, None, plan)),
              mock.patch.object(cli, "_continue_review", side_effect=lambda *a, **kw: calls.append((a, kw)) or self.store.get_workflow(workflow.id))):
            document, exit_code = cli._run_command(args)
        self.assertEqual(exit_code, 0)
        self.assertEqual(document["status"], "task_verified")
        self.assertEqual(len(calls), 1)

    def test_review_passed_human_and_json_presentation(self):
        workflow, _ = self.verified()
        ReviewContinuationService(self.store, RecordingReviewer(self.passed)).continue_once(workflow.id)
        payload = self.payload(workflow)
        latest = payload["plan"]["implementation"]["review"]["latest_attempt"]
        self.assertEqual((latest["outcome"], latest["summary"], latest["findings"]),
            ("REVIEW_PASSED", "Contract is satisfied.", []))
        document = cli._result_document("status", workflow=self.store.get_workflow(workflow.id), data=payload)
        output = io.StringIO(); render_result(document, mode=OutputMode.HUMAN, stream=output)
        self.assertIn("REVIEW_PASSED", output.getvalue())
        self.assertIn("not task acceptance", output.getvalue())
        encoded = io.StringIO(); render_result(document, mode=OutputMode.JSON, stream=encoded)
        self.assertEqual(json.loads(encoded.getvalue())["plan"]["implementation"]["review"]["latest_attempt"]["outcome"], "REVIEW_PASSED")

    def test_changes_requested_projects_ordered_findings(self):
        workflow, _ = self.verified()
        ReviewContinuationService(self.store, RecordingReviewer(self.changes)).continue_once(workflow.id)
        latest = self.payload(workflow)["plan"]["implementation"]["review"]["latest_attempt"]
        self.assertEqual([item["finding_id"] for item in latest["findings"]], ["R-2", "R-1"])
        document = cli._result_document("status", workflow=self.store.get_workflow(workflow.id), data=self.payload(workflow))
        output = io.StringIO(); render_result(document, mode=OutputMode.HUMAN, stream=output)
        self.assertLess(output.getvalue().index("R-2"), output.getvalue().index("R-1"))
        self.assertIn("bounded FIX", output.getvalue())
        self.assert_no_excluded_work()

    def test_review_failed_presentation(self):
        workflow = self.retained()
        attempt = self.store.list_review_attempt_projections(workflow.id)[0]
        self.store._connection.execute("UPDATE executions SET lifecycle='failed',failure_classification='provider' WHERE id=(SELECT execution_id FROM review_attempts WHERE id=?)", (attempt["id"],))
        self.assertEqual(ReviewRecoveryService(self.store).recover(workflow.id), "provider_runtime_failure")
        document = cli._result_document("status", workflow=self.store.get_workflow(workflow.id), data=self.payload(workflow))
        output = io.StringIO(); render_result(document, mode=OutputMode.HUMAN, stream=output)
        self.assertIn("REVIEW_FAILED", output.getvalue())

    def test_human_attention_recovery_presentation(self):
        workflow = self.retained()
        self.assertEqual(ReviewRecoveryService(self.store).recover(workflow.id), "ambiguous_evidence")
        document = cli._result_document("logs", workflow=self.store.get_workflow(workflow.id), data=self.payload(workflow))
        output = io.StringIO(); render_result(document, mode=OutputMode.HUMAN, stream=output)
        self.assertIn("HUMAN_ATTENTION", output.getvalue())
        self.assertIn("no Fixer, verifier, or Reviewer dispatch", output.getvalue())

    def test_logs_json_is_one_safe_document(self):
        workflow, _ = self.verified()
        ReviewContinuationService(self.store, RecordingReviewer(self.changes)).continue_once(workflow.id)
        payload = self.payload(workflow)
        payload["events"] = [cli._event_payload(event) for event in self.store.list_events(workflow.id)]
        document = cli._result_document("logs", workflow=self.store.get_workflow(workflow.id), data=payload)
        output = io.StringIO(); render_result(document, mode=OutputMode.JSON, stream=output)
        parsed = json.loads(output.getvalue())
        review_events = [event for event in parsed["events"] if event["type"].startswith("review.")]
        self.assertTrue(review_events)
        self.assertTrue(all("evidence" not in event["payload"] for event in review_events))
        self.assertEqual(parsed["plan"]["implementation"]["review"]["latest_attempt"]["outcome"], "CHANGES_REQUESTED")
