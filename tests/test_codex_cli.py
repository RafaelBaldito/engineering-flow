import json
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.codex_cli import CodexCliRuntime, FINAL_OUTPUT_SCHEMA  # noqa: E402
from engineering_flow.domain import FailureClassification, Role, Stage, ValidationFailure, WorkKind  # noqa: E402
from engineering_flow.runtime import PlanningExecutionRequest, TaskExecutionRequest, TerminalState  # noqa: E402


class FakeProcess:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0, timeout: bool = False):
        self.stdout_text = stdout
        self.stderr_text = stderr
        self.returncode = returncode
        self.timeout = timeout
        self.killed = False

    def communicate(self, timeout=None):
        if self.timeout and timeout is not None and not self.killed:
            raise subprocess.TimeoutExpired("codex", timeout, output=self.stdout_text, stderr=self.stderr_text)
        return self.stdout_text, self.stderr_text

    def kill(self):
        self.killed = True
        self.returncode = -9


class StreamingProcess:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0):
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class CodexCliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        git_dir = self.root / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_dir / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
        (git_dir / "objects").mkdir()
        (git_dir / "refs").mkdir()
        self.schema = self.root / "workspace" / "runtime" / "schema.json"
        self.output = self.root / "workspace" / "runtime" / "final.json"
        self.help_result = SimpleNamespace(
            returncode=0,
            stdout="codex exec --json --output-schema FILE --output-last-message FILE --sandbox {read-only,workspace-write}",
            stderr="",
        )
        self.process = None
        self.calls = []

    def tearDown(self):
        self.tempdir.cleanup()

    def request(self):
        return PlanningExecutionRequest(
            workflow_id="workflow-1", execution_id="execution-1", logical_session_id="session-1",
            role=Role.PRD, stage=Stage.PRD, repository_path=str(self.root),
            authoritative_input_paths=(str(self.root / "feature.md"),), authoritative_input_hashes=("hash",),
            instruction="Create the PRD.", output_schema_path=str(self.schema),
            final_output_path=str(self.output), timeout_seconds=3, required_capabilities=("json_events",),
        )

    def run_factory(self, *args, **kwargs):
        return self.help_result

    def git_runner(self, *args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="true\nfalse\n", stderr="")

    def popen_factory(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        payload = {
            "artifact_markdown": "# PRD",
            "summary": "A PRD",
            "requires_human_approval": True,
            "approval_reason": "required by policy",
        }
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(payload), encoding="utf-8")
        self.process = FakeProcess(
            '{"type":"thread.started","thread_id":"thread-1"}\n'
            '{"type":"turn.completed","id":"turn-1","usage":{"input_tokens":4}}\n'
        )
        return self.process

    def runtime(self, **kwargs):
        kwargs.setdefault("popen_factory", self.popen_factory)
        return CodexCliRuntime(
            command="codex", timeout_seconds=3, executable_resolver=lambda _: "codex",
            run_factory=self.run_factory, git_runner=self.git_runner, **kwargs,
        )

    def task_request(self, role, work_kind, **kwargs):
        return TaskExecutionRequest(
            workflow_id="workflow-1", execution_id="execution-task", logical_session_id="logical-task",
            role=role, work_kind=work_kind, stage=Stage.TASK_EXECUTION,
            repository_path=str(self.root), authoritative_input_paths=(), authoritative_input_hashes=(),
            instruction="Perform only the approved task.", output_schema_path=str(self.schema),
            final_output_path=str(self.output), timeout_seconds=3,
            **kwargs,
        )

    def test_preflight_requires_read_only_and_capabilities(self):
        runtime = self.runtime(allow_read_only_planning=False)
        report = runtime.verify_planning_capabilities(self.root)
        self.assertFalse(report.available)
        self.assertIn("read-only", report.failure_detail)
        with self.assertRaises(ValidationFailure):
            runtime.execute_planning(self.request())

        unsupported = self.runtime()
        unsupported._run = lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="codex exec", stderr="")
        report = unsupported.verify_planning_capabilities(self.root)
        self.assertFalse(report.available)
        self.assertIn("missing capabilities", report.failure_detail)

        missing_final_output = self.runtime()
        missing_final_output._run = lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="--json --output-schema --sandbox read-only",
            stderr="",
        )
        report = missing_final_output.verify_planning_capabilities(self.root)
        self.assertFalse(report.available)
        self.assertIn("output_last_message", report.failure_detail)

        developer = self.task_request(Role.DEVELOPER, WorkKind.DEVELOP)
        with self.assertRaises(ValidationFailure):
            self.runtime().execute(developer)

        reviewer = self.task_request(
            Role.REVIEWER, WorkKind.REVIEW,
            developer_logical_session_id="developer-session",
        )
        with self.assertRaises(ValidationFailure):
            self.runtime(allow_read_only_planning=False).execute(reviewer)

    def test_developer_preflight_does_not_require_reviewer_sandbox(self):
        runtime = self.runtime(allow_workspace_write=True)
        runtime._run = lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="codex exec --json --output-schema FILE --output-last-message FILE --sandbox workspace-write",
            stderr="",
        )

        developer = runtime.verify_capabilities(
            self.root, ("json_events", "output_schema", "output_last_message", "workspace_write"),
        )
        reviewer = runtime.verify_capabilities(
            self.root, ("json_events", "output_schema", "output_last_message", "read_only"),
        )

        self.assertTrue(developer.available)
        self.assertFalse(reviewer.available)
        self.assertIn("read-only", reviewer.failure_detail)

    def test_preflight_rejects_directory_with_only_git_marker(self):
        fake = self.root / "fake"
        (fake / ".git").mkdir(parents=True)
        report = self.runtime().verify_planning_capabilities(fake)
        self.assertFalse(report.available)
        self.assertFalse(report.capabilities["git_worktree"])

    def test_success_writes_schema_and_uses_safe_command(self):
        runtime = self.runtime()
        result = runtime.execute_planning(self.request())
        self.assertEqual(result.terminal_state, TerminalState.SUCCEEDED)
        self.assertEqual(result.provider_session_id, "thread-1")
        self.assertEqual(result.provider_execution_id, "turn-1")
        self.assertEqual(result.content, "# PRD")
        self.assertEqual(json.loads(self.schema.read_text(encoding="utf-8")), FINAL_OUTPUT_SCHEMA)
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[:5], ["codex", "exec", "--json", "--sandbox", "read-only"])
        self.assertIn("--output-schema", argv)
        self.assertIn("--output-last-message", argv)
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["cwd"], str(self.root.resolve()))
        self.assertNotIn("API_KEY", kwargs["env"])

    def test_malformed_output_is_agent_failure(self):
        def malformed_popen(argv, **kwargs):
            return FakeProcess("not-json\n{\"type\":\"turn.completed\"}\n")

        runtime = self.runtime(popen_factory=malformed_popen)
        result = runtime.execute_planning(self.request())
        self.assertEqual(result.failure_classification, FailureClassification.AGENT_EXECUTION)
        self.assertEqual(result.terminal_state, TerminalState.FAILED)

    def test_timeout_is_distinct(self):
        runtime = self.runtime(popen_factory=lambda argv, **kwargs: FakeProcess("", timeout=True))
        result = runtime.execute_planning(self.request())
        self.assertEqual(result.terminal_state, TerminalState.TIMED_OUT)
        self.assertEqual(result.failure_classification, FailureClassification.AGENT_EXECUTION)

    def test_nonzero_and_authentication_failures_are_distinct(self):
        runtime = self.runtime(popen_factory=lambda argv, **kwargs: FakeProcess(
            "", "PATH=C:/sensitive-user-profile\\bin\nAPI_KEY=top-secret\ntool crashed", 2
        ))
        result = runtime.execute_planning(self.request())
        self.assertEqual(result.failure_classification, FailureClassification.PROVIDER)
        self.assertNotIn("C:/sensitive-user-profile", result.metadata["stderr"])
        self.assertNotIn("top-secret", result.metadata["stderr"])
        self.assertIn("PATH=[REDACTED]", result.metadata["stderr"])

        auth = self.runtime(popen_factory=lambda argv, **kwargs: FakeProcess("", "Authentication required", 1))
        result = auth.execute_planning(self.request())
        self.assertEqual(result.failure_classification, FailureClassification.AUTHENTICATION)

    def test_zero_exit_authentication_event_is_distinct(self):
        auth = self.runtime(popen_factory=lambda argv, **kwargs: FakeProcess(
            '{"type":"error","message":"Authentication required"}\n'
        ))
        result = auth.execute_planning(self.request())
        self.assertEqual(result.terminal_state, TerminalState.FAILED)
        self.assertEqual(result.failure_classification, FailureClassification.AUTHENTICATION)

    def test_successful_artifact_mentioning_authentication_is_not_auth_failure(self):
        payload = {
            "artifact_markdown": "# Authentication\n\nAuthentication is required for deployment.",
            "summary": "Defines authentication requirements.",
            "requires_human_approval": True,
            "approval_reason": "required by policy",
        }
        runtime = self.runtime(popen_factory=lambda argv, **kwargs: FakeProcess(
            json.dumps({"type": "item.completed", "payload": payload}) + "\n"
            '{"type":"turn.completed","id":"turn-auth-content"}\n'
        ))

        result = runtime.execute_planning(self.request())

        self.assertEqual(result.terminal_state, TerminalState.SUCCEEDED)
        self.assertIsNone(result.failure_classification)
        self.assertEqual(result.content, payload["artifact_markdown"])

    def test_jsonl_is_consumed_from_streaming_stdout(self):
        def streaming_popen(argv, **kwargs):
            payload = {
                "artifact_markdown": "# PRD",
                "summary": "A PRD",
                "requires_human_approval": True,
                "approval_reason": "required by policy",
            }
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps(payload), encoding="utf-8")
            return StreamingProcess(
                '{"type":"thread.started","thread_id":"thread-stream"}\n'
                '{"type":"turn.completed","id":"turn-stream"}\n'
            )

        result = self.runtime(popen_factory=streaming_popen).execute_planning(self.request())
        self.assertTrue(result.success)
        self.assertEqual(result.provider_session_id, "thread-stream")
        self.assertEqual([event.type for event in result.events], ["thread.started", "turn.completed"])

    def test_developer_uses_workspace_write_and_exact_required_test_payload(self):
        request = self.task_request(
            Role.DEVELOPER, WorkKind.DEVELOP, required_test_commands=("python -m unittest",),
        )

        calls = []

        def developer_popen(argv, **kwargs):
            calls.append((argv, kwargs))
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps({
                "summary": "implemented", "changed_files": ["src/example.py"],
                "test_results": [{"command": "python -m unittest", "passed": True, "summary": "ok"}],
            }), encoding="utf-8")
            return FakeProcess('{"type":"thread.started","thread_id":"developer-thread"}\n'
                               '{"type":"turn.completed","id":"developer-turn"}\n')

        result = self.runtime(allow_workspace_write=True, popen_factory=developer_popen).execute(request)

        self.assertTrue(result.success)
        self.assertEqual(result.final_payload["changed_files"], ["src/example.py"])
        self.assertEqual(calls[0][0][4], "workspace-write")
        self.assertEqual(calls[0][1]["cwd"], str(self.root.resolve()))
        self.assertFalse(calls[0][1]["shell"])

    def test_reviewer_is_read_only_and_rejects_semantically_invalid_payload(self):
        request = self.task_request(
            Role.REVIEWER, WorkKind.REVIEW, developer_logical_session_id="developer-session",
        )
        calls = []

        def reviewer_popen(argv, **kwargs):
            calls.append((argv, kwargs))
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps({"outcome": "PASS", "summary": "looks good", "findings": [{
                "id": "F-1", "severity": "non_blocking", "description": "observation",
            }]}), encoding="utf-8")
            return FakeProcess('{"type":"turn.completed","id":"review-turn"}\n')

        result = self.runtime(popen_factory=reviewer_popen).execute(request)

        self.assertEqual(result.failure_classification, FailureClassification.AGENT_EXECUTION)
        self.assertEqual(calls[0][0][4], "read-only")
        self.assertFalse(calls[0][1]["shell"])

    def test_reviewer_rejects_fix_required_mixed_with_non_blocking_findings(self):
        request = self.task_request(
            Role.REVIEWER, WorkKind.REVIEW, developer_logical_session_id="developer-session",
        )

        def reviewer_popen(argv, **kwargs):
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps({
                "outcome": "FIX_REQUIRED", "summary": "needs work", "findings": [
                    {"id": "F-1", "severity": "blocking", "description": "defect"},
                    {"id": "F-2", "severity": "non_blocking", "description": "note"},
                ],
            }), encoding="utf-8")
            return FakeProcess('{"type":"turn.completed","id":"review-turn"}\n')

        result = self.runtime(popen_factory=reviewer_popen).execute(request)

        self.assertEqual(result.failure_classification, FailureClassification.AGENT_EXECUTION)
        self.assertIn("only blocking findings", result.failure_detail)

    def test_developer_continuity_falls_back_when_resume_is_not_advertised(self):
        request = self.task_request(
            Role.DEVELOPER, WorkKind.FIX, resume_provider_session_id="old-thread",
            continuity_bundle={"task_contract": {"key": "TASK-1"}, "review_findings": [{"id": "F-1"}]},
        )
        calls = []

        def fallback_popen(argv, **kwargs):
            calls.append(argv)
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps({
                "summary": "fixed", "changed_files": [], "test_results": [],
            }), encoding="utf-8")
            return FakeProcess('{"type":"turn.completed","id":"fix-turn"}\n')

        result = self.runtime(allow_workspace_write=True, popen_factory=fallback_popen).execute(request)

        self.assertTrue(result.success)
        self.assertTrue(result.metadata["continuity_degraded"])
        self.assertNotIn("resume", calls[0])
        self.assertIn("Bounded continuity evidence", calls[0][-1])

    def test_developer_resume_uses_only_advertised_subcommand(self):
        request = self.task_request(
            Role.DEVELOPER, WorkKind.FIX, resume_provider_session_id="old-thread",
        )
        calls = []
        self.help_result.stdout += "\ncodex exec resume [SESSION_ID]"

        def resume_popen(argv, **kwargs):
            calls.append(argv)
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps({
                "summary": "fixed", "changed_files": [], "test_results": [],
            }), encoding="utf-8")
            return FakeProcess('{"type":"thread.started","thread_id":"new-thread"}\n'
                               '{"type":"turn.completed","id":"fix-turn"}\n')

        result = self.runtime(allow_workspace_write=True, popen_factory=resume_popen).execute(request)

        self.assertTrue(result.success)
        self.assertFalse(result.metadata["continuity_degraded"])
        self.assertEqual(calls[0][:4], ["codex", "exec", "resume", "old-thread"])

    def test_developer_resume_falls_back_for_prose_or_alternate_syntax(self):
        request = self.task_request(
            Role.DEVELOPER, WorkKind.FIX, resume_provider_session_id="old-thread",
            continuity_bundle={"task_contract": {"key": "TASK-1"}},
        )
        self.help_result.stdout += "\nUse resume later or codex exec --resume SESSION_ID"
        calls = []

        def fallback_popen(argv, **kwargs):
            calls.append(argv)
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps({
                "summary": "fixed", "changed_files": [], "test_results": [],
            }), encoding="utf-8")
            return FakeProcess('{"type":"turn.completed","id":"fix-turn"}\n')

        report = self.runtime(allow_workspace_write=True).verify_capabilities(
            self.root, ("workspace_write", "json_events", "output_schema", "output_last_message"),
        )
        self.assertTrue(report.available)
        self.assertFalse(report.capabilities["developer_resume"])
        self.assertEqual(report.metadata["developer_resume_argv"], ())

        result = self.runtime(allow_workspace_write=True, popen_factory=fallback_popen).execute(request)

        self.assertTrue(result.success)
        self.assertTrue(result.metadata["continuity_degraded"])
        self.assertNotIn("resume", calls[0])


if __name__ == "__main__":
    unittest.main()
