"""Durable SQLite persistence for provider-neutral workflow state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import (
    Approval,
    ApprovalDecision,
    ApprovalState,
    ApprovedV2PlanAuthority,
    Artifact,
    ArtifactCorruptionFailure,
    ConflictFailure,
    DomainFailure,
    Execution,
    ExecutionLifecycle,
    FailureClassification,
    CapabilityOperation,
    Clarification,
    PlanChangeRequest,
    CanonicalStage,
    GenerationIntent,
    GovernanceDecision,
    GovernanceDecisionType,
    GovernanceRecord,
    AuthorityEvaluation,
    HumanAttentionOutcome,
    EvidenceReference,
    LifecycleState,
    LifecycleVersion,
    MigrationOutcome,
    MigrationReceipt,
    NotFoundFailure,
    Operation,
    OperationStatus,
    PersistenceFailure,
    Role,
    ScopeKind,
    Session,
    Stage,
    SuccessfulImplementationProducer,
    Intervention,
    TaskArtifact,
    TaskArtifactType,
    TaskCycle,
    TaskDefinition,
    TaskOperationIntent,
    TaskStatus,
    TaskImplementationState,
    TaskImplementationStatus,
    FeatureContract,
    IntakeOutcome,
    Plan,
    WorkKind,
    ValidationFailure,
    Workflow,
    WorkflowScope,
    WorkflowEvent,
    WorkflowStatus,
    is_terminal_workflow_status,
)
from .sanitization import sanitize_configuration_snapshot, sanitize_payload, sanitize_text
from .repository import RepositoryInspector, control_state_fingerprint


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class VerificationRecoveryDecision:
    """Externally observed facts for one dead, unchanged VERIFY recovery.

    This value is deliberately not release authority.  The store reconstructs
    the unique durable workflow/attempt/operation/execution/task/lease context
    and binds these observations to it inside the releasing transaction.
    """

    workflow_id: str
    process_observation: str
    observed_identity: Mapping[str, Any]
    repository: Mapping[str, Any]
    control_state_fingerprint: str
    authority: Mapping[str, Any]
    detail: str


_MANIFEST_RE = re.compile(
    r"```[ \t]*engineering-flow-task-plan[ \t]*\r?\n(?P<body>.*?)```",
    re.IGNORECASE | re.DOTALL,
)


_GOVERNANCE_DECISION_BY_TYPE = {
    GovernanceDecisionType.APPROVAL: GovernanceDecision.APPROVED,
    GovernanceDecisionType.REJECTION: GovernanceDecision.REJECTED,
    GovernanceDecisionType.WAVE_ACCEPTANCE: GovernanceDecision.ACCEPTED,
    GovernanceDecisionType.RELEASE_ACCEPTANCE: GovernanceDecision.ACCEPTED,
    GovernanceDecisionType.WAVE_START_AUTHORIZATION: GovernanceDecision.AUTHORIZED,
    GovernanceDecisionType.DELIVERY_AUTHORIZATION: GovernanceDecision.AUTHORIZED,
    GovernanceDecisionType.REVOCATION: GovernanceDecision.REVOKED,
    GovernanceDecisionType.SUPERSESSION: GovernanceDecision.SUPERSEDED,
}


def _non_empty_strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValidationFailure(f"task manifest {field} must be a non-empty string array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationFailure(f"task manifest {field} must contain non-empty strings")
        result.append(item)
    return tuple(result)


def parse_task_plan_manifest(markdown: str, repository_path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Parse and validate the single normative Wave 2 task manifest."""
    if not isinstance(markdown, str):
        raise ValidationFailure("task-plan artifact must be UTF-8 Markdown text")
    matches = list(_MANIFEST_RE.finditer(markdown))
    if len(matches) != 1:
        raise ValidationFailure(
            "approved task-plan Markdown must contain exactly one "
            "engineering-flow-task-plan JSON block"
        )
    try:
        manifest = json.loads(matches[0].group("body"))
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"task-plan manifest JSON is malformed: {exc.msg}") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValidationFailure("unsupported task-plan manifest version")
    raw_tasks = manifest.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValidationFailure("task-plan manifest tasks must be a non-empty array")
    repository = Path(repository_path).expanduser().resolve()
    result: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(raw_tasks, start=1):
        if not isinstance(raw, dict):
            raise ValidationFailure(f"task {index} must be an object")
        values: dict[str, Any] = {}
        for field in ("key", "title", "instructions"):
            value = raw.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValidationFailure(f"task {index} {field} must be a non-empty string")
            values[field] = value
        key = values["key"]
        if key in seen_keys:
            raise ValidationFailure(f"duplicate task key: {key}")
        seen_keys.add(key)
        values["acceptance_criteria"] = _non_empty_strings(raw.get("acceptance_criteria"), "acceptance_criteria")
        values["required_tests"] = _non_empty_strings(raw.get("required_tests"), "required_tests")
        context = raw.get("context_paths", [])
        if not isinstance(context, list):
            raise ValidationFailure("task manifest context_paths must be an array")
        canonical_context: list[str] = []
        seen_context: set[str] = set()
        for raw_path in context:
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValidationFailure("task manifest context_paths must contain strings")
            candidate = Path(raw_path)
            if candidate.is_absolute():
                raise ValidationFailure(f"task context path must be repository-relative: {raw_path}")
            resolved = (repository / candidate).resolve()
            try:
                relative = resolved.relative_to(repository)
            except ValueError as exc:
                raise ValidationFailure(f"task context path escapes repository: {raw_path}") from exc
            if not resolved.is_file():
                raise ValidationFailure(f"task context path is not an existing file: {raw_path}")
            canonical = relative.as_posix()
            if canonical in seen_context:
                raise ValidationFailure(f"duplicate task context path: {canonical}")
            seen_context.add(canonical)
            canonical_context.append(canonical)
        values["context_paths"] = tuple(canonical_context)
        values["ordinal"] = index
        result.append(values)
    return result


class WorkflowStore:
    """A single-process writer-guarded SQLite store.

    The store records explicit decisions supplied by orchestration; it never
    derives or advances workflow lifecycle on its own.
    """

    def __init__(self, database_path: str | os.PathLike[str], *, secret_values: tuple[str, ...] = ()):
        self.database_path = Path(database_path).expanduser().resolve()
        self.workspace_path = self.database_path.parent.resolve()
        self.secret_values = tuple(secret_values)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._writer_lock = threading.RLock()
        try:
            self._connection = sqlite3.connect(
                self.database_path, timeout=2.0, isolation_level=None, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._create_schema()
        except DomainFailure:
            self._connection.close()
            raise
        except sqlite3.Error as exc:
            raise PersistenceFailure(f"could not open workflow database: {exc}") from exc

    def close(self) -> None:
        with self._writer_lock:
            self._connection.close()

    def __enter__(self) -> WorkflowStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _create_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            repository_path TEXT NOT NULL,
            provider TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            configuration_snapshot TEXT NOT NULL,
            current_artifact_revision INTEGER,
            feature_input_path TEXT,
            feature_input_sha256 TEXT
            ,lifecycle_version TEXT NOT NULL DEFAULT 'historical'
        );
        CREATE TABLE IF NOT EXISTS repository_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            logical_session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_session_id TEXT,
            task_id TEXT,
            cycle_id TEXT,
            work_kind TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            session_id TEXT NOT NULL REFERENCES sessions(id),
            role TEXT NOT NULL,
            provider_execution_id TEXT,
            request_hash TEXT NOT NULL,
            lifecycle TEXT NOT NULL,
            capability_report TEXT NOT NULL,
            terminal_result TEXT,
            failure_classification TEXT,
            failure_detail TEXT,
            task_id TEXT,
            cycle_id TEXT,
            work_kind TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            stage TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision > 0),
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
            source_execution_id TEXT REFERENCES executions(id),
            approval_state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(workflow_id, stage, revision)
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id),
            decision TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clarifications (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            sequence INTEGER NOT NULL CHECK(sequence > 0),
            source_feature_contract_artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id),
            question TEXT NOT NULL,
            answer TEXT,
            actor TEXT,
            result_feature_contract_artifact_id TEXT UNIQUE REFERENCES artifacts(id),
            created_at TEXT NOT NULL,
            answered_at TEXT,
            completed_at TEXT,
            UNIQUE(workflow_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS plan_change_requests (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            sequence INTEGER NOT NULL CHECK(sequence > 0),
            target_plan_artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id),
            feedback TEXT NOT NULL,
            actor TEXT NOT NULL,
            replacement_plan_artifact_id TEXT UNIQUE REFERENCES artifacts(id),
            created_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(workflow_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS task_implementation_states (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            plan_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
            plan_sha256 TEXT NOT NULL CHECK(length(plan_sha256) = 64),
            task_contract_id TEXT NOT NULL,
            task_contract_sha256 TEXT NOT NULL CHECK(length(task_contract_sha256) = 64),
            status TEXT NOT NULL CHECK(status IN ('pending', 'implementing', 'implementation_completed', 'implementation_failed', 'implementation_unknown', 'verifying', 'verification_failed', 'verified')),
            selected_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(workflow_id, plan_artifact_id, task_contract_id)
        );
        CREATE TABLE IF NOT EXISTS implementation_attempts (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            execution_id TEXT NOT NULL UNIQUE REFERENCES executions(id),
            operation_id TEXT NOT NULL UNIQUE REFERENCES operations(id),
            lease_id TEXT NOT NULL UNIQUE,
            feature_artifact_id TEXT NOT NULL REFERENCES artifacts(id), feature_sha256 TEXT NOT NULL,
            plan_artifact_id TEXT NOT NULL REFERENCES artifacts(id), plan_sha256 TEXT NOT NULL,
            plan_revision INTEGER NOT NULL, plan_id TEXT NOT NULL, approval_id TEXT NOT NULL REFERENCES approvals(id),
            task_contract_id TEXT NOT NULL, task_contract_sha256 TEXT NOT NULL, sequence INTEGER NOT NULL,
            request_hash TEXT NOT NULL, requested_profile TEXT NOT NULL, requested_provider TEXT NOT NULL,
            requested_model TEXT, requested_reasoning TEXT, actual_provider TEXT, actual_model TEXT,
            actual_reasoning TEXT, provider_operation_ref TEXT, provider_session_ref TEXT,
            started_at TEXT, finished_at TEXT, status TEXT NOT NULL, result_classification TEXT,
            baseline_repository_json TEXT, final_repository_json TEXT, workspace_changed INTEGER,
            changed_paths_json TEXT, diff_summary_json TEXT, agent_result_json TEXT, usage_json TEXT,
            error_classification TEXT, error_detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(workflow_id, plan_artifact_id, task_contract_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS workspace_operation_leases (
            repository_key TEXT PRIMARY KEY, lease_id TEXT NOT NULL UNIQUE,
            operation_kind TEXT NOT NULL CHECK(operation_kind IN ('implementation', 'verification', 'fix')),
            attempt_id TEXT NOT NULL UNIQUE, operation_id TEXT NOT NULL UNIQUE REFERENCES operations(id),
            workflow_id TEXT NOT NULL REFERENCES workflows(id), canonical_root TEXT NOT NULL,
            owner_instance_id TEXT NOT NULL, owner_pid INTEGER NOT NULL, owner_host_id TEXT NOT NULL,
            owner_boot_id TEXT, child_pid INTEGER, child_process_start TEXT,
            child_process_group INTEGER, child_process_session INTEGER,
            acquired_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS verification_attempts (
            id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL REFERENCES workflows(id),
            producer_operation_id TEXT NOT NULL REFERENCES operations(id),
            execution_id TEXT NOT NULL UNIQUE REFERENCES executions(id),
            operation_id TEXT NOT NULL UNIQUE REFERENCES operations(id), lease_id TEXT NOT NULL UNIQUE,
            feature_artifact_id TEXT NOT NULL REFERENCES artifacts(id), feature_sha256 TEXT NOT NULL,
            plan_artifact_id TEXT NOT NULL REFERENCES artifacts(id), plan_sha256 TEXT NOT NULL,
            plan_revision INTEGER NOT NULL, plan_id TEXT NOT NULL, approval_id TEXT NOT NULL REFERENCES approvals(id),
            task_contract_id TEXT NOT NULL, task_contract_sha256 TEXT NOT NULL,
            authority_sha256 TEXT NOT NULL, request_hash TEXT NOT NULL,
            manifest_binding_json TEXT NOT NULL, baseline_repository_json TEXT NOT NULL,
            final_inspection_json TEXT, status TEXT NOT NULL, classification TEXT,
            sequence INTEGER NOT NULL, started_at TEXT, finished_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(workflow_id, producer_operation_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS verification_command_results (
            id TEXT PRIMARY KEY, verification_attempt_id TEXT NOT NULL REFERENCES verification_attempts(id),
            ordinal INTEGER NOT NULL CHECK(ordinal > 0), command_id TEXT NOT NULL,
            canonical_command_sha256 TEXT NOT NULL, argv_json TEXT NOT NULL,
            timeout_seconds INTEGER NOT NULL CHECK(timeout_seconds > 0), intent_at TEXT NOT NULL,
            result_at TEXT, exit_code INTEGER, timed_out INTEGER, output_sha256 TEXT,
            output_bytes INTEGER, output_truncated INTEGER, post_command_inspection_json TEXT,
            classification TEXT, child_pid INTEGER, child_process_start TEXT,
            child_process_group INTEGER, child_process_session INTEGER, child_host_id TEXT, child_boot_id TEXT,
            child_owner_instance_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(verification_attempt_id, ordinal), UNIQUE(verification_attempt_id, command_id)
        );
        CREATE TABLE IF NOT EXISTS operations (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            status TEXT NOT NULL,
            related_record_id TEXT,
            intent_stage TEXT,
            intent_revision INTEGER,
            intent_artifact_path TEXT,
            task_id TEXT,
            cycle_id TEXT,
            work_kind TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            type TEXT NOT NULL,
            stage TEXT,
            artifact_id TEXT,
            execution_id TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(workflow_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            ordinal INTEGER NOT NULL CHECK (ordinal > 0),
            key TEXT NOT NULL,
            title TEXT NOT NULL,
            instructions TEXT NOT NULL,
            acceptance_criteria TEXT NOT NULL,
            required_tests TEXT NOT NULL,
            context_paths TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            definition_sha256 TEXT NOT NULL CHECK (length(definition_sha256) = 64),
            source_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
            source_artifact_sha256 TEXT NOT NULL CHECK (length(source_artifact_sha256) = 64),
            status TEXT NOT NULL,
            current_review_window INTEGER NOT NULL DEFAULT 1 CHECK (current_review_window > 0),
            current_cycle INTEGER NOT NULL DEFAULT 0 CHECK (current_cycle >= 0),
            accepted_at TEXT,
            UNIQUE(workflow_id, ordinal),
            UNIQUE(workflow_id, key)
        );
        CREATE TABLE IF NOT EXISTS task_cycles (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id),
            review_window INTEGER NOT NULL CHECK (review_window > 0),
            cycle INTEGER NOT NULL CHECK (cycle > 0),
            developer_execution_id TEXT REFERENCES executions(id),
            required_test_artifact_id TEXT,
            reviewer_execution_id TEXT REFERENCES executions(id),
            review_artifact_id TEXT,
            outcome TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(task_id, review_window, cycle)
        );
        CREATE TABLE IF NOT EXISTS task_artifacts (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            task_id TEXT NOT NULL REFERENCES tasks(id),
            cycle_id TEXT REFERENCES task_cycles(id),
            artifact_type TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
            source_execution_id TEXT REFERENCES executions(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS interventions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            task_id TEXT NOT NULL REFERENCES tasks(id),
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            prior_review_window INTEGER NOT NULL CHECK (prior_review_window > 0),
            prior_cycle INTEGER NOT NULL CHECK (prior_cycle >= 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lifecycle_states (
            workflow_id TEXT PRIMARY KEY REFERENCES workflows(id),
            lifecycle_version TEXT NOT NULL,
            stage TEXT,
            status TEXT NOT NULL,
            scope_id TEXT,
            operation_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_scopes (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            kind TEXT NOT NULL,
            external_key TEXT NOT NULL,
            parent_scope_id TEXT REFERENCES workflow_scopes(id),
            created_at TEXT NOT NULL,
            UNIQUE(workflow_id, kind, external_key)
        );
        CREATE TABLE IF NOT EXISTS evidence_references (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            scope_id TEXT REFERENCES workflow_scopes(id),
            reference TEXT NOT NULL,
            sha256 TEXT NOT NULL CHECK(length(sha256) = 64),
            operation_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(workflow_id, reference, sha256),
            UNIQUE(operation_key)
        );
        CREATE TABLE IF NOT EXISTS capability_operations (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            scope_id TEXT REFERENCES workflow_scopes(id),
            operation_key TEXT NOT NULL UNIQUE,
            request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint) = 64),
            status TEXT NOT NULL,
            result TEXT,
            attention_outcome TEXT,
            evidence_id TEXT REFERENCES evidence_references(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS migration_receipts (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            operation_key TEXT NOT NULL UNIQUE,
            source_version TEXT NOT NULL,
            target_version TEXT NOT NULL,
            outcome TEXT NOT NULL,
            request_fingerprint TEXT,
            detail TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS governance_decisions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            scope_id TEXT NOT NULL REFERENCES workflow_scopes(id),
            lifecycle_version TEXT NOT NULL,
            operation_key TEXT NOT NULL UNIQUE,
            request_fingerprint TEXT NOT NULL CHECK(length(request_fingerprint) = 64),
            decision_type TEXT NOT NULL,
            decision TEXT NOT NULL,
            actor TEXT NOT NULL,
            evidence TEXT NOT NULL,
            approval_target_stage TEXT,
            predecessor_ids TEXT NOT NULL,
            affected_ids TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS governance_eligibility (
            decision_id TEXT PRIMARY KEY REFERENCES governance_decisions(id),
            eligible INTEGER NOT NULL CHECK(eligible IN (0, 1)),
            invalidated_by_id TEXT REFERENCES governance_decisions(id),
            invalidated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_governance_scope
            ON governance_decisions(workflow_id, scope_id, lifecycle_version, decision_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_events_workflow_sequence
            ON events(workflow_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_artifacts_workflow_stage
            ON artifacts(workflow_id, stage, revision);
        CREATE INDEX IF NOT EXISTS idx_clarifications_workflow ON clarifications(workflow_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_plan_change_requests_workflow ON plan_change_requests(workflow_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_task_implementation_states_plan
            ON task_implementation_states(workflow_id, plan_artifact_id, task_contract_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_workflow_ordinal
            ON tasks(workflow_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_task_cycles_task
            ON task_cycles(task_id, review_window, cycle);
        CREATE INDEX IF NOT EXISTS idx_task_artifacts_task
            ON task_artifacts(task_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_scopes_workflow ON workflow_scopes(workflow_id, kind);
        CREATE INDEX IF NOT EXISTS idx_capability_operations_workflow ON capability_operations(workflow_id, created_at);
        """
        with self._writer_lock:
            try:
                self._connection.executescript(schema)
                workflow_columns = {
                    row["name"]
                    for row in self._connection.execute("PRAGMA table_info(workflows)").fetchall()
                }
                operation_columns = {
                    row["name"]
                    for row in self._connection.execute("PRAGMA table_info(operations)").fetchall()
                }
                session_columns = {
                    row["name"]
                    for row in self._connection.execute("PRAGMA table_info(sessions)").fetchall()
                }
                execution_columns = {
                    row["name"]
                    for row in self._connection.execute("PRAGMA table_info(executions)").fetchall()
                }
                migration_receipt_columns = {
                    row["name"]
                    for row in self._connection.execute("PRAGMA table_info(migration_receipts)").fetchall()
                }
                governance_columns = {row["name"] for row in self._connection.execute(
                    "PRAGMA table_info(governance_decisions)").fetchall()}
                verification_command_columns = {row["name"] for row in self._connection.execute(
                    "PRAGMA table_info(verification_command_results)").fetchall()}
                workspace_lease_columns = {row["name"] for row in self._connection.execute(
                    "PRAGMA table_info(workspace_operation_leases)").fetchall()}
                if "approval_target_stage" not in governance_columns:
                    self._connection.execute("ALTER TABLE governance_decisions ADD COLUMN approval_target_stage TEXT")
                for name, statement in (
                    ("feature_input_path", "ALTER TABLE workflows ADD COLUMN feature_input_path TEXT"),
                    ("feature_input_sha256", "ALTER TABLE workflows ADD COLUMN feature_input_sha256 TEXT"),
                    ("lifecycle_version", "ALTER TABLE workflows ADD COLUMN lifecycle_version TEXT NOT NULL DEFAULT 'historical'"),
                ):
                    if name not in workflow_columns:
                        self._connection.execute(statement)
                for name, statement in (
                    ("intent_stage", "ALTER TABLE operations ADD COLUMN intent_stage TEXT"),
                    ("intent_revision", "ALTER TABLE operations ADD COLUMN intent_revision INTEGER"),
                    (
                        "intent_artifact_path",
                        "ALTER TABLE operations ADD COLUMN intent_artifact_path TEXT",
                    ),
                ):
                    if name not in operation_columns:
                        self._connection.execute(statement)
                for name, statement in (
                    ("task_id", "ALTER TABLE sessions ADD COLUMN task_id TEXT"),
                    ("cycle_id", "ALTER TABLE sessions ADD COLUMN cycle_id TEXT"),
                    ("work_kind", "ALTER TABLE sessions ADD COLUMN work_kind TEXT"),
                ):
                    if name not in session_columns:
                        self._connection.execute(statement)
                for name, statement in (
                    ("task_id", "ALTER TABLE executions ADD COLUMN task_id TEXT"),
                    ("cycle_id", "ALTER TABLE executions ADD COLUMN cycle_id TEXT"),
                    ("work_kind", "ALTER TABLE executions ADD COLUMN work_kind TEXT"),
                ):
                    if name not in execution_columns:
                        self._connection.execute(statement)
                if "request_fingerprint" not in migration_receipt_columns:
                    self._connection.execute(
                        "ALTER TABLE migration_receipts ADD COLUMN request_fingerprint TEXT"
                    )
                for name, statement in (
                    ("child_pid", "ALTER TABLE verification_command_results ADD COLUMN child_pid INTEGER"),
                    ("child_process_start", "ALTER TABLE verification_command_results ADD COLUMN child_process_start TEXT"),
                    ("child_process_group", "ALTER TABLE verification_command_results ADD COLUMN child_process_group INTEGER"),
                    ("child_process_session", "ALTER TABLE verification_command_results ADD COLUMN child_process_session INTEGER"),
                    ("child_host_id", "ALTER TABLE verification_command_results ADD COLUMN child_host_id TEXT"),
                    ("child_boot_id", "ALTER TABLE verification_command_results ADD COLUMN child_boot_id TEXT"),
                    ("child_owner_instance_id", "ALTER TABLE verification_command_results ADD COLUMN child_owner_instance_id TEXT"),
                ):
                    if name not in verification_command_columns:
                        self._connection.execute(statement)
                if "child_process_session" not in workspace_lease_columns:
                    self._connection.execute(
                        "ALTER TABLE workspace_operation_leases ADD COLUMN child_process_session INTEGER")
                self._migrate_workspace_writer_leases()
                self._migrate_verification_attempt_sequences()
                # SQLite cannot widen a CHECK constraint in place.  This is
                # the existing MDS #3 task-state table, not verification
                # attempt persistence; rebuilding it retains all rows while
                # allowing the Slice 1 domain states to round-trip.
                task_state_sql = self._connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='task_implementation_states'"
                ).fetchone()["sql"]
                if "'verifying'" not in task_state_sql:
                    self._connection.executescript("""
                        ALTER TABLE task_implementation_states RENAME TO task_implementation_states_legacy;
                        CREATE TABLE task_implementation_states (
                            id TEXT PRIMARY KEY,
                            workflow_id TEXT NOT NULL REFERENCES workflows(id),
                            plan_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
                            plan_sha256 TEXT NOT NULL CHECK(length(plan_sha256) = 64),
                            task_contract_id TEXT NOT NULL,
                            task_contract_sha256 TEXT NOT NULL CHECK(length(task_contract_sha256) = 64),
                            status TEXT NOT NULL CHECK(status IN ('pending', 'implementing', 'implementation_completed', 'implementation_failed', 'implementation_unknown', 'verifying', 'verification_failed', 'verified')),
                            selected_at TEXT,
                            updated_at TEXT NOT NULL,
                            UNIQUE(workflow_id, plan_artifact_id, task_contract_id)
                        );
                        INSERT INTO task_implementation_states
                            SELECT * FROM task_implementation_states_legacy;
                        DROP TABLE task_implementation_states_legacy;
                        CREATE INDEX IF NOT EXISTS idx_task_implementation_states_plan
                            ON task_implementation_states(workflow_id, plan_artifact_id, task_contract_id);
                    """)
                current_operation_columns = {
                    row["name"]
                    for row in self._connection.execute("PRAGMA table_info(operations)").fetchall()
                }
                for name, statement in (
                    ("task_id", "ALTER TABLE operations ADD COLUMN task_id TEXT"),
                    ("cycle_id", "ALTER TABLE operations ADD COLUMN cycle_id TEXT"),
                    ("work_kind", "ALTER TABLE operations ADD COLUMN work_kind TEXT"),
                ):
                    if name not in current_operation_columns:
                        self._connection.execute(statement)
            except sqlite3.Error as exc:
                raise PersistenceFailure(f"could not create workflow schema: {exc}") from exc

    def _migrate_workspace_writer_leases(self) -> None:
        """Atomically absorb the MDS #3 lease table, including interrupted residue."""
        legacy = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_writer_leases'"
        ).fetchone()
        if legacy is None:
            return
        with self._transaction() as conn:
            rows = conn.execute("""SELECT l.*, a.id AS implementation_attempt_id,
                a.lease_id AS implementation_lease_id,
                a.workflow_id AS implementation_workflow_id,
                a.operation_id AS implementation_operation_id,
                a.baseline_repository_json AS implementation_baseline_repository_json,
                o.id AS implementation_operation_identity,
                o.workflow_id AS implementation_operation_workflow_id
                FROM workspace_writer_leases l
                LEFT JOIN implementation_attempts a ON a.id=l.attempt_id
                LEFT JOIN operations o ON o.id=a.operation_id""").fetchall()
            for row in rows:
                if (row["implementation_attempt_id"] != row["attempt_id"]
                        or row["implementation_lease_id"] != row["lease_id"]
                        or row["implementation_workflow_id"] != row["workflow_id"]
                        or row["implementation_operation_identity"] != row["implementation_operation_id"]
                        or row["implementation_operation_workflow_id"] != row["workflow_id"]):
                    raise ConflictFailure("legacy writer lease identity conflicts with implementation attempt")
                try:
                    baseline = json.loads(row["implementation_baseline_repository_json"])
                    repository_key = hashlib.sha256("\0".join((
                        baseline["canonical_root"], baseline["git_dir"], baseline["git_common_dir"],
                    )).encode()).hexdigest()
                except (KeyError, TypeError, json.JSONDecodeError):
                    raise ConflictFailure("legacy writer lease lacks matching implementation repository identity") from None
                if baseline["canonical_root"] != row["canonical_root"] or repository_key != row["repository_key"]:
                    raise ConflictFailure("legacy writer lease repository identity conflicts with implementation attempt")
                common = conn.execute("SELECT * FROM workspace_operation_leases WHERE repository_key=?",
                                      (row["repository_key"],)).fetchone()
                values = (row["repository_key"], row["lease_id"], "implementation", row["attempt_id"],
                          row["implementation_operation_id"], row["workflow_id"], row["canonical_root"],
                          row["owner_instance_id"], row["owner_pid"], row["owner_host_id"],
                          row["owner_boot_id"], row["provider_pid"], row["provider_process_start"],
                          row["provider_process_group"], row["acquired_at"], row["updated_at"])
                if common is not None:
                    fields = ("repository_key", "lease_id", "operation_kind", "attempt_id", "operation_id",
                              "workflow_id", "canonical_root", "owner_instance_id", "owner_pid", "owner_host_id",
                              "owner_boot_id", "child_pid", "child_process_start", "child_process_group",
                              "acquired_at", "updated_at")
                    if tuple(common[field] for field in fields) != values:
                        raise ConflictFailure("legacy writer lease conflicts with common operation lease")
                    continue
                conn.execute("""INSERT INTO workspace_operation_leases
                    (repository_key,lease_id,operation_kind,attempt_id,operation_id,workflow_id,canonical_root,
                     owner_instance_id,owner_pid,owner_host_id,owner_boot_id,child_pid,child_process_start,
                     child_process_group,acquired_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
            for row in rows:
                migrated = conn.execute("""SELECT l.* FROM workspace_operation_leases l
                    WHERE l.repository_key=? AND l.lease_id=? AND l.attempt_id=?
                      AND l.operation_kind='implementation'""",
                    (row["repository_key"], row["lease_id"], row["attempt_id"])).fetchone()
                if migrated is None:
                    raise PersistenceFailure("legacy writer lease migration validation failed")
            conn.execute("DROP TABLE workspace_writer_leases")

    def _migrate_verification_attempt_sequences(self) -> None:
        """Remove the obsolete deterministic-request uniqueness constraint safely."""
        sql_row = self._connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='verification_attempts'").fetchone()
        if sql_row is None or "sequence INTEGER NOT NULL" in (sql_row["sql"] or ""):
            return
        with self._transaction() as conn:
            conn.execute("ALTER TABLE verification_attempts RENAME TO verification_attempts_legacy")
            conn.execute("""CREATE TABLE verification_attempts (
                id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL REFERENCES workflows(id),
                producer_operation_id TEXT NOT NULL REFERENCES operations(id),
                execution_id TEXT NOT NULL UNIQUE REFERENCES executions(id),
                operation_id TEXT NOT NULL UNIQUE REFERENCES operations(id), lease_id TEXT NOT NULL UNIQUE,
                feature_artifact_id TEXT NOT NULL REFERENCES artifacts(id), feature_sha256 TEXT NOT NULL,
                plan_artifact_id TEXT NOT NULL REFERENCES artifacts(id), plan_sha256 TEXT NOT NULL,
                plan_revision INTEGER NOT NULL, plan_id TEXT NOT NULL, approval_id TEXT NOT NULL REFERENCES approvals(id),
                task_contract_id TEXT NOT NULL, task_contract_sha256 TEXT NOT NULL,
                authority_sha256 TEXT NOT NULL, request_hash TEXT NOT NULL,
                manifest_binding_json TEXT NOT NULL, baseline_repository_json TEXT NOT NULL,
                final_inspection_json TEXT, status TEXT NOT NULL, classification TEXT,
                sequence INTEGER NOT NULL, started_at TEXT, finished_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(workflow_id, producer_operation_id, sequence))""")
            conn.execute("""INSERT INTO verification_attempts
                SELECT id,workflow_id,producer_operation_id,execution_id,operation_id,lease_id,feature_artifact_id,
                       feature_sha256,plan_artifact_id,plan_sha256,plan_revision,plan_id,approval_id,task_contract_id,
                       task_contract_sha256,authority_sha256,request_hash,manifest_binding_json,baseline_repository_json,
                       final_inspection_json,status,classification,1,started_at,finished_at,created_at,updated_at
                FROM verification_attempts_legacy""")
            conn.execute("DROP TABLE verification_attempts_legacy")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._writer_lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.execute("COMMIT")
            except BaseException as exc:
                # Once BEGIN succeeds, every exceptional exit must undo the
                # entire unit of work.  Rollback failure must not hide the
                # original domain, SQLite, or programming exception.
                if self._connection.in_transaction:
                    try:
                        self._connection.execute("ROLLBACK")
                    except BaseException:
                        # A failing SQL rollback must not replace the original
                        # exception.  The connection API provides a second,
                        # independent way to leave the transaction boundary.
                        try:
                            self._connection.rollback()
                        except BaseException:
                            pass
                if isinstance(exc, DomainFailure):
                    raise
                if isinstance(exc, sqlite3.IntegrityError):
                    raise ConflictFailure(
                        f"workflow record conflicts with an existing record: {exc}") from exc
                if isinstance(exc, sqlite3.OperationalError):
                    raise PersistenceFailure(f"workflow database is unavailable: {exc}") from exc
                if isinstance(exc, sqlite3.Error):
                    raise PersistenceFailure(f"workflow database error: {exc}") from exc
                raise

    @staticmethod
    def _require_enum(value: Any, enum_type: type) -> Any:
        try:
            return value if isinstance(value, enum_type) else enum_type(value)
        except ValueError as exc:
            raise ValidationFailure(f"invalid {enum_type.__name__}: {value!r}") from exc

    @staticmethod
    def _row_json(value: str | None) -> Any:
        return json.loads(value) if value is not None else None

    def _event_unlocked(
        self,
        conn: sqlite3.Connection,
        workflow_id: str,
        event_type: str,
        *,
        stage: Stage | None = None,
        artifact_id: str | None = None,
        execution_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> WorkflowEvent:
        previous = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()[0]
        sequence = int(previous) + 1
        created_at = _now()
        event_id = str(uuid.uuid4())
        safe_payload = sanitize_payload(payload or {}, self.secret_values)
        conn.execute(
            """INSERT INTO events
            (id, workflow_id, sequence, type, stage, artifact_id, execution_id, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, workflow_id, sequence, event_type, stage.value if stage else None,
             artifact_id, execution_id, _json(safe_payload), created_at),
        )
        return WorkflowEvent(event_id, workflow_id, sequence, event_type, stage, artifact_id,
                             execution_id, safe_payload, created_at)

    def create_workflow(
        self,
        repository_path: str | os.PathLike[str],
        *,
        provider: str = "codex-cli",
        configuration_snapshot: Mapping[str, Any] | None = None,
        workflow_id: str | None = None,
        feature_content: bytes | None = None,
        feature_path: str | os.PathLike[str] | None = None,
        lifecycle_version: LifecycleVersion | str = LifecycleVersion.HISTORICAL,
        stage: Stage | str = Stage.PRD,
    ) -> Workflow:
        if not provider:
            raise ValidationFailure("provider is required")
        snapshot = sanitize_configuration_snapshot(configuration_snapshot or {}, self.secret_values)
        lifecycle_version = self._require_enum(lifecycle_version, LifecycleVersion)
        stage = self._require_enum(stage, Stage)
        workflow_id = workflow_id or str(uuid.uuid4())
        now = _now()
        with self._transaction() as conn:
            retained_feature_path: Path | None = None
            feature_sha256: str | None = None
            if feature_content is not None:
                if not isinstance(feature_content, bytes):
                    raise ValidationFailure("feature_content must be bytes")
                retained_feature_path = self._workspace_file(
                    feature_path
                    or self.workspace_path / "workflows" / workflow_id / "input" / "feature-request.md",
                    label="feature input",
                )
                try:
                    retained_feature_path.parent.mkdir(parents=True, exist_ok=True)
                    if retained_feature_path.exists():
                        if retained_feature_path.read_bytes() != feature_content:
                            raise ConflictFailure("feature input destination is already immutable")
                    else:
                        retained_feature_path.write_bytes(feature_content)
                except OSError as exc:
                    raise PersistenceFailure(f"could not retain feature request: {exc}") from exc
                feature_sha256 = hashlib.sha256(feature_content).hexdigest()
            conn.execute(
                """INSERT INTO workflows
                (id, repository_path, provider, stage, status, created_at, updated_at,
                 configuration_snapshot, current_artifact_revision, feature_input_path, feature_input_sha256, lifecycle_version)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)""",
                (workflow_id, str(Path(repository_path).expanduser().resolve()), provider,
                 stage.value, WorkflowStatus.CREATED.value, now, now, _json(snapshot),
                 str(retained_feature_path) if retained_feature_path else None, feature_sha256, lifecycle_version.value),
            )
            if lifecycle_version is LifecycleVersion.V2:
                conn.execute(
                    """INSERT INTO repository_state (key, value) VALUES ('selected_workflow_id', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                    (workflow_id,),
                )
            self._event_unlocked(conn, workflow_id, "workflow.created", stage=stage,
                                 payload={
                                     "provider": provider, "lifecycle_version": lifecycle_version.value,
                                     **({
                                         "feature_input_path": str(retained_feature_path),
                                         "feature_input_sha256": feature_sha256,
                                     } if retained_feature_path else {}),
                                 })
        return self.get_workflow(workflow_id)

    def get_selected_workflow_id(self) -> str | None:
        """Return the repository-local selected workflow pointer, if present.

        Interpretation and validation of the stored value are deliberately a
        CLI/service concern so a stale pointer is never silently repaired.
        """
        row = self._connection.execute(
            "SELECT value FROM repository_state WHERE key = 'selected_workflow_id'"
        ).fetchone()
        return row["value"] if row is not None else None

    def set_selected_workflow_id(self, workflow_id: str) -> None:
        """Atomically select an existing workflow in this repository database."""
        try:
            uuid.UUID(workflow_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValidationFailure("invalid workflow id") from exc
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM workflows WHERE id = ?", (workflow_id,)).fetchone() is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            conn.execute(
                """INSERT INTO repository_state (key, value) VALUES ('selected_workflow_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (workflow_id,),
            )

    def get_workflow(self, workflow_id: str) -> Workflow:
        row = self._connection.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"workflow not found: {workflow_id}")
        return Workflow(row["id"], row["repository_path"], row["provider"],
                        Stage(row["stage"]), WorkflowStatus(row["status"]), row["created_at"],
                        row["updated_at"], self._row_json(row["configuration_snapshot"]),
                        row["current_artifact_revision"], row["feature_input_path"],
                        row["feature_input_sha256"], LifecycleVersion(row["lifecycle_version"]))

    @staticmethod
    def _require_no_unresolved_verification_unlocked(
        conn: sqlite3.Connection, workflow_id: str,
    ) -> None:
        """Prevent generic mutations from bypassing unresolved VERIFY ownership."""
        unresolved = conn.execute("""SELECT 1
            FROM workspace_operation_leases
            WHERE workflow_id=? AND operation_kind='verification'
            UNION ALL
            SELECT 1 FROM verification_attempts
            WHERE workflow_id=? AND status IN ('verifying','unknown')
            LIMIT 1""", (workflow_id, workflow_id)).fetchone()
        if unresolved is not None:
            raise ConflictFailure(
                "workflow has unresolved verification ownership; use verification-specific persistence")

    def set_workflow_state(
        self,
        workflow_id: str,
        *,
        stage: Stage | str | None = None,
        status: WorkflowStatus | str,
        event_type: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Workflow:
        status = self._require_enum(status, WorkflowStatus)
        stage = self._require_enum(stage, Stage) if stage is not None else None
        now = _now()
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM workflows WHERE id = ?", (workflow_id,)).fetchone() is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            if stage is None:
                conn.execute("UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                             (status.value, now, workflow_id))
                event_stage = None
            else:
                conn.execute("UPDATE workflows SET stage = ?, status = ?, updated_at = ? WHERE id = ?",
                             (stage.value, status.value, now, workflow_id))
                event_stage = stage
            if event_type:
                self._event_unlocked(conn, workflow_id, event_type, stage=event_stage, payload=payload)
        return self.get_workflow(workflow_id)

    def cancel_v2_workflow(self, workflow_id: str, *, actor: str = "human") -> Workflow:
        """Durably abandon an active V2 workflow without touching its evidence.

        Repeating an explicit cancellation is intentionally idempotent: no
        second event is added and no historical artifact is changed.
        """
        now = _now()
        with self._transaction() as conn:
            row = conn.execute("SELECT stage, status, lifecycle_version FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
            if row is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            if LifecycleVersion(row["lifecycle_version"]) is not LifecycleVersion.V2:
                raise ConflictFailure("workflow cancellation is supported only for V2 workflows")
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            status = WorkflowStatus(row["status"])
            if status is WorkflowStatus.CANCELLED:
                return self.get_workflow(workflow_id)
            if is_terminal_workflow_status(status):
                raise ConflictFailure("workflow is already terminal and cannot be cancelled")
            stage = Stage(row["stage"])
            conn.execute("UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                         (WorkflowStatus.CANCELLED.value, now, workflow_id))
            self._event_unlocked(conn, workflow_id, "workflow.cancelled", stage=stage,
                                 payload={"actor": actor})
        return self.get_workflow(workflow_id)

    def _create_session_unlocked(self, conn: sqlite3.Connection, workflow_id: str, provider: str,
                                 role: Role, logical_session_id: str | None = None,
                                 *, task_id: str | None = None, cycle_id: str | None = None,
                                 work_kind: WorkKind | None = None) -> Session:
        now = _now()
        session = Session(str(uuid.uuid4()), workflow_id, logical_session_id or str(uuid.uuid4()),
                          role, provider, None, now, now)
        conn.execute(
            """INSERT INTO sessions
            (id, workflow_id, logical_session_id, role, provider, provider_session_id,
             task_id, cycle_id, work_kind, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session.id, workflow_id, session.logical_session_id, role.value, provider, None,
             task_id, cycle_id, work_kind.value if work_kind else None, now, now),
        )
        return Session(session.id, session.workflow_id, session.logical_session_id, session.role,
                       session.provider, session.provider_session_id, session.created_at,
                       session.updated_at, task_id, cycle_id, work_kind)

    def create_generation_intent(
        self,
        workflow_id: str,
        stage: Stage | str,
        *,
        request_hash: str,
        provider: str = "codex-cli",
        role: Role | str = Role.PLANNER,
        revision: int | None = None,
        artifact_path: str | os.PathLike[str] | None = None,
        capability_report: Mapping[str, Any] | None = None,
    ) -> GenerationIntent:
        stage = self._require_enum(stage, Stage)
        role = self._require_enum(role, Role)
        if stage is Stage.READY_FOR_WAVE_2:
            raise ValidationFailure("ready_for_wave_2 is not a generatable stage")
        if not request_hash:
            raise ValidationFailure("request_hash is required")
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM workflows WHERE id = ?", (workflow_id,)).fetchone() is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            existing = None
            if revision is None:
                # A retry has no revision argument, so recover the exact prior
                # operation by its request hash before allocating a new revision.
                existing = conn.execute(
                    """SELECT o.* FROM operations o
                    LEFT JOIN executions e ON e.id = o.related_record_id
                    LEFT JOIN artifacts a ON a.id = o.related_record_id
                    LEFT JOIN executions ae ON ae.id = a.source_execution_id
                    WHERE o.workflow_id = ? AND o.kind = 'generate'
                      AND COALESCE(e.request_hash, ae.request_hash) = ?
                      AND o.idempotency_key LIKE ?
                    ORDER BY o.created_at DESC LIMIT 1""",
                    (workflow_id, request_hash,
                     f"workflow:{workflow_id}:stage:{stage.value}:revision:%:generate"),
                ).fetchone()
            if existing is not None:
                revision = int(existing["idempotency_key"].split(":revision:", 1)[1].split(":", 1)[0])
            elif revision is None:
                revision = int(conn.execute(
                    "SELECT COALESCE(MAX(revision), 0) FROM artifacts WHERE workflow_id = ? AND stage = ?",
                    (workflow_id, stage.value),
                ).fetchone()[0]) + 1
            if revision < 1:
                raise ValidationFailure("artifact revision must be positive")
            key = f"workflow:{workflow_id}:stage:{stage.value}:revision:{revision}:generate"
            intent_artifact_path = self._generation_artifact_path(
                workflow_id, stage, revision, artifact_path
            )
            if existing is None:
                existing = conn.execute("SELECT * FROM operations WHERE idempotency_key = ?", (key,)).fetchone()
            # A failed attempt has no canonical artifact.  A retry must retain
            # the intended artifact revision while receiving a fresh execution.
            prior_execution = (conn.execute("SELECT lifecycle FROM executions WHERE id = ?", (existing["related_record_id"],)).fetchone() if existing is not None else None)
            if existing is not None and (existing["status"] == OperationStatus.UNKNOWN.value or (prior_execution is not None and prior_execution["lifecycle"] in (ExecutionLifecycle.FAILED.value, ExecutionLifecycle.UNKNOWN.value))):
                existing = None
                key = f"{key}:attempt:{uuid.uuid4()}"
            if existing is not None:
                operation = self._operation_from_row(existing)
                if operation.related_record_id is None:
                    raise PersistenceFailure("generation operation has no execution record")
                execution_row = conn.execute(
                    "SELECT * FROM executions WHERE id = ?", (operation.related_record_id,)
                ).fetchone()
                if execution_row is None and operation.status is OperationStatus.COMPLETED:
                    artifact_row = conn.execute(
                        "SELECT source_execution_id FROM artifacts WHERE id = ?",
                        (operation.related_record_id,),
                    ).fetchone()
                    if artifact_row is not None:
                        execution_row = conn.execute(
                            "SELECT * FROM executions WHERE id = ?",
                            (artifact_row["source_execution_id"],),
                        ).fetchone()
                if execution_row is None:
                    raise PersistenceFailure("generation operation has no execution record")
                execution = self._execution_from_row(execution_row)
                return GenerationIntent(operation, execution, True)
            session = self._create_session_unlocked(conn, workflow_id, provider, role)
            execution_id = str(uuid.uuid4())
            now = _now()
            conn.execute(
                """INSERT INTO executions
                (id, workflow_id, session_id, role, provider_execution_id, request_hash, lifecycle,
                 capability_report, terminal_result, failure_classification, failure_detail, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, ?, ?)""",
                (execution_id, workflow_id, session.id, role.value, request_hash,
                 ExecutionLifecycle.INTENT.value, _json(sanitize_payload(capability_report or {}, self.secret_values)),
                 now, now),
            )
            operation = Operation(str(uuid.uuid4()), key, "generate", workflow_id,
                                  OperationStatus.PENDING, execution_id, now, now)
            conn.execute(
                """INSERT INTO operations
                (id, idempotency_key, kind, workflow_id, status, related_record_id,
                 intent_stage, intent_revision, intent_artifact_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (operation.id, key, operation.kind, workflow_id, operation.status.value,
                 execution_id, stage.value, revision, str(intent_artifact_path), now, now),
            )
            self._event_unlocked(conn, workflow_id, "stage.started", stage=stage,
                                 execution_id=execution_id, payload={"revision": revision})
            self._event_unlocked(conn, workflow_id, "agent.execution.started", stage=stage,
                                 execution_id=execution_id, payload={"role": role.value})
            execution = self.get_execution(execution_id)
        return GenerationIntent(operation, execution)

    def start_execution(self, execution_id: str, *, provider_execution_id: str | None = None) -> Execution:
        now = _now()
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
            if row is None:
                raise NotFoundFailure(f"execution not found: {execution_id}")
            self._require_no_unresolved_verification_unlocked(conn, row["workflow_id"])
            if row["lifecycle"] not in (ExecutionLifecycle.INTENT.value, ExecutionLifecycle.RUNNING.value):
                return self._execution_from_row(row)
            conn.execute("UPDATE executions SET lifecycle = ?, provider_execution_id = COALESCE(?, provider_execution_id), updated_at = ? WHERE id = ?",
                         (ExecutionLifecycle.RUNNING.value, provider_execution_id, now, execution_id))
        return self.get_execution(execution_id)

    def next_generation_revision(self, workflow_id: str, stage: Stage | str) -> int:
        """Return a revision not used by an artifact or an earlier attempt."""

        stage = self._require_enum(stage, Stage)
        if stage is Stage.READY_FOR_WAVE_2:
            raise ValidationFailure("ready_for_wave_2 is not a generatable stage")
        row = self._connection.execute(
            """SELECT MAX(revision) AS artifact_revision,
                      (SELECT MAX(intent_revision) FROM operations
                       WHERE workflow_id = ? AND kind = 'generate' AND intent_stage = ?) AS intent_revision
               FROM artifacts WHERE workflow_id = ? AND stage = ?""",
            (workflow_id, stage.value, workflow_id, stage.value),
        ).fetchone()
        highest = max(row["artifact_revision"] or 0, row["intent_revision"] or 0)
        return max(highest + 1, 1)

    def next_artifact_revision(self, workflow_id: str, stage: Stage | str) -> int:
        stage = self._require_enum(stage, Stage)
        row = self._connection.execute("SELECT COALESCE(MAX(revision), 0) FROM artifacts WHERE workflow_id = ? AND stage = ?", (workflow_id, stage.value)).fetchone()
        return int(row[0]) + 1

    def plan_path(self, workflow_id: str, revision: int) -> Path:
        name = "002-plan.json" if revision == 1 else f"002-plan-r{revision:03d}.json"
        return self.workspace_path / "workflows" / workflow_id / "artifacts" / name

    def feature_contract_path(self, workflow_id: str, revision: int) -> Path:
        name = "001-feature-contract.json" if revision == 1 else f"001-feature-contract-r{revision:03d}.json"
        return self.workspace_path / "workflows" / workflow_id / "artifacts" / name

    def list_plan_change_requests(self, workflow_id: str) -> list[PlanChangeRequest]:
        rows = self._connection.execute("SELECT * FROM plan_change_requests WHERE workflow_id = ? ORDER BY sequence", (workflow_id,)).fetchall()
        return [self._plan_change_request_from_row(row) for row in rows]

    def get_open_plan_change_request(self, workflow_id: str) -> PlanChangeRequest | None:
        rows = self._connection.execute("SELECT * FROM plan_change_requests WHERE workflow_id = ? AND replacement_plan_artifact_id IS NULL ORDER BY sequence", (workflow_id,)).fetchall()
        if len(rows) > 1:
            raise PersistenceFailure("workflow has multiple open Plan change requests")
        return self._plan_change_request_from_row(rows[0]) if rows else None

    def load_approved_v2_plan_authority(self, workflow_id: str, *, allow_human_attention: bool = False) -> ApprovedV2PlanAuthority:
        """Load the exact, currently approved V2 authority for task selection.

        This is intentionally a read-only projection: task definitions remain
        in the immutable Plan artifact and no caller-provided hash is trusted.
        """
        workflow = self.get_workflow(workflow_id)
        if (workflow.lifecycle_version is not LifecycleVersion.V2
                or not ((workflow.stage is Stage.PLAN and workflow.status is WorkflowStatus.PLAN_APPROVED)
                        or (workflow.stage is Stage.TASK_EXECUTION and workflow.status in {
                            WorkflowStatus.IMPLEMENTATION_FAILED,
                            WorkflowStatus.IMPLEMENTATION_COMPLETED,
                            WorkflowStatus.VERIFYING,
                            WorkflowStatus.VERIFICATION_FAILED,
                            WorkflowStatus.TASK_VERIFIED,
                        })
                        or (allow_human_attention and workflow.stage is Stage.TASK_EXECUTION
                            and workflow.status is WorkflowStatus.HUMAN_ATTENTION))):
            raise ConflictFailure("workflow is not at V2 PLAN_APPROVED authority")
        plans = self.list_artifacts(workflow.id, Stage.PLAN)
        if not plans:
            raise ValidationFailure("approved Plan artifact is required")
        highest_revision = max(item.revision for item in plans)
        current = [item for item in plans if item.revision == highest_revision]
        if len(current) != 1:
            raise PersistenceFailure("workflow has ambiguous current Plan authority")
        plan_artifact = current[0]
        if plan_artifact.approval_state is not ApprovalState.APPROVED:
            raise ConflictFailure("current Plan artifact is not approved")
        approval = self.get_approval_for_artifact(plan_artifact.id)
        if (approval is None or approval.workflow_id != workflow.id
                or approval.artifact_id != plan_artifact.id
                or approval.decision is not ApprovalDecision.APPROVED):
            raise PersistenceFailure("current Plan approval is missing or invalid")
        if self.get_open_plan_change_request(workflow.id) is not None:
            raise ConflictFailure("Plan authority has an unresolved change request")

        features = self.list_artifacts(workflow.id, Stage.INTAKE)
        if not features:
            raise ValidationFailure("READY Feature Contract artifact is required")
        feature_artifact = features[-1]
        if feature_artifact.approval_state is not ApprovalState.NOT_REQUIRED:
            raise ValidationFailure("current Feature Contract is not an Intake authority")
        try:
            feature_payload = json.loads(self.read_artifact(feature_artifact.id))
        except json.JSONDecodeError as exc:
            raise ValidationFailure("Feature Contract artifact is not valid JSON") from exc
        feature = FeatureContract.parse(feature_payload, workflow_id=workflow.id)
        if feature.outcome is not IntakeOutcome.READY or not feature.requirements or not feature.acceptance_criteria or feature.open_questions:
            raise ValidationFailure("current Feature Contract is not READY")
        try:
            plan_payload = json.loads(self.read_artifact(plan_artifact.id))
        except json.JSONDecodeError as exc:
            raise ValidationFailure("Plan artifact is not valid JSON") from exc
        plan = Plan.parse(plan_payload, workflow_id=workflow.id, revision=plan_artifact.revision,
                          feature_contract_artifact_id=feature_artifact.id,
                          feature_contract_sha256=feature_artifact.sha256,
                          repository_path=workflow.repository_path)
        return ApprovedV2PlanAuthority(workflow, feature_artifact, feature,
                                       plan_artifact, plan, approval)

    def load_successful_implementation_producer(
        self, workflow_id: str, operation_id: str, task_contract_id: str,
        task_contract_sha256: str,
    ) -> SuccessfulImplementationProducer:
        """Load only durable MDS #3 IMPLEMENT evidence eligible for VERIFY.

        The join deliberately proves all relationships at the persistence
        boundary, so callers cannot turn an arbitrary completed operation ID
        into verification authority.
        """
        if not operation_id:
            raise ValidationFailure("verification requires a producer operation")
        row = self._connection.execute("""SELECT o.id AS operation_id, o.kind AS operation_kind,
            o.workflow_id AS operation_workflow_id, o.status AS operation_status,
            o.related_record_id AS operation_execution_id, a.*, e.workflow_id AS execution_workflow_id,
            e.lifecycle AS execution_lifecycle, e.role AS execution_role, e.request_hash AS execution_request_hash,
            w.repository_path AS workflow_repository_path
            FROM operations o
            LEFT JOIN implementation_attempts a ON a.operation_id=o.id
            LEFT JOIN executions e ON e.id=a.execution_id
            LEFT JOIN workflows w ON w.id=o.workflow_id
            WHERE o.id=?""", (operation_id,)).fetchone()
        if row is None:
            raise ValidationFailure("verification producer operation is missing")
        if (row["operation_kind"] != "implementation" or row["operation_status"] != OperationStatus.COMPLETED.value
                or row["operation_workflow_id"] != workflow_id or row["workflow_id"] != workflow_id
                or row["execution_workflow_id"] != workflow_id or row["operation_execution_id"] != row["execution_id"]
                or row["execution_lifecycle"] != ExecutionLifecycle.COMPLETED.value
                or row["execution_role"] != Role.DEVELOPER.value):
            raise ValidationFailure("verification producer operation is not a successful IMPLEMENT operation")
        if (row["result_classification"] != "completed_changed" or row["status"] not in {"completed", "succeeded"}
                or row["task_contract_id"] != task_contract_id
                or row["task_contract_sha256"] != task_contract_sha256
                or row["request_hash"] != row["execution_request_hash"]):
            raise ValidationFailure("verification producer operation does not match the selected implementation")
        raw_final = row["final_repository_json"]
        try:
            final = json.loads(raw_final) if raw_final else None
        except json.JSONDecodeError as exc:
            raise ValidationFailure("verification producer final repository evidence is invalid") from exc
        if not isinstance(final, dict) or set(final) != {
                "canonical_root", "git_toplevel", "git_dir", "git_common_dir", "head_sha", "branch_name",
                "detached", "status_sha256", "diff_sha256", "untracked_manifest_sha256", "changed_paths",
                "changed_paths_sha256", "local_git_config_sha256", "fingerprint"}:
            raise ValidationFailure("verification producer final repository evidence is missing or invalid")
        fingerprint = final.get("fingerprint")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValidationFailure("verification producer final repository fingerprint is invalid")
        string_fields = set(final) - {"changed_paths", "detached"}
        if (any(not isinstance(final[field], str) for field in string_fields)
                or not isinstance(final["detached"], bool)
                or not isinstance(final["changed_paths"], list)
                or any(not isinstance(path, str) for path in final["changed_paths"])
                or final["canonical_root"] != str(Path(row["workflow_repository_path"]).resolve())):
            raise ValidationFailure("verification producer final repository evidence is invalid")
        recomputed = hashlib.sha256(_json({key: final[key] for key in final if key != "fingerprint"}).encode("utf-8")).hexdigest()
        if fingerprint != recomputed:
            raise ValidationFailure("verification producer final repository fingerprint does not match its evidence")
        digest = hashlib.sha256(_json(final).encode("utf-8")).hexdigest()
        return SuccessfulImplementationProducer(
            operation_id=row["operation_id"], execution_id=row["execution_id"], workflow_id=workflow_id,
            feature_artifact_id=row["feature_artifact_id"], feature_sha256=row["feature_sha256"],
            plan_artifact_id=row["plan_artifact_id"], plan_sha256=row["plan_sha256"],
            plan_revision=row["plan_revision"], plan_id=row["plan_id"], approval_id=row["approval_id"],
            task_contract_id=row["task_contract_id"], task_contract_sha256=row["task_contract_sha256"],
            implementation_request_hash=row["request_hash"], final_repository=final,
            final_repository_sha256=digest, final_repository_fingerprint=fingerprint,
        )

    def list_task_implementation_states(
        self, workflow_id: str, plan_artifact_id: str
    ) -> list[TaskImplementationState]:
        rows = self._connection.execute(
            """SELECT * FROM task_implementation_states
               WHERE workflow_id = ? AND plan_artifact_id = ? ORDER BY task_contract_id""",
            (workflow_id, plan_artifact_id),
        ).fetchall()
        return [self._task_implementation_state_from_row(row) for row in rows]

    def retry_safe_failed_task_ids(self, workflow_id: str, plan_artifact_id: str) -> frozenset[str]:
        rows = self._connection.execute("""SELECT a.task_contract_id FROM implementation_attempts a
            WHERE a.workflow_id=? AND a.plan_artifact_id=? AND a.status='failed'
              AND a.workspace_changed=0 AND a.id=(SELECT b.id FROM implementation_attempts b
                WHERE b.workflow_id=a.workflow_id AND b.plan_artifact_id=a.plan_artifact_id
                  AND b.task_contract_id=a.task_contract_id ORDER BY b.sequence DESC LIMIT 1)
              AND NOT EXISTS (SELECT 1 FROM workspace_operation_leases l WHERE l.attempt_id=a.id)""",
            (workflow_id, plan_artifact_id)).fetchall()
        return frozenset(row["task_contract_id"] for row in rows)

    def put_task_implementation_state(
        self, workflow_id: str, plan_artifact_id: str, plan_sha256: str,
        task_contract_id: str, task_contract_sha256: str,
        status: TaskImplementationStatus | str, *, selected_at: str | None = None,
    ) -> TaskImplementationState:
        """Persist an operational state only (used by later lifecycle slices/tests)."""
        status = self._require_enum(status, TaskImplementationStatus)
        self._require_sha256(plan_sha256, "plan_sha256")
        self._require_sha256(task_contract_sha256, "task_contract_sha256")
        if not task_contract_id:
            raise ValidationFailure("task_contract_id is required")
        with self._transaction() as conn:
            workflow = conn.execute(
                "SELECT lifecycle_version FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
            if workflow is None or workflow["lifecycle_version"] != LifecycleVersion.V2.value:
                raise ConflictFailure("task implementation states are V2-only")
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            artifact = conn.execute(
                "SELECT * FROM artifacts WHERE id = ? AND workflow_id = ?",
                (plan_artifact_id, workflow_id),
            ).fetchone()
            if artifact is None or artifact["stage"] != Stage.PLAN.value:
                raise ValidationFailure("task implementation state requires a workflow Plan artifact")
            if artifact["sha256"] != plan_sha256:
                raise ValidationFailure("task implementation state Plan hash does not match artifact")
            now = _now()
            existing = conn.execute(
                """SELECT * FROM task_implementation_states WHERE workflow_id = ?
                   AND plan_artifact_id = ? AND task_contract_id = ?""",
                (workflow_id, plan_artifact_id, task_contract_id),
            ).fetchone()
            if existing is None:
                state_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO task_implementation_states
                    (id, workflow_id, plan_artifact_id, plan_sha256, task_contract_id,
                     task_contract_sha256, status, selected_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (state_id, workflow_id, plan_artifact_id, plan_sha256, task_contract_id,
                     task_contract_sha256, status.value, selected_at, now),
                )
            else:
                state_id = existing["id"]
                conn.execute(
                    """UPDATE task_implementation_states SET plan_sha256 = ?,
                       task_contract_sha256 = ?, status = ?, selected_at = ?, updated_at = ? WHERE id = ?""",
                    (plan_sha256, task_contract_sha256, status.value, selected_at, now, state_id),
                )
            row = conn.execute("SELECT * FROM task_implementation_states WHERE id = ?", (state_id,)).fetchone()
        return self._task_implementation_state_from_row(row)

    def create_implementation_intent(self, workflow_id: str, *, repository_key: str,
                                     canonical_root: str, task_contract_id: str,
                                     task_contract_sha256: str, request_hash: str,
                                     baseline: Mapping[str, Any], owner_instance_id: str,
                                     owner_pid: int, owner_host_id: str, owner_boot_id: str | None = None,
                                     requested_profile: str = "fake",
                                     requested_provider: str = "fake", requested_model: str | None = None,
                                     requested_reasoning: str | None = None) -> dict[str, str]:
        """Atomically create the only Slice-2 writer intent and its durable lease.

        The authority projection is deliberately reloaded inside BEGIN IMMEDIATE;
        caller-provided Plan/Feature hashes never become authority.
        """
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            authority = self.load_approved_v2_plan_authority(workflow_id)
            task = next((item for item in authority.plan.tasks if item.id == task_contract_id), None)
            if task is None or task.payload_sha256() != task_contract_sha256:
                raise ConflictFailure("selected Task Contract no longer matches approved Plan")
            if conn.execute("SELECT 1 FROM workspace_operation_leases WHERE repository_key = ?", (repository_key,)).fetchone():
                raise ConflictFailure("target workspace already has an unresolved writer lease")
            old = conn.execute("""SELECT status, workspace_changed FROM implementation_attempts
                WHERE workflow_id=? AND plan_artifact_id=? AND task_contract_id=? ORDER BY sequence DESC LIMIT 1""",
                (workflow_id, authority.plan_artifact.id, task_contract_id)).fetchone()
            state = conn.execute("""SELECT status FROM task_implementation_states WHERE workflow_id=?
                AND plan_artifact_id=? AND task_contract_id=?""", (workflow_id, authority.plan_artifact.id, task_contract_id)).fetchone()
            if state and state["status"] not in ("pending", "implementation_failed"):
                raise ConflictFailure("selected Task Contract is not pending")
            if state and state["status"] == "implementation_failed" and (old is None or old["status"] != "failed" or old["workspace_changed"] != 0):
                raise ConflictFailure("failed Task Contract lacks retry-safe attempt evidence")
            sequence = int(conn.execute("""SELECT COALESCE(MAX(sequence), 0)+1 FROM implementation_attempts
                WHERE workflow_id=? AND plan_artifact_id=? AND task_contract_id=?""",
                (workflow_id, authority.plan_artifact.id, task_contract_id)).fetchone()[0])
            now, attempt_id, lease_id, execution_id, operation_id = _now(), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
            session = self._create_session_unlocked(conn, workflow_id, requested_provider, Role.DEVELOPER)
            conn.execute("""INSERT INTO executions (id,workflow_id,session_id,role,provider_execution_id,request_hash,lifecycle,capability_report,terminal_result,failure_classification,failure_detail,created_at,updated_at)
                VALUES (?,?,?,?,NULL,?,'intent','{}',NULL,NULL,NULL,?,?)""", (execution_id, workflow_id, session.id, Role.DEVELOPER.value, request_hash, now, now))
            conn.execute("""INSERT INTO operations (id,idempotency_key,kind,workflow_id,status,related_record_id,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""", (operation_id, f"implementation:{attempt_id}", "implementation", workflow_id, "pending", execution_id, now, now))
            conn.execute("""INSERT INTO implementation_attempts (id,workflow_id,execution_id,operation_id,lease_id,feature_artifact_id,feature_sha256,plan_artifact_id,plan_sha256,plan_revision,plan_id,approval_id,task_contract_id,task_contract_sha256,sequence,request_hash,requested_profile,requested_provider,requested_model,requested_reasoning,started_at,status,baseline_repository_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'preparing',?,?,?)""",
                (attempt_id,workflow_id,execution_id,operation_id,lease_id,authority.feature_contract_artifact.id,authority.feature_contract_artifact.sha256,authority.plan_artifact.id,authority.plan_artifact.sha256,authority.plan.revision,authority.plan.id,authority.approval.id,task_contract_id,task_contract_sha256,sequence,request_hash,requested_profile,requested_provider,requested_model,requested_reasoning,now,_json(baseline),now,now))
            conn.execute("""INSERT INTO workspace_operation_leases
                (repository_key,lease_id,operation_kind,attempt_id,operation_id,workflow_id,canonical_root,
                 owner_instance_id,owner_pid,owner_host_id,owner_boot_id,acquired_at,updated_at)
                VALUES (?,?,'implementation',?,?,?,?,?,?,?,?,?,?)""",
                (repository_key,lease_id,attempt_id,operation_id,workflow_id,canonical_root,
                 owner_instance_id,owner_pid,owner_host_id,owner_boot_id,now,now))
            conn.execute("""INSERT INTO task_implementation_states (id,workflow_id,plan_artifact_id,plan_sha256,task_contract_id,task_contract_sha256,status,selected_at,updated_at)
                VALUES (?,?,?,?,?,?, 'implementing',?,?) ON CONFLICT(workflow_id,plan_artifact_id,task_contract_id)
                DO UPDATE SET status='implementing', selected_at=excluded.selected_at, updated_at=excluded.updated_at""",
                (str(uuid.uuid4()),workflow_id,authority.plan_artifact.id,authority.plan_artifact.sha256,task_contract_id,task_contract_sha256,now,now))
            conn.execute("UPDATE workflows SET stage=?, status=?, updated_at=? WHERE id=?", (Stage.TASK_EXECUTION.value, WorkflowStatus.IMPLEMENTING.value,now,workflow_id))
            self._event_unlocked(conn, workflow_id, "implementation.attempt.created", stage=Stage.TASK_EXECUTION, execution_id=execution_id, payload={"attempt_id":attempt_id,"lease_id":lease_id})
        return {"attempt_id": attempt_id, "lease_id": lease_id, "execution_id": execution_id,
                "operation_id": operation_id, "owner_instance_id": owner_instance_id}

    def record_implementation_provider_started(self, attempt_id: str, lease_id: str,
                                               evidence: Mapping[str, Any]) -> None:
        """Persist only process identity actually exposed by the runtime."""
        with self._transaction() as conn:
            row = conn.execute("SELECT execution_id FROM implementation_attempts WHERE id=? AND lease_id=?", (attempt_id, lease_id)).fetchone()
            if row is None:
                raise ConflictFailure("implementation attempt/lease ownership mismatch")
            pid = evidence.get("pid")
            group = evidence.get("process_group")
            start = evidence.get("process_start")
            if type(pid) is not int: pid = None
            if type(group) is not int: group = None
            now = _now()
            if not isinstance(start, str) or not start:
                start = None
            conn.execute("UPDATE workspace_operation_leases SET child_pid=?,child_process_start=?,child_process_group=?,updated_at=? WHERE attempt_id=? AND lease_id=? AND operation_kind='implementation'",
                         (pid, start, group, now, attempt_id, lease_id))
            conn.execute("UPDATE implementation_attempts SET started_at=?,status='running',updated_at=? WHERE id=?", (now, now, attempt_id))
            conn.execute("UPDATE executions SET lifecycle='running',updated_at=? WHERE id=?", (now, row["execution_id"]))

    def update_implementation_baseline(self, attempt_id: str, lease_id: str,
                                       baseline: Mapping[str, Any]) -> None:
        """Replace pre-acquisition evidence with the accepted pre-spawn baseline."""
        with self._transaction() as conn:
            result = conn.execute("UPDATE implementation_attempts SET baseline_repository_json=?,updated_at=? WHERE id=? AND lease_id=? AND status='preparing'",
                (_json(baseline), _now(), attempt_id, lease_id))
            if result.rowcount != 1:
                raise ConflictFailure("implementation baseline ownership mismatch")

    def finish_implementation_attempt(self, attempt_id: str, lease_id: str, *, status: str,
                                      classification: str, final: Mapping[str, Any] | None,
                                      workspace_changed: bool | None, owner_instance_id: str | None = None,
                                      error_detail: str | None = None,
                                      agent_result: Mapping[str, Any] | None = None,
                                      actual_provider: str | None = None, actual_model: str | None = None,
                                      actual_reasoning: str | None = None, provider_operation_ref: str | None = None,
                                      provider_session_ref: str | None = None, usage: Mapping[str, Any] | None = None,
                                      error_classification: str | None = None, release_lease: bool = True) -> None:
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM implementation_attempts WHERE id=? AND lease_id=?", (attempt_id, lease_id)).fetchone()
            if row is None: raise ConflictFailure("implementation attempt/lease ownership mismatch")
            self._require_no_unresolved_verification_unlocked(conn, row["workflow_id"])
            lease = None
            if release_lease:
                if not isinstance(owner_instance_id, str) or not owner_instance_id:
                    raise ValidationFailure("implementation lease release requires owner_instance_id")
                lease = conn.execute("""SELECT repository_key FROM workspace_operation_leases
                    WHERE lease_id=? AND attempt_id=? AND operation_id=? AND operation_kind='implementation'
                      AND owner_instance_id=?""", (lease_id, attempt_id, row["operation_id"], owner_instance_id)).fetchone()
                if lease is None:
                    raise ConflictFailure("implementation lease ownership mismatch")
            task_status = "implementation_completed" if classification == "completed_changed" else ("pending" if classification == "baseline_refusal" else ("implementation_failed" if classification == "failed_unchanged" else "implementation_unknown"))
            workflow_status = (WorkflowStatus.PLAN_APPROVED.value if classification == "baseline_refusal" else (WorkflowStatus.IMPLEMENTATION_COMPLETED.value if task_status == "implementation_completed" else (WorkflowStatus.IMPLEMENTATION_FAILED.value if task_status == "implementation_failed" else WorkflowStatus.HUMAN_ATTENTION.value)))
            now = _now()
            conn.execute("""UPDATE implementation_attempts SET status=?,result_classification=?,finished_at=?,final_repository_json=?,workspace_changed=?,changed_paths_json=?,agent_result_json=?,actual_provider=?,actual_model=?,actual_reasoning=?,provider_operation_ref=?,provider_session_ref=?,usage_json=?,error_classification=?,error_detail=?,updated_at=? WHERE id=?""",
                (status,classification,now,_json(final) if final else None,None if workspace_changed is None else int(workspace_changed),_json(final.get("changed_paths", [])) if final else None,_json(agent_result or {}),actual_provider,actual_model,actual_reasoning,provider_operation_ref,provider_session_ref,_json(usage) if usage else None,error_classification,error_detail,now,attempt_id))
            conn.execute("UPDATE executions SET lifecycle=?, terminal_result=?, failure_detail=?, updated_at=? WHERE id=?", ("completed" if task_status == "implementation_completed" else ("failed" if task_status == "implementation_failed" else "unknown"),_json({"classification":classification}),error_detail,now,row["execution_id"]))
            conn.execute("UPDATE operations SET status=?, updated_at=? WHERE id=?", ("completed" if task_status == "implementation_completed" else "unknown",now,row["operation_id"]))
            conn.execute("UPDATE task_implementation_states SET status=?,updated_at=? WHERE workflow_id=? AND plan_artifact_id=? AND task_contract_id=?", (task_status,now,row["workflow_id"],row["plan_artifact_id"],row["task_contract_id"]))
            conn.execute("UPDATE workflows SET stage=?,status=?,updated_at=? WHERE id=?", (Stage.PLAN.value if classification == "baseline_refusal" else Stage.TASK_EXECUTION.value,workflow_status,now,row["workflow_id"]))
            if release_lease:
                # The terminal projection and release share one transaction,
                # but the lease must still match every persisted owner binding.
                deleted = conn.execute("""DELETE FROM workspace_operation_leases
                    WHERE repository_key=? AND lease_id=? AND attempt_id=? AND operation_id=?
                      AND operation_kind='implementation' AND owner_instance_id=?""",
                    (lease["repository_key"], lease_id, attempt_id, row["operation_id"], owner_instance_id))
                if deleted.rowcount != 1:
                    raise ConflictFailure("implementation lease ownership mismatch")

    def active_implementation_lease(self, workflow_id: str) -> Mapping[str, Any] | None:
        """Return one unresolved V2 writer lease joined to its attempt.

        This intentionally exposes raw persisted evidence only to the narrow
        recovery service; normal presentation must not display process IDs.
        """
        rows = self._connection.execute("""SELECT l.*, l.child_pid AS provider_pid,
            l.child_process_start AS provider_process_start,
            l.child_process_group AS provider_process_group, a.status AS attempt_status,
            a.result_classification, a.baseline_repository_json, a.workflow_id AS attempt_workflow_id,
            a.lease_id AS attempt_lease_id, a.task_contract_id, a.plan_artifact_id
            FROM workspace_operation_leases l JOIN implementation_attempts a ON a.id=l.attempt_id
            WHERE l.workflow_id=? AND l.operation_kind='implementation'""", (workflow_id,)).fetchall()
        if len(rows) > 1:
            raise PersistenceFailure("workflow has multiple unresolved writer leases")
        return dict(rows[0]) if rows else None

    def active_workspace_operation_lease(self, repository_key: str) -> Mapping[str, Any] | None:
        """Return the one non-expiring repository mutex, without interpreting it."""
        row = self._connection.execute(
            "SELECT * FROM workspace_operation_leases WHERE repository_key=?", (repository_key,)
        ).fetchone()
        return dict(row) if row is not None else None

    def release_workspace_operation_lease(self, *, repository_key: str, lease_id: str,
                                          attempt_id: str, operation_id: str,
                                          owner_instance_id: str) -> None:
        """Release a non-verification lease with exact persisted ownership.

        Verification release is intentionally unavailable through this generic
        surface.  Its terminal APIs must reconstruct verification authority and
        apply the lifecycle projection atomically with deletion.
        """
        with self._transaction() as conn:
            lease = conn.execute("""SELECT operation_kind,workflow_id FROM workspace_operation_leases
                WHERE repository_key=? AND lease_id=? AND attempt_id=? AND operation_id=?
                  AND owner_instance_id=?""",
                (repository_key, lease_id, attempt_id, operation_id, owner_instance_id)).fetchone()
            if lease is None:
                raise ConflictFailure("workspace operation lease ownership mismatch")
            linked_verification = conn.execute("""SELECT 1 FROM verification_attempts
                WHERE status IN ('verifying','unknown') AND
                  (id=? OR lease_id=? OR operation_id=? OR workflow_id=?) LIMIT 1""",
                (attempt_id, lease_id, operation_id, lease["workflow_id"])).fetchone()
            if lease["operation_kind"] == "verification" or linked_verification is not None:
                raise ConflictFailure(
                    "verification leases require an operation-specific terminal transition")
            result = conn.execute("""DELETE FROM workspace_operation_leases
                WHERE repository_key=? AND lease_id=? AND attempt_id=? AND operation_id=?
                  AND owner_instance_id=? AND operation_kind!='verification'""",
                (repository_key, lease_id, attempt_id, operation_id, owner_instance_id))
            if result.rowcount != 1:
                raise ConflictFailure("workspace operation lease ownership mismatch")

    def create_verification_intent(
        self, workflow_id: str, *, repository_key: str, canonical_root: str,
        producer_operation_id: str, task_contract_id: str, task_contract_sha256: str,
        authority_sha256: str, request_hash: str, manifest_binding: Mapping[str, Any],
        baseline: Mapping[str, Any], owner_instance_id: str, owner_pid: int,
        owner_host_id: str, owner_boot_id: str | None = None,
    ) -> dict[str, str]:
        """Persist VERIFY intent, its generic operation, and the common lease atomically.

        This method deliberately has no runner integration: a later slice may
        spawn only after this durable boundary exists.
        """
        self._require_sha256(authority_sha256, "authority_sha256")
        self._require_sha256(request_hash, "request_hash")
        if not all(isinstance(value, str) and value for value in
                   (repository_key, canonical_root, producer_operation_id, task_contract_id,
                    task_contract_sha256, owner_instance_id, owner_host_id)):
            raise ValidationFailure("verification intent has incomplete identity bindings")
        # The aggregate manifest hash is not enough to establish the final
        # ordinal after a restart.  The full normalized list is immutable
        # attempt authority; old bindings without it are deliberately legacy
        # evidence and cannot authorize a command transition.
        normalized_commands = self._normalize_verification_commands(manifest_binding)
        bound_manifest = {**dict(manifest_binding), "commands": normalized_commands}
        with self._transaction() as conn:
            existing = conn.execute("""SELECT id, lease_id, execution_id, operation_id, status, classification
                FROM verification_attempts WHERE workflow_id=? AND producer_operation_id=? AND request_hash=?
                ORDER BY sequence DESC LIMIT 1""", (workflow_id, producer_operation_id, request_hash)).fetchone()
            if existing is not None and (existing["status"] != "terminal" or existing["classification"] != "interrupted_unchanged"):
                return {"attempt_id": existing["id"], "lease_id": existing["lease_id"],
                        "execution_id": existing["execution_id"], "operation_id": existing["operation_id"]}
            if conn.execute("SELECT 1 FROM workspace_operation_leases WHERE repository_key=?", (repository_key,)).fetchone():
                raise ConflictFailure("target workspace already has an unresolved operation lease")
            authority = self.load_approved_v2_plan_authority(workflow_id, allow_human_attention=True)
            producer = self.load_successful_implementation_producer(
                workflow_id, producer_operation_id, task_contract_id, task_contract_sha256)
            if (producer.feature_artifact_id != authority.feature_contract_artifact.id
                    or producer.feature_sha256 != authority.feature_contract_artifact.sha256
                    or producer.plan_artifact_id != authority.plan_artifact.id
                    or producer.plan_sha256 != authority.plan_artifact.sha256
                    or producer.approval_id != authority.approval.id):
                raise ConflictFailure("verification producer no longer matches approved authority")
            now, attempt_id, lease_id, execution_id, operation_id = (
                _now(), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()))
            sequence = int(conn.execute("""SELECT COALESCE(MAX(sequence), 0) + 1 FROM verification_attempts
                WHERE workflow_id=? AND producer_operation_id=?""", (workflow_id, producer_operation_id)).fetchone()[0])
            session = self._create_session_unlocked(conn, workflow_id, "deterministic-verification", Role.DEVELOPER)
            conn.execute("""INSERT INTO executions
                (id,workflow_id,session_id,role,provider_execution_id,request_hash,lifecycle,capability_report,terminal_result,failure_classification,failure_detail,created_at,updated_at)
                VALUES (?,?,?,?,NULL,?,'intent','{}',NULL,NULL,NULL,?,?)""",
                (execution_id, workflow_id, session.id, Role.DEVELOPER.value, request_hash, now, now))
            conn.execute("""INSERT INTO operations (id,idempotency_key,kind,workflow_id,status,related_record_id,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (operation_id, f"verification:{attempt_id}", "verification", workflow_id, "pending", execution_id, now, now))
            conn.execute("""INSERT INTO verification_attempts
                (id,workflow_id,producer_operation_id,execution_id,operation_id,lease_id,feature_artifact_id,feature_sha256,
                 plan_artifact_id,plan_sha256,plan_revision,plan_id,approval_id,task_contract_id,task_contract_sha256,
                 authority_sha256,request_hash,manifest_binding_json,baseline_repository_json,status,sequence,started_at,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'verifying',?,?,?,?)""",
                (attempt_id, workflow_id, producer_operation_id, execution_id, operation_id, lease_id,
                 producer.feature_artifact_id, producer.feature_sha256, producer.plan_artifact_id, producer.plan_sha256,
                 producer.plan_revision, producer.plan_id, producer.approval_id, task_contract_id, task_contract_sha256,
                 authority_sha256, request_hash, _json(bound_manifest), _json(baseline), sequence, now, now, now))
            conn.execute("""INSERT INTO workspace_operation_leases
                (repository_key,lease_id,operation_kind,attempt_id,operation_id,workflow_id,canonical_root,
                 owner_instance_id,owner_pid,owner_host_id,owner_boot_id,acquired_at,updated_at)
                VALUES (?,?,'verification',?,?,?,?,?,?,?,?,?,?)""",
                (repository_key, lease_id, attempt_id, operation_id, workflow_id, canonical_root,
                 owner_instance_id, owner_pid, owner_host_id, owner_boot_id, now, now))
            state_update = conn.execute("""UPDATE task_implementation_states SET status='verifying',updated_at=?
                WHERE workflow_id=? AND plan_artifact_id=? AND task_contract_id=? AND status='implementation_completed'""",
                (now, workflow_id, authority.plan_artifact.id, task_contract_id))
            if state_update.rowcount != 1:
                raise ConflictFailure("verification requires completed implementation task state")
            conn.execute("UPDATE workflows SET stage=?,status=?,updated_at=? WHERE id=?",
                (Stage.TASK_EXECUTION.value, WorkflowStatus.VERIFYING.value, now, workflow_id))
            self._event_unlocked(conn, workflow_id, "verification.attempt.created", stage=Stage.TASK_EXECUTION,
                execution_id=execution_id, payload={"attempt_id": attempt_id, "lease_id": lease_id,
                                                     "producer_operation_id": producer_operation_id})
        return {"attempt_id": attempt_id, "lease_id": lease_id, "execution_id": execution_id, "operation_id": operation_id}

    @staticmethod
    def _normalize_verification_commands(manifest_binding: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Validate the immutable ordered command authority stored on an attempt."""
        commands = manifest_binding.get("commands") if isinstance(manifest_binding, Mapping) else None
        aggregate = manifest_binding.get("canonical_commands_sha256") if isinstance(manifest_binding, Mapping) else None
        if not isinstance(commands, list) or not commands or not isinstance(aggregate, str):
            raise ValidationFailure("verification command binding is incomplete")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for command in commands:
            if (not isinstance(command, Mapping) or set(command) != {"id", "argv", "timeout_seconds"}
                    or not isinstance(command["id"], str) or not command["id"]
                    or command["id"] in seen or not isinstance(command["argv"], list)
                    or not command["argv"] or any(not isinstance(arg, str) or not arg for arg in command["argv"])
                    or type(command["timeout_seconds"]) is not int or command["timeout_seconds"] < 1):
                raise ValidationFailure("verification command binding is invalid")
            seen.add(command["id"])
            normalized.append({"id": command["id"], "argv": list(command["argv"]),
                               "timeout_seconds": command["timeout_seconds"]})
        actual = hashlib.sha256(_json({"version": 1, "commands": normalized}).encode()).hexdigest()
        if aggregate != actual:
            raise ValidationFailure("verification command binding hash is inconsistent")
        return normalized

    @staticmethod
    def _command_hash(command: Mapping[str, Any]) -> str:
        return hashlib.sha256(_json(dict(command)).encode()).hexdigest()

    def _verification_command_state_unlocked(self, conn: sqlite3.Connection,
                                               attempt: sqlite3.Row) -> tuple[str, list[sqlite3.Row]]:
        """Return the only durable command-prefix states accepted by VERIFY.

        INVALID includes legacy aggregate-only bindings and every corrupt or
        impossible prefix.  Callers must retain ownership rather than infer a
        successor or terminal outcome from such evidence.
        """
        rows = conn.execute("SELECT * FROM verification_command_results WHERE verification_attempt_id=? ORDER BY ordinal,id",
                            (attempt["id"],)).fetchall()
        try:
            binding = json.loads(attempt["manifest_binding_json"])
            bound = self._normalize_verification_commands(binding)
            baseline = json.loads(attempt["baseline_repository_json"])
            expected_control = baseline["control_state_fingerprint"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationFailure):
            return "INVALID", rows
        if not isinstance(expected_control, str) or len(expected_control) != 64:
            return "INVALID", rows
        lease = conn.execute("""SELECT owner_instance_id,owner_host_id,owner_boot_id
            FROM workspace_operation_leases WHERE lease_id=? AND attempt_id=?
              AND operation_kind='verification'""",
            (attempt["lease_id"], attempt["id"])).fetchone()
        if lease is None:
            return "INVALID", rows
        saw_nonpass = False
        for ordinal, row in enumerate(rows, 1):
            if ordinal > len(bound) or row["ordinal"] != ordinal:
                return "INVALID", rows
            expected = bound[ordinal - 1]
            if (row["command_id"] != expected["id"] or row["argv_json"] != _json(expected["argv"])
                    or row["timeout_seconds"] != expected["timeout_seconds"]
                    or row["canonical_command_sha256"] != self._command_hash(expected)
                    or not row["intent_at"] or saw_nonpass):
                return "INVALID", rows
            if row["result_at"] is None:
                if ordinal != len(rows):
                    return "INVALID", rows
                return "UNRESOLVED", rows
            classification = row["classification"]
            if (classification not in {"passed", "failed", "timed_out", "output_limited", "spawn_blocked", "repository_mutated"}
                    or row["timed_out"] not in {0, 1} or row["output_truncated"] not in {0, 1}
                    or type(row["output_bytes"]) is not int or row["output_bytes"] < 0
                    or not isinstance(row["output_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["output_sha256"])):
                return "INVALID", rows
            try:
                inspection = json.loads(row["post_command_inspection_json"])
            except (TypeError, json.JSONDecodeError):
                return "INVALID", rows
            safe = (isinstance(inspection, dict) and inspection.get("safe") is True
                    and inspection.get("repository") == {key: value for key, value in baseline.items()
                                                          if key != "control_state_fingerprint"}
                    and inspection.get("control_state_fingerprint") == expected_control)
            facts_match = ((classification == "passed" and row["exit_code"] == 0 and not row["timed_out"] and not row["output_truncated"])
                or (classification == "failed" and type(row["exit_code"]) is int and row["exit_code"] != 0 and not row["timed_out"] and not row["output_truncated"])
                or (classification == "timed_out" and row["timed_out"] == 1 and not row["output_truncated"])
                or (classification == "output_limited" and not row["timed_out"] and row["output_truncated"] == 1)
                or (classification == "spawn_blocked" and row["exit_code"] is None and not row["timed_out"] and not row["output_truncated"]
                    and row["child_pid"] is None)
                or (classification == "repository_mutated" and not safe))
            if not facts_match:
                return "INVALID", rows
            if classification == "passed":
                historical_identity_is_coherent = (
                    isinstance(lease["owner_instance_id"], str) and lease["owner_instance_id"]
                    and isinstance(lease["owner_host_id"], str) and lease["owner_host_id"]
                    and isinstance(lease["owner_boot_id"], str) and lease["owner_boot_id"]
                    and isinstance(row["child_owner_instance_id"], str)
                    and row["child_owner_instance_id"] == lease["owner_instance_id"]
                    and isinstance(row["child_host_id"], str)
                    and row["child_host_id"] == lease["owner_host_id"]
                    and isinstance(row["child_boot_id"], str)
                    and row["child_boot_id"] == lease["owner_boot_id"]
                    and type(row["child_pid"]) is int and row["child_pid"] > 0
                    and isinstance(row["child_process_start"], str) and row["child_process_start"]
                    and type(row["child_process_group"]) is int
                    and row["child_process_group"] == row["child_pid"]
                    and type(row["child_process_session"]) is int
                    and row["child_process_session"] == row["child_pid"])
                if not safe or not historical_identity_is_coherent:
                    return "INVALID", rows
                continue
            if classification == "repository_mutated" or not safe:
                return "UNSAFE", rows
            saw_nonpass = True
            if ordinal != len(rows):
                return "INVALID", rows
            return "KNOWN_NONPASS", rows
        return ("EMPTY" if not rows else "COMPLETE_PASS" if len(rows) == len(bound) else "PASSING_PREFIX"), rows

    def find_verification_attempt(self, workflow_id: str, producer_operation_id: str,
                                  request_hash: str) -> Mapping[str, Any] | None:
        """Load existing VERIFY evidence without interpreting or reconciling it."""
        row = self._connection.execute("""SELECT * FROM verification_attempts
            WHERE workflow_id=? AND producer_operation_id=? AND request_hash=?
            ORDER BY sequence DESC LIMIT 1""", (workflow_id, producer_operation_id, request_hash)).fetchone()
        return dict(row) if row is not None else None

    def active_verification_recovery_context(self, workflow_id: str) -> Mapping[str, Any] | None:
        """Load raw unresolved VERIFY ownership and command evidence.

        Recovery deliberately receives even inconsistent rows so it can fail
        closed instead of losing a lease through an inner join.
        """
        leases = self._connection.execute("""SELECT * FROM workspace_operation_leases
            WHERE workflow_id=? AND operation_kind='verification'""", (workflow_id,)).fetchall()
        attempts = self._connection.execute("""SELECT * FROM verification_attempts
            WHERE workflow_id=? AND status IN ('verifying','unknown') ORDER BY sequence""",
            (workflow_id,)).fetchall()
        if len(leases) != 1:
            if not leases and not attempts:
                return None
            return {"ambiguous": True, "leases": [dict(row) for row in leases],
                    "attempts": [dict(row) for row in attempts]}
        if not attempts:
            # A lease without its unresolved attempt is itself recovery
            # evidence and must not be silently treated as no work.
            return {"ambiguous": True, "leases": [dict(leases[0])], "attempts": []}
        if len(attempts) != 1:
            return {"ambiguous": True, "leases": [dict(leases[0])],
                    "attempts": [dict(row) for row in attempts]}
        if not leases:
            return None
        lease = dict(leases[0])
        attempt = self._connection.execute(
            "SELECT * FROM verification_attempts WHERE id=?", (lease["attempt_id"],)).fetchone()
        operation = self._connection.execute(
            "SELECT * FROM operations WHERE id=?", (lease["operation_id"],)).fetchone()
        execution = None if attempt is None else self._connection.execute(
            "SELECT * FROM executions WHERE id=?", (attempt["execution_id"],)).fetchone()
        workflow = self._connection.execute(
            "SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        task_state = None
        if attempt is not None:
            task_states = self._connection.execute("""SELECT * FROM task_implementation_states
                WHERE workflow_id=? AND plan_artifact_id=? AND task_contract_id=?""",
                (workflow_id, attempt["plan_artifact_id"], attempt["task_contract_id"])).fetchall()
            if len(task_states) == 1:
                task_state = task_states[0]
        commands = self._connection.execute("""SELECT * FROM verification_command_results
            WHERE verification_attempt_id=? ORDER BY ordinal""", (lease["attempt_id"],)).fetchall()
        command_state = ("INVALID" if attempt is None else
            self._verification_command_state_unlocked(self._connection, attempt)[0])
        return {"lease": lease, "attempt": None if attempt is None else dict(attempt),
                "operation": None if operation is None else dict(operation),
                "execution": None if execution is None else dict(execution),
                "workflow": None if workflow is None else dict(workflow),
                "task_state": None if task_state is None else dict(task_state),
                "commands": [dict(row) for row in commands], "command_state": command_state}

    def retain_ambiguous_verification_recovery(self, workflow_id: str, *,
                                               evidence: Mapping[str, Any],
                                               detail: str) -> None:
        """Fail closed when no single exact lease/attempt context exists.

        This method never creates, deletes, or rewrites ownership rows.  It
        only projects HUMAN_ATTENTION and records the ambiguity so recovery
        cannot dispatch or signal from a guessed owner.
        """
        if not isinstance(detail, str) or not detail:
            raise ValidationFailure("ambiguous verification recovery detail is required")
        with self._transaction() as conn:
            workflow = conn.execute("SELECT id FROM workflows WHERE id=?", (workflow_id,)).fetchone()
            if workflow is None:
                raise ConflictFailure("ambiguous verification recovery workflow is missing")
            now = _now()
            conn.execute("UPDATE workflows SET stage=?,status=?,updated_at=? WHERE id=?",
                (Stage.TASK_EXECUTION.value, WorkflowStatus.HUMAN_ATTENTION.value, now, workflow_id))
            payload = {"reason": detail, "evidence": dict(evidence)}
            encoded = _json(payload)
            prior = conn.execute("""SELECT 1 FROM events WHERE workflow_id=?
                AND type='verification.recovery.ambiguous_context' AND payload=?""",
                (workflow_id, encoded)).fetchone()
            if prior is None:
                self._event_unlocked(conn, workflow_id,
                    "verification.recovery.ambiguous_context", stage=Stage.TASK_EXECUTION,
                    payload=payload)

    def record_verification_command_intent(self, attempt_id: str, lease_id: str, *, owner_instance_id: str,
                                            ordinal: int, command_id: str, canonical_command_sha256: str,
                                            argv: list[str] | tuple[str, ...], timeout_seconds: int) -> str:
        """Durably reserve exactly one command ordinal immediately before spawn."""
        self._require_sha256(canonical_command_sha256, "canonical_command_sha256")
        if (type(ordinal) is not int or ordinal < 1 or not isinstance(command_id, str) or not command_id
                or type(timeout_seconds) is not int or timeout_seconds < 1
                or not isinstance(argv, (list, tuple)) or not argv
                or any(not isinstance(x, str) or not x for x in argv)):
            raise ValidationFailure("verification command intent is invalid")
        with self._transaction() as conn:
            lease = conn.execute("""SELECT * FROM workspace_operation_leases WHERE lease_id=? AND attempt_id=?
                AND owner_instance_id=? AND operation_kind='verification'""",
                (lease_id, attempt_id, owner_instance_id)).fetchone()
            attempt = conn.execute("SELECT status FROM verification_attempts WHERE id=? AND lease_id=?", (attempt_id, lease_id)).fetchone()
            if lease is None or attempt is None or attempt["status"] != "verifying":
                raise ConflictFailure("verification command intent lacks exact active lease ownership")
            full_attempt = conn.execute("SELECT * FROM verification_attempts WHERE id=?", (attempt_id,)).fetchone()
            state, rows = self._verification_command_state_unlocked(conn, full_attempt)
            existing = conn.execute("SELECT * FROM verification_command_results WHERE verification_attempt_id=? AND ordinal=?",
                (attempt_id, ordinal)).fetchone()
            if existing is not None:
                if (existing["command_id"], existing["canonical_command_sha256"], existing["argv_json"], existing["timeout_seconds"]) != (
                        command_id, canonical_command_sha256, _json(list(argv)), timeout_seconds):
                    raise ConflictFailure("verification command ordinal is already bound differently")
                if state != "UNRESOLVED" or not rows or rows[-1]["id"] != existing["id"]:
                    raise ConflictFailure("verification command prefix does not permit idempotent intent")
                return existing["id"]
            if state not in {"EMPTY", "PASSING_PREFIX"} or ordinal != len(rows) + 1:
                raise ConflictFailure("verification command prefix does not permit a successor")
            bound = self._normalize_verification_commands(json.loads(full_attempt["manifest_binding_json"]))
            expected = bound[ordinal - 1]
            if (command_id, _json(list(argv)), timeout_seconds, canonical_command_sha256) != (
                    expected["id"], _json(expected["argv"]), expected["timeout_seconds"], self._command_hash(expected)):
                raise ConflictFailure("verification command intent does not match immutable binding")
            command_result_id, now = str(uuid.uuid4()), _now()
            conn.execute("""INSERT INTO verification_command_results
                (id,verification_attempt_id,ordinal,command_id,canonical_command_sha256,argv_json,timeout_seconds,intent_at,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (command_result_id, attempt_id, ordinal, command_id, canonical_command_sha256,
                 _json(list(argv)), timeout_seconds, now, now, now))
            conn.execute("UPDATE workspace_operation_leases SET updated_at=? WHERE lease_id=?", (now, lease_id))
        return command_result_id

    def record_workspace_operation_child(self, attempt_id: str, lease_id: str, *, owner_instance_id: str,
                                         child_pid: int | None, child_process_start: str | None,
                                         child_process_group: int | None) -> None:
        """Record non-verification child identity; VERIFY owns a write-once API."""
        if child_pid is not None and type(child_pid) is not int: raise ValidationFailure("child_pid must be an integer")
        if child_process_group is not None and type(child_process_group) is not int: raise ValidationFailure("child_process_group must be an integer")
        if child_process_start is not None and not isinstance(child_process_start, str): raise ValidationFailure("child_process_start must be text")
        with self._transaction() as conn:
            lease = conn.execute("""SELECT operation_kind FROM workspace_operation_leases
                WHERE lease_id=? AND attempt_id=? AND owner_instance_id=?""",
                (lease_id, attempt_id, owner_instance_id)).fetchone()
            if lease is None:
                raise ConflictFailure("workspace operation lease ownership mismatch")
            if lease["operation_kind"] == "verification":
                raise ConflictFailure("verification child identity requires its command-start boundary")
            result = conn.execute("""UPDATE workspace_operation_leases
                SET child_pid=?,child_process_start=?,child_process_group=?,updated_at=?
                WHERE lease_id=? AND attempt_id=? AND owner_instance_id=?
                  AND operation_kind!='verification'""",
                (child_pid, child_process_start, child_process_group, _now(), lease_id, attempt_id, owner_instance_id))
            if result.rowcount != 1: raise ConflictFailure("workspace operation lease ownership mismatch")

    def record_verification_command_started(self, attempt_id: str, lease_id: str, command_result_id: str, *,
                                            owner_instance_id: str, child_pid: int,
                                            child_process_start: str, child_process_group: int,
                                            child_process_session: int,
                                            child_host_id: str, child_boot_id: str) -> None:
        """Atomically bind a spawned VERIFY child to its intent and active lease.

        The command cannot be considered durably started until its PID-reuse-safe
        identity is present in both the historical command evidence and the
        unresolved lease used by a future recovery boundary.
        """
        if (type(child_pid) is not int or child_pid <= 0
                or type(child_process_group) is not int or child_process_group <= 0
                or type(child_process_session) is not int or child_process_session <= 0
                or child_process_group != child_pid or child_process_session != child_pid
                or not all(isinstance(value, str) and value for value in
                           (child_process_start, child_host_id, child_boot_id, owner_instance_id))):
            raise ValidationFailure("verification child identity is incomplete")
        with self._transaction() as conn:
            attempt_hint = conn.execute("SELECT workflow_id FROM verification_attempts WHERE id=?",
                (attempt_id,)).fetchone()
            if attempt_hint is None:
                raise ConflictFailure("verification child start lacks an attempt")
            _, lease, *_ = self._verification_transition_context_unlocked(conn,
                attempt_hint["workflow_id"], attempt_id=attempt_id, lease_id=lease_id,
                owner_instance_id=owner_instance_id)
            if (child_host_id != lease["owner_host_id"]
                    or child_boot_id != lease["owner_boot_id"]):
                raise ConflictFailure("verification child host/boot authority is inconsistent")
            command = conn.execute("""SELECT * FROM verification_command_results
                WHERE id=? AND verification_attempt_id=?""", (command_result_id, attempt_id)).fetchone()
            attempt = conn.execute("SELECT * FROM verification_attempts WHERE id=?", (attempt_id,)).fetchone()
            state, rows = self._verification_command_state_unlocked(conn, attempt)
            if (command is None or command["result_at"] is not None
                    or state != "UNRESOLVED" or not rows or rows[-1]["id"] != command_result_id
                    or any(command[field] is not None for field in (
                        "child_pid", "child_process_start", "child_process_group",
                        "child_process_session", "child_host_id", "child_boot_id",
                        "child_owner_instance_id"))
                    or any(lease[field] is not None for field in (
                        "child_pid", "child_process_start", "child_process_group",
                        "child_process_session"))):
                raise ConflictFailure("verification child start lacks exact active intent ownership")
            now = _now()
            conn.execute("""UPDATE verification_command_results SET child_pid=?,child_process_start=?,
                child_process_group=?,child_process_session=?,child_host_id=?,child_boot_id=?,
                child_owner_instance_id=?,updated_at=? WHERE id=?""",
                (child_pid, child_process_start, child_process_group, child_process_session, child_host_id,
                 child_boot_id, owner_instance_id, now, command_result_id))
            conn.execute("""UPDATE workspace_operation_leases SET child_pid=?,child_process_start=?,
                child_process_group=?,child_process_session=?,updated_at=? WHERE lease_id=? AND attempt_id=?""",
                (child_pid, child_process_start, child_process_group, child_process_session, now, lease_id, attempt_id))

    def record_verification_command_result(self, attempt_id: str, lease_id: str, command_result_id: str, *,
                                            owner_instance_id: str, exit_code: int | None, timed_out: bool,
                                            output_sha256: str | None, output_bytes: int | None,
                                            output_truncated: bool, post_command_inspection: Mapping[str, Any],
                                            classification: str) -> None:
        """Persist one dead-child result and its single post-command inspection."""
        if output_sha256 is not None: self._require_sha256(output_sha256, "output_sha256")
        if exit_code is not None and type(exit_code) is not int: raise ValidationFailure("exit_code must be an integer")
        if output_bytes is not None and (type(output_bytes) is not int or output_bytes < 0): raise ValidationFailure("output_bytes must be non-negative")
        if type(timed_out) is not bool or type(output_truncated) is not bool:
            raise ValidationFailure("verification command boolean fields must be boolean")
        if not isinstance(post_command_inspection, Mapping) or not isinstance(classification, str) or not classification:
            raise ValidationFailure("verification command result is invalid")
        with self._transaction() as conn:
            attempt_hint = conn.execute("SELECT workflow_id FROM verification_attempts WHERE id=?",
                (attempt_id,)).fetchone()
            if attempt_hint is None:
                raise ConflictFailure("verification command result lacks an attempt")
            attempt, lease, *_ = self._verification_transition_context_unlocked(conn,
                attempt_hint["workflow_id"], attempt_id=attempt_id, lease_id=lease_id,
                owner_instance_id=owner_instance_id)
            row = conn.execute("SELECT * FROM verification_command_results WHERE id=? AND verification_attempt_id=?",
                (command_result_id, attempt_id)).fetchone()
            if row is None: raise ConflictFailure("verification command result lacks exact active lease ownership")
            if row["result_at"] is not None: raise ConflictFailure("verification command result is already terminal")
            started = row["child_pid"] is not None
            if ((classification != "spawn_blocked" and not started)
                    or (started and (row["child_owner_instance_id"] != lease["owner_instance_id"]
                        or row["child_pid"] != lease["child_pid"]
                        or row["child_process_start"] != lease["child_process_start"]
                        or row["child_process_group"] != lease["child_process_group"]
                        or row["child_process_session"] != lease["child_process_session"]
                        or row["child_host_id"] != lease["owner_host_id"]
                        or row["child_boot_id"] != lease["owner_boot_id"]))):
                raise ConflictFailure("verification command result child authority is inconsistent")
            now = _now()
            conn.execute("""UPDATE verification_command_results SET result_at=?,exit_code=?,timed_out=?,output_sha256=?,output_bytes=?,
                output_truncated=?,post_command_inspection_json=?,classification=?,updated_at=? WHERE id=?""",
                (now, exit_code, int(timed_out), output_sha256, output_bytes, int(output_truncated),
                 _json(post_command_inspection), classification, now, command_result_id))
            cleared = conn.execute("""UPDATE workspace_operation_leases SET child_pid=NULL,
                child_process_start=NULL,child_process_group=NULL,child_process_session=NULL,updated_at=?
                WHERE lease_id=? AND attempt_id=? AND operation_id=? AND workflow_id=?
                  AND owner_instance_id=? AND operation_kind='verification'""",
                (now, lease_id, attempt_id, lease["operation_id"], lease["workflow_id"], owner_instance_id))
            if cleared.rowcount != 1:
                raise PersistenceFailure("verification command result lost exact lease ownership")
            state, _ = self._verification_command_state_unlocked(conn, attempt)
            if state == "INVALID":
                raise ConflictFailure("verification command result contradicts durable facts")

    @staticmethod
    def _verification_authority_evidence(attempt: sqlite3.Row) -> dict[str, Any]:
        return {key: attempt[key] for key in (
            "workflow_id", "feature_artifact_id", "feature_sha256",
            "plan_artifact_id", "plan_sha256", "plan_revision", "plan_id",
            "approval_id", "task_contract_id", "task_contract_sha256",
            "producer_operation_id", "execution_id", "operation_id", "lease_id",
            "authority_sha256", "request_hash")}

    def _verification_transition_context_unlocked(
        self, conn: sqlite3.Connection, workflow_id: str, *,
        attempt_id: str | None = None, lease_id: str | None = None,
        owner_instance_id: str | None = None,
    ) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row, sqlite3.Row, sqlite3.Row, sqlite3.Row]:
        """Reconstruct one coherent unresolved verification authority chain."""
        leases = conn.execute("""SELECT * FROM workspace_operation_leases
            WHERE workflow_id=? AND operation_kind='verification'""", (workflow_id,)).fetchall()
        attempts = conn.execute("""SELECT * FROM verification_attempts
            WHERE workflow_id=? AND status IN ('verifying','unknown')""", (workflow_id,)).fetchall()
        if len(leases) != 1 or len(attempts) != 1:
            raise ConflictFailure("verification transition requires one exact unresolved authority context")
        lease, attempt = leases[0], attempts[0]
        if ((attempt_id is not None and attempt["id"] != attempt_id)
                or (lease_id is not None and lease["lease_id"] != lease_id)
                or (owner_instance_id is not None and lease["owner_instance_id"] != owner_instance_id)
                or attempt["id"] != lease["attempt_id"]
                or attempt["lease_id"] != lease["lease_id"]
                or attempt["operation_id"] != lease["operation_id"]
                or attempt["workflow_id"] != lease["workflow_id"]):
            raise ConflictFailure("verification attempt and lease authority is inconsistent")
        workflow = conn.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        operation = conn.execute("SELECT * FROM operations WHERE id=?", (attempt["operation_id"],)).fetchone()
        execution = conn.execute("SELECT * FROM executions WHERE id=?", (attempt["execution_id"],)).fetchone()
        task_states = conn.execute("""SELECT * FROM task_implementation_states
            WHERE workflow_id=? AND plan_artifact_id=? AND task_contract_id=?""",
            (workflow_id, attempt["plan_artifact_id"], attempt["task_contract_id"])).fetchall()
        if workflow is None or operation is None or execution is None or len(task_states) != 1:
            raise ConflictFailure("verification durable authority is incomplete")
        task_state = task_states[0]
        expected_projection = ((WorkflowStatus.VERIFYING.value, "verifying", "pending", "intent")
            if attempt["status"] == "verifying" else
            (WorkflowStatus.HUMAN_ATTENTION.value, "implementation_completed", "unknown", "unknown"))
        actual_projection = (workflow["status"], task_state["status"], operation["status"], execution["lifecycle"])
        if (workflow["stage"] != Stage.TASK_EXECUTION.value
                or actual_projection != expected_projection
                or operation["workflow_id"] != workflow_id
                or operation["kind"] != "verification"
                or operation["idempotency_key"] != f"verification:{attempt['id']}"
                or operation["related_record_id"] != attempt["execution_id"]
                or execution["workflow_id"] != workflow_id
                or execution["request_hash"] != attempt["request_hash"]
                or execution["role"] != Role.DEVELOPER.value
                or task_state["plan_sha256"] != attempt["plan_sha256"]
                or task_state["task_contract_sha256"] != attempt["task_contract_sha256"]
                or not task_state["selected_at"]):
            raise ConflictFailure("verification lifecycle authority is inconsistent")
        try:
            baseline = json.loads(attempt["baseline_repository_json"])
            canonical_root = str(Path(workflow["repository_path"]).resolve())
            repository_key = hashlib.sha256("\0".join((
                baseline["canonical_root"], baseline["git_dir"], baseline["git_common_dir"])).encode()).hexdigest()
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ConflictFailure("verification repository authority is corrupt") from None
        if (lease["canonical_root"] != canonical_root
                or baseline["canonical_root"] != canonical_root
                or lease["repository_key"] != repository_key
                or not lease["owner_instance_id"]
                or type(lease["owner_pid"]) is not int or lease["owner_pid"] <= 0
                or not lease["owner_host_id"] or not lease["owner_boot_id"]):
            raise ConflictFailure("verification repository or owner authority is inconsistent")
        try:
            authority = self.load_approved_v2_plan_authority(
                workflow_id, allow_human_attention=True)
            task = next(item for item in authority.plan.tasks
                if item.id == attempt["task_contract_id"])
            producer = self.load_successful_implementation_producer(
                workflow_id, attempt["producer_operation_id"],
                attempt["task_contract_id"], attempt["task_contract_sha256"])
        except (DomainFailure, StopIteration) as exc:
            raise ConflictFailure("verification approved or producer authority is unavailable") from exc
        authority_payload = {"workflow_id": authority.workflow.id,
            "feature_artifact_id": authority.feature_contract_artifact.id,
            "feature_sha256": authority.feature_contract_artifact.sha256,
            "plan_artifact_id": authority.plan_artifact.id,
            "plan_sha256": authority.plan_artifact.sha256,
            "plan_id": authority.plan.id, "plan_revision": authority.plan.revision,
            "approval_id": authority.approval.id,
            "task_contract_id": attempt["task_contract_id"],
            "task_contract_sha256": attempt["task_contract_sha256"]}
        authority_sha256 = hashlib.sha256(_json(authority_payload).encode("utf-8")).hexdigest()
        baseline_without_control = dict(baseline)
        baseline_without_control.pop("control_state_fingerprint", None)
        if (task.payload_sha256() != attempt["task_contract_sha256"]
                or attempt["authority_sha256"] != authority_sha256
                or (attempt["feature_artifact_id"], attempt["feature_sha256"])
                    != (authority.feature_contract_artifact.id,
                        authority.feature_contract_artifact.sha256)
                or (attempt["plan_artifact_id"], attempt["plan_sha256"],
                    attempt["plan_revision"], attempt["plan_id"], attempt["approval_id"])
                    != (authority.plan_artifact.id, authority.plan_artifact.sha256,
                        authority.plan.revision, authority.plan.id, authority.approval.id)
                or (producer.feature_artifact_id, producer.feature_sha256,
                    producer.plan_artifact_id, producer.plan_sha256,
                    producer.plan_revision, producer.plan_id, producer.approval_id)
                    != (attempt["feature_artifact_id"], attempt["feature_sha256"],
                        attempt["plan_artifact_id"], attempt["plan_sha256"],
                        attempt["plan_revision"], attempt["plan_id"], attempt["approval_id"])
                or dict(producer.final_repository) != baseline_without_control):
            raise ConflictFailure("verification durable authority is stale or inconsistent")
        return attempt, lease, workflow, operation, execution, task_state

    def _project_verification_terminal_unlocked(
        self, conn: sqlite3.Connection, attempt: sqlite3.Row, lease: sqlite3.Row, *,
        outcome: str, final_inspection: Mapping[str, Any], detail: str | None,
        recovery_event: bool = False,
    ) -> None:
        now = _now()
        task_status = ("verified" if outcome == "verified" else
            "verification_failed" if outcome == "verification_failed" else "implementation_completed")
        workflow_status = (WorkflowStatus.TASK_VERIFIED.value if outcome == "verified" else
            WorkflowStatus.VERIFICATION_FAILED.value if outcome == "verification_failed"
            else WorkflowStatus.HUMAN_ATTENTION.value)
        execution_lifecycle = ("completed" if outcome == "verified" else
            "failed" if outcome == "verification_failed" else "unknown")
        conn.execute("""UPDATE verification_attempts SET status='terminal',classification=?,
            final_inspection_json=?,finished_at=?,updated_at=? WHERE id=?""",
            (outcome, _json(final_inspection), now, now, attempt["id"]))
        conn.execute("""UPDATE executions SET lifecycle=?,terminal_result=?,failure_detail=?,updated_at=?
            WHERE id=?""", (execution_lifecycle, _json({"classification": outcome}), detail,
                              now, attempt["execution_id"]))
        conn.execute("UPDATE operations SET status='completed',updated_at=? WHERE id=?",
            (now, attempt["operation_id"]))
        conn.execute("""UPDATE task_implementation_states SET status=?,updated_at=?
            WHERE workflow_id=? AND plan_artifact_id=? AND task_contract_id=?""",
            (task_status, now, attempt["workflow_id"], attempt["plan_artifact_id"],
             attempt["task_contract_id"]))
        conn.execute("UPDATE workflows SET stage=?,status=?,updated_at=? WHERE id=?",
            (Stage.TASK_EXECUTION.value, workflow_status, now, attempt["workflow_id"]))
        payload: dict[str, Any] = {"attempt_id": attempt["id"], "outcome": outcome}
        if recovery_event:
            payload["recovery"] = dict(final_inspection)
        self._event_unlocked(conn, attempt["workflow_id"], "verification.attempt.terminal",
            stage=Stage.TASK_EXECUTION, execution_id=attempt["execution_id"], payload=payload)

    def finish_verification_attempt(self, attempt_id: str, lease_id: str, *, owner_instance_id: str,
                                    outcome: str, final_inspection: Mapping[str, Any], detail: str | None = None) -> None:
        """Apply normal VERIFY completion; crash recovery has a separate boundary."""
        outcome = str(outcome)
        if outcome == "interrupted_unchanged":
            raise ValidationFailure("interrupted verification requires recovery authority")
        if outcome not in {"verified", "verification_failed", "verification_blocked", "verification_unknown"}:
            raise ValidationFailure("invalid verification terminal outcome")
        if not isinstance(final_inspection, Mapping):
            raise ValidationFailure("verification final inspection must be a mapping")
        with self._transaction() as conn:
            attempt_hint = conn.execute("SELECT workflow_id FROM verification_attempts WHERE id=?",
                (attempt_id,)).fetchone()
            if attempt_hint is None:
                raise ConflictFailure("verification attempt is missing")
            attempt, lease, *_ = self._verification_transition_context_unlocked(conn,
                attempt_hint["workflow_id"], attempt_id=attempt_id, lease_id=lease_id,
                owner_instance_id=owner_instance_id)
            if attempt["status"] != "verifying":
                raise ConflictFailure("verification normal transition requires a verifying attempt")
            if outcome == "verification_unknown":
                self._retain_verification_unknown_unlocked(conn, attempt, lease,
                    final_inspection=final_inspection,
                    detail=detail or "verification outcome is unknown", recovery=False)
                return
            command_state, commands = self._verification_command_state_unlocked(conn, attempt)
            if (any(lease[field] is not None for field in (
                    "child_pid", "child_process_start", "child_process_group",
                    "child_process_session"))):
                raise ConflictFailure(
                    "verification normal completion retains unresolved child ownership")
            if (outcome == "verified" and command_state != "COMPLETE_PASS"):
                raise ConflictFailure("verified requires the complete passing command sequence")
            if outcome == "verification_failed" and (command_state != "KNOWN_NONPASS"
                    or commands[-1]["classification"] not in {"failed", "timed_out", "output_limited"}):
                raise ConflictFailure("verification failure requires the first safe non-passing command")
            if outcome == "verification_blocked" and not (command_state == "EMPTY"
                    or (command_state == "KNOWN_NONPASS"
                        and commands[-1]["classification"] == "spawn_blocked")):
                raise ConflictFailure("verification blocked requires a safe spawn-blocked command")
            self._project_verification_terminal_unlocked(conn, attempt, lease, outcome=outcome,
                final_inspection=final_inspection, detail=detail)
            deleted = conn.execute("""DELETE FROM workspace_operation_leases WHERE repository_key=?
                AND lease_id=? AND attempt_id=? AND operation_id=? AND workflow_id=?
                AND owner_instance_id=? AND operation_kind='verification'""",
                (lease["repository_key"], lease["lease_id"], attempt["id"], attempt["operation_id"],
                 attempt["workflow_id"], lease["owner_instance_id"]))
            if deleted.rowcount != 1:
                raise PersistenceFailure(
                    "verification normal transition could not release its exact lease")

    def finish_interrupted_verification_recovery(
        self, decision: VerificationRecoveryDecision,
    ) -> None:
        """Atomically bind dead/unchanged observations and release exact VERIFY ownership."""
        if (not isinstance(decision, VerificationRecoveryDecision)
                or decision.process_observation != "dead"
                or not isinstance(decision.observed_identity, Mapping)
                or not isinstance(decision.repository, Mapping)
                or not isinstance(decision.authority, Mapping)
                or not isinstance(decision.control_state_fingerprint, str)
                or len(decision.control_state_fingerprint) != 64
                or not isinstance(decision.detail, str) or not decision.detail):
            raise ValidationFailure("verification recovery decision is incomplete")
        with self._transaction() as conn:
            attempt, lease, *_ = self._verification_transition_context_unlocked(
                conn, decision.workflow_id)
            if attempt["status"] != "verifying":
                raise ConflictFailure("UNKNOWN verification ownership cannot be released")
            state, commands = self._verification_command_state_unlocked(conn, attempt)
            if state not in {"UNRESOLVED", "PASSING_PREFIX", "COMPLETE_PASS"}:
                raise ConflictFailure("verification recovery command prefix is not a valid passing prefix")
            unresolved = [row for row in commands if row["result_at"] is None]
            if len(unresolved) > 1 or (unresolved and unresolved[0]["id"] != commands[-1]["id"]):
                raise ConflictFailure("verification recovery command state is ambiguous")
            for row in commands:
                if row["verification_attempt_id"] != attempt["id"]:
                    raise ConflictFailure("verification command attempt authority is inconsistent")
                if row["result_at"] is not None and row["classification"] != "spawn_blocked":
                    if (row["child_owner_instance_id"] != lease["owner_instance_id"]
                            or row["child_host_id"] != lease["owner_host_id"]
                            or row["child_boot_id"] != lease["owner_boot_id"]
                            or type(row["child_pid"]) is not int or row["child_pid"] <= 0
                            or not row["child_process_start"]
                            or row["child_process_group"] != row["child_pid"]
                            or row["child_process_session"] != row["child_pid"]):
                        raise ConflictFailure(
                            "verification historical child authority is inconsistent")
            command = unresolved[0] if unresolved else commands[-1]
            if unresolved:
                if (type(command["child_pid"]) is not int or command["child_pid"] <= 0
                        or not command["child_process_start"]
                        or type(command["child_process_group"]) is not int
                        or type(command["child_process_session"]) is not int
                        or not command["child_host_id"] or not command["child_boot_id"]
                        or command["child_owner_instance_id"] != lease["owner_instance_id"]
                        or command["child_pid"] != lease["child_pid"]
                        or command["child_process_start"] != lease["child_process_start"]
                        or command["child_process_group"] != lease["child_process_group"]
                        or command["child_process_session"] != lease["child_process_session"]
                        or command["child_host_id"] != lease["owner_host_id"]
                        or command["child_boot_id"] != lease["owner_boot_id"]):
                    raise ConflictFailure("verification active child authority is inconsistent")
            elif any(lease[field] is not None for field in (
                    "child_pid", "child_process_start", "child_process_group", "child_process_session")):
                raise ConflictFailure("verification completed command retains active child authority")
            expected_identity = {
                "pid": command["child_pid"], "process_start": command["child_process_start"],
                "process_group": command["child_process_group"],
                "process_session": command["child_process_session"],
                "machine_id": command["child_host_id"], "boot_id": command["child_boot_id"],
                "owner_instance_id": lease["owner_instance_id"], "owner_pid": lease["owner_pid"],
                "workflow_id": lease["workflow_id"], "attempt_id": lease["attempt_id"],
                "lease_id": lease["lease_id"], "operation_id": lease["operation_id"],
                "command_result_id": command["id"],
            }
            if dict(decision.observed_identity) != expected_identity:
                raise ConflictFailure("verification recovery observation does not match exact ownership")
            try:
                baseline = json.loads(attempt["baseline_repository_json"])
                baseline_repository = dict(baseline)
            except (TypeError, ValueError, json.JSONDecodeError):
                raise ConflictFailure("verification recovery baseline is corrupt") from None
            expected_control = baseline_repository.pop("control_state_fingerprint", None)
            if (not isinstance(expected_control, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", expected_control)):
                raise ConflictFailure("verification recovery baseline control authority is corrupt")
            try:
                current_repository = RepositoryInspector(lease["canonical_root"]).capture().as_payload()
                current_control = control_state_fingerprint(lease["canonical_root"])
            except Exception:
                raise ConflictFailure("verification recovery repository authority cannot be inspected") from None
            # Recovery observations are evidence, never release authority.  The
            # exact durable baseline must agree with an inspection captured at
            # this persistence boundary; a matching caller fingerprint alone
            # cannot release the lease.
            if (dict(decision.repository) != baseline_repository
                    or current_repository != baseline_repository
                    or decision.control_state_fingerprint != expected_control
                    or current_control != expected_control):
                raise ConflictFailure("verification recovery repository observation is not unchanged")
            expected_authority = self._verification_authority_evidence(attempt)
            if dict(decision.authority) != expected_authority:
                raise ConflictFailure("verification recovery authority observation is stale")
            final = {"recovery_classification": "process_dead_unchanged",
                "identity": expected_identity, "repository": dict(decision.repository),
                "control_state_fingerprint": decision.control_state_fingerprint,
                "authority": expected_authority, "process_observation": decision.process_observation}
            self._project_verification_terminal_unlocked(conn, attempt, lease,
                outcome="interrupted_unchanged", final_inspection=final,
                detail=decision.detail, recovery_event=True)
            deleted = conn.execute("""DELETE FROM workspace_operation_leases WHERE repository_key=?
                AND lease_id=? AND attempt_id=? AND operation_id=? AND workflow_id=?
                AND owner_instance_id=? AND operation_kind='verification'""",
                (lease["repository_key"], lease["lease_id"], attempt["id"], attempt["operation_id"],
                 attempt["workflow_id"], lease["owner_instance_id"]))
            if deleted.rowcount != 1:
                raise PersistenceFailure(
                    "verification recovery could not release its exact lease")

    @staticmethod
    def _unknown_observation(final_inspection: Mapping[str, Any], detail: str) -> dict[str, Any]:
        """Return one self-contained, canonical UNKNOWN safety observation."""
        observation: dict[str, Any] = {
            "classification": final_inspection.get(
                "recovery_classification", "verification_unknown"),
            "detail": detail,
        }
        for key in ("repository", "control_state_fingerprint", "identity", "authority"):
            if key in final_inspection:
                observation[key] = final_inspection[key]
        # Preserve additional evidence without making the history reader know
        # every future evidence field.
        remainder = {key: value for key, value in final_inspection.items()
            if key not in {"recovery_observations", *observation.keys()}}
        if remainder:
            observation["evidence"] = remainder
        return observation

    def _retain_verification_unknown_unlocked(self, conn: sqlite3.Connection,
                                               attempt: sqlite3.Row,
                                               lease: sqlite3.Row, *,
                                               final_inspection: Mapping[str, Any],
                                               detail: str, recovery: bool) -> None:
        """Shared sticky UNKNOWN projection; the exact lease is only touched."""
        if attempt["status"] not in {"verifying", "unknown"}:
            raise ConflictFailure("retained verification unknown is not recoverable")
        prior: dict[str, Any] = {}
        if attempt["final_inspection_json"]:
            try:
                loaded = json.loads(attempt["final_inspection_json"])
            except (TypeError, json.JSONDecodeError):
                loaded = None
            if isinstance(loaded, dict):
                prior = loaded
            else:
                # Corruption cannot be allowed to prevent the UNKNOWN/HUMAN
                # projection.  Preserve the exact raw bytes in the replacement
                # envelope so the earlier evidence remains recoverable.
                prior = {"corrupt_prior_evidence_raw": attempt["final_inspection_json"]}
        observations = prior.get("recovery_observations", [])
        if not isinstance(observations, list):
            prior["corrupt_recovery_observations"] = observations
            observations = []
        elif any(not isinstance(item, dict) for item in observations):
            prior["corrupt_recovery_observations"] = observations
            observations = []

        merged = dict(prior)
        if not prior:
            merged.update(final_inspection)
            merged["original_unknown_evidence"] = {
                "classification": final_inspection.get(
                    "recovery_classification", "verification_unknown"),
                "detail": detail,
                "evidence": dict(final_inspection),
            }
        else:
            # Earlier repository/control/identity evidence remains directly
            # recoverable as well as in the immutable original/history entry.
            for key, value in final_inspection.items():
                if key not in {"recovery_classification", "recovery_observations"}:
                    merged.setdefault(key, value)
            if "recovery_classification" in final_inspection:
                merged["recovery_classification"] = final_inspection["recovery_classification"]
            prior_identity, new_identity = merged.get("identity"), final_inspection.get("identity")
            if isinstance(prior_identity, dict) and isinstance(new_identity, Mapping):
                merged["identity"] = {**prior_identity,
                    **{key: value for key, value in new_identity.items()
                       if key not in prior_identity and value is not None}}

        if recovery:
            observation = self._unknown_observation(final_inspection, detail)
            if observations and observations[-1] == observation:
                return
            observations = [*observations, observation]
            merged["recovery_observations"] = observations

        now = _now()
        conn.execute("""UPDATE verification_attempts SET status='unknown',classification='verification_unknown',
            final_inspection_json=?,finished_at=?,updated_at=? WHERE id=?""",
            (_json(merged), now, now, attempt["id"]))
        conn.execute("UPDATE executions SET lifecycle='unknown',terminal_result=?,failure_detail=?,updated_at=? WHERE id=?",
            (_json({"classification": "verification_unknown"}), detail, now, attempt["execution_id"]))
        conn.execute("UPDATE operations SET status='unknown',updated_at=? WHERE id=?",
            (now, attempt["operation_id"]))
        conn.execute("""UPDATE task_implementation_states SET status='implementation_completed',updated_at=?
            WHERE workflow_id=? AND plan_artifact_id=? AND task_contract_id=?""",
            (now, attempt["workflow_id"], attempt["plan_artifact_id"], attempt["task_contract_id"]))
        conn.execute("UPDATE workflows SET stage=?,status=?,updated_at=? WHERE id=?",
            (Stage.TASK_EXECUTION.value, WorkflowStatus.HUMAN_ATTENTION.value,
             now, attempt["workflow_id"]))
        updated = conn.execute("""UPDATE workspace_operation_leases SET updated_at=?
            WHERE repository_key=? AND lease_id=? AND attempt_id=? AND operation_id=?
              AND workflow_id=? AND owner_instance_id=? AND operation_kind='verification'""",
            (now, lease["repository_key"], lease["lease_id"], attempt["id"],
             attempt["operation_id"], attempt["workflow_id"], lease["owner_instance_id"]))
        if updated.rowcount != 1:
            raise PersistenceFailure("verification UNKNOWN transition lost exact lease ownership")
        self._event_unlocked(conn, attempt["workflow_id"],
            "verification.recovery.unknown_retained" if recovery
            else "verification.attempt.unknown_retained",
            stage=Stage.TASK_EXECUTION, execution_id=attempt["execution_id"],
            payload={"attempt_id": attempt["id"], "reason": detail})

    def retain_verification_unknown(self, attempt_id: str, lease_id: str, *, owner_instance_id: str,
                                    final_inspection: Mapping[str, Any], detail: str) -> None:
        """Atomically project unknown VERIFY ownership without releasing its lease.

        This is deliberately not a terminal transition.  Slice 4 owns any
        recovery decision; until then the exact lease and unresolved command
        intent/child identity remain the repository mutex and evidence.
        """
        if not isinstance(final_inspection, Mapping) or not isinstance(detail, str) or not detail:
            raise ValidationFailure("retained verification unknown evidence is invalid")
        with self._transaction() as conn:
            lease = conn.execute("""SELECT * FROM workspace_operation_leases WHERE lease_id=? AND attempt_id=?
                AND owner_instance_id=? AND operation_kind='verification'""",
                (lease_id, attempt_id, owner_instance_id)).fetchone()
            attempt = conn.execute("SELECT * FROM verification_attempts WHERE id=? AND lease_id=?", (attempt_id, lease_id)).fetchone()
            if lease is None or attempt is None or attempt["status"] != "verifying":
                raise ConflictFailure("retained verification unknown lacks exact active lease ownership")
            self._retain_verification_unknown_unlocked(conn, attempt, lease,
                final_inspection=final_inspection, detail=detail, recovery=False)

    def retain_verification_recovery_unknown(self, attempt_id: str, lease_id: str, *,
                                             owner_instance_id: str,
                                             final_inspection: Mapping[str, Any], detail: str) -> None:
        """Fail closed during recovery while retaining exact ownership.

        A later recovery classification is merged into an already-unknown
        attempt.  UNKNOWN itself is sticky, while the more precise recovery
        observation and all previously captured ownership evidence remain
        durable.
        """
        if not isinstance(final_inspection, Mapping) or not isinstance(detail, str) or not detail:
            raise ValidationFailure("retained verification recovery evidence is invalid")
        with self._transaction() as conn:
            lease = conn.execute("""SELECT * FROM workspace_operation_leases WHERE lease_id=? AND attempt_id=?
                AND owner_instance_id=? AND operation_kind='verification'""",
                (lease_id, attempt_id, owner_instance_id)).fetchone()
            attempt = conn.execute("SELECT * FROM verification_attempts WHERE id=? AND lease_id=?",
                (attempt_id, lease_id)).fetchone()
            if lease is None or attempt is None or attempt["status"] not in {"verifying", "unknown"}:
                raise ConflictFailure("retained verification recovery lacks exact active lease ownership")
            self._retain_verification_unknown_unlocked(conn, attempt, lease,
                final_inspection=final_inspection, detail=detail, recovery=True)

    def retain_inconsistent_verification_lease(self, *, workflow_id: str, lease_id: str,
                                               attempt_id: str, operation_id: str,
                                               owner_instance_id: str,
                                               evidence: Mapping[str, Any], detail: str) -> None:
        """Project HUMAN_ATTENTION without claiming a corrupt attempt linkage."""
        with self._transaction() as conn:
            lease = conn.execute("""SELECT 1 FROM workspace_operation_leases WHERE workflow_id=?
                AND lease_id=? AND attempt_id=? AND operation_id=? AND owner_instance_id=?
                AND operation_kind='verification'""",
                (workflow_id, lease_id, attempt_id, operation_id, owner_instance_id)).fetchone()
            if lease is None:
                raise ConflictFailure("inconsistent verification lease ownership changed")
            workflow = conn.execute("SELECT status FROM workflows WHERE id=?", (workflow_id,)).fetchone()
            if workflow is None:
                raise ConflictFailure("inconsistent verification lease workflow is missing")
            conn.execute("UPDATE workflows SET stage=?,status=?,updated_at=? WHERE id=?",
                (Stage.TASK_EXECUTION.value, WorkflowStatus.HUMAN_ATTENTION.value, _now(), workflow_id))
            prior = conn.execute("""SELECT 1 FROM events WHERE workflow_id=?
                AND type='verification.recovery.inconsistent_lease'""", (workflow_id,)).fetchone()
            if prior is None:
                self._event_unlocked(conn, workflow_id, "verification.recovery.inconsistent_lease",
                    stage=Stage.TASK_EXECUTION,
                    payload={"attempt_id": attempt_id, "reason": detail, "identity": dict(evidence)})

    def list_implementation_attempts(self, workflow_id: str) -> list[Mapping[str, Any]]:
        """Return bounded operational evidence for the CLI status projection."""
        rows = self._connection.execute(
            """SELECT id, task_contract_id, sequence, status, result_classification,
                      requested_profile, requested_model, requested_reasoning,
                      actual_provider, actual_model, actual_reasoning, started_at,
                      finished_at, workspace_changed, changed_paths_json,
                      error_classification, error_detail
               FROM implementation_attempts WHERE workflow_id = ?
               ORDER BY created_at, sequence""",
            (workflow_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def request_plan_changes(self, workflow_id: str, target_plan_artifact_id: str, feedback: str, *, actor: str = "human") -> PlanChangeRequest:
        if not isinstance(feedback, str) or not feedback.strip():
            raise ValidationFailure("Plan feedback must be non-empty")
        if not actor:
            raise ValidationFailure("Plan feedback actor is required")
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            workflow = conn.execute("SELECT lifecycle_version, stage, status FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
            if workflow is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            if workflow["lifecycle_version"] != LifecycleVersion.V2.value:
                raise ConflictFailure("workflow is not V2")
            target = conn.execute("SELECT * FROM artifacts WHERE id = ? AND workflow_id = ?", (target_plan_artifact_id, workflow_id)).fetchone()
            if target is None or target["stage"] != Stage.PLAN.value:
                raise ConflictFailure("Plan feedback requires a workflow Plan artifact")
            existing = conn.execute("SELECT * FROM plan_change_requests WHERE target_plan_artifact_id = ?", (target_plan_artifact_id,)).fetchone()
            if existing is not None:
                if existing["feedback"] == feedback:
                    return self._plan_change_request_from_row(existing)
                raise ConflictFailure("Plan already has a different change request")
            if workflow["stage"] != Stage.PLAN.value or workflow["status"] != WorkflowStatus.AWAITING_APPROVAL.value:
                raise ConflictFailure("workflow is not awaiting Plan approval")
            latest = conn.execute("SELECT id FROM artifacts WHERE workflow_id = ? AND stage = ? ORDER BY revision DESC LIMIT 1", (workflow_id, Stage.PLAN.value)).fetchone()
            if latest is None or latest["id"] != target_plan_artifact_id or target["approval_state"] != ApprovalState.PENDING.value:
                raise ConflictFailure("Plan feedback targets a stale or non-pending Plan artifact")
            if conn.execute("SELECT 1 FROM plan_change_requests WHERE workflow_id = ? AND replacement_plan_artifact_id IS NULL", (workflow_id,)).fetchone() is not None:
                raise ConflictFailure("workflow already has an unresolved Plan change request")
            now = _now()
            request = PlanChangeRequest(str(uuid.uuid4()), workflow_id, conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM plan_change_requests WHERE workflow_id = ?", (workflow_id,)).fetchone()[0], target_plan_artifact_id, feedback, sanitize_text(actor, self.secret_values), None, now, None)
            conn.execute("INSERT INTO plan_change_requests (id, workflow_id, sequence, target_plan_artifact_id, feedback, actor, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (request.id, request.workflow_id, request.sequence, request.target_plan_artifact_id, request.feedback, request.actor, now))
            conn.execute("UPDATE artifacts SET approval_state = ? WHERE id = ?", (ApprovalState.CHANGES_REQUESTED.value, target_plan_artifact_id))
            conn.execute("UPDATE workflows SET stage = ?, status = ?, updated_at = ? WHERE id = ?", (Stage.PLAN.value, WorkflowStatus.CHANGES_REQUESTED.value, now, workflow_id))
            self._event_unlocked(conn, workflow_id, "plan.changes_requested", stage=Stage.PLAN, artifact_id=target_plan_artifact_id, payload={"change_request_id": request.id, "sequence": request.sequence})
        return self.get_open_plan_change_request(workflow_id)  # type: ignore[return-value]

    def list_clarifications(self, workflow_id: str) -> list[Clarification]:
        rows = self._connection.execute("SELECT * FROM clarifications WHERE workflow_id = ? ORDER BY sequence", (workflow_id,)).fetchall()
        return [self._clarification_from_row(row) for row in rows]

    def get_active_clarification(self, workflow_id: str) -> Clarification | None:
        rows = self._connection.execute("SELECT * FROM clarifications WHERE workflow_id = ? AND result_feature_contract_artifact_id IS NULL ORDER BY sequence", (workflow_id,)).fetchall()
        if len(rows) > 1:
            raise PersistenceFailure("workflow has multiple active clarifications")
        return self._clarification_from_row(rows[0]) if rows else None

    def answer_clarification(self, workflow_id: str, clarification_id: str, answer: str, *, actor: str = "human") -> Clarification:
        if not isinstance(answer, str) or not answer.strip():
            raise ValidationFailure("clarification answer must be non-empty")
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            row = conn.execute("SELECT * FROM clarifications WHERE id = ? AND workflow_id = ?", (clarification_id, workflow_id)).fetchone()
            if row is None:
                raise NotFoundFailure("clarification not found for workflow")
            if row["result_feature_contract_artifact_id"] is not None:
                raise ConflictFailure("clarification is already completed")
            if row["answer"] is not None:
                if row["answer"] == answer:
                    return self._clarification_from_row(row)
                raise ConflictFailure("clarification already has a different answer")
            if conn.execute("SELECT COUNT(*) FROM clarifications WHERE workflow_id = ? AND result_feature_contract_artifact_id IS NULL", (workflow_id,)).fetchone()[0] != 1:
                raise PersistenceFailure("workflow does not have exactly one active clarification")
            now = _now()
            conn.execute("UPDATE clarifications SET answer = ?, actor = ?, answered_at = ? WHERE id = ?", (answer, actor, now, clarification_id))
            self._event_unlocked(conn, workflow_id, "clarification.answered", stage=Stage.INTAKE, payload={"clarification_id": clarification_id})
            row = conn.execute("SELECT * FROM clarifications WHERE id = ?", (clarification_id,)).fetchone()
        return self._clarification_from_row(row)

    def complete_generation(
        self,
        operation_key: str,
        *,
        content: str,
        artifact_path: str | os.PathLike[str],
        stage: Stage | str,
        revision: int,
        terminal_result: Mapping[str, Any] | None = None,
        workflow_stage: Stage | str | None = None,
        workflow_status: WorkflowStatus | str | None = None,
        approval_state: ApprovalState | str = ApprovalState.PENDING,
        completion_event_type: str | None = None,
        completion_event_payload: Mapping[str, Any] | None = None,
        result_clarification_id: str | None = None,
        next_clarification_question: str | None = None,
        result_plan_change_request_id: str | None = None,
    ) -> Artifact:
        stage = self._require_enum(stage, Stage)
        if workflow_status is not None:
            workflow_status = self._require_enum(workflow_status, WorkflowStatus)
        if workflow_stage is not None:
            workflow_stage = self._require_enum(workflow_stage, Stage)
        approval_state = self._require_enum(approval_state, ApprovalState)
        if revision < 1:
            raise ValidationFailure("artifact revision must be positive")
        with self._transaction() as conn:
            operation_row = conn.execute("SELECT * FROM operations WHERE idempotency_key = ?", (operation_key,)).fetchone()
            if operation_row is None:
                raise NotFoundFailure(f"operation not found: {operation_key}")
            operation = self._operation_from_row(operation_row)
            self._require_no_unresolved_verification_unlocked(conn, operation.workflow_id)
            expected_stage, expected_revision, expected_path = self._generation_binding(
                operation_row, workflow_id=operation.workflow_id
            )
            if stage is not expected_stage:
                raise ValidationFailure(
                    f"generation stage does not match intent: expected {expected_stage.value}"
                )
            if revision != expected_revision:
                raise ValidationFailure(
                    f"artifact revision does not match intent: expected {expected_revision}"
                )
            destination = self._artifact_destination(artifact_path)
            if destination != expected_path:
                raise ValidationFailure(
                    f"artifact destination does not match intent: expected {expected_path}"
                )
            if operation.status is OperationStatus.COMPLETED:
                artifact_row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (operation.related_record_id,)).fetchone()
                if artifact_row is not None:
                    return self._artifact_from_row(artifact_row)
            execution_id = operation.related_record_id
            execution = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
            if execution is None:
                raise PersistenceFailure("generation operation has no execution")
            workflow_id = operation.workflow_id
            artifact_id = str(uuid.uuid4())
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    existing_bytes = destination.read_bytes()
                    if existing_bytes != content.encode("utf-8"):
                        raise ConflictFailure("artifact destination is already immutable")
                else:
                    destination.write_text(content, encoding="utf-8", newline="")
            except OSError as exc:
                raise PersistenceFailure(f"could not write artifact: {exc}") from exc
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            now = _now()
            conn.execute(
                """INSERT INTO artifacts
                (id, workflow_id, stage, revision, path, sha256, source_execution_id, approval_state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (artifact_id, workflow_id, stage.value, revision, str(destination), digest, execution_id,
                 approval_state.value, now),
            )
            conn.execute("UPDATE executions SET lifecycle = ?, terminal_result = ?, updated_at = ? WHERE id = ?",
                         (ExecutionLifecycle.COMPLETED.value, _json(sanitize_payload(terminal_result or {}, self.secret_values)), now, execution_id))
            conn.execute("UPDATE operations SET status = ?, related_record_id = ?, updated_at = ? WHERE id = ?",
                         (OperationStatus.COMPLETED.value, artifact_id, now, operation.id))
            conn.execute("""UPDATE workflows
                         SET current_artifact_revision = MAX(COALESCE(current_artifact_revision, 0), ?),
                             updated_at = ? WHERE id = ?""",
                         (revision, now, workflow_id))
            self._event_unlocked(conn, workflow_id, "agent.execution.completed", stage=stage,
                                 artifact_id=artifact_id, execution_id=execution_id, payload=terminal_result)
            self._event_unlocked(conn, workflow_id, "artifact.created", stage=stage,
                                 artifact_id=artifact_id, execution_id=execution_id,
                                 payload={"revision": revision, "sha256": digest})
            if workflow_status is not None:
                conn.execute("UPDATE workflows SET stage = COALESCE(?, stage), status = ?, updated_at = ? WHERE id = ?",
                             (workflow_stage.value if workflow_stage else None, workflow_status.value, now, workflow_id))
            if result_clarification_id is not None:
                if stage is not Stage.INTAKE:
                    raise ValidationFailure("clarification results require an Intake artifact")
                clarification = conn.execute("SELECT * FROM clarifications WHERE id = ? AND workflow_id = ?", (result_clarification_id, workflow_id)).fetchone()
                if clarification is None or clarification["answer"] is None or clarification["result_feature_contract_artifact_id"] is not None:
                    raise ConflictFailure("clarification cannot be linked to an Intake result")
                source_row = conn.execute("SELECT workflow_id, stage FROM artifacts WHERE id = ?", (clarification["source_feature_contract_artifact_id"],)).fetchone()
                if source_row is None or source_row["workflow_id"] != workflow_id or source_row["stage"] != Stage.INTAKE.value:
                    raise PersistenceFailure("clarification source artifact binding is invalid")
                conn.execute("UPDATE clarifications SET result_feature_contract_artifact_id = ?, completed_at = ? WHERE id = ?", (artifact_id, now, result_clarification_id))
                self._event_unlocked(conn, workflow_id, "clarification.completed", stage=Stage.INTAKE, artifact_id=artifact_id, payload={"clarification_id": result_clarification_id})
            if next_clarification_question is not None:
                if stage is not Stage.INTAKE:
                    raise ValidationFailure("clarifications require an Intake artifact")
                if not isinstance(next_clarification_question, str) or not next_clarification_question.strip():
                    raise ValidationFailure("clarification question must be non-empty")
                if conn.execute("SELECT COUNT(*) FROM clarifications WHERE workflow_id = ? AND result_feature_contract_artifact_id IS NULL", (workflow_id,)).fetchone()[0]:
                    raise ConflictFailure("workflow already has an active clarification")
                sequence = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM clarifications WHERE workflow_id = ?", (workflow_id,)).fetchone()[0]
                clarification_id = str(uuid.uuid4())
                conn.execute("INSERT INTO clarifications (id, workflow_id, sequence, source_feature_contract_artifact_id, question, created_at) VALUES (?, ?, ?, ?, ?, ?)", (clarification_id, workflow_id, sequence, artifact_id, next_clarification_question, now))
                self._event_unlocked(conn, workflow_id, "clarification.created", stage=Stage.INTAKE, artifact_id=artifact_id, payload={"clarification_id": clarification_id, "sequence": sequence})
            if result_plan_change_request_id is not None:
                if stage is not Stage.PLAN:
                    raise ValidationFailure("Plan change request results require a Plan artifact")
                change = conn.execute("SELECT * FROM plan_change_requests WHERE id = ? AND workflow_id = ?", (result_plan_change_request_id, workflow_id)).fetchone()
                if change is None or change["replacement_plan_artifact_id"] is not None:
                    raise ConflictFailure("Plan change request cannot be linked to a replacement")
                target = conn.execute("SELECT workflow_id, stage FROM artifacts WHERE id = ?", (change["target_plan_artifact_id"],)).fetchone()
                if target is None or target["workflow_id"] != workflow_id or target["stage"] != Stage.PLAN.value:
                    raise PersistenceFailure("Plan change request target binding is invalid")
                conn.execute("UPDATE plan_change_requests SET replacement_plan_artifact_id = ?, completed_at = ? WHERE id = ?", (artifact_id, now, result_plan_change_request_id))
                self._event_unlocked(conn, workflow_id, "plan.change_request.completed", stage=Stage.PLAN, artifact_id=artifact_id, payload={"change_request_id": result_plan_change_request_id})
            if completion_event_type:
                self._event_unlocked(conn, workflow_id, completion_event_type, stage=stage,
                                     artifact_id=artifact_id, execution_id=execution_id,
                                     payload=completion_event_payload)
        return self.get_artifact(artifact_id)

    def _task_artifact_destination(
        self,
        workflow_id: str,
        ordinal: int,
        key: str,
        artifact_type: TaskArtifactType,
        *,
        review_window: int = 1,
        cycle: int = 1,
    ) -> Path:
        safe_key = re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("._") or f"task-{ordinal:03d}"
        root = self.workspace_path / "workflows" / workflow_id / "tasks" / f"{ordinal:03d}-{safe_key}"
        if artifact_type is TaskArtifactType.DEFINITION:
            destination = root / "definition.json"
        else:
            names = {
                TaskArtifactType.DEVELOPER_RESULT: "developer-result.json",
                TaskArtifactType.TEST_RESULT: "required-tests.json",
                TaskArtifactType.REVIEW_RESULT: "review-result.json",
            }
            cycle_root = root / "cycles" / f"{cycle:03d}"
            if review_window > 1:
                cycle_root = root / "windows" / f"{review_window:03d}" / "cycles" / f"{cycle:03d}"
            destination = cycle_root / names[artifact_type]
        return self._artifact_destination(destination)

    def _write_task_artifact_unlocked(
        self,
        conn: sqlite3.Connection,
        *,
        workflow_id: str,
        task_id: str,
        ordinal: int,
        key: str,
        artifact_type: TaskArtifactType,
        content: bytes,
        cycle_id: str | None = None,
        source_execution_id: str | None = None,
        review_window: int = 1,
        cycle: int = 1,
    ) -> TaskArtifact:
        destination = self._task_artifact_destination(
            workflow_id, ordinal, key, artifact_type,
            review_window=review_window, cycle=cycle,
        )
        digest = hashlib.sha256(content).hexdigest()
        existing = conn.execute("SELECT * FROM task_artifacts WHERE path = ?", (str(destination),)).fetchone()
        if existing is not None:
            if existing["sha256"] != digest:
                raise ConflictFailure(f"task artifact destination is already immutable: {destination}")
            return self._task_artifact_from_row(existing)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != content:
                raise ConflictFailure(f"task artifact destination is already immutable: {destination}")
            if not destination.exists():
                destination.write_bytes(content)
        except OSError as exc:
            raise PersistenceFailure(f"could not write task artifact: {exc}") from exc
        artifact_id = str(uuid.uuid4())
        created_at = _now()
        conn.execute(
            """INSERT INTO task_artifacts
            (id, workflow_id, task_id, cycle_id, artifact_type, path, sha256,
             source_execution_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (artifact_id, workflow_id, task_id, cycle_id, artifact_type.value,
             str(destination), digest, source_execution_id, created_at),
        )
        return TaskArtifact(artifact_id, workflow_id, task_id, cycle_id, artifact_type,
                            str(destination), digest, source_execution_id, created_at)

    def import_task_plan(self, workflow_id: str, artifact_id: str | Artifact | None = None) -> list[TaskDefinition]:
        """Atomically import the approved task-plan manifest exactly once."""
        if hasattr(artifact_id, "id"):
            artifact_id = artifact_id.id
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            workflow_row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
            if workflow_row is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            if artifact_id is None:
                artifact_row = conn.execute(
                    """SELECT * FROM artifacts WHERE workflow_id = ? AND stage = ?
                       AND approval_state IN (?, ?) ORDER BY revision DESC LIMIT 1""",
                    (workflow_id, Stage.TASK_PLAN.value, ApprovalState.APPROVED.value,
                     ApprovalState.AUTO_APPROVED.value),
                ).fetchone()
                artifact_id = artifact_row["id"] if artifact_row is not None else None
            else:
                artifact_row = conn.execute(
                    "SELECT * FROM artifacts WHERE id = ? AND workflow_id = ?", (artifact_id, workflow_id)
                ).fetchone()
            if artifact_row is None:
                raise NotFoundFailure(f"artifact not found: {artifact_id}")
            if artifact_row["stage"] != Stage.TASK_PLAN.value:
                raise ValidationFailure("task-plan import requires a TASK_PLAN artifact")
            if artifact_row["approval_state"] not in (
                ApprovalState.APPROVED.value, ApprovalState.AUTO_APPROVED.value
            ):
                raise ValidationFailure("task-plan artifact must be explicitly approved before import")
            try:
                content = Path(artifact_row["path"]).read_bytes()
                text = content.decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ArtifactCorruptionFailure("task-plan artifact cannot be read as UTF-8") from exc
            source_digest = hashlib.sha256(content).hexdigest()
            if source_digest != artifact_row["sha256"]:
                raise ArtifactCorruptionFailure(
                    f"artifact hash mismatch for {artifact_id}",
                    details={"expected": artifact_row["sha256"], "actual": source_digest},
                )
            existing_rows = conn.execute(
                "SELECT * FROM tasks WHERE workflow_id = ? ORDER BY ordinal", (workflow_id,)
            ).fetchall()
            if existing_rows:
                hashes = {row["source_artifact_sha256"] for row in existing_rows}
                if hashes != {source_digest}:
                    raise ConflictFailure("workflow already contains a task plan from a different source artifact")
                return [self._task_from_row(row) for row in existing_rows]
            manifest = parse_task_plan_manifest(text, workflow_row["repository_path"])
            imported: list[TaskDefinition] = []
            for entry in manifest:
                definition = {
                    "key": entry["key"],
                    "title": entry["title"],
                    "instructions": entry["instructions"],
                    "acceptance_criteria": list(entry["acceptance_criteria"]),
                    "required_tests": list(entry["required_tests"]),
                    "context_paths": list(entry["context_paths"]),
                }
                definition_json = _json(definition)
                definition_hash = hashlib.sha256(definition_json.encode("utf-8")).hexdigest()
                task_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO tasks
                    (id, workflow_id, ordinal, key, title, instructions,
                     acceptance_criteria, required_tests, context_paths,
                     definition_json, definition_sha256, source_artifact_id,
                     source_artifact_sha256, status, current_review_window,
                     current_cycle, accepted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, NULL)""",
                    (task_id, workflow_id, entry["ordinal"], entry["key"], entry["title"],
                     entry["instructions"], _json(entry["acceptance_criteria"]),
                     _json(entry["required_tests"]), _json(entry["context_paths"]),
                     definition_json, definition_hash, artifact_id, source_digest,
                     TaskStatus.PENDING.value),
                )
                artifact = self._write_task_artifact_unlocked(
                    conn, workflow_id=workflow_id, task_id=task_id,
                    ordinal=entry["ordinal"], key=entry["key"],
                    artifact_type=TaskArtifactType.DEFINITION,
                    content=definition_json.encode("utf-8"),
                )
                imported.append(TaskDefinition(
                    task_id, workflow_id, entry["ordinal"], entry["key"], entry["title"],
                    entry["instructions"], entry["acceptance_criteria"], entry["required_tests"],
                    entry["context_paths"], definition_json, definition_hash, artifact_id,
                    source_digest, TaskStatus.PENDING, 1, 0, None,
                ))
                self._event_unlocked(
                    conn, workflow_id, "task.imported", stage=Stage.TASK_EXECUTION,
                    artifact_id=artifact.id, payload={"task_id": task_id, "key": entry["key"], "ordinal": entry["ordinal"]},
                )
            return imported

    # Compatibility spellings keep the persistence boundary easy to discover.
    import_task_definitions = import_task_plan
    import_tasks = import_task_plan
    import_task_plan_artifact = import_task_plan

    def get_task(self, task_id: str) -> TaskDefinition:
        row = self._connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"task not found: {task_id}")
        return self._task_from_row(row)

    def list_tasks(self, workflow_id: str) -> list[TaskDefinition]:
        rows = self._connection.execute(
            "SELECT * FROM tasks WHERE workflow_id = ? ORDER BY ordinal", (workflow_id,)
        ).fetchall()
        return [self._task_from_row(row) for row in rows]

    get_tasks = list_tasks

    def select_next_task(self, workflow_id: str) -> TaskDefinition | None:
        row = self._connection.execute(
            """SELECT * FROM tasks WHERE workflow_id = ? AND status != ?
               ORDER BY ordinal LIMIT 1""",
            (workflow_id, TaskStatus.ACCEPTED.value),
        ).fetchone()
        return self._task_from_row(row) if row else None

    def get_task_artifact(self, artifact_id: str) -> TaskArtifact:
        row = self._connection.execute("SELECT * FROM task_artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"task artifact not found: {artifact_id}")
        return self._task_artifact_from_row(row)

    def list_task_artifacts(self, task_id: str) -> list[TaskArtifact]:
        rows = self._connection.execute(
            "SELECT * FROM task_artifacts WHERE task_id = ? ORDER BY created_at", (task_id,)
        ).fetchall()
        return [self._task_artifact_from_row(row) for row in rows]

    def read_task_artifact(self, artifact_id: str) -> bytes:
        artifact = self.get_task_artifact(artifact_id)
        task = self.get_task(artifact.task_id)
        review_window = 1
        cycle = 1
        if artifact.cycle_id is not None:
            cycle_row = self._connection.execute(
                "SELECT review_window, cycle FROM task_cycles WHERE id = ? AND task_id = ?",
                (artifact.cycle_id, artifact.task_id),
            ).fetchone()
            if cycle_row is None:
                raise ArtifactCorruptionFailure(f"task artifact cycle binding is invalid: {artifact.id}")
            review_window, cycle = cycle_row["review_window"], cycle_row["cycle"]
        expected_path = self._task_artifact_destination(
            artifact.workflow_id, task.ordinal, task.key, artifact.artifact_type,
            review_window=review_window, cycle=cycle,
        )
        if Path(artifact.path).resolve() != expected_path:
            raise ArtifactCorruptionFailure(f"task artifact path binding is invalid: {artifact.id}")
        try:
            content = Path(artifact.path).read_bytes()
        except OSError as exc:
            raise PersistenceFailure(f"could not read task artifact: {exc}") from exc
        digest = hashlib.sha256(content).hexdigest()
        if digest != artifact.sha256:
            raise ArtifactCorruptionFailure(
                f"task artifact hash mismatch for {artifact.id}",
                details={"expected": artifact.sha256, "actual": digest},
            )
        return content

    def read_task_artifact_text(self, artifact_id: str) -> str:
        try:
            return self.read_task_artifact(artifact_id).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactCorruptionFailure(f"task artifact is not valid UTF-8: {artifact_id}") from exc

    verify_task_artifact = read_task_artifact

    def read_task_definition(self, task_id: str) -> str:
        task = self.get_task(task_id)
        content = task.definition_json.encode("utf-8")
        if hashlib.sha256(content).hexdigest() != task.definition_sha256:
            raise ArtifactCorruptionFailure(f"task definition hash mismatch for {task.id}")
        definition_artifact = next(
            artifact for artifact in self.list_task_artifacts(task_id)
            if artifact.artifact_type is TaskArtifactType.DEFINITION
        )
        if self.read_task_artifact(definition_artifact.id) != content:
            raise ArtifactCorruptionFailure(f"task definition artifact mismatch for {task.id}")
        return task.definition_json

    def create_task_cycle(
        self,
        task_id: str,
        *,
        review_window: int = 1,
        cycle: int = 1,
    ) -> TaskCycle:
        if review_window < 1 or cycle < 1:
            raise ValidationFailure("task review window and cycle must be positive")
        with self._transaction() as conn:
            task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task_row is None:
                raise NotFoundFailure(f"task not found: {task_id}")
            self._require_no_unresolved_verification_unlocked(conn, task_row["workflow_id"])
            existing = conn.execute(
                "SELECT * FROM task_cycles WHERE task_id = ? AND review_window = ? AND cycle = ?",
                (task_id, review_window, cycle),
            ).fetchone()
            if existing is not None:
                return self._task_cycle_from_row(existing)
            cycle_id = str(uuid.uuid4())
            now = _now()
            conn.execute(
                """INSERT INTO task_cycles
                (id, task_id, review_window, cycle, developer_execution_id,
                 required_test_artifact_id, reviewer_execution_id, review_artifact_id,
                 outcome, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?)""",
                (cycle_id, task_id, review_window, cycle, now, now),
            )
            return TaskCycle(cycle_id, task_id, review_window, cycle, None, None, None, None, None, now, now)

    def get_task_cycle(self, cycle_id: str) -> TaskCycle:
        row = self._connection.execute("SELECT * FROM task_cycles WHERE id = ?", (cycle_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"task cycle not found: {cycle_id}")
        return self._task_cycle_from_row(row)

    def list_task_cycles(self, task_id: str) -> list[TaskCycle]:
        rows = self._connection.execute(
            "SELECT * FROM task_cycles WHERE task_id = ? ORDER BY review_window, cycle", (task_id,)
        ).fetchall()
        return [self._task_cycle_from_row(row) for row in rows]

    def create_task_operation(
        self,
        workflow_id: str,
        task_id: str,
        *,
        review_window: int = 1,
        cycle: int = 1,
        work_kind: WorkKind | str = WorkKind.DEVELOP,
        request_hash: str,
        provider: str = "codex-cli",
        role: Role | str | None = None,
        capability_report: Mapping[str, Any] | None = None,
    ) -> TaskOperationIntent:
        work_kind = self._require_enum(work_kind, WorkKind)
        if role is None:
            role = Role.REVIEWER if work_kind is WorkKind.REVIEW else Role.DEVELOPER
        role = self._require_enum(role, Role)
        if role not in (Role.DEVELOPER, Role.REVIEWER):
            raise ValidationFailure("task operations require Developer or Reviewer role")
        expected_role = Role.REVIEWER if work_kind is WorkKind.REVIEW else Role.DEVELOPER
        if role is not expected_role:
            raise ValidationFailure(
                f"{work_kind.value} task operations require the {expected_role.value} role"
            )
        if not request_hash:
            raise ValidationFailure("request_hash is required")
        if review_window < 1 or cycle < 1:
            raise ValidationFailure("task review window and cycle must be positive")
        key = f"workflow:{workflow_id}:task:{task_id}:window:{review_window}:cycle:{cycle}:{work_kind.value}"
        with self._transaction() as conn:
            task_row = conn.execute(
                "SELECT * FROM tasks WHERE id = ? AND workflow_id = ?", (task_id, workflow_id)
            ).fetchone()
            if task_row is None:
                raise NotFoundFailure(f"task not found: {task_id}")
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            cycle_row = conn.execute(
                "SELECT * FROM task_cycles WHERE task_id = ? AND review_window = ? AND cycle = ?",
                (task_id, review_window, cycle),
            ).fetchone()
            if cycle_row is None:
                cycle_id = str(uuid.uuid4())
                now = _now()
                conn.execute(
                    """INSERT INTO task_cycles
                    (id, task_id, review_window, cycle, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (cycle_id, task_id, review_window, cycle, now, now),
                )
            else:
                cycle_id = cycle_row["id"]
            existing = conn.execute("SELECT * FROM operations WHERE idempotency_key = ?", (key,)).fetchone()
            if existing is not None:
                operation = self._operation_from_row(existing)
                execution_id = operation.related_record_id
                execution_row = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
                if execution_row is None and operation.status is OperationStatus.COMPLETED:
                    execution_row = conn.execute(
                        """SELECT e.* FROM executions e JOIN task_artifacts a
                           ON a.source_execution_id = e.id WHERE a.id = ?""",
                        (execution_id,),
                    ).fetchone()
                if execution_row is None:
                    raise PersistenceFailure("task operation has no execution record")
                return TaskOperationIntent(operation, self._execution_from_row(execution_row), task_id, cycle_id, True)
            now = _now()
            # A Developer's logical session belongs to the task rather than a
            # single review cycle.  Each operation still gets its own durable
            # session row/correlation, but remediation can carry the stable
            # logical identity into the runtime.  Reviewer sessions are
            # intentionally always fresh.
            logical_session_id = None
            if role is Role.DEVELOPER:
                prior_session = conn.execute(
                    """SELECT logical_session_id FROM sessions
                       WHERE workflow_id = ? AND task_id = ? AND role = ?
                       ORDER BY created_at LIMIT 1""",
                    (workflow_id, task_id, Role.DEVELOPER.value),
                ).fetchone()
                if prior_session is not None:
                    logical_session_id = prior_session["logical_session_id"]
            session = self._create_session_unlocked(
                conn, workflow_id, provider, role, logical_session_id,
                task_id=task_id, cycle_id=cycle_id, work_kind=work_kind,
            )
            execution_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO executions
                (id, workflow_id, session_id, role, provider_execution_id, request_hash,
                 lifecycle, capability_report, terminal_result, failure_classification,
                 failure_detail, task_id, cycle_id, work_kind, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, ?)""",
                (execution_id, workflow_id, session.id, role.value, request_hash,
                 ExecutionLifecycle.INTENT.value,
                 _json(sanitize_payload(capability_report or {}, self.secret_values)),
                 task_id, cycle_id, work_kind.value, now, now),
            )
            operation = Operation(
                str(uuid.uuid4()), key, work_kind.value, workflow_id,
                OperationStatus.PENDING, execution_id, now, now, task_id, cycle_id, work_kind,
            )
            conn.execute(
                """INSERT INTO operations
                (id, idempotency_key, kind, workflow_id, status, related_record_id,
                 task_id, cycle_id, work_kind, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (operation.id, key, operation.kind, workflow_id, operation.status.value,
                 execution_id, task_id, cycle_id, work_kind.value, now, now),
            )
            conn.execute("UPDATE tasks SET status = ?, current_review_window = ?, current_cycle = ? WHERE id = ?",
                         (TaskStatus.ACTIVE.value, review_window, cycle, task_id))
            self._event_unlocked(
                conn, workflow_id, "task.started", stage=Stage.TASK_EXECUTION,
                execution_id=execution_id, payload={"task_id": task_id, "cycle_id": cycle_id,
                                                    "work_kind": work_kind.value, "review_window": review_window,
                                                    "cycle": cycle},
            )
            execution_row = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
            return TaskOperationIntent(operation, self._execution_from_row(execution_row), task_id, cycle_id, False)

    create_task_execution_intent = create_task_operation
    create_task_intent = create_task_operation
    create_task_operation_intent = create_task_operation

    def complete_task_operation(
        self,
        operation_key: str,
        *,
        content: str | bytes | Mapping[str, Any],
        artifact_type: TaskArtifactType | str,
        terminal_result: Mapping[str, Any] | None = None,
        outcome: str | None = None,
    ) -> TaskArtifact:
        artifact_type = self._require_enum(artifact_type, TaskArtifactType)
        if isinstance(content, bytes):
            encoded = content
        elif isinstance(content, str):
            encoded = sanitize_text(content, self.secret_values).encode("utf-8")
        else:
            encoded = _json(sanitize_payload(content, self.secret_values)).encode("utf-8")
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM operations WHERE idempotency_key = ?", (operation_key,)).fetchone()
            if row is None:
                raise NotFoundFailure(f"operation not found: {operation_key}")
            operation = self._operation_from_row(row)
            self._require_no_unresolved_verification_unlocked(conn, operation.workflow_id)
            task_id = operation.task_id
            if task_id is None:
                raise ValidationFailure("operation is not task-correlated")
            task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task_row is None:
                raise NotFoundFailure(f"task not found: {task_id}")
            cycle_id = operation.cycle_id
            cycle_row = conn.execute("SELECT * FROM task_cycles WHERE id = ?", (cycle_id,)).fetchone()
            if cycle_row is None:
                raise PersistenceFailure("task operation has no cycle")
            expected_artifact_type = {
                WorkKind.DEVELOP: TaskArtifactType.DEVELOPER_RESULT,
                WorkKind.FIX: TaskArtifactType.DEVELOPER_RESULT,
                WorkKind.REVIEW: TaskArtifactType.REVIEW_RESULT,
            }.get(operation.work_kind)
            if expected_artifact_type is None or artifact_type is not expected_artifact_type:
                raise ValidationFailure("task operation work kind is incompatible with artifact type")
            if operation.status is OperationStatus.COMPLETED:
                existing_artifact = conn.execute(
                    "SELECT * FROM task_artifacts WHERE id = ?", (operation.related_record_id,)
                ).fetchone()
                if existing_artifact is not None:
                    return self._task_artifact_from_row(existing_artifact)
            execution_id = operation.related_record_id
            execution_row = conn.execute(
                "SELECT role, work_kind FROM executions WHERE id = ?", (execution_id,)
            ).fetchone()
            if execution_row is None:
                raise PersistenceFailure("task operation has no execution record")
            expected_role = Role.REVIEWER if operation.work_kind is WorkKind.REVIEW else Role.DEVELOPER
            if (execution_row["role"] != expected_role.value
                    or execution_row["work_kind"] != operation.work_kind.value):
                raise ValidationFailure("task operation execution has incompatible role or work kind")
            artifact = self._write_task_artifact_unlocked(
                conn, workflow_id=operation.workflow_id, task_id=task_id,
                ordinal=task_row["ordinal"], key=task_row["key"], artifact_type=artifact_type,
                content=encoded, cycle_id=cycle_id, source_execution_id=operation.related_record_id,
                review_window=cycle_row["review_window"], cycle=cycle_row["cycle"],
            )
            now = _now()
            conn.execute(
                """UPDATE executions SET lifecycle = ?, terminal_result = ?, updated_at = ?
                   WHERE id = ?""",
                (ExecutionLifecycle.COMPLETED.value,
                 _json(sanitize_payload(terminal_result or {}, self.secret_values)), now,
                 operation.related_record_id),
            )
            conn.execute(
                "UPDATE operations SET status = ?, related_record_id = ?, updated_at = ? WHERE id = ?",
                (OperationStatus.COMPLETED.value, artifact.id, now, operation.id),
            )
            if artifact_type is TaskArtifactType.DEVELOPER_RESULT:
                existing_execution_id = cycle_row["developer_execution_id"]
                if existing_execution_id is not None and existing_execution_id != execution_id:
                    raise ConflictFailure("task cycle already has a different Developer execution")
                conn.execute(
                    """UPDATE task_cycles
                       SET developer_execution_id = ?, outcome = COALESCE(?, outcome), updated_at = ?
                       WHERE id = ?""",
                    (execution_id, outcome, now, cycle_id),
                )
            else:
                existing_execution_id = cycle_row["reviewer_execution_id"]
                if existing_execution_id is not None and existing_execution_id != execution_id:
                    raise ConflictFailure("task cycle already has a different Reviewer execution")
                if (cycle_row["review_artifact_id"] is not None
                        and cycle_row["review_artifact_id"] != artifact.id):
                    raise ConflictFailure("task cycle already has a different review artifact")
                conn.execute(
                    """UPDATE task_cycles
                       SET reviewer_execution_id = ?, review_artifact_id = ?,
                           outcome = COALESCE(?, outcome), updated_at = ?
                       WHERE id = ?""",
                    (execution_id, artifact.id, outcome, now, cycle_id),
                )
            event_type = {
                TaskArtifactType.DEVELOPER_RESULT: "task.developer.completed",
                TaskArtifactType.REVIEW_RESULT: "review.completed",
            }.get(artifact_type, "task.artifact.created")
            self._event_unlocked(
                conn, operation.workflow_id, event_type, stage=Stage.TASK_EXECUTION,
                artifact_id=artifact.id, execution_id=operation.related_record_id,
                payload={"task_id": task_id, "cycle_id": cycle_id, "artifact_type": artifact_type.value,
                         "sha256": artifact.sha256},
            )
            return artifact

    complete_task_execution = complete_task_operation
    complete_task_operation_intent = complete_task_operation

    def record_task_test_evidence(
        self,
        task_id: str,
        cycle_id: str,
        *,
        content: str | bytes | Mapping[str, Any],
    ) -> TaskArtifact:
        """Persist immutable required-test evidence without consuming a provider operation."""
        if isinstance(content, bytes):
            encoded = content
        elif isinstance(content, str):
            encoded = sanitize_text(content, self.secret_values).encode("utf-8")
        else:
            encoded = _json(sanitize_payload(content, self.secret_values)).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        with self._transaction() as conn:
            task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task_row is None:
                raise NotFoundFailure(f"task not found: {task_id}")
            self._require_no_unresolved_verification_unlocked(conn, task_row["workflow_id"])
            cycle_row = conn.execute(
                "SELECT * FROM task_cycles WHERE id = ? AND task_id = ?", (cycle_id, task_id)
            ).fetchone()
            if cycle_row is None:
                raise NotFoundFailure(f"task cycle not found: {cycle_id}")
            existing = conn.execute(
                """SELECT * FROM task_artifacts
                   WHERE task_id = ? AND cycle_id = ? AND artifact_type = ?""",
                (task_id, cycle_id, TaskArtifactType.TEST_RESULT.value),
            ).fetchone()
            if existing is not None:
                if existing["sha256"] != digest:
                    raise ConflictFailure("required-test evidence is already immutable")
                if cycle_row["required_test_artifact_id"] != existing["id"]:
                    raise PersistenceFailure("task cycle test-evidence link is invalid")
                return self._task_artifact_from_row(existing)
            artifact = self._write_task_artifact_unlocked(
                conn, workflow_id=task_row["workflow_id"], task_id=task_id,
                ordinal=task_row["ordinal"], key=task_row["key"],
                artifact_type=TaskArtifactType.TEST_RESULT, content=encoded,
                cycle_id=cycle_id, review_window=cycle_row["review_window"],
                cycle=cycle_row["cycle"],
            )
            if (cycle_row["required_test_artifact_id"] is not None
                    and cycle_row["required_test_artifact_id"] != artifact.id):
                raise ConflictFailure("task cycle already has different required-test evidence")
            now = _now()
            conn.execute(
                "UPDATE task_cycles SET required_test_artifact_id = ?, updated_at = ? WHERE id = ?",
                (artifact.id, now, cycle_id),
            )
            self._event_unlocked(
                conn, task_row["workflow_id"], "test.completed", stage=Stage.TASK_EXECUTION,
                artifact_id=artifact.id,
                payload={"task_id": task_id, "cycle_id": cycle_id,
                         "artifact_type": artifact.artifact_type.value, "sha256": artifact.sha256},
            )
            return artifact

    record_required_test_evidence = record_task_test_evidence

    def accept_task(self, task_id: str, *, cycle_id: str | None = None, outcome: str = "PASS") -> TaskDefinition:
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise NotFoundFailure(f"task not found: {task_id}")
            self._require_no_unresolved_verification_unlocked(conn, row["workflow_id"])
            if row["status"] == TaskStatus.ACCEPTED.value:
                return self._task_from_row(row)
            if cycle_id is not None and conn.execute("SELECT 1 FROM task_cycles WHERE id = ? AND task_id = ?", (cycle_id, task_id)).fetchone() is None:
                raise ValidationFailure("task cycle does not belong to task")
            now = _now()
            conn.execute("UPDATE tasks SET status = ?, accepted_at = ? WHERE id = ?",
                         (TaskStatus.ACCEPTED.value, now, task_id))
            if cycle_id:
                conn.execute("UPDATE task_cycles SET outcome = ?, updated_at = ? WHERE id = ?", (outcome, now, cycle_id))
            self._event_unlocked(conn, row["workflow_id"], "task.accepted", stage=Stage.TASK_EXECUTION,
                                 payload={"task_id": task_id, "cycle_id": cycle_id, "outcome": outcome})
            return self._task_from_row(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def complete_task_cycle(
        self,
        task_id: str,
        cycle_id: str,
        *,
        outcome: str,
        review_artifact_id: str | None = None,
        accept: bool = False,
    ) -> tuple[TaskDefinition, TaskDefinition | None]:
        """Record cycle outcome and, when requested, atomically accept/select."""
        if not outcome or not outcome.strip():
            raise ValidationFailure("task cycle outcome is required")
        with self._transaction() as conn:
            task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task_row is None:
                raise NotFoundFailure(f"task not found: {task_id}")
            self._require_no_unresolved_verification_unlocked(conn, task_row["workflow_id"])
            cycle_row = conn.execute(
                "SELECT * FROM task_cycles WHERE id = ? AND task_id = ?", (cycle_id, task_id)
            ).fetchone()
            if cycle_row is None:
                raise NotFoundFailure(f"task cycle not found: {cycle_id}")
            if review_artifact_id is not None and conn.execute(
                "SELECT 1 FROM task_artifacts WHERE id = ? AND task_id = ?",
                (review_artifact_id, task_id),
            ).fetchone() is None:
                raise ValidationFailure("review artifact does not belong to task")
            now = _now()
            conn.execute(
                "UPDATE task_cycles SET outcome = ?, review_artifact_id = COALESCE(?, review_artifact_id), updated_at = ? WHERE id = ?",
                (outcome, review_artifact_id, now, cycle_id),
            )
            if accept:
                conn.execute("UPDATE tasks SET status = ?, accepted_at = ? WHERE id = ?",
                             (TaskStatus.ACCEPTED.value, now, task_id))
                self._event_unlocked(conn, task_row["workflow_id"], "task.accepted", stage=Stage.TASK_EXECUTION,
                                     payload={"task_id": task_id, "cycle_id": cycle_id, "outcome": outcome})
                remaining = conn.execute(
                    "SELECT * FROM tasks WHERE workflow_id = ? AND status != ? ORDER BY ordinal LIMIT 1",
                    (task_row["workflow_id"], TaskStatus.ACCEPTED.value),
                ).fetchone()
                if remaining is None:
                    conn.execute(
                        "UPDATE workflows SET stage = ?, status = ?, updated_at = ? WHERE id = ?",
                        (Stage.TASKS_READY_FOR_WAVE_REVIEW.value, WorkflowStatus.COMPLETED.value, now,
                         task_row["workflow_id"]),
                    )
                    self._event_unlocked(conn, task_row["workflow_id"], "tasks.ready_for_wave_review",
                                         stage=Stage.TASKS_READY_FOR_WAVE_REVIEW,
                                         payload={"task_id": task_id})
            task = self._task_from_row(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
            next_task = self._task_from_row(remaining) if accept and remaining is not None else None
            return task, next_task

    def record_intervention(self, workflow_id: str, task_id: str, *, actor: str, reason: str) -> Intervention:
        if not actor or not reason or not reason.strip():
            raise ValidationFailure("intervention actor and reason are required")
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ? AND workflow_id = ?", (task_id, workflow_id)).fetchone()
            if row is None:
                raise NotFoundFailure(f"task not found: {task_id}")
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            workflow = conn.execute("SELECT stage, status FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
            if workflow is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            if (workflow["stage"] != Stage.TASK_EXECUTION.value
                    or workflow["status"] != WorkflowStatus.HUMAN_ATTENTION.value
                    or row["status"] != TaskStatus.HUMAN_ATTENTION.value):
                raise ConflictFailure("intervention requires a task-level human-attention boundary")
            boundary_events = conn.execute(
                """SELECT payload FROM events
                   WHERE workflow_id = ? AND type IN
                   ('task.human_attention', 'task.operation.failed', 'review.limit_reached')""",
                (workflow_id,),
            ).fetchall()
            has_boundary_event = any(
                self._row_json(event["payload"]).get("task_id") == task_id
                for event in boundary_events
            )
            has_unknown_operation = conn.execute(
                """SELECT 1 FROM operations
                   WHERE workflow_id = ? AND task_id = ? AND status = ? LIMIT 1""",
                (workflow_id, task_id, OperationStatus.UNKNOWN.value),
            ).fetchone() is not None
            if not has_boundary_event and not has_unknown_operation:
                raise ConflictFailure("intervention requires actionable human-attention evidence for the task")
            now = _now()
            safe_actor = sanitize_text(actor, self.secret_values)
            safe_reason = sanitize_text(reason, self.secret_values)
            intervention = Intervention(str(uuid.uuid4()), workflow_id, task_id, safe_actor, safe_reason,
                                        row["current_review_window"], row["current_cycle"], now)
            conn.execute(
                """INSERT INTO interventions
                (id, workflow_id, task_id, actor, reason, prior_review_window, prior_cycle, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (intervention.id, workflow_id, task_id, safe_actor, safe_reason, intervention.prior_review_window,
                 intervention.prior_cycle, now),
            )
            conn.execute(
                "UPDATE tasks SET status = ?, current_review_window = ?, current_cycle = 0 WHERE id = ?",
                (TaskStatus.PENDING.value, row["current_review_window"] + 1, task_id),
            )
            conn.execute("UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                         (WorkflowStatus.RUNNING.value, now, workflow_id))
            self._event_unlocked(conn, workflow_id, "task.intervention.recorded", stage=Stage.TASK_EXECUTION,
                                 payload={"task_id": task_id, "actor": safe_actor, "reason": safe_reason,
                                          "prior_review_window": intervention.prior_review_window,
                                          "prior_cycle": intervention.prior_cycle})
            return intervention

    intervene = record_intervention

    def pause_task(
        self,
        task_id: str,
        *,
        classification: FailureClassification | str,
        detail: str,
        event_type: str = "task.human_attention",
    ) -> TaskDefinition:
        """Durably stop one task without making a lifecycle decision for it.

        The orchestrator owns *when* a task must pause; the store only records
        the requested task/workflow state and an auditable, sanitized reason.
        """
        classification = self._require_enum(classification, FailureClassification)
        if not detail or not detail.strip():
            raise ValidationFailure("task pause detail is required")
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise NotFoundFailure(f"task not found: {task_id}")
            self._require_no_unresolved_verification_unlocked(conn, row["workflow_id"])
            now = _now()
            conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (TaskStatus.HUMAN_ATTENTION.value, task_id))
            conn.execute("UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                         (WorkflowStatus.HUMAN_ATTENTION.value, now, row["workflow_id"]))
            self._event_unlocked(
                conn, row["workflow_id"], event_type, stage=Stage.TASK_EXECUTION,
                payload={"task_id": task_id, "classification": classification.value,
                         "detail": sanitize_text(detail, self.secret_values)},
            )
            updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(updated)

    def fail_task_operation(
        self,
        operation_key: str,
        classification: FailureClassification | str,
        detail: str,
    ) -> Operation:
        """Record a known terminal task-operation failure and pause safely."""
        classification = self._require_enum(classification, FailureClassification)
        if not detail or not detail.strip():
            raise ValidationFailure("task failure detail is required")
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM operations WHERE idempotency_key = ?", (operation_key,)).fetchone()
            if row is None:
                raise NotFoundFailure(f"operation not found: {operation_key}")
            operation = self._operation_from_row(row)
            self._require_no_unresolved_verification_unlocked(conn, operation.workflow_id)
            if operation.task_id is None:
                raise ValidationFailure("operation is not task-correlated")
            now = _now()
            safe_detail = sanitize_text(detail, self.secret_values)
            if operation.status is OperationStatus.PENDING:
                conn.execute(
                    """UPDATE executions SET lifecycle = ?, failure_classification = ?, failure_detail = ?,
                       updated_at = ? WHERE id = ?""",
                    (ExecutionLifecycle.FAILED.value, classification.value, safe_detail, now,
                     operation.related_record_id),
                )
                conn.execute("UPDATE operations SET status = ?, updated_at = ? WHERE id = ?",
                             (OperationStatus.COMPLETED.value, now, operation.id))
            conn.execute("UPDATE tasks SET status = ? WHERE id = ?",
                         (TaskStatus.HUMAN_ATTENTION.value, operation.task_id))
            conn.execute("UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                         (WorkflowStatus.HUMAN_ATTENTION.value, now, operation.workflow_id))
            self._event_unlocked(
                conn, operation.workflow_id, "task.operation.failed", stage=Stage.TASK_EXECUTION,
                execution_id=operation.related_record_id,
                payload={"task_id": operation.task_id, "cycle_id": operation.cycle_id,
                         "classification": classification.value, "detail": safe_detail},
            )
        return self.get_operation(operation.id)

    def list_interventions(self, task_id: str) -> list[Intervention]:
        rows = self._connection.execute(
            "SELECT * FROM interventions WHERE task_id = ? ORDER BY created_at", (task_id,)
        ).fetchall()
        return [self._intervention_from_row(row) for row in rows]

    def mark_task_operation_unknown(self, operation_key: str, *, detail: str | None = None) -> Operation:
        operation = self.mark_operation_unknown(operation_key, detail=detail)
        with self._transaction() as conn:
            row = conn.execute("SELECT task_id, workflow_id FROM operations WHERE id = ?", (operation.id,)).fetchone()
            if row and row["task_id"]:
                self._require_no_unresolved_verification_unlocked(conn, row["workflow_id"])
                now = _now()
                conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (TaskStatus.HUMAN_ATTENTION.value, row["task_id"]))
                conn.execute("UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                             (WorkflowStatus.HUMAN_ATTENTION.value, now, row["workflow_id"]))
        return self.get_operation(operation.id)

    def reconcile_task_operations(self, workflow_id: str | None = None) -> list[Operation]:
        query = "SELECT idempotency_key FROM operations WHERE status = ? AND task_id IS NOT NULL"
        params: list[Any] = [OperationStatus.PENDING.value]
        if workflow_id:
            query += " AND workflow_id = ?"
            params.append(workflow_id)
        keys = [row["idempotency_key"] for row in self._connection.execute(query, params).fetchall()]
        return [self.mark_task_operation_unknown(key, detail="operation was pending during recovery") for key in keys]


    def fail_generation(
        self,
        operation_key: str,
        classification: FailureClassification | str,
        detail: str,
        *,
        workflow_status: WorkflowStatus | str = WorkflowStatus.FAILED,
    ) -> Operation:
        classification = self._require_enum(classification, FailureClassification)
        workflow_status = self._require_enum(workflow_status, WorkflowStatus)
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM operations WHERE idempotency_key = ?", (operation_key,)).fetchone()
            if row is None:
                raise NotFoundFailure(f"operation not found: {operation_key}")
            operation = self._operation_from_row(row)
            self._require_no_unresolved_verification_unlocked(conn, operation.workflow_id)
            if operation.status is not OperationStatus.PENDING:
                return operation
            now = _now()
            execution_id = operation.related_record_id
            conn.execute("UPDATE executions SET lifecycle = ?, failure_classification = ?, failure_detail = ?, updated_at = ? WHERE id = ?",
                         (ExecutionLifecycle.FAILED.value, classification.value, sanitize_text(detail, self.secret_values), now, execution_id))
            conn.execute("UPDATE operations SET status = ?, updated_at = ? WHERE id = ?",
                         (OperationStatus.COMPLETED.value, now, operation.id))
            conn.execute("UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                         (workflow_status.value, now, operation.workflow_id))
            self._event_unlocked(conn, operation.workflow_id, "agent.execution.failed",
                                 execution_id=execution_id,
                                 payload={"classification": classification.value, "detail": detail})
        return self.get_operation(operation.id)

    def mark_operation_unknown(self, operation_key: str, *, detail: str | None = None) -> Operation:
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM operations WHERE idempotency_key = ?", (operation_key,)).fetchone()
            if row is None:
                raise NotFoundFailure(f"operation not found: {operation_key}")
            operation = self._operation_from_row(row)
            self._require_no_unresolved_verification_unlocked(conn, operation.workflow_id)
            if operation.status is not OperationStatus.PENDING:
                return operation
            now = _now()
            conn.execute("UPDATE operations SET status = ?, updated_at = ? WHERE id = ?",
                         (OperationStatus.UNKNOWN.value, now, operation.id))
            conn.execute("UPDATE executions SET lifecycle = ?, failure_detail = ?, updated_at = ? WHERE id = ?",
                         (ExecutionLifecycle.UNKNOWN.value, sanitize_text(detail or "", self.secret_values), now, operation.related_record_id))
            self._event_unlocked(conn, operation.workflow_id, "agent.execution.unknown",
                                 execution_id=operation.related_record_id, payload={"detail": detail or ""})
        return self.get_operation(operation.id)

    def reconcile_operations(self, workflow_id: str | None = None) -> list[Operation]:
        query = "SELECT * FROM operations WHERE status = ?"
        params: list[Any] = [OperationStatus.PENDING.value]
        if workflow_id:
            query += " AND workflow_id = ?"
            params.append(workflow_id)
        rows = self._connection.execute(query, params).fetchall()
        return [self._operation_from_row(row) for row in rows]

    def record_approval(
        self,
        workflow_id: str,
        artifact_id: str,
        decision: ApprovalDecision | str,
        *,
        actor: str,
        reason: str | None = None,
        workflow_stage: Stage | str | None = None,
        workflow_status: WorkflowStatus | str | None = None,
        transition_event_type: str | None = None,
        transition_payload: Mapping[str, Any] | None = None,
    ) -> Approval:
        decision = self._require_enum(decision, ApprovalDecision)
        if not actor:
            raise ValidationFailure("approval actor is required")
        if workflow_stage is not None:
            workflow_stage = self._require_enum(workflow_stage, Stage)
        if workflow_status is not None:
            workflow_status = self._require_enum(workflow_status, WorkflowStatus)
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            artifact_row = conn.execute("SELECT * FROM artifacts WHERE id = ? AND workflow_id = ?",
                                        (artifact_id, workflow_id)).fetchone()
            if artifact_row is None:
                raise NotFoundFailure(f"artifact not found: {artifact_id}")
            existing = conn.execute("SELECT * FROM approvals WHERE artifact_id = ?", (artifact_id,)).fetchone()
            if existing is not None:
                if existing["decision"] != decision.value:
                    raise ConflictFailure("artifact approval has already been decided")
                if workflow_status is not None:
                    self._apply_workflow_transition_unlocked(
                        conn,
                        workflow_id,
                        artifact_id=artifact_id,
                        stage=workflow_stage,
                        status=workflow_status,
                        event_type=transition_event_type,
                        payload=transition_payload,
                    )
                return self._approval_from_row(existing)
            now = _now()
            approval = Approval(str(uuid.uuid4()), workflow_id, artifact_id, decision, actor,
                                sanitize_text(reason, self.secret_values) if reason else None, now)
            conn.execute(
                """INSERT INTO approvals (id, workflow_id, artifact_id, decision, actor, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (approval.id, workflow_id, artifact_id, decision.value, sanitize_text(actor, self.secret_values),
                 approval.reason, now),
            )
            state = ApprovalState.AUTO_APPROVED if decision is ApprovalDecision.AUTO_APPROVED else ApprovalState(decision.value)
            conn.execute("UPDATE artifacts SET approval_state = ? WHERE id = ?", (state.value, artifact_id))
            operation_key = f"artifact:{artifact_id}:approve"
            operation_row = conn.execute("SELECT * FROM operations WHERE idempotency_key = ?", (operation_key,)).fetchone()
            if operation_row is None:
                conn.execute(
                    """INSERT INTO operations
                    (id, idempotency_key, kind, workflow_id, status, related_record_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), operation_key, "approve", workflow_id, OperationStatus.COMPLETED.value,
                     approval.id, now, now),
                )
            self._event_unlocked(conn, workflow_id, "approval.recorded", stage=Stage(artifact_row["stage"]),
                                 artifact_id=artifact_id, payload={"decision": decision.value, "actor": actor})
            if workflow_status is not None:
                self._apply_workflow_transition_unlocked(
                    conn,
                    workflow_id,
                    artifact_id=artifact_id,
                    stage=workflow_stage,
                    status=workflow_status,
                    event_type=transition_event_type,
                    payload=transition_payload,
                )
        return self.get_approval(approval.id)

    def _apply_workflow_transition_unlocked(
        self,
        conn: sqlite3.Connection,
        workflow_id: str,
        *,
        artifact_id: str,
        stage: Stage | None,
        status: WorkflowStatus,
        event_type: str | None,
        payload: Mapping[str, Any] | None,
    ) -> None:
        row = conn.execute(
            "SELECT stage, status FROM workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
        if row is None:
            raise NotFoundFailure(f"workflow not found: {workflow_id}")
        target_stage = stage.value if stage else row["stage"]
        if row["stage"] == target_stage and row["status"] == status.value:
            return
        now = _now()
        conn.execute(
            "UPDATE workflows SET stage = ?, status = ?, updated_at = ? WHERE id = ?",
            (target_stage, status.value, now, workflow_id),
        )
        if event_type:
            self._event_unlocked(
                conn,
                workflow_id,
                event_type,
                stage=Stage(target_stage),
                artifact_id=artifact_id,
                payload=payload,
            )

    def _artifact_destination(self, artifact_path: str | os.PathLike[str]) -> Path:
        return self._workspace_file(artifact_path, label="artifact")

    def plan_markdown_path(self, workflow_id: str, revision: int = 1) -> Path:
        """Return the fixed, confined derived Plan projection path.

        This is deliberately not an artifact path: callers must not use it in
        generation transactions or artifact identity checks.
        """

        destination = self._workspace_file(
            self.workspace_path / "workflows" / workflow_id / "artifacts" / ("002-plan.md" if revision == 1 else f"002-plan-r{revision:03d}.md"),
            label="Plan projection",
        )
        expected_parent = (self.workspace_path / "workflows" / workflow_id / "artifacts").resolve()
        try:
            destination.relative_to(expected_parent)
        except ValueError as exc:
            raise ValidationFailure("Plan projection destination must be inside its workflow artifacts directory") from exc
        return destination

    def read_plan_markdown(self, workflow_id: str, revision: int = 1) -> bytes | None:
        """Read the derived view only; missing is an expected cache state."""

        path = self.plan_markdown_path(workflow_id, revision)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise PersistenceFailure(f"could not read Plan projection: {exc}") from exc

    def write_plan_markdown(self, workflow_id: str, content: str, revision: int = 1) -> Path:
        """Atomically replace a derived Plan projection without touching SQLite."""

        destination = self.plan_markdown_path(workflow_id, revision)
        encoded = content.encode("utf-8")
        temporary_name: str | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".002-plan.", suffix=".tmp", dir=destination.parent
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
            try:
                directory_descriptor = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
            except OSError:
                # The replacement is already complete. Directory fsync support
                # varies by filesystem and must not turn this cache write into
                # a canonical workflow failure.
                pass
            return destination
        except OSError as exc:
            raise PersistenceFailure(f"could not write Plan projection: {exc}") from exc
        finally:
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass

    def _workspace_file(self, file_path: str | os.PathLike[str], *, label: str) -> Path:
        destination = Path(file_path).expanduser().resolve()
        try:
            destination.relative_to(self.workspace_path)
        except ValueError as exc:
            raise ValidationFailure(f"{label} destination must be inside the application workspace") from exc
        if destination == self.database_path:
            raise ValidationFailure(f"database file cannot be a {label} destination")
        return destination

    def _generation_artifact_path(
        self,
        workflow_id: str,
        stage: Stage,
        revision: int,
        artifact_path: str | os.PathLike[str] | None = None,
    ) -> Path:
        if artifact_path is None:
            labels = {
                Stage.INTAKE: "feature-contract",
                Stage.PLAN: "plan",
                Stage.PRD: "prd",
                Stage.TECHSPEC: "techspec",
                Stage.TASK_PLAN: "task-plan",
            }
            artifact_path = (
                self.workspace_path
                / "workflows"
                / workflow_id
                / "artifacts"
                / f"{revision:03d}-{labels[stage]}.md"
            )
        return self._artifact_destination(artifact_path)

    def _generation_binding(
        self,
        operation_row: sqlite3.Row,
        *,
        workflow_id: str,
    ) -> tuple[Stage, int, Path]:
        stage_value = operation_row["intent_stage"]
        revision = operation_row["intent_revision"]
        path_value = operation_row["intent_artifact_path"]
        if stage_value is None or revision is None or path_value is None:
            key = operation_row["idempotency_key"]
            try:
                stage_value = key.split(":stage:", 1)[1].split(":revision:", 1)[0]
                revision = int(key.split(":revision:", 1)[1].split(":generate", 1)[0])
            except (IndexError, ValueError) as exc:
                raise PersistenceFailure("generation operation has no intent binding") from exc
            artifact_row = self._connection.execute(
                "SELECT path, stage, revision FROM artifacts WHERE id = ?",
                (operation_row["related_record_id"],),
            ).fetchone()
            if artifact_row is not None:
                path_value = artifact_row["path"]
            else:
                path_value = str(self._generation_artifact_path(
                    workflow_id, Stage(stage_value), int(revision)
                ))
        try:
            stage = Stage(stage_value)
        except ValueError as exc:
            raise PersistenceFailure("generation operation has an invalid intent stage") from exc
        if stage is Stage.READY_FOR_WAVE_2 or int(revision) < 1:
            raise PersistenceFailure("generation operation has an invalid intent revision")
        return stage, int(revision), self._artifact_destination(path_value)

    def get_artifact(self, artifact_id: str) -> Artifact:
        row = self._connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"artifact not found: {artifact_id}")
        return self._artifact_from_row(row)

    def append_event(
        self,
        workflow_id: str,
        event_type: str,
        *,
        stage: Stage | str | None = None,
        artifact_id: str | None = None,
        execution_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> WorkflowEvent:
        """Append one sanitized event while allocating its workflow sequence."""
        if not event_type:
            raise ValidationFailure("event type is required")
        stage = self._require_enum(stage, Stage) if stage is not None else None
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM workflows WHERE id = ?", (workflow_id,)).fetchone() is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            return self._event_unlocked(conn, workflow_id, event_type, stage=stage,
                                        artifact_id=artifact_id, execution_id=execution_id,
                                        payload=payload)

    @staticmethod
    def _require_sha256(value: str, field: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValidationFailure(f"{field} must be a lowercase SHA-256 hex digest")
        return value

    def create_scope(self, workflow_id: str, kind: ScopeKind | str, external_key: str,
                     *, parent_scope_id: str | None = None) -> WorkflowScope:
        kind = self._require_enum(kind, ScopeKind)
        if not external_key:
            raise ValidationFailure("scope external_key is required")
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM workflows WHERE id = ?", (workflow_id,)).fetchone() is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            if parent_scope_id is not None:
                parent = conn.execute("SELECT workflow_id FROM workflow_scopes WHERE id = ?", (parent_scope_id,)).fetchone()
                if parent is None or parent["workflow_id"] != workflow_id:
                    raise ValidationFailure("scope parent must belong to the workflow")
            row = conn.execute("SELECT * FROM workflow_scopes WHERE workflow_id = ? AND kind = ? AND external_key = ?", (workflow_id, kind.value, external_key)).fetchone()
            if row is None:
                scope_id, now = str(uuid.uuid4()), _now()
                conn.execute("INSERT INTO workflow_scopes (id, workflow_id, kind, external_key, parent_scope_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (scope_id, workflow_id, kind.value, external_key, parent_scope_id, now))
                row = conn.execute("SELECT * FROM workflow_scopes WHERE id = ?", (scope_id,)).fetchone()
            elif row["parent_scope_id"] != parent_scope_id:
                raise ConflictFailure("scope key is already recorded with a different parent")
        return self._scope_from_row(row)

    def record_lifecycle_state(self, workflow_id: str, *, lifecycle_version: LifecycleVersion | str,
                               stage: CanonicalStage | str | None, status: WorkflowStatus | str,
                               operation_key: str, request_fingerprint: str, scope_id: str | None = None) -> LifecycleState:
        lifecycle_version = self._require_enum(lifecycle_version, LifecycleVersion)
        stage = self._require_enum(stage, CanonicalStage) if stage is not None else None
        status = self._require_enum(status, WorkflowStatus)
        self._require_sha256(request_fingerprint, "request_fingerprint")
        if not operation_key:
            raise ValidationFailure("operation_key is required")
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            existing = conn.execute("SELECT * FROM capability_operations WHERE operation_key = ?", (operation_key,)).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise ConflictFailure("operation key was reused with different input")
                row = conn.execute("SELECT * FROM lifecycle_states WHERE workflow_id = ?", (workflow_id,)).fetchone()
                if row is None:
                    raise PersistenceFailure("replayed lifecycle operation has no state")
                return self._lifecycle_state_from_row(row)
            if scope_id and conn.execute("SELECT 1 FROM workflow_scopes WHERE id = ? AND workflow_id = ?", (scope_id, workflow_id)).fetchone() is None:
                raise ValidationFailure("lifecycle scope must belong to the workflow")
            now = _now()
            conn.execute("INSERT INTO capability_operations (id, workflow_id, scope_id, operation_key, request_fingerprint, status, result, attention_outcome, evidence_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)", (str(uuid.uuid4()), workflow_id, scope_id, operation_key, request_fingerprint, OperationStatus.COMPLETED.value, _json({"lifecycle_version": lifecycle_version.value, "stage": stage.value if stage else None, "status": status.value}), now, now))
            conn.execute("INSERT INTO lifecycle_states (workflow_id, lifecycle_version, stage, status, scope_id, operation_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(workflow_id) DO UPDATE SET lifecycle_version=excluded.lifecycle_version, stage=excluded.stage, status=excluded.status, scope_id=excluded.scope_id, operation_key=excluded.operation_key, updated_at=excluded.updated_at", (workflow_id, lifecycle_version.value, stage.value if stage else None, status.value, scope_id, operation_key, now, now))
            self._event_unlocked(conn, workflow_id, "lifecycle.state.recorded", payload={"operation_key": operation_key, "lifecycle_version": lifecycle_version.value, "stage": stage.value if stage else None, "status": status.value})
            row = conn.execute("SELECT * FROM lifecycle_states WHERE workflow_id = ?", (workflow_id,)).fetchone()
        return self._lifecycle_state_from_row(row)

    def record_capability_result(self, workflow_id: str, *, operation_key: str, request_fingerprint: str,
                                 result: Mapping[str, Any] | None, scope_id: str | None = None,
                                 evidence_reference: str | None = None, evidence_sha256: str | None = None,
                                 attention_outcome: HumanAttentionOutcome | str | None = None) -> CapabilityOperation:
        self._require_sha256(request_fingerprint, "request_fingerprint")
        if not operation_key:
            raise ValidationFailure("operation_key is required")
        attention_outcome = self._require_enum(attention_outcome, HumanAttentionOutcome) if attention_outcome else None
        if (evidence_reference is None) != (evidence_sha256 is None):
            raise ValidationFailure("evidence reference and SHA-256 must be supplied together")
        if evidence_sha256:
            self._require_sha256(evidence_sha256, "evidence_sha256")
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            existing = conn.execute("SELECT * FROM capability_operations WHERE operation_key = ?", (operation_key,)).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise ConflictFailure("operation key was reused with different input")
                return self._capability_operation_from_row(existing)
            if scope_id and conn.execute("SELECT 1 FROM workflow_scopes WHERE id = ? AND workflow_id = ?", (scope_id, workflow_id)).fetchone() is None:
                raise ValidationFailure("capability scope must belong to the workflow")
            now, evidence_id = _now(), None
            if evidence_reference is not None:
                evidence_id = str(uuid.uuid4())
                conn.execute("INSERT INTO evidence_references (id, workflow_id, scope_id, reference, sha256, operation_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (evidence_id, workflow_id, scope_id, evidence_reference, evidence_sha256, f"evidence:{operation_key}", now))
            state = OperationStatus.UNKNOWN if attention_outcome else OperationStatus.COMPLETED
            operation_id = str(uuid.uuid4())
            conn.execute("INSERT INTO capability_operations (id, workflow_id, scope_id, operation_key, request_fingerprint, status, result, attention_outcome, evidence_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (operation_id, workflow_id, scope_id, operation_key, request_fingerprint, state.value, _json(sanitize_payload(result or {}, self.secret_values)), attention_outcome.value if attention_outcome else None, evidence_id, now, now))
            self._event_unlocked(conn, workflow_id, "capability.result.recorded", payload={"operation_key": operation_key, "status": state.value, "evidence_id": evidence_id, "attention_outcome": attention_outcome.value if attention_outcome else None})
            row = conn.execute("SELECT * FROM capability_operations WHERE id = ?", (operation_id,)).fetchone()
        return self._capability_operation_from_row(row)

    def record_canonical_transition(
        self, workflow_id: str, *, operation_key: str, request_fingerprint: str,
        scope_id: str, lifecycle_version: LifecycleVersion | str,
        stage: CanonicalStage | str | None, status: WorkflowStatus | str,
        result: Mapping[str, Any] | None, evidence_reference: str | None = None,
        evidence_sha256: str | None = None,
        attention_outcome: HumanAttentionOutcome | str | None = None,
        expected_predecessor: CanonicalStage | str | None = None,
        required_authority: GovernanceDecisionType | str | None = None,
        required_approval_target_stage: CanonicalStage | str | None = None,
    ) -> LifecycleState:
        """Atomically retain a normalized result, lifecycle state, and audit event.

        This is intentionally the only store primitive which couples a
        canonical capability result to an advancement.  Callers must decide
        policy before invoking it; provider output cannot select ``stage``.
        """
        lifecycle_version = self._require_enum(lifecycle_version, LifecycleVersion)
        stage = self._require_enum(stage, CanonicalStage) if stage is not None else None
        status = self._require_enum(status, WorkflowStatus)
        attention_outcome = self._require_enum(attention_outcome, HumanAttentionOutcome) if attention_outcome else None
        expected_predecessor = self._require_enum(expected_predecessor, CanonicalStage) if expected_predecessor else None
        required_authority = self._require_enum(required_authority, GovernanceDecisionType) if required_authority else None
        required_approval_target_stage = self._require_enum(required_approval_target_stage, CanonicalStage) if required_approval_target_stage else None
        self._require_sha256(request_fingerprint, "request_fingerprint")
        if not operation_key:
            raise ValidationFailure("operation_key is required")
        if (evidence_reference is None) != (evidence_sha256 is None):
            raise ValidationFailure("evidence reference and SHA-256 must be supplied together")
        if evidence_sha256:
            self._require_sha256(evidence_sha256, "evidence_sha256")
        if attention_outcome is None and (not isinstance(result, Mapping) or not result):
            raise ValidationFailure("a successful canonical transition requires a structured result")
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            existing = conn.execute("SELECT * FROM capability_operations WHERE operation_key = ?", (operation_key,)).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise ConflictFailure("operation key was reused with different input")
                row = conn.execute("SELECT * FROM lifecycle_states WHERE workflow_id = ?", (workflow_id,)).fetchone()
                if row is None:
                    raise PersistenceFailure("replayed canonical operation has no lifecycle state")
                return self._lifecycle_state_from_row(row)
            if conn.execute("SELECT 1 FROM workflow_scopes WHERE id = ? AND workflow_id = ?", (scope_id, workflow_id)).fetchone() is None:
                raise ValidationFailure("canonical transition scope must belong to the workflow")
            current = conn.execute("SELECT * FROM lifecycle_states WHERE workflow_id = ?", (workflow_id,)).fetchone()
            if expected_predecessor is not None:
                if current is None or current["lifecycle_version"] != lifecycle_version.value or current["stage"] != expected_predecessor.value:
                    raise ConflictFailure("canonical transition predecessor is no longer current")
                legal_successors = {
                    CanonicalStage.PRD: {CanonicalStage.DELIVERY_PLAN},
                    CanonicalStage.DELIVERY_PLAN: {CanonicalStage.ARCHITECTURE, CanonicalStage.TECHSPEC},
                    CanonicalStage.ARCHITECTURE: {CanonicalStage.TECHSPEC},
                    CanonicalStage.TECHSPEC: {CanonicalStage.TASK_PLAN},
                    CanonicalStage.TASK_PLAN: {CanonicalStage.TASK_EXECUTION},
                    CanonicalStage.TASK_EXECUTION: {CanonicalStage.WAVE_REVIEW},
                    CanonicalStage.WAVE_REVIEW: {CanonicalStage.FINAL_REVIEW},
                    CanonicalStage.FINAL_REVIEW: {CanonicalStage.DELIVERY_PREPARATION},
                    CanonicalStage.DELIVERY_PREPARATION: {CanonicalStage.DELIVERY_PREPARATION},
                }
                if stage not in legal_successors[expected_predecessor]:
                    raise ValidationFailure("canonical transition is not a legal successor")
            if required_authority is not None:
                # Evaluate from the same transaction snapshot that writes the
                # operation/state/event, so a stale preflight cannot advance.
                authority_rows = conn.execute("""SELECT d.*, e.eligible FROM governance_decisions d
                    JOIN governance_eligibility e ON e.decision_id = d.id
                    WHERE d.workflow_id = ? AND d.scope_id = ? AND d.lifecycle_version = ? AND d.decision_type = ?
                      AND (? IS NULL OR d.approval_target_stage = ?)
                    ORDER BY d.created_at, d.rowid""", (workflow_id, scope_id, lifecycle_version.value, required_authority.value,
                                                          required_approval_target_stage.value if required_approval_target_stage else None,
                                                          required_approval_target_stage.value if required_approval_target_stage else None)).fetchall()
                eligible = []
                for row in authority_rows:
                    evidence = self._row_json(row["evidence"])
                    evidence_is_valid = bool(evidence) and all(
                        conn.execute("""SELECT 1 FROM evidence_references evidence
                            JOIN capability_operations operation ON operation.evidence_id = evidence.id
                            WHERE evidence.workflow_id = ? AND evidence.scope_id = ?
                              AND evidence.reference = ? AND evidence.sha256 = ?
                              AND operation.status = ? AND operation.attention_outcome IS NULL""",
                            (workflow_id, scope_id, reference, digest, OperationStatus.COMPLETED.value)).fetchone()
                        is not None for reference, digest in evidence
                    )
                    if row["eligible"] and evidence_is_valid and row["decision"] in (GovernanceDecision.APPROVED.value, GovernanceDecision.ACCEPTED.value, GovernanceDecision.AUTHORIZED.value):
                        eligible.append(row)
                if len(eligible) != 1:
                    raise ConflictFailure("required canonical authority is unavailable or ambiguous")
            now, evidence_id = _now(), None
            if evidence_reference:
                evidence_id = str(uuid.uuid4())
                conn.execute("INSERT INTO evidence_references (id, workflow_id, scope_id, reference, sha256, operation_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (evidence_id, workflow_id, scope_id, evidence_reference, evidence_sha256, f"evidence:{operation_key}", now))
            op_status = OperationStatus.UNKNOWN if attention_outcome else OperationStatus.COMPLETED
            conn.execute("INSERT INTO capability_operations (id, workflow_id, scope_id, operation_key, request_fingerprint, status, result, attention_outcome, evidence_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (str(uuid.uuid4()), workflow_id, scope_id, operation_key, request_fingerprint, op_status.value,
                          _json(sanitize_payload(result or {}, self.secret_values)), attention_outcome.value if attention_outcome else None,
                          evidence_id, now, now))
            conn.execute("INSERT INTO lifecycle_states (workflow_id, lifecycle_version, stage, status, scope_id, operation_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(workflow_id) DO UPDATE SET lifecycle_version=excluded.lifecycle_version, stage=excluded.stage, status=excluded.status, scope_id=excluded.scope_id, operation_key=excluded.operation_key, updated_at=excluded.updated_at",
                         (workflow_id, lifecycle_version.value, stage.value if stage else None, status.value, scope_id, operation_key, now, now))
            self._event_unlocked(conn, workflow_id, "canonical.transition.recorded", payload={
                "operation_key": operation_key, "stage": stage.value if stage else None,
                "status": status.value, "attention_outcome": attention_outcome.value if attention_outcome else None,
                "evidence_id": evidence_id,
            })
            row = conn.execute("SELECT * FROM lifecycle_states WHERE workflow_id = ?", (workflow_id,)).fetchone()
        return self._lifecycle_state_from_row(row)

    def record_governance_decision(
        self,
        workflow_id: str,
        *,
        scope_id: str,
        lifecycle_version: LifecycleVersion | str,
        operation_key: str,
        request_fingerprint: str,
        decision_type: GovernanceDecisionType | str,
        decision: GovernanceDecision | str,
        actor: str,
        evidence: Mapping[str, str],
        approval_target_stage: CanonicalStage | str | None = None,
        predecessor_ids: tuple[str, ...] = (),
        affected_ids: tuple[str, ...] = (),
    ) -> GovernanceRecord:
        """Append one auditable governance fact and its atomic invalidation effects."""
        lifecycle_version = self._require_enum(lifecycle_version, LifecycleVersion)
        decision_type = self._require_enum(decision_type, GovernanceDecisionType)
        decision = self._require_enum(decision, GovernanceDecision)
        approval_target_stage = self._require_enum(approval_target_stage, CanonicalStage) if approval_target_stage else None
        if approval_target_stage is not None and decision_type is not GovernanceDecisionType.APPROVAL:
            raise ValidationFailure("only approvals may target a canonical stage")
        self._require_sha256(request_fingerprint, "request_fingerprint")
        if not operation_key or not isinstance(actor, str) or not actor.strip():
            raise ValidationFailure("operation_key and identifiable actor are required")
        if not isinstance(evidence, Mapping) or not evidence:
            raise ValidationFailure("at least one exact evidence reference and hash is required")
        normalized_evidence = tuple(sorted((str(reference), digest) for reference, digest in evidence.items()))
        if any(not reference for reference, _ in normalized_evidence):
            raise ValidationFailure("evidence reference is required")
        for _, digest in normalized_evidence:
            self._require_sha256(digest, "evidence hash")
        predecessors, affected = tuple(predecessor_ids), tuple(affected_ids)
        if len(set(predecessors)) != len(predecessors) or len(set(affected)) != len(affected):
            raise ValidationFailure("governance decision links must not contain duplicates")
        if decision is not _GOVERNANCE_DECISION_BY_TYPE[decision_type]:
            raise ValidationFailure("governance decision must match its decision type")
        if decision_type in {GovernanceDecisionType.REVOCATION, GovernanceDecisionType.SUPERSESSION}:
            if not affected:
                raise ValidationFailure("revocation/supersession requires affected facts")
        contract_data = {"workflow_id": workflow_id, "scope_id": scope_id,
                          "lifecycle_version": lifecycle_version.value, "decision_type": decision_type.value,
                          "decision": decision.value, "actor": actor, "evidence": normalized_evidence,
                          "predecessor_ids": predecessors, "affected_ids": affected}
        if approval_target_stage is not None:
            contract_data["approval_target_stage"] = approval_target_stage.value
        contract = _json(contract_data)
        if hashlib.sha256(contract.encode("utf-8")).hexdigest() != request_fingerprint:
            raise ValidationFailure("request_fingerprint does not match governance decision input")
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            existing = conn.execute("SELECT * FROM governance_decisions WHERE operation_key = ?", (operation_key,)).fetchone()
            if existing is not None:
                if existing["request_fingerprint"] != request_fingerprint:
                    raise ConflictFailure("operation key was reused with different input")
                return self._governance_record_from_row(existing)
            if conn.execute("SELECT 1 FROM workflow_scopes WHERE id = ? AND workflow_id = ?", (scope_id, workflow_id)).fetchone() is None:
                raise ValidationFailure("governance scope must belong to the workflow")
            links = predecessors + affected
            if links:
                marks = ",".join("?" for _ in links)
                linked = conn.execute(
                    f"""SELECT d.id, e.eligible, e.invalidated_by_id
                        FROM governance_decisions d
                        JOIN governance_eligibility e ON e.decision_id = d.id
                        WHERE d.workflow_id = ? AND d.id IN ({marks})""",
                    (workflow_id, *links),
                ).fetchall()
                if {row["id"] for row in linked} != set(links):
                    raise ValidationFailure("governance links must reference existing facts in the workflow")
            else:
                linked = ()
            record_id, now = str(uuid.uuid4()), _now()
            conn.execute("""INSERT INTO governance_decisions
                (id, workflow_id, scope_id, lifecycle_version, operation_key, request_fingerprint,
                 decision_type, decision, actor, evidence, approval_target_stage, predecessor_ids, affected_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record_id, workflow_id, scope_id, lifecycle_version.value, operation_key, request_fingerprint,
                 decision_type.value, decision.value, actor, _json(normalized_evidence), approval_target_stage.value if approval_target_stage else None, _json(predecessors),
                 _json(affected), now))
            stale_predecessor = next(
                (row for row in linked if row["id"] in predecessors and not row["eligible"]), None
            )
            conn.execute(
                """INSERT INTO governance_eligibility
                   (decision_id, eligible, invalidated_by_id, invalidated_at) VALUES (?, ?, ?, ?)""",
                (record_id, 0 if stale_predecessor else 1,
                 stale_predecessor["invalidated_by_id"] if stale_predecessor else None,
                 now if stale_predecessor else None),
            )
            invalidator_evidence_valid = all(
                self._has_valid_governance_evidence(
                    workflow_id, scope_id, reference, digest
                )
                for reference, digest in normalized_evidence
            )
            if affected and invalidator_evidence_valid:
                # Only a valid revocation/supersession can withdraw authority.
                # An invalid one remains an immutable audit fact, but cannot
                # silently invalidate the fact it purports to replace.
                # Affected facts and only records which declare them as predecessors lose eligibility.
                invalidated = set(affected)
                changed = True
                rows = conn.execute("SELECT id, predecessor_ids FROM governance_decisions WHERE workflow_id = ?", (workflow_id,)).fetchall()
                while changed:
                    changed = False
                    for row in rows:
                        if row["id"] not in invalidated and invalidated.intersection(self._row_json(row["predecessor_ids"])):
                            invalidated.add(row["id"])
                            changed = True
                marks = ",".join("?" for _ in invalidated)
                conn.execute(f"UPDATE governance_eligibility SET eligible = 0, invalidated_by_id = ?, invalidated_at = ? WHERE decision_id IN ({marks})", (record_id, now, *invalidated))
            self._event_unlocked(conn, workflow_id, "governance.decision.recorded", payload={
                "decision_id": record_id, "operation_key": operation_key, "decision_type": decision_type.value,
                "decision": decision.value, "scope_id": scope_id, "affected_ids": affected,
            })
            row = conn.execute("SELECT * FROM governance_decisions WHERE id = ?", (record_id,)).fetchone()
        return self._governance_record_from_row(row)

    def evaluate_active_authority(
        self, workflow_id: str, *, scope_id: str, lifecycle_version: LifecycleVersion | str,
        decision_type: GovernanceDecisionType | str, approval_target_stage: CanonicalStage | str | None = None,
    ) -> AuthorityEvaluation:
        """Return active authority only for one exact, unambiguous lineage."""
        lifecycle_version = self._require_enum(lifecycle_version, LifecycleVersion)
        decision_type = self._require_enum(decision_type, GovernanceDecisionType)
        approval_target_stage = self._require_enum(approval_target_stage, CanonicalStage) if approval_target_stage else None
        rows = self._connection.execute("""SELECT d.*, e.eligible FROM governance_decisions d
            JOIN governance_eligibility e ON e.decision_id = d.id
            WHERE d.workflow_id = ? AND d.scope_id = ? AND d.lifecycle_version = ? AND d.decision_type = ?
              AND (? IS NULL OR d.approval_target_stage = ?)
            ORDER BY d.created_at, d.rowid""", (workflow_id, scope_id, lifecycle_version.value, decision_type.value,
                                                  approval_target_stage.value if approval_target_stage else None,
                                                  approval_target_stage.value if approval_target_stage else None)).fetchall()
        candidates: list[GovernanceRecord] = []
        invalid_evidence = False
        invalid_pairing = False
        invalid_lineage = False
        for row in rows:
            record = self._governance_record_from_row(row)
            if record.decision is not _GOVERNANCE_DECISION_BY_TYPE[record.decision_type]:
                invalid_pairing = True
                continue
            valid_evidence = bool(record.evidence) and all(
                self._has_valid_governance_evidence(
                    workflow_id, scope_id, reference, digest
                )
                for reference, digest in record.evidence
            )
            if row["eligible"] and not valid_evidence:
                invalid_evidence = True
            valid_lineage = self._has_eligible_governance_lineage(
                self._connection, workflow_id, record.predecessor_ids
            )
            if row["eligible"] and not valid_lineage:
                invalid_lineage = True
            if row["eligible"] and valid_evidence and record.decision in {
                GovernanceDecision.APPROVED, GovernanceDecision.ACCEPTED, GovernanceDecision.AUTHORIZED
            } and valid_lineage:
                candidates.append(record)
        if invalid_pairing:
            return AuthorityEvaluation(False, True, "invalid authority record", None)
        # An eligible fact with invalid evidence or lineage makes the exact
        # authority set ambiguous.  Do not let an otherwise valid sibling
        # mask it: governance must fail closed until a human resolves it.
        if invalid_evidence:
            return AuthorityEvaluation(False, True, "invalid authority evidence", None)
        if invalid_lineage:
            return AuthorityEvaluation(False, True, "invalid authority lineage", None)
        if len(candidates) == 1:
            return AuthorityEvaluation(True, False, None, candidates[0])
        if len(candidates) > 1:
            return AuthorityEvaluation(False, True, "conflicting active authority", None)
        reason = "no active authority" if rows else "missing authority"
        return AuthorityEvaluation(False, False, reason, None)

    def _has_eligible_governance_lineage(
        self, conn: sqlite3.Connection, workflow_id: str, predecessor_ids: tuple[str, ...],
    ) -> bool:
        """Require every predecessor in an authority chain to remain eligible."""
        pending = list(predecessor_ids)
        visited: set[str] = set()
        while pending:
            decision_id = pending.pop()
            if decision_id in visited:
                continue
            visited.add(decision_id)
            row = conn.execute(
                """SELECT d.predecessor_ids, e.eligible
                   FROM governance_decisions d
                   JOIN governance_eligibility e ON e.decision_id = d.id
                   WHERE d.workflow_id = ? AND d.id = ?""",
                (workflow_id, decision_id),
            ).fetchone()
            if row is None or not row["eligible"]:
                return False
            pending.extend(self._row_json(row["predecessor_ids"]))
        return True

    def _has_valid_governance_evidence(
        self, workflow_id: str, scope_id: str, reference: str, digest: str,
    ) -> bool:
        """Require a completed immutable evidence fact matching the decision exactly."""
        if not reference or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return False
        return self._connection.execute(
            """SELECT 1 FROM evidence_references evidence
               JOIN capability_operations operation ON operation.evidence_id = evidence.id
               WHERE evidence.workflow_id = ?
                 AND evidence.scope_id = ?
                 AND evidence.reference = ? AND evidence.sha256 = ?
                 AND operation.status = ? AND operation.attention_outcome IS NULL""",
            (workflow_id, scope_id, reference, digest, OperationStatus.COMPLETED.value),
        ).fetchone() is not None

    def has_accepted_task_evidence(self, workflow_id: str, scope_id: str, evidence: Mapping[str, Any]) -> bool:
        """Validate immutable Wave 2 reviewer-PASS evidence without plan-cell reads."""
        del scope_id  # Wave 2 task identity is already bound to the workflow.
        if not isinstance(evidence, Mapping):
            return False
        task_id, cycle_id = evidence.get("task_id"), evidence.get("cycle_id")
        reference, digest = evidence.get("review_evidence_reference"), evidence.get("review_evidence_sha256")
        if (evidence.get("status") != TaskStatus.ACCEPTED.value or evidence.get("reviewer_result") != "PASS"
                or not all(isinstance(value, str) and value for value in (task_id, cycle_id, reference, digest))
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            return False
        return self._connection.execute("""SELECT 1 FROM tasks task
            JOIN task_cycles cycle ON cycle.task_id = task.id
            JOIN task_artifacts artifact ON artifact.id = cycle.review_artifact_id
            WHERE task.id = ? AND task.workflow_id = ? AND task.status = ?
              AND cycle.id = ? AND cycle.outcome = ? AND artifact.path = ? AND artifact.sha256 = ?""",
            (task_id, workflow_id, TaskStatus.ACCEPTED.value, cycle_id, "PASS", reference, digest),
        ).fetchone() is not None

    # Clear aliases for callers that use the domain vocabulary rather than storage vocabulary.
    record_decision = record_governance_decision
    active_authority = evaluate_active_authority

    def get_lifecycle_state(self, workflow_id: str) -> LifecycleState | None:
        row = self._connection.execute("SELECT * FROM lifecycle_states WHERE workflow_id = ?", (workflow_id,)).fetchone()
        return self._lifecycle_state_from_row(row) if row is not None else None

    def get_capability_operation(self, operation_key: str) -> CapabilityOperation:
        row = self._connection.execute("SELECT * FROM capability_operations WHERE operation_key = ?", (operation_key,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"capability operation not found: {operation_key}")
        return self._capability_operation_from_row(row)

    def get_governance_decision(self, decision_id: str) -> GovernanceRecord:
        row = self._connection.execute("SELECT * FROM governance_decisions WHERE id = ?", (decision_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"governance decision not found: {decision_id}")
        return self._governance_record_from_row(row)

    def list_governance_decisions(self, workflow_id: str) -> list[GovernanceRecord]:
        rows = self._connection.execute(
            "SELECT * FROM governance_decisions WHERE workflow_id = ? ORDER BY created_at, rowid", (workflow_id,)
        ).fetchall()
        return [self._governance_record_from_row(row) for row in rows]

    def migrate_historical_workflow(self, workflow_id: str, *, operation_key: str,
                                    source_version: LifecycleVersion | str = LifecycleVersion.HISTORICAL,
                                    target_version: LifecycleVersion | str = LifecycleVersion.CANONICAL_V1,
                                    valid: bool = True, detail: str | None = None,
                                    canonical_stage: CanonicalStage | str | None = None,
                                    canonical_status: WorkflowStatus | str = WorkflowStatus.CREATED,
                                    attention_outcome: HumanAttentionOutcome | str | None = None,
                                    request_fingerprint: str | None = None) -> MigrationReceipt:
        source_version, target_version = self._require_enum(source_version, LifecycleVersion), self._require_enum(target_version, LifecycleVersion)
        canonical_stage = self._require_enum(canonical_stage, CanonicalStage) if canonical_stage is not None else None
        canonical_status = self._require_enum(canonical_status, WorkflowStatus)
        if not operation_key:
            raise ValidationFailure("operation_key is required")
        if source_version is not LifecycleVersion.HISTORICAL or target_version is not LifecycleVersion.CANONICAL_V1:
            raise ValidationFailure("historical migration only supports historical to canonical-v1")
        if valid and attention_outcome is not None:
            raise ValidationFailure("successful migration cannot have a human-attention outcome")
        if not valid:
            attention_outcome = self._require_enum(
                attention_outcome or HumanAttentionOutcome.AMBIGUOUS_MIGRATION,
                HumanAttentionOutcome,
            )
            if attention_outcome not in {
                HumanAttentionOutcome.AMBIGUOUS_MIGRATION,
                HumanAttentionOutcome.PARTIAL_MIGRATION,
                HumanAttentionOutcome.MIGRATION_FAILED,
            }:
                raise ValidationFailure("migration pause requires a migration attention outcome")
        contract = {
            "workflow_id": workflow_id,
            "source_version": source_version.value,
            "target_version": target_version.value,
            "valid": valid,
            "canonical_stage": canonical_stage.value if canonical_stage else None,
            "canonical_status": canonical_status.value,
            "attention_outcome": attention_outcome.value if attention_outcome else None,
            "detail": detail,
        }
        expected_fingerprint = hashlib.sha256(_json(contract).encode("utf-8")).hexdigest()
        if request_fingerprint is not None:
            self._require_sha256(request_fingerprint, "request_fingerprint")
            if request_fingerprint != expected_fingerprint:
                raise ValidationFailure("request_fingerprint does not match migration input")
        else:
            request_fingerprint = expected_fingerprint
        with self._transaction() as conn:
            self._require_no_unresolved_verification_unlocked(conn, workflow_id)
            existing = conn.execute("SELECT * FROM migration_receipts WHERE operation_key = ?", (operation_key,)).fetchone()
            if existing is not None:
                if (existing["workflow_id"] != workflow_id
                        or existing["source_version"] != source_version.value
                        or existing["target_version"] != target_version.value
                        or existing["request_fingerprint"] != request_fingerprint):
                    raise ConflictFailure("migration operation key was reused with different input")
                return self._migration_receipt_from_row(existing)
            if conn.execute("SELECT 1 FROM workflows WHERE id = ?", (workflow_id,)).fetchone() is None:
                raise NotFoundFailure(f"workflow not found: {workflow_id}")
            prior_completed = conn.execute(
                "SELECT * FROM migration_receipts WHERE workflow_id = ? AND source_version = ? "
                "AND target_version = ? AND outcome = ?",
                (workflow_id, source_version.value, target_version.value, MigrationOutcome.COMPLETED.value),
            ).fetchone()
            if prior_completed is not None:
                raise ConflictFailure("historical workflow already has a completed migration")
            if valid:
                outcome, lifecycle_version, lifecycle_status = (
                    MigrationOutcome.COMPLETED, target_version, canonical_status
                )
            else:
                outcome = {
                    HumanAttentionOutcome.AMBIGUOUS_MIGRATION: MigrationOutcome.AMBIGUOUS,
                    HumanAttentionOutcome.PARTIAL_MIGRATION: MigrationOutcome.PARTIAL,
                    HumanAttentionOutcome.MIGRATION_FAILED: MigrationOutcome.FAILED,
                }[attention_outcome]
                lifecycle_version, lifecycle_status = source_version, WorkflowStatus.HUMAN_ATTENTION
            receipt_id, now = str(uuid.uuid4()), _now()
            lifecycle_operation_key = f"lifecycle:{operation_key}"
            conn.execute("INSERT INTO capability_operations (id, workflow_id, scope_id, operation_key, request_fingerprint, status, result, attention_outcome, evidence_id, created_at, updated_at) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?)", (str(uuid.uuid4()), workflow_id, lifecycle_operation_key, request_fingerprint, OperationStatus.UNKNOWN.value if attention_outcome else OperationStatus.COMPLETED.value, _json({"migration_receipt_id": receipt_id}), attention_outcome.value if attention_outcome else None, now, now))
            conn.execute("INSERT INTO lifecycle_states (workflow_id, lifecycle_version, stage, status, scope_id, operation_key, created_at, updated_at) VALUES (?, ?, ?, ?, NULL, ?, ?, ?) ON CONFLICT(workflow_id) DO UPDATE SET lifecycle_version=excluded.lifecycle_version, stage=excluded.stage, status=excluded.status, scope_id=NULL, operation_key=excluded.operation_key, updated_at=excluded.updated_at", (workflow_id, lifecycle_version.value, canonical_stage.value if valid and canonical_stage else None, lifecycle_status.value, lifecycle_operation_key, now, now))
            conn.execute("INSERT INTO migration_receipts (id, workflow_id, operation_key, source_version, target_version, outcome, request_fingerprint, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (receipt_id, workflow_id, operation_key, source_version.value, target_version.value, outcome.value, request_fingerprint, detail, now))
            self._event_unlocked(conn, workflow_id, "lifecycle.migration.recorded", payload={"operation_key": operation_key, "outcome": outcome.value, "source_version": source_version.value, "target_version": target_version.value, "attention_outcome": attention_outcome.value if attention_outcome else None})
            row = conn.execute("SELECT * FROM migration_receipts WHERE id = ?", (receipt_id,)).fetchone()
        return self._migration_receipt_from_row(row)

    def read_artifact(self, artifact_id: str) -> str:
        artifact = self.get_artifact(artifact_id)
        try:
            content = Path(artifact.path).read_bytes()
        except OSError as exc:
            raise PersistenceFailure(f"could not read artifact: {exc}") from exc
        digest = hashlib.sha256(content).hexdigest()
        if digest != artifact.sha256:
            raise ArtifactCorruptionFailure(
                f"artifact hash mismatch for {artifact.id}",
                details={"expected": artifact.sha256, "actual": digest},
            )
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactCorruptionFailure(f"artifact is not valid UTF-8: {artifact.id}") from exc

    def get_approval(self, approval_id: str) -> Approval:
        row = self._connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"approval not found: {approval_id}")
        return self._approval_from_row(row)

    def get_approval_for_artifact(self, artifact_id: str) -> Approval | None:
        """Return the single decision bound to an artifact, if one exists."""
        row = self._connection.execute(
            "SELECT * FROM approvals WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        return self._approval_from_row(row) if row is not None else None

    def get_operation(self, operation_id: str) -> Operation:
        row = self._connection.execute("SELECT * FROM operations WHERE id = ?", (operation_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"operation not found: {operation_id}")
        return self._operation_from_row(row)

    def get_operation_by_key(self, idempotency_key: str) -> Operation:
        row = self._connection.execute("SELECT * FROM operations WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"operation not found: {idempotency_key}")
        return self._operation_from_row(row)

    def get_execution(self, execution_id: str) -> Execution:
        row = self._connection.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"execution not found: {execution_id}")
        return self._execution_from_row(row)

    def get_session(self, session_id: str) -> Session:
        row = self._connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"session not found: {session_id}")
        return self._session_from_row(row)

    def get_latest_execution(self, workflow_id: str) -> Execution | None:
        row = self._connection.execute(
            "SELECT * FROM executions WHERE workflow_id = ? ORDER BY created_at DESC LIMIT 1",
            (workflow_id,),
        ).fetchone()
        return self._execution_from_row(row) if row is not None else None

    def list_events(self, workflow_id: str, *, after: int = 0) -> list[WorkflowEvent]:
        rows = self._connection.execute(
            "SELECT * FROM events WHERE workflow_id = ? AND sequence > ? ORDER BY sequence ASC",
            (workflow_id, after),
        ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def list_artifacts(self, workflow_id: str, stage: Stage | str | None = None) -> list[Artifact]:
        if stage is None:
            rows = self._connection.execute(
                "SELECT * FROM artifacts WHERE workflow_id = ? ORDER BY created_at ASC", (workflow_id,)
            ).fetchall()
        else:
            stage = self._require_enum(stage, Stage)
            rows = self._connection.execute(
                "SELECT * FROM artifacts WHERE workflow_id = ? AND stage = ? ORDER BY revision ASC",
                (workflow_id, stage.value),
            ).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def _artifact_from_row(self, row: sqlite3.Row) -> Artifact:
        return Artifact(row["id"], row["workflow_id"], Stage(row["stage"]), row["revision"], row["path"],
                        row["sha256"], row["source_execution_id"], ApprovalState(row["approval_state"]), row["created_at"])

    def _task_implementation_state_from_row(self, row: sqlite3.Row) -> TaskImplementationState:
        return TaskImplementationState(
            row["id"], row["workflow_id"], row["plan_artifact_id"], row["plan_sha256"],
            row["task_contract_id"], row["task_contract_sha256"],
            TaskImplementationStatus(row["status"]), row["selected_at"], row["updated_at"],
        )

    def _scope_from_row(self, row: sqlite3.Row) -> WorkflowScope:
        return WorkflowScope(row["id"], row["workflow_id"], ScopeKind(row["kind"]), row["external_key"], row["parent_scope_id"], row["created_at"])

    def _lifecycle_state_from_row(self, row: sqlite3.Row) -> LifecycleState:
        return LifecycleState(row["workflow_id"], LifecycleVersion(row["lifecycle_version"]), CanonicalStage(row["stage"]) if row["stage"] else None, WorkflowStatus(row["status"]), row["scope_id"], row["operation_key"], row["created_at"], row["updated_at"])

    def _capability_operation_from_row(self, row: sqlite3.Row) -> CapabilityOperation:
        return CapabilityOperation(row["id"], row["workflow_id"], row["scope_id"], row["operation_key"], row["request_fingerprint"], OperationStatus(row["status"]), self._row_json(row["result"]), HumanAttentionOutcome(row["attention_outcome"]) if row["attention_outcome"] else None, row["evidence_id"], row["created_at"], row["updated_at"])

    def _governance_record_from_row(self, row: sqlite3.Row) -> GovernanceRecord:
        return GovernanceRecord(
            row["id"], row["workflow_id"], row["scope_id"], LifecycleVersion(row["lifecycle_version"]),
            row["operation_key"], GovernanceDecisionType(row["decision_type"]),
            GovernanceDecision(row["decision"]), row["actor"],
            tuple(tuple(item) for item in self._row_json(row["evidence"])),
            CanonicalStage(row["approval_target_stage"]) if row["approval_target_stage"] else None,
            tuple(self._row_json(row["predecessor_ids"])), tuple(self._row_json(row["affected_ids"])),
            row["created_at"],
        )

    def _migration_receipt_from_row(self, row: sqlite3.Row) -> MigrationReceipt:
        return MigrationReceipt(row["id"], row["workflow_id"], row["operation_key"], LifecycleVersion(row["source_version"]), LifecycleVersion(row["target_version"]), MigrationOutcome(row["outcome"]), row["detail"], row["created_at"])

    def _session_from_row(self, row: sqlite3.Row) -> Session:
        return Session(
            row["id"], row["workflow_id"], row["logical_session_id"], Role(row["role"]),
            row["provider"], row["provider_session_id"], row["created_at"], row["updated_at"],
            row["task_id"] if "task_id" in row.keys() else None,
            row["cycle_id"] if "cycle_id" in row.keys() else None,
            WorkKind(row["work_kind"]) if "work_kind" in row.keys() and row["work_kind"] else None,
        )

    def _approval_from_row(self, row: sqlite3.Row) -> Approval:
        return Approval(row["id"], row["workflow_id"], row["artifact_id"], ApprovalDecision(row["decision"]),
                        row["actor"], row["reason"], row["created_at"])

    def _clarification_from_row(self, row: sqlite3.Row) -> Clarification:
        return Clarification(row["id"], row["workflow_id"], row["sequence"], row["source_feature_contract_artifact_id"], row["question"], row["answer"], row["actor"], row["result_feature_contract_artifact_id"], row["created_at"], row["answered_at"], row["completed_at"])

    def _plan_change_request_from_row(self, row: sqlite3.Row) -> PlanChangeRequest:
        return PlanChangeRequest(row["id"], row["workflow_id"], row["sequence"], row["target_plan_artifact_id"], row["feedback"], row["actor"], row["replacement_plan_artifact_id"], row["created_at"], row["completed_at"])

    def _operation_from_row(self, row: sqlite3.Row) -> Operation:
        return Operation(row["id"], row["idempotency_key"], row["kind"], row["workflow_id"],
                         OperationStatus(row["status"]), row["related_record_id"], row["created_at"], row["updated_at"],
                         row["task_id"] if "task_id" in row.keys() else None,
                         row["cycle_id"] if "cycle_id" in row.keys() else None,
                         WorkKind(row["work_kind"]) if "work_kind" in row.keys() and row["work_kind"] else None)

    def _execution_from_row(self, row: sqlite3.Row) -> Execution:
        return Execution(row["id"], row["workflow_id"], row["session_id"], Role(row["role"]),
                         row["provider_execution_id"], row["request_hash"], ExecutionLifecycle(row["lifecycle"]),
                         self._row_json(row["capability_report"]), self._row_json(row["terminal_result"]),
                         FailureClassification(row["failure_classification"]) if row["failure_classification"] else None,
                         row["failure_detail"], row["created_at"], row["updated_at"],
                         row["task_id"] if "task_id" in row.keys() else None,
                         row["cycle_id"] if "cycle_id" in row.keys() else None,
                         WorkKind(row["work_kind"]) if "work_kind" in row.keys() and row["work_kind"] else None)

    def _event_from_row(self, row: sqlite3.Row) -> WorkflowEvent:
        return WorkflowEvent(row["id"], row["workflow_id"], row["sequence"], row["type"],
                             Stage(row["stage"]) if row["stage"] else None, row["artifact_id"],
                             row["execution_id"], self._row_json(row["payload"]), row["created_at"])

    def _task_from_row(self, row: sqlite3.Row) -> TaskDefinition:
        return TaskDefinition(
            row["id"], row["workflow_id"], row["ordinal"], row["key"], row["title"],
            row["instructions"], tuple(self._row_json(row["acceptance_criteria"])),
            tuple(self._row_json(row["required_tests"])), tuple(self._row_json(row["context_paths"])),
            row["definition_json"], row["definition_sha256"], row["source_artifact_id"],
            row["source_artifact_sha256"], TaskStatus(row["status"]),
            row["current_review_window"], row["current_cycle"], row["accepted_at"],
        )

    def _task_cycle_from_row(self, row: sqlite3.Row) -> TaskCycle:
        return TaskCycle(
            row["id"], row["task_id"], row["review_window"], row["cycle"],
            row["developer_execution_id"], row["required_test_artifact_id"],
            row["reviewer_execution_id"], row["review_artifact_id"], row["outcome"],
            row["created_at"], row["updated_at"],
        )

    def _task_artifact_from_row(self, row: sqlite3.Row) -> TaskArtifact:
        return TaskArtifact(
            row["id"], row["workflow_id"], row["task_id"], row["cycle_id"],
            TaskArtifactType(row["artifact_type"]), row["path"], row["sha256"],
            row["source_execution_id"], row["created_at"],
        )

    def _intervention_from_row(self, row: sqlite3.Row) -> Intervention:
        return Intervention(
            row["id"], row["workflow_id"], row["task_id"], row["actor"], row["reason"],
            row["prior_review_window"], row["prior_cycle"], row["created_at"],
        )


SQLiteStore = WorkflowStore
