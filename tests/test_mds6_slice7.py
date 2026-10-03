"""Vertical acceptance for the complete bounded MDS #6 remediation loop."""
import io
import json
import sys
import unittest

from engineering_flow import cli
from engineering_flow.domain import Role, WorkKind, WorkflowStatus
from engineering_flow.fix import FixAttemptOrchestrator, FixContinuationService
from engineering_flow.presentation import OutputMode, render_result
from engineering_flow.review import ReviewContinuationService
from tests import test_mds5_slice3 as slice3
from tests.test_mds6_slice3 import FixRuntime
from tests.test_mds6_slice6 import NeverRuntime


class Mds6Slice7AcceptanceTests(unittest.TestCase):
    """Exercise the public continuation boundaries with real V2 evidence."""

    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare

    changes_one = slice3.Mds5Slice3Tests.changes
    changes_two = {"outcome": "CHANGES_REQUESTED", "summary": "Correct the next guard.", "findings": [{
        "id": "R-2", "severity": "blocking", "category": "correctness",
        "description": "The repaired guard misses another input.", "path": "source.py", "line": 1,
        "requirement_reference": "acceptance 1",
    }]}
    passed = slice3.Mds5Slice3Tests.passed

    def changes_requested(self, commands=(("/bin/true",),), *, payload=None):
        workflow, verification, verifier = self.prepare([list(command) for command in commands])
        self.assertEqual(verifier.run(verification).value, "verified")
        reviewer = slice3.RecordingReviewer(payload or self.changes_one)
        ReviewContinuationService(self.store, reviewer).continue_once(workflow.id)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_CHANGES_REQUESTED)
        return workflow, verification, reviewer

    def fix_runtime(self, *, value="fixed", finding_id="R-1"):
        return FixRuntime(self.root, {"summary": value, "addressed_blocking_finding_ids": [finding_id]},
            mutate=lambda: (self.root / "source.py").write_text(f"{value}\n"))

    def test_successful_remediation_requires_verify_then_later_fresh_independent_review_pass(self):
        workflow, _, first_reviewer = self.changes_requested()
        fixer = self.fix_runtime()
        self.assertEqual(FixContinuationService(self.store, fixer, max_review_cycles=3).continue_once(workflow.id),
                         "dispatched")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_VERIFIED)
        self.assertEqual(len(first_reviewer.requests), 1)

        final_reviewer = slice3.RecordingReviewer(self.passed)
        self.assertEqual(ReviewContinuationService(self.store, final_reviewer).continue_once(workflow.id), "dispatched")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_REVIEW_PASSED)
        self.assertEqual(len(fixer.requests), 1)
        self.assertEqual(len(final_reviewer.requests), 1)
        self.assertEqual((fixer.requests[0].role, fixer.requests[0].work_kind),
                         (Role.DEVELOPER, WorkKind.FIX))
        self.assertEqual((final_reviewer.requests[0].role, final_reviewer.requests[0].work_kind),
                         (Role.REVIEWER, WorkKind.REVIEW))
        self.assertNotEqual(fixer.requests[0].logical_session_id, final_reviewer.requests[0].logical_session_id)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_attempts").fetchone()[0], 2)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 2)
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM operations WHERE kind IN ('accept', 'dependency_release', 'successor', 'commit', 'push', 'pr')"
        ).fetchone()[0], 0)

    def test_second_changes_requested_round_below_limit_authorizes_one_new_bound_fix(self):
        workflow, _, _ = self.changes_requested()
        first = self.fix_runtime(value="fixed-one")
        FixContinuationService(self.store, first, max_review_cycles=3).continue_once(workflow.id)
        second_reviewer = slice3.RecordingReviewer(self.changes_two)
        ReviewContinuationService(self.store, second_reviewer).continue_once(workflow.id)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_CHANGES_REQUESTED)

        second = self.fix_runtime(value="fixed-two", finding_id="R-2")
        FixContinuationService(self.store, second, max_review_cycles=3).continue_once(workflow.id)
        fixes = self.store._connection.execute("""SELECT remediation_cycle_ordinal,fix_attempt_ordinal
            FROM fix_attempts ORDER BY created_at""").fetchall()
        self.assertEqual([tuple(row) for row in fixes], [(1, 1), (2, 1)])
        self.assertEqual((len(first.requests), len(second.requests)), (1, 1))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_VERIFIED)

    def test_cycle_limit_projects_human_attention_without_another_fix_dispatch(self):
        workflow, _, _ = self.changes_requested()
        FixContinuationService(self.store, self.fix_runtime(), max_review_cycles=2).continue_once(workflow.id)
        ReviewContinuationService(self.store, slice3.RecordingReviewer(self.changes_two)).continue_once(workflow.id)
        blocked = self.fix_runtime(value="must-not-run", finding_id="R-2")
        FixContinuationService(self.store, blocked, max_review_cycles=2).continue_once(workflow.id)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(blocked.requests, [])
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fix_attempts").fetchone()[0], 1)

    def test_post_fix_verify_failure_and_unresolved_fix_recovery_never_retry_or_dispatch(self):
        command = (sys.executable, "-c", "from pathlib import Path; assert Path('source.py').read_text() == 'implemented\\n'")
        workflow, _, reviewer = self.changes_requested((command,))
        failed = self.fix_runtime()
        FixContinuationService(self.store, failed, max_review_cycles=2).continue_once(workflow.id)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        no_retry = NeverRuntime()
        self.assertEqual(FixContinuationService(self.store, no_retry, max_review_cycles=2).continue_once(workflow.id),
                         "not_fixable")
        self.assertEqual(no_retry.requests, [])
        self.assertEqual((len(failed.requests), len(reviewer.requests)), (1, 1))

        self.tearDown(); self.setUp()
        workflow, verification, _ = self.changes_requested()
        unresolved = FixRuntime(self.root, {"summary": "bad", "addressed_blocking_finding_ids": ["wrong"]})
        FixAttemptOrchestrator(self.store, unresolved).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256, max_review_cycles=2)
        recovery_runtime = NeverRuntime()
        FixContinuationService(self.store, recovery_runtime, max_review_cycles=2).continue_once(workflow.id)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(recovery_runtime.requests, [])

    def test_status_and_logs_expose_safe_bound_trail_without_acceptance_or_sensitive_runtime_data(self):
        workflow, _, _ = self.changes_requested()
        FixContinuationService(self.store, self.fix_runtime(), max_review_cycles=2).continue_once(workflow.id)
        payload = cli._workflow_payload(self.store, self.store.get_workflow(workflow.id))
        payload["events"] = [cli._event_payload(event) for event in self.store.list_events(workflow.id)]
        document = cli._result_document("status", workflow=self.store.get_workflow(workflow.id), data=payload)
        rendered = io.StringIO()
        render_result(document, mode=OutputMode.JSON, stream=rendered)
        output = rendered.getvalue()
        parsed = json.loads(output)
        fix = parsed["plan"]["implementation"]["fix"]["latest_attempt"]
        self.assertEqual((fix["source_finding_ids"], fix["remediation_cycle_ordinal"], fix["max_review_cycles"]),
                         (["R-1"], 1, 2))
        self.assertEqual(fix["verification_classification"], "verified")
        self.assertNotIn("provider-session", output)
        self.assertNotIn("pid", output.casefold())
        human = io.StringIO()
        render_result(document, mode=OutputMode.HUMAN, stream=human)
        self.assertIn("no acceptance", human.getvalue())

