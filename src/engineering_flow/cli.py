"""The thin command-line adapter for the Wave 1 planning control plane."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .codex_cli import CodexCliRuntime
from .config import (
    DATABASE_FILENAME,
    INITIAL_CONFIG,
    FlowConfig,
    application_owned_path,
    application_path,
    is_git_worktree,
    load_config,
)
from .domain import (
    ConflictFailure,
    DomainFailure,
    FailureClassification,
    NotFoundFailure,
    PersistenceFailure,
    Stage,
    ValidationFailure,
    Workflow,
    WorkflowStatus,
    LifecycleVersion,
)
from .orchestrator import (CodexImplementationWriter, ImplementationAttemptOrchestrator,
                           IntakeOrchestrator, PlanningOrchestrator, V2HappyPathCoordinator,
                           V2PlanOrchestrator)
from .presentation import (OutputMode, create_progress_renderer, interactive_prompt_eligible,
                           prompt_for_clarification, prompt_for_plan_decision,
                           prompt_for_implementation_start,
                           render_clarification_recovery_instruction, render_plan_decision_result,
                           render_plan_revision_limit_instruction, render_recovery_instruction, render_result)
from .sanitization import sanitize_payload, sanitize_text
from .store import WorkflowStore


EXIT_SUCCESS = 0
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_PROVIDER = 5
EXIT_AUTHENTICATION = 6
EXIT_PERSISTENCE = 7
EXIT_HUMAN_ATTENTION = 8
EXIT_INTERRUPTED = 130
MAX_INTAKE_CALLS_PER_INVOCATION = 5
MAX_PLANNER_CALLS_PER_INVOCATION = 3

ERROR_CODES = {
    "usage": "usage",
    "config": "config",
    "not_found": "not_found",
    "conflict": "conflict",
    FailureClassification.WORKFLOW.value: FailureClassification.WORKFLOW.value,
    FailureClassification.PROVIDER.value: FailureClassification.PROVIDER.value,
    FailureClassification.AGENT_EXECUTION.value: FailureClassification.AGENT_EXECUTION.value,
    FailureClassification.AUTHENTICATION.value: FailureClassification.AUTHENTICATION.value,
    FailureClassification.TOOL.value: FailureClassification.TOOL.value,
    FailureClassification.HUMAN_REJECTION.value: FailureClassification.HUMAN_REJECTION.value,
    FailureClassification.PERSISTENCE.value: FailureClassification.PERSISTENCE.value,
    "human_attention": "human_attention",
}


class _ParserUsageError(Exception):
    """An argparse usage failure that main() can render consistently."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ParserUsageError(message)


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="engineering-flow")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="initialize a repository-local workflow workspace")
    init.add_argument("--repo", required=True, metavar="PATH")

    run = commands.add_parser("run", help="start a planning workflow")
    run.add_argument("--repo", default=".", metavar="PATH")
    input_mode = run.add_mutually_exclusive_group(required=True)
    input_mode.add_argument("--feature-file", metavar="PATH")
    input_mode.add_argument("--request", metavar="TEXT")
    run.add_argument("--provider", choices=("codex-cli",), default="codex-cli")
    run_output = run.add_mutually_exclusive_group()
    run_output.add_argument("--json", action="store_true", dest="json_output")
    run_output.add_argument("--verbose", action="store_true")
    run.add_argument("--no-color", action="store_true")

    for name in ("status", "approve", "reject", "resume", "intervene", "logs", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("--repo", default=".", metavar="PATH")
        command.add_argument("--workflow", required=name in ("intervene", "logs"), metavar="ID")
        output = command.add_mutually_exclusive_group()
        output.add_argument("--json", action="store_true", dest="json_output")
        output.add_argument("--verbose", action="store_true")
        command.add_argument("--no-color", action="store_true")
        if name in ("approve", "reject"):
            command.add_argument("--artifact", required=False, metavar="ID")
        if name in ("approve", "reject"):
            command.add_argument("--reason", required=name == "reject", metavar="TEXT")
        if name == "resume":
            command.add_argument("--regenerate", choices=("prd", "techspec", "task-plan"))
            inputs = command.add_mutually_exclusive_group()
            inputs.add_argument("--answer", metavar="TEXT")
            inputs.add_argument("--feedback", metavar="TEXT")
        if name == "intervene":
            command.add_argument("--task", required=True, metavar="ID")
            command.add_argument("--reason", required=True, metavar="TEXT")
        if name == "logs":
            command.add_argument("--after", type=_nonnegative_int, default=0, metavar="SEQUENCE")
    return parser


def _workflow_payload(store: WorkflowStore, workflow: Workflow, *, plan_projection: Any = None) -> dict[str, Any]:
    artifacts = []
    for artifact in store.list_artifacts(workflow.id):
        # Reading is deliberate: status and logs must detect tampering without
        # changing the authoritative workflow state.
        store.read_artifact(artifact.id)
        artifacts.append({
            "id": artifact.id,
            "stage": artifact.stage.value,
            "revision": artifact.revision,
            "path": artifact.path,
            "sha256": artifact.sha256,
            "source_execution_id": artifact.source_execution_id,
            "approval_state": artifact.approval_state.value,
            "created_at": artifact.created_at,
        })
    latest = store.get_latest_execution(workflow.id)
    execution = None
    if latest is not None:
        execution = {
            "id": latest.id,
            "session_id": latest.session_id,
            "role": latest.role.value,
            "provider_execution_id": latest.provider_execution_id,
            "request_hash": latest.request_hash,
            "lifecycle": latest.lifecycle.value,
            "failure_classification": latest.failure_classification.value if latest.failure_classification else None,
            "failure_detail": latest.failure_detail,
            "created_at": latest.created_at,
            "updated_at": latest.updated_at,
        }
    tasks = [_task_payload(store, task) for task in store.list_tasks(workflow.id)]
    active_task = next((task for task in tasks if task["status"] == "active"), None)
    if active_task is None:
        active_task = next((task for task in tasks if task["status"] == "human_attention"), None)
    return {
        "workflow_id": workflow.id,
        "repository_path": workflow.repository_path,
        "provider": workflow.provider,
        "status": workflow.status.value,
        "stage": workflow.stage.value,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
        "current_artifact_revision": workflow.current_artifact_revision,
        "artifacts": artifacts,
        "latest_execution": execution,
        "tasks": tasks,
        "active_task": active_task,
        "lifecycle_version": workflow.lifecycle_version.value,
        **(_intake_payload(store, workflow) if workflow.lifecycle_version is LifecycleVersion.V2 else {}),
        **(_plan_payload(store, workflow, projection=plan_projection) if workflow.lifecycle_version is LifecycleVersion.V2 else {}),
    }


def _intake_payload(store: WorkflowStore, workflow: Workflow) -> dict[str, Any]:
    artifacts = store.list_artifacts(workflow.id, Stage.INTAKE)
    artifact = artifacts[-1] if artifacts else None
    contract: dict[str, Any] = {}
    if artifact:
        parsed = json.loads(store.read_artifact(artifact.id))
        contract = parsed if isinstance(parsed, dict) else {}
    feature = contract.get("feature", {}) if isinstance(contract.get("feature"), dict) else {}
    records = store.list_clarifications(workflow.id)
    active = store.get_active_clarification(workflow.id)
    clarification_payload = [{"id": item.id, "sequence": item.sequence,
                              "source_feature_contract_artifact_id": item.source_feature_contract_artifact_id,
                              "question": item.question, "answer": item.answer, "actor": item.actor,
                              "result_feature_contract_artifact_id": item.result_feature_contract_artifact_id,
                              "created_at": item.created_at, "answered_at": item.answered_at,
                              "completed_at": item.completed_at} for item in records]
    return {"intake": {"outcome": contract.get("outcome"), "feature_contract_artifact_id": artifact.id if artifact else None,
                       "open_questions": feature.get("open_questions", []), "clarifications": clarification_payload,
                       "current_clarification": ({"id": active.id, "sequence": active.sequence, "question": active.question,
                                                  "answered": active.answer is not None} if active else None)}}


def _plan_payload(store: WorkflowStore, workflow: Workflow, *, projection: Any = None) -> dict[str, Any]:
    artifacts = store.list_artifacts(workflow.id, Stage.PLAN)
    if not artifacts:
        return {"plan": None}
    artifact = artifacts[-1]
    plan = json.loads(store.read_artifact(artifact.id))
    # Plan task contracts stay immutable. Operational task states and attempts
    # are projected alongside them for every V2 stop boundary.
    states = {
        state.task_contract_id: state.status.value
        for state in store.list_task_implementation_states(workflow.id, artifact.id)
    }
    verification_attempts = store.list_verification_attempt_projections(workflow.id)
    verification_by_task = {
        attempt["task_contract_id"]: attempt for attempt in verification_attempts
    }
    raw_plan = plan.get("plan") if isinstance(plan, dict) else None
    raw_tasks = raw_plan.get("tasks") if isinstance(raw_plan, dict) else None
    if isinstance(raw_tasks, list):
        for task in raw_tasks:
            if isinstance(task, dict) and isinstance(task.get("id"), str):
                task["implementation_status"] = states.get(task["id"], "pending")
                verification = verification_by_task.get(task["id"])
                task["verification_status"] = ("not_run" if verification is None
                    else verification["classification"] or verification["recovery_classification"]
                    or verification["status"])
    attempts = store.list_implementation_attempts(workflow.id)
    latest_attempt = attempts[-1] if attempts else None
    if latest_attempt and isinstance(latest_attempt.get("changed_paths_json"), str):
        try:
            latest_attempt["changed_paths"] = json.loads(latest_attempt.pop("changed_paths_json"))
        except json.JSONDecodeError:
            latest_attempt["changed_paths"] = []
    lease = store.active_implementation_lease(workflow.id)
    approval = store.get_approval_for_artifact(artifact.id)
    projection_data: dict[str, Any] = {}
    if projection is not None:
        path = Path(projection.path)
        try:
            display_path = str(path.relative_to(Path(workflow.repository_path).resolve()))
        except ValueError:
            display_path = str(path)
        projection_data = {
            "plan_markdown_path": display_path,
            "projection_state": projection.state,
            "projection_error": projection.error,
        }
    changes = store.list_plan_change_requests(workflow.id)
    return {"plan": {"artifact_id": artifact.id, "sha256": artifact.sha256, "revision": artifact.revision,
                      "approval_state": artifact.approval_state.value,
                      "decision_reason": approval.reason if approval else None,
                      "approval": ({"id": approval.id, "decision": approval.decision.value,
                                    "actor": approval.actor, "reason": approval.reason,
                                    "created_at": approval.created_at}
                                   if approval else None),
                      "change_requests": [{"id": item.id, "sequence": item.sequence,
                                           "target_plan_artifact_id": item.target_plan_artifact_id,
                                           "replacement_plan_artifact_id": item.replacement_plan_artifact_id,
                                           "actor": item.actor, "created_at": item.created_at,
                                           "completed_at": item.completed_at} for item in changes],
                      "implementation": {
                          "attempt_count": len(attempts),
                          "latest_attempt": latest_attempt,
                          "active_writer": (None if lease is None else {
                              "task_id": lease.get("task_contract_id"),
                              "attempt_id": lease.get("attempt_id"),
                              "lease_held": True,
                          }),
                          "verification_status": ("not_run" if not verification_attempts
                              else verification_attempts[-1]["classification"]
                              or verification_attempts[-1]["recovery_classification"]
                              or verification_attempts[-1]["status"]),
                          "verification": {
                              "attempt_count": len(verification_attempts),
                              "latest_attempt": (verification_attempts[-1]
                                  if verification_attempts else None),
                          },
                      },
                      **projection_data, **plan}}


def _task_evidence(store: WorkflowStore, artifact_id: str | None, *, kind: str) -> dict[str, Any] | None:
    """Project verified task evidence without exposing provider prose."""
    if artifact_id is None:
        return None
    try:
        content = json.loads(store.read_task_artifact_text(artifact_id))
    except (TypeError, ValueError):
        return {"result": "invalid"}
    if not isinstance(content, dict):
        return {"result": "invalid"}
    if kind == "test":
        results = content.get("test_results")
        if not isinstance(results, list) or not results or not all(isinstance(item, dict) for item in results):
            return {"result": "invalid"}
        passed = all(item.get("passed") is True for item in results)
        return {"result": "pass" if passed else "fail", "passed": passed}
    outcome = content.get("outcome")
    return ({"result": outcome, "outcome": outcome}
            if outcome in {"PASS", "FIX_REQUIRED"} else {"result": "invalid"})


def _task_payload(store: WorkflowStore, task: Any) -> dict[str, Any]:
    # Definitions are immutable workflow evidence just like result artifacts.
    # Verify their stored hash before projecting the persisted lifecycle state.
    store.read_task_definition(task.id)
    cycles = store.list_task_cycles(task.id)
    latest = cycles[-1] if cycles else None
    latest_test = _task_evidence(store, latest.required_test_artifact_id if latest else None, kind="test")
    latest_review = _task_evidence(store, latest.review_artifact_id if latest else None, kind="review")
    return {
        "id": task.id,
        "ordinal": task.ordinal,
        "key": task.key,
        "title": task.title,
        "status": task.status.value,
        "review_window": task.current_review_window,
        "cycle": task.current_cycle,
        "latest_required_test": latest_test,
        "latest_review": latest_review,
        "intervention_required": task.status.value == "human_attention",
    }


def _event_payload(event: Any) -> dict[str, Any]:
    payload = dict(event.payload)
    payload = _recovery_event_payload(event.type, payload)
    return {
        "sequence": event.sequence,
        "type": event.type,
        "stage": event.stage.value if event.stage else None,
        "artifact_id": event.artifact_id,
        "execution_id": event.execution_id,
        "task_id": payload.get("task_id"),
        "cycle_id": payload.get("cycle_id"),
        "review_window": payload.get("review_window"),
        "cycle": payload.get("cycle"),
        "payload": payload,
        "created_at": event.created_at,
    }


def _recovery_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Expose only a fixed safe summary for verification recovery evidence.

    Recovery payloads deliberately retain raw process and repository evidence
    durably.  Logs are a separate trust boundary: unknown fields and nested
    evidence never cross it.  Non-recovery events retain their existing
    presentation unchanged.
    """
    recovery_types = {
        "verification.recovery.ambiguous_context": ("state_inconsistent", True),
        "verification.recovery.inconsistent_lease": ("state_inconsistent", True),
        "verification.recovery.live_owned": ("process_alive_owned", True),
    }
    safe_classifications = {
        "ambiguous_ownership", "different_boot", "different_machine",
        "identity_mismatch", "incomplete_identity", "inspection_failure",
        "pid_reused", "process_dead_changed", "process_dead_unchanged",
        "process_alive_owned", "repository_inspection_failure", "state_inconsistent",
        "verification_unknown",
    }
    classification: str | None = None
    lease_held: bool | None = None
    if event_type in recovery_types:
        classification, lease_held = recovery_types[event_type]
    elif event_type == "verification.recovery.unknown_retained":
        observation = payload.get("observation")
        if isinstance(observation, dict):
            observed = observation.get("classification")
            if observed in safe_classifications:
                classification = observed
        lease_held = True
    elif event_type == "verification.attempt.terminal" and "recovery" in payload:
        if payload.get("outcome") == "interrupted_unchanged":
            classification = "process_dead_unchanged"
            lease_held = False
    else:
        # A future recovery event has no approved presentation contract yet.
        # Its durable payload must therefore remain private by default.
        return {} if event_type.startswith("verification.recovery.") else payload

    safe: dict[str, Any] = {"lease_held": lease_held}
    attempt_id = payload.get("attempt_id")
    if isinstance(attempt_id, str):
        safe["attempt_id"] = attempt_id
    if classification is not None:
        safe["classification"] = classification
    return safe


def _result_document(command: str, *, workflow: Workflow | None = None, error_code: str | None = None,
                     message: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
    document: dict[str, Any] = {
        "command_result": "success" if error_code is None else "error",
        "workflow_id": workflow.id if workflow else None,
        "status": workflow.status.value if workflow else None,
        "stage": workflow.stage.value if workflow else None,
        "error_code": error_code,
        "command": command,
    }
    if message:
        document["message"] = sanitize_text(message)
    if data:
        document.update(data)
    return sanitize_payload(document)


def _failure_for_workflow(store: WorkflowStore, workflow: Workflow) -> tuple[str | None, int]:
    if workflow.status is WorkflowStatus.HUMAN_ATTENTION:
        latest = store.get_latest_execution(workflow.id)
        if latest and latest.failure_classification is FailureClassification.AUTHENTICATION:
            return ERROR_CODES[FailureClassification.AUTHENTICATION.value], EXIT_AUTHENTICATION
        return ERROR_CODES["human_attention"], EXIT_HUMAN_ATTENTION
    if workflow.status is WorkflowStatus.IMPLEMENTATION_FAILED:
        return ERROR_CODES[FailureClassification.AGENT_EXECUTION.value], EXIT_PROVIDER
    if workflow.status is not WorkflowStatus.FAILED:
        return None, EXIT_SUCCESS
    latest = store.get_latest_execution(workflow.id)
    classification = latest.failure_classification.value if latest and latest.failure_classification else "workflow"
    if classification == FailureClassification.AUTHENTICATION.value:
        return ERROR_CODES[classification], EXIT_AUTHENTICATION
    if classification in (FailureClassification.PROVIDER.value, FailureClassification.AGENT_EXECUTION.value,
                          FailureClassification.TOOL.value):
        return ERROR_CODES[classification], EXIT_PROVIDER
    if classification == FailureClassification.PERSISTENCE.value:
        return ERROR_CODES[classification], EXIT_PERSISTENCE
    return ERROR_CODES.get(classification, ERROR_CODES["workflow"]), EXIT_USAGE


def _error_code(exc: BaseException, *, config_phase: bool = False) -> tuple[str, int]:
    if isinstance(exc, NotFoundFailure):
        return ERROR_CODES["not_found"], EXIT_NOT_FOUND
    if isinstance(exc, ConflictFailure):
        return ERROR_CODES["conflict"], EXIT_CONFLICT
    if isinstance(exc, PersistenceFailure) or isinstance(exc, sqlite3.Error):
        return ERROR_CODES[FailureClassification.PERSISTENCE.value], EXIT_PERSISTENCE
    if isinstance(exc, (OSError, UnicodeError, ValueError)):
        return ERROR_CODES[FailureClassification.PERSISTENCE.value], EXIT_PERSISTENCE
    if config_phase or isinstance(exc, ValidationFailure):
        return ERROR_CODES["config"], EXIT_USAGE
    return ERROR_CODES[FailureClassification.WORKFLOW.value], EXIT_USAGE


def _validate_feature_file(value: str | Path) -> Path:
    try:
        path = Path(value).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValidationFailure("invalid feature-file path") from exc
    if not path.is_file():
        raise ValidationFailure(f"feature file not found: {path}")
    return path


def _services(config: FlowConfig) -> tuple[WorkflowStore, PlanningOrchestrator, IntakeOrchestrator, V2PlanOrchestrator]:
    store = WorkflowStore(config.database_path)
    runtime = CodexCliRuntime(
        config.provider_command,
        provider=config.provider_name,
        timeout_seconds=config.timeout_seconds,
        allow_read_only_planning=config.allow_read_only_planning,
        allow_workspace_write=config.allow_workspace_write_development,
    )
    orchestrator = PlanningOrchestrator(
        store,
        runtime,
        approval_policies=config.approval_policies,
        timeout_seconds=config.timeout_seconds,
        max_review_cycles=config.max_review_cycles,
    )
    return store, orchestrator, IntakeOrchestrator(store, runtime, timeout_seconds=config.timeout_seconds), V2PlanOrchestrator(store, runtime, timeout_seconds=config.timeout_seconds)


def _close_progress(progress_sink: Any) -> None:
    close = getattr(progress_sink, "close", None)
    if callable(close):
        close()


def _continue_approved_implementation(
    workflow_id: str,
    *,
    store: WorkflowStore,
    config: FlowConfig,
    runtime: Any,
    progress_sink: Any,
) -> Workflow:
    """Invoke the sole MDS #3 implementation gateway once, then reload state.

    Selection, authority validation, leases, repository safety, recovery, and
    result classification deliberately remain owned by the orchestrator.
    """

    writer = CodexImplementationWriter(runtime=runtime, config=config, progress_sink=progress_sink)
    ImplementationAttemptOrchestrator(store, writer, progress_sink=progress_sink).run_once(workflow_id)
    return store.get_workflow(workflow_id)


def _continue_v2_clarifications(
    workflow: Workflow,
    *,
    intake: IntakeOrchestrator,
    plan: V2PlanOrchestrator,
    progress_sink: Any,
    interactive: bool,
    initial_intake_calls: int = 0,
    no_color: bool = False,
) -> tuple[Workflow, bool]:
    """Coordinate terminal interaction around persisted Step 1 boundaries.

    This function deliberately owns no answer state.  Each turn resolves the
    current clarification from SQLite, sends a single submitted answer through
    ``resume_answer()``, and then reads persisted state again.
    """

    calls = initial_intake_calls
    coordinator = V2HappyPathCoordinator(intake, plan)
    while workflow.stage is Stage.INTAKE:
        if workflow.status is WorkflowStatus.READY:
            return coordinator.continue_ready_to_plan(workflow.id, progress_sink=progress_sink), False
        if workflow.status not in {WorkflowStatus.NEEDS_CLARIFICATION, WorkflowStatus.FAILED, WorkflowStatus.HUMAN_ATTENTION}:
            return workflow, False
        current = intake.store.get_active_clarification(workflow.id)
        if current is None:
            return workflow, False
        if current.answer is not None:
            if calls >= MAX_INTAKE_CALLS_PER_INVOCATION:
                return workflow, False
            workflow = intake.resume_answer(workflow.id, progress_sink=progress_sink)
            calls += 1
            continue
        if not interactive or calls >= MAX_INTAKE_CALLS_PER_INVOCATION:
            return workflow, False
        _close_progress(progress_sink)
        answer = prompt_for_clarification(current.question, sys.stdin, sys.stdout, no_color=no_color)
        if answer is None:
            render_clarification_recovery_instruction(sys.stdout, no_color=no_color)
            return workflow, True
        # This is the sole answer operation; it persists before dispatching
        # the provider and is identical to explicit ``resume --answer``.
        workflow = intake.resume_answer(workflow.id, answer, progress_sink=progress_sink)
        calls += 1
    return workflow, False


def _interactive_v2_plan_loop(
    workflow: Workflow,
    *,
    command: str,
    store: WorkflowStore,
    plan: V2PlanOrchestrator,
    progress_sink: Any,
    planner_calls: int,
    verbose: bool,
    no_color: bool,
) -> tuple[Workflow, bool]:
    """Drive only the human Plan boundary using persisted Step 3 authority.

    The caller supplies calls already dispatched in this CLI invocation.  The
    loop deliberately resolves the pending artifact afresh before *every*
    prompt, so replacement identity never comes from process-local state.
    """

    while workflow.stage is Stage.PLAN and workflow.status is WorkflowStatus.AWAITING_APPROVAL:
        projection = plan.inspect_plan_projection(workflow.id, repair=True)
        payload = _workflow_payload(store, workflow, plan_projection=projection)
        document = _result_document(command, workflow=workflow, data=payload)
        if projection.error:
            document["recovery_instruction"] = True
            render_result(document, mode=OutputMode.VERBOSE if verbose else OutputMode.HUMAN,
                          stream=sys.stdout, no_color=no_color)
            return workflow, True
        render_result(document, mode=OutputMode.VERBOSE if verbose else OutputMode.HUMAN,
                      stream=sys.stdout, no_color=no_color)
        artifact_id = plan.resolve_current_pending_plan_artifact(workflow.id)
        decision = prompt_for_plan_decision(
            sys.stdin, sys.stdout, no_color=no_color,
            revised=payload.get("plan", {}).get("revision", 1) > 1,
            allow_changes=planner_calls < MAX_PLANNER_CALLS_PER_INVOCATION,
        )
        if decision is None:
            render_recovery_instruction(sys.stdout, no_color=no_color)
            return workflow, True
        action, feedback = decision
        if action == "approve":
            workflow = plan.approve(workflow.id, artifact_id)
            render_plan_decision_result(sys.stdout, "approve", no_color=no_color)
            return workflow, True
        # Do not collect input that cannot be dispatched in this invocation.
        # The choice itself is intentionally non-durable until feedback is
        # accepted by the Step 3 transaction.
        if action == "changes_unavailable" or planner_calls >= MAX_PLANNER_CALLS_PER_INVOCATION:
            render_plan_revision_limit_instruction(sys.stdout, no_color=no_color)
            return workflow, True
        workflow = plan.request_changes(workflow.id, feedback or "", progress_sink=progress_sink)
        planner_calls += 1
        if workflow.status is not WorkflowStatus.AWAITING_APPROVAL:
            return workflow, False
    return workflow, False


def _resolve_v2_workflow(store: WorkflowStore, explicit_workflow_id: str | None) -> tuple[Workflow, bool]:
    """Resolve explicit V2 context or the persisted selected V2 workflow.

    The boolean records explicit use; selection is deliberately updated only
    after the command itself completes successfully.
    """
    if explicit_workflow_id is not None:
        try:
            uuid.UUID(explicit_workflow_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValidationFailure("invalid workflow id") from exc
        workflow = store.get_workflow(explicit_workflow_id)
        _require_local_workflow(store, workflow)
        if workflow.lifecycle_version is not LifecycleVersion.V2:
            return workflow, True
        return workflow, True

    selected_workflow_id = store.get_selected_workflow_id()
    if selected_workflow_id is None:
        raise NotFoundFailure(
            "No workflow is selected for this repository. Run a V2 workflow or specify --workflow <id>."
        )
    try:
        uuid.UUID(selected_workflow_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PersistenceFailure("selected workflow context contains an invalid workflow id") from exc
    try:
        workflow = store.get_workflow(selected_workflow_id)
    except NotFoundFailure as exc:
        raise PersistenceFailure("selected workflow context refers to a missing workflow") from exc
    _require_local_workflow(store, workflow)
    if workflow.lifecycle_version is not LifecycleVersion.V2:
        raise ConflictFailure("selected workflow context does not refer to a V2 workflow")
    return workflow, False


def _require_local_workflow(store: WorkflowStore, workflow: Workflow) -> None:
    """Reject a copied/cross-repository workflow record before it becomes context."""
    try:
        repository_path = Path(workflow.repository_path).resolve()
        database_repository = store.workspace_path.parent.resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PersistenceFailure("workflow repository context is invalid") from exc
    if repository_path != database_repository:
        raise ConflictFailure("workflow does not belong to this repository context")


def _init(repository_value: str) -> dict[str, Any]:
    try:
        repository = Path(repository_value).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValidationFailure("invalid repository path") from exc
    if not repository.is_dir() or not is_git_worktree(repository):
        raise ValidationFailure(f"target repository is not a Git worktree: {repository}")
    application = application_path(repository)
    application.mkdir(parents=True, exist_ok=True)
    config_path = application_owned_path(application, "config.toml", "configuration")
    database_path = application_owned_path(application, DATABASE_FILENAME, "database")
    if config_path.exists():
        try:
            if config_path.read_text(encoding="utf-8") != INITIAL_CONFIG:
                raise ConflictFailure("configuration file already exists with different content")
        except OSError as exc:
            raise PersistenceFailure(f"could not read configuration: {exc}") from exc
    else:
        try:
            config_path.write_text(INITIAL_CONFIG, encoding="utf-8", newline="")
        except OSError as exc:
            raise PersistenceFailure(f"could not create configuration: {exc}") from exc
    try:
        gitignore = (repository / ".gitignore").resolve()
        gitignore.relative_to(repository)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValidationFailure(".gitignore path escapes the repository") from exc
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        entries = {line.strip() for line in existing.splitlines()}
        if ".engineering-flow/" not in entries:
            suffix = "" if not existing or existing.endswith(("\n", "\r")) else "\n"
            gitignore.write_text(existing + suffix + ".engineering-flow/\n", encoding="utf-8", newline="")
    except OSError as exc:
        raise PersistenceFailure(f"could not update .gitignore: {exc}") from exc
    store = WorkflowStore(database_path)
    store.close()
    return _result_document("init", data={"repository_path": str(repository), "application_path": str(application)})


def _run_command(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    command = args.command
    if command == "init":
        return _init(args.repo), EXIT_SUCCESS
    config = load_config(args.repo)
    store, orchestrator, intake_orchestrator, plan_orchestrator = _services(config)
    try:
        eof_at_clarification = False
        def payload_for(workflow: Workflow) -> dict[str, Any]:
            projection = None
            if (workflow.lifecycle_version is LifecycleVersion.V2 and workflow.stage is Stage.PLAN
                    and store.list_artifacts(workflow.id, Stage.PLAN)):
                # JSON is strictly observation-only. Human commands may repair
                # only this derived cache after canonical JSON is verified.
                projection = plan_orchestrator.inspect_plan_projection(
                    workflow.id, repair=not args.json_output
                )
            return _workflow_payload(store, workflow, plan_projection=projection)

        if command == "run":
            if args.request is not None:
                progress_sink = (None if args.json_output else create_progress_renderer(
                    sys.stderr, no_color=args.no_color,
                ))
                workflow = V2HappyPathCoordinator(intake_orchestrator, plan_orchestrator).run(
                    config.repository_path, args.request, provider=config.provider_name,
                    configuration_snapshot=config.snapshot,
                    progress_sink=progress_sink,
                )
                if not args.json_output and workflow.stage is Stage.INTAKE:
                    workflow, eof_at_clarification = _continue_v2_clarifications(
                        workflow, intake=intake_orchestrator, plan=plan_orchestrator,
                        progress_sink=progress_sink,
                        interactive=interactive_prompt_eligible(sys.stdin, sys.stdout, sys.stderr),
                        initial_intake_calls=1, no_color=args.no_color,
                    )
                payload = payload_for(workflow)
                code, exit_code = _failure_for_workflow(store, workflow)
                document = _result_document(command, workflow=workflow, error_code=code, data=payload)
                if eof_at_clarification:
                    document["_already_rendered"] = True
                    return document, exit_code
                if args.json_output or workflow.stage is not Stage.PLAN or workflow.status is not WorkflowStatus.AWAITING_APPROVAL:
                    return document, exit_code

                if not interactive_prompt_eligible(sys.stdin, sys.stdout, sys.stderr):
                    document["recovery_instruction"] = True
                    return document, exit_code
                workflow, rendered = _interactive_v2_plan_loop(
                    workflow, command=command, store=store, plan=plan_orchestrator,
                    progress_sink=progress_sink, planner_calls=1, verbose=args.verbose,
                    no_color=args.no_color,
                )
                if workflow.status is WorkflowStatus.PLAN_APPROVED:
                    # The prompt-local approval decision is never authority.
                    # Reload and validate the durable Plan before offering the
                    # optional, one-shot continuation.
                    workflow = store.get_workflow(workflow.id)
                    if (workflow.lifecycle_version is LifecycleVersion.V2
                            and workflow.stage is Stage.PLAN
                            and workflow.status is WorkflowStatus.PLAN_APPROVED):
                        store.load_approved_v2_plan_authority(workflow.id)
                        if prompt_for_implementation_start(sys.stdin, sys.stdout, no_color=args.no_color):
                            progress_sink = create_progress_renderer(sys.stderr, no_color=args.no_color)
                            workflow = _continue_approved_implementation(
                                workflow.id, store=store, config=config,
                                runtime=plan_orchestrator.runtime, progress_sink=progress_sink,
                            )
                            rendered = False
                # Inline continuation is the same implementation boundary as
                # ``resume``.  Classify its reloaded terminal state through
                # the shared workflow classifier so writer failures and
                # uncertain outcomes cannot be reported as command success.
                code, exit_code = _failure_for_workflow(store, workflow)
                result = _result_document(
                    command, workflow=workflow, error_code=code,
                    data=_workflow_payload(store, workflow),
                )
                if rendered:
                    result["_already_rendered"] = True
                return result, exit_code
            feature_file = _validate_feature_file(args.feature_file)
            workflow = orchestrator.run(config.repository_path, feature_file=feature_file, provider=config.provider_name, configuration_snapshot=config.snapshot)
        elif command == "status":
            workflow, explicit = _resolve_v2_workflow(store, args.workflow)
            workflow = orchestrator.status(workflow.id)
            payload = payload_for(workflow)
            if explicit and workflow.lifecycle_version is LifecycleVersion.V2:
                store.set_selected_workflow_id(workflow.id)
            code, exit_code = _failure_for_workflow(store, workflow)
            return _result_document(command, workflow=workflow, error_code=code, data=payload), exit_code
        elif command == "approve":
            existing, explicit = _resolve_v2_workflow(store, args.workflow)
            if existing.lifecycle_version is LifecycleVersion.V2:
                artifact_id = args.artifact or plan_orchestrator.resolve_current_pending_plan_artifact(existing.id)
                workflow = plan_orchestrator.approve(existing.id, artifact_id, reason=args.reason)
            else:
                if args.artifact is None:
                    raise ValidationFailure("--artifact is required for V1 workflows")
                workflow = orchestrator.approve(existing.id, args.artifact, reason=args.reason)
            if explicit and workflow.lifecycle_version is LifecycleVersion.V2:
                store.set_selected_workflow_id(workflow.id)
        elif command == "reject":
            existing, explicit = _resolve_v2_workflow(store, args.workflow)
            if existing.lifecycle_version is LifecycleVersion.V2:
                artifact_id = args.artifact or plan_orchestrator.resolve_current_pending_plan_artifact(existing.id)
                workflow = plan_orchestrator.reject(existing.id, artifact_id, reason=args.reason)
            else:
                if args.artifact is None:
                    raise ValidationFailure("--artifact is required for V1 workflows")
                workflow = orchestrator.reject(existing.id, args.artifact, reason=args.reason)
            if explicit and workflow.lifecycle_version is LifecycleVersion.V2:
                store.set_selected_workflow_id(workflow.id)
        elif command == "cancel":
            existing, explicit = _resolve_v2_workflow(store, args.workflow)
            if existing.lifecycle_version is not LifecycleVersion.V2:
                raise ConflictFailure("workflow cancellation is supported only for V2 workflows")
            workflow = plan_orchestrator.cancel(existing.id)
            if explicit:
                store.set_selected_workflow_id(workflow.id)
        elif command == "resume":
            existing, explicit = _resolve_v2_workflow(store, args.workflow)
            if existing.lifecycle_version is LifecycleVersion.V2:
                if existing.status is WorkflowStatus.CANCELLED:
                    raise ConflictFailure("workflow is cancelled and cannot be resumed")
                if args.regenerate:
                    raise ValidationFailure("--regenerate is V1-only")
                if args.answer is not None:
                    workflow = intake_orchestrator.resume_answer(existing.id, args.answer, progress_sink=(None if args.json_output else create_progress_renderer(sys.stderr, no_color=args.no_color)))
                elif args.feedback is not None:
                    workflow = plan_orchestrator.request_changes(existing.id, args.feedback, progress_sink=(None if args.json_output else create_progress_renderer(sys.stderr, no_color=args.no_color)))
                elif existing.stage is Stage.INTAKE and existing.status in {WorkflowStatus.NEEDS_CLARIFICATION, WorkflowStatus.FAILED, WorkflowStatus.HUMAN_ATTENTION, WorkflowStatus.READY}:
                    progress_sink = (None if args.json_output else create_progress_renderer(sys.stderr, no_color=args.no_color))
                    workflow, eof_at_clarification = _continue_v2_clarifications(
                        existing, intake=intake_orchestrator, plan=plan_orchestrator,
                        progress_sink=progress_sink,
                        interactive=(not args.json_output and interactive_prompt_eligible(sys.stdin, sys.stdout, sys.stderr)),
                        no_color=args.no_color,
                    )
                elif (existing.status in {WorkflowStatus.PLAN_APPROVED, WorkflowStatus.IMPLEMENTATION_FAILED}
                      or store.active_implementation_lease(existing.id) is not None):
                    # The implementation orchestrator owns all authority,
                    # recovery, lease, dispatch, and result decisions.  This
                    # CLI branch is intentionally one call with no loop.
                    progress_sink = (None if args.json_output else create_progress_renderer(
                        sys.stderr, no_color=args.no_color,
                    ))
                    workflow = _continue_approved_implementation(
                        existing.id, store=store, config=config,
                        runtime=plan_orchestrator.runtime, progress_sink=progress_sink,
                    )
                else:
                    workflow = plan_orchestrator.resume(existing.id, progress_sink=(None if args.json_output else create_progress_renderer(sys.stderr, no_color=args.no_color)))
            else:
                if args.answer is not None or args.feedback is not None:
                    raise ValidationFailure("--answer and --feedback are V2-only")
                regenerate = {"prd": Stage.PRD, "techspec": Stage.TECHSPEC, "task-plan": Stage.TASK_PLAN}.get(args.regenerate)
                workflow = orchestrator.resume(existing.id, regenerate=regenerate)
            if explicit and workflow.lifecycle_version is LifecycleVersion.V2:
                store.set_selected_workflow_id(workflow.id)
        elif command == "intervene":
            workflow = orchestrator.intervene(args.workflow, args.task, reason=args.reason)
        elif command == "logs":
            workflow = orchestrator.status(args.workflow)
            payload = payload_for(workflow)
            payload["events"] = [_event_payload(event) for event in orchestrator.logs(args.workflow, after=args.after)]
            code, exit_code = _failure_for_workflow(store, workflow)
            return _result_document(command, workflow=workflow, error_code=code, data=payload), exit_code
        else:
            raise ValidationFailure(f"unsupported command: {command}")
        code, exit_code = _failure_for_workflow(store, workflow)
        payload = (payload_for(workflow)
                   if command == "resume" and workflow.lifecycle_version is LifecycleVersion.V2
                   else (_workflow_payload(store, workflow)
                         if command in ("approve", "reject", "cancel") and workflow.lifecycle_version is LifecycleVersion.V2
                         else None))
        document = _result_document(command, workflow=workflow, error_code=code, data=payload)
        if eof_at_clarification:
            document["_already_rendered"] = True
            return document, exit_code
        if (command == "resume" and args.feedback is None and not args.json_output
                and workflow.lifecycle_version is LifecycleVersion.V2
                and workflow.stage is Stage.PLAN and workflow.status is WorkflowStatus.AWAITING_APPROVAL
                and interactive_prompt_eligible(sys.stdin, sys.stdout, sys.stderr)):
            # A pending change request was retried just above, so its dispatch
            # consumes this invocation's first local Planner slot.
            planner_calls = (1 if existing.status is WorkflowStatus.CHANGES_REQUESTED
                             or (existing.stage is Stage.INTAKE and existing.status is WorkflowStatus.READY)
                             else 0)
            workflow, rendered = _interactive_v2_plan_loop(
                workflow, command=command, store=store, plan=plan_orchestrator,
                progress_sink=create_progress_renderer(sys.stderr, no_color=args.no_color),
                planner_calls=planner_calls, verbose=args.verbose, no_color=args.no_color,
            )
            result = _result_document(command, workflow=workflow, data=_workflow_payload(store, workflow))
            if rendered:
                result["_already_rendered"] = True
            return result, EXIT_SUCCESS
        return document, exit_code
    finally:
        store.close()


def _requested_json_output(argv: list[str]) -> bool:
    """Detect JSON intent before argparse can reject an invalid invocation."""

    return "--json" in argv


def _requested_command(argv: list[str]) -> str:
    """Return the requested stable command without attempting full parsing."""

    commands = {"init", "run", "status", "approve", "reject", "resume", "intervene", "logs", "cancel"}
    return next((argument for argument in argv if argument in commands), "unknown")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(raw_argv)
        document, exit_code = _run_command(args)
    except KeyboardInterrupt:
        # Orchestrators have already durably marked an in-flight provider call
        # unknown.  Prompt cancellation has no authority transition at all.
        document = _result_document(
            getattr(locals().get("args", None), "command", _requested_command(raw_argv)),
            error_code="human_attention",
            message="interrupted; persisted workflow state remains available via status or resume",
        )
        exit_code = EXIT_INTERRUPTED
    except _ParserUsageError as exc:
        if not _requested_json_output(raw_argv):
            parser.print_usage(sys.stderr)
            parser._print_message(f"{parser.prog}: error: {exc}\n", sys.stderr)
            return EXIT_USAGE
        document = _result_document(
            _requested_command(raw_argv), error_code=ERROR_CODES["usage"], message=str(exc)
        )
        exit_code = EXIT_USAGE
    except (DomainFailure, sqlite3.Error, OSError, ValueError) as exc:
        config_phase = bool("args" not in locals() or getattr(args, "command", None) != "init")
        code, exit_code = _error_code(exc, config_phase=config_phase and isinstance(exc, ValidationFailure))
        failed_workflow = None
        failed_args = locals().get("args")
        if getattr(failed_args, "workflow", None) and getattr(failed_args, "repo", None):
            try:
                failed_config = load_config(failed_args.repo)
                failed_store = WorkflowStore(failed_config.database_path)
                try:
                    failed_workflow = failed_store.get_workflow(failed_args.workflow)
                finally:
                    failed_store.close()
            except Exception:
                failed_workflow = None
        document = _result_document(
            getattr(failed_args, "command", "unknown"),
            workflow=failed_workflow, error_code=code, message=str(exc),
        )
        if failed_workflow is None and getattr(failed_args, "workflow", None):
            document["workflow_id"] = sanitize_text(str(failed_args.workflow))
    json_output = bool(
        ("args" in locals() and getattr(args, "json_output", False))
        or _requested_json_output(raw_argv)
    )
    verbose_output = bool("args" in locals() and getattr(args, "verbose", False))
    mode = OutputMode.JSON if json_output else (OutputMode.VERBOSE if verbose_output else OutputMode.HUMAN)
    already_rendered = bool(document.pop("_already_rendered", False))
    if already_rendered:
        return exit_code
    render_result(
        document,
        mode=mode,
        stream=sys.stdout,
        no_color=bool("args" in locals() and getattr(args, "no_color", False)),
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
