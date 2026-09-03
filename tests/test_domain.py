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
    WorkflowStatus,
)


class DomainTests(unittest.TestCase):
    def test_domain_enums_are_provider_neutral_and_complete(self):
        self.assertEqual([stage.value for stage in Stage], [
            "prd", "techspec", "task_plan", "ready_for_wave_2",
            "task_execution", "tasks_ready_for_wave_review",
        ])
        self.assertEqual({item.value for item in WorkflowStatus}, {
            "created", "running", "awaiting_approval", "rejected", "failed",
            "cancelled", "human_attention", "completed",
        })
        self.assertEqual({item.value for item in ApprovalPolicy}, {"required", "automatic", "conditional"})
        self.assertEqual({item.value for item in ApprovalDecision}, {"approved", "rejected", "auto_approved"})
        self.assertEqual({item.value for item in FailureClassification}, {
            "workflow", "provider", "agent_execution", "authentication", "tool",
            "human_rejection", "persistence", "test", "review",
        })
        self.assertEqual({item.value for item in Role}, {
            "prd", "architect", "planner", "developer", "reviewer",
        })
        self.assertEqual({item.value for item in TaskStatus}, {
            "pending", "active", "implementing", "testing", "reviewing", "fixing",
            "accepted", "human_attention",
        })

    def test_domain_records_are_immutable(self):
        from engineering_flow.domain import Intervention, Workflow  # noqa: E402

        for record in (Workflow, TaskDefinition, TaskCycle, TaskArtifact, Intervention):
            self.assertTrue(dataclasses.is_dataclass(record))
            self.assertTrue(record.__dataclass_params__.frozen)


if __name__ == "__main__":
    unittest.main()
