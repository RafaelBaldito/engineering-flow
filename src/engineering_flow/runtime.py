"""Provider-neutral contracts for bounded planning runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .domain import FailureClassification, Role, Stage


class TerminalState(str, Enum):
    """Normalized terminal states understood by orchestration."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    """Result of checking whether a runtime can perform read-only planning."""

    provider: str
    executable: str
    repository_path: str
    available: bool
    capabilities: Mapping[str, bool] = field(default_factory=dict)
    read_only_planning: bool = False
    failure_classification: FailureClassification | None = None
    failure_detail: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def supported(self) -> bool:
        return self.available

    @property
    def ok(self) -> bool:
        return self.available


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """Provider-independent evidence emitted during one runtime execution."""

    type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    provider_event_id: str | None = None
    timestamp: str | None = None

    @property
    def event_type(self) -> str:
        return self.type


@dataclass(frozen=True, slots=True)
class PlanningExecutionRequest:
    """Bounded request sent by orchestration to an agent runtime."""

    workflow_id: str
    execution_id: str
    role: Role
    stage: Stage
    repository_path: str
    authoritative_input_paths: tuple[str, ...]
    authoritative_input_hashes: tuple[str, ...]
    instruction: str
    output_schema_path: str
    final_output_path: str
    timeout_seconds: float
    required_capabilities: tuple[str, ...] = ()
    logical_session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.workflow_id or not self.execution_id:
            raise ValueError("workflow and execution IDs are required")
        if not self.instruction.strip():
            raise ValueError("planning instruction is required")
        if len(self.authoritative_input_paths) != len(self.authoritative_input_hashes):
            raise ValueError("authoritative input paths and hashes must have equal length")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    @property
    def repository(self) -> Path:
        return Path(self.repository_path)


@dataclass(frozen=True, slots=True)
class PlanningExecutionResult:
    """Normalized terminal result returned by a planning runtime."""

    provider: str
    logical_session_id: str
    provider_session_id: str | None
    provider_execution_id: str | None
    terminal_state: TerminalState
    final_payload: Mapping[str, Any] | None
    usage: Mapping[str, Any] = field(default_factory=dict)
    events: tuple[NormalizedEvent, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    failure_classification: FailureClassification | None = None
    failure_detail: str | None = None

    @property
    def success(self) -> bool:
        return self.terminal_state is TerminalState.SUCCEEDED

    @property
    def content(self) -> str | None:
        if self.final_payload is None:
            return None
        content = self.final_payload.get("artifact_markdown")
        return content if isinstance(content, str) else None

    @property
    def structured_final_payload(self) -> Mapping[str, Any] | None:
        return self.final_payload

    @property
    def provider_name(self) -> str:
        return self.provider


class AgentRuntime(Protocol):
    """Small provider-neutral runtime boundary used by the orchestrator."""

    provider: str

    def verify_planning_capabilities(self, repository: str | Path) -> CapabilityReport:
        ...

    def execute_planning(self, request: PlanningExecutionRequest) -> PlanningExecutionResult:
        ...


# This alias keeps the older concise names usable by callers that adopted the
# initial domain vocabulary before the richer runtime contract was introduced.
ExecutionRequest = PlanningExecutionRequest
ExecutionResult = PlanningExecutionResult


def normalize_required_capabilities(values: Sequence[str]) -> tuple[str, ...]:
    """Return stable, duplicate-free capability names for request metadata."""

    return tuple(dict.fromkeys(str(value) for value in values if str(value)))
