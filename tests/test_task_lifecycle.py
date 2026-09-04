"""Offline, cross-component acceptance evidence for the Wave 2 task loop."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.cli import _event_payload, _task_payload  # noqa: E402
from engineering_flow.domain import (  # noqa: E402
    ApprovalDecision,
    FailureClassification,
    Role,
    Stage,
    TaskArtifactType,
    WorkflowStatus,
    WorkKind,
)
from engineering_flow.orchestrator import PlanningOrchestrator  # noqa: E402
from engineering_flow.runtime import CapabilityReport, PlanningExecutionResult, TerminalState  # noqa: E402
from engineering_flow.store import WorkflowStore  # noqa: E402


class DeterministicRuntime:
    """A provider fake that records role-scoped requests without side effects."""

    provider = "deterministic-fake"

    def __init__(self) -> None:
        self.requests = []
        self.results = []

    def verify_capabilities(self, repository, required_capabilities=()):
        return CapabilityReport(
            provider=self.provider,
            executable="offline-fake",
            repository_path=str(repository),
            available=True,
            capabilities={capability: True for capability in required_capabilities},
        )

    def execute(self, request):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class TaskLifecycleIntegrationTests(unittest.TestCase):
    """Exercise the persisted lifecycle through its public orchestration boundary."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.repository = self.root / "disposable-repository"
        self.repository.mkdir()
        subprocess.run(["git", "init", str(self.repository)], check=True, capture_output=True)
        self.store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3",
                                   secret_values=("TOP-SECRET",))

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    @staticmethod
    def developer(*, passed=True, provider_session_id="developer-provider-session"):
        return PlanningExecutionResult(
            provider="deterministic-fake",
            logical_session_id="provider-developer",
            provider_session_id=provider_session_id,
            provider_execution_id="developer-turn",
            terminal_state=TerminalState.SUCCEEDED,
            final_payload={
                "summary": "implemented",
                "changed_files": [],
                "test_results": [{"command": "python -m unittest", "passed": passed, "summary": "offline"}],
            },
        )

    @staticmethod
    def reviewer(outcome="PASS"):
        findings = [] if outcome == "PASS" else [{
            "id": "F-1", "severity": "blocking", "description": "correct the bounded defect",
        }]
        return PlanningExecutionResult(
            provider="deterministic-fake",
            logical_session_id="provider-reviewer",
            provider_session_id=None,
            provider_execution_id="reviewer-turn",
            terminal_state=TerminalState.SUCCEEDED,
            final_payload={"outcome": outcome, "summary": outcome, "findings": findings},
        )

    @staticmethod
    def provider_failure():
        return PlanningExecutionResult(
            provider="deterministic-fake",
            logical_session_id="provider-developer",
            provider_session_id=None,
            provider_execution_id="failed-turn",
            terminal_state=TerminalState.FAILED,
            final_payload=None,
            failure_classification=FailureClassification.PROVIDER,
            failure_detail="offline provider failure",
        )

    def ready_workflow(self, *, task_count=2, max_review_cycles=3, manifest=None):
        workflow = self.store.create_workflow(
            self.repository,
            provider="deterministic-fake",
            configuration_snapshot={"execution": {"max_review_cycles": max_review_cycles}},
        )
        if manifest is None:
            tasks = [{
                "key": f"TASK-{number:03d}",
                "title": f"Disposable task {number}",
                "instructions": "Make only the approved disposable change.",
                "acceptance_criteria": ["The result is observable."],
                "required_tests": ["python -m unittest"],
            } for number in range(1, task_count + 1)]
            manifest = "```engineering-flow-task-plan\n" + json.dumps({"version": 1, "tasks": tasks}) + "\n```\n"
        intent = self.store.create_generation_intent(
            workflow.id, Stage.TASK_PLAN, request_hash="approved-disposable-plan", revision=1,
        )
        artifact = self.store.complete_generation(
            intent.operation.idempotency_key,
            content=manifest,
            artifact_path=(self.repository / ".engineering-flow" / "workflows" / workflow.id
                           / "artifacts" / "001-task-plan.md"),
            stage=Stage.TASK_PLAN,
            revision=1,
        )
        self.store.record_approval(workflow.id, artifact.id, ApprovalDecision.APPROVED, actor="human")
        workflow = self.store.set_workflow_state(
            workflow.id, stage=Stage.READY_FOR_WAVE_2, status=WorkflowStatus.COMPLETED,
        )
        runtime = DeterministicRuntime()
        return PlanningOrchestrator(self.store, runtime), runtime, workflow

    def reopen(self):
        database = self.repository / ".engineering-flow" / "workflows.sqlite3"
        self.store.close()
        self.store = WorkflowStore(database, secret_values=("TOP-SECRET",))

    def test_two_tasks_complete_in_manifest_order_without_delivery_side_effects(self):
        orchestrator, runtime, workflow = self.ready_workflow(task_count=2)
        runtime.results = [self.developer(), self.reviewer(), self.developer(), self.reviewer()]

        for _ in range(4):
            workflow = orchestrator.resume(workflow.id)

        self.assertEqual((workflow.stage, workflow.status),
                         (Stage.TASKS_READY_FOR_WAVE_REVIEW, WorkflowStatus.COMPLETED))
        self.assertEqual([request.work_kind for request in runtime.requests],
                         [WorkKind.DEVELOP, WorkKind.REVIEW, WorkKind.DEVELOP, WorkKind.REVIEW])
        self.assertEqual([task.key for task in self.store.list_tasks(workflow.id)], ["TASK-001", "TASK-002"])
        self.assertTrue(all(task.status.value == "accepted" for task in self.store.list_tasks(workflow.id)))
        self.assertNotEqual(runtime.requests[0].logical_session_id, runtime.requests[1].logical_session_id)
        self.assertNotEqual(runtime.requests[2].logical_session_id, runtime.requests[3].logical_session_id)
        self.assertNotEqual(runtime.requests[1].logical_session_id, runtime.requests[3].logical_session_id)
        self.assertNotEqual(runtime.requests[1].developer_logical_session_id, runtime.requests[1].logical_session_id)
        self.assertNotEqual(runtime.requests[3].developer_logical_session_id, runtime.requests[3].logical_session_id)
        self.assertNotEqual(subprocess.run(["git", "-C", str(self.repository), "rev-parse", "--verify", "HEAD"],
                                            capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(["git", "-C", str(self.repository), "remote"],
                                        check=True, capture_output=True, text=True).stdout, "")

    def test_invalid_import_payload_test_and_provider_failures_pause_before_unauthorized_work(self):
        invalid_manifests = {
            "legacy": "# Old task plan\n- TASK-001\n",
            "malformed": "```engineering-flow-task-plan\n{not JSON}\n```\n",
            "escaping": "```engineering-flow-task-plan\n" + json.dumps({"version": 1, "tasks": [{
                "key": "TASK-001", "title": "Escapes", "instructions": "No.",
                "acceptance_criteria": ["No escape"], "required_tests": ["python -m unittest"],
                "context_paths": ["../outside.md"],
            }]}) + "\n```\n",
        }
        for label, manifest in invalid_manifests.items():
            with self.subTest(import_case=label):
                orchestrator, runtime, workflow = self.ready_workflow(task_count=1, manifest=manifest)
                paused = orchestrator.resume(workflow.id)
                self.assertEqual((paused.stage, paused.status),
                                 (Stage.READY_FOR_WAVE_2, WorkflowStatus.HUMAN_ATTENTION))
                self.assertEqual(runtime.requests, [])

        cases = {
            "invalid_developer_payload": PlanningExecutionResult(
                provider="deterministic-fake", logical_session_id="provider-developer", provider_session_id=None,
                provider_execution_id="bad-payload", terminal_state=TerminalState.SUCCEEDED,
                final_payload={"not": "the contract"},
            ),
            "failed_exact_test": self.developer(passed=False),
            "provider_failure": self.provider_failure(),
        }
        for label, result in cases.items():
            with self.subTest(runtime_case=label):
                orchestrator, runtime, workflow = self.ready_workflow(task_count=1)
                runtime.results = [result]
                paused = orchestrator.resume(workflow.id)
                self.assertEqual(paused.status, WorkflowStatus.HUMAN_ATTENTION)
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(len(self.store.list_task_cycles(self.store.list_tasks(workflow.id)[0].id)), 1)

    def test_remediation_limit_intervention_and_cli_projections_preserve_evidence(self):
        orchestrator, runtime, workflow = self.ready_workflow(task_count=1, max_review_cycles=1)
        runtime.results = [self.developer(), self.reviewer("FIX_REQUIRED")]
        orchestrator.resume(workflow.id)
        paused = orchestrator.resume(workflow.id)
        task = self.store.list_tasks(workflow.id)[0]
        initial_cycle = self.store.list_task_cycles(task.id)[0]
        initial_review = initial_cycle.review_artifact_id
        initial_review_content = self.store.read_task_artifact(initial_review)

        self.assertEqual(paused.status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(initial_cycle.outcome, "FIX_REQUIRED")
        self.assertIsNotNone(initial_review)
        projected = _task_payload(self.store, task)
        self.assertEqual(projected["latest_review"]["outcome"], "FIX_REQUIRED")
        self.assertTrue(projected["intervention_required"])
        self.store.append_event(workflow.id, "test.redaction", stage=Stage.TASK_EXECUTION,
                                payload={"task_id": task.id, "detail": "TOP-SECRET"})
        events = [_event_payload(event) for event in self.store.list_events(workflow.id)]
        self.assertEqual([event["sequence"] for event in events], sorted(event["sequence"] for event in events))
        self.assertTrue(all(event["task_id"] == task.id or event["task_id"] is None for event in events))
        self.assertNotIn("TOP-SECRET", json.dumps(events))

        intervention = self.store.record_intervention(
            workflow.id, task.id, actor="human", reason="perform bounded remediation",
        )
        self.assertEqual(intervention.prior_review_window, 1)
        self.assertEqual(self.store.get_task(task.id).current_review_window, 2)
        self.assertEqual(self.store.get_task(task.id).status.value, "pending")
        self.assertEqual(self.store.get_task_cycle(initial_cycle.id).review_artifact_id, initial_review)
        self.assertEqual(self.store.read_task_artifact(initial_review), initial_review_content)
        runtime.results = [self.developer(), self.reviewer()]
        workflow = orchestrator.resume(workflow.id)
        workflow = orchestrator.resume(workflow.id)
        self.assertEqual(workflow.status, WorkflowStatus.COMPLETED)
        self.assertEqual([request.work_kind for request in runtime.requests],
                         [WorkKind.DEVELOP, WorkKind.REVIEW, WorkKind.FIX, WorkKind.REVIEW])
        self.assertEqual(runtime.requests[2].continuity_bundle["review_findings"][0]["id"], "F-1")
        self.assertNotEqual(runtime.requests[1].logical_session_id, runtime.requests[3].logical_session_id)

    def test_reopen_at_pending_provider_boundary_does_not_replay_unknown_work(self):
        orchestrator, runtime, workflow = self.ready_workflow(task_count=1)
        runtime.results = [RuntimeError("simulated lost provider process")]
        paused = orchestrator.resume(workflow.id)
        self.assertEqual(paused.status, WorkflowStatus.HUMAN_ATTENTION)
        self.reopen()
        recovered = PlanningOrchestrator(self.store, runtime)
        self.assertEqual(recovered.resume(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(len(runtime.requests), 1)
        operation = self.store._connection.execute(
            "SELECT status FROM operations WHERE workflow_id = ? AND task_id IS NOT NULL", (workflow.id,)
        ).fetchone()
        self.assertEqual(operation["status"], "unknown")

    def test_reopen_after_artifact_review_and_acceptance_boundaries_never_duplicate_work(self):
        boundaries = ("artifact", "review", "acceptance")
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                self.store.close()
                database = self.repository / ".engineering-flow" / "workflows.sqlite3"

                class InterruptingStore(WorkflowStore):
                    interrupt = True

                    def complete_task_operation(instance, *args, **kwargs):
                        artifact = super().complete_task_operation(*args, **kwargs)
                        if (boundary == "artifact" and instance.interrupt
                                and kwargs.get("artifact_type") is TaskArtifactType.DEVELOPER_RESULT):
                            instance.interrupt = False
                            raise RuntimeError("interrupted after artifact persistence")
                        return artifact

                    def complete_task_cycle(instance, *args, **kwargs):
                        result = super().complete_task_cycle(*args, **kwargs)
                        should_interrupt = ((boundary == "review" and kwargs.get("outcome") == "FIX_REQUIRED")
                                            or (boundary == "acceptance" and kwargs.get("accept")))
                        if instance.interrupt and should_interrupt:
                            instance.interrupt = False
                            raise RuntimeError("interrupted after review or acceptance persistence")
                        return result

                self.store = InterruptingStore(database)
                orchestrator, runtime, workflow = self.ready_workflow(task_count=1)
                runtime.results = ([self.developer(), self.reviewer()] if boundary != "review"
                                   else [self.developer(), self.reviewer("FIX_REQUIRED"), self.developer()])
                if boundary == "artifact":
                    with self.assertRaises(RuntimeError):
                        orchestrator.resume(workflow.id)
                else:
                    orchestrator.resume(workflow.id)
                    with self.assertRaises(RuntimeError):
                        orchestrator.resume(workflow.id)
                self.reopen()
                recovered = PlanningOrchestrator(self.store, runtime)
                if boundary == "artifact":
                    recovered.resume(workflow.id)
                    finished = recovered.resume(workflow.id)
                    self.assertEqual([request.role for request in runtime.requests], [Role.DEVELOPER, Role.REVIEWER])
                elif boundary == "review":
                    recovered.resume(workflow.id)
                    finished = self.store.get_workflow(workflow.id)
                    self.assertEqual([request.work_kind for request in runtime.requests],
                                     [WorkKind.DEVELOP, WorkKind.REVIEW, WorkKind.FIX])
                else:
                    finished = recovered.resume(workflow.id)
                    self.assertEqual(len(runtime.requests), 2)
                    self.assertEqual(sum(event.type == "task.accepted" for event in self.store.list_events(workflow.id)), 1)
                self.assertNotEqual(finished.status, WorkflowStatus.HUMAN_ATTENTION)
                task = self.store.list_tasks(workflow.id)[0]
                artifacts = self.store.list_task_artifacts(task.id)
                counts = {kind: sum(item.artifact_type is kind for item in artifacts) for kind in TaskArtifactType}
                self.assertEqual(counts[TaskArtifactType.DEFINITION], 1)
                if boundary in {"artifact", "acceptance"}:
                    self.assertEqual(counts[TaskArtifactType.DEVELOPER_RESULT], 1)
                    self.assertEqual(counts[TaskArtifactType.TEST_RESULT], 1)
                    self.assertEqual(counts[TaskArtifactType.REVIEW_RESULT], 1)
                else:
                    self.assertEqual(counts[TaskArtifactType.DEVELOPER_RESULT], 2)
                    self.assertEqual(counts[TaskArtifactType.TEST_RESULT], 2)
                    self.assertEqual(counts[TaskArtifactType.REVIEW_RESULT], 1)


if __name__ == "__main__":
    unittest.main()
