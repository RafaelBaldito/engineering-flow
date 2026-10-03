import dataclasses
import copy
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.domain import (  # noqa: E402
    ApprovalDecision,
    ApprovalPolicy,
    FailureClassification,
    Role,
    Stage,
    TaskArtifact,
    TaskCycle,
    TaskDefinition,
    TaskStatus,
    LifecycleVersion,
    CanonicalStage,
    ScopeKind,
    HumanAttentionOutcome,
    WorkflowStatus,
    GovernanceDecision,
    GovernanceDecisionType,
    FeatureContract,
    IntakeOutcome,
    Plan,
    ValidationFailure,
)


class DomainTests(unittest.TestCase):
    def test_domain_enums_are_provider_neutral_and_complete(self):
        self.assertEqual([stage.value for stage in Stage], [
            "intake", "plan", "prd", "techspec", "task_plan", "ready_for_wave_2",
            "task_execution", "tasks_ready_for_wave_review",
        ])
        self.assertEqual({item.value for item in WorkflowStatus}, {
            "created", "running", "awaiting_approval", "rejected", "failed",
            "cancelled", "human_attention", "completed", "ready", "needs_clarification", "plan_approved", "changes_requested", "implementing", "implementation_completed", "implementation_failed", "verifying", "verification_failed", "task_verified", "reviewing", "review_failed", "task_review_passed", "task_changes_requested", "fixing",
        })
        self.assertEqual({item.value for item in ApprovalPolicy}, {"required", "automatic", "conditional"})
        self.assertEqual({item.value for item in ApprovalDecision}, {"approved", "rejected", "auto_approved"})
        self.assertEqual({item.value for item in FailureClassification}, {
            "workflow", "provider", "agent_execution", "authentication", "tool",
            "human_rejection", "persistence", "test", "review",
        })
        self.assertEqual({item.value for item in Role}, {
            "intake", "prd", "architect", "planner", "developer", "reviewer",
        })
        self.assertEqual({item.value for item in TaskStatus}, {
            "pending", "active", "implementing", "testing", "reviewing", "fixing",
            "accepted", "human_attention",
        })
        self.assertEqual([item.value for item in LifecycleVersion], ["historical", "canonical-v1", "v2"])
        self.assertIn("delivery_plan", {item.value for item in CanonicalStage})
        self.assertEqual({item.value for item in ScopeKind}, {"workflow", "release", "wave", "task"})
        self.assertIn("ambiguous_migration", {item.value for item in HumanAttentionOutcome})
        self.assertEqual({item.value for item in GovernanceDecisionType}, {
            "approval", "rejection", "wave_acceptance", "release_acceptance",
            "wave_start_authorization", "delivery_authorization", "revocation", "supersession",
        })
        self.assertIn("authorized", {item.value for item in GovernanceDecision})

    def test_domain_records_are_immutable(self):
        from engineering_flow.domain import Intervention, Workflow  # noqa: E402

        for record in (Workflow, TaskDefinition, TaskCycle, TaskArtifact, Intervention):
            self.assertTrue(dataclasses.is_dataclass(record))
            self.assertTrue(record.__dataclass_params__.frozen)

    def test_needs_clarification_requires_non_empty_open_questions(self):
        payload = {
            "outcome": "NEEDS_CLARIFICATION",
            "feature": {
                "id": "workflow-1", "goal": "Allow users to cancel orders.",
                "requirements": [], "acceptance_criteria": [], "constraints": [],
                "out_of_scope": [], "assumptions": [],
                "open_questions": ["Which order states allow cancellation?"],
            },
        }
        contract = FeatureContract.parse(payload, workflow_id="workflow-1")
        self.assertEqual(contract.outcome, IntakeOutcome.NEEDS_CLARIFICATION)
        self.assertEqual(contract.open_questions, ("Which order states allow cancellation?",))

        payload["feature"]["open_questions"] = []
        with self.assertRaisesRegex(ValidationFailure, "requires open questions"):
            FeatureContract.parse(payload, workflow_id="workflow-1")

    def test_feature_contract_rejects_ready_questions_and_invalid_shapes(self):
        payload = {
            "outcome": "READY",
            "feature": {
                "id": "workflow-1", "goal": "A goal", "requirements": ["A requirement"],
                "acceptance_criteria": ["A criterion"], "constraints": [], "out_of_scope": [],
                "assumptions": [], "open_questions": ["A question"],
            },
        }
        with self.assertRaisesRegex(ValidationFailure, "no open questions"):
            FeatureContract.parse(payload, workflow_id="workflow-1")
        del payload["feature"]["constraints"]
        with self.assertRaisesRegex(ValidationFailure, "invalid shape"):
            FeatureContract.parse(payload, workflow_id="workflow-1")
        payload["unexpected"] = True
        with self.assertRaisesRegex(ValidationFailure, "only outcome and feature"):
            FeatureContract.parse(payload, workflow_id="workflow-1")

    def test_plan_parser_rejects_critical_contract_violations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("x = 1\n", encoding="utf-8")
            def payload():
                return {"plan": {"id": "workflow-1:plan:r1", "workflow_id": "workflow-1", "revision": 1,
                    "feature_contract": {"artifact_id": "artifact-1", "sha256": "hash-1"}, "strategy": "Plan it.",
                    "assumptions": [], "verification_strategy": ["unit tests"], "tasks": [{"id": "T1", "objective": "Change it.",
                    "context": {"relevant_files": ["source.py"], "existing_patterns": []}, "requirements": ["Requirement"],
                    "acceptance_criteria": ["Criterion"], "verification": ["tests"], "constraints": [],
                    "depends_on": [], "complexity": "low", "risk": "high"}]}}
            parse = lambda value: Plan.parse(value, workflow_id="workflow-1", revision=1,
                feature_contract_artifact_id="artifact-1", feature_contract_sha256="hash-1", repository_path=root)
            for mutate, message in (
                (lambda item: item["plan"]["feature_contract"].update(artifact_id="wrong"), "binding"),
                (lambda item: item["plan"]["tasks"][0].update(depends_on=["T2"]), "dependencies"),
                (lambda item: item["plan"]["tasks"][0]["context"].update(relevant_files=["../outside.py"]), "repository-relative"),
                (lambda item: item["plan"].update(assumptions=["same", "same"]), "duplicates"),
            ):
                value = payload()
                mutate(value)
                with self.assertRaisesRegex(ValidationFailure, message):
                    parse(value)

    def test_plan_parser_validates_complexity_and_risk_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("x = 1\n", encoding="utf-8")
            value = {"plan": {"id": "workflow-1:plan:r1", "workflow_id": "workflow-1", "revision": 1,
                "feature_contract": {"artifact_id": "artifact-1", "sha256": "hash-1"}, "strategy": "Plan it.",
                "assumptions": [], "verification_strategy": ["unit tests"], "tasks": [{"id": "T1", "objective": "Change it.",
                "context": {"relevant_files": ["source.py"], "existing_patterns": []}, "requirements": ["Requirement"],
                "acceptance_criteria": ["Criterion"], "verification": ["tests"], "constraints": [], "depends_on": [],
                "complexity": "low", "risk": "high"}]}}
            parsed = Plan.parse(value, workflow_id="workflow-1", revision=1, feature_contract_artifact_id="artifact-1",
                feature_contract_sha256="hash-1", repository_path=root)
            self.assertEqual((parsed.tasks[0].complexity, parsed.tasks[0].risk), ("low", "high"))
            value["plan"]["tasks"][0]["risk"] = "invalid"
            with self.assertRaisesRegex(ValidationFailure, "complexity and risk"):
                Plan.parse(value, workflow_id="workflow-1", revision=1, feature_contract_artifact_id="artifact-1",
                    feature_contract_sha256="hash-1", repository_path=root)

    def test_plan_parser_canonicalizes_model_local_task_keys_and_reparses_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("x = 1\n", encoding="utf-8")
            task = lambda key, dependencies: {"id": key, "objective": key,
                "context": {"relevant_files": ["source.py"], "existing_patterns": []},
                "requirements": ["Requirement"], "acceptance_criteria": ["Criterion"],
                "verification": ["tests"], "constraints": [], "depends_on": dependencies,
                "complexity": "low", "risk": "high"}
            payload = {"plan": {"id": "workflow-1:plan:r1", "workflow_id": "workflow-1", "revision": 1,
                "feature_contract": {"artifact_id": "artifact-1", "sha256": "hash-1"}, "strategy": "Plan it.",
                "assumptions": [], "verification_strategy": ["unit tests"],
                "tasks": [task("task-1", []), task("task-2", ["task-1"]),
                          task("arbitrary local key", ["task-2"])]}}
            parse = lambda value: Plan.parse(value, workflow_id="workflow-1", revision=1,
                feature_contract_artifact_id="artifact-1", feature_contract_sha256="hash-1", repository_path=root)
            parsed = parse(payload)
            self.assertEqual([item.id for item in parsed.tasks], ["T1", "T2", "T3"])
            self.assertEqual(parsed.tasks[1].depends_on, ("T1",))
            self.assertEqual(parsed.tasks[2].depends_on, ("T2",))
            canonical_payload = parsed.as_payload()
            self.assertEqual([item["id"] for item in canonical_payload["plan"]["tasks"]], ["T1", "T2", "T3"])
            self.assertEqual(canonical_payload["plan"]["tasks"][1]["depends_on"], ["T1"])
            self.assertEqual(parse(canonical_payload), parsed)

    def test_plan_parser_rejects_invalid_model_local_task_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("x = 1\n", encoding="utf-8")
            task = lambda key, dependencies: {"id": key, "objective": key,
                "context": {"relevant_files": ["source.py"], "existing_patterns": []},
                "requirements": ["Requirement"], "acceptance_criteria": ["Criterion"],
                "verification": ["tests"], "constraints": [], "depends_on": dependencies,
                "complexity": "low", "risk": "high"}
            payload = {"plan": {"id": "workflow-1:plan:r1", "workflow_id": "workflow-1", "revision": 1,
                "feature_contract": {"artifact_id": "artifact-1", "sha256": "hash-1"}, "strategy": "Plan it.",
                "assumptions": [], "verification_strategy": ["unit tests"],
                "tasks": [task("first", []), task("second", [])]}}
            parse = lambda value: Plan.parse(value, workflow_id="workflow-1", revision=1,
                feature_contract_artifact_id="artifact-1", feature_contract_sha256="hash-1", repository_path=root)
            for mutate, message in (
                (lambda value: value["plan"]["tasks"][1].update(id="first"), "local dependency keys"),
                (lambda value: value["plan"]["tasks"][1].update(id=""), "task.id"),
                (lambda value: value["plan"]["tasks"][1].update(depends_on=["missing"]), "dependencies"),
                (lambda value: value["plan"]["tasks"][1].update(depends_on=[1]), "depends_on"),
                (lambda value: value["plan"]["tasks"][1].update(depends_on=["second"]), "dependencies"),
                (lambda value: value["plan"]["tasks"][0].update(depends_on=["second"]), "dependencies"),
            ):
                value = copy.deepcopy(payload)
                mutate(value)
                with self.assertRaisesRegex(ValidationFailure, message):
                    parse(value)


if __name__ == "__main__":
    unittest.main()
