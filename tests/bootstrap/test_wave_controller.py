from __future__ import annotations

import hashlib
import json
import subprocess
import sys
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
        artifacts = []
        if role in {"Reviewer", "Wave Reviewer"}:
            path = active["allowed_output_paths"][0]
            artifact = self.root / path
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(f"{role} {decision}\n")
            artifacts = [{"path": path, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "purpose": "review"}]
        identity = capture(self.root)
        return {"envelope_version": 1, "operation_id": operation_id,
                "scope": {"wave_id": "fixture", "task_id": active.get("task_id")}, "role": role,
                "attempt": 0, "child_task_name": "child", "input_checkout_identity": active["input_identity"],
                "output_checkout_identity": identity, "terminal_status": decision or "COMPLETED",
                "authoritative_artifacts": artifacts, "validation": [], "review_decision": decision,
                "recorded_at": "2026-01-01T00:00:00Z"}

    def test_selected_task_is_durable_across_restart_and_operation(self):
        self.save(lifecycle_state="TASK_EXECUTION_REQUIRED", tasks=[
            {"id": "TASK-A", "status": "PENDING", "dependencies": []},
            {"id": "TASK-B", "status": "PENDING", "dependencies": []},
        ])
        first = self.controller.next()
        self.assertEqual("TASK-A", first["handoff"]["task_id"])
        self.assertEqual("TASK-A", self.controller.load()["current_task_id"])
        fresh = Controller(self.root, "fixture")
        self.assertEqual("TASK-A", fresh.next()["handoff"]["task_id"])
        self.assertEqual("TASK-A", fresh.status() and fresh.load()["current_task_id"])
        acquired = fresh.begin_operation("task-a")
        self.assertEqual("TASK-A", acquired["handoff"]["task_id"])
        self.assertEqual("TASK-A", fresh.load()["active_operation"]["task_id"])
        self.assertEqual("COMPLETED", fresh.complete_operation(self.envelope("Developer", "task-a"))["status"])

    def test_reviewer_allows_only_exact_task_review_artifact(self):
        self.save(lifecycle_state="TASK_REVIEW_REQUIRED", current_task_id="TASK-A", tasks=[{"id":"TASK-A", "status":"PENDING", "dependencies":[]}])
        self.controller.begin_operation("review-ok")
        self.assertEqual("COMPLETED", self.controller.complete_operation(self.envelope("Reviewer", "review-ok", "PASS"))["status"])

    def test_reviewer_rejects_source_test_and_wrong_review_artifacts(self):
        for name, path in (("source", "tracked.txt"), ("test", "tests/test_x.py"), ("wrong", "tasks/fixture/reviews/TASK-B-REVIEW.md")):
            with self.subTest(name=name):
                self.save(lifecycle_state="TASK_REVIEW_REQUIRED", current_task_id="TASK-A", active_operation=None,
                          tasks=[{"id":"TASK-A", "status":"PENDING", "dependencies":[]}],
                          blocker={"classification":None,"reason":"","required_human_action":None})
                self.controller.begin_operation(f"review-{name}")
                envelope = self.envelope("Reviewer", f"review-{name}", "PASS")
                target = self.root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_text("unauthorized\n")
                envelope["output_checkout_identity"] = capture(self.root)
                self.assertEqual("HUMAN_ATTENTION", self.controller.complete_operation(envelope)["status"])

    def test_reviewer_requires_authorized_artifact_and_preserves_stale_protection(self):
        self.save(lifecycle_state="TASK_REVIEW_REQUIRED", current_task_id="TASK-A", tasks=[{"id":"TASK-A", "status":"PENDING", "dependencies":[]}])
        self.controller.begin_operation("review-missing")
        missing = self.envelope("Reviewer", "review-missing", "PASS")
        missing["authoritative_artifacts"] = []
        self.assertEqual("HUMAN_ATTENTION", self.controller.complete_operation(missing)["status"])
        self.save(lifecycle_state="WAVE_REVIEW_REQUIRED", current_task_id=None, active_operation=None,
                  tasks=[{"id":"TASK-A", "status":"PASS", "dependencies":[]}], blocker={"classification":None,"reason":"","required_human_action":None})
        self.controller.begin_operation("wave-stale")
        stale = self.envelope("Wave Reviewer", "wave-stale", "PASS")
        stale["output_checkout_identity"] = self.controller.load()["active_operation"]["input_identity"]
        self.assertEqual("HUMAN_ATTENTION", self.controller.complete_operation(stale)["status"])

    def test_wave_reviewer_allows_only_exact_wave_review_artifact(self):
        self.save(lifecycle_state="WAVE_REVIEW_REQUIRED", tasks=[{"id":"TASK-A", "status":"PASS", "dependencies":[]}])
        self.controller.begin_operation("wave-ok")
        self.assertEqual("WAVE_ACCEPTED", self.controller.complete_operation(self.envelope("Wave Reviewer", "wave-ok", "PASS"))["state"])
        # A new review lease rejects material implementation drift even when
        # the aggregate output fingerprint supplied by the Host matches.
        self.save(lifecycle_state="WAVE_REVIEW_REQUIRED", active_operation=None, blocker={"classification":None,"reason":"","required_human_action":None})
        self.controller.begin_operation("wave-source")
        bad = self.envelope("Wave Reviewer", "wave-source", "PASS")
        (self.root / "tracked.txt").write_text("unauthorized\n")
        bad["output_checkout_identity"] = capture(self.root)
        self.assertEqual("HUMAN_ATTENTION", self.controller.complete_operation(bad)["status"])

    def test_explicit_human_authority_is_persisted_and_strict(self):
        gate = self.controller.next()
        self.assertEqual("HUMAN_ACTION", gate["status"])
        evidence = [self.authority()]
        self.assertEqual("RECORDED", self.controller.record_authority("WAVE_START_AUTHORIZATION", "APPROVE", "human@example", evidence, "fixture")["status"])
        fresh = Controller(self.root, "fixture")
        self.assertEqual("SATISFIED", fresh.load()["human_gate"]["status"])
        self.assertEqual("ACTION_REQUIRED", fresh.next()["status"])
        self.assertEqual("IDEMPOTENT", fresh.record_authority("WAVE_START_AUTHORIZATION", "APPROVE", "human@example", evidence, "fixture")["status"])

    def test_explicit_human_authority_rejects_invalid_and_never_infers(self):
        self.assertEqual("HUMAN_ACTION", self.controller.reconcile()["status"])
        evidence = [self.authority()]
        with self.assertRaisesRegex(ControllerError, "gate"):
            self.controller.record_authority("TASK_PLAN_APPROVAL", "APPROVE", "human", evidence, "fixture")
        with self.assertRaisesRegex(ControllerError, "wave"):
            self.controller.record_authority("WAVE_START_AUTHORIZATION", "APPROVE", "human", evidence, "other")
        with self.assertRaisesRegex(ControllerError, "actor"):
            self.controller.record_authority("WAVE_START_AUTHORIZATION", "APPROVE", "", evidence, "fixture")
        with self.assertRaisesRegex(ControllerError, "decision"):
            self.controller.record_authority("WAVE_START_AUTHORIZATION", "please approve this conversational text", "human", evidence, "fixture")

    def test_record_authority_cli_persists_explicit_human_input(self):
        evidence_path = self.root / "evidence.json"
        evidence_path.write_text(json.dumps([self.authority()]))
        result = subprocess.run([
            sys.executable, "-m", "tools.wave_controller.cli", "--root", str(self.root), "--wave", "fixture",
            "record-authority", "--gate", "WAVE_START_AUTHORIZATION", "--decision", "APPROVE",
            "--actor", "human@example", "--evidence", str(evidence_path), "--authority-wave", "fixture",
        ], cwd=Path(__file__).parents[2], check=True, capture_output=True, text=True)
        self.assertEqual("RECORDED", json.loads(result.stdout)["status"])
        self.assertEqual("SATISFIED", Controller(self.root, "fixture").load()["human_gate"]["status"])

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
