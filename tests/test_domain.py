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
    WorkflowStatus,
)


class DomainTests(unittest.TestCase):
    def test_wave_one_enums_are_provider_neutral_and_complete(self):
        self.assertEqual([stage.value for stage in Stage], ["prd", "techspec", "task_plan", "ready_for_wave_2"])
        self.assertEqual({item.value for item in WorkflowStatus}, {
            "created", "running", "awaiting_approval", "rejected", "failed",
            "cancelled", "human_attention", "completed",
        })
        self.assertEqual({item.value for item in ApprovalPolicy}, {"required", "automatic", "conditional"})
        self.assertEqual({item.value for item in ApprovalDecision}, {"approved", "rejected", "auto_approved"})
        self.assertEqual({item.value for item in FailureClassification}, {
            "workflow", "provider", "agent_execution", "authentication", "tool",
            "human_rejection", "persistence",
        })
        self.assertEqual({item.value for item in Role}, {"prd", "architect", "planner"})

    def test_domain_records_are_immutable(self):
        from engineering_flow.domain import Workflow  # noqa: E402

        self.assertTrue(dataclasses.is_dataclass(Workflow))
        self.assertTrue(Workflow.__dataclass_params__.frozen)


if __name__ == "__main__":
    unittest.main()
