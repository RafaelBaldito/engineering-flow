"""Orchestrator-owned Wave 1 planning lifecycle."""

from __future__ import annotations

import hashlib
import json
import uuid
import time
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from .domain import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalState,
    ConflictFailure,
    FailureClassification,
    Role,
    Stage,
    TaskArtifactType,
    TaskStatus,
    PersistenceFailure,
    ValidationFailure,
    WorkKind,
    Workflow,
    WorkflowStatus,
    CanonicalStage,
    CapabilityId,
    GovernanceDecisionType,
    HumanAttentionOutcome,
    LifecycleVersion,
    FeatureContract,
    IntakeOutcome,
    Plan,
)
from .runtime import (
    AgentRuntime,
    CapabilityReport,
    PlanningExecutionRequest,
    PlanningExecutionResult,
    TaskExecutionRequest,
    TerminalState,
    RuntimeExecutionRequest,
    RuntimeProgressEvent,
    CapabilityRegistry,
    CapabilityResolutionStatus,
)
from .plan_markdown import render_plan_markdown
from .store import WorkflowStore


_STAGES: tuple[Stage, ...] = (Stage.PRD, Stage.TECHSPEC, Stage.TASK_PLAN)
_ROLES: dict[Stage, Role] = {
    Stage.PRD: Role.PRD,
    Stage.TECHSPEC: Role.ARCHITECT,
    Stage.TASK_PLAN: Role.PLANNER,
}
_ARTIFACT_LABELS: dict[Stage, str] = {
    Stage.PRD: "prd",
    Stage.TECHSPEC: "techspec",
    Stage.TASK_PLAN: "task-plan",
}
_DEFAULT_POLICIES: dict[Stage, ApprovalPolicy] = {
    stage: ApprovalPolicy.REQUIRED for stage in _STAGES
}
_RETRIABLE_FAILURES = frozenset({
    FailureClassification.PROVIDER,
    FailureClassification.AGENT_EXECUTION,
    FailureClassification.TOOL,
})


class IntakeOrchestrator:
    """The bounded V2 Intake lifecycle; it deliberately has no successor stage."""

    def __init__(self, store: WorkflowStore, runtime: AgentRuntime, *, timeout_seconds: float = 1800,
                 monotonic_clock: Any = time.monotonic) -> None:
        self.store, self.runtime, self.timeout_seconds, self._monotonic = store, runtime, timeout_seconds, monotonic_clock

    def run(self, repository_path: str | Path, request: str, *, provider: str | None = None,
            configuration_snapshot: Mapping[str, Any] | None = None, progress_sink: Any = None) -> Workflow:
        if not isinstance(request, str) or not request.strip():
            raise ValidationFailure("request must be non-empty")
        workflow_id = str(uuid.uuid4())
        workflow = self.store.create_workflow(repository_path, provider=provider or getattr(self.runtime, "provider", "provider"),
            configuration_snapshot=configuration_snapshot, workflow_id=workflow_id, feature_content=request.encode("utf-8"),
            feature_path=self.store.workspace_path / "workflows" / workflow_id / "input" / "request.txt",
            lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
        return self._intake(workflow, progress_sink=progress_sink)

    def status(self, workflow_id: str) -> Workflow:
        return self.store.get_workflow(workflow_id)

    def _intake(self, workflow: Workflow, *, progress_sink: Any = None) -> Workflow:
        request_path = Path(workflow.feature_input_path or "")
        raw = request_path.read_bytes()
        request_digest = hashlib.sha256(raw).hexdigest()
        instruction = (
            f"You are the Intake agent. The raw user request is the authoritative UTF-8 file {request_path} (sha256: {request_digest}); read it before responding. "
            "If information can reasonably be discovered from the repository, inspect the repository instead of asking the user. "
            "You may make and record safe engineering assumptions. If a material product or business decision is missing, do not invent it; "
            "ask an explicit open question instead. Do not implement, plan, mutate files, or progress beyond Intake. "
            f"Return only the Feature Contract schema. feature.id must be {workflow.id}. "
            "Set outcome READY only when requirements and acceptance_criteria are non-empty and open_questions is empty. "
            "If any material product or business question remains, set outcome NEEDS_CLARIFICATION and include it in open_questions."
        )
        request_hash = hashlib.sha256(json.dumps({"raw_request_sha256": request_digest, "stage": "intake", "instruction": instruction, "output": "feature-contract-v1"}, sort_keys=True).encode()).hexdigest()
        report = self.runtime.verify_planning_capabilities(workflow.repository_path)
        intent = self.store.create_generation_intent(workflow.id, Stage.INTAKE, request_hash=request_hash, provider=workflow.provider,
            role=Role.INTAKE, revision=1, artifact_path=self.store.workspace_path / "workflows" / workflow.id / "artifacts" / "001-feature-contract.json", capability_report=_json_mapping(report))
        if intent.reused:
            return self.store.get_workflow(workflow.id)
        if not report.available or not report.read_only_planning:
            self.store.fail_generation(intent.operation.idempotency_key, FailureClassification.PROVIDER, report.failure_detail or "Intake runtime is unavailable")
            return self.store.get_workflow(workflow.id)
        self.store.set_workflow_state(workflow.id, stage=Stage.INTAKE, status=WorkflowStatus.RUNNING, event_type="workflow.running", payload={"execution_id": intent.execution.id})
        self.store.start_execution(intent.execution.id)
        started = self._monotonic()
        _emit_progress(progress_sink, Stage.INTAKE, "started", 0.0)
        root = self.store.workspace_path / "workflows" / workflow.id / "runtime" / intent.execution.id
        runtime_request = PlanningExecutionRequest(workflow_id=workflow.id, execution_id=intent.execution.id, logical_session_id=intent.execution.session_id,
            role=Role.INTAKE, stage=Stage.INTAKE, repository_path=workflow.repository_path,
            authoritative_input_paths=(str(request_path),), authoritative_input_hashes=(request_digest,), instruction=instruction,
            output_schema_path=str(root / "feature-contract.schema.json"), final_output_path=str(root / "final-output.json"), timeout_seconds=self.timeout_seconds,
            required_capabilities=("read_only",), progress_sink=progress_sink)
        try:
            # Keep the public compatibility entry point: it delegates to the
            # generalized runtime contract and carries the same transient sink.
            result = self.runtime.execute_planning(runtime_request)
        except Exception as exc:
            self.store.mark_operation_unknown(intent.operation.idempotency_key, detail=str(exc))
            result_workflow = self.store.set_workflow_state(workflow.id, stage=Stage.INTAKE, status=WorkflowStatus.HUMAN_ATTENTION, event_type="workflow.human_attention", payload={"reason": "provider operation outcome is unknown"})
            _emit_progress(progress_sink, Stage.INTAKE, "failed", self._monotonic() - started)
            return result_workflow
        self.store.start_execution(intent.execution.id, provider_execution_id=result.provider_execution_id)
        for event in result.events:
            self.store.append_event(workflow.id, f"agent.runtime.{event.type}", stage=Stage.INTAKE,
                execution_id=intent.execution.id, payload={"provider_event_id": event.provider_event_id,
                "timestamp": event.timestamp, **dict(event.payload)})
        if result.terminal_state is TerminalState.UNKNOWN:
            self.store.mark_operation_unknown(intent.operation.idempotency_key, detail=result.failure_detail or "unknown provider outcome")
            result_workflow = self.store.set_workflow_state(workflow.id, stage=Stage.INTAKE, status=WorkflowStatus.HUMAN_ATTENTION, event_type="workflow.human_attention", payload={"reason": "provider operation outcome is unknown"})
            _emit_progress(progress_sink, Stage.INTAKE, "failed", self._monotonic() - started)
            return result_workflow
        if not result.success or not isinstance(result.final_payload, Mapping):
            self.store.fail_generation(intent.operation.idempotency_key, result.failure_classification or FailureClassification.AGENT_EXECUTION, result.failure_detail or "Intake runtime failed")
            _emit_progress(progress_sink, Stage.INTAKE, "timed_out" if result.terminal_state is TerminalState.TIMED_OUT else "failed", self._monotonic() - started)
            return self.store.get_workflow(workflow.id)
        try:
            contract = FeatureContract.parse(result.final_payload, workflow_id=workflow.id)
        except ValidationFailure as exc:
            self.store.fail_generation(intent.operation.idempotency_key, FailureClassification.AGENT_EXECUTION, str(exc))
            _emit_progress(progress_sink, Stage.INTAKE, "failed", self._monotonic() - started)
            return self.store.get_workflow(workflow.id)
        status = {IntakeOutcome.READY: WorkflowStatus.READY, IntakeOutcome.NEEDS_CLARIFICATION: WorkflowStatus.NEEDS_CLARIFICATION, IntakeOutcome.REJECTED: WorkflowStatus.REJECTED}[contract.outcome]
        self.store.complete_generation(intent.operation.idempotency_key, content=json.dumps(contract.as_payload(), ensure_ascii=False, indent=2) + "\n",
            artifact_path=self.store.workspace_path / "workflows" / workflow.id / "artifacts" / "001-feature-contract.json", stage=Stage.INTAKE, revision=1,
            terminal_result={"provider": result.provider, "final_payload": contract.as_payload(), "usage": dict(result.usage), "metadata": dict(result.metadata)},
            workflow_stage=Stage.INTAKE, workflow_status=status, approval_state=ApprovalState.NOT_REQUIRED,
            completion_event_type="intake.completed", completion_event_payload={"outcome": contract.outcome.value, "question_count": len(contract.open_questions)})
        result_workflow = self.store.get_workflow(workflow.id)
        _emit_progress(progress_sink, Stage.INTAKE, "completed", self._monotonic() - started)
        return result_workflow


@dataclass(frozen=True, slots=True)
class PlanProjection:
    """Observation of the non-authoritative Plan Markdown cache."""

    path: Path
    state: str
    error: str | None = None


class V2PlanOrchestrator:
    """The deliberately bounded V2 successor: Plan and stop."""
    def __init__(self, store: WorkflowStore, runtime: AgentRuntime, *, timeout_seconds: float = 1800,
                 monotonic_clock: Any = time.monotonic) -> None:
        self.store, self.runtime, self.timeout_seconds, self._monotonic = store, runtime, timeout_seconds, monotonic_clock

    def resume(self, workflow_id: str, *, progress_sink: Any = None) -> Workflow:
        workflow = self.store.get_workflow(workflow_id)
        if workflow.lifecycle_version is not LifecycleVersion.V2:
            raise ConflictFailure("workflow is not V2")
        if workflow.stage is Stage.PLAN or not (workflow.stage is Stage.INTAKE and workflow.status is WorkflowStatus.READY):
            return workflow
        source = self.store.list_artifacts(workflow.id, Stage.INTAKE)
        if len(source) != 1:
            raise ValidationFailure("READY Feature Contract artifact is required")
        feature_artifact = source[0]
        if feature_artifact.revision != 1 or feature_artifact.approval_state is not ApprovalState.NOT_REQUIRED:
            raise ValidationFailure("Feature Contract artifact is not a READY Intake artifact")
        feature_payload = json.loads(self.store.read_artifact(feature_artifact.id))
        feature = FeatureContract.parse(feature_payload, workflow_id=workflow.id)
        if feature.outcome is not IntakeOutcome.READY or feature.open_questions:
            raise ValidationFailure("Feature Contract must be READY")
        revision = self.store.next_generation_revision(workflow.id, Stage.PLAN)
        plan_id = f"{workflow.id}:plan:r{revision}"
        instruction = (
            f"You are the Planner. Read the authoritative READY Feature Contract at {feature_artifact.path} (artifact UUID {feature_artifact.id}, sha256 {feature_artifact.sha256}) and inspect repository {workflow.repository_path}. "
            "Read applicable AGENTS.md, relevant implementation, tests, configuration, and patterns. Produce a small ordered dependency-aware implementation Plan directly; do not create a PRD, Tech Spec, Wave or release governance. "
            "Do not modify files, commit, approve, invoke agents, run implementation work or progress beyond Plan. "
            f"Return only strict Plan JSON. plan.id={plan_id}; workflow_id={workflow.id}; revision={revision}; feature_contract artifact_id={feature_artifact.id}; sha256={feature_artifact.sha256}. "
            "Each task must be precise with bounded context and verification; complexity and risk are independent; assumptions must not change product behavior."
        )
        request_hash = hashlib.sha256(json.dumps({"feature_artifact_id": feature_artifact.id, "feature_sha256": feature_artifact.sha256, "instruction": instruction, "stage": "plan", "revision": revision, "output": "plan-v1"}, sort_keys=True).encode()).hexdigest()
        report = self.runtime.verify_planning_capabilities(workflow.repository_path)
        artifact_path = self.store.workspace_path / "workflows" / workflow.id / "artifacts" / "002-plan.json"
        intent = self.store.create_generation_intent(workflow.id, Stage.PLAN, request_hash=request_hash, provider=workflow.provider, role=Role.PLANNER, revision=revision, artifact_path=artifact_path, capability_report=_json_mapping(report))
        if intent.reused:
            return self.store.get_workflow(workflow.id)
        if not report.available or not report.read_only_planning:
            self.store.fail_generation(intent.operation.idempotency_key, FailureClassification.PROVIDER, report.failure_detail or "Planner runtime is unavailable")
            return self.store.get_workflow(workflow.id)
        self.store.set_workflow_state(workflow.id, stage=Stage.PLAN, status=WorkflowStatus.RUNNING, event_type="workflow.running", payload={"execution_id": intent.execution.id})
        self.store.start_execution(intent.execution.id)
        started = self._monotonic()
        _emit_progress(progress_sink, Stage.PLAN, "started", 0)
        root = self.store.workspace_path / "workflows" / workflow.id / "runtime" / intent.execution.id
        request = RuntimeExecutionRequest(workflow_id=workflow.id, execution_id=intent.execution.id, logical_session_id=intent.execution.session_id, role=Role.PLANNER, stage=Stage.PLAN, repository_path=workflow.repository_path, authoritative_input_paths=(feature_artifact.path,), authoritative_input_hashes=(feature_artifact.sha256,), instruction=instruction, output_schema_path=str(root / "plan.schema.json"), final_output_path=str(root / "final-output.json"), timeout_seconds=self.timeout_seconds, required_capabilities=("read_only",), progress_sink=progress_sink)
        try:
            result = self.runtime.execute(request)
        except Exception as exc:
            self.store.mark_operation_unknown(intent.operation.idempotency_key, detail=str(exc))
            result_workflow = self.store.set_workflow_state(workflow.id, stage=Stage.PLAN, status=WorkflowStatus.HUMAN_ATTENTION, event_type="workflow.human_attention", payload={"reason": "provider operation outcome is unknown"})
            _emit_progress(progress_sink, Stage.PLAN, "failed", self._monotonic() - started)
            return result_workflow
        for event in result.events:
            self.store.append_event(workflow.id, f"agent.runtime.{event.type}", stage=Stage.PLAN, execution_id=intent.execution.id, payload={"provider_event_id": event.provider_event_id, "timestamp": event.timestamp, **dict(event.payload)})
        if result.terminal_state is TerminalState.UNKNOWN:
            self.store.mark_operation_unknown(intent.operation.idempotency_key, detail=result.failure_detail or "unknown provider outcome")
            result_workflow = self.store.set_workflow_state(workflow.id, stage=Stage.PLAN, status=WorkflowStatus.HUMAN_ATTENTION, event_type="workflow.human_attention", payload={"reason": "provider operation outcome is unknown"})
            _emit_progress(progress_sink, Stage.PLAN, "failed", self._monotonic() - started)
            return result_workflow
        if not result.success or not isinstance(result.final_payload, Mapping):
            self.store.fail_generation(intent.operation.idempotency_key, result.failure_classification or FailureClassification.AGENT_EXECUTION, result.failure_detail or "Planner runtime failed")
            _emit_progress(progress_sink, Stage.PLAN, "timed_out" if result.terminal_state is TerminalState.TIMED_OUT else "failed", self._monotonic() - started)
            return self.store.get_workflow(workflow.id)
        try:
            plan = Plan.parse(result.final_payload, workflow_id=workflow.id, revision=revision, feature_contract_artifact_id=feature_artifact.id, feature_contract_sha256=feature_artifact.sha256, repository_path=workflow.repository_path)
        except ValidationFailure as exc:
            self.store.fail_generation(intent.operation.idempotency_key, FailureClassification.AGENT_EXECUTION, str(exc))
            _emit_progress(progress_sink, Stage.PLAN, "failed", self._monotonic() - started)
            return self.store.get_workflow(workflow.id)
        self.store.complete_generation(intent.operation.idempotency_key, content=json.dumps(plan.as_payload(), ensure_ascii=False, indent=2) + "\n", artifact_path=artifact_path, stage=Stage.PLAN, revision=revision, terminal_result={"provider": result.provider, "final_payload": plan.as_payload(), "usage": dict(result.usage), "metadata": dict(result.metadata)}, workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.AWAITING_APPROVAL, approval_state=ApprovalState.PENDING, completion_event_type="plan.completed", completion_event_payload={"plan_id": plan.id, "revision": revision, "task_count": len(plan.tasks), "feature_contract_artifact_id": feature_artifact.id})
        # The canonical JSON transaction has committed.  This is deliberately
        # best-effort: projection failure cannot change Plan validity or state.
        try:
            self.inspect_plan_projection(workflow.id, repair=True)
        except PersistenceFailure:
            pass
        _emit_progress(progress_sink, Stage.PLAN, "completed", self._monotonic() - started)
        return self.store.get_workflow(workflow.id)

    def inspect_plan_projection(self, workflow_id: str, *, repair: bool = False) -> PlanProjection:
        """Verify canonical inputs then inspect, and optionally repair, its view."""

        workflow, _artifact, plan = self._verified_plan(workflow_id)
        expected_markdown = render_plan_markdown(plan)
        expected = expected_markdown.encode("utf-8")
        path = self.store.plan_markdown_path(workflow.id)
        actual = self.store.read_plan_markdown(workflow.id)
        state = "missing" if actual is None else ("current" if actual == expected else "modified")
        if repair and state != "current":
            try:
                self.store.write_plan_markdown(workflow.id, expected_markdown)
            except PersistenceFailure as exc:
                return PlanProjection(path, state, str(exc))
            return PlanProjection(path, "current")
        return PlanProjection(path, state)

    def approve(self, workflow_id: str, artifact_id: str, *, actor: str = "human",
                reason: str | None = None) -> Workflow:
        """Approve exactly the verified current V2 Plan and stop at its gate."""
        workflow, artifact, plan = self._validate_current_plan_decision(workflow_id, artifact_id)
        self.store.record_approval(
            workflow.id, artifact.id, ApprovalDecision.APPROVED, actor=actor, reason=reason,
            workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.PLAN_APPROVED,
            transition_event_type="plan.approved",
            transition_payload={"plan_id": plan.id, "revision": plan.revision},
        )
        return self.store.get_workflow(workflow.id)

    def reject(self, workflow_id: str, artifact_id: str, *, actor: str = "human",
               reason: str | None = None) -> Workflow:
        """Reject exactly the verified current V2 Plan and stop at its gate."""
        workflow, artifact, plan = self._validate_current_plan_decision(workflow_id, artifact_id)
        self.store.record_approval(
            workflow.id, artifact.id, ApprovalDecision.REJECTED, actor=actor, reason=reason,
            workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.REJECTED,
            transition_event_type="plan.rejected",
            transition_payload={"plan_id": plan.id, "revision": plan.revision},
        )
        return self.store.get_workflow(workflow.id)

    def resolve_current_pending_plan_artifact(self, workflow_id: str) -> str:
        """Resolve only the exact V2 Plan that the existing gate can decide."""
        workflow = self.store.get_workflow(workflow_id)
        if workflow.lifecycle_version is not LifecycleVersion.V2:
            raise ConflictFailure("workflow is not V2")
        if workflow.stage is not Stage.PLAN or workflow.status is not WorkflowStatus.AWAITING_APPROVAL:
            raise ConflictFailure("workflow is not awaiting Plan approval")
        candidates = [
            artifact for artifact in self.store.list_artifacts(workflow.id, Stage.PLAN)
            if artifact.revision == workflow.current_artifact_revision
            and artifact.approval_state is ApprovalState.PENDING
        ]
        if len(candidates) != 1:
            raise ConflictFailure("could not resolve a unique current pending Plan artifact; specify --artifact")
        # Reuse every strict authority check (including bytes, source binding,
        # revision, ownership, and approval state) before returning an ID.
        _workflow, artifact, _plan = self._validate_current_plan_decision(
            workflow.id, candidates[0].id
        )
        return artifact.id

    def _validate_current_plan_decision(self, workflow_id: str, artifact_id: str) -> tuple[Workflow, Any, Plan]:
        """Verify the immutable Plan boundary shared by both human decisions."""
        workflow = self.store.get_workflow(workflow_id)
        if workflow.lifecycle_version is not LifecycleVersion.V2:
            raise ConflictFailure("workflow is not V2")
        if workflow.stage is not Stage.PLAN or workflow.status is not WorkflowStatus.AWAITING_APPROVAL:
            raise ConflictFailure("workflow is not awaiting Plan approval")
        supplied = self.store.get_artifact(artifact_id)
        if supplied.workflow_id != workflow.id:
            raise ConflictFailure("artifact does not belong to workflow")
        if supplied.stage is not Stage.PLAN:
            raise ConflictFailure("approval requires a Plan artifact")
        plans = self.store.list_artifacts(workflow.id, Stage.PLAN)
        if not plans:
            raise ConflictFailure("no Plan artifact is awaiting approval")
        artifact = plans[-1]
        if artifact.id != artifact_id:
            raise ConflictFailure("approval targets a stale artifact")
        if (workflow.current_artifact_revision != artifact.revision
                or artifact.revision != max(item.revision for item in plans)):
            raise ConflictFailure("approval targets a noncurrent Plan artifact")
        if artifact.approval_state is not ApprovalState.PENDING:
            raise ConflictFailure("artifact approval has already been decided")
        if self.store.get_approval_for_artifact(artifact.id) is not None:
            raise ConflictFailure("artifact approval has already been decided")

        # Re-read immutable bytes before the transaction; approval is for the
        # verified Plan, not merely for its database identifier.
        try:
            payload = json.loads(self.store.read_artifact(artifact.id))
        except json.JSONDecodeError as exc:
            raise ValidationFailure("Plan artifact is not valid JSON") from exc
        source = self.store.list_artifacts(workflow.id, Stage.INTAKE)
        if len(source) != 1:
            raise ValidationFailure("exact READY Feature Contract artifact is required")
        feature_artifact = source[0]
        if (feature_artifact.revision != 1
                or feature_artifact.approval_state is not ApprovalState.NOT_REQUIRED):
            raise ValidationFailure("Feature Contract artifact is not a READY Intake artifact")
        try:
            feature_payload = json.loads(self.store.read_artifact(feature_artifact.id))
        except json.JSONDecodeError as exc:
            raise ValidationFailure("Feature Contract artifact is not valid JSON") from exc
        feature = FeatureContract.parse(feature_payload, workflow_id=workflow.id)
        if feature.outcome is not IntakeOutcome.READY or feature.open_questions:
            raise ValidationFailure("Feature Contract must be READY")
        plan = Plan.parse(
            payload, workflow_id=workflow.id, revision=artifact.revision,
            feature_contract_artifact_id=feature_artifact.id,
            feature_contract_sha256=feature_artifact.sha256,
            repository_path=workflow.repository_path,
        )
        return workflow, artifact, plan

    def _verified_plan(self, workflow_id: str) -> tuple[Workflow, Any, Plan]:
        """Load a Plan only after hash-verifying its JSON and READY source."""

        workflow = self.store.get_workflow(workflow_id)
        if workflow.lifecycle_version is not LifecycleVersion.V2 or workflow.stage is not Stage.PLAN:
            raise ConflictFailure("workflow has no V2 Plan projection")
        plans = self.store.list_artifacts(workflow.id, Stage.PLAN)
        if not plans:
            raise ValidationFailure("Plan artifact is required for projection")
        artifact = plans[-1]
        try:
            payload = json.loads(self.store.read_artifact(artifact.id))
        except json.JSONDecodeError as exc:
            raise ValidationFailure("Plan artifact is not valid JSON") from exc
        source = self.store.list_artifacts(workflow.id, Stage.INTAKE)
        if len(source) != 1:
            raise ValidationFailure("exact READY Feature Contract artifact is required")
        feature_artifact = source[0]
        if (feature_artifact.revision != 1
                or feature_artifact.approval_state is not ApprovalState.NOT_REQUIRED):
            raise ValidationFailure("Feature Contract artifact is not a READY Intake artifact")
        try:
            feature_payload = json.loads(self.store.read_artifact(feature_artifact.id))
        except json.JSONDecodeError as exc:
            raise ValidationFailure("Feature Contract artifact is not valid JSON") from exc
        feature = FeatureContract.parse(feature_payload, workflow_id=workflow.id)
        if feature.outcome is not IntakeOutcome.READY or feature.open_questions:
            raise ValidationFailure("Feature Contract must be READY")
        plan = Plan.parse(
            payload, workflow_id=workflow.id, revision=artifact.revision,
            feature_contract_artifact_id=feature_artifact.id,
            feature_contract_sha256=feature_artifact.sha256,
            repository_path=workflow.repository_path,
        )
        return workflow, artifact, plan

def _emit_progress(sink: Any, stage: Stage, kind: str, elapsed: float) -> None:
    """Emit safe transient stage progress without coupling it to lifecycle work."""

    if sink:
        try:
            sink(RuntimeProgressEvent(kind, stage, max(0.0, elapsed)))
        except Exception:
            pass


def _json_mapping(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


class CanonicalLifecycleOrchestrator:
    """Policy-only driver for records created under ``canonical-v1``.

    The legacy ``PlanningOrchestrator`` remains readable and continues to own
    the Wave 2 task loop.  This narrow companion deliberately accepts an
    already-normalized provider result: it resolves the requested capability,
    checks persisted authority, and is the sole component that selects the
    successor stage.
    """

    _CAPABILITY_BY_STAGE = {
        CanonicalStage.PRD: CapabilityId.PRD,
        CanonicalStage.DELIVERY_PLAN: CapabilityId.DELIVERY_PLANNING,
        CanonicalStage.ARCHITECTURE: CapabilityId.ARCHITECTURE_OVERVIEW,
        CanonicalStage.TECHSPEC: CapabilityId.TECHSPEC,
        CanonicalStage.TASK_PLAN: CapabilityId.TASK_PLANNING,
        CanonicalStage.WAVE_REVIEW: CapabilityId.WAVE_REVIEW,
        CanonicalStage.FINAL_REVIEW: CapabilityId.FINAL_REVIEW,
        CanonicalStage.DELIVERY_PREPARATION: CapabilityId.DELIVERY_PREPARATION,
    }
    _ROLE_BY_CAPABILITY = {
        CapabilityId.PRD: Role.PRD, CapabilityId.DELIVERY_PLANNING: Role.PLANNER,
        CapabilityId.ARCHITECTURE_OVERVIEW: Role.ARCHITECT, CapabilityId.TECHSPEC: Role.ARCHITECT,
        CapabilityId.TASK_PLANNING: Role.PLANNER, CapabilityId.WAVE_REVIEW: Role.REVIEWER,
        CapabilityId.FINAL_REVIEW: Role.REVIEWER, CapabilityId.DELIVERY_PREPARATION: Role.PLANNER,
    }

    # These are gates for *leaving* a stage.  They deliberately live beside
    # the lifecycle policy rather than in an adapter: provider output is never
    # allowed to select either an authority type or a successor.
    _AUTHORITY_BY_STAGE = {
        CanonicalStage.DELIVERY_PLAN: GovernanceDecisionType.APPROVAL,
        CanonicalStage.ARCHITECTURE: GovernanceDecisionType.APPROVAL,
        CanonicalStage.TECHSPEC: GovernanceDecisionType.APPROVAL,
        CanonicalStage.TASK_PLAN: GovernanceDecisionType.APPROVAL,
        CanonicalStage.TASK_EXECUTION: GovernanceDecisionType.WAVE_START_AUTHORIZATION,
        CanonicalStage.WAVE_REVIEW: GovernanceDecisionType.WAVE_ACCEPTANCE,
        CanonicalStage.FINAL_REVIEW: GovernanceDecisionType.RELEASE_ACCEPTANCE,
        CanonicalStage.DELIVERY_PREPARATION: GovernanceDecisionType.DELIVERY_AUTHORIZATION,
    }

    def __init__(self, store: WorkflowStore, *, registry: CapabilityRegistry | None = None,
                 runtime_name: str = "codex", architecture_required: bool | None = None) -> None:
        self.store = store
        self.registry = registry or CapabilityRegistry()
        self.runtime_name = runtime_name
        # Kept only as a compatibility argument.  Branching is derived from
        # the persisted delivery-plan result below, never this process-local
        # value.
        self.architecture_required = architecture_required

    def _attention(self, workflow_id: str, scope_id: str, operation_key: str,
                   fingerprint: str, outcome: HumanAttentionOutcome, detail: str) -> LifecycleState:
        return self.store.record_canonical_transition(
            workflow_id, operation_key=operation_key, request_fingerprint=fingerprint,
            scope_id=scope_id, lifecycle_version=LifecycleVersion.CANONICAL_V1,
            stage=self.store.get_lifecycle_state(workflow_id).stage if self.store.get_lifecycle_state(workflow_id) else None,
            status=WorkflowStatus.HUMAN_ATTENTION, result={"detail": detail}, attention_outcome=outcome,
        )

    def advance(self, workflow_id: str, *, scope_id: str, operation_key: str,
                request_fingerprint: str, normalized_result: Mapping[str, Any],
                evidence_reference: str, evidence_sha256: str,
                supported_providers: Mapping[str, str],
                repository_constraints: Mapping[str, Any] | None = None) -> LifecycleState:
        """Commit one legal successor, or durably pause for human attention.

        ``normalized_result`` is evidence only. Its ``outcome`` must be
        ``success`` and its capability identifier/schema must match the
        persisted current stage; it never supplies a destination stage.
        """
        state = self.store.get_lifecycle_state(workflow_id)
        if state is None or state.lifecycle_version is not LifecycleVersion.CANONICAL_V1 or state.stage is None:
            return self._attention(workflow_id, scope_id, operation_key, request_fingerprint,
                                   HumanAttentionOutcome.INVALID_STATE, "canonical lifecycle state is missing or incompatible")
        # Wave 2 owns task execution.  Its accepted-task evidence is the only
        # input accepted here; task-plan PENDING cells are not interpreted.
        if state.stage is CanonicalStage.TASK_EXECUTION:
            if not self.store.has_accepted_task_evidence(
                workflow_id, scope_id, normalized_result.get("accepted_task_evidence", {})
            ):
                return self._attention(workflow_id, scope_id, operation_key, request_fingerprint,
                                       HumanAttentionOutcome.INVALID_EVIDENCE,
                                       "accepted Wave 2 task evidence is required for Wave review")
            capability_id = None
        else:
            capability_id = self._CAPABILITY_BY_STAGE.get(state.stage)
        if capability_id is None and state.stage is not CanonicalStage.TASK_EXECUTION:
            return self._attention(workflow_id, scope_id, operation_key, request_fingerprint,
                                   HumanAttentionOutcome.INVALID_STATE, "stage has no dispatchable canonical capability")
        resolution = None
        if capability_id is not None:
            resolution = self.registry.resolve(
            lifecycle_version=state.lifecycle_version, stage=state.stage, capability_id=capability_id,
            role=self._ROLE_BY_CAPABILITY[capability_id], runtime=self.runtime_name,
            provider=self.store.get_workflow(workflow_id).provider,
            repository_constraints=repository_constraints or {}, supported_providers=supported_providers,
            )
        if resolution is not None and resolution.status is not CapabilityResolutionStatus.RESOLVED:
            return self._attention(workflow_id, scope_id, operation_key, request_fingerprint,
                                   HumanAttentionOutcome.UNSUPPORTED_CAPABILITY, resolution.detail or "capability is unresolved")
        if not isinstance(normalized_result, Mapping):
            return self._attention(workflow_id, scope_id, operation_key, request_fingerprint,
                                   HumanAttentionOutcome.INVALID_CAPABILITY_RESULT, "normalized result is not structured")
        outcome = normalized_result.get("outcome")
        if outcome in {"permission_denied", "unknown"}:
            return self._attention(workflow_id, scope_id, operation_key, request_fingerprint,
                                   HumanAttentionOutcome.PERMISSION_DENIED if outcome == "permission_denied" else HumanAttentionOutcome.UNKNOWN_OUTCOME,
                                   "provider result requires human attention")
        if (outcome != "success"
                or (capability_id is not None and (
                    normalized_result.get("capability_id") != capability_id.value
                    or normalized_result.get("schema_version") != resolution.binding.capability.schema_version))):
            return self._attention(workflow_id, scope_id, operation_key, request_fingerprint,
                                   HumanAttentionOutcome.INVALID_CAPABILITY_RESULT, "normalized result does not satisfy capability contract")
        if (state.stage is CanonicalStage.DELIVERY_PLAN
                and not isinstance(normalized_result.get("architecture_required"), bool)):
            return self._attention(workflow_id, scope_id, operation_key, request_fingerprint,
                                   HumanAttentionOutcome.INVALID_EVIDENCE,
                                   "delivery-plan result lacks persisted architecture policy evidence")
        required_authority = self._AUTHORITY_BY_STAGE.get(state.stage)
        if required_authority is not None:
            authority = self.store.evaluate_active_authority(
                workflow_id, scope_id=scope_id, lifecycle_version=state.lifecycle_version,
                decision_type=required_authority,
                approval_target_stage=state.stage if required_authority is GovernanceDecisionType.APPROVAL else None,
            )
            if not authority.active:
                return self._attention(workflow_id, scope_id, operation_key, request_fingerprint,
                                       HumanAttentionOutcome.AMBIGUOUS_AUTHORITY if authority.attention_required else HumanAttentionOutcome.MISSING_AUTHORITY,
                                       authority.reason or "required authority is unavailable")
        successor = self._successor(state.stage, normalized_result)
        return self.store.record_canonical_transition(
            workflow_id, operation_key=operation_key, request_fingerprint=request_fingerprint,
            scope_id=scope_id, lifecycle_version=state.lifecycle_version, stage=successor,
            status=WorkflowStatus.CREATED, result=dict(normalized_result),
            evidence_reference=evidence_reference, evidence_sha256=evidence_sha256,
            expected_predecessor=state.stage, required_authority=required_authority,
            required_approval_target_stage=state.stage if required_authority is GovernanceDecisionType.APPROVAL else None,
        )

    def _successor(self, stage: CanonicalStage, result: Mapping[str, Any]) -> CanonicalStage:
        if stage is CanonicalStage.DELIVERY_PLAN:
            required = result.get("architecture_required")
            if not isinstance(required, bool):
                # The policy fact is retained in this same result transaction,
                # making reopen/reconciliation deterministic.
                raise ValidationFailure("delivery-plan result must include boolean architecture_required policy fact")
            if not required:
                return CanonicalStage.TECHSPEC
        successors = {
            CanonicalStage.PRD: CanonicalStage.DELIVERY_PLAN,
            CanonicalStage.DELIVERY_PLAN: CanonicalStage.ARCHITECTURE,
            CanonicalStage.ARCHITECTURE: CanonicalStage.TECHSPEC,
            CanonicalStage.TECHSPEC: CanonicalStage.TASK_PLAN,
            CanonicalStage.TASK_PLAN: CanonicalStage.TASK_EXECUTION,
            CanonicalStage.TASK_EXECUTION: CanonicalStage.WAVE_REVIEW,
            CanonicalStage.WAVE_REVIEW: CanonicalStage.FINAL_REVIEW,
            CanonicalStage.FINAL_REVIEW: CanonicalStage.DELIVERY_PREPARATION,
            CanonicalStage.DELIVERY_PREPARATION: CanonicalStage.DELIVERY_PREPARATION,
        }
        return successors[stage]

    def resume(self, workflow_id: str) -> LifecycleState:
        """Return durable canonical state without re-dispatching provider work."""
        state = self.store.get_lifecycle_state(workflow_id)
        if state is None:
            raise ValidationFailure("canonical lifecycle state is missing")
        return state


class PlanningOrchestrator:
    """The sole Wave 1 authority for planning state transitions."""

    def __init__(
        self,
        store: WorkflowStore,
        runtime: AgentRuntime,
        *,
        approval_policies: Mapping[Stage | str, ApprovalPolicy | str] | None = None,
        timeout_seconds: float = 1800,
        required_capabilities: tuple[str, ...] = ("json_events", "output_schema", "read_only_planning"),
        max_review_cycles: int = 3,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValidationFailure("timeout_seconds must be positive")
        if isinstance(max_review_cycles, bool) or not isinstance(max_review_cycles, int) or max_review_cycles < 1:
            raise ValidationFailure("max_review_cycles must be a positive integer")
        self.store = store
        self.runtime = runtime
        self.timeout_seconds = timeout_seconds
        self.required_capabilities = tuple(required_capabilities)
        self.max_review_cycles = max_review_cycles
        self.approval_policies = dict(_DEFAULT_POLICIES)
        for stage, policy in (approval_policies or {}).items():
            parsed_stage = self._stage(stage)
            if parsed_stage is Stage.READY_FOR_WAVE_2:
                raise ValidationFailure("ready_for_wave_2 has no approval policy")
            try:
                self.approval_policies[parsed_stage] = (
                    policy if isinstance(policy, ApprovalPolicy) else ApprovalPolicy(policy)
                )
            except ValueError as exc:
                raise ValidationFailure(f"invalid approval policy: {policy!r}") from exc

    @staticmethod
    def _stage(value: Stage | str) -> Stage:
        try:
            return value if isinstance(value, Stage) else Stage(value)
        except ValueError as exc:
            raise ValidationFailure(f"invalid planning stage: {value!r}") from exc

    @staticmethod
    def _policy(value: Any) -> ApprovalPolicy:
        try:
            return value if isinstance(value, ApprovalPolicy) else ApprovalPolicy(value)
        except ValueError as exc:
            raise ValidationFailure(f"invalid approval policy: {value!r}") from exc

    def _configured_policies(self, snapshot: Mapping[str, Any]) -> dict[Stage, ApprovalPolicy]:
        policies = dict(self.approval_policies)
        configured = snapshot.get("approval", {})
        if isinstance(configured, Mapping):
            for stage in _STAGES:
                if stage.value in configured:
                    policies[stage] = self._policy(configured[stage.value])
        return policies

    def _feature_path(self, workflow_id: str) -> Path:
        return self.store.workspace_path / "workflows" / workflow_id / "input" / "feature-request.md"

    def _runtime_path(self, workflow_id: str, execution_id: str, name: str) -> Path:
        return self.store.workspace_path / "workflows" / workflow_id / "runtime" / execution_id / name

    @staticmethod
    def _read_feature(feature_request: str | Path, *, explicit_file: bool = False) -> bytes:
        if explicit_file or (isinstance(feature_request, Path) and feature_request.exists()):
            try:
                return Path(feature_request).read_bytes()
            except OSError as exc:
                raise ValidationFailure(f"could not read feature request: {exc}") from exc
        return str(feature_request).encode("utf-8")

    def create_workflow(
        self,
        repository_path: str | Path,
        feature_request: str | Path,
        *,
        feature_file: bool = False,
        provider: str | None = None,
        configuration_snapshot: Mapping[str, Any] | None = None,
        workflow_id: str | None = None,
    ) -> Workflow:
        """Create a workflow and retain the feature request byte-for-byte."""

        content = self._read_feature(feature_request, explicit_file=feature_file)
        selected_workflow_id = workflow_id or str(uuid.uuid4())
        workflow = self.store.create_workflow(
            repository_path,
            provider=provider or getattr(self.runtime, "provider", "provider"),
            configuration_snapshot=configuration_snapshot,
            workflow_id=selected_workflow_id,
            feature_content=content,
            feature_path=self._feature_path(selected_workflow_id),
        )
        return workflow

    def run(
        self,
        repository_path: str | Path,
        feature_request: str | Path | None = None,
        *,
        feature_file: str | Path | None = None,
        provider: str | None = None,
        configuration_snapshot: Mapping[str, Any] | None = None,
    ) -> Workflow:
        if feature_file is not None:
            if feature_request is not None:
                raise ValidationFailure("provide feature_request or feature_file, not both")
            feature_request = Path(feature_file)
            from_file = True
        else:
            if feature_request is None:
                raise ValidationFailure("feature request is required")
            from_file = False
        workflow = self.create_workflow(
            repository_path,
            feature_request,
            feature_file=from_file,
            provider=provider,
            configuration_snapshot=configuration_snapshot,
        )
        return self._drive(workflow.id)

    def run_workflow(self, *args: Any, **kwargs: Any) -> Workflow:
        return self.run(*args, **kwargs)

    def status(self, workflow_id: str) -> Workflow:
        return self.store.get_workflow(workflow_id)

    def get_status(self, workflow_id: str) -> Workflow:
        return self.status(workflow_id)

    def logs(self, workflow_id: str, *, after: int = 0):
        return self.store.list_events(workflow_id, after=after)

    def get_logs(self, workflow_id: str, *, after: int = 0):
        return self.logs(workflow_id, after=after)

    def intervene(self, workflow_id: str, task_id: str, *, reason: str, actor: str = "human") -> Workflow:
        """Record a valid task intervention without advancing task execution.

        The store enforces the persisted human-attention boundary.  Keeping
        this small delegation here ensures the CLI has no lifecycle authority.
        """
        if not workflow_id or not workflow_id.strip():
            raise ValidationFailure("workflow ID is required")
        if not task_id or not task_id.strip():
            raise ValidationFailure("task ID is required")
        if not reason or not reason.strip():
            raise ValidationFailure("intervention reason is required")
        self.store.record_intervention(workflow_id, task_id, actor=actor, reason=reason)
        return self.store.get_workflow(workflow_id)

    def _current_artifact(self, workflow: Workflow):
        if workflow.stage is Stage.READY_FOR_WAVE_2:
            raise ConflictFailure("workflow has no current planning artifact")
        artifacts = self.store.list_artifacts(workflow.id, workflow.stage)
        if not artifacts:
            raise ConflictFailure(f"no artifact is awaiting approval for {workflow.stage.value}")
        return artifacts[-1]

    def _validate_current_approval(self, workflow_id: str, artifact_id: str):
        workflow = self.store.get_workflow(workflow_id)
        if workflow.status is not WorkflowStatus.AWAITING_APPROVAL:
            raise ConflictFailure("workflow is not awaiting approval")
        artifact = self._current_artifact(workflow)
        if artifact.id != artifact_id:
            raise ConflictFailure("approval targets a stale artifact")
        if artifact.approval_state is not ApprovalState.PENDING:
            raise ConflictFailure("artifact approval has already been decided")
        return workflow, artifact

    def approve(self, workflow_id: str, artifact_id: str, actor: str = "human", reason: str | None = None) -> Workflow:
        workflow, artifact = self._validate_current_approval(workflow_id, artifact_id)
        stage, status, event_type, payload = self._approval_transition(workflow, artifact.id)
        self.store.record_approval(
            workflow_id,
            artifact_id,
            ApprovalDecision.APPROVED,
            actor=actor,
            reason=reason,
            workflow_stage=stage,
            workflow_status=status,
            transition_event_type=event_type,
            transition_payload=payload,
        )
        return self.store.get_workflow(workflow_id)

    def approve_artifact(self, *args: Any, **kwargs: Any) -> Workflow:
        return self.approve(*args, **kwargs)

    def reject(self, workflow_id: str, artifact_id: str, actor: str = "human", reason: str | None = None) -> Workflow:
        workflow, _artifact = self._validate_current_approval(workflow_id, artifact_id)
        payload = {"artifact_id": artifact_id, "classification": FailureClassification.HUMAN_REJECTION.value}
        self.store.record_approval(
            workflow_id,
            artifact_id,
            ApprovalDecision.REJECTED,
            actor=actor,
            reason=reason,
            workflow_stage=workflow.stage,
            workflow_status=WorkflowStatus.REJECTED,
            transition_event_type="stage.rejected",
            transition_payload=payload,
        )
        return self.store.get_workflow(workflow_id)

    def reject_artifact(self, *args: Any, **kwargs: Any) -> Workflow:
        return self.reject(*args, **kwargs)

    def resume(self, workflow_id: str, *, regenerate: Stage | str | None = None) -> Workflow:
        workflow = self.store.get_workflow(workflow_id)
        if workflow.stage is Stage.TASKS_READY_FOR_WAVE_REVIEW or workflow.status is WorkflowStatus.CANCELLED:
            return workflow
        if workflow.stage in (Stage.READY_FOR_WAVE_2, Stage.TASK_EXECUTION):
            if regenerate is not None:
                raise ConflictFailure("task execution does not support planning regeneration")
            return self._resume_task_execution(workflow)
        if workflow.status is WorkflowStatus.COMPLETED:
            return workflow
        if workflow.status is WorkflowStatus.AWAITING_APPROVAL:
            return self._reconcile_approval_boundary(workflow)
        pending = self.store.reconcile_operations(workflow_id)
        if pending:
            for operation in pending:
                self.store.mark_operation_unknown(
                    operation.idempotency_key,
                    detail="planning operation was incomplete at resume",
                )
            return self.store.set_workflow_state(
                workflow_id,
                status=WorkflowStatus.HUMAN_ATTENTION,
                event_type="workflow.human_attention",
                payload={"reason": "incomplete planning operation"},
            )
        if workflow.status is WorkflowStatus.HUMAN_ATTENTION:
            return workflow
        if workflow.status is WorkflowStatus.REJECTED:
            if regenerate is None:
                return workflow
            requested_stage = self._stage(regenerate)
            if requested_stage is not workflow.stage:
                raise ConflictFailure("only the current rejected stage can be regenerated")
            return self._drive(workflow_id, force_new_revision=True)
        if regenerate is not None:
            raise ConflictFailure("regeneration requires a rejected workflow")
        if workflow.status is WorkflowStatus.FAILED:
            execution = self.store.get_latest_execution(workflow_id)
            if not self._retry_eligible(execution):
                return workflow
            return self._drive(workflow_id, force_new_revision=True)
        return self._drive(workflow_id)

    def resume_workflow(self, *args: Any, **kwargs: Any) -> Workflow:
        return self.resume(*args, **kwargs)

    def _advance_after_approval(self, workflow: Workflow, artifact_id: str) -> Workflow:
        stage, status, event_type, payload = self._approval_transition(workflow, artifact_id)
        return self.store.set_workflow_state(
            workflow.id,
            stage=stage,
            status=status,
            event_type=event_type,
            payload=payload,
        )

    @staticmethod
    def _retry_eligible(execution) -> bool:
        return (
            execution is not None
            and execution.lifecycle.value == "failed"
            and execution.failure_classification in _RETRIABLE_FAILURES
        )

    @staticmethod
    def _approval_transition(
        workflow: Workflow,
        artifact_id: str,
    ) -> tuple[Stage, WorkflowStatus, str, dict[str, Any]]:
        index = _STAGES.index(workflow.stage)
        if index == len(_STAGES) - 1:
            return (
                Stage.READY_FOR_WAVE_2,
                WorkflowStatus.COMPLETED,
                "workflow.ready_for_wave_2",
                {"artifact_id": artifact_id},
            )
        return (
            _STAGES[index + 1],
            WorkflowStatus.CREATED,
            "stage.approved",
            {"artifact_id": artifact_id},
        )

    def _automatic_decision(
        self,
        workflow: Workflow,
        execution,
    ) -> bool:
        if execution is None or not isinstance(execution.terminal_result, Mapping):
            return False
        final_payload = execution.terminal_result.get("final_payload")
        if not isinstance(final_payload, Mapping):
            return False
        policy = self._configured_policies(workflow.configuration_snapshot)[workflow.stage]
        return policy is ApprovalPolicy.AUTOMATIC or (
            policy is ApprovalPolicy.CONDITIONAL
            and isinstance(final_payload.get("requires_human_approval"), bool)
            and not final_payload["requires_human_approval"]
        )

    def _reconcile_approval_boundary(self, workflow: Workflow) -> Workflow:
        artifact = self._current_artifact(workflow)
        if artifact.approval_state is ApprovalState.PENDING:
            execution = self.store.get_execution(artifact.source_execution_id) if artifact.source_execution_id else None
            if not self._automatic_decision(workflow, execution):
                return workflow
            decision = ApprovalDecision.AUTO_APPROVED
            actor = "system:approval-policy"
            reason = str(execution.terminal_result["final_payload"]["approval_reason"])
            stage, status, event_type, payload = self._approval_transition(workflow, artifact.id)
        elif artifact.approval_state in (ApprovalState.APPROVED, ApprovalState.AUTO_APPROVED):
            decision = (
                ApprovalDecision.AUTO_APPROVED
                if artifact.approval_state is ApprovalState.AUTO_APPROVED
                else ApprovalDecision.APPROVED
            )
            actor = "system:approval-recovery"
            reason = None
            stage, status, event_type, payload = self._approval_transition(workflow, artifact.id)
        elif artifact.approval_state is ApprovalState.REJECTED:
            decision = ApprovalDecision.REJECTED
            actor = "system:approval-recovery"
            reason = None
            stage, status, event_type = (
                workflow.stage,
                WorkflowStatus.REJECTED,
                "stage.rejected",
            )
            payload = {
                "artifact_id": artifact.id,
                "classification": FailureClassification.HUMAN_REJECTION.value,
            }
        else:
            return workflow
        self.store.record_approval(
            workflow.id,
            artifact.id,
            decision,
            actor=actor,
            reason=reason,
            workflow_stage=stage,
            workflow_status=status,
            transition_event_type=event_type,
            transition_payload=payload,
        )
        updated = self.store.get_workflow(workflow.id)
        if decision is ApprovalDecision.AUTO_APPROVED and updated.status is not WorkflowStatus.COMPLETED:
            return self._drive(updated.id)
        return updated

    def _approved_inputs(self, workflow: Workflow, stage: Stage) -> tuple[tuple[str, ...], tuple[str, ...]]:
        feature_path = Path(workflow.feature_input_path or self._feature_path(workflow.id))
        try:
            feature_digest = hashlib.sha256(feature_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise PersistenceFailure(f"feature request evidence is unavailable: {exc}") from exc
        if workflow.feature_input_sha256 and feature_digest != workflow.feature_input_sha256:
            raise PersistenceFailure("feature request evidence hash does not match its recorded hash")
        paths = [feature_path]
        hashes = [feature_digest]
        for prior_stage in _STAGES[:_STAGES.index(stage)]:
            artifacts = self.store.list_artifacts(workflow.id, prior_stage)
            if not artifacts or artifacts[-1].approval_state not in (ApprovalState.APPROVED, ApprovalState.AUTO_APPROVED):
                raise ConflictFailure(f"{prior_stage.value} is not approved")
            artifact = artifacts[-1]
            self.store.read_artifact(artifact.id)
            paths.append(Path(artifact.path))
            hashes.append(artifact.sha256)
        return tuple(str(path) for path in paths), tuple(hashes)

    def _prompt(self, stage: Stage, paths: tuple[str, ...], hashes: tuple[str, ...]) -> str:
        role = _ROLES[stage].value
        artifact = _ARTIFACT_LABELS[stage]
        inputs = "\n".join(f"- {path} (sha256: {digest})" for path, digest in zip(paths, hashes))
        return (
            f"Role: {role}.\n"
            f"Required artifact type: {artifact}.\n"
            "Authoritative inputs (the only planning inputs you may use):\n"
            f"{inputs}\n"
            "Output contract: return the required structured final payload with non-empty artifact_markdown, "
            "summary, requires_human_approval, and approval_reason.\n"
            "Scope boundary: produce only this Wave 1 planning artifact; do not execute tasks, tests, Git, or PR work.\n"
            "You have no authority to approve artifacts, change workflow state, select another stage, or progress the workflow."
        )

    def _revision(self, workflow: Workflow, stage: Stage, force_new: bool) -> int:
        if not force_new:
            return _STAGES.index(stage) + 1
        return max(_STAGES.index(stage) + 1, self.store.next_generation_revision(workflow.id, stage))

    def _drive(self, workflow_id: str, *, force_new_revision: bool = False) -> Workflow:
        workflow = self.store.get_workflow(workflow_id)
        if workflow.stage in (Stage.READY_FOR_WAVE_2, Stage.TASK_EXECUTION):
            return self._resume_task_execution(workflow)
        if workflow.stage is Stage.TASKS_READY_FOR_WAVE_REVIEW or workflow.status is WorkflowStatus.AWAITING_APPROVAL:
            return workflow
        if workflow.status is WorkflowStatus.HUMAN_ATTENTION:
            return workflow
        if workflow.stage not in _STAGES:
            raise ValidationFailure(f"cannot generate stage {workflow.stage.value}")
        return self._run_stage(workflow, force_new_revision=force_new_revision)

    def _run_stage(self, workflow: Workflow, *, force_new_revision: bool = False) -> Workflow:
        stage = workflow.stage
        input_paths, input_hashes = self._approved_inputs(workflow, stage)
        instruction = self._prompt(stage, input_paths, input_hashes)
        request_hash = hashlib.sha256(
            json.dumps({"stage": stage.value, "inputs": input_hashes, "instruction": instruction}, sort_keys=True).encode()
        ).hexdigest()
        capability: CapabilityReport
        try:
            capability = self.runtime.verify_planning_capabilities(workflow.repository_path)
        except Exception as exc:  # A capability check failure is never an execution success.
            return self.store.set_workflow_state(
                workflow.id,
                status=WorkflowStatus.HUMAN_ATTENTION,
                event_type="workflow.human_attention",
                payload={"reason": "runtime capability check failed", "detail": str(exc)},
            )
        report = _json_mapping(capability)
        revision = self._revision(workflow, stage, force_new_revision)
        intent = self.store.create_generation_intent(
            workflow.id,
            stage,
            request_hash=request_hash,
            provider=workflow.provider,
            role=_ROLES[stage],
            revision=revision,
            capability_report=report,
        )
        capabilities = capability.capabilities or {}
        missing_capabilities = [
            name
            for name in self.required_capabilities
            if (
                not capability.read_only_planning
                if name == "read_only_planning"
                else not bool(capabilities.get(name, False))
            )
        ]
        capability_failure = None
        if not capability.available:
            capability_failure = capability.failure_detail or "planning runtime unavailable"
        elif missing_capabilities or not capability.read_only_planning:
            missing = ", ".join(missing_capabilities) or "read_only_planning"
            capability_failure = f"planning runtime does not satisfy required capabilities: {missing}"
        if capability_failure is not None:
            classification = capability.failure_classification or FailureClassification.PROVIDER
            target_status = (
                WorkflowStatus.HUMAN_ATTENTION
                if classification is FailureClassification.AUTHENTICATION
                else WorkflowStatus.FAILED
            )
            self.store.fail_generation(intent.operation.idempotency_key, classification, capability_failure, workflow_status=target_status)
            return self.store.get_workflow(workflow.id)
        self.store.set_workflow_state(
            workflow.id,
            stage=stage,
            status=WorkflowStatus.RUNNING,
            event_type="workflow.running",
            payload={"execution_id": intent.execution.id},
        )
        execution_dir = self._runtime_path(workflow.id, intent.execution.id, "artifact.schema.json")
        final_output = execution_dir.with_name("final-output.json")
        request = PlanningExecutionRequest(
            workflow_id=workflow.id,
            execution_id=intent.execution.id,
            logical_session_id=intent.execution.session_id,
            role=_ROLES[stage],
            stage=stage,
            repository_path=workflow.repository_path,
            authoritative_input_paths=input_paths,
            authoritative_input_hashes=input_hashes,
            instruction=instruction,
            output_schema_path=str(execution_dir),
            final_output_path=str(final_output),
            timeout_seconds=self.timeout_seconds,
            required_capabilities=self.required_capabilities,
        )
        try:
            result = self.runtime.execute_planning(request)
        except Exception as exc:
            self.store.mark_operation_unknown(intent.operation.idempotency_key, detail=str(exc))
            return self.store.set_workflow_state(
                workflow.id,
                stage=stage,
                status=WorkflowStatus.HUMAN_ATTENTION,
                event_type="workflow.human_attention",
                payload={"reason": "provider operation outcome is unknown"},
            )
        self.store.start_execution(intent.execution.id, provider_execution_id=result.provider_execution_id)
        for event in result.events:
            self.store.append_event(
                workflow.id,
                f"agent.runtime.{event.type}",
                stage=stage,
                execution_id=intent.execution.id,
                payload={"provider_event_id": event.provider_event_id, "timestamp": event.timestamp, **dict(event.payload)},
            )
        if result.terminal_state is TerminalState.UNKNOWN:
            self.store.mark_operation_unknown(intent.operation.idempotency_key, detail=result.failure_detail or "unknown provider outcome")
            return self.store.set_workflow_state(
                workflow.id,
                stage=stage,
                status=WorkflowStatus.HUMAN_ATTENTION,
                event_type="workflow.human_attention",
                payload={"reason": "provider operation outcome is unknown"},
            )
        if not result.success:
            classification = result.failure_classification or FailureClassification.AGENT_EXECUTION
            target_status = (
                WorkflowStatus.HUMAN_ATTENTION
                if classification is FailureClassification.AUTHENTICATION
                else WorkflowStatus.FAILED
            )
            self.store.fail_generation(
                intent.operation.idempotency_key,
                classification,
                result.failure_detail or "planning runtime failed",
                workflow_status=target_status,
            )
            return self.store.get_workflow(workflow.id)
        payload = result.final_payload
        if not isinstance(payload, Mapping) or not self._valid_payload(payload):
            self.store.fail_generation(
                intent.operation.idempotency_key,
                FailureClassification.AGENT_EXECUTION,
                "final planning payload does not satisfy the output contract",
            )
            return self.store.get_workflow(workflow.id)
        policy = self._configured_policies(workflow.configuration_snapshot)[stage]
        artifact_path = self.store.workspace_path / "workflows" / workflow.id / "artifacts" / f"{revision:03d}-{_ARTIFACT_LABELS[stage]}.md"
        artifact = self.store.complete_generation(
            intent.operation.idempotency_key,
            content=str(payload["artifact_markdown"]),
            artifact_path=artifact_path,
            stage=stage,
            revision=revision,
            terminal_result={
                "provider": result.provider,
                "logical_session_id": result.logical_session_id,
                "provider_session_id": result.provider_session_id,
                "provider_execution_id": result.provider_execution_id,
                "final_payload": dict(payload),
                "usage": dict(result.usage),
                "metadata": dict(result.metadata),
            },
            workflow_stage=stage,
            workflow_status=WorkflowStatus.AWAITING_APPROVAL,
        )
        # Preserve the approval boundary even when policy will immediately
        # record an automatic decision in the next transaction.
        self.store.append_event(
            workflow.id,
            "approval.requested",
            stage=stage,
            artifact_id=artifact.id,
            execution_id=intent.execution.id,
            payload={"policy": policy.value},
        )
        if policy is ApprovalPolicy.REQUIRED or (
            policy is ApprovalPolicy.CONDITIONAL and bool(payload["requires_human_approval"])
        ):
            return self.store.get_workflow(workflow.id)
        approval_reason = str(payload["approval_reason"])
        stage_after_approval, status_after_approval, transition_event_type, transition_payload = self._approval_transition(
            self.store.get_workflow(workflow.id), artifact.id
        )
        self.store.record_approval(
            workflow.id,
            artifact.id,
            ApprovalDecision.AUTO_APPROVED,
            actor="system:approval-policy",
            reason=approval_reason,
            workflow_stage=stage_after_approval,
            workflow_status=status_after_approval,
            transition_event_type=transition_event_type,
            transition_payload=transition_payload,
        )
        advanced = self.store.get_workflow(workflow.id)
        if advanced.status is WorkflowStatus.COMPLETED:
            return advanced
        return self._drive(advanced.id)

    @staticmethod
    def _valid_payload(payload: Mapping[str, Any]) -> bool:
        required = {"artifact_markdown", "summary", "requires_human_approval", "approval_reason"}
        if set(payload) != required:
            return False
        return (
            isinstance(payload["artifact_markdown"], str)
            and bool(payload["artifact_markdown"].strip())
            and isinstance(payload["summary"], str)
            and isinstance(payload["requires_human_approval"], bool)
            and isinstance(payload["approval_reason"], str)
        )

    # Wave 2 task execution -------------------------------------------------

    def _max_review_cycles(self, workflow: Workflow) -> int:
        """Use a persisted policy snapshot when it is available.

        Wave 2 configuration-file migration belongs to TASK-004.  This keeps
        the orchestrator deterministic for workflows that already carry the
        approved execution policy, while retaining the constructor default for
        older Wave 1 snapshots.
        """
        execution = workflow.configuration_snapshot.get("execution", {})
        if isinstance(execution, Mapping):
            value = execution.get("max_review_cycles", self.max_review_cycles)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
        return self.max_review_cycles

    def _resume_task_execution(self, workflow: Workflow) -> Workflow:
        """Perform one persisted, permitted Wave 2 task action."""
        if workflow.stage is Stage.READY_FOR_WAVE_2:
            if workflow.status is not WorkflowStatus.COMPLETED:
                return self.store.set_workflow_state(
                    workflow.id, status=WorkflowStatus.HUMAN_ATTENTION,
                    event_type="workflow.human_attention",
                    payload={"reason": "READY_FOR_WAVE_2 workflow is not completed"},
                )
            try:
                self.store.import_task_plan(workflow.id)
            except Exception as exc:
                return self.store.set_workflow_state(
                    workflow.id, stage=Stage.READY_FOR_WAVE_2, status=WorkflowStatus.HUMAN_ATTENTION,
                    event_type="workflow.human_attention",
                    payload={"reason": "approved task-plan import failed", "detail": str(exc)},
                )
            workflow = self.store.set_workflow_state(
                workflow.id, stage=Stage.TASK_EXECUTION, status=WorkflowStatus.RUNNING,
                event_type="workflow.task_execution.started", payload={},
            )
        if workflow.stage is not Stage.TASK_EXECUTION or workflow.status is WorkflowStatus.HUMAN_ATTENTION:
            return workflow
        pending = self.store.reconcile_task_operations(workflow.id)
        if pending:
            return self.store.get_workflow(workflow.id)
        task = self.store.select_next_task(workflow.id)
        if task is None:
            # Normally complete_task_cycle performs this transition atomically.
            return self.store.set_workflow_state(
                workflow.id, stage=Stage.TASKS_READY_FOR_WAVE_REVIEW, status=WorkflowStatus.COMPLETED,
                event_type="tasks.ready_for_wave_review", payload={},
            )
        active = [item for item in self.store.list_tasks(workflow.id)
                  if item.status is TaskStatus.ACTIVE and item.id != task.id]
        if active:
            self.store.pause_task(
                task.id, classification=FailureClassification.WORKFLOW,
                detail="a higher-order task is active while a lower-order task remains unaccepted",
            )
            return self.store.get_workflow(workflow.id)
        try:
            return self._drive_task(workflow, task)
        except PersistenceFailure as exc:
            return self._pause_task(task, FailureClassification.PERSISTENCE, str(exc))
        except (ValidationFailure, ConflictFailure) as exc:
            return self._pause_task(task, FailureClassification.WORKFLOW, str(exc))

    def _drive_task(self, workflow: Workflow, task) -> Workflow:
        cycles = [cycle for cycle in self.store.list_task_cycles(task.id)
                  if cycle.review_window == task.current_review_window]
        current = cycles[-1] if cycles else None
        if current is None:
            kind = WorkKind.FIX if task.current_review_window > 1 else WorkKind.DEVELOP
            return self._dispatch_task_operation(workflow, task, 1, kind)
        if current.developer_execution_id is None:
            kind = WorkKind.FIX if current.cycle > 1 else WorkKind.DEVELOP
            return self._dispatch_task_operation(workflow, task, current.cycle, kind)
        developer_artifact = self._cycle_artifact(task.id, current.id, TaskArtifactType.DEVELOPER_RESULT)
        if developer_artifact is None:
            return self._pause_task(task, FailureClassification.AGENT_EXECUTION, "Developer execution has no result artifact")
        if current.required_test_artifact_id is None:
            payload = self._read_json_task_artifact(developer_artifact.id)
            error, canonical = self._validate_developer_payload(payload, task.required_tests, workflow.repository_path)
            if error:
                return self._pause_task(task, self._developer_payload_failure_classification(error), error)
            self.store.record_task_test_evidence(task.id, current.id, content={"test_results": canonical["test_results"]})
            return self.store.get_workflow(workflow.id)
        if current.reviewer_execution_id is None:
            return self._dispatch_task_operation(workflow, task, current.cycle, WorkKind.REVIEW, cycle_id=current.id)
        review_artifact = self._cycle_artifact(task.id, current.id, TaskArtifactType.REVIEW_RESULT)
        if review_artifact is None:
            return self._pause_task(task, FailureClassification.AGENT_EXECUTION, "Reviewer execution has no result artifact")
        payload = self._read_json_task_artifact(review_artifact.id)
        error, canonical = self._validate_reviewer_payload(payload, workflow.repository_path)
        if error:
            return self._pause_task(task, FailureClassification.AGENT_EXECUTION, error)
        if canonical["outcome"] == "PASS":
            self.store.complete_task_cycle(task.id, current.id, outcome="PASS", review_artifact_id=review_artifact.id, accept=True)
            return self.store.get_workflow(workflow.id)
        if current.cycle >= self._max_review_cycles(workflow):
            self.store.pause_task(
                task.id, classification=FailureClassification.REVIEW,
                detail="review-cycle limit reached", event_type="review.limit_reached",
            )
            return self.store.get_workflow(workflow.id)
        return self._dispatch_task_operation(workflow, task, current.cycle + 1, WorkKind.FIX)

    def _cycle_artifact(self, task_id: str, cycle_id: str, artifact_type: TaskArtifactType):
        return next((artifact for artifact in self.store.list_task_artifacts(task_id)
                     if artifact.cycle_id == cycle_id and artifact.artifact_type is artifact_type), None)

    def _pause_task(self, task, classification: FailureClassification, detail: str) -> Workflow:
        self.store.pause_task(task.id, classification=classification, detail=detail)
        return self.store.get_workflow(task.workflow_id)

    def _task_inputs(self, workflow: Workflow, task, *, reviewer: bool, cycle_id: str | None = None):
        definition = self.store.read_task_definition(task.id)
        definition_artifact = next(artifact for artifact in self.store.list_task_artifacts(task.id)
                                   if artifact.artifact_type is TaskArtifactType.DEFINITION)
        self.store.read_task_artifact(definition_artifact.id)
        paths = [definition_artifact.path]
        hashes = [definition_artifact.sha256]
        if not reviewer:
            source = self.store.get_artifact(task.source_artifact_id)
            self.store.read_artifact(source.id)
            paths.append(source.path)
            hashes.append(source.sha256)
        repository = Path(workflow.repository_path).resolve()
        for relative in task.context_paths:
            path = (repository / relative).resolve()
            try:
                path.relative_to(repository)
            except ValueError as exc:
                raise PersistenceFailure("task context path escapes the repository") from exc
            if not path.is_file():
                raise PersistenceFailure(f"task context file is unavailable: {relative}")
            paths.append(str(path))
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
        if reviewer:
            if cycle_id is None:
                raise ValidationFailure("Reviewer input requires a task cycle")
            for artifact_type in (TaskArtifactType.DEVELOPER_RESULT, TaskArtifactType.TEST_RESULT):
                artifact = self._cycle_artifact(task.id, cycle_id, artifact_type)
                if artifact is None:
                    raise PersistenceFailure("Reviewer input is missing required task evidence")
                self.store.read_task_artifact(artifact.id)
                paths.append(artifact.path)
                hashes.append(artifact.sha256)
        return definition, tuple(paths), tuple(hashes)

    def _dispatch_task_operation(self, workflow: Workflow, task, cycle: int, work_kind: WorkKind, *, cycle_id: str | None = None) -> Workflow:
        reviewer = work_kind is WorkKind.REVIEW
        try:
            definition, paths, hashes = self._task_inputs(workflow, task, reviewer=reviewer, cycle_id=cycle_id)
            required_capabilities = (("read_only", "json_events", "output_schema") if reviewer
                                     else ("workspace_write", "json_events", "output_schema"))
            capability = self.runtime.verify_capabilities(workflow.repository_path, required_capabilities)
        except PersistenceFailure as exc:
            return self._pause_task(task, FailureClassification.PERSISTENCE, f"task input verification failed: {exc}")
        except (ValidationFailure, ConflictFailure) as exc:
            return self._pause_task(task, FailureClassification.WORKFLOW, f"task input verification failed: {exc}")
        except Exception as exc:
            return self._pause_task(task, FailureClassification.PROVIDER, f"runtime preflight failed: {exc}")
        capabilities = capability.capabilities or {}
        if not capability.available or any(not capabilities.get(name, False) for name in required_capabilities):
            detail = capability.failure_detail or "runtime does not satisfy task role capabilities"
            return self._pause_task(task, capability.failure_classification or FailureClassification.PROVIDER, detail)
        instruction = self._task_instruction(task, definition, reviewer=reviewer)
        request_hash = hashlib.sha256(json.dumps({
            "task": task.definition_sha256, "window": task.current_review_window,
            "cycle": cycle, "work_kind": work_kind.value, "inputs": hashes,
            "instruction": instruction,
        }, sort_keys=True).encode()).hexdigest()
        intent = self.store.create_task_operation(
            workflow.id, task.id, review_window=task.current_review_window, cycle=cycle,
            work_kind=work_kind, request_hash=request_hash, provider=workflow.provider,
            capability_report=_json_mapping(capability),
        )
        if intent.reused:
            operation = intent.operation
            if operation.status.value == "completed":
                return self.store.get_workflow(workflow.id)
            self.store.mark_task_operation_unknown(operation.idempotency_key, detail="replayed task operation was incomplete")
            return self.store.get_workflow(workflow.id)
        continuity = (
            self._developer_continuity(task, task.current_review_window, cycle)
            if not reviewer and work_kind is WorkKind.FIX else {}
        )
        resume_provider_session_id = (
            self._developer_provider_session(task, task.current_review_window, cycle) if continuity else None
        )
        developer_session = None
        if reviewer:
            task_cycle = self.store.get_task_cycle(intent.cycle_id)
            developer_session = self.store.get_session(
                self.store.get_execution(task_cycle.developer_execution_id).session_id
            ).logical_session_id
        logical_session_id = self.store.get_session(intent.execution.session_id).logical_session_id
        request = TaskExecutionRequest(
            workflow_id=workflow.id, execution_id=intent.execution.id, logical_session_id=logical_session_id,
            role=Role.REVIEWER if reviewer else Role.DEVELOPER, stage=Stage.TASK_EXECUTION,
            repository_path=workflow.repository_path, authoritative_input_paths=paths,
            authoritative_input_hashes=hashes, instruction=instruction,
            output_schema_path=str(self._runtime_path(workflow.id, intent.execution.id, "task-output.schema.json")),
            final_output_path=str(self._runtime_path(workflow.id, intent.execution.id, "final-output.json")),
            timeout_seconds=self.timeout_seconds, required_capabilities=required_capabilities,
            work_kind=work_kind, required_test_commands=task.required_tests,
            continuity_bundle=continuity, resume_provider_session_id=resume_provider_session_id,
            developer_logical_session_id=developer_session,
        )
        try:
            result = self.runtime.execute(request)
        except Exception as exc:
            self.store.mark_task_operation_unknown(intent.operation.idempotency_key, detail=str(exc))
            return self.store.get_workflow(workflow.id)
        self.store.start_execution(intent.execution.id, provider_execution_id=result.provider_execution_id)
        for event in result.events:
            self.store.append_event(workflow.id, f"agent.runtime.{event.type}", stage=Stage.TASK_EXECUTION,
                                    execution_id=intent.execution.id,
                                    payload={"provider_event_id": event.provider_event_id, "timestamp": event.timestamp,
                                             **dict(event.payload)})
        if result.terminal_state is TerminalState.UNKNOWN:
            self.store.mark_task_operation_unknown(intent.operation.idempotency_key,
                                                   detail=result.failure_detail or "unknown provider outcome")
            return self.store.get_workflow(workflow.id)
        if not result.success:
            self.store.fail_task_operation(intent.operation.idempotency_key,
                                           result.failure_classification or FailureClassification.AGENT_EXECUTION,
                                           result.failure_detail or "task runtime failed")
            return self.store.get_workflow(workflow.id)
        if reviewer:
            error, canonical = self._validate_reviewer_payload(result.final_payload, workflow.repository_path)
            if error:
                self.store.fail_task_operation(intent.operation.idempotency_key, FailureClassification.AGENT_EXECUTION, error)
                return self.store.get_workflow(workflow.id)
            artifact = self.store.complete_task_operation(
                intent.operation.idempotency_key, content=canonical, artifact_type=TaskArtifactType.REVIEW_RESULT,
                terminal_result=self._terminal_result(result), outcome=canonical["outcome"],
            )
            if canonical["outcome"] == "PASS":
                self.store.complete_task_cycle(task.id, intent.cycle_id, outcome="PASS", review_artifact_id=artifact.id, accept=True)
            else:
                self.store.complete_task_cycle(task.id, intent.cycle_id, outcome="FIX_REQUIRED", review_artifact_id=artifact.id)
                if cycle >= self._max_review_cycles(workflow):
                    self.store.pause_task(task.id, classification=FailureClassification.REVIEW,
                                          detail="review-cycle limit reached", event_type="review.limit_reached")
            return self.store.get_workflow(workflow.id)
        error, canonical = self._validate_developer_payload(result.final_payload, task.required_tests, workflow.repository_path)
        if error:
            self.store.fail_task_operation(
                intent.operation.idempotency_key, self._developer_payload_failure_classification(error), error
            )
            return self.store.get_workflow(workflow.id)
        self.store.complete_task_operation(
            intent.operation.idempotency_key, content=canonical, artifact_type=TaskArtifactType.DEVELOPER_RESULT,
            terminal_result=self._terminal_result(result), outcome="TESTS_REPORTED",
        )
        self.store.record_task_test_evidence(task.id, intent.cycle_id, content={"test_results": canonical["test_results"]})
        return self.store.get_workflow(workflow.id)

    @staticmethod
    def _terminal_result(result) -> dict[str, Any]:
        return {"provider": result.provider, "logical_session_id": result.logical_session_id,
                "provider_session_id": result.provider_session_id,
                "provider_execution_id": result.provider_execution_id, "usage": dict(result.usage),
                "metadata": dict(result.metadata)}

    def _developer_continuity(self, task, review_window: int, cycle: int) -> dict[str, Any]:
        previous = [
            item for item in self.store.list_task_cycles(task.id)
            if (item.review_window, item.cycle) < (review_window, cycle)
        ]
        if not previous:
            return {}
        prior = previous[-1]
        bundle: dict[str, Any] = {"task_contract": task.definition}
        developer = self._cycle_artifact(task.id, prior.id, TaskArtifactType.DEVELOPER_RESULT)
        tests = self._cycle_artifact(task.id, prior.id, TaskArtifactType.TEST_RESULT)
        review = self._cycle_artifact(task.id, prior.id, TaskArtifactType.REVIEW_RESULT)
        if developer:
            bundle["developer_result"] = self._read_json_task_artifact(developer.id)
        if tests:
            bundle["test_evidence"] = self._read_json_task_artifact(tests.id)
        if review:
            bundle["review_findings"] = self._read_json_task_artifact(review.id).get("findings", [])
        return bundle

    def _developer_provider_session(self, task, review_window: int, cycle: int) -> str | None:
        """Return only recorded Developer session evidence from the prior cycle."""
        previous = [
            item for item in self.store.list_task_cycles(task.id)
            if (item.review_window, item.cycle) < (review_window, cycle)
        ]
        if not previous or previous[-1].developer_execution_id is None:
            return None
        terminal = self.store.get_execution(previous[-1].developer_execution_id).terminal_result
        if not isinstance(terminal, Mapping):
            return None
        value = terminal.get("provider_session_id")
        return value if isinstance(value, str) and value else None

    def _task_instruction(self, task, definition: str, *, reviewer: bool) -> str:
        role = "Reviewer" if reviewer else "Developer"
        boundary = (
            "Review the immutable task and supplied evidence. Do not modify files, use credentials, read unrelated tasks, "
            "or treat Developer transcripts as input. The orchestrator alone determines task order and predecessor acceptance; "
            "do not report a finding about task scheduling or proof of predecessor acceptance." if reviewer else
            "Implement only the immutable task using the supplied context. Do not read unrelated tasks, credentials, future "
            "Wave material, or perform Git delivery."
        )
        test_evidence_rule = (
            "\nDeveloper final-payload rule: test_results must contain exactly one entry for each Required tests command "
            "above, in that same order. Run each required command once for this report; do not repeat a command for draft, "
            "verification, or any other phase, and do not include additional commands in test_results."
            if not reviewer else ""
        )
        return (
            f"Role: {role}.\nImmutable task definition: {definition}\n"
            f"Required tests: {json.dumps(list(task.required_tests))}\n{boundary}{test_evidence_rule}\n"
            "You have no authority to select tasks, record a pass, change workflow state, authorize delivery, or advance the workflow. "
            "Return only the required structured final payload."
        )

    def _read_json_task_artifact(self, artifact_id: str) -> Mapping[str, Any]:
        try:
            value = json.loads(self.store.read_task_artifact_text(artifact_id))
        except (ValueError, PersistenceFailure) as exc:
            raise ValidationFailure("task evidence is not valid JSON") from exc
        if not isinstance(value, Mapping):
            raise ValidationFailure("task evidence payload must be an object")
        return value

    @staticmethod
    def _canonical_claimed_path(value: Any, repository_path: str) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        path = Path(value)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            return None
        candidate = (Path(repository_path).resolve() / path).resolve()
        try:
            candidate.relative_to(Path(repository_path).resolve())
        except ValueError:
            return None
        return candidate.relative_to(Path(repository_path).resolve()).as_posix()

    def _validate_developer_payload(self, payload: Any, required_tests: tuple[str, ...], repository_path: str):
        if not isinstance(payload, Mapping) or set(payload) != {"summary", "changed_files", "test_results"}:
            return "Developer final payload does not satisfy the output contract", None
        if not isinstance(payload["summary"], str) or not isinstance(payload["changed_files"], list) or not isinstance(payload["test_results"], list):
            return "Developer final payload has invalid field types", None
        changed = [self._canonical_claimed_path(value, repository_path) for value in payload["changed_files"]]
        if any(value is None for value in changed) or len(set(changed)) != len(changed):
            return "Developer changed-file claims are not canonical unique repository paths", None
        observed: list[dict[str, Any]] = []
        for entry in payload["test_results"]:
            if not isinstance(entry, Mapping) or set(entry) != {"command", "passed", "summary"}:
                return "Developer required-test evidence has an invalid shape", None
            if not isinstance(entry["command"], str) or not isinstance(entry["passed"], bool) or not isinstance(entry["summary"], str):
                return "Developer required-test evidence has invalid field types", None
            observed.append(dict(entry))
        commands = [entry["command"] for entry in observed]
        if (len(commands) != len(required_tests) or set(commands) != set(required_tests)
                or len(set(commands)) != len(commands) or any(not entry["passed"] for entry in observed)):
            return "Developer required-test evidence is missing, duplicate, mismatched, or failed", None
        return None, {"summary": payload["summary"], "changed_files": changed, "test_results": observed}

    @staticmethod
    def _developer_payload_failure_classification(error: str) -> FailureClassification:
        """Keep schema failures distinct from failed exact required-test claims."""
        if error == "Developer required-test evidence is missing, duplicate, mismatched, or failed":
            return FailureClassification.TEST
        return FailureClassification.AGENT_EXECUTION

    def _validate_reviewer_payload(self, payload: Any, repository_path: str):
        if not isinstance(payload, Mapping) or set(payload) != {"outcome", "summary", "findings"}:
            return "Reviewer final payload does not satisfy the output contract", None
        if payload.get("outcome") not in {"PASS", "FIX_REQUIRED"} or not isinstance(payload.get("summary"), str) or not isinstance(payload.get("findings"), list):
            return "Reviewer final payload has invalid field types", None
        findings: list[dict[str, Any]] = []
        identifiers: set[str] = set()
        for finding in payload["findings"]:
            if not isinstance(finding, Mapping) or set(finding) - {"id", "severity", "description", "path", "line"}:
                return "Reviewer finding has an invalid shape", None
            identifier, severity, description = finding.get("id"), finding.get("severity"), finding.get("description")
            if (not isinstance(identifier, str) or not identifier or identifier in identifiers or severity not in {"blocking", "non_blocking"}
                    or not isinstance(description, str)):
                return "Reviewer finding has invalid fields", None
            canonical = dict(finding)
            if canonical.get("path") is not None:
                path = self._canonical_claimed_path(canonical["path"], repository_path)
                if path is None:
                    return "Reviewer finding path is not canonical", None
                canonical["path"] = path
            if canonical.get("line") is not None and (isinstance(canonical["line"], bool) or not isinstance(canonical["line"], int) or canonical["line"] < 1):
                return "Reviewer finding line is invalid", None
            canonical = {key: value for key, value in canonical.items() if value is not None}
            identifiers.add(identifier)
            findings.append(canonical)
        blocking = [item for item in findings if item["severity"] == "blocking"]
        if payload["outcome"] == "PASS" and blocking:
            return "Reviewer PASS payload contains blocking findings", None
        if payload["outcome"] == "FIX_REQUIRED" and (not blocking or len(blocking) != len(findings)):
            return "Reviewer FIX_REQUIRED payload must contain only blocking findings", None
        return None, {"outcome": payload["outcome"], "summary": payload["summary"], "findings": findings}


Orchestrator = PlanningOrchestrator
