from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from tools.wave_controller.core import Controller, ControllerError
from tools.wave_controller.fingerprint import capture


class WaveControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        (self.root / "tracked.txt").write_text("base\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.root, check=True)
        self.controller = Controller(self.root, "fixture")
        self.state = self.controller.initial("fixture", "Fixture")
        self.controller.save(self.state)

    def tearDown(self): self.temp.cleanup()

    def save(self, **changes):
        state = self.controller.load(); state.update(changes); self.controller.save(state); return state

    def authority(self):
        path = self.root / "authority.md"; path.write_text("approved")
        return {"path": "authority.md", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "purpose": "human authority"}

    def test_valid_state_parsing_and_invalid_rejection(self):
        self.assertEqual("WAVE_AUTHORIZED", self.controller.load()["lifecycle_state"])
        self.controller.path.write_text("# bad\n```yaml\n[]\n```\n")
        with self.assertRaises(ControllerError): self.controller.load()

    def test_allowed_and_invalid_lifecycle_transition(self):
        self.save(human_gate={"status": "SATISFIED", "reason": "", "evidence": [self.authority()]})
        self.assertEqual("ACTION_REQUIRED", self.controller.next()["status"])
        self.assertEqual("TECHSPEC_REQUIRED", self.controller.load()["lifecycle_state"])
        state = self.controller.load(); state["lifecycle_state"] = "NOPE"
        with self.assertRaises(ControllerError): self.controller.save(state)

    def test_fingerprint_stable_and_material_changes(self):
        first = capture(self.root); self.assertEqual(first, capture(self.root))
        (self.root / "tracked.txt").write_text("changed\n")
        self.assertNotEqual(first["fingerprint"], capture(self.root)["fingerprint"])

    def test_atomic_replacement_and_interruption_preserves_old_file(self):
        before = self.controller.load(); changed = dict(before); changed["lifecycle_state"] = "TECHSPEC_REQUIRED"
        with self.assertRaises(InterruptedError): self.controller.save(changed, interrupt_before_replace=True)
        self.assertEqual("WAVE_AUTHORIZED", self.controller.load()["lifecycle_state"])
        self.controller.save(changed); self.assertEqual("TECHSPEC_REQUIRED", self.controller.load()["lifecycle_state"])

    def test_writer_lease_acquire_reject_unknown_and_valid_release(self):
        self.save(lifecycle_state="TASK_EXECUTION_REQUIRED", tasks=[{"id": "TASK-001", "status": "PENDING", "dependencies": []}])
        acquired = self.controller.begin_operation("op-1")
        self.assertEqual("ACQUIRED", acquired["status"])
        self.assertEqual("REJECT", self.controller.begin_operation("op-2")["status"])
        state = self.controller.load(); state["active_operation"]["role"] = "Mystery"; self.controller.save(state)
        self.assertEqual("HUMAN_ATTENTION", self.controller.next()["status"])
        # Restore a valid active lease and complete it; only this completion releases it.
        state = self.controller.load(); state["lifecycle_state"] = "TASK_IMPLEMENTATION"; state["active_operation"]["role"] = "Developer"; self.controller.save(state)
        result = self.envelope("Developer", "op-1")
        self.assertEqual("COMPLETED", self.controller.complete_operation(result)["status"])
        self.assertIsNone(self.controller.load()["active_operation"])

    def test_next_human_gate_and_reviewer_handoff_isolated(self):
        self.save(lifecycle_state="AWAITING_TASK_PLAN_APPROVAL", human_gate={"status": "OPEN", "reason": "", "evidence": []})
        self.assertEqual("HUMAN_ACTION", self.controller.next()["status"])
        self.save(lifecycle_state="TASK_REVIEW_REQUIRED", current_task_id="TASK-001", human_gate={"status": "NOT_APPLICABLE", "reason": "", "evidence": []})
        handoff = self.controller.next()["handoff"]
        self.assertEqual("none", handoff["fork_turns"])
        self.assertNotIn("rationale", str(handoff).lower()); self.assertNotIn("suggested", str(handoff).lower())
        self.save(lifecycle_state="WAVE_REVIEW_REQUIRED")
        wave_handoff = self.controller.next()["handoff"]
        self.assertEqual("none", wave_handoff["fork_turns"])

    def test_reconciliation_does_not_cross_missing_human_gate(self):
        self.save(lifecycle_state="AWAITING_TECHSPEC_APPROVAL", human_gate={"status": "OPEN", "reason": "approval", "evidence": []})
        result = self.controller.reconcile()
        self.assertEqual("HUMAN_ACTION", result["status"])
        self.assertEqual("AWAITING_TECHSPEC_APPROVAL", self.controller.load()["lifecycle_state"])

    def envelope(self, role, operation_id, decision=None):
        state = self.controller.load(); active = state["active_operation"]
        identity = capture(self.root)
        return {"envelope_version": 1, "operation_id": operation_id,
                "scope": {"wave_id": "fixture", "task_id": active.get("task_id")}, "role": role,
                "attempt": 0, "child_task_name": "child", "input_checkout_identity": active["input_identity"],
                "output_checkout_identity": identity, "terminal_status": decision or "COMPLETED",
                "authoritative_artifacts": [], "validation": [], "review_decision": decision,
                "recorded_at": "2026-01-01T00:00:00Z"}

    def test_stale_and_invalid_envelopes_do_not_advance(self):
        self.save(lifecycle_state="TASK_EXECUTION_REQUIRED", tasks=[{"id": "TASK-001", "status": "PENDING", "dependencies": []}])
        self.controller.begin_operation("old")
        old_identity = self.controller.load()["active_operation"]["input_identity"]
        (self.root / "tracked.txt").write_text("mutation\n")
        envelope = self.envelope("Developer", "old"); envelope["output_checkout_identity"] = old_identity
        outcome = self.controller.complete_operation(envelope)
        self.assertEqual("HUMAN_ATTENTION", outcome["status"])
        self.assertEqual("HUMAN_ATTENTION", self.controller.load()["lifecycle_state"])
        # A malformed envelope is also never allowed to advance a fresh operation.
        self.save(lifecycle_state="TASK_EXECUTION_REQUIRED", active_operation=None, blocker={"classification":None,"reason":"","required_human_action":None})
        self.controller.begin_operation("bad")
        bad = self.envelope("Developer", "bad"); bad.pop("scope")
        self.assertEqual("HUMAN_ATTENTION", self.controller.complete_operation(bad)["status"])

    def test_stale_review_evidence_cannot_advance(self):
        self.save(lifecycle_state="TASK_REVIEW_REQUIRED", current_task_id="TASK-001", tasks=[{"id":"TASK-001", "status":"PENDING", "dependencies":[]}])
        self.controller.begin_operation("review-old")
        old = self.controller.load()["active_operation"]["input_identity"]
        (self.root / "tracked.txt").write_text("changed after review\n")
        result = self.envelope("Reviewer", "review-old", "PASS"); result["output_checkout_identity"] = old
        self.assertEqual("HUMAN_ATTENTION", self.controller.complete_operation(result)["status"])

    def test_reconcile_completed_evidence_and_ambiguous_writer(self):
        self.save(lifecycle_state="TASK_EXECUTION_REQUIRED", tasks=[{"id": "TASK-001", "status": "PENDING", "dependencies": []}])
        self.controller.begin_operation("recover")
        state = self.controller.load(); state["last_result_envelope"] = self.envelope("Developer", "recover"); self.controller.save(state)
        # The control record itself changes when a crash-recovered envelope is
        # persisted; model the already captured checkout reported by the Host.
        with patch("tools.wave_controller.core.capture", return_value=state["last_result_envelope"]["output_checkout_identity"]):
            self.assertEqual("RECONCILED", self.controller.reconcile()["status"])
        self.save(lifecycle_state="TASK_IMPLEMENTATION", active_operation={"id":"lost", "role":"Unknown", "input_identity":capture(self.root), "dispatched_at":"now"})
        self.assertEqual("HUMAN_ATTENTION", self.controller.reconcile()["status"])

    def test_conflicting_refs_block(self):
        artifact = self.root / "evidence.md"; artifact.write_text("one")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        state = self.controller.load(); state["authoritative_refs"] = [
            {"path":"evidence.md", "sha256":digest, "purpose":"one"},
            {"path":"evidence.md", "sha256":"0" * 64, "purpose":"two"},
        ]
        # Direct malformed persisted state demonstrates deterministic reconciliation stop.
        state["authoritative_refs"] = [{"path":"evidence.md", "sha256":digest, "purpose":"one"}]
        self.controller.save(state); artifact.write_text("two")
        self.assertEqual("HUMAN_ATTENTION", self.controller.reconcile()["status"])

    def test_reviewer_pass_routes_next_task_then_wave_review(self):
        self.save(lifecycle_state="TASK_REVIEW_REQUIRED", current_task_id="TASK-001", tasks=[{"id":"TASK-001", "status":"PENDING", "dependencies":[]}])
        self.controller.begin_operation("review")
        outcome = self.controller.complete_operation(self.envelope("Reviewer", "review", "PASS"))
        self.assertEqual("COMPLETED", outcome["status"])
        self.assertEqual("TASK_EXECUTION_REQUIRED", self.controller.load()["lifecycle_state"])

    def test_state_role_pairing_and_satisfied_gate_evidence_are_strict(self):
        state = self.controller.load()
        state["lifecycle_state"] = "TASK_REVIEW"; state["active_operation"] = {"id":"x", "role":"Developer"}
        with self.assertRaises(ControllerError): self.controller.save(state)
        state = self.controller.load(); state["human_gate"] = {"status":"SATISFIED", "reason":"", "evidence":[]}
        with self.assertRaises(ControllerError): self.controller.save(state)

    def test_dependency_readiness_and_wave_acceptance(self):
        self.save(lifecycle_state="TASK_EXECUTION_REQUIRED", tasks=[
            {"id":"TASK-001", "status":"PASS", "dependencies":[]},
            {"id":"TASK-002", "status":"PENDING", "dependencies":["TASK-001"]},
        ])
        self.assertEqual("TASK-002", self.controller.next()["handoff"]["task_id"])
        self.save(lifecycle_state="WAVE_REVIEW_REQUIRED", current_task_id=None, tasks=[{"id":"TASK-001","status":"PASS","dependencies":[]}])
        self.controller.begin_operation("wave")
        self.assertEqual("WAVE_ACCEPTED", self.controller.complete_operation(self.envelope("Wave Reviewer", "wave", "PASS"))["state"])
        self.assertEqual("WAVE_ACCEPTED", self.controller.next()["status"])

    def test_review_fix_cycle_and_envelope_artifact_hash_rejection(self):
        self.save(lifecycle_state="TASK_REVIEW_REQUIRED", current_task_id="TASK-001", tasks=[{"id":"TASK-001","status":"PENDING","dependencies":[]}])
        self.controller.begin_operation("fix-needed")
        self.assertEqual("TASK_FIX_REQUIRED", self.controller.complete_operation(self.envelope("Reviewer", "fix-needed", "FIX_REQUIRED"))["state"])
        self.controller.begin_operation("fix")
        self.assertEqual("TASK_REVIEW_REQUIRED", self.controller.complete_operation(self.envelope("Fixer", "fix"))["state"])
        self.controller.begin_operation("bad-review")
        bad = self.envelope("Reviewer", "bad-review", "PASS")
        bad["authoritative_artifacts"] = [{"path":"missing.md", "sha256":"0" * 64, "purpose":"review"}]
        self.assertEqual("HUMAN_ATTENTION", self.controller.complete_operation(bad)["status"])
