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
    ConflictFailure,
    FailureClassification,
    PersistenceFailure,
    Role,
    Stage,
    TaskArtifactType,
    WorkKind,
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


if __name__ == "__main__":
    unittest.main()
