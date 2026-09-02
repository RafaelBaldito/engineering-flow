import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.cli import main  # noqa: E402
from engineering_flow.domain import Stage  # noqa: E402
from engineering_flow.runtime import CapabilityReport, PlanningExecutionResult, TerminalState  # noqa: E402
from engineering_flow.store import WorkflowStore  # noqa: E402


class FakeRuntime:
    provider = "codex-cli"

    def __init__(self, *args, **kwargs):
        self.requests = []

    def verify_planning_capabilities(self, repository):
        return CapabilityReport(
            "codex-cli", "fake", str(repository), True,
            {"json_events": True, "output_schema": True}, True,
        )

    def execute_planning(self, request):
        self.requests.append(request)
        return PlanningExecutionResult(
            "codex-cli", request.logical_session_id or "session", "thread", request.execution_id,
            TerminalState.SUCCEEDED,
            {
                "artifact_markdown": f"# {request.stage.value}\n",
                "summary": "generated",
                "requires_human_approval": True,
                "approval_reason": "review required",
            },
        )


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = Path(self.tempdir.name) / "repo"
        self.repository.mkdir()
        subprocess.run(["git", "init", str(self.repository)], check=True, capture_output=True)
        main(["init", "--repo", str(self.repository)])
        self.feature = self.repository / "feature.md"
        self.feature.write_text("A controlled planning workflow.\n", encoding="utf-8")

    def tearDown(self):
        self.tempdir.cleanup()

    def invoke(self, argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue()) if "--json" in argv else output.getvalue()

    def test_run_status_and_logs_use_persisted_state(self):
        with patch("engineering_flow.cli.CodexCliRuntime", FakeRuntime):
            code, text = self.invoke(["run", "--repo", str(self.repository), "--feature-file", str(self.feature)])
            self.assertEqual(code, 0)
            workflow_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("workflow:"))
            code, status = self.invoke(["status", "--repo", str(self.repository), "--workflow", workflow_id, "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(status["status"], "awaiting_approval")
            self.assertEqual(status["stage"], "prd")
            self.assertEqual(len(status["artifacts"]), 1)
            code, logs = self.invoke(["logs", "--repo", str(self.repository), "--workflow", workflow_id, "--after", "1", "--json"])
            self.assertEqual(code, 0)
            self.assertTrue(all(event["sequence"] > 1 for event in logs["events"]))

    def test_cli_fake_runtime_reaches_wave_two_after_three_exact_approvals(self):
        with patch("engineering_flow.cli.CodexCliRuntime", FakeRuntime):
            _, text = self.invoke(["run", "--repo", str(self.repository), "--feature-file", str(self.feature)])
            workflow_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("workflow:"))
            for index, stage in enumerate((Stage.PRD, Stage.TECHSPEC, Stage.TASK_PLAN)):
                store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
                artifact = store.list_artifacts(workflow_id, stage)[-1]
                store.close()
                self.assertEqual(main([
                    "approve", "--repo", str(self.repository), "--workflow", workflow_id,
                    "--artifact", artifact.id,
                ]), 0)
                if index < 2:
                    self.assertEqual(main(["resume", "--repo", str(self.repository), "--workflow", workflow_id]), 0)
            store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
            workflow = store.get_workflow(workflow_id)
            self.assertEqual(workflow.status.value, "completed")
            self.assertEqual(workflow.stage.value, "ready_for_wave_2")
            self.assertEqual(len(store.list_artifacts(workflow_id)), 3)
            store.close()

    def test_approval_requires_exact_current_artifact(self):
        with patch("engineering_flow.cli.CodexCliRuntime", FakeRuntime):
            main(["run", "--repo", str(self.repository), "--feature-file", str(self.feature)])
            store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
            workflow = store.get_workflow(store._connection.execute("SELECT id FROM workflows").fetchone()[0])
            artifact = store.list_artifacts(workflow.id, Stage.PRD)[0]
            store.close()
            self.assertEqual(main(["approve", "--repo", str(self.repository), "--workflow", workflow.id, "--artifact", artifact.id]), 0)
            self.assertEqual(main(["approve", "--repo", str(self.repository), "--workflow", workflow.id, "--artifact", artifact.id]), 4)

    def test_status_reports_artifact_corruption_as_json_error(self):
        with patch("engineering_flow.cli.CodexCliRuntime", FakeRuntime):
            main(["run", "--repo", str(self.repository), "--feature-file", str(self.feature)])
        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        workflow_id = store._connection.execute("SELECT id FROM workflows").fetchone()[0]
        artifact = store.list_artifacts(workflow_id)[0]
        Path(artifact.path).write_text("tampered", encoding="utf-8")
        store.close()
        code, result = self.invoke(["status", "--repo", str(self.repository), "--workflow", workflow_id, "--json"])
        self.assertEqual(code, 7)
        self.assertEqual(result["error_code"], "persistence")

    def test_json_usage_errors_emit_one_stable_result_document(self):
        for argv in (
            ["logs", "--repo", str(self.repository), "--workflow", "id", "--after", "-1", "--json"],
            ["status", "--repo", str(self.repository), "--json"],
        ):
            code, result = self.invoke(argv)
            self.assertEqual(code, 2)
            self.assertEqual(result["command_result"], "error")
            self.assertEqual(result["error_code"], "usage")
            self.assertIn("workflow_id", result)
            self.assertIn("status", result)
            self.assertIn("stage", result)


if __name__ == "__main__":
    unittest.main()
