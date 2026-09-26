import dataclasses
import sys
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
    ValidationFailure,
)


class DomainTests(unittest.TestCase):
    def test_domain_enums_are_provider_neutral_and_complete(self):
        self.assertEqual([stage.value for stage in Stage], [
            "intake", "prd", "techspec", "task_plan", "ready_for_wave_2",
            "task_execution", "tasks_ready_for_wave_review",
        ])
        self.assertEqual({item.value for item in WorkflowStatus}, {
            "created", "running", "awaiting_approval", "rejected", "failed",
            "cancelled", "human_attention", "completed", "ready", "needs_clarification",
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


if __name__ == "__main__":
    unittest.main()
