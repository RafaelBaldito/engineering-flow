import unittest
from unittest import mock

from engineering_flow.domain import ConflictFailure, WorkflowStatus
from engineering_flow.review import ReviewPreflightResolver
from tests import test_mds4_slice3 as mds4


class Mds5Slice2Tests(unittest.TestCase):
    setUp = mds4.Mds4Slice3RunnerTests.setUp
    tearDown = mds4.Mds4Slice3RunnerTests.tearDown
    prepare = mds4.Mds4Slice3RunnerTests.prepare

    def preflight(self):
        workflow, verification, orchestrator = self.prepare([["/bin/true"]])
        self.assertEqual(orchestrator.run(verification).value, "verified")
        review = ReviewPreflightResolver(self.store.load_approved_v2_plan_authority,
            self.store.load_successful_implementation_producer,
            self.store.load_verified_review_evidence).resolve(workflow.id,
                task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        return workflow, verification, review

    @staticmethod
    def changes():
        return {"outcome": "CHANGES_REQUESTED", "summary": "Two corrections are needed.", "findings": [
            {"id": "R-2", "severity": "advisory", "category": "maintainability",
             "description": "Name the boundary.", "path": "source.py", "line": 1,
             "requirement_reference": None},
            {"id": "R-1", "severity": "blocking", "category": "correctness",
             "description": "Check the input.", "path": "source.py", "line": 2,
             "requirement_reference": "acceptance 1"}]}

    @staticmethod
    def passed():
        return {"outcome": "REVIEW_PASSED", "summary": "The verified task meets its contract.", "findings": []}

    def create(self, workflow, review):
        return self.store.create_review_intent(workflow.id,
            task_contract_id=review.producer.task_contract_id,
            task_contract_sha256=review.producer.task_contract_sha256,
            authority_sha256=review.authority_sha256,
            verification_evidence_sha256=review.verification["verification_evidence_sha256"],
            request_hash=review.request_hash,
            repository_fingerprint=review.verification["repository_fingerprint"])

    def test_pass_persists_exact_operation_execution_and_stops_before_acceptance_or_successor(self):
        workflow, _, review = self.preflight()
        intent = self.create(workflow, review)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.REVIEWING)
        self.store.finish_review_attempt(intent["attempt_id"], reviewer_result=self.passed())
        attempt = self.store._connection.execute("SELECT * FROM review_attempts").fetchone()
        operation = self.store._connection.execute("SELECT * FROM operations WHERE id=?", (intent["operation_id"],)).fetchone()
        execution = self.store._connection.execute("SELECT * FROM executions WHERE id=?", (intent["execution_id"],)).fetchone()
        self.assertEqual((attempt["status"], attempt["outcome"]), ("terminal", "REVIEW_PASSED"))
        self.assertEqual((attempt["authority_sha256"], attempt["verification_evidence_sha256"],
                          attempt["repository_fingerprint"]),
            (review.authority_sha256, review.verification["verification_evidence_sha256"],
             review.verification["repository_fingerprint"]))
        self.assertEqual((operation["kind"], operation["related_record_id"], operation["status"]),
            ("review", execution["id"], "completed"))
        self.assertEqual((execution["role"], execution["lifecycle"]), ("reviewer", "completed"))
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_REVIEW_PASSED)
        self.assertEqual(self.store._connection.execute("SELECT status FROM task_implementation_states").fetchone()[0], "review_passed")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM operations WHERE kind='fix'").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM task_cycles").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM events WHERE type='review.attempt.terminal'").fetchone()[0], 1)

    def test_changes_requested_persists_ordered_immutable_findings_and_stops(self):
        workflow, _, review = self.preflight()
        intent = self.create(workflow, review)
        self.store.finish_review_attempt(intent["attempt_id"], reviewer_result=self.changes())
        rows = self.store._connection.execute("SELECT ordinal,finding_id,severity FROM review_findings ORDER BY ordinal").fetchall()
        self.assertEqual([tuple(row) for row in rows], [(1, "R-2", "advisory"), (2, "R-1", "blocking")])
        self.assertEqual(self.store._connection.execute(
            "SELECT verification_attempt_id FROM review_attempts").fetchone()[0],
            review.verification["attempt_id"])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_CHANGES_REQUESTED)
        self.assertEqual(self.store._connection.execute("SELECT status FROM task_implementation_states").fetchone()[0], "changes_requested")
        with self.assertRaises(Exception):
            self.store._connection.execute("UPDATE review_findings SET description='altered' WHERE ordinal=1")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM operations WHERE kind='fix'").fetchone()[0], 0)

    def test_illegal_transitions_and_mismatched_authority_or_evidence_fail_closed(self):
        workflow, _, review = self.preflight()
        with self.assertRaises(ConflictFailure):
            self.store.create_review_intent(workflow.id, task_contract_id=review.producer.task_contract_id,
                task_contract_sha256=review.producer.task_contract_sha256, authority_sha256="0" * 64,
                verification_evidence_sha256=review.verification["verification_evidence_sha256"],
                request_hash=review.request_hash, repository_fingerprint=review.verification["repository_fingerprint"])
        intent = self.create(workflow, review)
        with self.assertRaisesRegex(ConflictFailure, "authority|evidence"):
            self.store._connection.execute("UPDATE review_attempts SET verification_evidence_sha256=?", ("0" * 64,))
            self.store.finish_review_attempt(intent["attempt_id"], reviewer_result=self.passed())
        self.store._connection.execute("UPDATE review_attempts SET verification_evidence_sha256=?",
            (review.verification["verification_evidence_sha256"],))
        bad_pass = {**self.passed(), "findings": [self.changes()["findings"][1]]}
        with self.assertRaises(Exception):
            self.store.finish_review_attempt(intent["attempt_id"], reviewer_result=bad_pass)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.REVIEWING)

    def test_intent_and_terminal_event_faults_roll_back_every_owned_projection(self):
        workflow, _, review = self.preflight()
        real = self.store._event_unlocked
        def fail_intent(*args, **kwargs):
            if args[2] == "review.attempt.created":
                raise RuntimeError("intent fault")
            return real(*args, **kwargs)
        with mock.patch.object(self.store, "_event_unlocked", side_effect=fail_intent):
            with self.assertRaisesRegex(RuntimeError, "intent fault"):
                self.create(workflow, review)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_attempts").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM operations WHERE kind='review'").fetchone()[0], 0)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_VERIFIED)
        intent = self.create(workflow, review)
        def fail_terminal(*args, **kwargs):
            if args[2] == "review.attempt.terminal":
                raise RuntimeError("terminal fault")
            return real(*args, **kwargs)
        with mock.patch.object(self.store, "_event_unlocked", side_effect=fail_terminal):
            with self.assertRaisesRegex(RuntimeError, "terminal fault"):
                self.store.finish_review_attempt(intent["attempt_id"], reviewer_result=self.changes())
        self.assertEqual(self.store._connection.execute("SELECT status,outcome FROM review_attempts").fetchone()[:], ("reviewing", None))
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM review_findings").fetchone()[0], 0)
        self.assertEqual(self.store._connection.execute("SELECT status FROM operations WHERE id=?", (intent["operation_id"],)).fetchone()[0], "pending")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.REVIEWING)
