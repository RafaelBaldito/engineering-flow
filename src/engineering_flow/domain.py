"""Immutable provider-neutral values used by the workflow control plane."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class _ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class Stage(_ValueEnum):
    INTAKE = "intake"
    PRD = "prd"
    TECHSPEC = "techspec"
    TASK_PLAN = "task_plan"
    READY_FOR_WAVE_2 = "ready_for_wave_2"
    TASK_EXECUTION = "task_execution"
    TASKS_READY_FOR_WAVE_REVIEW = "tasks_ready_for_wave_review"


class LifecycleVersion(_ValueEnum):
    """The explicitly recorded contract under which a workflow is read."""

    HISTORICAL = "historical"
    CANONICAL_V1 = "canonical-v1"
    V2 = "v2"


class CanonicalStage(_ValueEnum):
    """Provider-neutral stages for workflows created under a canonical contract."""

    PRD = "prd"
    DELIVERY_PLAN = "delivery_plan"
    ARCHITECTURE = "architecture"
    TECHSPEC = "techspec"
    TASK_PLAN = "task_plan"
    TASK_EXECUTION = "task_execution"
    WAVE_REVIEW = "wave_review"
    FINAL_REVIEW = "final_review"
    DELIVERY_PREPARATION = "delivery_preparation"


class ScopeKind(_ValueEnum):
    WORKFLOW = "workflow"
    RELEASE = "release"
    WAVE = "wave"
    TASK = "task"


class HumanAttentionOutcome(_ValueEnum):
    UNKNOWN_OUTCOME = "unknown_outcome"
    INVALID_EVIDENCE = "invalid_evidence"
    AMBIGUOUS_MIGRATION = "ambiguous_migration"
    PARTIAL_MIGRATION = "partial_migration"
    MIGRATION_FAILED = "migration_failed"
    INVALID_STATE = "invalid_state"
    MISSING_AUTHORITY = "missing_authority"
    AMBIGUOUS_AUTHORITY = "ambiguous_authority"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INVALID_CAPABILITY_RESULT = "invalid_capability_result"
    PERMISSION_DENIED = "permission_denied"


class WorkflowStatus(_ValueEnum):
    CREATED = "created"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"
    HUMAN_ATTENTION = "human_attention"
    COMPLETED = "completed"
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"


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
    NOT_REQUIRED = "not_required"


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
    INTAKE = "intake"
    PRD = "prd"
    ARCHITECT = "architect"
    PLANNER = "planner"
    DEVELOPER = "developer"
    REVIEWER = "reviewer"


class CapabilityId(_ValueEnum):
    """Stable, provider-neutral work the lifecycle can request."""

    PRD = "prd"
    DELIVERY_PLANNING = "delivery-planning"
    ARCHITECTURE_OVERVIEW = "architecture-overview"
    TECHSPEC = "techspec"
    TASK_PLANNING = "task-planning"
    TASK_EXECUTION = "task-execution"
    TASK_REVIEW = "task-review"
    TASK_FIX = "task-fix"
    WAVE_REVIEW = "wave-review"
    WAVE_REMEDIATION = "wave-remediation"
    FINAL_REVIEW = "final-review"
    FINAL_REMEDIATION = "final-remediation"
    DELIVERY_PREPARATION = "delivery-preparation"


class HumanPolicyPlacement(_ValueEnum):
    BEFORE = "before"
    AFTER = "after"


class GovernanceDecisionType(_ValueEnum):
    """Immutable governance facts used to gate canonical lifecycle work."""

    APPROVAL = "approval"
    REJECTION = "rejection"
    WAVE_ACCEPTANCE = "wave_acceptance"
    RELEASE_ACCEPTANCE = "release_acceptance"
    WAVE_START_AUTHORIZATION = "wave_start_authorization"
    DELIVERY_AUTHORIZATION = "delivery_authorization"
    REVOCATION = "revocation"
    SUPERSESSION = "supersession"


class GovernanceDecision(_ValueEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    AUTHORIZED = "authorized"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class DomainCapability:
    """Canonical contract; deliberately contains no provider-native details."""

    id: CapabilityId
    schema_version: str
    supported_lifecycle_versions: tuple[LifecycleVersion, ...]
    supported_stages: tuple[CanonicalStage, ...]
    role: Role
    required_inputs: tuple[str, ...]
    required_outputs: tuple[str, ...]
    required_evidence: tuple[str, ...]
    human_policy_placement: HumanPolicyPlacement


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


class MigrationOutcome(_ValueEnum):
    COMPLETED = "completed"
    AMBIGUOUS = "ambiguous"
    PARTIAL = "partial"
    FAILED = "failed"


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
    lifecycle_version: LifecycleVersion = LifecycleVersion.HISTORICAL


class IntakeOutcome(_ValueEnum):
    READY = "READY"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class FeatureContract:
    outcome: IntakeOutcome
    feature_id: str
    goal: str
    requirements: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    constraints: tuple[str, ...]
    out_of_scope: tuple[str, ...]
    assumptions: tuple[str, ...]
    open_questions: tuple[str, ...]

    @classmethod
    def parse(cls, value: Mapping[str, Any], *, workflow_id: str) -> "FeatureContract":
        if not isinstance(value, Mapping) or set(value) != {"outcome", "feature"}:
            raise ValidationFailure("Feature Contract must contain only outcome and feature")
        try:
            outcome = IntakeOutcome(value["outcome"])
        except (TypeError, ValueError) as exc:
            raise ValidationFailure("Feature Contract has an invalid outcome") from exc
        feature = value["feature"]
        expected = {"id", "goal", "requirements", "acceptance_criteria", "constraints", "out_of_scope", "assumptions", "open_questions"}
        if not isinstance(feature, Mapping) or set(feature) != expected:
            raise ValidationFailure("Feature Contract feature has an invalid shape")
        def text(name: str) -> str:
            item = feature[name]
            if not isinstance(item, str) or not item.strip():
                raise ValidationFailure(f"Feature Contract {name} must be a non-empty string")
            return item
        def texts(name: str) -> tuple[str, ...]:
            item = feature[name]
            if not isinstance(item, list) or not all(isinstance(entry, str) and entry.strip() for entry in item):
                raise ValidationFailure(f"Feature Contract {name} must be a list of non-empty strings")
            return tuple(item)
        feature_id, goal = text("id"), text("goal")
        if feature_id != workflow_id:
            raise ValidationFailure("Feature Contract feature.id must equal the workflow ID")
        contract = cls(outcome, feature_id, goal, *(texts(name) for name in (
            "requirements", "acceptance_criteria", "constraints", "out_of_scope", "assumptions", "open_questions"
        )))
        if outcome is IntakeOutcome.READY and (not contract.requirements or not contract.acceptance_criteria or contract.open_questions):
            raise ValidationFailure("READY Feature Contract requires requirements and acceptance criteria with no open questions")
        if outcome is IntakeOutcome.NEEDS_CLARIFICATION and not contract.open_questions:
            raise ValidationFailure("NEEDS_CLARIFICATION Feature Contract requires open questions")
        return contract

    def as_payload(self) -> dict[str, Any]:
        return {"outcome": self.outcome.value, "feature": {
            "id": self.feature_id, "goal": self.goal, "requirements": list(self.requirements),
            "acceptance_criteria": list(self.acceptance_criteria), "constraints": list(self.constraints),
            "out_of_scope": list(self.out_of_scope), "assumptions": list(self.assumptions),
            "open_questions": list(self.open_questions),
        }}


@dataclass(frozen=True, slots=True)
class LifecycleState:
    workflow_id: str
    lifecycle_version: LifecycleVersion
    stage: CanonicalStage | None
    status: WorkflowStatus
    scope_id: str | None
    operation_key: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WorkflowScope:
    id: str
    workflow_id: str
    kind: ScopeKind
    external_key: str
    parent_scope_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    id: str
    workflow_id: str
    scope_id: str | None
    reference: str
    sha256: str
    operation_key: str
    created_at: str


@dataclass(frozen=True, slots=True)
class GovernanceRecord:
    id: str
    workflow_id: str
    scope_id: str
    lifecycle_version: LifecycleVersion
    operation_key: str
    decision_type: GovernanceDecisionType
    decision: GovernanceDecision
    actor: str
    evidence: tuple[tuple[str, str], ...]
    approval_target_stage: CanonicalStage | None
    predecessor_ids: tuple[str, ...]
    affected_ids: tuple[str, ...]
    created_at: str

    @property
    def operation_id(self) -> str:
        """Durable operation identity (named operation_key at the store boundary)."""
        return self.operation_key


@dataclass(frozen=True, slots=True)
class AuthorityEvaluation:
    active: bool
    attention_required: bool
    reason: str | None
    record: GovernanceRecord | None


@dataclass(frozen=True, slots=True)
class CapabilityOperation:
    id: str
    workflow_id: str
    scope_id: str | None
    operation_key: str
    request_fingerprint: str
    status: OperationStatus
    result: Mapping[str, Any] | None
    attention_outcome: HumanAttentionOutcome | None
    evidence_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class MigrationReceipt:
    id: str
    workflow_id: str
    operation_key: str
    source_version: LifecycleVersion
    target_version: LifecycleVersion
    outcome: MigrationOutcome
    detail: str | None
    created_at: str


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
