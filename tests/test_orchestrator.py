import hashlib
import json
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
    ArtifactCorruptionFailure,
    ConflictFailure,
    FailureClassification,
    CanonicalStage,
    HumanAttentionOutcome,
    LifecycleVersion,
    PersistenceFailure,
    Role,
    Stage,
    TaskArtifactType,
    ValidationFailure,
    WorkKind,
    WorkflowStatus,
)
from engineering_flow.orchestrator import CanonicalLifecycleOrchestrator, IntakeOrchestrator, PlanningOrchestrator, V2PlanOrchestrator  # noqa: E402
from engineering_flow.runtime import (  # noqa: E402
    CapabilityReport,
    PlanningExecutionResult,
    RuntimeProgressEvent,
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

    def test_intake_persists_needs_clarification_and_stops(self):
        class ClarifyingRuntime(FakeRuntime):
            def execute_planning(self, request):
                self.requests.append(request)
                return PlanningExecutionResult(
                    provider=self.provider, logical_session_id=request.logical_session_id or "session",
                    provider_session_id="thread-1", provider_execution_id="turn-1",
                    terminal_state=TerminalState.SUCCEEDED, final_payload={
                        "outcome": "NEEDS_CLARIFICATION", "feature": {
                            "id": request.workflow_id, "goal": "Allow users to cancel orders.",
                            "requirements": [], "acceptance_criteria": [], "constraints": [],
                            "out_of_scope": [], "assumptions": [],
                            "open_questions": ["Which order states allow a user to cancel an order?"],
                        },
                    },
                )

        runtime = ClarifyingRuntime()
        workflow = IntakeOrchestrator(self.store, runtime).run(self.root, "Allow users to cancel orders.")

        self.assertEqual((workflow.lifecycle_version.value, workflow.stage, workflow.status.value),
                         ("v2", Stage.INTAKE, "needs_clarification"))
        self.assertEqual(len(runtime.requests), 1)
        instruction = runtime.requests[0].instruction
        self.assertIn("inspect the repository instead of asking", instruction)
        self.assertIn("safe engineering assumptions", instruction)
        self.assertIn("material product or business decision", instruction)
        artifacts = self.store.list_artifacts(workflow.id)
        self.assertEqual([(artifact.stage, artifact.approval_state.value) for artifact in artifacts],
                         [(Stage.INTAKE, "not_required")])
        completed = [event for event in self.store.list_events(workflow.id) if event.type == "intake.completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].payload, {"outcome": "NEEDS_CLARIFICATION", "question_count": 1})

    def test_one_answer_creates_immutable_second_contract_and_new_current_question(self):
        def contract(workflow_id, outcome, questions):
            return {"outcome": outcome, "feature": {"id": workflow_id, "goal": "Goal",
                "requirements": [] if questions else ["Requirement"],
                "acceptance_criteria": [] if questions else ["Criterion"], "constraints": [],
                "out_of_scope": [], "assumptions": [], "open_questions": questions}}

        class Runtime(FakeRuntime):
            def execute_planning(self, request):
                self.requests.append(request)
                payload = contract(request.workflow_id, "NEEDS_CLARIFICATION", ["Q1", "Q2", "Q3"])
                if len(self.requests) == 2:
                    payload = contract(request.workflow_id, "NEEDS_CLARIFICATION", ["Q3", "Q4"])
                return PlanningExecutionResult(self.provider, request.logical_session_id or "s", "thread", "turn",
                    TerminalState.SUCCEEDED, payload)

        runtime = Runtime()
        intake = IntakeOrchestrator(self.store, runtime)
        workflow = intake.run(self.root, "Ambiguous request")
        source = self.store.list_artifacts(workflow.id, Stage.INTAKE)[0]
        original = Path(source.path).read_bytes()
        current = self.store.get_active_clarification(workflow.id)
        self.assertEqual(current.question, "Q1")
        workflow = intake.resume_answer(workflow.id, "A1")
        artifacts = self.store.list_artifacts(workflow.id, Stage.INTAKE)
        self.assertEqual([item.revision for item in artifacts], [1, 2])
        self.assertEqual(Path(source.path).read_bytes(), original)
        self.assertTrue(artifacts[1].path.endswith("001-feature-contract-r002.json"))
        records = self.store.list_clarifications(workflow.id)
        self.assertEqual((records[0].question, records[0].answer, records[0].result_feature_contract_artifact_id), ("Q1", "A1", artifacts[1].id))
        self.assertEqual((records[1].question, records[1].answer), ("Q3", None))
        self.assertEqual(len(runtime.requests), 2)
        self.assertIn("A1", runtime.requests[1].instruction)

    def test_answer_survives_failed_attempt_and_retry_uses_revision_two(self):
        def payload(workflow_id):
            return {"outcome": "NEEDS_CLARIFICATION", "feature": {"id": workflow_id, "goal": "Goal",
                "requirements": [], "acceptance_criteria": [], "constraints": [], "out_of_scope": [],
                "assumptions": [], "open_questions": ["Q1"]}}

        class Runtime(FakeRuntime):
            def execute_planning(self, request):
                self.requests.append(request)
                if len(self.requests) == 1:
                    return PlanningExecutionResult(self.provider, "s", "thread", "turn", TerminalState.SUCCEEDED, payload(request.workflow_id))
                if len(self.requests) == 2:
                    return PlanningExecutionResult(self.provider, "s", "thread", "turn", TerminalState.FAILED, None,
                        failure_classification=FailureClassification.PROVIDER, failure_detail="offline")
                return PlanningExecutionResult(self.provider, "s", "thread", "turn", TerminalState.SUCCEEDED,
                    {"outcome": "READY", "feature": {"id": request.workflow_id, "goal": "Goal", "requirements": ["R"],
                    "acceptance_criteria": ["A"], "constraints": [], "out_of_scope": [], "assumptions": [], "open_questions": []}})

        runtime = Runtime()
        intake = IntakeOrchestrator(self.store, runtime)
        workflow = intake.run(self.root, "Ambiguous")
        failed = intake.resume_answer(workflow.id, "A1")
        self.assertEqual(failed.status, WorkflowStatus.FAILED)
        active = self.store.get_active_clarification(workflow.id)
        self.assertEqual(active.answer, "A1")
        self.assertEqual(len(self.store.list_artifacts(workflow.id, Stage.INTAKE)), 1)
        ready = intake.resume_answer(workflow.id)
        self.assertEqual(ready.status, WorkflowStatus.READY)
        artifacts = self.store.list_artifacts(workflow.id, Stage.INTAKE)
        self.assertEqual([item.revision for item in artifacts], [1, 2])
        self.assertEqual(self.store.list_clarifications(workflow.id)[0].result_feature_contract_artifact_id, artifacts[1].id)

    def test_intake_emits_safe_progress_before_dispatch_and_preserves_result(self):
        observed = []
        clock = iter((10.0, 13.4))

        class ProgressRuntime(FakeRuntime):
            def execute_planning(runtime_self, request):
                runtime_self.requests.append(request)
                self.assertIsNotNone(request.progress_sink)
                execution = self.store.get_execution(request.execution_id)
                self.assertEqual(execution.lifecycle.value, "running")
                request.progress_sink(RuntimeProgressEvent("activity", Stage.INTAKE, 1.0, "Agent session started"))
                request.progress_sink(RuntimeProgressEvent("heartbeat", Stage.INTAKE, 10.0))
                return PlanningExecutionResult(runtime_self.provider, request.logical_session_id or "s", "thread", "turn",
                    TerminalState.SUCCEEDED, {"outcome": "READY", "feature": {"id": request.workflow_id,
                    "goal": "Goal", "requirements": ["Requirement"], "acceptance_criteria": ["Criterion"],
                    "constraints": [], "out_of_scope": [], "assumptions": [], "open_questions": []}})

        workflow = IntakeOrchestrator(self.store, ProgressRuntime(), monotonic_clock=lambda: next(clock)).run(
            self.root, "Implement the bounded request.", progress_sink=observed.append,
        )
        self.assertEqual(workflow.status, WorkflowStatus.READY)
        self.assertEqual([(event.kind, event.stage) for event in observed], [
            ("started", Stage.INTAKE), ("activity", Stage.INTAKE),
            ("heartbeat", Stage.INTAKE), ("completed", Stage.INTAKE),
        ])
        self.assertAlmostEqual(observed[-1].elapsed_seconds, 3.4)

    def test_interrupted_intake_preserves_unknown_operation_without_artifact(self):
        class InterruptingRuntime(FakeRuntime):
            def execute_planning(runtime_self, request):
                runtime_self.requests.append(request)
                raise KeyboardInterrupt

        observed = []
        with self.assertRaises(KeyboardInterrupt):
            IntakeOrchestrator(self.store, InterruptingRuntime()).run(
                self.root, "Interrupt this request.", progress_sink=observed.append,
            )
        workflow_id = self.store.get_selected_workflow_id()
        self.assertIsNotNone(workflow_id)
        workflow = self.store.get_workflow(workflow_id)
        self.assertEqual((workflow.stage, workflow.status),
                         (Stage.INTAKE, WorkflowStatus.HUMAN_ATTENTION))
        self.assertEqual(self.store.list_artifacts(workflow.id), [])
        self.assertEqual(self.store.reconcile_operations(workflow.id), [])
        execution = self.store.get_latest_execution(workflow.id)
        self.assertEqual(execution.lifecycle.value, "unknown")
        self.assertEqual([event.kind for event in observed], ["started", "interrupted"])
        self.store.close()
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        resumed = V2PlanOrchestrator(self.store, InterruptingRuntime()).resume(workflow.id)
        self.assertEqual((resumed.stage, resumed.status),
                         (Stage.INTAKE, WorkflowStatus.HUMAN_ATTENTION))


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


class TaskExecutionOrchestrationTests(unittest.TestCase):
    """Focused fake-runtime coverage for the persisted Wave 2 action loop."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    @staticmethod
    def developer(*, passed=True, command="python -m unittest", provider_session_id=None):
        return PlanningExecutionResult(
            provider="fake", logical_session_id="developer", provider_session_id=provider_session_id,
            provider_execution_id="developer-turn", terminal_state=TerminalState.SUCCEEDED,
            final_payload={"summary": "implemented", "changed_files": [],
                           "test_results": [{"command": command, "passed": passed, "summary": "ok"}]},
        )

    @staticmethod
    def reviewer(outcome="PASS"):
        findings = [] if outcome == "PASS" else [{
            "id": "F-1", "severity": "blocking", "description": "fix this",
        }]
        return PlanningExecutionResult(
            provider="fake", logical_session_id="reviewer", provider_session_id=None,
            provider_execution_id="reviewer-turn", terminal_state=TerminalState.SUCCEEDED,
            final_payload={"outcome": outcome, "summary": outcome, "findings": findings},
        )

    def _ready_workflow(self, task_count=2):
        class Runtime:
            provider = "fake"

            def __init__(self):
                self.requests = []
                self.results = []

            def verify_capabilities(self, repository, required_capabilities=()):
                return CapabilityReport(
                    provider="fake", executable="fake", repository_path=str(repository), available=True,
                    capabilities={name: True for name in required_capabilities},
                )

            def execute(self, request):
                self.requests.append(request)
                return self.results.pop(0)

        runtime = Runtime()
        workflow = self.store.create_workflow(self.root, provider="fake")
        tasks = [{
            "key": f"TASK-{index:03d}", "title": f"Task {index}", "instructions": "Make the approved change.",
            "acceptance_criteria": ["Observable result"], "required_tests": ["python -m unittest"],
        } for index in range(1, task_count + 1)]
        manifest = "```engineering-flow-task-plan\n" + json.dumps({"version": 1, "tasks": tasks}) + "\n```\n"
        intent = self.store.create_generation_intent(workflow.id, Stage.TASK_PLAN, request_hash="approved-plan", revision=1)
        artifact_path = self.root / ".engineering-flow" / "workflows" / workflow.id / "artifacts" / "001-task-plan.md"
        artifact = self.store.complete_generation(
            intent.operation.idempotency_key, content=manifest, artifact_path=artifact_path,
            stage=Stage.TASK_PLAN, revision=1,
        )
        self.store.record_approval(workflow.id, artifact.id, ApprovalDecision.APPROVED, actor="human")
        self.store.set_workflow_state(workflow.id, stage=Stage.READY_FOR_WAVE_2, status=WorkflowStatus.COMPLETED)
        return PlanningOrchestrator(self.store, runtime), runtime, self.store.get_workflow(workflow.id)

    def test_imports_once_then_dispatches_tasks_in_order_after_independent_passes(self):
        orchestrator, runtime, workflow = self._ready_workflow()
        runtime.results = [self.developer(), self.reviewer(), self.developer(), self.reviewer()]

        for _ in range(4):
            workflow = orchestrator.resume(workflow.id)

        self.assertEqual((workflow.stage, workflow.status),
                         (Stage.TASKS_READY_FOR_WAVE_REVIEW, WorkflowStatus.COMPLETED))
        self.assertEqual([request.role for request in runtime.requests],
                         [Role.DEVELOPER, Role.REVIEWER, Role.DEVELOPER, Role.REVIEWER])
        self.assertEqual([request.work_kind for request in runtime.requests],
                         [WorkKind.DEVELOP, WorkKind.REVIEW, WorkKind.DEVELOP, WorkKind.REVIEW])
        self.assertNotEqual(runtime.requests[0].logical_session_id, runtime.requests[1].logical_session_id)
        self.assertEqual([task.status.value for task in self.store.list_tasks(workflow.id)], ["accepted", "accepted"])
        self.assertEqual(len(self.store.list_tasks(workflow.id)), 2)

    def test_invalid_required_test_evidence_pauses_before_reviewer_dispatch(self):
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
        runtime.results = [self.developer(passed=False)]

        workflow = orchestrator.resume(workflow.id)

        self.assertEqual(workflow.status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual([request.role for request in runtime.requests], [Role.DEVELOPER])
        task = self.store.list_tasks(workflow.id)[0]
        self.assertEqual(task.status.value, "human_attention")
        self.assertEqual(self.store.get_latest_execution(workflow.id).failure_classification, FailureClassification.TEST)

    def test_duplicate_or_mismatched_required_test_claims_pause_as_test_failures(self):
        for claims in (
            [
                {"command": "python -m unittest", "passed": True, "summary": "first"},
                {"command": "python -m unittest", "passed": True, "summary": "duplicate"},
            ],
            [{"command": "python -m unittest other", "passed": True, "summary": "mismatched"}],
        ):
            with self.subTest(claims=claims):
                orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
                runtime.results = [PlanningExecutionResult(
                    provider="fake", logical_session_id="developer", provider_session_id=None,
                    provider_execution_id="developer-turn", terminal_state=TerminalState.SUCCEEDED,
                    final_payload={"summary": "implemented", "changed_files": [], "test_results": claims},
                )]

                workflow = orchestrator.resume(workflow.id)

                self.assertEqual(workflow.status, WorkflowStatus.HUMAN_ATTENTION)
                self.assertEqual(self.store.get_latest_execution(workflow.id).failure_classification,
                                 FailureClassification.TEST)
                self.assertEqual([request.role for request in runtime.requests], [Role.DEVELOPER])

    def test_developer_instruction_requires_one_ordered_result_per_required_test(self):
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
        runtime.results = [self.developer()]

        orchestrator.resume(workflow.id)

        instruction = runtime.requests[0].instruction
        self.assertIn("exactly one entry for each Required tests command", instruction)
        self.assertIn("in that same order", instruction)
        self.assertIn("do not repeat a command", instruction)
        self.assertIn("do not include additional commands in test_results", instruction)

    def test_reviewer_instruction_excludes_task_order_and_predecessor_acceptance(self):
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
        runtime.results = [self.developer(), self.reviewer()]

        orchestrator.resume(workflow.id)
        orchestrator.resume(workflow.id)

        instruction = runtime.requests[1].instruction
        self.assertIn("orchestrator alone determines task order and predecessor acceptance", instruction)
        self.assertIn("do not report a finding about task scheduling", instruction)

    def test_malformed_reviewer_payload_pauses_without_accepting_the_task(self):
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
        runtime.results = [
            self.developer(),
            PlanningExecutionResult(
                provider="fake", logical_session_id="reviewer", provider_session_id=None,
                provider_execution_id="reviewer-turn", terminal_state=TerminalState.SUCCEEDED,
                final_payload={"outcome": "PASS", "summary": "invalid", "findings": [{
                    "id": "F-1", "severity": "blocking", "description": "contradiction",
                }]},
            ),
        ]

        orchestrator.resume(workflow.id)
        workflow = orchestrator.resume(workflow.id)

        self.assertEqual(workflow.status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store.list_tasks(workflow.id)[0].status.value, "human_attention")
        self.assertEqual(self.store.get_latest_execution(workflow.id).failure_classification,
                         FailureClassification.AGENT_EXECUTION)

    def test_fix_required_below_limit_remediates_then_uses_a_new_reviewer(self):
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
        runtime.results = [
            self.developer(provider_session_id="developer-provider-session"),
            self.reviewer("FIX_REQUIRED"),
            self.developer(),
            self.reviewer(),
        ]

        for _ in range(4):
            workflow = orchestrator.resume(workflow.id)

        self.assertEqual(workflow.status, WorkflowStatus.COMPLETED)
        self.assertEqual([request.work_kind for request in runtime.requests],
                         [WorkKind.DEVELOP, WorkKind.REVIEW, WorkKind.FIX, WorkKind.REVIEW])
        self.assertEqual(runtime.requests[2].continuity_bundle["review_findings"][0]["id"], "F-1")
        self.assertEqual(runtime.requests[2].resume_provider_session_id, "developer-provider-session")
        self.assertNotEqual(runtime.requests[1].logical_session_id, runtime.requests[3].logical_session_id)

    def test_intervention_requires_an_existing_task_human_attention_boundary(self):
        orchestrator, _, workflow = self._ready_workflow(task_count=1)
        self.store.import_task_plan(workflow.id)
        self.store.set_workflow_state(workflow.id, stage=Stage.TASK_EXECUTION, status=WorkflowStatus.RUNNING)
        task = self.store.list_tasks(workflow.id)[0]

        with self.assertRaises(ConflictFailure):
            self.store.record_intervention(workflow.id, task.id, actor="human", reason="premature")

        unchanged = self.store.get_task(task.id)
        self.assertEqual((unchanged.status.value, unchanged.current_review_window), ("pending", 1))

    def test_unknown_task_operation_is_not_replayed_after_resume(self):
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)

        def lost_process(request):
            runtime.requests.append(request)
            raise RuntimeError("provider process disappeared")

        runtime.execute = lost_process
        workflow = orchestrator.resume(workflow.id)
        self.assertEqual(workflow.status, WorkflowStatus.HUMAN_ATTENTION)
        resumed = orchestrator.resume(workflow.id)
        self.assertEqual(resumed.status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(len(runtime.requests), 1)
        operation = self.store._connection.execute(
            "SELECT status FROM operations WHERE workflow_id = ? AND task_id IS NOT NULL", (workflow.id,)
        ).fetchone()
        self.assertEqual(operation["status"], "unknown")

    def test_reopen_after_developer_artifact_commit_does_not_repeat_the_developer(self):
        class InterruptingStore(WorkflowStore):
            interrupt = True

            def complete_task_operation(self, *args, **kwargs):
                artifact = super().complete_task_operation(*args, **kwargs)
                if self.interrupt and kwargs.get("artifact_type") is TaskArtifactType.DEVELOPER_RESULT:
                    self.interrupt = False
                    raise RuntimeError("simulated interruption after developer artifact commit")
                return artifact

        database = self.root / ".engineering-flow" / "workflows.sqlite3"
        self.store.close()
        self.store = InterruptingStore(database)
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
        runtime.results = [self.developer(), self.reviewer()]

        with self.assertRaises(RuntimeError):
            orchestrator.resume(workflow.id)
        self.store.close()
        self.store = WorkflowStore(database)
        recovered = PlanningOrchestrator(self.store, runtime)

        recovered.resume(workflow.id)
        workflow = recovered.resume(workflow.id)
        self.assertEqual(workflow.status, WorkflowStatus.COMPLETED)
        self.assertEqual([request.role for request in runtime.requests], [Role.DEVELOPER, Role.REVIEWER])

    def test_reopen_after_review_commit_dispatches_remediation_without_a_duplicate_review(self):
        class InterruptingStore(WorkflowStore):
            interrupt = True

            def complete_task_cycle(self, *args, **kwargs):
                result = super().complete_task_cycle(*args, **kwargs)
                if self.interrupt and kwargs.get("outcome") == "FIX_REQUIRED":
                    self.interrupt = False
                    raise RuntimeError("simulated interruption after review commit")
                return result

        database = self.root / ".engineering-flow" / "workflows.sqlite3"
        self.store.close()
        self.store = InterruptingStore(database)
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
        runtime.results = [self.developer(), self.reviewer("FIX_REQUIRED"), self.developer()]

        orchestrator.resume(workflow.id)
        with self.assertRaises(RuntimeError):
            orchestrator.resume(workflow.id)
        self.store.close()
        self.store = WorkflowStore(database)
        recovered = PlanningOrchestrator(self.store, runtime)

        recovered.resume(workflow.id)
        self.assertEqual([request.role for request in runtime.requests],
                         [Role.DEVELOPER, Role.REVIEWER, Role.DEVELOPER])
        self.assertEqual(runtime.requests[-1].work_kind, WorkKind.FIX)

    def test_reopen_after_acceptance_commit_does_not_repeat_acceptance_or_dispatch(self):
        class InterruptingStore(WorkflowStore):
            interrupt = True

            def complete_task_cycle(self, *args, **kwargs):
                result = super().complete_task_cycle(*args, **kwargs)
                if self.interrupt and kwargs.get("accept"):
                    self.interrupt = False
                    raise RuntimeError("simulated interruption after acceptance commit")
                return result

        database = self.root / ".engineering-flow" / "workflows.sqlite3"
        self.store.close()
        self.store = InterruptingStore(database)
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
        runtime.results = [self.developer(), self.reviewer()]

        orchestrator.resume(workflow.id)
        with self.assertRaises(RuntimeError):
            orchestrator.resume(workflow.id)
        self.store.close()
        self.store = WorkflowStore(database)
        recovered = PlanningOrchestrator(self.store, runtime)

        workflow = recovered.resume(workflow.id)
        self.assertEqual((workflow.stage, workflow.status),
                         (Stage.TASKS_READY_FOR_WAVE_REVIEW, WorkflowStatus.COMPLETED))
        self.assertEqual(len(runtime.requests), 2)
        self.assertEqual(sum(event.type == "task.accepted" for event in self.store.list_events(workflow.id)), 1)

    def test_fix_uses_task_local_developer_continuity_and_intervention_opens_new_window(self):
        orchestrator, runtime, workflow = self._ready_workflow(task_count=1)
        orchestrator.max_review_cycles = 1
        runtime.results = [self.developer(provider_session_id="developer-provider-session"), self.reviewer("FIX_REQUIRED")]

        workflow = orchestrator.resume(workflow.id)
        workflow = orchestrator.resume(workflow.id)
        task = self.store.list_tasks(workflow.id)[0]
        self.assertEqual(workflow.status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store.list_task_cycles(task.id)[0].outcome, "FIX_REQUIRED")

        intervention = self.store.record_intervention(workflow.id, task.id, actor="human", reason="apply remediation")
        self.assertEqual(intervention.prior_review_window, 1)
        self.assertEqual(self.store.get_task(task.id).status.value, "pending")
        runtime.results = [self.developer(), self.reviewer()]
        workflow = orchestrator.resume(workflow.id)
        workflow = orchestrator.resume(workflow.id)

        self.assertEqual(workflow.status, WorkflowStatus.COMPLETED)
        self.assertEqual(runtime.requests[2].work_kind, WorkKind.FIX)
        self.assertEqual(runtime.requests[0].logical_session_id, runtime.requests[2].logical_session_id)
        self.assertEqual(runtime.requests[2].resume_provider_session_id, "developer-provider-session")
        self.assertEqual(runtime.requests[2].continuity_bundle["developer_result"]["summary"], "implemented")
        self.assertEqual(runtime.requests[2].continuity_bundle["test_evidence"]["test_results"][0]["passed"], True)
        self.assertEqual(runtime.requests[2].continuity_bundle["review_findings"][0]["id"], "F-1")
        self.assertNotEqual(runtime.requests[1].logical_session_id, runtime.requests[3].logical_session_id)
        self.assertEqual(self.store.get_task(task.id).current_review_window, 2)

class CanonicalLifecycleOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = WorkflowStore(Path(self.tempdir.name) / "workflows.sqlite3")
        self.workflow = self.store.create_workflow("/repo", provider="fake")
        self.scope = self.store.create_scope(self.workflow.id, "wave", "1")
        self.store.record_lifecycle_state(
            self.workflow.id, lifecycle_version=LifecycleVersion.CANONICAL_V1,
            stage=CanonicalStage.PRD, status=WorkflowStatus.CREATED,
            scope_id=self.scope.id, operation_key="initial", request_fingerprint=hashlib.sha256(b"initial").hexdigest(),
        )
        self.orchestrator = CanonicalLifecycleOrchestrator(self.store, runtime_name="codex")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def test_only_policy_selects_successor_and_records_result_atomically(self):
        state = self.orchestrator.advance(
            self.workflow.id, scope_id=self.scope.id, operation_key="prd-result",
            request_fingerprint=hashlib.sha256(b"prd-result").hexdigest(),
            normalized_result={"outcome": "success", "capability_id": "prd", "schema_version": "1"},
            evidence_reference="docs/prd.md", evidence_sha256=hashlib.sha256(b"prd").hexdigest(),
            supported_providers={"codex": "fake"},
        )
        self.assertEqual((state.stage, state.status), (CanonicalStage.DELIVERY_PLAN, WorkflowStatus.CREATED))
        self.assertEqual(self.store.get_capability_operation("prd-result").status.value, "completed")
        self.assertEqual(self.store.list_events(self.workflow.id)[-1].type, "canonical.transition.recorded")
        paused = self.orchestrator.advance(
            self.workflow.id, scope_id=self.scope.id, operation_key="delivery-result",
            request_fingerprint=hashlib.sha256(b"delivery-result").hexdigest(),
            normalized_result={"outcome": "success", "capability_id": "delivery-planning", "schema_version": "1", "architecture_required": True},
            evidence_reference="docs/plan.md", evidence_sha256=hashlib.sha256(b"plan").hexdigest(),
            supported_providers={"codex": "fake"},
        )
        self.assertEqual(paused.status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(self.store.get_capability_operation("delivery-result").attention_outcome,
                         HumanAttentionOutcome.MISSING_AUTHORITY)


class V2PlanTests(unittest.TestCase):
    def test_ready_contract_becomes_pending_plan_without_task_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_text("x = 1\n", encoding="utf-8")
            store = WorkflowStore(root / ".engineering-flow" / "workflows.sqlite3")
            class Runtime(FakeRuntime):
                def execute(self, request):
                    self.requests.append(request)
                    return PlanningExecutionResult(self.provider, request.logical_session_id or "s", "thread", "turn", TerminalState.SUCCEEDED, {"plan": {"id": f"{request.workflow_id}:plan:r1", "workflow_id": request.workflow_id, "revision": 1, "feature_contract": {"artifact_id": feature.id, "sha256": feature.sha256}, "strategy": "Change source.", "assumptions": [], "verification_strategy": ["unit tests"], "tasks": [{"id": "T1", "objective": "Change source.", "context": {"relevant_files": ["source.py"], "existing_patterns": []}, "requirements": ["Update behavior."], "acceptance_criteria": ["Works."], "verification": ["tests"], "constraints": [], "depends_on": [], "complexity": "low", "risk": "high"}]}})
            runtime = Runtime()
            intake = IntakeOrchestrator(store, runtime)
            # Persist a verified READY source without invoking the intake fake.
            workflow = store.create_workflow(root, provider="fake", configuration_snapshot={}, feature_content=b"request", feature_path=root / ".engineering-flow" / "workflows" / "input", lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
            intent = store.create_generation_intent(workflow.id, Stage.INTAKE, request_hash="source", provider="fake", role=Role.INTAKE, revision=1, artifact_path=root / ".engineering-flow" / "workflows" / workflow.id / "artifacts" / "001-feature-contract.json")
            payload = {"outcome": "READY", "feature": {"id": workflow.id, "goal": "Goal", "requirements": ["Requirement"], "acceptance_criteria": ["Criterion"], "constraints": [], "out_of_scope": [], "assumptions": [], "open_questions": []}}
            feature = store.complete_generation(intent.operation.idempotency_key, content=json.dumps(payload), artifact_path=root / ".engineering-flow" / "workflows" / workflow.id / "artifacts" / "001-feature-contract.json", stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE, workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED)
            result = V2PlanOrchestrator(store, runtime).resume(workflow.id)
            self.assertEqual((result.stage, result.status), (Stage.PLAN, WorkflowStatus.AWAITING_APPROVAL))
            self.assertEqual(store.list_artifacts(workflow.id, Stage.PLAN)[0].approval_state, ApprovalState.PENDING)
            self.assertEqual(store.list_tasks(workflow.id), [])
            self.assertEqual(runtime.requests[-1].role, Role.PLANNER)
            store.close()


class V2PlanApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "source.py").write_text("x = 1\n", encoding="utf-8")
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def pending_plan(self):
        workflow = self.store.create_workflow(
            self.root, provider="fake", configuration_snapshot={}, feature_content=b"request",
            feature_path=self.root / ".engineering-flow" / "workflows" / "input",
            lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE,
        )
        intent = self.store.create_generation_intent(
            workflow.id, Stage.INTAKE, request_hash=f"source-{workflow.id}", provider="fake",
            role=Role.INTAKE, revision=1,
            artifact_path=self.root / ".engineering-flow" / "workflows" / workflow.id / "artifacts" / "001-feature-contract.json",
        )
        feature_payload = {"outcome": "READY", "feature": {"id": workflow.id, "goal": "Goal",
            "requirements": ["Requirement"], "acceptance_criteria": ["Criterion"], "constraints": [],
            "out_of_scope": [], "assumptions": [], "open_questions": []}}
        feature = self.store.complete_generation(
            intent.operation.idempotency_key, content=json.dumps(feature_payload),
            artifact_path=self.root / ".engineering-flow" / "workflows" / workflow.id / "artifacts" / "001-feature-contract.json",
            stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE,
            workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED,
        )

        class Runtime(FakeRuntime):
            def execute(runtime_self, request):
                runtime_self.requests.append(request)
                return PlanningExecutionResult(runtime_self.provider, request.logical_session_id or "s", "thread", "turn",
                    TerminalState.SUCCEEDED, {"plan": {"id": f"{request.workflow_id}:plan:r1",
                    "workflow_id": request.workflow_id, "revision": 1,
                    "feature_contract": {"artifact_id": feature.id, "sha256": feature.sha256},
                    "strategy": "Change source.", "assumptions": [], "verification_strategy": ["unit tests"],
                    "tasks": [{"id": "T1", "objective": "Change source.",
                    "context": {"relevant_files": ["source.py"], "existing_patterns": []},
                    "requirements": ["Update behavior."], "acceptance_criteria": ["Works."],
                    "verification": ["tests"], "constraints": [], "depends_on": [], "complexity": "low", "risk": "high"}]}})

        runtime = Runtime()
        result = V2PlanOrchestrator(self.store, runtime).resume(workflow.id)
        return result, self.store.list_artifacts(workflow.id, Stage.PLAN)[0], feature, runtime

    def test_approve_persists_plan_stop_and_resume_does_not_dispatch(self):
        workflow, plan, _feature, runtime = self.pending_plan()
        event_count = len(self.store.list_events(workflow.id))
        approved = V2PlanOrchestrator(self.store, runtime).approve(workflow.id, plan.id)
        self.assertEqual((approved.stage, approved.status), (Stage.PLAN, WorkflowStatus.PLAN_APPROVED))
        self.assertEqual(self.store.get_artifact(plan.id).approval_state, ApprovalState.APPROVED)
        self.assertIsNotNone(self.store.get_approval_for_artifact(plan.id))
        self.assertTrue(any(event.type == "plan.approved" for event in self.store.list_events(workflow.id)))
        self.assertGreater(len(self.store.list_events(workflow.id)), event_count)
        self.store.close()
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        reopened = self.store.get_workflow(workflow.id)
        self.assertEqual((reopened.stage, reopened.status), (Stage.PLAN, WorkflowStatus.PLAN_APPROVED))
        resumed = V2PlanOrchestrator(self.store, runtime).resume(workflow.id)
        self.assertEqual((resumed.stage, resumed.status), (Stage.PLAN, WorkflowStatus.PLAN_APPROVED))
        self.assertEqual(len(runtime.requests), 1)
        self.assertEqual(self.store.list_tasks(workflow.id), [])
        self.assertEqual(self.store._connection.execute(
            "SELECT COUNT(*) FROM task_artifacts WHERE workflow_id = ?", (workflow.id,)
        ).fetchone()[0], 0)

    def test_current_pending_plan_resolution_reuses_strict_authority_checks(self):
        workflow, plan, _feature, runtime = self.pending_plan()
        orchestrator = V2PlanOrchestrator(self.store, runtime)
        self.assertEqual(orchestrator.resolve_current_pending_plan_artifact(workflow.id), plan.id)
        Path(plan.path).write_text("tampered", encoding="utf-8")
        with self.assertRaises(ArtifactCorruptionFailure):
            orchestrator.resolve_current_pending_plan_artifact(workflow.id)

    def test_approval_guards_fail_closed_for_wrong_duplicate_tampered_and_invalid_inputs(self):
        workflow, plan, feature, runtime = self.pending_plan()
        orchestrator = V2PlanOrchestrator(self.store, runtime)
        before_events = len(self.store.list_events(workflow.id))
        with self.assertRaises(ConflictFailure):
            orchestrator.approve(workflow.id, feature.id)
        self.assertEqual(self.store.get_artifact(plan.id).approval_state, ApprovalState.PENDING)
        self.assertEqual(len(self.store.list_events(workflow.id)), before_events)

        other_workflow, other_plan, _other_feature, _other_runtime = self.pending_plan()
        with self.assertRaises(ConflictFailure):
            orchestrator.approve(workflow.id, other_plan.id)
        self.assertEqual(self.store.get_artifact(plan.id).approval_state, ApprovalState.PENDING)

        Path(plan.path).write_text("tampered", encoding="utf-8")
        with self.assertRaises(ArtifactCorruptionFailure):
            orchestrator.approve(workflow.id, plan.id)
        self.assertEqual(self.store.get_artifact(plan.id).approval_state, ApprovalState.PENDING)
        self.assertIsNone(self.store.get_approval_for_artifact(plan.id))

        # Restore immutable bytes, then alter the valid JSON binding while
        # preserving its stored hash to prove approval re-parses the source.
        bad_plan = {"plan": {"id": f"{workflow.id}:plan:r1", "workflow_id": workflow.id, "revision": 1,
            "feature_contract": {"artifact_id": feature.id, "sha256": "0" * 64}, "strategy": "Change source.",
            "assumptions": [], "verification_strategy": ["unit tests"], "tasks": [{"id": "T1", "objective": "Change source.",
            "context": {"relevant_files": ["source.py"], "existing_patterns": []}, "requirements": ["Update behavior."],
            "acceptance_criteria": ["Works."], "verification": ["tests"], "constraints": [], "depends_on": [],
            "complexity": "low", "risk": "high"}]}}
        content = json.dumps(bad_plan)
        Path(plan.path).write_text(content, encoding="utf-8")
        self.store._connection.execute("UPDATE artifacts SET sha256 = ? WHERE id = ?", (hashlib.sha256(content.encode()).hexdigest(), plan.id))
        with self.assertRaises(ValidationFailure):
            orchestrator.approve(workflow.id, plan.id)
        self.assertEqual(self.store.get_artifact(plan.id).approval_state, ApprovalState.PENDING)
        self.assertIsNone(self.store.get_approval_for_artifact(plan.id))

        # The Step-2 slice has only revision 1; a mismatched projection is a
        # representable non-current decision and must also leave it pending.
        self.store._connection.execute("UPDATE workflows SET current_artifact_revision = 2 WHERE id = ?", (workflow.id,))
        with self.assertRaises(ConflictFailure):
            orchestrator.approve(workflow.id, plan.id)
        self.assertEqual(self.store.get_artifact(plan.id).approval_state, ApprovalState.PENDING)

    def test_duplicate_approval_fails_without_mutation(self):
        workflow, plan, _feature, runtime = self.pending_plan()
        orchestrator = V2PlanOrchestrator(self.store, runtime)
        orchestrator.approve(workflow.id, plan.id)
        event_count = len(self.store.list_events(workflow.id))
        with self.assertRaises(ConflictFailure):
            orchestrator.approve(workflow.id, plan.id)
        self.assertEqual(len(self.store.list_events(workflow.id)), event_count)
        self.assertEqual(self.store.get_artifact(plan.id).approval_state, ApprovalState.APPROVED)

    def test_reject_persists_stop_survives_reopen_and_blocks_future_decisions(self):
        workflow, plan, _feature, runtime = self.pending_plan()
        orchestrator = V2PlanOrchestrator(self.store, runtime)
        executions_before = len(runtime.requests)
        rejected = orchestrator.reject(workflow.id, plan.id, reason="Revise task boundaries.")

        self.assertEqual((rejected.stage, rejected.status), (Stage.PLAN, WorkflowStatus.REJECTED))
        self.assertEqual(self.store.get_artifact(plan.id).approval_state, ApprovalState.REJECTED)
        approval = self.store.get_approval_for_artifact(plan.id)
        self.assertEqual((approval.decision, approval.reason), (ApprovalDecision.REJECTED, "Revise task boundaries."))
        self.assertTrue(any(event.type == "plan.rejected" for event in self.store.list_events(workflow.id)))
        self.assertEqual(len(self.store.list_artifacts(workflow.id, Stage.PLAN)), 1)

        self.store.close()
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        reopened = self.store.get_workflow(workflow.id)
        self.assertEqual((reopened.stage, reopened.status), (Stage.PLAN, WorkflowStatus.REJECTED))
        self.assertEqual(V2PlanOrchestrator(self.store, runtime).resume(workflow.id).status, WorkflowStatus.REJECTED)
        self.assertEqual(len(runtime.requests), executions_before)
        self.assertEqual(len(self.store.list_artifacts(workflow.id, Stage.PLAN)), 1)

        before = self._decision_snapshot(workflow.id, plan.id)
        with self.assertRaises(ConflictFailure):
            V2PlanOrchestrator(self.store, runtime).reject(workflow.id, plan.id, reason="again")
        self.assertEqual(self._decision_snapshot(workflow.id, plan.id), before)
        with self.assertRaises(ConflictFailure):
            V2PlanOrchestrator(self.store, runtime).approve(workflow.id, plan.id)
        self.assertEqual(self._decision_snapshot(workflow.id, plan.id), before)

    def test_rejection_guards_fail_closed_for_wrong_stale_and_tampered_inputs(self):
        workflow, plan, feature, runtime = self.pending_plan()
        orchestrator = V2PlanOrchestrator(self.store, runtime)
        for artifact_id in (feature.id, self.pending_plan()[1].id):
            before = self._decision_snapshot(workflow.id, plan.id)
            with self.assertRaises(ConflictFailure):
                orchestrator.reject(workflow.id, artifact_id, reason="no")
            self.assertEqual(self._decision_snapshot(workflow.id, plan.id), before)

        Path(plan.path).write_text("tampered", encoding="utf-8")
        before = self._decision_snapshot(workflow.id, plan.id)
        with self.assertRaises(ArtifactCorruptionFailure):
            orchestrator.reject(workflow.id, plan.id, reason="no")
        self.assertEqual(self._decision_snapshot(workflow.id, plan.id), before)

        original = json.dumps({"plan": {"id": f"{workflow.id}:plan:r1", "workflow_id": workflow.id,
            "revision": 1, "feature_contract": {"artifact_id": feature.id, "sha256": feature.sha256},
            "strategy": "Change source.", "assumptions": [], "verification_strategy": ["unit tests"],
            "tasks": [{"id": "T1", "objective": "Change source.",
            "context": {"relevant_files": ["source.py"], "existing_patterns": []},
            "requirements": ["Update behavior."], "acceptance_criteria": ["Works."],
            "verification": ["tests"], "constraints": [], "depends_on": [], "complexity": "low", "risk": "high"}]}})
        Path(plan.path).write_text(original, encoding="utf-8")
        self.store._connection.execute("UPDATE artifacts SET sha256 = ? WHERE id = ?", (hashlib.sha256(original.encode()).hexdigest(), plan.id))
        self.store._connection.execute("UPDATE workflows SET current_artifact_revision = 2 WHERE id = ?", (workflow.id,))
        before = self._decision_snapshot(workflow.id, plan.id)
        with self.assertRaises(ConflictFailure):
            orchestrator.reject(workflow.id, plan.id, reason="no")
        self.assertEqual(self._decision_snapshot(workflow.id, plan.id), before)

    def _decision_snapshot(self, workflow_id, artifact_id):
        workflow = self.store.get_workflow(workflow_id)
        artifact = self.store.get_artifact(artifact_id)
        return (workflow.stage, workflow.status, workflow.current_artifact_revision,
                artifact.approval_state, self.store.get_approval_for_artifact(artifact_id),
                len(self.store.list_events(workflow_id)),
                self.store._connection.execute("SELECT COUNT(*) FROM operations WHERE workflow_id = ?", (workflow_id,)).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
