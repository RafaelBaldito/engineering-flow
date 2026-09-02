import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.domain import Stage, WorkflowStatus  # noqa: E402
from engineering_flow.orchestrator import PlanningOrchestrator  # noqa: E402
from engineering_flow.runtime import CapabilityReport, PlanningExecutionResult, TerminalState  # noqa: E402
from engineering_flow.store import WorkflowStore  # noqa: E402


class PlanningWorkflowIntegrationTests(unittest.TestCase):
    def test_full_approval_flow_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkflowStore(Path(directory) / ".engineering-flow" / "workflows.sqlite3")

            class Runtime:
                provider = "fake"

                def verify_planning_capabilities(self, repository):
                    return CapabilityReport(
                        "fake",
                        "fake",
                        str(repository),
                        True,
                        {"json_events": True, "output_schema": True},
                        True,
                    )

                def execute_planning(self, request):
                    return PlanningExecutionResult(
                        "fake", request.logical_session_id or "session", None, request.execution_id,
                        TerminalState.SUCCEEDED,
                        {"artifact_markdown": "artifact", "summary": "ok", "requires_human_approval": True, "approval_reason": "human"},
                    )

            orchestrator = PlanningOrchestrator(store, Runtime())
            workflow = orchestrator.run(directory, "request")
            for stage in (Stage.PRD, Stage.TECHSPEC, Stage.TASK_PLAN):
                artifact = store.list_artifacts(workflow.id, stage)[-1]
                workflow = orchestrator.approve(workflow.id, artifact.id)
                if stage is not Stage.TASK_PLAN:
                    workflow = orchestrator.resume(workflow.id)
            self.assertEqual(workflow.status, WorkflowStatus.COMPLETED)
            self.assertEqual(workflow.stage, Stage.READY_FOR_WAVE_2)
            self.assertEqual(len(store.list_artifacts(workflow.id)), 3)
            self.assertEqual(len(store.list_events(workflow.id)), len({e.sequence for e in store.list_events(workflow.id)}))
            store.close()


if __name__ == "__main__":
    unittest.main()
