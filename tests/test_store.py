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
    ValidationFailure,
    Stage,
)
from engineering_flow.store import WorkflowStore  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "workflows.sqlite3"
        self.store = WorkflowStore(self.db_path, secret_values=("TOP-SECRET",))

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_schema_enables_wal_foreign_keys_and_required_tables(self):
        self.assertEqual(self.store._connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.assertEqual(self.store._connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        names = {
            row[0] for row in self.store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({"workflows", "artifacts", "approvals", "sessions", "executions", "operations", "events"} <= names)

    def test_generation_intent_and_approval_replay_are_idempotent(self):
        workflow = self.store.create_workflow("/repo", configuration_snapshot={"secret": "TOP-SECRET"})
        first = self.store.create_generation_intent(workflow.id, Stage.PRD, request_hash="request-hash")
        replay = self.store.create_generation_intent(workflow.id, Stage.PRD, request_hash="request-hash")
        self.assertTrue(replay.reused)
        self.assertEqual(first.execution.id, replay.execution.id)

        artifact = self.store.complete_generation(
            first.operation.idempotency_key,
            content="# PRD\n",
            artifact_path=Path(self.temp_dir.name) / "workflows" / workflow.id / "artifacts" / "001-prd.md",
            stage=Stage.PRD,
            revision=1,
        )
        replay_after_completion = self.store.create_generation_intent(
            workflow.id, Stage.PRD, request_hash="request-hash"
        )
        self.assertTrue(replay_after_completion.reused)
        approval = self.store.record_approval(
            workflow.id, artifact.id, ApprovalDecision.APPROVED, actor="human", reason="TOP-SECRET"
        )
        self.assertEqual(approval.id, self.store.record_approval(
            workflow.id, artifact.id, ApprovalDecision.APPROVED, actor="human", reason="ignored"
        ).id)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0], 1)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], 1)

    def test_generation_completion_matches_intent_binding(self):
        workflow = self.store.create_workflow("/repo")
        intent = self.store.create_generation_intent(workflow.id, Stage.PRD, request_hash="request-hash")
        with self.assertRaises(ValidationFailure):
            self.store.complete_generation(
                intent.operation.idempotency_key,
                content="# TECHSPEC\n",
                artifact_path=Path(self.temp_dir.name) / "arbitrary-name.md",
                stage=Stage.TECHSPEC,
                revision=17,
            )
        with self.assertRaises(ValidationFailure):
            self.store.complete_generation(
                intent.operation.idempotency_key,
                content="# PRD\n",
                artifact_path=Path(self.temp_dir.name)
                / "workflows"
                / workflow.id
                / "artifacts"
                / "001-prd.md",
                stage=Stage.PRD,
                revision=17,
            )
        with self.assertRaises(ValidationFailure):
            self.store.complete_generation(
                intent.operation.idempotency_key,
                content="# PRD\n",
                artifact_path=Path(self.temp_dir.name) / "arbitrary-name.md",
                stage=Stage.PRD,
                revision=1,
            )

        artifact = self.store.complete_generation(
            intent.operation.idempotency_key,
            content="# PRD\n",
            artifact_path=Path(self.temp_dir.name)
            / "workflows"
            / workflow.id
            / "artifacts"
            / "001-prd.md",
            stage=Stage.PRD,
            revision=1,
        )
        self.assertEqual(artifact.stage, Stage.PRD)

    def test_artifact_is_revisioned_immutable_and_hash_verified(self):
        workflow = self.store.create_workflow("/repo")
        intent = self.store.create_generation_intent(workflow.id, Stage.PRD, request_hash="hash")
        path = Path(self.temp_dir.name) / "workflows" / workflow.id / "artifacts" / "001-prd.md"
        artifact = self.store.complete_generation(intent.operation.idempotency_key, content="stable", artifact_path=path,
                                                  stage=Stage.PRD, revision=1)
        self.assertEqual(artifact.sha256, hashlib.sha256(b"stable").hexdigest())
        self.assertEqual(self.store.read_artifact(artifact.id), "stable")
        path.write_text("modified", encoding="utf-8")
        with self.assertRaises(ArtifactCorruptionFailure):
            self.store.read_artifact(artifact.id)
        second = self.store.create_generation_intent(
            workflow.id, Stage.PRD, request_hash="hash-2", artifact_path=path
        )
        with self.assertRaises(ConflictFailure):
            self.store.complete_generation(second.operation.idempotency_key, content="x", artifact_path=path,
                                           stage=Stage.PRD, revision=2)

    def test_events_are_monotonic_and_sanitized(self):
        workflow = self.store.create_workflow(
            "/repo",
            configuration_snapshot={
                "api_token": "TOP-SECRET",
                "environment": {"PATH": "C:/sensitive-runtime-path"},
            },
        )
        self.store.append_event(
            workflow.id,
            "diagnostic.environment",
            payload={
                "env": {"PATH": "C:/event-path"},
                "nested": {"ENVIRONMENT": {"HOME": "C:/event-home"}},
                "input_tokens": 101,
            },
        )
        intent = self.store.create_generation_intent(
            workflow.id,
            Stage.PRD,
            request_hash="hash",
            capability_report={
                "password": "TOP-SECRET",
                "environment": {"HOME": "C:/capability-home"},
                "cached_input_tokens": 202,
            },
        )
        self.store.complete_generation(intent.operation.idempotency_key, content="content", stage=Stage.PRD,
                                       revision=1, artifact_path=Path(self.temp_dir.name) / "workflows" / workflow.id
                                       / "artifacts" / "001-prd.md",
            terminal_result={
                "stderr": "token=TOP-SECRET",
                "env": {"SHELL": "C:/terminal-shell"},
                "nested": {"environment": {"TEMP": "C:/terminal-temp"}},
                "output_tokens": 303,
            })
        events = self.store.list_events(workflow.id)
        self.assertEqual([event.sequence for event in events], list(range(1, len(events) + 1)))
        encoded = json.dumps([event.payload for event in events])
        self.assertNotIn("TOP-SECRET", encoded)
        for environment_value in (
            "C:/event-path",
            "C:/event-home",
            "C:/capability-home",
            "C:/terminal-shell",
            "C:/terminal-temp",
        ):
            self.assertNotIn(environment_value, encoded)
        self.assertNotIn('"env"', encoded)
        self.assertNotIn('"ENVIRONMENT"', encoded)
        self.assertNotIn('"environment"', encoded)
        self.assertNotIn("environment", json.dumps(intent.execution.capability_report))
        self.assertNotIn("C:/capability-home", json.dumps(intent.execution.capability_report))
        execution = self.store.get_execution(intent.execution.id)
        self.assertNotIn("env", json.dumps(execution.terminal_result))
        self.assertNotIn("environment", json.dumps(execution.terminal_result))
        self.assertNotIn("C:/terminal-shell", json.dumps(execution.terminal_result))
        diagnostic_event = next(event for event in events if event.type == "diagnostic.environment")
        self.assertEqual(diagnostic_event.payload["input_tokens"], 101)
        self.assertEqual(intent.execution.capability_report["cached_input_tokens"], 202)
        self.assertEqual(execution.terminal_result["output_tokens"], 303)
        self.assertEqual(self.store.get_workflow(workflow.id).configuration_snapshot["api_token"], "[REDACTED]")
        self.assertNotIn("environment", self.store.get_workflow(workflow.id).configuration_snapshot)
        self.assertNotIn("C:/sensitive-runtime-path", json.dumps(
            self.store.get_workflow(workflow.id).configuration_snapshot
        ))

    def test_foreign_keys_reject_orphan_records(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._connection.execute(
                "INSERT INTO artifacts (id, workflow_id, stage, revision, path, sha256, approval_state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("a", "missing", "prd", 1, "x", "0" * 64, "pending", "now"),
            )


if __name__ == "__main__":
    unittest.main()
