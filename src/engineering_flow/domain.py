"""Immutable provider-neutral values used by the workflow control plane."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class _ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class Stage(_ValueEnum):
    PRD = "prd"
    TECHSPEC = "techspec"
    TASK_PLAN = "task_plan"
    READY_FOR_WAVE_2 = "ready_for_wave_2"
    TASK_EXECUTION = "task_execution"
    TASKS_READY_FOR_WAVE_REVIEW = "tasks_ready_for_wave_review"


class WorkflowStatus(_ValueEnum):
    CREATED = "created"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"
    HUMAN_ATTENTION = "human_attention"
    COMPLETED = "completed"


class ApprovalPolicy(_ValueEnum):
    REQUIRED = "required"
    AUTOMATIC = "automatic"
    CONDITIONAL = "conditional"


class ApprovalDecision(_ValueEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"


class ApprovalState(_ValueEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"


class TaskStatus(_ValueEnum):
    PENDING = "pending"
    ACTIVE = "active"
    IN_PROGRESS = "active"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    ACCEPTED = "accepted"
    COMPLETED = "accepted"
    HUMAN_ATTENTION = "human_attention"


class TaskArtifactType(_ValueEnum):
    DEFINITION = "definition"
    DEVELOPER_RESULT = "developer_result"
    DEVELOPER = "developer_result"
    TEST_RESULT = "test_result"
    TEST = "test_result"
    REVIEW_RESULT = "review_result"
    REVIEW = "review_result"


class WorkKind(_ValueEnum):
    DEVELOP = "develop"
    FIX = "fix"
    REVIEW = "review"


class Role(_ValueEnum):
    PRD = "prd"
    ARCHITECT = "architect"
    PLANNER = "planner"
    DEVELOPER = "developer"
    REVIEWER = "reviewer"


class FailureClassification(_ValueEnum):
    WORKFLOW = "workflow"
    PROVIDER = "provider"
    AGENT_EXECUTION = "agent_execution"
    AUTHENTICATION = "authentication"
    TOOL = "tool"
    HUMAN_REJECTION = "human_rejection"
    PERSISTENCE = "persistence"
    TEST = "test"
    REVIEW = "review"


class OperationStatus(_ValueEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class ExecutionLifecycle(_ValueEnum):
    INTENT = "intent"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DomainFailure(Exception):
    """Base for failures that are safe for higher layers to classify."""

    classification = FailureClassification.WORKFLOW

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.details = dict(details or {})


class ValidationFailure(DomainFailure):
    classification = FailureClassification.WORKFLOW


class NotFoundFailure(DomainFailure):
    classification = FailureClassification.WORKFLOW


class ConflictFailure(DomainFailure):
    classification = FailureClassification.WORKFLOW


class PersistenceFailure(DomainFailure):
    classification = FailureClassification.PERSISTENCE


class ArtifactCorruptionFailure(PersistenceFailure):
    """The bytes on disk do not match the authoritative artifact hash."""


# A shorter name is useful to callers while retaining the explicit type above.
CorruptionFailure = ArtifactCorruptionFailure


@dataclass(frozen=True, slots=True)
class Workflow:
    id: str
    repository_path: str
    provider: str
    stage: Stage
    status: WorkflowStatus
    created_at: str
    updated_at: str
    configuration_snapshot: Mapping[str, Any]
    current_artifact_revision: int | None = None
    feature_input_path: str | None = None
    feature_input_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class Artifact:
    id: str
    workflow_id: str
    stage: Stage
    revision: int
    path: str
    sha256: str
    source_execution_id: str | None
    approval_state: ApprovalState
    created_at: str


@dataclass(frozen=True, slots=True)
class Approval:
    id: str
    workflow_id: str
    artifact_id: str
    decision: ApprovalDecision
    actor: str
    reason: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class Operation:
    id: str
    idempotency_key: str
    kind: str
    workflow_id: str
    status: OperationStatus
    related_record_id: str | None
    created_at: str
    updated_at: str
    task_id: str | None = None
    cycle_id: str | None = None
    work_kind: WorkKind | None = None


@dataclass(frozen=True, slots=True)
class Execution:
    id: str
    workflow_id: str
    session_id: str
    role: Role
    provider_execution_id: str | None
    request_hash: str
    lifecycle: ExecutionLifecycle
    capability_report: Mapping[str, Any]
    terminal_result: Mapping[str, Any] | None
    failure_classification: FailureClassification | None
    failure_detail: str | None
    created_at: str
    updated_at: str
    task_id: str | None = None
    cycle_id: str | None = None
    work_kind: WorkKind | None = None


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    id: str
    workflow_id: str
    sequence: int
    type: str
    stage: Stage | None
    artifact_id: str | None
    execution_id: str | None
    payload: Mapping[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class GenerationIntent:
    operation: Operation
    execution: Execution
    reused: bool = False


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    workflow_id: str
    logical_session_id: str
    role: Role
    provider: str
    provider_session_id: str | None
    created_at: str
    updated_at: str
    task_id: str | None = None
    cycle_id: str | None = None
    work_kind: WorkKind | None = None


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """Provider-neutral request handed from orchestration to a runtime."""

    stage: Stage
    role: Role
    repository_path: str
    authoritative_input_paths: tuple[str, ...]
    instruction: str
    request_hash: str


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Provider-neutral terminal result returned by a runtime."""

    success: bool
    content: str | None
    provider_execution_id: str | None
    metadata: Mapping[str, Any]
    failure_classification: FailureClassification | None = None
    failure_detail: str | None = None


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    id: str
    workflow_id: str
    ordinal: int
    key: str
    title: str
    instructions: str
    acceptance_criteria: tuple[str, ...]
    required_tests: tuple[str, ...]
    context_paths: tuple[str, ...]
    definition_json: str
    definition_sha256: str
    source_artifact_id: str
    source_artifact_sha256: str
    status: TaskStatus
    current_review_window: int
    current_cycle: int
    accepted_at: str | None = None

    @property
    def definition(self) -> Mapping[str, Any]:
        import json
        return json.loads(self.definition_json)

    @property
    def definition_hash(self) -> str:
        return self.definition_sha256

    @property
    def source_task_plan_artifact_id(self) -> str:
        return self.source_artifact_id

    @property
    def source_task_plan_artifact_sha256(self) -> str:
        return self.source_artifact_sha256


@dataclass(frozen=True, slots=True)
class TaskCycle:
    id: str
    task_id: str
    review_window: int
    cycle: int
    developer_execution_id: str | None
    required_test_artifact_id: str | None
    reviewer_execution_id: str | None
    review_artifact_id: str | None
    outcome: str | None
    created_at: str
    updated_at: str

    @property
    def review_number(self) -> int:
        return self.cycle


@dataclass(frozen=True, slots=True)
class TaskArtifact:
    id: str
    workflow_id: str
    task_id: str
    cycle_id: str | None
    artifact_type: TaskArtifactType
    path: str
    sha256: str
    source_execution_id: str | None
    created_at: str

    @property
    def type(self) -> TaskArtifactType:
        return self.artifact_type

    @property
    def hash(self) -> str:
        return self.sha256


@dataclass(frozen=True, slots=True)
class Intervention:
    id: str
    workflow_id: str
    task_id: str
    actor: str
    reason: str
    prior_review_window: int
    prior_cycle: int
    created_at: str


@dataclass(frozen=True, slots=True)
class TaskOperationIntent:
    operation: Operation
    execution: Execution
    task_id: str
    cycle_id: str | None = None
    reused: bool = False


# Concise aliases are kept for callers that model the persisted record as a
# task rather than a task-definition document.
Task = TaskDefinition
Cycle = TaskCycle


# The concise name is useful to event consumers while WorkflowEvent remains
# explicit in persistence-oriented code.
Event = WorkflowEvent
