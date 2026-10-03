"""Focused MDS #6 Slice 6.4 abnormal FIX recovery tests."""
import json
import unittest
import uuid

from engineering_flow.domain import WorkflowStatus
from engineering_flow.fix import FixAttemptOrchestrator, FixRecoveryService
from engineering_flow.process_identity import HostBootIdentity, ProcessGroupObservation
from engineering_flow.repository import RepositoryInspector, control_state_fingerprint
from engineering_flow.review import ReviewAttemptOrchestrator
from tests import test_mds5_slice3 as slice3
from tests.test_mds6_slice3 import FixRuntime


class Mds6Slice4Tests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare
    changes = slice3.Mds5Slice3Tests.changes

    def unresolved_fix(self):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        ReviewAttemptOrchestrator(self.store, slice3.RecordingReviewer(self.changes)).run_once(
            workflow.id, task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        runtime = FixRuntime(self.root, {"summary": "bad", "addressed_blocking_finding_ids": ["wrong"]})
        FixAttemptOrchestrator(self.store, runtime).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256, max_review_cycles=2)
        row = self.store._connection.execute("SELECT id,lease_id FROM fix_attempts").fetchone()
        snapshot = RepositoryInspector(self.root).capture().as_payload()
        snapshot["control_state_fingerprint"] = control_state_fingerprint(self.root)
        self.store.update_fix_baseline(row["id"], row["lease_id"], snapshot)
        self.store._connection.execute("""UPDATE workspace_operation_leases SET child_pid=101,
            child_process_start='start',child_process_group=101,child_process_session=101 WHERE lease_id=?""",
            (row["lease_id"],))
        return workflow, runtime

    def foreign_fix_lease(self, workflow):
        """Insert a second retained FIX context without borrowing its ownership."""
        operation_id, lease_id = str(uuid.uuid4()), str(uuid.uuid4())
        self.store._connection.execute("""INSERT INTO operations
            (id,idempotency_key,kind,workflow_id,status,related_record_id,created_at,updated_at)
            VALUES (?,?,'fix',?,'pending',NULL,'now','now')""",
            (operation_id, f"foreign-fix:{operation_id}", workflow.id))
        self.store._connection.execute("""INSERT INTO workspace_operation_leases
            (repository_key,lease_id,operation_kind,attempt_id,operation_id,workflow_id,canonical_root,
             owner_instance_id,owner_pid,owner_host_id,owner_boot_id,acquired_at,updated_at)
            VALUES (?,?, 'fix',?,?,?, '/foreign', 'foreign-owner', 1, 'foreign-host', 'foreign-boot', 'now', 'now')""",
            (f"foreign-{lease_id}", lease_id, f"foreign-attempt-{lease_id}", operation_id, workflow.id))
        return lease_id

    def assert_r5_sticky_unknown(self, workflow, runtime, recovery, expected):
        dispatches = len(runtime.requests)
        verification_count = self.store._connection.execute("SELECT count(*) FROM verification_attempts").fetchone()[0]
        self.assertEqual(recovery.recover(workflow.id), expected)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        row = self.store._connection.execute("SELECT status,outcome,abnormal_evidence_json FROM fix_attempts").fetchone()
        self.assertEqual(tuple(row[:2]), ("unknown", "unknown"))
        self.assertEqual(json.loads(row[2])["classification"], expected)
        events = self.store._connection.execute("SELECT count(*) FROM events WHERE type='fix.attempt.abnormal'").fetchone()[0]
        self.assertEqual(len(runtime.requests), dispatches)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_attempts").fetchone()[0], verification_count)
        # Malformed prior observations must not defeat status-based duplicate suppression.
        self.store._connection.execute("UPDATE fix_attempts SET abnormal_evidence_json='not-json'")
        self.assertEqual(recovery.recover(workflow.id), "already_recovered")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM events WHERE type='fix.attempt.abnormal'").fetchone()[0], events)

    def test_missing_expected_fix_lease_is_durable_unknown_and_idempotent(self):
        workflow, runtime = self.unresolved_fix()
        lease_id = self.store._connection.execute("SELECT lease_id FROM fix_attempts").fetchone()[0]
        self.store._connection.execute("DELETE FROM workspace_operation_leases WHERE lease_id=?", (lease_id,))
        self.assert_r5_sticky_unknown(workflow, runtime, FixRecoveryService(self.store), "missing_expected_fix_lease")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM workspace_operation_leases").fetchone()[0], 0)

    def test_multiple_fix_leases_are_retained_and_fail_closed_idempotently(self):
        workflow, runtime = self.unresolved_fix()
        foreign = self.foreign_fix_lease(workflow)
        self.assert_r5_sticky_unknown(workflow, runtime, FixRecoveryService(self.store), "multiple_fix_leases")
        retained = {row[0] for row in self.store._connection.execute("SELECT lease_id FROM workspace_operation_leases")}
        self.assertIn(foreign, retained)
        self.assertEqual(len(retained), 2)

    def test_foreign_fix_lease_is_retained_without_verify_authority(self):
        workflow, runtime = self.unresolved_fix()
        expected = self.store._connection.execute("SELECT lease_id FROM fix_attempts").fetchone()[0]
        self.store._connection.execute("DELETE FROM workspace_operation_leases WHERE lease_id=?", (expected,))
        foreign = self.foreign_fix_lease(workflow)
        self.assert_r5_sticky_unknown(workflow, runtime, FixRecoveryService(self.store), "foreign_or_mismatched_fix_lease")
        self.assertEqual(self.store._connection.execute("SELECT lease_id FROM workspace_operation_leases").fetchone()[0], foreign)

    def test_dead_unchanged_fix_releases_exact_lease_and_stops_at_human_attention(self):
        workflow, runtime = self.unresolved_fix()
        recovery = FixRecoveryService(self.store, identity=HostBootIdentity("host", "boot"),
            observer=lambda **_: ProcessGroupObservation.DEAD)
        self.assertEqual(recovery.recover(workflow.id), "process_dead_unchanged")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(tuple(self.store._connection.execute("SELECT status,outcome FROM fix_attempts").fetchone()),
                         ("abnormal", "interrupted_unchanged"))
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM workspace_operation_leases").fetchone()[0], 0)
        self.assertEqual(len(runtime.requests), 1)  # recovery itself made no dispatch
        self.assertEqual(recovery.recover(workflow.id), "no_attempt")

    def test_live_or_ambiguous_fix_is_sticky_unknown_and_retains_lease(self):
        workflow, runtime = self.unresolved_fix()
        recovery = FixRecoveryService(self.store, identity=HostBootIdentity("host", "boot"),
            observer=lambda **_: ProcessGroupObservation.ALIVE_OWNED)
        self.assertEqual(recovery.recover(workflow.id), "alive_owned")
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(tuple(self.store._connection.execute("SELECT status,outcome FROM fix_attempts").fetchone()),
                         ("unknown", "unknown"))
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM workspace_operation_leases").fetchone()[0], 1)
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(recovery.recover(workflow.id), "already_recovered")

    def test_dead_changed_or_unreadable_fix_retains_lease_without_retry(self):
        workflow, runtime = self.unresolved_fix()
        (self.root / "source.py").write_text("drift\n")
        recovery = FixRecoveryService(self.store, identity=HostBootIdentity("host", "boot"),
            observer=lambda **_: ProcessGroupObservation.DEAD)
        self.assertEqual(recovery.recover(workflow.id), "protected_state_unknown")
        self.assertEqual(self.store._connection.execute("SELECT status FROM fix_attempts").fetchone()[0], "unknown")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM workspace_operation_leases").fetchone()[0], 1)
        self.assertEqual(len(runtime.requests), 1)

    def test_corrupt_durable_join_is_sticky_unknown_and_never_releases(self):
        workflow, runtime = self.unresolved_fix()
        operation = self.store._connection.execute("SELECT operation_id FROM fix_attempts").fetchone()[0]
        self.store._connection.execute("UPDATE operations SET related_record_id='corrupt' WHERE id=?", (operation,))
        recovery = FixRecoveryService(self.store, identity=HostBootIdentity("host", "boot"),
            observer=lambda **_: ProcessGroupObservation.DEAD)
        self.assertEqual(recovery.recover(workflow.id), "process_dead_unchanged")
        self.assertEqual(self.store._connection.execute("SELECT status FROM fix_attempts").fetchone()[0], "unknown")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM workspace_operation_leases").fetchone()[0], 1)
        self.assertEqual(len(runtime.requests), 1)
