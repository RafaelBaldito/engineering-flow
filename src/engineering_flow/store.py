"""Durable SQLite persistence for provider-neutral workflow state."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import (
    Approval,
    ApprovalDecision,
    ApprovalState,
    Artifact,
    ArtifactCorruptionFailure,
    ConflictFailure,
    DomainFailure,
    Execution,
    ExecutionLifecycle,
    FailureClassification,
    GenerationIntent,
    NotFoundFailure,
    Operation,
    OperationStatus,
    PersistenceFailure,
    Role,
    Session,
    Stage,
    ValidationFailure,
    Workflow,
    WorkflowEvent,
    WorkflowStatus,
)
from .sanitization import sanitize_configuration_snapshot, sanitize_payload, sanitize_text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL REFERENCES workflows(id),
            logical_session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_session_id TEXT,
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
        CREATE INDEX IF NOT EXISTS idx_events_workflow_sequence
            ON events(workflow_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_artifacts_workflow_stage
            ON artifacts(workflow_id, stage, revision);
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
                for name, statement in (
                    ("feature_input_path", "ALTER TABLE workflows ADD COLUMN feature_input_path TEXT"),
                    ("feature_input_sha256", "ALTER TABLE workflows ADD COLUMN feature_input_sha256 TEXT"),
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
            except sqlite3.Error as exc:
                raise PersistenceFailure(f"could not create workflow schema: {exc}") from exc

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._writer_lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.execute("COMMIT")
            except DomainFailure:
                self._connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError as exc:
                self._connection.execute("ROLLBACK")
                raise ConflictFailure(f"workflow record conflicts with an existing record: {exc}") from exc
            except sqlite3.OperationalError as exc:
                try:
                    self._connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise PersistenceFailure(f"workflow database is unavailable: {exc}") from exc
            except sqlite3.Error as exc:
                self._connection.execute("ROLLBACK")
                raise PersistenceFailure(f"workflow database error: {exc}") from exc

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
    ) -> Workflow:
        if not provider:
            raise ValidationFailure("provider is required")
        snapshot = sanitize_configuration_snapshot(configuration_snapshot or {}, self.secret_values)
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
                 configuration_snapshot, current_artifact_revision, feature_input_path, feature_input_sha256)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
                (workflow_id, str(Path(repository_path).expanduser().resolve()), provider,
                 Stage.PRD.value, WorkflowStatus.CREATED.value, now, now, _json(snapshot),
                 str(retained_feature_path) if retained_feature_path else None, feature_sha256),
            )
            self._event_unlocked(conn, workflow_id, "workflow.created", stage=Stage.PRD,
                                 payload={
                                     "provider": provider,
                                     **({
                                         "feature_input_path": str(retained_feature_path),
                                         "feature_input_sha256": feature_sha256,
                                     } if retained_feature_path else {}),
                                 })
        return self.get_workflow(workflow_id)

    def get_workflow(self, workflow_id: str) -> Workflow:
        row = self._connection.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise NotFoundFailure(f"workflow not found: {workflow_id}")
        return Workflow(row["id"], row["repository_path"], row["provider"],
                        Stage(row["stage"]), WorkflowStatus(row["status"]), row["created_at"],
                        row["updated_at"], self._row_json(row["configuration_snapshot"]),
                        row["current_artifact_revision"], row["feature_input_path"],
                        row["feature_input_sha256"])

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

    def _create_session_unlocked(self, conn: sqlite3.Connection, workflow_id: str, provider: str,
                                 role: Role, logical_session_id: str | None = None) -> Session:
        now = _now()
        session = Session(str(uuid.uuid4()), workflow_id, logical_session_id or str(uuid.uuid4()),
                          role, provider, None, now, now)
        conn.execute(
            """INSERT INTO sessions
            (id, workflow_id, logical_session_id, role, provider, provider_session_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session.id, workflow_id, session.logical_session_id, role.value, provider, None, now, now),
        )
        return session

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
    ) -> Artifact:
        stage = self._require_enum(stage, Stage)
        if workflow_status is not None:
            workflow_status = self._require_enum(workflow_status, WorkflowStatus)
        if workflow_stage is not None:
            workflow_stage = self._require_enum(workflow_stage, Stage)
        if revision < 1:
            raise ValidationFailure("artifact revision must be positive")
        with self._transaction() as conn:
            operation_row = conn.execute("SELECT * FROM operations WHERE idempotency_key = ?", (operation_key,)).fetchone()
            if operation_row is None:
                raise NotFoundFailure(f"operation not found: {operation_key}")
            operation = self._operation_from_row(operation_row)
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
                 ApprovalState.PENDING.value, now),
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
        return self.get_artifact(artifact_id)

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

    def _approval_from_row(self, row: sqlite3.Row) -> Approval:
        return Approval(row["id"], row["workflow_id"], row["artifact_id"], ApprovalDecision(row["decision"]),
                        row["actor"], row["reason"], row["created_at"])

    def _operation_from_row(self, row: sqlite3.Row) -> Operation:
        return Operation(row["id"], row["idempotency_key"], row["kind"], row["workflow_id"],
                         OperationStatus(row["status"]), row["related_record_id"], row["created_at"], row["updated_at"])

    def _execution_from_row(self, row: sqlite3.Row) -> Execution:
        return Execution(row["id"], row["workflow_id"], row["session_id"], Role(row["role"]),
                         row["provider_execution_id"], row["request_hash"], ExecutionLifecycle(row["lifecycle"]),
                         self._row_json(row["capability_report"]), self._row_json(row["terminal_result"]),
                         FailureClassification(row["failure_classification"]) if row["failure_classification"] else None,
                         row["failure_detail"], row["created_at"], row["updated_at"])

    def _event_from_row(self, row: sqlite3.Row) -> WorkflowEvent:
        return WorkflowEvent(row["id"], row["workflow_id"], row["sequence"], row["type"],
                             Stage(row["stage"]) if row["stage"] else None, row["artifact_id"],
                             row["execution_id"], self._row_json(row["payload"]), row["created_at"])


SQLiteStore = WorkflowStore
