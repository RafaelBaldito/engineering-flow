"""Focused MDS #6 Slice 6.6 continuation and safe-presentation tests."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from engineering_flow import cli
from engineering_flow.domain import WorkflowStatus
from engineering_flow.fix import FixAttemptOrchestrator, FixContinuationService
from engineering_flow.presentation import OutputMode, render_result
from engineering_flow.review import ReviewAttemptOrchestrator
from tests import test_mds5_slice3 as slice3
from tests.test_mds6_slice3 import FixRuntime


class NeverRuntime:
    provider = "never"

    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        raise AssertionError("recovery must not dispatch")


class Mds6Slice6Tests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare

    changes = {"outcome": "CHANGES_REQUESTED", "summary": "Correct guard.", "findings": [
        {"id": "R-1", "severity": "blocking", "category": "correctness", "description": "Guard.",
         "path": "source.py", "line": 1, "requirement_reference": "acceptance 1"},
    ]}

    def source(self):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        ReviewAttemptOrchestrator(self.store, slice3.RecordingReviewer(self.changes)).run_once(
            workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        return workflow, verification

    def test_changes_requested_continuation_dispatches_one_fix_then_only_verifies(self):
        workflow, verification = self.source()
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        self.assertEqual(FixContinuationService(self.store, runtime, max_review_cycles=2).continue_once(workflow.id),
                         "dispatched")
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_VERIFIED)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 1)

    def test_active_fix_continuation_recovers_with_zero_dispatch(self):
        workflow, verification = self.source()
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]})
        FixAttemptOrchestrator(self.store, runtime, before_dispatch=lambda: None).run_once(
            workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256, max_review_cycles=2)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.FIXING)
        never = NeverRuntime()
        FixContinuationService(self.store, never, max_review_cycles=2).continue_once(workflow.id)
        self.assertEqual(never.requests, [])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        # The retained UNKNOWN row remains recovery-only on every later resume.
        FixContinuationService(self.store, never, max_review_cycles=2).continue_once(workflow.id)
        self.assertEqual(never.requests, [])

    def test_status_and_logs_project_safe_remediation_trail_as_one_json_document(self):
        workflow, verification = self.source()
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        FixContinuationService(self.store, runtime, max_review_cycles=2).continue_once(workflow.id)
        payload = cli._workflow_payload(self.store, self.store.get_workflow(workflow.id))
        latest = payload["plan"]["implementation"]["fix"]["latest_attempt"]
        self.assertEqual((latest["source_finding_ids"], latest["remediation_cycle_ordinal"], latest["max_review_cycles"]),
                         (["R-1"], 1, 2))
        payload["events"] = [cli._event_payload(event) for event in self.store.list_events(workflow.id)]
        document = cli._result_document("logs", workflow=self.store.get_workflow(workflow.id), data=payload)
        output = io.StringIO(); render_result(document, mode=OutputMode.JSON, stream=output)
        parsed = json.loads(output.getvalue())
        self.assertEqual(parsed["plan"]["implementation"]["fix"]["latest_attempt"]["verification_classification"], "verified")
        rendered = output.getvalue()
        self.assertNotIn("provider-session", rendered)
        self.assertNotIn("pid", rendered.casefold())
        human = io.StringIO(); render_result(document, mode=OutputMode.HUMAN, stream=human)
        self.assertIn("FIX", human.getvalue())
        self.assertIn("R-1", human.getvalue())
        self.assertIn("no acceptance", human.getvalue())

    def test_cli_routes_changes_requested_to_service_without_prompt_or_review(self):
        workflow, _ = self.source(); self.store.set_selected_workflow_id(workflow.id)
        args = cli.build_parser().parse_args(["resume", "--repo", str(self.root), "--json"])
        calls = []
        config = SimpleNamespace(repository_path=str(self.root), max_review_cycles=2)
        plan = SimpleNamespace(runtime=NeverRuntime())
        with (mock.patch.object(cli, "load_config", return_value=config),
              mock.patch.object(cli, "_services", return_value=(self.store, None, None, plan)),
              mock.patch.object(cli, "_continue_fix", side_effect=lambda *a, **kw: calls.append((a, kw)) or self.store.get_workflow(workflow.id))):
            document, exit_code = cli._run_command(args)
        self.assertEqual((exit_code, document["status"], len(calls)), (0, "task_changes_requested", 1))
