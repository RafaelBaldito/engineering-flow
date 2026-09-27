import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from engineering_flow.domain import ApprovalDecision, ApprovalState, LifecycleVersion, Stage, WorkflowStatus
from engineering_flow.repository import RepositoryInspector
from engineering_flow.store import ConflictFailure, ValidationFailure, WorkflowStore


def git(root, *args):
    return subprocess.run(("git", "-C", str(root), *args), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


class Mds4Slice2PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name) / "repo"; self.root.mkdir()
        git(self.root, "init", "-q"); git(self.root, "config", "user.email", "test@example.invalid"); git(self.root, "config", "user.name", "Test")
        (self.root / "source.py").write_text("before\n"); git(self.root, "add", "."); git(self.root, "commit", "-qm", "initial")
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")

    def tearDown(self):
        if self.store is not None:
            self.store.close()
        self.temp.cleanup()

    def producer(self, *, finish=True, repository_root=None):
        repository_root = repository_root or self.root
        workflow = self.store.create_workflow(repository_root, provider="fake", lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
        fi = self.store.create_generation_intent(workflow.id, Stage.INTAKE, request_hash="feature", provider="fake", role="intake", revision=1, artifact_path=self.store.feature_contract_path(workflow.id, 1))
        feature = self.store.complete_generation(fi.operation.idempotency_key, content=json.dumps({"outcome":"READY", "feature":{"id":workflow.id,"goal":"g","requirements":["r"],"acceptance_criteria":["a"],"constraints":[],"out_of_scope":[],"assumptions":[],"open_questions":[]}}), artifact_path=self.store.feature_contract_path(workflow.id, 1), stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE, workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED)
        pi = self.store.create_generation_intent(workflow.id, Stage.PLAN, request_hash="plan", provider="fake", role="planner", revision=1, artifact_path=self.store.plan_path(workflow.id, 1))
        task = {"id":"T1","objective":"one","context":{"relevant_files":["source.py"],"existing_patterns":[]},"requirements":["r"],"acceptance_criteria":["a"],"verification":["test"],"constraints":[],"depends_on":[],"complexity":"low","risk":"low"}
        plan = self.store.complete_generation(pi.operation.idempotency_key, content=json.dumps({"plan":{"id":f"{workflow.id}:plan:r1","workflow_id":workflow.id,"revision":1,"feature_contract":{"artifact_id":feature.id,"sha256":feature.sha256},"strategy":"s","assumptions":[],"verification_strategy":["test"],"tasks":[task]}}), artifact_path=self.store.plan_path(workflow.id, 1), stage=Stage.PLAN, revision=1, workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.AWAITING_APPROVAL)
        self.store.record_approval(workflow.id, plan.id, ApprovalDecision.APPROVED, actor="human", workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.PLAN_APPROVED)
        authority = self.store.load_approved_v2_plan_authority(workflow.id); contract = authority.plan.tasks[0]; inspector = RepositoryInspector(repository_root)
        intent = self.store.create_implementation_intent(workflow.id, repository_key=inspector.repository_key(), canonical_root=str(repository_root), task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), request_hash="i" * 64, baseline=inspector.capture().as_payload(), owner_instance_id="implement-owner", owner_pid=os.getpid(), owner_host_id="host")
        if finish:
            (repository_root / "source.py").write_text("implemented\n")
            self.store.finish_implementation_attempt(intent["attempt_id"], intent["lease_id"], status="succeeded", classification="completed_changed", final=inspector.capture().as_payload(), workspace_changed=True, owner_instance_id=intent["owner_instance_id"])
        return workflow, contract, intent, inspector.repository_key()

    def verification_intent(self):
        workflow, contract, producer, key = self.producer()
        kwargs = dict(repository_key=key, canonical_root=str(self.root), producer_operation_id=producer["operation_id"], task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), authority_sha256="a" * 64, request_hash="b" * 64, manifest_binding={"path":"manifest"}, baseline={"fingerprint":"baseline"}, owner_instance_id="verify-owner", owner_pid=os.getpid(), owner_host_id="host")
        return workflow, contract, key, kwargs, self.store.create_verification_intent(workflow.id, **kwargs)

    def test_verification_intent_atomically_binds_producer_operation_and_common_lease(self):
        workflow, contract, key, kwargs, intent = self.verification_intent()
        lease = self.store.active_workspace_operation_lease(key)
        self.assertEqual((lease["operation_kind"], lease["attempt_id"], lease["operation_id"]), ("verification", intent["attempt_id"], intent["operation_id"]))
        row = self.store._connection.execute("SELECT producer_operation_id,status FROM verification_attempts WHERE id=?", (intent["attempt_id"],)).fetchone()
        self.assertEqual((row["producer_operation_id"], row["status"]), (kwargs["producer_operation_id"], "verifying"))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.VERIFYING)
        self.assertEqual(self.store.create_verification_intent(workflow.id, **kwargs), intent)

    def test_command_evidence_is_ordered_immutable_and_terminal_success_releases_exact_lease(self):
        workflow, contract, key, kwargs, intent = self.verification_intent()
        command = self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"], owner_instance_id="verify-owner", ordinal=1, command_id="unit", canonical_command_sha256="c" * 64, argv=["python", "-m", "unittest"], timeout_seconds=30)
        with self.assertRaises(ConflictFailure):
            self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"], owner_instance_id="verify-owner", ordinal=1, command_id="other", canonical_command_sha256="d" * 64, argv=["false"], timeout_seconds=1)
        self.store.record_verification_command_result(intent["attempt_id"], intent["lease_id"], command, owner_instance_id="verify-owner", exit_code=0, timed_out=False, output_sha256=None, output_bytes=0, output_truncated=False, post_command_inspection={"fingerprint":"same"}, classification="passed")
        with self.assertRaises(ConflictFailure):
            self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"], owner_instance_id="wrong", outcome="verified", final_inspection={})
        self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"], owner_instance_id="verify-owner", outcome="verified", final_inspection={"fingerprint":"same"})
        self.assertIsNone(self.store.active_workspace_operation_lease(key))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_VERIFIED)
        self.assertEqual(self.store.list_task_implementation_states(workflow.id, self.store.load_approved_v2_plan_authority(workflow.id).plan_artifact.id)[0].status.value, "verified")

    def test_implementation_lease_uses_same_repository_mutex(self):
        workflow, contract, key, kwargs, intent = self.verification_intent()
        # VERIFY now owns the repository mutex; IMPLEMENT must observe it
        # before it can reconsider a task state.
        with self.assertRaises(ConflictFailure):
            self.store.create_implementation_intent(workflow.id, repository_key=key, canonical_root=str(self.root), task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), request_hash="n" * 64, baseline=RepositoryInspector(self.root).capture().as_payload(), owner_instance_id=str(uuid.uuid4()), owner_pid=os.getpid(), owner_host_id="host")
        self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"], owner_instance_id="verify-owner", outcome="verification_blocked", final_inspection={})

    def test_interrupted_unchanged_creates_one_fresh_attempt_with_same_binding(self):
        workflow, contract, key, kwargs, first = self.verification_intent()
        self.store.finish_verification_attempt(first["attempt_id"], first["lease_id"], owner_instance_id="verify-owner", outcome="interrupted_unchanged", final_inspection={})
        second = self.store.create_verification_intent(workflow.id, **kwargs)
        self.assertNotEqual(first["attempt_id"], second["attempt_id"])
        self.assertEqual(self.store.create_verification_intent(workflow.id, **kwargs), second)
        rows = self.store._connection.execute("SELECT request_hash,authority_sha256,sequence FROM verification_attempts ORDER BY sequence").fetchall()
        self.assertEqual([(row["request_hash"], row["authority_sha256"], row["sequence"]) for row in rows], [("b" * 64, "a" * 64, 1), ("b" * 64, "a" * 64, 2)])

    def test_active_verification_duplicate_is_not_created(self):
        workflow, contract, key, kwargs, first = self.verification_intent()
        self.assertEqual(self.store.create_verification_intent(workflow.id, **kwargs), first)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_attempts").fetchone()[0], 1)

    def test_implementation_terminal_refuses_owner_mismatch(self):
        workflow, contract, intent, key = self.producer(finish=False)
        with self.assertRaises(ConflictFailure):
            self.store.finish_implementation_attempt(intent["attempt_id"], intent["lease_id"], status="failed", classification="failed_unchanged", final={}, workspace_changed=False, owner_instance_id="wrong")
        self.assertEqual(self.store.active_workspace_operation_lease(key)["owner_instance_id"], "implement-owner")

    def test_command_intents_are_serial_and_strictly_typed(self):
        workflow, contract, key, kwargs, intent = self.verification_intent()
        args = dict(owner_instance_id="verify-owner", command_id="unit", canonical_command_sha256="c" * 64, argv=["python"], timeout_seconds=30)
        with self.assertRaises(ConflictFailure):
            self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"], ordinal=2, **args)
        first = self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"], ordinal=1, **args)
        with self.assertRaises(ConflictFailure):
            self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"], ordinal=2, **{**args, "command_id":"next"})
        with self.assertRaises(ValidationFailure):
            self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"], ordinal=True, **args)
        with self.assertRaises(ValidationFailure):
            self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"], ordinal=1, **{**args, "timeout_seconds":True})
        with self.assertRaises(ValidationFailure):
            self.store.record_verification_command_result(intent["attempt_id"], intent["lease_id"], first, owner_instance_id="verify-owner", exit_code=0, timed_out=1, output_sha256=None, output_bytes=0, output_truncated=False, post_command_inspection={}, classification="passed")
        with self.assertRaises(ValidationFailure):
            self.store.record_verification_command_result(intent["attempt_id"], intent["lease_id"], first, owner_instance_id="verify-owner", exit_code=0, timed_out=False, output_sha256=None, output_bytes=True, output_truncated=False, post_command_inspection={}, classification="passed")
        self.store.record_verification_command_result(intent["attempt_id"], intent["lease_id"], first, owner_instance_id="verify-owner", exit_code=0, timed_out=False, output_sha256=None, output_bytes=0, output_truncated=False, post_command_inspection={}, classification="passed")
        with self.assertRaises(ConflictFailure):
            self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"], ordinal=2, **args)
        self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"], ordinal=2, **{**args, "command_id":"next"})

    def test_legacy_lease_migration_is_restart_safe_and_preserves_owner_fields(self):
        workflow, contract, intent, key = self.producer()
        self.store.close()
        conn = sqlite3.connect(self.root / ".engineering-flow" / "workflows.sqlite3")
        conn.execute("""CREATE TABLE workspace_writer_leases (repository_key TEXT PRIMARY KEY, lease_id TEXT NOT NULL UNIQUE,
            attempt_id TEXT NOT NULL UNIQUE REFERENCES implementation_attempts(id), workflow_id TEXT NOT NULL REFERENCES workflows(id),
            canonical_root TEXT NOT NULL, owner_instance_id TEXT NOT NULL, owner_pid INTEGER NOT NULL, owner_host_id TEXT NOT NULL,
            owner_boot_id TEXT, provider_pid INTEGER, provider_process_start TEXT, provider_process_group INTEGER,
            acquired_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        values = (key, intent["lease_id"], intent["attempt_id"], workflow.id, str(self.root), "legacy-owner", 123, "legacy-host", "legacy-boot", 456, "legacy-start", 789, "one", "two")
        conn.execute("INSERT INTO workspace_writer_leases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
        # This is the durable residue left if a process is interrupted after
        # copy/validation but before the legacy-table removal.
        conn.execute("""INSERT INTO workspace_operation_leases
            (repository_key,lease_id,operation_kind,attempt_id,operation_id,workflow_id,canonical_root,
             owner_instance_id,owner_pid,owner_host_id,owner_boot_id,child_pid,child_process_start,
             child_process_group,acquired_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (key, intent["lease_id"], "implementation", intent["attempt_id"], intent["operation_id"], workflow.id,
             str(self.root), "legacy-owner", 123, "legacy-host", "legacy-boot", 456, "legacy-start", 789, "one", "two"))
        conn.commit(); conn.close()
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        lease = self.store.active_workspace_operation_lease(key)
        self.assertEqual(tuple(lease[field] for field in ("lease_id", "attempt_id", "workflow_id", "canonical_root", "owner_instance_id", "owner_pid", "owner_host_id", "owner_boot_id", "child_pid", "child_process_start", "child_process_group", "acquired_at", "updated_at")), (intent["lease_id"], intent["attempt_id"], workflow.id, str(self.root), "legacy-owner", 123, "legacy-host", "legacy-boot", 456, "legacy-start", 789, "one", "two"))
        self.store.close(); self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        self.assertEqual(self.store.active_workspace_operation_lease(key)["lease_id"], intent["lease_id"])

    def _assert_legacy_migration_rolls_back_identity_conflict(self, *, mismatch):
        first_workflow, _, first_intent, first_key = self.producer()
        second_root = Path(self.temp.name) / "second-repo"
        second_root.mkdir()
        git(second_root, "init", "-q"); git(second_root, "config", "user.email", "test@example.invalid"); git(second_root, "config", "user.name", "Test")
        (second_root / "source.py").write_text("before\n"); git(second_root, "add", "."); git(second_root, "commit", "-qm", "initial")
        second_workflow, _, second_intent, second_key = self.producer(repository_root=second_root)
        self.store.close()
        database = self.root / ".engineering-flow" / "workflows.sqlite3"
        conn = sqlite3.connect(database)
        conn.execute("""CREATE TABLE workspace_writer_leases (repository_key TEXT PRIMARY KEY, lease_id TEXT NOT NULL UNIQUE,
            attempt_id TEXT NOT NULL UNIQUE REFERENCES implementation_attempts(id), workflow_id TEXT NOT NULL REFERENCES workflows(id),
            canonical_root TEXT NOT NULL, owner_instance_id TEXT NOT NULL, owner_pid INTEGER NOT NULL, owner_host_id TEXT NOT NULL,
            owner_boot_id TEXT, provider_pid INTEGER, provider_process_start TEXT, provider_process_group INTEGER,
            acquired_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        valid = (first_key, first_intent["lease_id"], first_intent["attempt_id"], first_workflow.id, str(self.root),
                 "first-owner", 123, "host", "boot", None, None, None, "one", "two")
        conflicting = [second_key, second_intent["lease_id"], second_intent["attempt_id"], second_workflow.id, str(second_root),
                       "second-owner", 456, "host", "boot", None, None, None, "three", "four"]
        if mismatch == "lease_id":
            conflicting[1] = "conflicting-lease-id"
        elif mismatch == "workflow_id":
            conflicting[3] = first_workflow.id
        elif mismatch == "attempt_id":
            conflicting[2] = "missing-implementation-attempt"
        elif mismatch == "operation_id":
            conn.execute("DELETE FROM operations WHERE id=?", (second_intent["operation_id"],))
        elif mismatch == "operation_workflow_id":
            conn.execute("UPDATE operations SET workflow_id=? WHERE id=?", (first_workflow.id, second_intent["operation_id"]))
        elif mismatch == "canonical_root":
            conflicting[4] = str(self.root)
        elif mismatch == "repository_key":
            conflicting[0] = "derived-repository-key-mismatch"
        else:
            self.fail(f"unknown identity mismatch: {mismatch}")
        conn.execute("INSERT INTO workspace_writer_leases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", valid)
        conn.execute("INSERT INTO workspace_writer_leases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", conflicting)
        conn.commit(); conn.close(); self.store = None

        with self.assertRaises(ConflictFailure):
            WorkflowStore(database)

        conn = sqlite3.connect(database)
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM workspace_writer_leases").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM workspace_operation_leases").fetchone()[0], 0)
            rows = conn.execute("SELECT repository_key,lease_id,attempt_id,workflow_id,canonical_root FROM workspace_writer_leases ORDER BY acquired_at").fetchall()
            self.assertEqual(rows, [(valid[0], valid[1], valid[2], valid[3], valid[4]),
                                    tuple(conflicting[index] for index in (0, 1, 2, 3, 4))])
        finally:
            conn.close()

    def test_legacy_lease_id_conflict_fails_initialization_and_rolls_back_migration(self):
        self._assert_legacy_migration_rolls_back_identity_conflict(mismatch="lease_id")

    def test_legacy_workflow_id_conflict_fails_initialization_and_rolls_back_migration(self):
        self._assert_legacy_migration_rolls_back_identity_conflict(mismatch="workflow_id")

    def test_legacy_attempt_id_conflict_fails_initialization_and_rolls_back_migration(self):
        self._assert_legacy_migration_rolls_back_identity_conflict(mismatch="attempt_id")

    def test_legacy_operation_id_conflict_fails_initialization_and_rolls_back_migration(self):
        self._assert_legacy_migration_rolls_back_identity_conflict(mismatch="operation_id")

    def test_legacy_operation_workflow_id_conflict_fails_initialization_and_rolls_back_migration(self):
        self._assert_legacy_migration_rolls_back_identity_conflict(mismatch="operation_workflow_id")

    def test_legacy_canonical_root_conflict_fails_initialization_and_rolls_back_migration(self):
        self._assert_legacy_migration_rolls_back_identity_conflict(mismatch="canonical_root")

    def test_legacy_repository_key_conflict_fails_initialization_and_rolls_back_migration(self):
        self._assert_legacy_migration_rolls_back_identity_conflict(mismatch="repository_key")
