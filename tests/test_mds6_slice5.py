"""Focused MDS #6 Slice 6.5 post-FIX deterministic verification tests."""
import sys
import unittest

from engineering_flow.domain import WorkflowStatus
from engineering_flow.fix import FixAttemptOrchestrator
from engineering_flow.review import ReviewAttemptOrchestrator
from tests import test_mds5_slice3 as slice3
from tests.test_mds6_slice3 import FixRuntime


class Mds6Slice5Tests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare
    changes = slice3.Mds5Slice3Tests.changes

    def source(self, commands):
        workflow, verification, verifier = self.prepare(commands)
        self.assertEqual(verifier.run(verification).value, "verified")
        reviewer = slice3.RecordingReviewer(self.changes)
        ReviewAttemptOrchestrator(self.store, reviewer).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        return workflow, verification, reviewer

    def run_fix(self, workflow, verification, runtime):
        return FixAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256, max_review_cycles=2)

    def test_completed_fix_gets_new_bound_deterministic_verify_and_only_that_reestablishes_task_verified(self):
        workflow, verification, reviewer = self.source([["/bin/true"]])
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        self.assertIsNotNone(self.run_fix(workflow, verification, runtime))
        attempts = self.store._connection.execute("""SELECT producer_operation_id,status,classification
            FROM verification_attempts ORDER BY sequence""").fetchall()
        fix = self.store._connection.execute("SELECT id,operation_id,source_review_attempt_id FROM fix_attempts").fetchone()
        self.assertEqual(tuple(attempts[-1][1:]), ("terminal", "verified"))
        self.assertEqual(attempts[-1][0], fix["operation_id"])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_VERIFIED)
        next_review_authority = self.store.load_verified_review_evidence(workflow.id,
            verification.producer.task_contract_id, verification.producer.task_contract_sha256)
        self.assertEqual(next_review_authority["producer_operation_id"], fix["operation_id"])
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 1)
        self.assertEqual(len(reviewer.requests), 1)

    def test_failed_post_fix_verify_stops_at_human_attention_without_fix_or_reviewer_retry(self):
        command = [sys.executable, "-c", "from pathlib import Path; assert Path('source.py').read_text() == 'implemented\\n'"]
        workflow, verification, reviewer = self.source([command])
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        self.run_fix(workflow, verification, runtime)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("""SELECT v.classification FROM verification_attempts v
            JOIN fix_attempts f ON f.operation_id=v.producer_operation_id""").fetchone()[0],
                         "verification_failed")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fix_attempts").fetchone()[0], 1)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 1)
        self.assertEqual(len(reviewer.requests), 1)

    def test_stale_fix_review_binding_fails_closed_without_new_verify_or_reviewer(self):
        workflow, verification, reviewer = self.source([["/bin/true"]])
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        original = self.store.finish_fix_attempt
        def stale(*args, **kwargs):
            original(*args, **kwargs)
            self.store._connection.execute("UPDATE fix_attempts SET source_reviewer_result_sha256=?", ("0" * 64,))
        self.store.finish_fix_attempt = stale
        self.run_fix(workflow, verification, runtime)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_attempts").fetchone()[0], 1)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 1)
        self.assertEqual(len(reviewer.requests), 1)
