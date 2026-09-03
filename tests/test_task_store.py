import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.domain import (  # noqa: E402
    ApprovalDecision,
    ArtifactCorruptionFailure,
    ConflictFailure,
    Role,
    Stage,
    TaskArtifactType,
    ValidationFailure,
    WorkKind,
)
from engineering_flow.store import WorkflowStore, parse_task_plan_manifest  # noqa: E402


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        (self.repository / "context.md").write_text("context\n", encoding="utf-8")
        self.store = WorkflowStore(self.root / "workflows.sqlite3")
        self.workflow = self.store.create_workflow(self.repository)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def _manifest(self):
        return {
            "version": 1,
            "tasks": [
                {
                    "key": "TASK-001",
                    "title": "Implement the first task",
                    "instructions": "Make the bounded change.",
                    "acceptance_criteria": ["The change is observable."],
                    "required_tests": ["python -m unittest"],
                    "context_paths": ["context.md"],
                },
                {
                    "key": "TASK-002",
                    "title": "Implement the second task",
                    "instructions": "Make the next bounded change.",
                    "acceptance_criteria": ["The next change is observable."],
                    "required_tests": ["python -m unittest"],
                },
            ],
        }

    def _approved_plan(self, markdown=None, *, revision=1, request_hash="task-plan"):
        manifest = self._manifest()
        markdown = markdown or (
            "# Approved task plan\n\n```engineering-flow-task-plan\n"
            + json.dumps(manifest)
            + "\n```\n"
        )
        intent = self.store.create_generation_intent(
            self.workflow.id, Stage.TASK_PLAN, request_hash=request_hash, revision=revision
        )
        artifact = self.store.complete_generation(
            intent.operation.idempotency_key,
            content=markdown,
            artifact_path=self.root / "workflows" / self.workflow.id / "artifacts" / f"{revision:03d}-task-plan.md",
            stage=Stage.TASK_PLAN,
            revision=revision,
        )
        self.store.record_approval(
            self.workflow.id, artifact.id, ApprovalDecision.APPROVED, actor="human"
        )
        return artifact

    def test_import_is_ordered_idempotent_and_hash_verified(self):
        source = self._approved_plan()
        tasks = self.store.import_task_plan(self.workflow.id, source.id)
        replay = self.store.import_task_plan(self.workflow.id, source.id)
        self.assertEqual([task.key for task in tasks], ["TASK-001", "TASK-002"])
        self.assertEqual([task.id for task in replay], [task.id for task in tasks])
        self.assertEqual(tasks[0].context_paths, ("context.md",))
        definition = next(
            item for item in self.store.list_task_artifacts(tasks[0].id)
            if item.artifact_type is TaskArtifactType.DEFINITION
        )
        content = self.store.read_task_artifact(definition.id)
        self.assertEqual(definition.sha256, hashlib.sha256(content).hexdigest())
        Path(definition.path).write_text("tampered", encoding="utf-8")
        with self.assertRaises(ArtifactCorruptionFailure):
            self.store.read_task_artifact(definition.id)

    def test_manifest_rejects_invalid_blocks_and_context_paths(self):
        valid_task = self._manifest()["tasks"][0]
        invalid_manifests = [
            "no tagged block",
            "```engineering-flow-task-plan\n{}\n```\n```engineering-flow-task-plan\n{}\n```",
            {"version": 2, "tasks": [valid_task]},
            {"version": 1, "tasks": []},
            {"version": 1, "tasks": [valid_task, valid_task]},
            {"version": 1, "tasks": [{**valid_task, "title": ""}]},
            {"version": 1, "tasks": [{**valid_task, "context_paths": ["../outside"]}]},
            {"version": 1, "tasks": [{**valid_task, "context_paths": ["."]}]},
            {"version": 1, "tasks": [{**valid_task, "context_paths": ["context.md", "./context.md"]}]},
        ]
        for invalid in invalid_manifests:
            markdown = invalid if isinstance(invalid, str) else (
                "```engineering-flow-task-plan\n" + json.dumps(invalid) + "\n```"
            )
            with self.subTest(markdown=markdown), self.assertRaises(ValidationFailure):
                parse_task_plan_manifest(markdown, self.repository)

    def test_changed_task_plan_is_rejected_after_import(self):
        source = self._approved_plan()
        self.store.import_task_plan(self.workflow.id, source.id)
        changed = self._manifest()
        changed["tasks"][0]["instructions"] = "A changed task is not permitted."
        changed_source = self._approved_plan(
            "```engineering-flow-task-plan\n" + json.dumps(changed) + "\n```",
            revision=2,
            request_hash="changed-task-plan",
        )
        with self.assertRaises(ConflictFailure):
            self.store.import_task_plan(self.workflow.id, changed_source.id)

    def test_task_operation_replay_and_unknown_recovery(self):
        source = self._approved_plan()
        task = self.store.import_task_plan(self.workflow.id, source.id)[0]
        intent = self.store.create_task_operation(
            self.workflow.id, task.id, request_hash="developer-request"
        )
        replay = self.store.create_task_operation(
            self.workflow.id, task.id, request_hash="developer-request"
        )
        self.assertTrue(replay.reused)
        self.assertEqual(replay.execution.id, intent.execution.id)
        operation = self.store.get_operation(intent.operation.id)
        execution = self.store.get_execution(intent.execution.id)
        session = self.store.get_session(intent.execution.session_id)
        self.assertEqual((operation.task_id, operation.cycle_id), (task.id, intent.cycle_id))
        self.assertEqual((execution.task_id, execution.cycle_id), (task.id, intent.cycle_id))
        self.assertEqual((session.task_id, session.cycle_id), (task.id, intent.cycle_id))
        self.assertEqual(operation.work_kind.value, "develop")
        artifact = self.store.complete_task_operation(
            intent.operation.idempotency_key,
            content={"summary": "implemented"},
            artifact_type=TaskArtifactType.DEVELOPER_RESULT,
        )
        self.assertEqual(self.store.complete_task_operation(
            intent.operation.idempotency_key,
            content={"summary": "ignored"},
            artifact_type=TaskArtifactType.DEVELOPER_RESULT,
        ).id, artifact.id)
        review_intent = self.store.create_task_operation(
            self.workflow.id, task.id, request_hash="review-request", work_kind="review"
        )
        unknown = self.store.mark_task_operation_unknown(
            review_intent.operation.idempotency_key, detail="process lost"
        )
        self.assertEqual(unknown.status.value, "unknown")
        self.assertEqual(self.store.get_task(task.id).status.value, "human_attention")

    def test_task_operation_rejects_incompatible_role_before_persisting_intent(self):
        source = self._approved_plan()
        task = self.store.import_task_plan(self.workflow.id, source.id)[0]
        incompatible_operations = (
            (WorkKind.DEVELOP, Role.REVIEWER),
            (WorkKind.FIX, Role.REVIEWER),
            (WorkKind.REVIEW, Role.DEVELOPER),
        )

        for work_kind, role in incompatible_operations:
            with self.subTest(work_kind=work_kind, role=role):
                with self.assertRaisesRegex(ValidationFailure, "require the"):
                    self.store.create_task_operation(
                        self.workflow.id,
                        task.id,
                        request_hash=f"{work_kind.value}-{role.value}-request",
                        work_kind=work_kind,
                        role=role,
                    )
                self.assertEqual(self.store.list_task_cycles(task.id), [])
                self.assertEqual(self.store.get_task(task.id).status.value, "pending")
                for table in ("sessions", "executions", "operations"):
                    count = self.store._connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE task_id = ?", (task.id,)
                    ).fetchone()[0]
                    self.assertEqual(count, 0)

    def test_complete_cycle_links_and_replays_developer_test_and_reviewer_evidence(self):
        source = self._approved_plan()
        task = self.store.import_task_plan(self.workflow.id, source.id)[0]
        developer = self.store.create_task_operation(
            self.workflow.id, task.id, request_hash="developer-request"
        )
        developer_artifact = self.store.complete_task_operation(
            developer.operation.idempotency_key,
            content={"summary": "implemented"},
            artifact_type=TaskArtifactType.DEVELOPER_RESULT,
        )
        tests = self.store.record_task_test_evidence(
            task.id, developer.cycle_id,
            content={"command": "python -m unittest", "passed": True},
        )
        reviewer = self.store.create_task_operation(
            self.workflow.id, task.id, request_hash="review-request", work_kind=WorkKind.REVIEW
        )
        review_artifact = self.store.complete_task_operation(
            reviewer.operation.idempotency_key,
            content={"decision": "PASS", "findings": []},
            artifact_type=TaskArtifactType.REVIEW_RESULT,
            outcome="PASS",
        )

        cycle = self.store.get_task_cycle(developer.cycle_id)
        self.assertEqual(cycle.developer_execution_id, developer.execution.id)
        self.assertEqual(cycle.required_test_artifact_id, tests.id)
        self.assertEqual(cycle.reviewer_execution_id, reviewer.execution.id)
        self.assertEqual(cycle.review_artifact_id, review_artifact.id)
        self.assertEqual(cycle.outcome, "PASS")
        self.assertEqual(
            self.store.complete_task_operation(
                developer.operation.idempotency_key,
                content={"summary": "ignored"},
                artifact_type=TaskArtifactType.DEVELOPER_RESULT,
            ).id,
            developer_artifact.id,
        )
        self.assertEqual(
            self.store.record_task_test_evidence(
                task.id, developer.cycle_id,
                content={"command": "python -m unittest", "passed": True},
            ).id,
            tests.id,
        )
        self.assertEqual(
            self.store.complete_task_operation(
                reviewer.operation.idempotency_key,
                content={"decision": "ignored"},
                artifact_type=TaskArtifactType.REVIEW_RESULT,
            ).id,
            review_artifact.id,
        )
        self.assertEqual(len(self.store.list_task_artifacts(task.id)), 4)
        evidence_events = [
            event.type for event in self.store.list_events(self.workflow.id)
            if event.type in {"task.developer.completed", "test.completed", "review.completed"}
        ]
        self.assertEqual(
            evidence_events,
            ["task.developer.completed", "test.completed", "review.completed"],
        )
        with self.assertRaises(ValidationFailure):
            self.store.complete_task_operation(
                reviewer.operation.idempotency_key,
                content={"command": "python -m unittest", "passed": True},
                artifact_type=TaskArtifactType.TEST_RESULT,
            )

    def test_accept_task_persists_cycle_outcome_and_event(self):
        source = self._approved_plan()
        task = self.store.import_task_plan(self.workflow.id, source.id)[0]
        intent = self.store.create_task_operation(
            self.workflow.id, task.id, request_hash="developer-request"
        )
        accepted = self.store.accept_task(task.id, cycle_id=intent.cycle_id)
        self.assertEqual(accepted.status.value, "accepted")
        self.assertTrue(accepted.accepted_at.endswith("Z"))
        self.assertEqual(self.store.get_task_cycle(intent.cycle_id).outcome, "PASS")
        accepted_events = [
            event for event in self.store.list_events(self.workflow.id)
            if event.type == "task.accepted"
        ]
        self.assertEqual(len(accepted_events), 1)
        self.assertEqual(self.store.accept_task(task.id, cycle_id=intent.cycle_id).id, task.id)
        self.assertEqual(len([
            event for event in self.store.list_events(self.workflow.id)
            if event.type == "task.accepted"
        ]), 1)


class LegacyMigrationTests(unittest.TestCase):
    def test_wave_one_records_open_and_gain_nullable_task_correlations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = root / "repository"
            repository.mkdir()
            database = root / "workflows.sqlite3"
            connection = sqlite3.connect(database)
            connection.executescript("""
                CREATE TABLE workflows (
                    id TEXT PRIMARY KEY, repository_path TEXT NOT NULL, provider TEXT NOT NULL,
                    stage TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, configuration_snapshot TEXT NOT NULL,
                    current_artifact_revision INTEGER, feature_input_path TEXT,
                    feature_input_sha256 TEXT
                );
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, logical_session_id TEXT NOT NULL,
                    role TEXT NOT NULL, provider TEXT NOT NULL, provider_session_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE executions (
                    id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    role TEXT NOT NULL, provider_execution_id TEXT, request_hash TEXT NOT NULL,
                    lifecycle TEXT NOT NULL, capability_report TEXT NOT NULL, terminal_result TEXT,
                    failure_classification TEXT, failure_detail TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE operations (
                    id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
                    workflow_id TEXT NOT NULL, status TEXT NOT NULL, related_record_id TEXT,
                    intent_stage TEXT, intent_revision INTEGER, intent_artifact_path TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
            """)
            now = "2026-01-01T00:00:00.000000Z"
            connection.execute(
                "INSERT INTO workflows VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
                ("workflow-1", str(repository), "codex-cli", "ready_for_wave_2", "completed", now, now, "{}"),
            )
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
                ("session-1", "workflow-1", "logical-1", "planner", "codex-cli", now, now),
            )
            connection.execute(
                "INSERT INTO executions VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, ?, ?)",
                ("execution-1", "workflow-1", "session-1", "planner", "request-1", "completed", "{}", now, now),
            )
            connection.execute(
                "INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("operation-1", "legacy-key", "generate", "workflow-1", "completed", "execution-1",
                 "task_plan", 1, "legacy.md", now, now),
            )
            connection.commit()
            connection.close()

            with WorkflowStore(database) as store:
                self.assertEqual(store.get_workflow("workflow-1").stage, Stage.READY_FOR_WAVE_2)
                self.assertIsNone(store.get_session("session-1").task_id)
                self.assertIsNone(store.get_execution("execution-1").cycle_id)
                self.assertIsNone(store.get_operation("operation-1").work_kind)
                for table in ("sessions", "executions", "operations"):
                    columns = {
                        row["name"] for row in store._connection.execute(
                            f"PRAGMA table_info({table})"
                        )
                    }
                    self.assertTrue({"task_id", "cycle_id", "work_kind"} <= columns)


if __name__ == "__main__":
    unittest.main()
