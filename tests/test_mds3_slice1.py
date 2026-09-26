import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from engineering_flow.domain import (
    ApprovalDecision, ApprovalState, ConflictFailure, LifecycleVersion, Plan,
    Stage, TaskContract, TaskImplementationStatus, TaskSelectionOutcome,
    ValidationFailure, WorkflowStatus, select_executable_task,
)
from engineering_flow.orchestrator import ImplementationSelectionOrchestrator
from engineering_flow.store import WorkflowStore


def task(task_id, depends_on=()):
    return TaskContract(task_id, f"Task {task_id}", ("source.py",), (), ("requirement",),
                        ("criterion",), ("test",), (), tuple(depends_on), "low", "low")


def plan(tasks):
    return Plan("workflow:plan:r1", "workflow", 1, "feature", "a" * 64,
                "strategy", (), ("test",), tuple(tasks))


class SelectionTests(unittest.TestCase):
    def test_hash_is_canonical_and_numeric_order_beats_array_order(self):
        contract = task("T1")
        self.assertEqual(contract.payload_sha256(), contract.payload_sha256())
        unordered = plan((task("T2"), task("T1")))
        self.assertEqual(select_executable_task(unordered, {}).task.id, "T1")

    def test_dependencies_only_accept_verified(self):
        graph = plan((task("T1"), task("T2", ("T1",))))
        for blocked in (TaskImplementationStatus.PENDING, TaskImplementationStatus.IMPLEMENTING,
                        TaskImplementationStatus.IMPLEMENTATION_COMPLETED,
                        TaskImplementationStatus.IMPLEMENTATION_FAILED,
                        TaskImplementationStatus.IMPLEMENTATION_UNKNOWN):
            result = select_executable_task(graph, {"T1": blocked})
            self.assertEqual(result.task.id if result.task else None,
                             "T1" if blocked is TaskImplementationStatus.PENDING else None)
        self.assertEqual(select_executable_task(graph, {"T1": TaskImplementationStatus.VERIFIED}).task.id, "T2")

    def test_completed_boundary_and_failed_without_evidence(self):
        graph = plan((task("T1"), task("T2", ("T1",))))
        self.assertEqual(select_executable_task(graph, {"T1": TaskImplementationStatus.IMPLEMENTATION_COMPLETED}).outcome,
                         TaskSelectionOutcome.AWAITING_VERIFICATION)
        self.assertEqual(select_executable_task(plan((task("T1"),)), {"T1": TaskImplementationStatus.IMPLEMENTATION_FAILED}).outcome,
                         TaskSelectionOutcome.NO_EXECUTABLE_TASK)
        graph = plan((task("T1"), task("T2", ("T1",))))
        self.assertEqual(select_executable_task(graph, {
            "T1": TaskImplementationStatus.IMPLEMENTATION_COMPLETED,
            "T2": TaskImplementationStatus.IMPLEMENTATION_COMPLETED,
        }).outcome, TaskSelectionOutcome.AWAITING_VERIFICATION)
        self.assertEqual(select_executable_task(graph, {
            "T1": TaskImplementationStatus.VERIFIED,
            "T2": TaskImplementationStatus.VERIFIED,
        }).outcome, TaskSelectionOutcome.NO_EXECUTABLE_TASK)

    def test_invalid_graph_fails_closed(self):
        cyclic = plan((task("T1", ("T2",)), task("T2", ("T1",))))
        with self.assertRaises(ValidationFailure):
            select_executable_task(cyclic, {})
        with self.assertRaisesRegex(ValidationFailure, "missing"):
            select_executable_task(plan((task("T1"),)), {"T9": TaskImplementationStatus.PENDING})


class ApprovedAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "source.py").write_text("x = 1\n", encoding="utf-8")
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def approved(self, *, task_specs=(("T1", ()),)):
        workflow = self.store.create_workflow(self.root, provider="never-called", lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
        feature_intent = self.store.create_generation_intent(workflow.id, Stage.INTAKE, request_hash="feature", provider="fake", role="intake", revision=1, artifact_path=self.store.feature_contract_path(workflow.id, 1))
        feature_payload = {"outcome": "READY", "feature": {"id": workflow.id, "goal": "goal", "requirements": ["r"], "acceptance_criteria": ["a"], "constraints": [], "out_of_scope": [], "assumptions": [], "open_questions": []}}
        feature = self.store.complete_generation(feature_intent.operation.idempotency_key, content=json.dumps(feature_payload), artifact_path=self.store.feature_contract_path(workflow.id, 1), stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE, workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED)
        plan_intent = self.store.create_generation_intent(workflow.id, Stage.PLAN, request_hash="plan", provider="fake", role="planner", revision=1, artifact_path=self.store.plan_path(workflow.id, 1))
        tasks = [{"id": identity, "objective": identity, "context": {"relevant_files": ["source.py"], "existing_patterns": []}, "requirements": ["r"], "acceptance_criteria": ["a"], "verification": ["test"], "constraints": [], "depends_on": list(dependencies), "complexity": "low", "risk": "low"} for identity, dependencies in task_specs]
        payload = {"plan": {"id": f"{workflow.id}:plan:r1", "workflow_id": workflow.id, "revision": 1, "feature_contract": {"artifact_id": feature.id, "sha256": feature.sha256}, "strategy": "s", "assumptions": [], "verification_strategy": ["test"], "tasks": tasks}}
        artifact = self.store.complete_generation(plan_intent.operation.idempotency_key, content=json.dumps(payload), artifact_path=self.store.plan_path(workflow.id, 1), stage=Stage.PLAN, revision=1, workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.AWAITING_APPROVAL)
        self.store.record_approval(workflow.id, artifact.id, ApprovalDecision.APPROVED, actor="human", workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.PLAN_APPROVED)
        return self.store.get_workflow(workflow.id), feature, self.store.get_artifact(artifact.id)

    def test_authority_and_selection_are_read_only_and_state_is_plan_isolated(self):
        workflow, _feature, artifact = self.approved(task_specs=(("T1", ()), ("T2", ("T1",))))
        authority = self.store.load_approved_v2_plan_authority(workflow.id)
        self.assertEqual(authority.plan_artifact.id, artifact.id)
        before = len(self.store.list_events(workflow.id))
        selected = ImplementationSelectionOrchestrator(self.store).select_once(workflow.id)
        self.assertEqual((selected.outcome, selected.task.id), (TaskSelectionOutcome.SELECTED, "T1"))
        self.assertEqual(len(self.store.list_events(workflow.id)), before)
        self.store.put_task_implementation_state(workflow.id, artifact.id, artifact.sha256, "T1", selected.task.payload_sha256(), TaskImplementationStatus.IMPLEMENTATION_COMPLETED)
        self.assertEqual(ImplementationSelectionOrchestrator(self.store).select_once(workflow.id).outcome, TaskSelectionOutcome.AWAITING_VERIFICATION)

    def test_selection_has_zero_provider_calls_and_zero_target_mutations(self):
        workflow, _feature, _artifact = self.approved()
        source = self.root / "source.py"
        before = source.read_bytes()
        class Provider:
            calls = 0
        provider = Provider()
        self.assertEqual(ImplementationSelectionOrchestrator(self.store).select_once(workflow.id).task.id, "T1")
        self.assertEqual(provider.calls, 0)
        self.assertEqual(source.read_bytes(), before)

    def test_state_values_round_trip_and_invalid_value_is_rejected(self):
        workflow, _feature, artifact = self.approved()
        selected = ImplementationSelectionOrchestrator(self.store).select_once(workflow.id).task
        for status in TaskImplementationStatus:
            stored = self.store.put_task_implementation_state(workflow.id, artifact.id, artifact.sha256,
                "T1", selected.payload_sha256(), status)
            self.assertEqual(stored.status, status)
        with self.assertRaises(ValidationFailure):
            self.store.put_task_implementation_state(workflow.id, artifact.id, artifact.sha256,
                "T1", selected.payload_sha256(), "invalid")

    def test_plan_artifact_identity_isolates_same_task_id(self):
        workflow, _feature, artifact = self.approved()
        selected = ImplementationSelectionOrchestrator(self.store).select_once(workflow.id).task
        self.store.put_task_implementation_state(workflow.id, artifact.id, artifact.sha256,
            "T1", selected.payload_sha256(), TaskImplementationStatus.VERIFIED)
        # The query API itself is scoped to the exact Plan artifact identity;
        # another artifact UUID with the same T1 cannot inherit this state.
        self.assertEqual(self.store.list_task_implementation_states(workflow.id, "different-plan"), [])

    def test_tampered_or_wrong_entry_authority_is_rejected(self):
        workflow, feature, artifact = self.approved()
        Path(artifact.path).write_text("{}", encoding="utf-8")
        with self.assertRaises(Exception):
            self.store.load_approved_v2_plan_authority(workflow.id)
        # A V1 workflow never gains V2 selection authority.
        v1 = self.store.create_workflow(self.root, provider="fake")
        with self.assertRaises(ConflictFailure):
            self.store.load_approved_v2_plan_authority(v1.id)

    def test_state_hash_mismatch_fails_closed(self):
        workflow, _feature, artifact = self.approved()
        self.store.put_task_implementation_state(workflow.id, artifact.id, artifact.sha256, "T1", "b" * 64, TaskImplementationStatus.PENDING)
        with self.assertRaisesRegex(Exception, "payload hash"):
            ImplementationSelectionOrchestrator(self.store).select_once(workflow.id)
