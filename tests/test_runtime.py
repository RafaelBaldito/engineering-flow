import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.domain import Role, Stage  # noqa: E402
from engineering_flow.runtime import (  # noqa: E402
    AgentRuntime,
    CapabilityReport,
    NormalizedEvent,
    PlanningExecutionRequest,
    PlanningExecutionResult,
    TerminalState,
)


class RuntimeContractTests(unittest.TestCase):
    def test_contract_is_provider_neutral(self):
        request = PlanningExecutionRequest(
            workflow_id="workflow-1",
            execution_id="execution-1",
            logical_session_id="session-1",
            role=Role.PRD,
            stage=Stage.PRD,
            repository_path="repo",
            authoritative_input_paths=("feature.md",),
            authoritative_input_hashes=("hash",),
            instruction="Create the PRD.",
            output_schema_path="schema.json",
            final_output_path="result.json",
            timeout_seconds=10,
            required_capabilities=("json_events",),
        )
        result = PlanningExecutionResult(
            provider="test-provider",
            logical_session_id=request.logical_session_id,
            provider_session_id="provider-thread",
            provider_execution_id="provider-turn",
            terminal_state=TerminalState.SUCCEEDED,
            final_payload={
                "artifact_markdown": "# PRD",
                "summary": "done",
                "requires_human_approval": True,
                "approval_reason": "policy",
            },
        )
        self.assertIsInstance(request, PlanningExecutionRequest)
        self.assertEqual(result.content, "# PRD")
        self.assertTrue(result.success)
        self.assertIsInstance(CapabilityReport("p", "x", "repo", True), CapabilityReport)
        self.assertIsInstance(NormalizedEvent("turn.completed"), NormalizedEvent)
        self.assertTrue(hasattr(AgentRuntime, "execute_planning"))

    def test_request_rejects_unpaired_inputs_and_invalid_timeout(self):
        with self.assertRaises(ValueError):
            PlanningExecutionRequest(
                "w", "e", Role.PRD, Stage.PRD, "repo", ("a",), (),
                "instruction", "schema", "output", 1,
            )
        with self.assertRaises(ValueError):
            PlanningExecutionRequest(
                "w", "e", Role.PRD, Stage.PRD, "repo", (), (),
                "instruction", "schema", "output", 0,
            )


if __name__ == "__main__":
    unittest.main()
