import json
import os
import subprocess
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from engineering_flow.domain import (ApprovalDecision, ApprovalState, LifecycleVersion,
                                     SuccessfulImplementationProducer, Stage,
                                     ValidationFailure, VerificationOutcome, WorkflowStatus)
from engineering_flow.verification import (MANIFEST_RELATIVE_PATH,
    DeterministicVerificationPreflight, VerificationManifestResolver,
    classify_verification_preflight_failure)
from engineering_flow.repository import RepositoryInspector, control_state_fingerprint
from engineering_flow.store import WorkflowStore


def git(root, *args):
    return subprocess.run(("git", "-C", str(root), *args), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


class Mds4Slice1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"; self.root.mkdir()
        git(self.root, "init", "-q"); git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "Test")
        (self.root / ".gitignore").write_text(".engineering-flow/*\n!.engineering-flow/verification/\n.engineering-flow/verification/*\n!.engineering-flow/verification/manifest-v1.json\n")
        self.path = self.root / MANIFEST_RELATIVE_PATH; self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"version": 1, "commands": [{"id": "unit", "argv": [".venv/bin/python3", "-m", "unittest"], "timeout_seconds": 120}]}))
        (self.root / "source.py").write_text("before\n")
        git(self.root, "add", "."); git(self.root, "commit", "-qm", "initial")
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")

    def tearDown(self): self.store.close(); self.temp.cleanup()

    def _approved_producer(self):
        workflow = self.store.create_workflow(self.root, provider="fake", lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
        feature_intent = self.store.create_generation_intent(workflow.id, Stage.INTAKE, request_hash="feature", provider="fake", role="intake", revision=1, artifact_path=self.store.feature_contract_path(workflow.id, 1))
        feature_payload = {"outcome":"READY", "feature":{"id":workflow.id,"goal":"g","requirements":["r"],"acceptance_criteria":["a"],"constraints":[],"out_of_scope":[],"assumptions":[],"open_questions":[]}}
        feature = self.store.complete_generation(feature_intent.operation.idempotency_key, content=json.dumps(feature_payload), artifact_path=self.store.feature_contract_path(workflow.id, 1), stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE, workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED)
        plan_intent = self.store.create_generation_intent(workflow.id, Stage.PLAN, request_hash="plan", provider="fake", role="planner", revision=1, artifact_path=self.store.plan_path(workflow.id, 1))
        task = {"id":"T1","objective":"one","context":{"relevant_files":["source.py"],"existing_patterns":[]},"requirements":["r"],"acceptance_criteria":["a"],"verification":["test"],"constraints":[],"depends_on":[],"complexity":"low","risk":"low"}
        plan = {"plan":{"id":f"{workflow.id}:plan:r1","workflow_id":workflow.id,"revision":1,"feature_contract":{"artifact_id":feature.id,"sha256":feature.sha256},"strategy":"s","assumptions":[],"verification_strategy":["test"],"tasks":[task]}}
        plan_artifact = self.store.complete_generation(plan_intent.operation.idempotency_key, content=json.dumps(plan), artifact_path=self.store.plan_path(workflow.id, 1), stage=Stage.PLAN, revision=1, workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.AWAITING_APPROVAL)
        self.store.record_approval(workflow.id, plan_artifact.id, ApprovalDecision.APPROVED, actor="human", workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.PLAN_APPROVED)
        authority = self.store.load_approved_v2_plan_authority(workflow.id); contract = authority.plan.tasks[0]
        inspector = RepositoryInspector(self.root); baseline = inspector.capture(require_clean=True).as_payload(); baseline["control_state_fingerprint"] = control_state_fingerprint(self.root)
        intent = self.store.create_implementation_intent(workflow.id, repository_key=inspector.repository_key(), canonical_root=str(self.root), task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), request_hash="i" * 64, baseline=baseline, owner_instance_id=str(uuid.uuid4()), owner_pid=os.getpid(), owner_host_id="host", owner_boot_id="boot")
        (self.root / "source.py").write_text("implemented\n")
        final = inspector.capture().as_payload()
        self.store.finish_implementation_attempt(intent["attempt_id"], intent["lease_id"], status="succeeded", classification="completed_changed", final=final, workspace_changed=True, owner_instance_id=intent["owner_instance_id"])
        return workflow, authority, contract, intent, final

    def test_tracked_manifest_is_canonical_and_hash_bound(self):
        binding = VerificationManifestResolver(self.root).resolve()
        self.assertEqual(binding.path, MANIFEST_RELATIVE_PATH)
        self.assertEqual(binding.manifest.commands[0].argv, (".venv/bin/python3", "-m", "unittest"))
        self.assertEqual(binding, VerificationManifestResolver(self.root).validate_unchanged(binding))
        producer = SuccessfulImplementationProducer("operation-1", "execution-1", "workflow-1", "feature", "f" * 64, "plan", "p" * 64, 1, "workflow-1:plan:r1", "approval", "T1", "t" * 64, "i" * 64, {}, "e" * 64, "r" * 64)
        self.assertEqual(len(binding.request_hash(authority_hash="a" * 64, producer=producer)), 64)

    def test_rejects_unknown_fields_duplicates_and_invalid_tokens(self):
        cases = (
            b'{"version":1,"commands":[],"other":true}',
            b'{"version":1,"version":1,"commands":[]}',
            b'{"version":1,"commands":[{"id":"x","argv":["ok"],"timeout_seconds":true}]}',
            b'{"version":1,"commands":[{"id":"x","argv":["ok"],"timeout_seconds":1,"cwd":"."}]}',
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValidationFailure):
                VerificationManifestResolver.parse(raw)

    def test_untracked_or_changed_worktree_manifest_is_blocked(self):
        self.path.write_text('{"version":1,"commands":[{"id":"changed","argv":["true"],"timeout_seconds":1}]}')
        with self.assertRaisesRegex(ValidationFailure, "working-tree bytes differ"):
            VerificationManifestResolver(self.root).resolve()
        self.path.unlink()
        with self.assertRaises(ValidationFailure): VerificationManifestResolver(self.root).resolve()

    def test_present_but_never_tracked_manifest_is_blocked(self):
        git(self.root, "rm", "--cached", MANIFEST_RELATIVE_PATH)
        git(self.root, "commit", "-qm", "remove manifest")
        with self.assertRaisesRegex(ValidationFailure, "tracked"):
            VerificationManifestResolver(self.root).resolve()

    def test_gitignore_allows_manifest_but_ignores_runtime_control_paths(self):
        runtime = self.root / ".engineering-flow" / "workflows.sqlite3"; runtime.parent.mkdir(exist_ok=True); runtime.write_text("runtime")
        runtime_ignored = subprocess.run(("git", "-C", str(self.root), "check-ignore", "--no-index", "-q", str(runtime.relative_to(self.root))))
        manifest_ignored = subprocess.run(("git", "-C", str(self.root), "check-ignore", "--no-index", "-q", MANIFEST_RELATIVE_PATH))
        self.assertEqual(runtime_ignored.returncode, 0)
        self.assertNotEqual(manifest_ignored.returncode, 0)
        git(self.root, "rm", "--cached", MANIFEST_RELATIVE_PATH)
        git(self.root, "add", MANIFEST_RELATIVE_PATH)

    def test_manifest_binding_detects_head_change_even_with_same_bytes(self):
        binding = VerificationManifestResolver(self.root).resolve()
        (self.root / "unrelated").write_text("change\n")
        git(self.root, "add", "unrelated"); git(self.root, "commit", "-qm", "head changes")
        with self.assertRaisesRegex(ValidationFailure, "binding changed"):
            VerificationManifestResolver(self.root).validate_unchanged(binding)

    def test_preflight_failure_classification_is_not_test_failure(self):
        self.assertEqual(classify_verification_preflight_failure(ValidationFailure("bad")),
            VerificationOutcome.VERIFICATION_BLOCKED)
        self.assertEqual(classify_verification_preflight_failure(RuntimeError("bad")),
            VerificationOutcome.VERIFICATION_UNKNOWN)

    def test_preflight_requires_persisted_successful_producer_and_snapshot(self):
        workflow, _authority, contract, intent, _final = self._approved_producer()
        preflight = DeterministicVerificationPreflight(self.root, self.store.load_approved_v2_plan_authority, self.store.load_successful_implementation_producer)
        result = preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=intent["operation_id"])
        self.assertEqual(len(result.authority_sha256), 64)
        self.assertEqual(len(result.request_hash), 64)
        self.assertEqual(result.producer.operation_id, intent["operation_id"])
        (self.root / "source.py").write_text("stale\n")
        with self.assertRaisesRegex(ValidationFailure, "final snapshot"):
            preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=intent["operation_id"])

    def test_forged_non_successful_mismatched_and_missing_producer_evidence_fail_closed(self):
        workflow, _authority, contract, intent, _final = self._approved_producer()
        preflight = DeterministicVerificationPreflight(self.root, self.store.load_approved_v2_plan_authority, self.store.load_successful_implementation_producer)
        with self.assertRaisesRegex(ValidationFailure, "missing"):
            preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id="forged")
        self.store._connection.execute("UPDATE operations SET status='pending' WHERE id=?", (intent["operation_id"],))
        with self.assertRaisesRegex(ValidationFailure, "successful IMPLEMENT"):
            preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=intent["operation_id"])
        self.store._connection.execute("UPDATE operations SET status='completed' WHERE id=?", (intent["operation_id"],))
        self.store._connection.execute("UPDATE implementation_attempts SET task_contract_sha256=? WHERE operation_id=?", ("x" * 64, intent["operation_id"]))
        with self.assertRaisesRegex(ValidationFailure, "selected implementation"):
            preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=intent["operation_id"])
        self.store._connection.execute("UPDATE implementation_attempts SET task_contract_sha256=?, final_repository_json=NULL WHERE operation_id=?", (contract.payload_sha256(), intent["operation_id"]))
        with self.assertRaisesRegex(ValidationFailure, "final repository evidence"):
            preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=intent["operation_id"])

    def test_forged_final_repository_fingerprint_is_rejected(self):
        workflow, _authority, contract, intent, final = self._approved_producer()
        final["head_sha"] = "f" * 40
        self.store._connection.execute("UPDATE implementation_attempts SET final_repository_json=? WHERE operation_id=?", (json.dumps(final), intent["operation_id"]))
        preflight = DeterministicVerificationPreflight(self.root, self.store.load_approved_v2_plan_authority, self.store.load_successful_implementation_producer)
        with self.assertRaisesRegex(ValidationFailure, "fingerprint does not match"):
            preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=intent["operation_id"])

    def test_stale_or_invalid_persisted_authority_fails_closed(self):
        workflow, authority, contract, intent, _final = self._approved_producer()
        Path(authority.plan_artifact.path).write_text("{}")
        preflight = DeterministicVerificationPreflight(self.root, self.store.load_approved_v2_plan_authority, self.store.load_successful_implementation_producer)
        with self.assertRaises(Exception):
            preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=intent["operation_id"])

    def test_request_hash_is_deterministic_and_binds_every_producer_input(self):
        workflow, _authority, contract, intent, _final = self._approved_producer()
        preflight = DeterministicVerificationPreflight(self.root, self.store.load_approved_v2_plan_authority, self.store.load_successful_implementation_producer)
        first = preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=intent["operation_id"])
        second = preflight.validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=intent["operation_id"])
        self.assertEqual(first.request_hash, second.request_hash)
        producer = first.producer
        for field in ("operation_id", "execution_id", "implementation_request_hash", "final_repository_sha256", "final_repository_fingerprint"):
            changed = replace(producer, **{field: "z" * 64})
            self.assertNotEqual(first.manifest_binding.request_hash(authority_hash=first.authority_sha256, producer=producer), first.manifest_binding.request_hash(authority_hash=first.authority_sha256, producer=changed), field)
        self.assertNotEqual(first.manifest_binding.request_hash(authority_hash=first.authority_sha256, producer=producer), first.manifest_binding.request_hash(authority_hash="a" * 64, producer=producer))
        for field in ("head_sha", "head_blob_sha256", "worktree_sha256", "canonical_commands_sha256"):
            changed_binding = replace(first.manifest_binding, **{field: "z" * 64})
            self.assertNotEqual(first.manifest_binding.request_hash(authority_hash=first.authority_sha256, producer=producer), changed_binding.request_hash(authority_hash=first.authority_sha256, producer=producer), field)

    def test_approved_authority_reloads_through_verification_lifecycle_statuses(self):
        workflow, authority, _contract, _intent, _final = self._approved_producer()
        for status in (WorkflowStatus.VERIFYING, WorkflowStatus.VERIFICATION_FAILED, WorkflowStatus.TASK_VERIFIED):
            self.store._connection.execute("UPDATE workflows SET stage=?, status=? WHERE id=?", (Stage.TASK_EXECUTION.value, status.value, workflow.id))
            reloaded = self.store.load_approved_v2_plan_authority(workflow.id)
            self.assertEqual(reloaded.plan_artifact.id, authority.plan_artifact.id)
