"""Orchestrator-owned Wave 1 planning lifecycle."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, is_dataclass
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
)
from .runtime import (
    AgentRuntime,
    CapabilityReport,
    PlanningExecutionRequest,
    PlanningExecutionResult,
    TaskExecutionRequest,
    TerminalState,
)
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


def _json_mapping(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


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
            "or treat Developer transcripts as input." if reviewer else
            "Implement only the immutable task using the supplied context. Do not read unrelated tasks, credentials, future "
            "Wave material, or perform Git delivery."
        )
        return (
            f"Role: {role}.\nImmutable task definition: {definition}\n"
            f"Required tests: {json.dumps(list(task.required_tests))}\n{boundary}\n"
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
            if "path" in canonical:
                path = self._canonical_claimed_path(canonical["path"], repository_path)
                if path is None:
                    return "Reviewer finding path is not canonical", None
                canonical["path"] = path
            if "line" in canonical and (isinstance(canonical["line"], bool) or not isinstance(canonical["line"], int) or canonical["line"] < 1):
                return "Reviewer finding line is invalid", None
            identifiers.add(identifier)
            findings.append(canonical)
        blocking = [item for item in findings if item["severity"] == "blocking"]
        if payload["outcome"] == "PASS" and blocking:
            return "Reviewer PASS payload contains blocking findings", None
        if payload["outcome"] == "FIX_REQUIRED" and (not blocking or len(blocking) != len(findings)):
            return "Reviewer FIX_REQUIRED payload must contain only blocking findings", None
        return None, {"outcome": payload["outcome"], "summary": payload["summary"], "findings": findings}


Orchestrator = PlanningOrchestrator
