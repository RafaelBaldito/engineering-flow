"""CLI acceptance coverage for the final MDS #3 presentation slice."""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engineering_flow.cli import main
from engineering_flow.config import INITIAL_CONFIG
from engineering_flow.domain import (ApprovalDecision, ApprovalState, ImplementationProfile,
                                     LifecycleVersion, Role, Stage, WorkflowStatus)
from engineering_flow.orchestrator import FakeWriterResult
from engineering_flow.store import WorkflowStore


def git(root, *args):
    return subprocess.run(("git", "-C", str(root), *args), check=True, stdout=subprocess.PIPE)


class Slice5CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"; self.root.mkdir()
        git(self.root, "init", "-q"); git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "Test")
        (self.root / ".gitignore").write_text(".engineering-flow/\n")
        (self.root / "source.py").write_text("before\n")
        git(self.root, "add", "."); git(self.root, "commit", "-qm", "initial")
        application = self.root / ".engineering-flow"; application.mkdir()
        (application / "config.toml").write_text(INITIAL_CONFIG)
        self.store = WorkflowStore(application / "workflows.sqlite3")

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def approved(self, *, second=False):
        workflow = self.store.create_workflow(self.root, provider="fake", lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
        intake = self.store.create_generation_intent(workflow.id, Stage.INTAKE, request_hash="f", provider="fake", role=Role.INTAKE, revision=1, artifact_path=self.store.feature_contract_path(workflow.id, 1))
        feature = {"outcome":"READY", "feature":{"id":workflow.id,"goal":"g","requirements":["r"],"acceptance_criteria":["a"],"constraints":[],"out_of_scope":[],"assumptions":[],"open_questions":[]}}
        artifact = self.store.complete_generation(intake.operation.idempotency_key, content=json.dumps(feature), artifact_path=self.store.feature_contract_path(workflow.id, 1), stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE, workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED)
        intent = self.store.create_generation_intent(workflow.id, Stage.PLAN, request_hash="p", provider="fake", role=Role.PLANNER, revision=1, artifact_path=self.store.plan_path(workflow.id, 1))
        task = lambda identity, deps: {"id":identity,"objective":identity,"context":{"relevant_files":["source.py"],"existing_patterns":[]},"requirements":["r"],"acceptance_criteria":["a"],"verification":["tests"],"constraints":[],"depends_on":deps,"complexity":"low","risk":"low"}
        plan = {"plan":{"id":f"{workflow.id}:plan:r1","workflow_id":workflow.id,"revision":1,"feature_contract":{"artifact_id":artifact.id,"sha256":artifact.sha256},"strategy":"s","assumptions":[],"verification_strategy":["tests"],"tasks":[task("T1", []), *( [task("T2", ["T1"])] if second else [])]}}
        plan_artifact = self.store.complete_generation(intent.operation.idempotency_key, content=json.dumps(plan), artifact_path=self.store.plan_path(workflow.id, 1), stage=Stage.PLAN, revision=1, workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.AWAITING_APPROVAL)
        self.store.record_approval(workflow.id, plan_artifact.id, ApprovalDecision.APPROVED, actor="human", workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.PLAN_APPROVED)
        self.store.set_selected_workflow_id(workflow.id)
        return workflow

    def invoke_json(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["resume", "--repo", str(self.root), "--json"])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_approved_resume_dispatches_one_task_once_and_reports_not_run(self):
        self.approved(second=True); calls = []
        class Writer:
            provider = "fake"
            def __init__(self, *args, **kwargs): pass
            def routing_for(self, task): return ImplementationProfile.EFFICIENT, "fake-model", "low"
            def bind(self, *args): pass
            def __call__(self, root, task):
                calls.append(task.id); Path(root, "source.py").write_text("after\n")
                return FakeWriterResult(True)
        with patch("engineering_flow.cli.CodexImplementationWriter", Writer):
            code, stdout, stderr = self.invoke_json()
        self.assertEqual(code, 0); self.assertEqual(stderr, "")
        document = json.loads(stdout); self.assertEqual(calls, ["T1"])
        self.assertEqual(document["status"], "implementation_completed")
        self.assertEqual(document["plan"]["implementation"]["verification_status"], "not_run")
        self.assertEqual(document["plan"]["plan"]["tasks"][1]["implementation_status"], "pending")

    def test_failed_unchanged_requires_a_later_explicit_resume(self):
        self.approved(); calls = []
        class Writer:
            provider = "fake"
            def __init__(self, *args, **kwargs): pass
            def routing_for(self, task): return ImplementationProfile.EFFICIENT, "fake-model", "low"
            def bind(self, *args): pass
            def __call__(self, root, task): calls.append(task.id); return FakeWriterResult(False, error="failed")
        with patch("engineering_flow.cli.CodexImplementationWriter", Writer):
            code, stdout, _ = self.invoke_json()
            self.assertNotEqual(code, 0); self.assertEqual(json.loads(stdout)["status"], "implementation_failed")
            code, stdout, _ = self.invoke_json()
        self.assertEqual(calls, ["T1", "T1"])
        self.assertEqual(json.loads(stdout)["status"], "implementation_failed")

    def test_changed_failure_is_human_attention_and_never_redispatches(self):
        self.approved(); calls = []
        class Writer:
            provider = "fake"
            def __init__(self, *args, **kwargs): pass
            def routing_for(self, task): return ImplementationProfile.EFFICIENT, "fake-model", "low"
            def bind(self, *args): pass
            def __call__(self, root, task):
                calls.append(task.id); Path(root, "source.py").write_text("partial\n")
                return FakeWriterResult(False, error="partial failure")
        with patch("engineering_flow.cli.CodexImplementationWriter", Writer):
            code, stdout, _ = self.invoke_json()
            self.assertEqual(code, 8); self.assertEqual(json.loads(stdout)["status"], "human_attention")
            self.invoke_json()
        self.assertEqual(calls, ["T1"])

    def test_approved_human_output_keeps_resume_as_the_explicit_writer_boundary(self):
        self.approved()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["status", "--repo", str(self.root)]), 0)
        self.assertIn("IMPLEMENT one eligible Task", output.getvalue())

