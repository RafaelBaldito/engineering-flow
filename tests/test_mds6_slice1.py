"""Focused MDS #6 Slice 6.1 authority and advisory-result tests."""
import copy
import unittest

from engineering_flow.domain import ConflictFailure, ImplementationProfile, ValidationFailure, WorkflowStatus
from engineering_flow.fix import FixPreflightResolver, parse_fix_result
from engineering_flow.review import ReviewAttemptOrchestrator
from tests import test_mds5_slice3 as slice3


class RecordingReviewer(slice3.RecordingReviewer):
    pass


class Mds6Slice1Tests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare
    changes = slice3.Mds5Slice3Tests.changes

    def changes_requested(self):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        runtime = RecordingReviewer(self.changes)
        ReviewAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_CHANGES_REQUESTED)
        return workflow, verification, runtime

    def resolver(self, limit=2, loader=None):
        return FixPreflightResolver(self.store.load_approved_v2_plan_authority,
            loader or self.store.load_fix_source_review_evidence, limit)

    def test_exact_immutable_source_review_and_findings_resolve_without_writes(self):
        workflow, verification, runtime = self.changes_requested()
        before = {table: self.store._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("operations", "executions", "review_attempts", "review_findings", "events")}
        preflight = self.resolver().resolve(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(preflight.source_review.blocking_finding_ids, ("R-1",))
        self.assertEqual(preflight.source_review.review_cycle, 1)
        self.assertEqual(preflight.implementation_profile, ImplementationProfile.EFFICIENT)
        self.assertTrue(preflight.request_hash)
        self.assertEqual(runtime.requests[0].work_kind.value, "review")
        after = {table: self.store._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                 for table in before}
        self.assertEqual(after, before)

    def test_stale_and_duplicate_source_evidence_fail_closed_before_any_write(self):
        workflow, verification, _ = self.changes_requested()
        source = self.store.load_fix_source_review_evidence(workflow.id,
            verification.producer.task_contract_id, verification.producer.task_contract_sha256)
        stale = copy.deepcopy(source); stale["reviewer_result_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValidationFailure, "stale or mismatched"):
            self.resolver(loader=lambda *_: stale).resolve(workflow.id,
                task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        with self.assertRaisesRegex(ValidationFailure, "invalid shape"):
            self.resolver(loader=lambda *_: {"sources": [source, source]}).resolve(workflow.id,
                task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)

    def test_planning_changes_requested_and_cycle_limit_cannot_authorize_fix(self):
        workflow, verification, _ = self.changes_requested()
        self.store._connection.execute("UPDATE workflows SET stage='plan',status='changes_requested' WHERE id=?", (workflow.id,))
        with self.assertRaisesRegex(ConflictFailure, "not at V2 PLAN_APPROVED authority"):
            self.resolver().resolve(workflow.id, task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        self.store._connection.execute("UPDATE workflows SET stage='task_execution',status='task_changes_requested' WHERE id=?", (workflow.id,))
        at_limit = self.resolver(limit=1).resolve(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(at_limit.source_review.review_cycle, 1)

    def test_fix_result_is_strict_advisory_claim_for_every_blocking_finding_in_order(self):
        raw = {"summary": "Corrected the guards.", "addressed_blocking_finding_ids": ["R-2", "R-1"]}
        result = parse_fix_result(raw, source_blocking_finding_ids=("R-2", "R-1"))
        self.assertEqual(result.canonical_payload(), raw)
        for invalid in (
            {"summary": "x", "addressed_blocking_finding_ids": ["R-2", "R-2"]},
            {"summary": "x", "addressed_blocking_finding_ids": ["R-1", "R-2"]},
            {"summary": "x", "addressed_blocking_finding_ids": ["R-2"]},
            {"summary": "x", "addressed_blocking_finding_ids": ["R-2"], "path": "../escape"},
        ):
            with self.assertRaises(ValidationFailure):
                parse_fix_result(invalid, source_blocking_finding_ids=("R-2", "R-1"))

    def test_unsafe_source_finding_path_is_rejected(self):
        workflow, verification, _ = self.changes_requested()
        source = self.store.load_fix_source_review_evidence(workflow.id,
            verification.producer.task_contract_id, verification.producer.task_contract_sha256)
        unsafe = copy.deepcopy(source); unsafe["findings"][0]["path"] = "../escape.py"
        with self.assertRaisesRegex(ValidationFailure, "findings are invalid"):
            self.resolver(loader=lambda *_: unsafe).resolve(workflow.id,
                task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
