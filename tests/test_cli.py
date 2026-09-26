import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.cli import main  # noqa: E402
from engineering_flow.domain import ApprovalDecision, ApprovalState, LifecycleVersion, Role, Stage, WorkflowStatus  # noqa: E402
from engineering_flow.runtime import CapabilityReport, PlanningExecutionResult, RuntimeProgressEvent, TerminalState  # noqa: E402
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

    def ready_v2_workflow(self):
        (self.repository / "source.py").write_text("x = 1\n", encoding="utf-8")
        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        workflow = store.create_workflow(self.repository, provider="fake", configuration_snapshot={}, feature_content=b"request",
            feature_path=self.repository / ".engineering-flow" / "workflows" / "input", lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
        intent = store.create_generation_intent(workflow.id, Stage.INTAKE, request_hash="source", provider="fake", role=Role.INTAKE, revision=1,
            artifact_path=self.repository / ".engineering-flow" / "workflows" / workflow.id / "artifacts" / "001-feature-contract.json")
        feature = {"outcome": "READY", "feature": {"id": workflow.id, "goal": "Goal", "requirements": ["Requirement"],
            "acceptance_criteria": ["Criterion"], "constraints": [], "out_of_scope": [], "assumptions": [], "open_questions": []}}
        store.complete_generation(intent.operation.idempotency_key, content=json.dumps(feature),
            artifact_path=self.repository / ".engineering-flow" / "workflows" / workflow.id / "artifacts" / "001-feature-contract.json",
            stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE, workflow_status=WorkflowStatus.READY,
            approval_state=ApprovalState.NOT_REQUIRED)
        store.close()
        return workflow.id

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

    def test_run_input_modes_are_mutually_exclusive_and_required(self):
        for argv in (
            ["run", "--repo", str(self.repository), "--request", "inline", "--feature-file", str(self.feature)],
            ["run", "--repo", str(self.repository)],
        ):
            self.assertEqual(main(argv), 2)

    def test_explicit_repo_and_feature_file_keep_the_v1_prd_route(self):
        with patch("engineering_flow.cli.CodexCliRuntime", FakeRuntime):
            code, text = self.invoke([
                "run", "--repo", str(self.repository), "--feature-file", str(self.feature),
            ])
        self.assertEqual(code, 0)
        workflow_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("workflow:"))
        status_code, status = self.invoke([
            "status", "--repo", str(self.repository), "--workflow", workflow_id, "--json",
        ])
        self.assertEqual(status_code, 0)
        self.assertEqual((status["repository_path"], status["lifecycle_version"], status["stage"]),
                         (str(self.repository.resolve()), "historical", "prd"))
        self.assertNotIn("intake", status)

    def test_inline_request_persists_ready_intake_and_status_reopens_it(self):
        class IntakeRuntime(FakeRuntime):
            def execute_planning(self, request):
                self.requests.append(request)
                return PlanningExecutionResult(
                    "codex-cli", request.logical_session_id or "session", "thread", request.execution_id,
                    TerminalState.SUCCEEDED, {"outcome": "READY", "feature": {
                        "id": request.workflow_id, "goal": "Allow cancellation before shipment.",
                        "requirements": ["Only PENDING orders may be cancelled."],
                        "acceptance_criteria": ["A PENDING order can be cancelled."],
                        "constraints": ["SHIPPED orders cannot be cancelled."], "out_of_scope": [],
                        "assumptions": [], "open_questions": [],
                    }},
                )
        request = "Allow users to cancel an order before shipment. Only PENDING orders may be cancelled. SHIPPED orders cannot be cancelled."
        with patch("engineering_flow.cli.CodexCliRuntime", IntakeRuntime):
            code, text = self.invoke(["run", "--repo", str(self.repository), "--request", request])
        self.assertEqual(code, 0)
        self.assertIn("Intake: READY", text)
        workflow_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("workflow:"))
        code, status = self.invoke(["status", "--repo", str(self.repository), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual((status["lifecycle_version"], status["stage"], status["status"]), ("v2", "intake", "ready"))
        self.assertEqual(status["intake"]["outcome"], "READY")
        self.assertEqual(status["intake"]["open_questions"], [])
        self.assertEqual(len(status["artifacts"]), 1)
        self.assertEqual(status["artifacts"][0]["approval_state"], "not_required")
        self.assertEqual(status["tasks"], [])
        self.assertEqual([artifact["stage"] for artifact in status["artifacts"]], ["intake"])
        code, logs = self.invoke(["logs", "--repo", str(self.repository), "--workflow", workflow_id, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(logs["lifecycle_version"], "v2")
        self.assertEqual(logs["intake"]["outcome"], "READY")
        self.assertTrue(any(event["type"] == "intake.completed" for event in logs["events"]))

    def test_resume_progress_uses_tty_stderr_and_json_and_non_tty_is_bounded(self):
        class PlanRuntime(FakeRuntime):
            def verify_planning_capabilities(self, repository):
                return CapabilityReport("fake", "fake", str(repository), True, {"read_only": True}, True)
            def execute(self, request):
                self.requests.append(request)
                match = re.search(r"artifact UUID ([^,]+), sha256 ([^)]+)", request.instruction)
                artifact_id, sha256 = match.groups()
                if request.progress_sink:
                    request.progress_sink(RuntimeProgressEvent("heartbeat", Stage.PLAN, 10.0))
                return PlanningExecutionResult("fake", request.logical_session_id or "session", "thread", "turn", TerminalState.SUCCEEDED,
                    {"plan": {"id": f"{request.workflow_id}:plan:r1", "workflow_id": request.workflow_id, "revision": 1,
                    "feature_contract": {"artifact_id": artifact_id, "sha256": sha256}, "strategy": "Change source.", "assumptions": [],
                    "verification_strategy": ["tests"], "tasks": [{"id": "T1", "objective": "Change source.",
                    "context": {"relevant_files": ["source.py"], "existing_patterns": []}, "requirements": ["Update behavior."],
                    "acceptance_criteria": ["Works."], "verification": ["tests"], "constraints": [], "depends_on": [],
                    "complexity": "low", "risk": "high"}]}})
        class Tty(io.StringIO):
            def isatty(self): return True
        workflow_id = self.ready_v2_workflow()
        stdout, stderr = io.StringIO(), Tty()
        with patch("engineering_flow.cli.CodexCliRuntime", PlanRuntime), contextlib.redirect_stdout(stdout), patch("engineering_flow.cli.sys.stderr", stderr):
            self.assertEqual(main(["resume", "--repo", str(self.repository)]), 0, stdout.getvalue())
        self.assertNotIn("Codex running", stderr.getvalue())
        self.assertIn("✓ PLAN completed", stderr.getvalue())
        self.assertNotIn("Codex running", stdout.getvalue())
        self.assertIn("AWAITING_APPROVAL", stdout.getvalue())
        self.assertIn("T1", stdout.getvalue())
        self.assertIn("low complexity", stdout.getvalue())
        self.assertIn(f".engineering-flow/workflows/{workflow_id}/artifacts/002-plan.md", stdout.getvalue().replace("\n", ""))
        self.assertNotIn("source.py", stdout.getvalue())
        self.assertNotIn("Update behavior.", stdout.getvalue())

        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        plan_artifact = store.list_artifacts(workflow_id, Stage.PLAN)[0]
        store.close()
        code, verbose = self.invoke([
            "status", "--repo", str(self.repository), "--workflow", workflow_id,
            "--verbose", "--no-color",
        ])
        self.assertEqual(code, 0)
        self.assertIn(workflow_id, verbose)
        self.assertIn(plan_artifact.id, verbose)
        self.assertIn(plan_artifact.sha256, verbose)
        self.assertIn("Change source.", verbose)
        self.assertIn("source.py", verbose)
        self.assertIn("Update behavior.", verbose)
        self.assertNotRegex(verbose, r"\x1b\[")

        # A reopened V2 workflow does not execute again; both machine modes remain noise-free.
        json_out, json_err = io.StringIO(), Tty()
        with patch("engineering_flow.cli.CodexCliRuntime", PlanRuntime), contextlib.redirect_stdout(json_out), patch("engineering_flow.cli.sys.stderr", json_err):
            self.assertEqual(main(["resume", "--repo", str(self.repository), "--workflow", workflow_id, "--json"]), 0)
        self.assertEqual(json_err.getvalue(), "")
        self.assertNotIn("Codex running", json_out.getvalue())
        self.assertEqual(json.loads(json_out.getvalue())["stage"], "plan")

        workflow_id = self.ready_v2_workflow()
        non_tty_out, non_tty_err = io.StringIO(), io.StringIO()
        with patch("engineering_flow.cli.CodexCliRuntime", PlanRuntime), contextlib.redirect_stdout(non_tty_out), patch("engineering_flow.cli.sys.stderr", non_tty_err):
            self.assertEqual(main(["resume", "--repo", str(self.repository), "--workflow", workflow_id]), 0)
        self.assertIn("PLAN started", non_tty_err.getvalue())
        self.assertIn("PLAN completed duration=", non_tty_err.getvalue())
        self.assertNotIn("Codex running", non_tty_err.getvalue())
        self.assertNotIn("Codex running", non_tty_out.getvalue())

    def test_v2_approve_reports_durable_stop_without_execution(self):
        class PlanRuntime(FakeRuntime):
            def verify_planning_capabilities(self, repository):
                return CapabilityReport("fake", "fake", str(repository), True, {"read_only": True}, True)

            def execute(self, request):
                self.requests.append(request)
                artifact_id, sha256 = re.search(r"artifact UUID ([^,]+), sha256 ([^)]+)", request.instruction).groups()
                return PlanningExecutionResult("fake", request.logical_session_id or "session", "thread", "turn",
                    TerminalState.SUCCEEDED, {"plan": {"id": f"{request.workflow_id}:plan:r1",
                    "workflow_id": request.workflow_id, "revision": 1,
                    "feature_contract": {"artifact_id": artifact_id, "sha256": sha256}, "strategy": "Change source.",
                    "assumptions": [], "verification_strategy": ["tests"], "tasks": [{"id": "T1", "objective": "Change source.",
                    "context": {"relevant_files": ["source.py"], "existing_patterns": []}, "requirements": ["Update behavior."],
                    "acceptance_criteria": ["Works."], "verification": ["tests"], "constraints": [], "depends_on": [],
                    "complexity": "low", "risk": "high"}]}})

        workflow_id = self.ready_v2_workflow()
        with patch("engineering_flow.cli.CodexCliRuntime", PlanRuntime):
            self.assertEqual(main(["resume", "--repo", str(self.repository), "--workflow", workflow_id]), 0)
        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        plan = store.list_artifacts(workflow_id, Stage.PLAN)[0]
        executions_before = len(store._connection.execute(
            "SELECT id FROM executions WHERE workflow_id = ?", (workflow_id,)
        ).fetchall())
        store.close()
        code, output = self.invoke(["approve", "--repo", str(self.repository)])
        self.assertEqual(code, 0)
        self.assertIn("Plan approved.\nNo implementation has started.", output)
        code, status = self.invoke(["status", "--repo", str(self.repository), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual((status["stage"], status["status"], status["plan"]["approval_state"]),
                         ("plan", "plan_approved", "approved"))
        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        self.assertEqual(len(store._connection.execute(
            "SELECT id FROM executions WHERE workflow_id = ?", (workflow_id,)
        ).fetchall()), executions_before)
        self.assertEqual(store.list_tasks(workflow_id), [])
        store.close()

    def test_v2_reject_routes_to_plan_gate_and_reports_persisted_reason(self):
        class PlanRuntime(FakeRuntime):
            def verify_planning_capabilities(self, repository):
                return CapabilityReport("fake", "fake", str(repository), True, {"read_only": True}, True)

            def execute(self, request):
                self.requests.append(request)
                artifact_id, sha256 = re.search(r"artifact UUID ([^,]+), sha256 ([^)]+)", request.instruction).groups()
                return PlanningExecutionResult("fake", request.logical_session_id or "session", "thread", "turn", TerminalState.SUCCEEDED,
                    {"plan": {"id": f"{request.workflow_id}:plan:r1", "workflow_id": request.workflow_id, "revision": 1,
                    "feature_contract": {"artifact_id": artifact_id, "sha256": sha256}, "strategy": "Change source.", "assumptions": [], "verification_strategy": ["tests"], "tasks": [{"id": "T1", "objective": "Change source.", "context": {"relevant_files": ["source.py"], "existing_patterns": []}, "requirements": ["Update behavior."], "acceptance_criteria": ["Works."], "verification": ["tests"], "constraints": [], "depends_on": [], "complexity": "low", "risk": "high"}]}})

        workflow_id = self.ready_v2_workflow()
        with patch("engineering_flow.cli.CodexCliRuntime", PlanRuntime):
            self.assertEqual(main(["resume", "--repo", str(self.repository), "--workflow", workflow_id]), 0)
        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        plan = store.list_artifacts(workflow_id, Stage.PLAN)[0]
        store.close()
        code, output = self.invoke(["reject", "--repo", str(self.repository), "--reason", "Revise boundaries."])
        self.assertEqual(code, 0)
        self.assertIn("Plan rejected.\nRejection reason recorded.", output)
        code, status = self.invoke(["status", "--repo", str(self.repository), "--workflow", workflow_id, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual((status["stage"], status["status"], status["plan"]["approval_state"], status["plan"]["decision_reason"]),
                         ("plan", "rejected", "rejected", "Revise boundaries."))
        code, failed = self.invoke(["approve", "--repo", str(self.repository), "--workflow", workflow_id, "--artifact", plan.id])
        self.assertEqual(code, 4)
        self.assertIn("error: conflict:", failed)

    def test_v2_feature_contract_tampering_is_detected_after_reopen(self):
        class IntakeRuntime(FakeRuntime):
            def execute_planning(self, request):
                return PlanningExecutionResult(
                    "codex-cli", request.logical_session_id or "session", "thread", request.execution_id,
                    TerminalState.SUCCEEDED, {"outcome": "READY", "feature": {
                        "id": request.workflow_id, "goal": "Cancel pending orders.",
                        "requirements": ["Only PENDING orders may be cancelled."],
                        "acceptance_criteria": ["A pending order can be cancelled."],
                        "constraints": [], "out_of_scope": [], "assumptions": [], "open_questions": [],
                    }},
                )

        with patch("engineering_flow.cli.CodexCliRuntime", IntakeRuntime):
            _, text = self.invoke(["run", "--repo", str(self.repository), "--request", "Cancel pending orders."])
        workflow_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("workflow:"))
        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        artifact = store.list_artifacts(workflow_id, Stage.INTAKE)[0]
        Path(artifact.path).write_text("tampered", encoding="utf-8")
        store.close()
        code, result = self.invoke(["status", "--repo", str(self.repository), "--workflow", workflow_id, "--json"])
        self.assertEqual((code, result["error_code"]), (7, "persistence"))

    def test_status_projection_uses_persisted_lifecycle_version(self):
        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        workflow = store.create_workflow(self.repository)
        store._connection.execute("UPDATE workflows SET lifecycle_version = ? WHERE id = ?", ("v2", workflow.id))
        store.close()

        code, status = self.invoke(["status", "--repo", str(self.repository), "--workflow", workflow.id, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(status["lifecycle_version"], "v2")
        self.assertIn("intake", status)

    def test_inline_request_displays_and_reopens_needs_clarification(self):
        class ClarifyingRuntime(FakeRuntime):
            def execute_planning(self, request):
                self.requests.append(request)
                return PlanningExecutionResult(
                    "codex-cli", request.logical_session_id or "session", "thread", request.execution_id,
                    TerminalState.SUCCEEDED, {"outcome": "NEEDS_CLARIFICATION", "feature": {
                        "id": request.workflow_id, "goal": "Allow users to cancel orders.",
                        "requirements": [], "acceptance_criteria": [], "constraints": [], "out_of_scope": [],
                        "assumptions": [],
                        "open_questions": ["Which order states allow cancellation?"],
                    }},
                )

        with patch("engineering_flow.cli.CodexCliRuntime", ClarifyingRuntime):
            code, text = self.invoke(["run", "--repo", str(self.repository), "--request", "Allow users to cancel orders."])
        self.assertEqual(code, 0)
        self.assertIn("Intake: NEEDS_CLARIFICATION", text)
        self.assertIn("Open questions:\n- Which order states allow cancellation?", text)
        workflow_id = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("workflow:"))
        code, status = self.invoke(["status", "--repo", str(self.repository), "--workflow", workflow_id, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual((status["lifecycle_version"], status["stage"], status["status"]),
                         ("v2", "intake", "needs_clarification"))
        self.assertEqual(status["intake"]["open_questions"], ["Which order states allow cancellation?"])
        self.assertEqual(status["tasks"], [])
        self.assertEqual([artifact["stage"] for artifact in status["artifacts"]], ["intake"])

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
        ):
            code, result = self.invoke(argv)
            self.assertEqual(code, 2)
            self.assertEqual(result["command_result"], "error")
            self.assertEqual(result["error_code"], "usage")
            self.assertIn("workflow_id", result)
            self.assertIn("status", result)
            self.assertIn("stage", result)

        code, result = self.invoke(["status", "--repo", str(self.repository), "--json"])
        self.assertEqual((code, result["error_code"]), (3, "not_found"))
        self.assertIn("No workflow is selected", result["message"])

    def test_explicit_v2_status_replaces_selected_workflow_context(self):
        first = self.ready_v2_workflow()
        self.ready_v2_workflow()
        self.assertEqual(self.invoke(["status", "--repo", str(self.repository), "--workflow", first, "--json"])[1]["workflow_id"], first)
        code, selected = self.invoke(["status", "--repo", str(self.repository), "--json"])
        self.assertEqual((code, selected["workflow_id"]), (0, first))
        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        store._connection.execute("UPDATE repository_state SET value = ? WHERE key = 'selected_workflow_id'", ("not-a-uuid",))
        store.close()
        code, result = self.invoke(["status", "--repo", str(self.repository), "--json"])
        self.assertEqual((code, result["error_code"]), (7, "persistence"))
        self.assertIn("selected workflow context", result["message"])

    def test_invalid_explicit_workflow_does_not_replace_selection(self):
        selected = self.ready_v2_workflow()
        code, result = self.invoke([
            "status", "--repo", str(self.repository),
            "--workflow", "00000000-0000-0000-0000-000000000000", "--json",
        ])
        self.assertEqual((code, result["error_code"]), (3, "not_found"))
        code, result = self.invoke(["status", "--repo", str(self.repository), "--json"])
        self.assertEqual((code, result["workflow_id"]), (0, selected))

    def test_run_approve_and_reject_json_are_single_documents_with_empty_stderr(self):
        class IntakeRuntime(FakeRuntime):
            def execute_planning(self, request):
                return PlanningExecutionResult(
                    "codex-cli", request.logical_session_id or "session", "thread", request.execution_id,
                    TerminalState.SUCCEEDED, {"outcome": "READY", "feature": {
                        "id": request.workflow_id, "goal": "Change the CLI safely.",
                        "requirements": ["Preserve compatibility."],
                        "acceptance_criteria": ["The CLI remains compatible."],
                        "constraints": [], "out_of_scope": [], "assumptions": [], "open_questions": [],
                    }},
                )

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("engineering_flow.cli.CodexCliRuntime", IntakeRuntime), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(main([
                "run", "--repo", str(self.repository), "--request", "Change the CLI safely.", "--json",
            ]), 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        run_document = json.loads(stdout.getvalue())
        self.assertEqual((run_document["command"], run_document["stage"], run_document["status"]),
                         ("run", "intake", "ready"))
        self.assertNotRegex(stdout.getvalue(), r"\x1b\[")

        class PlanRuntime(FakeRuntime):
            def verify_planning_capabilities(self, repository):
                return CapabilityReport("fake", "fake", str(repository), True, {"read_only": True}, True)

            def execute(self, request):
                artifact_id, sha256 = re.search(
                    r"artifact UUID ([^,]+), sha256 ([^)]+)", request.instruction,
                ).groups()
                return PlanningExecutionResult(
                    "fake", request.logical_session_id or "session", "thread", "turn",
                    TerminalState.SUCCEEDED, {"plan": {
                        "id": f"{request.workflow_id}:plan:r1", "workflow_id": request.workflow_id,
                        "revision": 1, "feature_contract": {"artifact_id": artifact_id, "sha256": sha256},
                        "strategy": "Change source.", "assumptions": [],
                        "verification_strategy": ["tests"], "tasks": [{
                            "id": "T1", "objective": "Change source.",
                            "context": {"relevant_files": ["source.py"], "existing_patterns": []},
                            "requirements": ["Update behavior."], "acceptance_criteria": ["Works."],
                            "verification": ["tests"], "constraints": [], "depends_on": [],
                            "complexity": "low", "risk": "low",
                        }],
                    }},
                )

        def waiting_plan():
            workflow_id = self.ready_v2_workflow()
            out, err = io.StringIO(), io.StringIO()
            with patch("engineering_flow.cli.CodexCliRuntime", PlanRuntime), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main([
                    "resume", "--repo", str(self.repository), "--workflow", workflow_id, "--json",
                ]), 0)
            self.assertEqual(err.getvalue(), "")
            store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
            artifact_id = store.list_artifacts(workflow_id, Stage.PLAN)[0].id
            store.close()
            return workflow_id, artifact_id

        for decision in ("approve", "reject"):
            with self.subTest(decision=decision):
                workflow_id, artifact_id = waiting_plan()
                argv = [
                    decision, "--repo", str(self.repository), "--workflow", workflow_id,
                    "--artifact", artifact_id,
                ]
                if decision == "reject":
                    argv.extend(["--reason", "Revise it."])
                argv.append("--json")
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(main(argv), 0)
                self.assertEqual(err.getvalue(), "")
                self.assertEqual(len(out.getvalue().splitlines()), 1)
                document = json.loads(out.getvalue())
                self.assertEqual(document["command"], decision)
                self.assertEqual(document["status"], "plan_approved" if decision == "approve" else "rejected")
                self.assertEqual(document["plan"]["approval"]["decision"],
                                 "approved" if decision == "approve" else "rejected")
                self.assertNotRegex(out.getvalue(), r"\x1b\[")

    def test_verbose_and_json_conflict_as_one_json_usage_error(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main([
                "status", "--repo", str(self.repository), "--workflow", "workflow-id",
                "--verbose", "--json",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        document = json.loads(stdout.getvalue())
        self.assertEqual((document["command_result"], document["error_code"]), ("error", "usage"))

    def test_task_status_logs_and_intervention_are_persisted_projections(self):
        store = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        workflow = store.create_workflow(self.repository, configuration_snapshot={
            "execution": {"max_review_cycles": 3},
        })
        manifest = (
            "```engineering-flow-task-plan\n"
            + json.dumps({"version": 1, "tasks": [{
                "key": "TASK-001", "title": "Projected task", "instructions": "Implement it.",
                "acceptance_criteria": ["It is visible"], "required_tests": ["python -m unittest"],
            }]})
            + "\n```\n"
        )
        intent = store.create_generation_intent(workflow.id, Stage.TASK_PLAN, request_hash="plan", revision=1)
        artifact = store.complete_generation(
            intent.operation.idempotency_key, content=manifest,
            artifact_path=self.repository / ".engineering-flow" / "workflows" / workflow.id / "artifacts" / "001-task-plan.md",
            stage=Stage.TASK_PLAN, revision=1,
        )
        store.record_approval(workflow.id, artifact.id, ApprovalDecision.APPROVED, actor="human")
        store.set_workflow_state(
            workflow.id, stage=Stage.READY_FOR_WAVE_2, status=WorkflowStatus.COMPLETED,
        )
        task = store.import_task_plan(workflow.id)[0]
        store.set_workflow_state(
            workflow.id, stage=Stage.TASK_EXECUTION, status=WorkflowStatus.RUNNING,
        )
        store.pause_task(task.id, classification="review", detail="operator action is required")
        store.close()

        code, status = self.invoke(["status", "--repo", str(self.repository), "--workflow", workflow.id, "--json"])
        self.assertEqual(code, 8)
        self.assertEqual(status["tasks"][0]["key"], "TASK-001")
        self.assertEqual(status["tasks"][0]["title"], "Projected task")
        self.assertTrue(status["tasks"][0]["intervention_required"])
        self.assertEqual(status["active_task"]["id"], task.id)

        code, logs = self.invoke(["logs", "--repo", str(self.repository), "--workflow", workflow.id, "--json"])
        self.assertEqual(code, 8)
        task_events = [event for event in logs["events"] if event["task_id"] == task.id]
        self.assertTrue(task_events)
        self.assertEqual([event["sequence"] for event in logs["events"]], sorted(event["sequence"] for event in logs["events"]))

        code, intervention = self.invoke([
            "intervene", "--repo", str(self.repository), "--workflow", workflow.id,
            "--task", task.id, "--reason", "Proceed with remediation", "--json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(intervention["status"], "running")
        reopened = WorkflowStore(self.repository / ".engineering-flow" / "workflows.sqlite3")
        self.assertEqual(len(reopened.list_interventions(task.id)), 1)
        self.assertEqual(reopened.get_task(task.id).status.value, "pending")
        reopened.close()


if __name__ == "__main__":
    unittest.main()
