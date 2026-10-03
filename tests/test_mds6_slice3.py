"""Focused MDS #6 Slice 6.3 one-dispatch Developer/FIX tests."""
import os
import unittest
from pathlib import Path

from engineering_flow.domain import Role, WorkKind, WorkflowStatus
from engineering_flow.fix import FixAttemptOrchestrator
from engineering_flow.review import ReviewAttemptOrchestrator
from engineering_flow.runtime import RuntimeExecutionResult, TerminalState
from tests import test_mds5_slice3 as slice3


class FixRuntime:
    provider = "fix-runtime"

    def __init__(self, root, payload, *, mutate=None):
        self.root, self.payload, self.mutate, self.requests = root, payload, mutate, []

    def execute(self, request):
        self.requests.append(request)
        if request.provider_started is not None:
            request.provider_started({"pid": os.getpid(), "process_start": "fixture-start",
                "process_group": os.getpgrp(), "process_session": os.getsid(0)})
        if self.mutate:
            self.mutate()
        return RuntimeExecutionResult(self.provider, request.logical_session_id, "fix-session", "fix-execution",
            TerminalState.SUCCEEDED, self.payload)


class Mds6Slice3Tests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare
    changes = slice3.Mds5Slice3Tests.changes

    def source(self):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        ReviewAttemptOrchestrator(self.store, slice3.RecordingReviewer(self.changes)).run_once(
            workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        return workflow, verification

    def run_fix(self, runtime, workflow, verification, **kwargs):
        return FixAttemptOrchestrator(self.store, runtime, **kwargs).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256, max_review_cycles=2)

    def test_one_workspace_write_developer_fix_records_only_normal_completed_evidence(self):
        workflow, verification = self.source()
        runtime = FixRuntime(self.root, {"summary": "Corrected guard.", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        result = self.run_fix(runtime, workflow, verification)
        self.assertEqual(result.addressed_blocking_finding_ids, ("R-1",))
        self.assertEqual(len(runtime.requests), 1)
        request = runtime.requests[0]
        self.assertEqual((request.role, request.work_kind), (Role.DEVELOPER, WorkKind.FIX))
        self.assertIn("workspace_write", request.required_capabilities)
        self.assertNotIn(Role.REVIEWER, (request.role,))
        evidence = next(Path(path) for path in request.authoritative_input_paths if path.endswith("fix-evidence.json"))
        self.assertIn('"id":"R-1"', evidence.read_text())
        row = self.store._connection.execute("SELECT status,outcome,provider_result_sha256,final_repository_json FROM fix_attempts").fetchone()
        self.assertEqual(tuple(row[:2]), ("completed", "completed")); self.assertTrue(row[2]); self.assertTrue(row[3])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_VERIFIED)
        self.assertIsNone(self.store.active_workspace_operation_lease(
            __import__("engineering_flow.repository", fromlist=["RepositoryInspector"]).RepositoryInspector(self.root).repository_key()))
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_attempts").fetchone()[0], 2)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 1)

    def test_exact_provider_bound_developer_continuity_or_fresh_fallback_never_reuses_reviewer(self):
        workflow, verification = self.source()
        # The original fixture has no persisted Developer provider session, so
        # Slice 6.3 must use a fresh bounded Developer session.
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        self.run_fix(runtime, workflow, verification)
        request = runtime.requests[0]
        self.assertIsNone(request.resume_provider_session_id)
        self.assertEqual(request.continuity_bundle, {})
        reviewer = self.store._connection.execute("SELECT session_id FROM executions WHERE role='reviewer'").fetchone()[0]
        self.assertNotEqual(self.store.get_execution(request.execution_id).session_id, reviewer)

    def test_exact_original_developer_lineage_may_offer_continuity_but_not_reviewer_reuse(self):
        workflow, verification = self.source()
        self.store._connection.execute("UPDATE implementation_attempts SET provider_session_ref='developer-thread' WHERE operation_id=?",
            (verification.producer.operation_id,))
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        runtime.provider = "fake"  # Matches the exact original Developer provider in this fixture.
        self.run_fix(runtime, workflow, verification)
        request = runtime.requests[0]
        self.assertEqual(request.resume_provider_session_id, "developer-thread")
        self.assertIn("review_findings", request.continuity_bundle)
        self.assertEqual(request.role, Role.DEVELOPER)

    def test_pre_dispatch_drift_and_duplicate_intent_never_dispatch_a_second_fixer(self):
        workflow, verification = self.source()
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]})
        result = self.run_fix(runtime, workflow, verification,
            before_dispatch=lambda: (self.root / "source.py").write_text("drift\n"))
        self.assertIsNone(result); self.assertEqual(runtime.requests, [])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.FIXING)
        with self.assertRaisesRegex(Exception, "TASK_CHANGES_REQUESTED"):
            self.run_fix(runtime, workflow, verification)
        self.assertEqual(runtime.requests, [])

    def test_malformed_result_is_not_a_normal_completion(self):
        workflow, verification = self.source()
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["wrong"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        self.assertIsNone(self.run_fix(runtime, workflow, verification))
        self.assertEqual(self.store._connection.execute("SELECT status FROM fix_attempts").fetchone()[0], "fixing")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM operations WHERE kind='verification'").fetchone()[0], 1)

    def test_post_dispatch_manifest_or_ref_drift_never_becomes_normal_fix_completion(self):
        workflow, verification = self.source()
        manifest = self.root / ".engineering-flow" / "verification" / "manifest-v1.json"
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: manifest.write_text('{"changed":true}'))
        self.assertIsNone(self.run_fix(runtime, workflow, verification))
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(self.store._connection.execute("SELECT status,outcome FROM fix_attempts").fetchone()[0], "fixing")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.FIXING)
