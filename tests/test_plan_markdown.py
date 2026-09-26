import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.domain import (ApprovalState, ArtifactCorruptionFailure, LifecycleVersion,
                                     PersistenceFailure, Plan, Role, Stage, TaskContract,
                                     WorkflowStatus)  # noqa: E402
from engineering_flow.orchestrator import V2PlanOrchestrator  # noqa: E402
from engineering_flow.plan_markdown import render_plan_markdown  # noqa: E402
from engineering_flow.store import WorkflowStore  # noqa: E402


def sample_plan() -> Plan:
    return Plan(
        "workflow-1:plan:r1", "workflow-1", 1, "feature-1", "a" * 64,
        "Use the existing CLI boundary.", ("Unicode remains useful: café",),
        ("Run focused tests.", "Run the full suite."), (
            TaskContract(
                "T1", "Implement *safe* output\nwithout markup.",
                ("src/engineering_flow/cli.py",), ("Follow argparse conventions.",),
                ("Expose the command.",), ("The command works.",),
                ("Run CLI tests.",), (), (), "low", "medium",
            ),
            TaskContract(
                "T2", "Cover the projection.", ("tests/test_cli.py",), (),
                ("Add regression coverage.",), ("Tests pass.",), ("Run unit tests.",),
                (), ("T1",), "medium", "low",
            ),
        ),
    )


class PlanMarkdownTests(unittest.TestCase):
    def test_renderer_is_deterministic_utf8_lf_and_complete(self):
        plan = sample_plan()
        first = render_plan_markdown(plan)
        self.assertEqual(first, render_plan_markdown(plan))
        self.assertTrue(first.endswith("\n"))
        self.assertFalse(first.endswith("\n\n"))
        self.assertNotIn("\r", first)
        self.assertEqual(first.encode("utf-8").decode("utf-8"), first)
        for expected in (
            "# Plan", "canonical `002-plan.json`", "## Revision", "## Strategy",
            "Use the existing CLI boundary.", "## Assumptions", "café",
            "## Verification Strategy", "### T1", "### T2", "#### Dependencies",
            "#### Relevant Files", "#### Existing Patterns", "#### Requirements",
            "#### Acceptance Criteria", "#### Verification", "#### Constraints",
            "**Complexity:** low", "**Risk:** medium", "`T1`",
        ):
            self.assertIn(expected, first)
        self.assertLess(first.index("### T1"), first.index("### T2"))
        self.assertIn("None.", first)
        self.assertNotIn("workflow-1:plan:r1", first)

    def test_renderer_makes_model_text_inert_without_changing_plan(self):
        plan = sample_plan()
        rendered = render_plan_markdown(plan)
        self.assertIn(r"Implement \*safe\* output\nwithout markup.", rendered)
        self.assertEqual(plan.tasks[0].objective, "Implement *safe* output\nwithout markup.")

    def test_projection_repair_is_non_authoritative_and_json_inspection_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "engineering_flow").mkdir()
            (root / "src" / "engineering_flow" / "cli.py").write_text("", encoding="utf-8")
            (root / "tests" / "test_cli.py").write_text("", encoding="utf-8")
            store = WorkflowStore(root / ".engineering-flow" / "workflows.sqlite3")
            try:
                workflow = store.create_workflow(
                    root, provider="fake", configuration_snapshot={}, feature_content=b"request",
                    lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE,
                )
                feature_path = store.workspace_path / "workflows" / workflow.id / "artifacts" / "001-feature-contract.json"
                feature_intent = store.create_generation_intent(
                    workflow.id, Stage.INTAKE, request_hash="feature", role=Role.INTAKE,
                    revision=1, artifact_path=feature_path,
                )
                feature = {"outcome": "READY", "feature": {"id": workflow.id, "goal": "Goal",
                    "requirements": ["Requirement"], "acceptance_criteria": ["Criterion"],
                    "constraints": [], "out_of_scope": [], "assumptions": [], "open_questions": []}}
                feature_artifact = store.complete_generation(
                    feature_intent.operation.idempotency_key, content=json.dumps(feature), artifact_path=feature_path,
                    stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE,
                    workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED,
                )
                plan = sample_plan()
                plan = Plan(f"{workflow.id}:plan:r1", workflow.id, 1, feature_artifact.id,
                            feature_artifact.sha256, plan.strategy, plan.assumptions,
                            plan.verification_strategy, plan.tasks)
                plan_path = store.workspace_path / "workflows" / workflow.id / "artifacts" / "002-plan.json"
                plan_intent = store.create_generation_intent(
                    workflow.id, Stage.PLAN, request_hash="plan", role=Role.PLANNER,
                    revision=1, artifact_path=plan_path,
                )
                artifact = store.complete_generation(
                    plan_intent.operation.idempotency_key,
                    content=json.dumps(plan.as_payload(), ensure_ascii=False) + "\n", artifact_path=plan_path,
                    stage=Stage.PLAN, revision=1, workflow_stage=Stage.PLAN,
                    workflow_status=WorkflowStatus.AWAITING_APPROVAL, approval_state=ApprovalState.PENDING,
                )
                orchestrator = V2PlanOrchestrator(store, None)
                created = orchestrator.inspect_plan_projection(workflow.id, repair=True)
                markdown_path = store.plan_markdown_path(workflow.id)
                expected = render_plan_markdown(plan).encode("utf-8")
                self.assertEqual((created.state, markdown_path.read_bytes()), ("current", expected))
                self.assertEqual(len(store.list_artifacts(workflow.id)), 2)
                identity = (artifact.id, artifact.sha256, artifact.revision, artifact.approval_state)

                markdown_path.unlink()
                missing = orchestrator.inspect_plan_projection(workflow.id)
                self.assertEqual(missing.state, "missing")
                self.assertFalse(markdown_path.exists())
                self.assertEqual(orchestrator.inspect_plan_projection(workflow.id, repair=True).state, "current")
                markdown_path.write_text("MANUAL EDIT\n", encoding="utf-8")
                modified = orchestrator.inspect_plan_projection(workflow.id)
                self.assertEqual(modified.state, "modified")
                self.assertEqual(markdown_path.read_text(encoding="utf-8"), "MANUAL EDIT\n")
                self.assertEqual(orchestrator.inspect_plan_projection(workflow.id, repair=True).state, "current")
                self.assertEqual(markdown_path.read_bytes(), expected)
                current = store.get_artifact(artifact.id)
                self.assertEqual((current.id, current.sha256, current.revision, current.approval_state), identity)

                with patch.object(store, "write_plan_markdown", side_effect=PersistenceFailure("disk unavailable")):
                    markdown_path.write_text("MANUAL EDIT\n", encoding="utf-8")
                    failed = orchestrator.inspect_plan_projection(workflow.id, repair=True)
                self.assertEqual((failed.state, failed.error), ("modified", "disk unavailable"))
                self.assertEqual(store.get_artifact(artifact.id).sha256, artifact.sha256)

                plan_path.write_text("tampered", encoding="utf-8")
                with self.assertRaises(ArtifactCorruptionFailure):
                    orchestrator.inspect_plan_projection(workflow.id)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
