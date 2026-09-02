"""The thin command-line adapter for the Wave 1 planning control plane."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

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
)
from .orchestrator import PlanningOrchestrator
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
    run.add_argument("--repo", required=True, metavar="PATH")
    run.add_argument("--feature-file", required=True, metavar="PATH")
    run.add_argument("--provider", choices=("codex-cli",), default="codex-cli")

    for name in ("status", "approve", "reject", "resume", "logs"):
        command = commands.add_parser(name)
        command.add_argument("--repo", required=True, metavar="PATH")
        command.add_argument("--workflow", required=True, metavar="ID")
        if name in ("status", "logs"):
            command.add_argument("--json", action="store_true", dest="json_output")
        if name in ("approve", "reject"):
            command.add_argument("--artifact", required=True, metavar="ID")
        if name in ("approve", "reject"):
            command.add_argument("--reason", required=name == "reject", metavar="TEXT")
        if name == "resume":
            command.add_argument("--regenerate", choices=("prd", "techspec", "task-plan"))
        if name == "logs":
            command.add_argument("--after", type=_nonnegative_int, default=0, metavar="SEQUENCE")
    return parser


def _workflow_payload(store: WorkflowStore, workflow: Workflow) -> dict[str, Any]:
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
            "lifecycle": latest.lifecycle.value,
            "failure_classification": latest.failure_classification.value if latest.failure_classification else None,
            "failure_detail": latest.failure_detail,
        }
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
    }


def _event_payload(event: Any) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "type": event.type,
        "stage": event.stage.value if event.stage else None,
        "artifact_id": event.artifact_id,
        "execution_id": event.execution_id,
        "payload": dict(event.payload),
        "created_at": event.created_at,
    }


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


def _print_result(document: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(document, ensure_ascii=False, sort_keys=True))
        return
    if document.get("command_result") == "error":
        print(f"error: {document.get('error_code')}: {document.get('message', '')}")
        return
    print(f"command: {document.get('command_result')}")
    if document.get("workflow_id"):
        print(f"workflow: {document['workflow_id']}")
    if document.get("status"):
        print(f"status: {document['status']}")
    if document.get("stage"):
        print(f"stage: {document['stage']}")
    if document.get("artifacts") is not None:
        for artifact in document["artifacts"]:
            print(f"artifact: {artifact['id']} {artifact['stage']} revision={artifact['revision']} approval={artifact['approval_state']}")
    if document.get("events") is not None:
        for event in document["events"]:
            print(json.dumps(event, ensure_ascii=False, sort_keys=True))


def _failure_for_workflow(store: WorkflowStore, workflow: Workflow) -> tuple[str | None, int]:
    if workflow.status is WorkflowStatus.HUMAN_ATTENTION:
        latest = store.get_latest_execution(workflow.id)
        if latest and latest.failure_classification is FailureClassification.AUTHENTICATION:
            return ERROR_CODES[FailureClassification.AUTHENTICATION.value], EXIT_AUTHENTICATION
        return ERROR_CODES["human_attention"], EXIT_HUMAN_ATTENTION
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


def _services(config: FlowConfig) -> tuple[WorkflowStore, PlanningOrchestrator]:
    store = WorkflowStore(config.database_path)
    runtime = CodexCliRuntime(
        config.provider_command,
        timeout_seconds=config.timeout_seconds,
        allow_read_only_planning=config.allow_read_only_planning,
    )
    orchestrator = PlanningOrchestrator(
        store,
        runtime,
        approval_policies=config.approval_policies,
        timeout_seconds=config.timeout_seconds,
    )
    return store, orchestrator


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
    store, orchestrator = _services(config)
    try:
        if command == "run":
            feature_file = _validate_feature_file(args.feature_file)
            workflow = orchestrator.run(
                config.repository_path, feature_file=feature_file,
                provider=config.provider_name, configuration_snapshot=config.snapshot,
            )
        elif command == "status":
            workflow = orchestrator.status(args.workflow)
            payload = _workflow_payload(store, workflow)
            code, exit_code = _failure_for_workflow(store, workflow)
            return _result_document(command, workflow=workflow, error_code=code, data=payload), exit_code
        elif command == "approve":
            workflow = orchestrator.approve(args.workflow, args.artifact, reason=args.reason)
        elif command == "reject":
            workflow = orchestrator.reject(args.workflow, args.artifact, reason=args.reason)
        elif command == "resume":
            regenerate = {"prd": Stage.PRD, "techspec": Stage.TECHSPEC, "task-plan": Stage.TASK_PLAN}.get(args.regenerate)
            workflow = orchestrator.resume(args.workflow, regenerate=regenerate)
        elif command == "logs":
            workflow = orchestrator.status(args.workflow)
            payload = _workflow_payload(store, workflow)
            payload["events"] = [_event_payload(event) for event in orchestrator.logs(args.workflow, after=args.after)]
            code, exit_code = _failure_for_workflow(store, workflow)
            return _result_document(command, workflow=workflow, error_code=code, data=payload), exit_code
        else:
            raise ValidationFailure(f"unsupported command: {command}")
        code, exit_code = _failure_for_workflow(store, workflow)
        return _result_document(command, workflow=workflow, error_code=code), exit_code
    finally:
        store.close()


def _requested_json_output(argv: list[str]) -> bool:
    """Detect JSON intent before argparse can reject an invalid invocation."""

    return "--json" in argv


def _requested_command(argv: list[str]) -> str:
    """Return the requested stable command without attempting full parsing."""

    commands = {"init", "run", "status", "approve", "reject", "resume", "logs"}
    return next((argument for argument in argv if argument in commands), "unknown")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(raw_argv)
        document, exit_code = _run_command(args)
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
    _print_result(document, json_output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
