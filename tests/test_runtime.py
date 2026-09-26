import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.domain import CanonicalStage, CapabilityId, LifecycleVersion, Role, Stage, WorkKind  # noqa: E402
from engineering_flow.runtime import (  # noqa: E402
    AgentRuntime,
    CANONICAL_CAPABILITIES,
    CapabilityRegistry,
    CapabilityResolutionStatus,
    CapabilityReport,
    NormalizedEvent,
    PlanningExecutionRequest,
    PlanningExecutionResult,
    TaskExecutionRequest,
    TerminalState,
)


class RuntimeContractTests(unittest.TestCase):
    def test_capability_registry_rejects_duplicate_definitions(self):
        with self.assertRaisesRegex(ValueError, "duplicate capability IDs"):
            CapabilityRegistry((CANONICAL_CAPABILITIES[0], CANONICAL_CAPABILITIES[0]))

    def test_capability_registry_resolves_only_one_compatible_binding(self):
        registry = CapabilityRegistry()
        result = registry.resolve(
            lifecycle_version=LifecycleVersion.CANONICAL_V1, stage=CanonicalStage.TASK_EXECUTION,
            capability_id=CapabilityId.TASK_EXECUTION, role=Role.DEVELOPER,
            runtime="codex-cli", provider="codex-cli", repository_constraints={},
            supported_providers={"codex-cli": "codex-cli"},
        )
        self.assertEqual(result.status, CapabilityResolutionStatus.RESOLVED)
        self.assertEqual(result.binding.capability.id, CapabilityId.TASK_EXECUTION)
        self.assertEqual(len(CANONICAL_CAPABILITIES), 13)
        self.assertFalse(hasattr(result.binding.capability, "skill"))
        mismatch = registry.resolve(
            lifecycle_version=LifecycleVersion.CANONICAL_V1, stage=CanonicalStage.TASK_EXECUTION,
            capability_id="task-execution", role=Role.REVIEWER,
            runtime="codex-cli", provider="other", repository_constraints={},
            supported_providers={"codex-cli": "codex-cli"},
        )
        self.assertEqual(mismatch.status, CapabilityResolutionStatus.INCOMPATIBLE)
        unsupported = registry.resolve(
            lifecycle_version=LifecycleVersion.CANONICAL_V1, stage=CanonicalStage.TASK_EXECUTION,
            capability_id="task-execution", role=Role.DEVELOPER,
            runtime="codex-cli", provider="other", repository_constraints={},
            supported_providers={"codex-cli": "codex-cli"},
        )
        self.assertEqual(unsupported.status, CapabilityResolutionStatus.UNSUPPORTED_PROVIDER)
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

    def test_task_roles_require_matching_work_kind_and_independent_reviewer(self):
        common = dict(
            workflow_id="workflow-1", execution_id="execution-1", stage=Stage.TASK_EXECUTION,
            repository_path="repo", authoritative_input_paths=(), authoritative_input_hashes=(),
            instruction="Implement the approved task.", output_schema_path="schema", final_output_path="result",
            timeout_seconds=10,
        )
        developer = TaskExecutionRequest(
            **common, role=Role.DEVELOPER, work_kind=WorkKind.DEVELOP,
            logical_session_id="developer-session", continuity_bundle={"task_contract": {"key": "TASK-1"}},
        )
        self.assertEqual(developer.work_kind, WorkKind.DEVELOP)
        with self.assertRaises(ValueError):
            TaskExecutionRequest(**common, role=Role.REVIEWER, work_kind=WorkKind.DEVELOP)
        with self.assertRaises(ValueError):
            TaskExecutionRequest(
                **common, role=Role.REVIEWER, work_kind=WorkKind.REVIEW,
                logical_session_id="reviewer-session",
            )
        with self.assertRaises(ValueError):
            TaskExecutionRequest(
                **common, role=Role.REVIEWER, work_kind=WorkKind.REVIEW,
                logical_session_id="developer-session", developer_logical_session_id="developer-session",
            )


if __name__ == "__main__":
    unittest.main()
