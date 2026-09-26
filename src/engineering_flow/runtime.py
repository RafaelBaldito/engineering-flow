"""Provider-neutral contracts for bounded agent runtime execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .domain import (
    CanonicalStage,
    CapabilityId,
    DomainCapability,
    FailureClassification,
    HumanPolicyPlacement,
    LifecycleVersion,
    Role,
    Stage,
    WorkKind,
)


class TerminalState(str, Enum):
    """Normalized terminal states understood by orchestration."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"


class CapabilityResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    UNKNOWN_CAPABILITY = "unknown_capability"
    INCOMPATIBLE = "incompatible"
    UNSUPPORTED_PROVIDER = "unsupported_provider"


class ExecutionContract(str, Enum):
    """Whether a request uses the historical or canonical capability boundary."""

    LEGACY = "legacy"
    CANONICAL = "canonical"


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    """A resolved provider/runtime target, without a native mechanism."""

    capability: DomainCapability
    runtime: str
    provider: str


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    status: CapabilityResolutionStatus
    binding: CapabilityBinding | None = None
    detail: str | None = None


def _capability(
    id: CapabilityId, role: Role, stage: CanonicalStage,
    *, policy: HumanPolicyPlacement = HumanPolicyPlacement.AFTER
) -> DomainCapability:
    return DomainCapability(
        id, "1", (LifecycleVersion.CANONICAL_V1,), (stage,), role,
        ("authoritative_inputs",), ("structured_result",), ("provider_evidence",), policy,
    )


CANONICAL_CAPABILITIES: tuple[DomainCapability, ...] = (
    _capability(CapabilityId.PRD, Role.PRD, CanonicalStage.PRD),
    _capability(CapabilityId.DELIVERY_PLANNING, Role.PLANNER, CanonicalStage.DELIVERY_PLAN),
    _capability(CapabilityId.ARCHITECTURE_OVERVIEW, Role.ARCHITECT, CanonicalStage.ARCHITECTURE),
    _capability(CapabilityId.TECHSPEC, Role.ARCHITECT, CanonicalStage.TECHSPEC),
    _capability(CapabilityId.TASK_PLANNING, Role.PLANNER, CanonicalStage.TASK_PLAN),
    _capability(CapabilityId.TASK_EXECUTION, Role.DEVELOPER, CanonicalStage.TASK_EXECUTION),
    _capability(CapabilityId.TASK_REVIEW, Role.REVIEWER, CanonicalStage.TASK_EXECUTION),
    _capability(CapabilityId.TASK_FIX, Role.DEVELOPER, CanonicalStage.TASK_EXECUTION),
    _capability(CapabilityId.WAVE_REVIEW, Role.REVIEWER, CanonicalStage.WAVE_REVIEW),
    _capability(CapabilityId.WAVE_REMEDIATION, Role.DEVELOPER, CanonicalStage.WAVE_REVIEW),
    _capability(CapabilityId.FINAL_REVIEW, Role.REVIEWER, CanonicalStage.FINAL_REVIEW),
    _capability(CapabilityId.FINAL_REMEDIATION, Role.DEVELOPER, CanonicalStage.FINAL_REVIEW),
    _capability(CapabilityId.DELIVERY_PREPARATION, Role.PLANNER, CanonicalStage.DELIVERY_PREPARATION, policy=HumanPolicyPlacement.BEFORE),
)


class CapabilityRegistry:
    """Deterministic registry with no fallback or provider routing."""

    def __init__(self, capabilities: Sequence[DomainCapability] = CANONICAL_CAPABILITIES):
        identifiers = [capability.id.value for capability in capabilities]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("capability registry contains duplicate capability IDs")
        self._capabilities = {capability.id.value: capability for capability in capabilities}

    def resolve(
        self, *, lifecycle_version: LifecycleVersion, stage: CanonicalStage,
        capability_id: str | CapabilityId, role: Role, runtime: str, provider: str,
        repository_constraints: Mapping[str, Any], supported_providers: Mapping[str, str],
        schema_version: str = "1",
    ) -> CapabilityResolution:
        del repository_constraints  # Constraint policy is owned by the later orchestrator.
        capability = self._capabilities.get(str(capability_id))
        if capability is None:
            return CapabilityResolution(CapabilityResolutionStatus.UNKNOWN_CAPABILITY, detail="unknown capability")
        if (lifecycle_version not in capability.supported_lifecycle_versions or stage not in capability.supported_stages
                or schema_version != capability.schema_version or role is not capability.role):
            return CapabilityResolution(CapabilityResolutionStatus.INCOMPATIBLE, detail="capability contract is incompatible")
        if supported_providers.get(runtime) != provider:
            return CapabilityResolution(CapabilityResolutionStatus.UNSUPPORTED_PROVIDER, detail="configured provider is unsupported")
        return CapabilityResolution(CapabilityResolutionStatus.RESOLVED, CapabilityBinding(capability, runtime, provider))


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    """Sanitized result of a provider capability preflight."""

    provider: str
    executable: str
    repository_path: str
    available: bool
    capabilities: Mapping[str, bool] = field(default_factory=dict)
    # Kept for Wave 1 callers. New code should require ``read_only`` instead.
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


_DEVELOPER_CONTINUITY_KEYS = frozenset({
    "task_contract", "developer_result", "test_evidence", "review_findings",
})


@dataclass(frozen=True, slots=True)
class RuntimeExecutionRequest:
    """A bounded, provider-neutral request for planning or task work.

    ``work_kind`` is absent for the Wave 1 planning roles. It is mandatory for
    task Developer and Reviewer work, which lets a provider reject a
    role/work-kind mismatch before invoking a subprocess.
    """

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
    work_kind: WorkKind | None = None
    required_test_commands: tuple[str, ...] = ()
    continuity_bundle: Mapping[str, Any] = field(default_factory=dict)
    resume_provider_session_id: str | None = None
    developer_logical_session_id: str | None = None
    capability_id: str | None = None
    capability_schema_version: str | None = None
    runtime_name: str | None = None
    provider_name: str | None = None
    execution_contract: ExecutionContract = ExecutionContract.LEGACY

    def __post_init__(self) -> None:
        if not self.workflow_id or not self.execution_id:
            raise ValueError("workflow and execution IDs are required")
        if not self.instruction.strip():
            raise ValueError("runtime instruction is required")
        if len(self.authoritative_input_paths) != len(self.authoritative_input_hashes):
            raise ValueError("authoritative input paths and hashes must have equal length")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.work_kind in (WorkKind.DEVELOP, WorkKind.FIX) and self.role is not Role.DEVELOPER:
            raise ValueError("Developer work requires the Developer role")
        if self.work_kind is WorkKind.REVIEW and self.role is not Role.REVIEWER:
            raise ValueError("review work requires the Reviewer role")
        if self.role in (Role.DEVELOPER, Role.REVIEWER) and self.work_kind is None:
            raise ValueError("Developer and Reviewer requests require a work kind")
        if self.role is Role.REVIEWER:
            if self.resume_provider_session_id:
                raise ValueError("Reviewer requests cannot resume a Developer provider session")
            if not self.developer_logical_session_id:
                raise ValueError("Reviewer requests require the Developer logical session")
            if self.developer_logical_session_id == self.logical_session_id:
                raise ValueError("Reviewer logical session must be distinct from Developer session")
        unknown = set(self.continuity_bundle) - _DEVELOPER_CONTINUITY_KEYS
        if unknown:
            raise ValueError("continuity bundle has unsupported fields")
        if self.role is not Role.DEVELOPER and self.continuity_bundle:
            raise ValueError("only Developer requests may carry continuity")
        capability_fields = (self.capability_id, self.capability_schema_version, self.runtime_name, self.provider_name)
        if any(capability_fields) and not all(capability_fields):
            raise ValueError("capability, schema, runtime, and provider must be specified together")
        if self.execution_contract is ExecutionContract.CANONICAL and not all(capability_fields):
            raise ValueError("canonical requests require a complete capability binding")
        if self.execution_contract is ExecutionContract.LEGACY and any(capability_fields):
            raise ValueError("legacy requests cannot carry a canonical capability binding")

    @property
    def repository(self) -> Path:
        return Path(self.repository_path)


@dataclass(frozen=True, slots=True)
class RuntimeExecutionResult:
    """Normalized terminal result returned by an agent runtime."""

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
    capability_id: str | None = None
    capability_schema_version: str | None = None

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
    """Provider-neutral boundary used by planning and task orchestration."""

    provider: str

    def verify_capabilities(
        self, repository: str | Path, required_capabilities: Sequence[str] = ()
    ) -> CapabilityReport:
        ...

    def execute(self, request: RuntimeExecutionRequest) -> RuntimeExecutionResult:
        ...

    # Wave 1 compatibility surface.
    def verify_planning_capabilities(self, repository: str | Path) -> CapabilityReport:
        ...

    def execute_planning(self, request: "PlanningExecutionRequest") -> "PlanningExecutionResult":
        ...


# The planning names remain public so existing Wave 1 integrations do not need
# migration. The concise aliases now describe the provider-neutral contract.
ExecutionRequest = RuntimeExecutionRequest
ExecutionResult = RuntimeExecutionResult
PlanningExecutionRequest = RuntimeExecutionRequest
PlanningExecutionResult = RuntimeExecutionResult
TaskExecutionRequest = RuntimeExecutionRequest
TaskExecutionResult = RuntimeExecutionResult


def normalize_required_capabilities(values: Sequence[str]) -> tuple[str, ...]:
    """Return stable, duplicate-free capability names for request metadata."""

    return tuple(dict.fromkeys(str(value) for value in values if str(value)))
