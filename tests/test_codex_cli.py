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
from engineering_flow.domain import FailureClassification, Role, Stage, ValidationFailure  # noqa: E402
from engineering_flow.runtime import PlanningExecutionRequest, TerminalState  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
