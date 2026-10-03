"""Focused MDS #6 Slice 6.2 durable, dispatch-free FIX intent tests."""
import os
import unittest

from engineering_flow.domain import ConflictFailure, Role, ValidationFailure, WorkKind, WorkflowStatus
from engineering_flow.fix import FixPreflightResolver
from engineering_flow.repository import RepositoryInspector, control_state_fingerprint
from engineering_flow.review import ReviewAttemptOrchestrator
from tests import test_mds5_slice3 as slice3


class Mds6Slice2Tests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare
    changes = slice3.Mds5Slice3Tests.changes

    def source(self):
        # Keep the execution path identical to Slice 6.1: only an actual MDS #5
        # terminal CHANGES_REQUESTED result can authorize this store boundary.
        from tests.test_mds5_slice3 import RecordingReviewer
        # ``prepare`` returns the verifier as its third element in the MDS #4 fixture.
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        ReviewAttemptOrchestrator(self.store, RecordingReviewer(self.changes)).run_once(
            workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        resolver = FixPreflightResolver(self.store.load_approved_v2_plan_authority,
            self.store.load_fix_source_review_evidence, 2)
        preflight = resolver.resolve(workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        return workflow, verification, preflight

    def kwargs(self, workflow, verification, preflight, *, limit=2):
        source = preflight.source_review
        inspector = RepositoryInspector(self.root)
        return dict(repository_key=inspector.repository_key(), canonical_root=str(self.root),
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256,
            source_review_attempt_id=source.attempt_id,
            source_reviewer_result_sha256=source.reviewer_result_sha256,
            source_producer_operation_id=source.producer_operation_id,
            source_verification_attempt_id=source.verification_attempt_id,
            source_verification_evidence_sha256=source.verification_evidence_sha256,
            authority_sha256=preflight.authority_sha256, request_hash=preflight.request_hash,
            max_review_cycles=limit, baseline={**inspector.capture().as_payload(),
                "control_state_fingerprint": control_state_fingerprint(self.root)},
            owner_instance_id="fix-owner", owner_pid=os.getpid(), owner_host_id="host",
            requested_profile=preflight.implementation_profile.value, requested_provider="fake")

    def test_one_source_review_creates_exact_fix_intent_with_all_immutable_findings(self):
        workflow, verification, preflight = self.source()
        intent = self.store.create_fix_intent(workflow.id, **self.kwargs(workflow, verification, preflight))
        self.assertTrue(intent["created"])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.FIXING)
        row = self.store._connection.execute("""SELECT source_review_attempt_id,source_reviewer_result_sha256,
            source_producer_operation_id,source_verification_attempt_id,remediation_cycle_ordinal,
            fix_attempt_ordinal,status FROM fix_attempts WHERE id=?""", (intent["attempt_id"],)).fetchone()
        self.assertEqual(tuple(row), (preflight.source_review.attempt_id,
            preflight.source_review.reviewer_result_sha256, preflight.source_review.producer_operation_id,
            preflight.source_review.verification_attempt_id, 1, 1, "fixing"))
        bindings = self.store._connection.execute("""SELECT source_ordinal,finding_id,severity,finding_sha256
            FROM fix_attempt_finding_bindings WHERE fix_attempt_id=? ORDER BY source_ordinal""",
            (intent["attempt_id"],)).fetchall()
        self.assertEqual([(row["source_ordinal"], row["finding_id"], row["severity"]) for row in bindings],
            [(1, "R-1", "blocking")])
        operation = self.store._connection.execute("SELECT kind,work_kind FROM operations WHERE id=?",
            (intent["operation_id"],)).fetchone()
        execution = self.store._connection.execute("SELECT role,work_kind,lifecycle FROM executions WHERE id=?",
            (intent["execution_id"],)).fetchone()
        self.assertEqual(tuple(operation), ("fix", WorkKind.FIX.value))
        self.assertEqual(tuple(execution), (Role.DEVELOPER.value, WorkKind.FIX.value, "intent"))
        lease = self.store.active_workspace_operation_lease(self.kwargs(workflow, verification, preflight)["repository_key"])
        self.assertEqual((lease["operation_kind"], lease["attempt_id"]), ("fix", intent["attempt_id"]))

    def test_duplicate_resume_reuses_only_the_exact_active_intent_and_lease(self):
        workflow, verification, preflight = self.source()
        kwargs = self.kwargs(workflow, verification, preflight)
        first = self.store.create_fix_intent(workflow.id, **kwargs)
        second = self.store.create_fix_intent(workflow.id, **kwargs)
        self.assertFalse(second["created"])
        self.assertEqual({key: second[key] for key in ("attempt_id", "lease_id", "execution_id", "operation_id")},
            {key: first[key] for key in ("attempt_id", "lease_id", "execution_id", "operation_id")})
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fix_attempts").fetchone()[0], 1)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM workspace_operation_leases").fetchone()[0], 1)
        kwargs["request_hash"] = "0" * 64
        with self.assertRaisesRegex(ConflictFailure, "not safely reusable"):
            self.store.create_fix_intent(workflow.id, **kwargs)

    def test_source_substitution_and_cycle_limit_fail_before_writing_intent(self):
        workflow, verification, preflight = self.source()
        kwargs = self.kwargs(workflow, verification, preflight)
        kwargs["source_review_attempt_id"] = "foreign-review"
        with self.assertRaisesRegex(ConflictFailure, "stale or inconsistent"):
            self.store.create_fix_intent(workflow.id, **kwargs)
        kwargs = self.kwargs(workflow, verification, preflight, limit=1)
        with self.assertRaisesRegex(ConflictFailure, "max_review_cycles"):
            self.store.create_fix_intent(workflow.id, **kwargs)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fix_attempts").fetchone()[0], 0)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_CHANGES_REQUESTED)

    def test_altered_or_deleted_immutable_source_findings_fail_closed_before_intent(self):
        workflow, verification, preflight = self.source()
        self.store._connection.execute("DROP TRIGGER review_findings_no_update")
        self.store._connection.execute("UPDATE review_findings SET description='substituted' WHERE review_attempt_id=?",
            (preflight.source_review.attempt_id,))
        with self.assertRaisesRegex(ValidationFailure, "source findings"):
            self.store.create_fix_intent(workflow.id, **self.kwargs(workflow, verification, preflight))
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fix_attempts").fetchone()[0], 0)

    def test_deleted_immutable_source_findings_fail_closed_before_intent(self):
        workflow, verification, preflight = self.source()
        self.store._connection.execute("DROP TRIGGER review_findings_no_delete")
        self.store._connection.execute("DELETE FROM review_findings WHERE review_attempt_id=?",
            (preflight.source_review.attempt_id,))
        with self.assertRaisesRegex(ValidationFailure, "source findings"):
            self.store.create_fix_intent(workflow.id, **self.kwargs(workflow, verification, preflight))
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fix_attempts").fetchone()[0], 0)

    def test_transaction_fault_rolls_back_intent_bindings_lease_projections_and_event(self):
        workflow, verification, preflight = self.source()
        tables = ("fix_attempts", "fix_attempt_finding_bindings", "operations", "executions",
                  "workspace_operation_leases", "events")
        before = {table: self.store._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in tables}
        original = self.store._event_unlocked
        self.store._event_unlocked = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected"))
        try:
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.store.create_fix_intent(workflow.id, **self.kwargs(workflow, verification, preflight))
        finally:
            self.store._event_unlocked = original
        after = {table: self.store._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                 for table in tables}
        self.assertEqual(after, before)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_CHANGES_REQUESTED)
