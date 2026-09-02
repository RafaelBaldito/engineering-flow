import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.domain import (  # noqa: E402
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalState,
    ConflictFailure,
    FailureClassification,
    PersistenceFailure,
    Stage,
    WorkflowStatus,
)
from engineering_flow.orchestrator import PlanningOrchestrator  # noqa: E402
from engineering_flow.runtime import (  # noqa: E402
    CapabilityReport,
    PlanningExecutionResult,
    TerminalState,
)
from engineering_flow.store import WorkflowStore  # noqa: E402


class FakeRuntime:
    provider = "fake"

    def __init__(self, results=None, *, requires_human_approval=True):
        self.requests = []
        self.results = list(results or [])
        self.requires_human_approval = requires_human_approval

    def verify_planning_capabilities(self, repository):
        return CapabilityReport(
            provider=self.provider,
            executable="fake",
            repository_path=str(repository),
            available=True,
            capabilities={"json_events": True, "output_schema": True},
            read_only_planning=True,
        )

    def execute_planning(self, request):
        self.requests.append(request)
        if self.results:
            return self.results.pop(0)
        return PlanningExecutionResult(
            provider=self.provider,
            logical_session_id=request.logical_session_id or "session",
            provider_session_id="thread-1",
            provider_execution_id=f"turn-{len(self.requests)}",
            terminal_state=TerminalState.SUCCEEDED,
            final_payload={
                "artifact_markdown": f"# {request.stage.value}\n",
                "summary": "generated",
                "requires_human_approval": self.requires_human_approval,
                "approval_reason": "review required",
            },
        )


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        self.runtime = FakeRuntime()
        self.orchestrator = PlanningOrchestrator(self.store, self.runtime)

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def approve_current(self, workflow):
        artifact = self.store.list_artifacts(workflow.id, workflow.stage)[-1]
        return self.orchestrator.approve(workflow.id, artifact.id, "reviewer")

    def test_required_workflow_is_sequential_and_context_is_scoped(self):
        feature = "Build a durable planning control plane.\n"
        workflow = self.orchestrator.run(self.root, feature)
        self.assertEqual(workflow.status, WorkflowStatus.AWAITING_APPROVAL)
        self.assertEqual(workflow.stage, Stage.PRD)
        self.assertEqual(len(self.runtime.requests), 1)
        feature_path = Path(self.runtime.requests[0].authoritative_input_paths[0])
        self.assertEqual(feature_path.read_bytes(), feature.encode())
        self.assertEqual(
            self.runtime.requests[0].authoritative_input_hashes[0],
            hashlib.sha256(feature.encode()).hexdigest(),
        )
        self.assertEqual(workflow.feature_input_path, str(feature_path))
        self.assertEqual(workflow.feature_input_sha256, hashlib.sha256(feature.encode()).hexdigest())

        workflow = self.approve_current(workflow)
        self.assertEqual((workflow.status, workflow.stage), (WorkflowStatus.CREATED, Stage.TECHSPEC))
        workflow = self.orchestrator.resume(workflow.id)
        self.assertEqual(workflow.status, WorkflowStatus.AWAITING_APPROVAL)
        self.assertEqual(len(self.runtime.requests[-1].authoritative_input_paths), 2)
        self.assertIn("no authority to approve", self.runtime.requests[-1].instruction)
        self.assertNotIn("future", self.runtime.requests[-1].instruction.lower())

        workflow = self.approve_current(workflow)
        workflow = self.orchestrator.resume(workflow.id)
        self.assertEqual(workflow.stage, Stage.TASK_PLAN)
        self.assertEqual(len(self.runtime.requests[-1].authoritative_input_paths), 3)
        workflow = self.approve_current(workflow)
        self.assertEqual((workflow.status, workflow.stage), (WorkflowStatus.COMPLETED, Stage.READY_FOR_WAVE_2))
        self.assertEqual(len(self.store.list_artifacts(workflow.id)), 3)

    def test_automatic_and_conditional_policies_record_waiting_then_auto_approval(self):
        runtime = FakeRuntime()
        orchestrator = PlanningOrchestrator(
            self.store,
            runtime,
            approval_policies={Stage.PRD: "automatic", Stage.TECHSPEC: "conditional", Stage.TASK_PLAN: "required"},
        )
        workflow = orchestrator.run(self.root, "feature")
        self.assertEqual(workflow.stage, Stage.TECHSPEC)
        prd = self.store.list_artifacts(workflow.id, Stage.PRD)[0]
        self.assertEqual(prd.approval_state, ApprovalState.AUTO_APPROVED)
        approval = self.store._connection.execute(
            "SELECT decision FROM approvals WHERE artifact_id = ?", (prd.id,)
        ).fetchone()
        self.assertEqual(approval[0], ApprovalDecision.AUTO_APPROVED.value)
        self.assertTrue(any(event.type == "stage.started" for event in self.store.list_events(workflow.id)))

    def test_capability_report_must_satisfy_every_required_control(self):
        class UnsafeRuntime(FakeRuntime):
            def verify_planning_capabilities(self, repository):
                return CapabilityReport(
                    provider=self.provider,
                    executable="fake",
                    repository_path=str(repository),
                    available=True,
                    capabilities={"json_events": False, "output_schema": False},
                    read_only_planning=False,
                )

            def execute_planning(self, request):
                raise AssertionError("unsafe capability reports must not execute")

        runtime = UnsafeRuntime()
        workflow = PlanningOrchestrator(self.store, runtime).run(self.root, "feature")
        self.assertEqual(workflow.status, WorkflowStatus.FAILED)
        self.assertEqual(runtime.requests, [])
        execution = self.store.get_latest_execution(workflow.id)
        self.assertEqual(execution.failure_classification, FailureClassification.PROVIDER)

    def test_conditional_policy_covers_human_and_automatic_branches(self):
        for requires_human_approval in (True, False):
            with self.subTest(requires_human_approval=requires_human_approval):
                runtime = FakeRuntime(requires_human_approval=requires_human_approval)
                orchestrator = PlanningOrchestrator(
                    self.store,
                    runtime,
                    approval_policies={Stage.PRD: ApprovalPolicy.CONDITIONAL},
                )
                workflow = orchestrator.run(self.root, "feature")
                artifact = self.store.list_artifacts(workflow.id, Stage.PRD)[-1]
                if requires_human_approval:
                    self.assertEqual(workflow.status, WorkflowStatus.AWAITING_APPROVAL)
                    self.assertEqual(artifact.approval_state, ApprovalState.PENDING)
                else:
                    self.assertEqual(workflow.stage, Stage.TECHSPEC)
                    self.assertEqual(artifact.approval_state, ApprovalState.AUTO_APPROVED)

    def test_approval_boundary_is_recoverable_after_reopen(self):
        class InterruptingStore(WorkflowStore):
            interrupt_after_approval = False

            def record_approval(self, *args, **kwargs):
                approval = super().record_approval(*args, **kwargs)
                if self.interrupt_after_approval:
                    self.interrupt_after_approval = False
                    raise RuntimeError("simulated interruption after approval commit")
                return approval

        self.store.close()
        store = InterruptingStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        runtime = FakeRuntime(requires_human_approval=False)
        orchestrator = PlanningOrchestrator(
            store,
            runtime,
            approval_policies={Stage.PRD: ApprovalPolicy.AUTOMATIC},
        )
        store.interrupt_after_approval = True
        with self.assertRaises(RuntimeError):
            orchestrator.run(self.root, "feature")
        workflow_id = store.get_latest_execution(
            store._connection.execute("SELECT id FROM workflows ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        ).workflow_id
        store.close()

        reopened = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        self.store = reopened
        resumed = PlanningOrchestrator(
            reopened,
            runtime,
            approval_policies={Stage.PRD: ApprovalPolicy.AUTOMATIC},
        ).resume(workflow_id)
        self.assertEqual((resumed.stage, resumed.status), (Stage.TECHSPEC, WorkflowStatus.AWAITING_APPROVAL))
        self.assertEqual(len(reopened.list_artifacts(workflow_id, Stage.PRD)), 1)
        self.assertEqual(len(reopened._connection.execute("SELECT * FROM approvals WHERE workflow_id = ?", (workflow_id,)).fetchall()), 1)

    def test_human_approval_boundary_is_recoverable_after_reopen(self):
        class InterruptingStore(WorkflowStore):
            interrupt_after_approval = False

            def record_approval(self, *args, **kwargs):
                approval = super().record_approval(*args, **kwargs)
                if self.interrupt_after_approval:
                    self.interrupt_after_approval = False
                    raise RuntimeError("simulated interruption after approval commit")
                return approval

        self.store.close()
        store = InterruptingStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        self.store = store
        runtime = FakeRuntime()
        orchestrator = PlanningOrchestrator(store, runtime)
        workflow = orchestrator.run(self.root, "feature")
        artifact = store.list_artifacts(workflow.id, Stage.PRD)[0]
        store.interrupt_after_approval = True
        with self.assertRaises(RuntimeError):
            orchestrator.approve(workflow.id, artifact.id)
        store.close()

        reopened = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        self.store = reopened
        resumed = PlanningOrchestrator(reopened, runtime).resume(workflow.id)
        self.assertEqual((resumed.stage, resumed.status), (Stage.TECHSPEC, WorkflowStatus.AWAITING_APPROVAL))
        self.assertEqual(reopened.get_artifact(artifact.id).approval_state, ApprovalState.APPROVED)

    def test_intent_boundary_can_resume_without_a_duplicate_operation(self):
        class InterruptingStore(WorkflowStore):
            interrupt_intent = True

            def create_generation_intent(self, *args, **kwargs):
                if self.interrupt_intent:
                    self.interrupt_intent = False
                    raise RuntimeError("simulated interruption before intent commit")
                return super().create_generation_intent(*args, **kwargs)

        self.store.close()
        store = InterruptingStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        self.store = store
        runtime = FakeRuntime()
        orchestrator = PlanningOrchestrator(store, runtime)
        with self.assertRaises(RuntimeError):
            orchestrator.run(self.root, "feature")
        workflow_id = store._connection.execute(
            "SELECT id FROM workflows ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        resumed = orchestrator.resume(workflow_id)
        self.assertEqual(resumed.status, WorkflowStatus.AWAITING_APPROVAL)
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(len(store.reconcile_operations(workflow_id)), 0)

    def test_feature_input_write_interruption_rolls_back_workflow_creation(self):
        with patch.object(Path, "write_bytes", side_effect=OSError("simulated input interruption")):
            with self.assertRaises(PersistenceFailure):
                self.orchestrator.create_workflow(self.root, "feature")
        self.assertEqual(
            self.store._connection.execute("SELECT COUNT(*) FROM workflows").fetchone()[0],
            0,
        )
        self.assertEqual(
            list((self.root / ".engineering-flow" / "workflows").rglob("feature-request.md")),
            [],
        )

    def test_artifact_write_boundary_becomes_human_attention_on_resume(self):
        class InterruptingStore(WorkflowStore):
            interrupt_artifact = True

            def complete_generation(self, *args, **kwargs):
                if self.interrupt_artifact:
                    self.interrupt_artifact = False
                    raise RuntimeError("simulated interruption at artifact boundary")
                return super().complete_generation(*args, **kwargs)

        self.store.close()
        store = InterruptingStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        self.store = store
        runtime = FakeRuntime()
        orchestrator = PlanningOrchestrator(store, runtime)
        with self.assertRaises(RuntimeError):
            orchestrator.run(self.root, "feature")
        workflow_id = store._connection.execute(
            "SELECT id FROM workflows ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        store.close()
        reopened = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        self.store = reopened
        resumed = PlanningOrchestrator(reopened, runtime).resume(workflow_id)
        self.assertEqual(resumed.status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(reopened.reconcile_operations(workflow_id), [])

    def test_rejection_requires_explicit_current_stage_regeneration(self):
        workflow = self.orchestrator.run(self.root, "feature")
        original = self.store.list_artifacts(workflow.id, Stage.PRD)[0]
        workflow = self.orchestrator.reject(workflow.id, original.id, "reviewer", "needs more detail")
        self.assertEqual(workflow.status, WorkflowStatus.REJECTED)
        self.assertEqual(len(self.store.list_artifacts(workflow.id, Stage.PRD)), 1)
        self.assertEqual(self.orchestrator.resume(workflow.id).status, WorkflowStatus.REJECTED)
        with self.assertRaises(ConflictFailure):
            self.orchestrator.resume(workflow.id, regenerate=Stage.TECHSPEC)
        workflow = self.orchestrator.resume(workflow.id, regenerate=Stage.PRD)
        self.assertEqual(workflow.status, WorkflowStatus.AWAITING_APPROVAL)
        self.assertEqual(len(self.store.list_artifacts(workflow.id, Stage.PRD)), 2)

    def test_unknown_execution_routes_to_human_attention_without_retry(self):
        class BrokenRuntime(FakeRuntime):
            def execute_planning(self, request):
                self.requests.append(request)
                raise RuntimeError("provider stopped before outcome")

        runtime = BrokenRuntime()
        orchestrator = PlanningOrchestrator(self.store, runtime)
        workflow = orchestrator.run(self.root, "feature")
        self.assertEqual(workflow.status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(orchestrator.resume(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(self.store.reconcile_operations(workflow.id), [])

    def test_resume_retries_only_eligible_failure_classifications(self):
        for classification, should_retry in (
            (FailureClassification.PROVIDER, True),
            (FailureClassification.AGENT_EXECUTION, True),
            (FailureClassification.TOOL, True),
            (FailureClassification.WORKFLOW, False),
        ):
            with self.subTest(classification=classification):
                failed = PlanningExecutionResult(
                    provider="fake",
                    logical_session_id="session",
                    provider_session_id=None,
                    provider_execution_id="failed-turn",
                    terminal_state=TerminalState.FAILED,
                    final_payload=None,
                    failure_classification=classification,
                    failure_detail="deterministic failure",
                )
                runtime = FakeRuntime(results=[failed])
                orchestrator = PlanningOrchestrator(self.store, runtime)
                workflow = orchestrator.run(self.root, "feature")
                self.assertEqual(workflow.status, WorkflowStatus.FAILED)
                resumed = orchestrator.resume(workflow.id)
                self.assertEqual(len(runtime.requests), 2 if should_retry else 1)
                self.assertEqual(resumed.status, WorkflowStatus.AWAITING_APPROVAL if should_retry else WorkflowStatus.FAILED)

    def test_retriable_failures_preserve_attempt_evidence_and_allocate_new_intents(self):
        failed = PlanningExecutionResult(
            provider="fake",
            logical_session_id="session",
            provider_session_id=None,
            provider_execution_id="failed-turn",
            terminal_state=TerminalState.FAILED,
            final_payload=None,
            failure_classification=FailureClassification.PROVIDER,
            failure_detail="first failure",
        )
        runtime = FakeRuntime(results=[failed, failed, failed])
        orchestrator = PlanningOrchestrator(self.store, runtime)

        workflow = orchestrator.run(self.root, "feature")
        workflow = orchestrator.resume(workflow.id)
        self.assertEqual(workflow.status, WorkflowStatus.FAILED)
        workflow = orchestrator.resume(workflow.id)

        operations = self.store._connection.execute(
            "SELECT idempotency_key, status, related_record_id FROM operations "
            "WHERE workflow_id = ? AND kind = 'generate' ORDER BY created_at",
            (workflow.id,),
        ).fetchall()
        executions = self.store._connection.execute(
            "SELECT id, lifecycle, failure_classification, failure_detail FROM executions "
            "WHERE workflow_id = ? ORDER BY created_at",
            (workflow.id,),
        ).fetchall()
        self.assertEqual(len(operations), 3)
        self.assertEqual(len({row["idempotency_key"] for row in operations}), 3)
        self.assertEqual([row["lifecycle"] for row in executions], ["failed", "failed", "failed"])
        self.assertEqual([row["failure_detail"] for row in executions], ["first failure"] * 3)

    def test_malformed_final_payload_fails_without_creating_an_artifact(self):
        malformed = PlanningExecutionResult(
            provider="fake",
            logical_session_id="session",
            provider_session_id=None,
            provider_execution_id="malformed-turn",
            terminal_state=TerminalState.SUCCEEDED,
            final_payload={"artifact_markdown": "content"},
        )
        runtime = FakeRuntime(results=[malformed])
        workflow = PlanningOrchestrator(self.store, runtime).run(self.root, "feature")

        self.assertEqual(workflow.status, WorkflowStatus.FAILED)
        self.assertEqual(self.store.list_artifacts(workflow.id), [])
        execution = self.store.get_latest_execution(workflow.id)
        self.assertEqual(execution.failure_classification, FailureClassification.AGENT_EXECUTION)
        self.assertIn("output contract", execution.failure_detail)

    def test_stale_and_duplicate_decisions_conflict_without_mutation(self):
        workflow = self.orchestrator.run(self.root, "feature")
        original = self.store.list_artifacts(workflow.id, Stage.PRD)[0]
        workflow = self.orchestrator.reject(workflow.id, original.id, "reviewer", "regenerate")
        regenerated = self.orchestrator.resume(workflow.id, regenerate=Stage.PRD)
        current = self.store.list_artifacts(workflow.id, Stage.PRD)[-1]
        event_count = len(self.store.list_events(workflow.id))

        with self.assertRaises(ConflictFailure):
            self.orchestrator.approve(workflow.id, original.id)
        self.assertEqual(len(self.store.list_events(workflow.id)), event_count)
        self.orchestrator.approve(workflow.id, current.id)
        with self.assertRaises(ConflictFailure):
            self.orchestrator.approve(workflow.id, current.id)
        self.assertEqual(self.store.get_artifact(current.id).approval_state, ApprovalState.APPROVED)
        self.assertEqual(regenerated.stage, Stage.PRD)


if __name__ == "__main__":
    unittest.main()
