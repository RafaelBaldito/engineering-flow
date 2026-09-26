import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from engineering_flow.domain import ApprovalDecision, ApprovalState, ImplementationProfile, LifecycleVersion, Stage, WorkflowStatus
from engineering_flow.domain import ConflictFailure
from engineering_flow.orchestrator import FakeWriterResult, ImplementationAttemptOrchestrator
from engineering_flow.repository import RepositoryInspector
from engineering_flow.store import WorkflowStore


def git(root, *args):
    return subprocess.run(("git", "-C", str(root), *args), check=True, stdout=subprocess.PIPE).stdout


class Slice2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name) / "repo"; self.root.mkdir()
        git(self.root, "init", "-q"); git(self.root, "config", "user.email", "test@example.invalid"); git(self.root, "config", "user.name", "Test")
        (self.root / ".gitignore").write_text(".engineering-flow/\nignored\n")
        (self.root / "source.py").write_text("value = 1\n")
        git(self.root, "add", "."); git(self.root, "commit", "-qm", "initial")
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")

    def tearDown(self): self.store.close(); self.temp.cleanup()

    def approved(self, tasks=(("T1", ()),)):
        w = self.store.create_workflow(self.root, provider="never-real", lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
        fi = self.store.create_generation_intent(w.id, Stage.INTAKE, request_hash="f", provider="fake", role="intake", revision=1, artifact_path=self.store.feature_contract_path(w.id, 1))
        fp = {"outcome":"READY","feature":{"id":w.id,"goal":"g","requirements":["r"],"acceptance_criteria":["a"],"constraints":[],"out_of_scope":[],"assumptions":[],"open_questions":[]}}
        f = self.store.complete_generation(fi.operation.idempotency_key, content=json.dumps(fp), artifact_path=self.store.feature_contract_path(w.id,1), stage=Stage.INTAKE, revision=1, workflow_stage=Stage.INTAKE, workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED)
        pi = self.store.create_generation_intent(w.id, Stage.PLAN, request_hash="p", provider="fake", role="planner", revision=1, artifact_path=self.store.plan_path(w.id,1))
        task_data = [{"id": ident,"objective":ident,"context":{"relevant_files":["source.py"],"existing_patterns":[]},"requirements":["r"],"acceptance_criteria":["a"],"verification":["test"],"constraints":[],"depends_on":list(deps),"complexity":"low","risk":"low"} for ident,deps in tasks]
        p = {"plan":{"id":f"{w.id}:plan:r1","workflow_id":w.id,"revision":1,"feature_contract":{"artifact_id":f.id,"sha256":f.sha256},"strategy":"s","assumptions":[],"verification_strategy":["test"],"tasks":task_data}}
        a = self.store.complete_generation(pi.operation.idempotency_key, content=json.dumps(p), artifact_path=self.store.plan_path(w.id,1), stage=Stage.PLAN, revision=1, workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.AWAITING_APPROVAL)
        self.store.record_approval(w.id,a.id,ApprovalDecision.APPROVED,actor="human",workflow_stage=Stage.PLAN,workflow_status=WorkflowStatus.PLAN_APPROVED)
        return w

    def test_repository_clean_policy_and_snapshot(self):
        first = RepositoryInspector(self.root).capture(require_clean=True)
        self.assertEqual(first, RepositoryInspector(self.root).capture(require_clean=True))
        (self.root / "ignored").write_text("ok")
        RepositoryInspector(self.root).capture(require_clean=True)
        (self.root / "untracked").write_text("no")
        with self.assertRaisesRegex(Exception, "not clean"): RepositoryInspector(self.root).capture(require_clean=True)
        (self.root / "untracked").unlink(); (self.root / "source.py").write_text("dirty\n")
        with self.assertRaisesRegex(Exception, "not clean"): RepositoryInspector(self.root).capture(require_clean=True)

    def test_repository_identity_rejections(self):
        git(self.root, "checkout", "--detach", "-q")
        with self.assertRaisesRegex(Exception, "attached"): RepositoryInspector(self.root).capture()
        git(self.root, "checkout", "-q", "-")
        nested = self.root / "nested"; nested.mkdir(); git(nested, "init", "-q")
        with self.assertRaisesRegex(Exception, "nested"): RepositoryInspector(self.root).capture()

    def test_symlink_untracked_manifest_does_not_follow_target(self):
        (self.root / "outside").symlink_to("/etc/passwd")
        snapshot = RepositoryInspector(self.root).capture()
        self.assertIn("outside", snapshot.changed_paths)
        self.assertNotEqual(snapshot.untracked_manifest_sha256, "")

    def test_success_changed_is_one_fake_call_and_unverified(self):
        w = self.approved(tasks=(("T1",()),("T2",("T1",))))
        calls = []
        def writer(root, task):
            calls.append(task.id); (Path(root)/"source.py").write_text("value = 2\n"); return FakeWriterResult(True, ("wrong.py",))
        ImplementationAttemptOrchestrator(self.store, writer).run_once(w.id)
        self.assertEqual(calls, ["T1"])
        plan_id = self.store._connection.execute("SELECT plan_artifact_id FROM implementation_attempts").fetchone()[0]
        state = self.store.list_task_implementation_states(w.id, plan_id)[0]
        self.assertEqual(state.status.value, "implementation_completed")
        self.assertEqual(self.store.get_workflow(w.id).status.value, "implementation_completed")
        row = self.store._connection.execute("SELECT changed_paths_json FROM implementation_attempts").fetchone()
        self.assertEqual(json.loads(row[0]), ["source.py"])

    def test_failure_unchanged_later_invocation_can_retry_but_never_loops(self):
        w = self.approved(); calls=[]
        def fail(root, task): calls.append(task.id); return FakeWriterResult(False, error="no")
        ImplementationAttemptOrchestrator(self.store, fail).run_once(w.id)
        self.assertEqual(calls,["T1"])
        # A new explicit invocation is eligible and makes one new call.
        ImplementationAttemptOrchestrator(self.store, fail).run_once(w.id)
        self.assertEqual(calls,["T1","T1"])

    def test_failure_changed_is_unknown_and_no_retry(self):
        w=self.approved(); calls=[]
        def writer(root, task): calls.append(1); (Path(root)/"source.py").write_text("partial\n"); return FakeWriterResult(False)
        ImplementationAttemptOrchestrator(self.store, writer).run_once(w.id)
        self.assertEqual(self.store.get_workflow(w.id).status.value,"human_attention")
        with self.assertRaises(ConflictFailure):
            ImplementationAttemptOrchestrator(self.store, writer).run_once(w.id)
        self.assertEqual(calls,[1])

    def test_head_change_is_safety_violation(self):
        w=self.approved()
        def writer(root, task):
            (Path(root)/"source.py").write_text("committed\n"); git(Path(root),"add","source.py"); git(Path(root),"commit","-qm","bad"); return FakeWriterResult(True)
        ImplementationAttemptOrchestrator(self.store, writer).run_once(w.id)
        self.assertEqual(self.store.get_workflow(w.id).status.value,"human_attention")

    def test_toctou_change_prevents_writer(self):
        w=self.approved(); calls=[]
        def before(): (self.root/"source.py").write_text("raced\n")
        ImplementationAttemptOrchestrator(self.store, lambda *_: calls.append(1) or FakeWriterResult(True), before_dispatch=before).run_once(w.id)
        self.assertEqual(calls,[])

    def test_resolved_routing_binds_hash_and_persists_requested_separate_from_actual(self):
        class RoutedWriter:
            provider = "codex-cli"
            def __init__(self, model, reasoning): self.model, self.reasoning, self.calls = model, reasoning, []
            def routing_for(self, task): return ImplementationProfile.BALANCED, self.model, self.reasoning
            def bind(self, authority, task, intent, store): self.intent = intent
            def __call__(self, root, task):
                self.calls.append(task.id); (Path(root) / "source.py").write_text("value = 2\n")
                return FakeWriterResult(True, actual_provider="codex-cli", actual_model="runtime-model",
                    actual_reasoning="runtime-reasoning", provider_operation_ref="turn-1", provider_session_ref="session-1",
                    usage={"input_tokens": 3})
        writer = RoutedWriter("configured-balanced", "medium")
        ImplementationAttemptOrchestrator(self.store, writer).run_once(self.approved().id)
        row = self.store._connection.execute("""SELECT request_hash,requested_provider,requested_profile,
            requested_model,requested_reasoning,actual_provider,actual_model,actual_reasoning,usage_json
            FROM implementation_attempts""").fetchone()
        self.assertEqual(writer.calls, ["T1"])
        self.assertEqual(tuple(row[1:5]), ("codex-cli", "balanced", "configured-balanced", "medium"))
        self.assertEqual(tuple(row[5:8]), ("codex-cli", "runtime-model", "runtime-reasoning"))
        self.assertEqual(json.loads(row[8]), {"input_tokens": 3})
        first_hash = row[0]
        (self.root / "source.py").write_text("value = 1\n")
        writer = RoutedWriter("changed-balanced", "high")
        ImplementationAttemptOrchestrator(self.store, writer).run_once(self.approved().id)
        second_hash = self.store._connection.execute("SELECT request_hash FROM implementation_attempts ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        self.assertNotEqual(first_hash, second_hash)
