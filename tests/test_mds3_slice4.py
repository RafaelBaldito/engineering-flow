import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from engineering_flow.domain import (ApprovalDecision, ApprovalState, LifecycleVersion,
                                     Stage, WorkflowStatus)
from engineering_flow.orchestrator import (ImplementationRecoveryService,
                                           ReconciliationOutcome)
from engineering_flow.process_identity import (HostBootIdentity, ProcessObservation,
                                               observe_exact_process, signal_owned_group)
from engineering_flow.repository import RepositoryInspector, control_state_fingerprint
from engineering_flow.store import WorkflowStore


def git(root, *args):
    return subprocess.run(("git", "-C", str(root), *args), check=True, stdout=subprocess.PIPE).stdout


class Slice4RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name) / "repo"; self.root.mkdir()
        git(self.root, "init", "-q"); git(self.root, "config", "user.email", "test@example.invalid"); git(self.root, "config", "user.name", "Test")
        (self.root / ".gitignore").write_text(".engineering-flow/\n")
        (self.root / "source.py").write_text("before\n"); git(self.root, "add", "."); git(self.root, "commit", "-qm", "initial")
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")

    def tearDown(self): self.store.close(); self.temp.cleanup()

    def _approved(self):
        w = self.store.create_workflow(self.root, provider="fake", lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
        fi = self.store.create_generation_intent(w.id, Stage.INTAKE, request_hash="f", provider="fake", role="intake", revision=1, artifact_path=self.store.feature_contract_path(w.id, 1))
        feature = {"outcome":"READY", "feature":{"id":w.id,"goal":"g","requirements":["r"],"acceptance_criteria":["a"],"constraints":[],"out_of_scope":[],"assumptions":[],"open_questions":[]}}
        f = self.store.complete_generation(fi.operation.idempotency_key, content=json.dumps(feature), artifact_path=self.store.feature_contract_path(w.id,1), stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE, workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED)
        pi = self.store.create_generation_intent(w.id, Stage.PLAN, request_hash="p", provider="fake", role="planner", revision=1, artifact_path=self.store.plan_path(w.id,1))
        task = {"id":"T1","objective":"one","context":{"relevant_files":["source.py"],"existing_patterns":[]},"requirements":["r"],"acceptance_criteria":["a"],"verification":["test"],"constraints":[],"depends_on":[],"complexity":"low","risk":"low"}
        plan = {"plan":{"id":f"{w.id}:plan:r1","workflow_id":w.id,"revision":1,"feature_contract":{"artifact_id":f.id,"sha256":f.sha256},"strategy":"s","assumptions":[],"verification_strategy":["test"],"tasks":[task]}}
        p = self.store.complete_generation(pi.operation.idempotency_key, content=json.dumps(plan), artifact_path=self.store.plan_path(w.id,1), stage=Stage.PLAN, revision=1, workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.AWAITING_APPROVAL)
        self.store.record_approval(w.id, p.id, ApprovalDecision.APPROVED, actor="human", workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.PLAN_APPROVED)
        return w

    def _running(self):
        w = self._approved(); authority = self.store.load_approved_v2_plan_authority(w.id); task = authority.plan.tasks[0]
        inspector = RepositoryInspector(self.root); baseline = inspector.capture(require_clean=True).as_payload(); baseline["control_state_fingerprint"] = control_state_fingerprint(self.root)
        intent = self.store.create_implementation_intent(w.id, repository_key=inspector.repository_key(), canonical_root=str(self.root), task_contract_id=task.id, task_contract_sha256=task.payload_sha256(), request_hash="a" * 64, baseline=baseline, owner_instance_id=str(uuid.uuid4()), owner_pid=os.getpid(), owner_host_id="host", owner_boot_id="boot")
        self.store.record_implementation_provider_started(intent["attempt_id"], intent["lease_id"], {"pid": 99999, "process_start":"start", "process_group":99999})
        return w, intent

    def test_dead_writer_unchanged_releases_lease_and_stops(self):
        w, _ = self._running()
        outcome = ImplementationRecoveryService(self.store, identity=HostBootIdentity("host", "boot"), observer=lambda **_: ProcessObservation.GONE).reconcile(w.id)
        self.assertEqual(outcome, ReconciliationOutcome.WRITER_GONE_UNCHANGED)
        self.assertIsNone(self.store.active_implementation_lease(w.id))
        self.assertEqual(self.store.get_workflow(w.id).status.value, "implementation_failed")

    def test_dead_writer_changed_is_unknown_but_releases_after_death_proof(self):
        w, _ = self._running(); (self.root / "source.py").write_text("changed\n")
        outcome = ImplementationRecoveryService(self.store, identity=HostBootIdentity("host", "boot"), observer=lambda **_: ProcessObservation.GONE).reconcile(w.id)
        self.assertEqual(outcome, ReconciliationOutcome.WRITER_GONE_CHANGED)
        self.assertIsNone(self.store.active_implementation_lease(w.id))
        self.assertEqual(self.store.get_workflow(w.id).status.value, "human_attention")

    def test_live_or_ambiguous_writer_keeps_lease(self):
        w, _ = self._running()
        outcome = ImplementationRecoveryService(self.store, identity=HostBootIdentity("host", "boot"), observer=lambda **_: ProcessObservation.ALIVE).reconcile(w.id)
        self.assertEqual(outcome, ReconciliationOutcome.WRITER_ALIVE); self.assertIsNotNone(self.store.active_implementation_lease(w.id))
        # A different host never turns a local PID observation into a death proof.
        outcome = ImplementationRecoveryService(self.store, identity=HostBootIdentity("other", "boot")).reconcile(w.id)
        self.assertEqual(outcome, ReconciliationOutcome.IDENTITY_AMBIGUOUS); self.assertIsNotNone(self.store.active_implementation_lease(w.id))

    def test_different_boot_never_uses_current_pid_as_death_evidence(self):
        w, _ = self._running()
        outcome = ImplementationRecoveryService(self.store, identity=HostBootIdentity("host", "new-boot")).reconcile(w.id)
        self.assertEqual(outcome, ReconciliationOutcome.IDENTITY_AMBIGUOUS)
        self.assertIsNotNone(self.store.active_implementation_lease(w.id))

    def test_pid_reuse_is_ambiguous_and_never_signaled(self):
        identity = HostBootIdentity("host", "boot")
        observed = observe_exact_process(host_id="host", boot_id="boot", provider_pid=42,
            provider_process_start="old", identity=identity, token_reader=lambda _: "new")
        self.assertIs(observed, ProcessObservation.AMBIGUOUS)
        calls = []
        self.assertFalse(signal_owned_group(process_group=42, provider_pid=42, provider_process_start="old",
            host_id="host", boot_id="boot", sig=15, identity=identity, token_reader=lambda _: "new",
            signal_sender=lambda *args: calls.append(args)))
        self.assertEqual(calls, [])
