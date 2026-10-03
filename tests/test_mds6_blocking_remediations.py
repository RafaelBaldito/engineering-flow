"""Regressions for consolidated MDS #6 blockers R1--R4."""
import unittest

from engineering_flow.domain import WorkflowStatus
from engineering_flow.fix import FixAttemptOrchestrator
from engineering_flow.review import ReviewAttemptOrchestrator
from engineering_flow.runtime import RuntimeExecutionResult, TerminalState
from tests import test_mds5_slice3 as slice3
from tests.test_mds6_slice3 import FixRuntime


class UnprovenSuccessRuntime:
    provider = "unproven-success"

    def __init__(self, root):
        self.root, self.requests = root, []

    def execute(self, request):
        self.requests.append(request)
        (self.root / "source.py").write_text("fixed\n")
        # Deliberately do not invoke request.provider_started.
        return RuntimeExecutionResult(self.provider, request.logical_session_id, "session", "execution",
            TerminalState.SUCCEEDED, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]})


class Mds6BlockingRemediationTests(unittest.TestCase):
    setUp = slice3.Mds5Slice3Tests.setUp
    tearDown = slice3.Mds5Slice3Tests.tearDown
    prepare = slice3.Mds5Slice3Tests.prepare
    changes = slice3.Mds5Slice3Tests.changes

    def source(self, *, findings=None):
        workflow, verification, verifier = self.prepare([["/bin/true"]])
        self.assertEqual(verifier.run(verification).value, "verified")
        payload = findings or self.changes
        ReviewAttemptOrchestrator(self.store, slice3.RecordingReviewer(payload)).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        return workflow, verification

    def fix(self, workflow, verification, *, limit=3, runtime=None, **kwargs):
        runtime = runtime or FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        value = FixAttemptOrchestrator(self.store, runtime, **kwargs).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256, max_review_cycles=limit)
        return value, runtime

    def test_r1_global_cycles_select_current_round_and_stop_at_limit(self):
        workflow, verification = self.source()
        self.assertIsNotNone(self.fix(workflow, verification, limit=3)[0])
        ReviewAttemptOrchestrator(self.store, slice3.RecordingReviewer(self.changes)).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        cycles = [row[0] for row in self.store._connection.execute(
            "SELECT sequence FROM review_attempts ORDER BY sequence")]
        self.assertEqual(cycles, [1, 2])
        second = self.store.load_fix_source_review_evidence(workflow.id,
            verification.producer.task_contract_id, verification.producer.task_contract_sha256)
        self.assertEqual(second["review_cycle"], 2)
        self.assertIsNotNone(self.fix(workflow, verification, limit=3,
            runtime=FixRuntime(self.root, {"summary": "fixed again", "addressed_blocking_finding_ids": ["R-1"]},
                mutate=lambda: (self.root / "source.py").write_text("fixed-again\n")))[0])
        fixes = self.store._connection.execute("SELECT remediation_cycle_ordinal,source_review_attempt_id FROM fix_attempts ORDER BY created_at").fetchall()
        self.assertEqual([row[0] for row in fixes], [1, 2])
        self.assertEqual(fixes[-1][1], second["attempt_id"])

        # A fresh fixture proves that a terminal cycle at the configured limit
        # becomes a human stop instead of creating a second FIX.
        self.tearDown(); self.setUp()
        workflow, verification = self.source()
        self.assertIsNotNone(self.fix(workflow, verification, limit=2)[0])
        ReviewAttemptOrchestrator(self.store, slice3.RecordingReviewer(self.changes)).run_once(workflow.id,
            task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        result, runtime = self.fix(workflow, verification, limit=2)
        self.assertIsNone(result); self.assertEqual(runtime.requests, [])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fix_attempts").fetchone()[0], 1)

    def test_r2_control_drift_before_intent_and_before_dispatch_has_zero_dispatch(self):
        workflow, verification = self.source()
        manifest = self.root / ".engineering-flow" / "verification" / "manifest-v1.json"
        manifest.write_text('{"drift":"before-intent"}')
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1"]})
        with self.assertRaisesRegex(Exception, "drifted.*REVIEW evidence"):
            self.fix(workflow, verification, runtime=runtime)
        self.assertEqual(runtime.requests, [])
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fix_attempts").fetchone()[0], 0)

        self.tearDown(); self.setUp()
        workflow, verification = self.source(); manifest = self.root / ".engineering-flow" / "verification" / "manifest-v1.json"
        result, runtime = self.fix(workflow, verification,
            before_dispatch=lambda: manifest.write_text('{"drift":"before-dispatch"}'))
        self.assertIsNone(result); self.assertEqual(runtime.requests, [])
        self.assertEqual(self.store._connection.execute("SELECT status FROM fix_attempts").fetchone()[0], "fixing")

    def test_r3_foreign_binding_with_matching_count_cannot_produce_verify(self):
        findings = {"outcome": "CHANGES_REQUESTED", "summary": "two findings", "findings": [
            *self.changes["findings"], {"id": "R-2", "severity": "blocking", "category": "correctness",
                "description": "A second defect.", "path": "source.py", "line": 1,
                "requirement_reference": "acceptance 1"}]}
        workflow, verification = self.source(findings=findings)
        runtime = FixRuntime(self.root, {"summary": "fixed", "addressed_blocking_finding_ids": ["R-1", "R-2"]},
            mutate=lambda: (self.root / "source.py").write_text("fixed\n"))
        original = self.store.finish_fix_attempt
        def corrupt(*args, **kwargs):
            original(*args, **kwargs)
            self.store._connection.execute("DROP TRIGGER fix_attempt_finding_bindings_no_update")
            bindings = self.store._connection.execute("SELECT id,review_finding_row_id,finding_sha256 FROM fix_attempt_finding_bindings ORDER BY source_ordinal").fetchall()
            first, second = bindings
            # Substitute the second finding's canonical hash into the first
            # binding while preserving row count and IDs.  Count-only checks
            # would accept this corrupted provenance.
            self.store._connection.execute("UPDATE fix_attempt_finding_bindings SET finding_sha256=? WHERE id=?",
                (second["finding_sha256"], first["id"]))
        self.store.finish_fix_attempt = corrupt
        self.fix(workflow, verification, runtime=runtime)
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_attempts WHERE producer_operation_id IN (SELECT operation_id FROM fix_attempts)").fetchone()[0], 0)

    def test_r4_success_without_provider_started_is_not_completed_or_verified(self):
        workflow, verification = self.source()
        runtime = UnprovenSuccessRuntime(self.root)
        with self.assertRaisesRegex(Exception, "completion durable authority"):
            self.fix(workflow, verification, runtime=runtime)
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(self.store._connection.execute("SELECT status FROM fix_attempts").fetchone()[0], "fixing")
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_attempts").fetchone()[0], 1)
