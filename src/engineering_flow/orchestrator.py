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
    PersistenceFailure,
    ValidationFailure,
    Workflow,
    WorkflowStatus,
)
from .runtime import AgentRuntime, CapabilityReport, PlanningExecutionRequest, PlanningExecutionResult, TerminalState
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
    ) -> None:
        if timeout_seconds <= 0:
            raise ValidationFailure("timeout_seconds must be positive")
        self.store = store
        self.runtime = runtime
        self.timeout_seconds = timeout_seconds
        self.required_capabilities = tuple(required_capabilities)
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
        if workflow.status in (WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED):
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
        if workflow.stage is Stage.READY_FOR_WAVE_2 or workflow.status is WorkflowStatus.AWAITING_APPROVAL:
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


Orchestrator = PlanningOrchestrator
