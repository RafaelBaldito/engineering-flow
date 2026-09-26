import io
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.domain import Stage  # noqa: E402
from engineering_flow.presentation import (OutputMode, ProgressRenderer, create_progress_renderer,
                                           prompt_for_plan_decision, render_result)  # noqa: E402
from engineering_flow.runtime import RuntimeProgressEvent  # noqa: E402


ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def plan_document():
    return {
        "command_result": "success",
        "command": "status",
        "workflow_id": "workflow-1111",
        "repository_path": "/repo",
        "provider": "codex-cli",
        "status": "awaiting_approval",
        "stage": "plan",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:01:00Z",
        "current_artifact_revision": 1,
        "lifecycle_version": "v2",
        "error_code": None,
        "artifacts": [{
            "id": "artifact-2222", "stage": "plan", "revision": 1,
            "path": "/repo/.engineering-flow/002-plan.json",
            "sha256": "a" * 64, "source_execution_id": "execution-3333",
            "approval_state": "pending", "created_at": "2026-01-01T00:01:00Z",
        }],
        "latest_execution": {
            "id": "execution-3333", "lifecycle": "succeeded",
            "failure_classification": None, "failure_detail": None,
        },
        "tasks": [],
        "active_task": None,
        "intake": {
            "outcome": "READY", "feature_contract_artifact_id": "feature-4444",
            "open_questions": [],
        },
        "plan": {
            "artifact_id": "artifact-2222", "sha256": "a" * 64,
            "revision": 1, "approval_state": "pending", "decision_reason": None,
            "plan": {
                "id": "workflow-1111:plan:r1", "workflow_id": "workflow-1111",
                "revision": 1,
                "feature_contract": {"artifact_id": "feature-4444", "sha256": "b" * 64},
                "strategy": "Make the smallest compatible CLI change.",
                "assumptions": ["The package metadata is available."],
                "verification_strategy": ["Run focused CLI tests.", "Run the full suite."],
                "tasks": [
                    {
                        "id": "T1", "objective": "Implement version CLI command",
                        "context": {"relevant_files": ["src/engineering_flow/cli.py"],
                                    "existing_patterns": ["Use argparse subcommands."]},
                        "requirements": ["Print the installed version."],
                        "acceptance_criteria": ["Version is printed."],
                        "verification": ["Run version command."], "constraints": ["Keep V1 compatible."],
                        "depends_on": [], "complexity": "low", "risk": "medium",
                    },
                    {
                        "id": "T2", "objective": "Add automated coverage",
                        "context": {"relevant_files": ["tests/test_cli.py"],
                                    "existing_patterns": ["Use unittest."]},
                        "requirements": ["Cover the new command."],
                        "acceptance_criteria": ["Tests pass."],
                        "verification": ["Run focused tests."], "constraints": [],
                        "depends_on": ["T1"], "complexity": "low", "risk": "low",
                    },
                ],
            },
        },
    }


class Tty(io.StringIO):
    def isatty(self):
        return True


class PresentationTests(unittest.TestCase):
    def test_plan_prompt_accepts_explicit_values_reprompts_and_leaves_eof_undecided(self):
        output = Tty()
        self.assertEqual(prompt_for_plan_decision(Tty("wat\nYES\n"), output, no_color=True), ("approve", None))
        self.assertIn("Please enter y or n.", output.getvalue())
        self.assertEqual(prompt_for_plan_decision(Tty("n\nToo broad.\n"), Tty(), no_color=True),
                         ("request_changes", "Too broad."))
        self.assertEqual(prompt_for_plan_decision(Tty("\n"), Tty(), no_color=True), ("approve", None))
        self.assertIsNone(prompt_for_plan_decision(Tty(""), Tty(), no_color=True))

    def test_tty_progress_updates_one_live_renderer_then_finalizes(self):
        output = Tty()
        instances = []

        class FakeLive:
            def __init__(self, renderable, **kwargs):
                self.renderables, self.started, self.stopped = [renderable], False, False
                instances.append(self)
            def start(self): self.started = True
            def update(self, renderable, **kwargs): self.renderables.append(renderable)
            def stop(self): self.stopped = True

        progress = ProgressRenderer(output, no_color=True, live_factory=FakeLive)
        progress(RuntimeProgressEvent("started", Stage.INTAKE, 0.0))
        progress(RuntimeProgressEvent("heartbeat", Stage.INTAKE, 10.0))
        progress(RuntimeProgressEvent("activity", Stage.INTAKE, 11.0, "provider prose"))
        progress(RuntimeProgressEvent("failed", Stage.INTAKE, 12.0))
        self.assertEqual(len(instances), 1)
        self.assertTrue(instances[0].started)
        self.assertTrue(instances[0].stopped)
        self.assertEqual(len(instances[0].renderables), 3)
        self.assertIn("INTAKE failed", output.getvalue())
        self.assertNotIn("provider prose", output.getvalue())

    def test_tty_progress_close_restores_live_renderer_after_interruption(self):
        output = Tty()
        instances = []

        class FakeLive:
            def __init__(self, *args, **kwargs):
                self.stopped = False
                instances.append(self)
            def start(self): pass
            def update(self, *args, **kwargs): pass
            def stop(self): self.stopped = True

        progress = ProgressRenderer(output, no_color=True, live_factory=FakeLive)
        progress(RuntimeProgressEvent("started", Stage.PLAN, 0.0))
        progress.close()
        self.assertEqual(len(instances), 1)
        self.assertTrue(instances[0].stopped)

    def test_stage_neutral_progress_uses_bounded_non_tty_lifecycle_lines(self):
        output = io.StringIO()
        progress = create_progress_renderer(output, environ={"TERM": "xterm-256color"})
        for stage in (Stage.INTAKE, Stage.PLAN):
            progress(RuntimeProgressEvent("started", stage, 0.0))
            progress(RuntimeProgressEvent("activity", stage, 1.0, "arbitrary provider prose"))
            progress(RuntimeProgressEvent("heartbeat", stage, 10.0))
            progress(RuntimeProgressEvent("heartbeat", stage, 20.0))
            progress(RuntimeProgressEvent("completed", stage, 21.5))
        text = output.getvalue()
        self.assertEqual(text.count("started"), 2)
        self.assertEqual(text.count("completed"), 2)
        self.assertIn("INTAKE", text)
        self.assertIn("PLAN", text)
        self.assertNotIn("arbitrary provider prose", text)
        self.assertNotRegex(text, r"\x1b\[|\r")

    def test_progress_terminal_failure_and_unknown_event_are_safe(self):
        output = io.StringIO()
        progress = create_progress_renderer(output, no_color=True)
        progress(RuntimeProgressEvent("started", Stage.INTAKE, 0.0))
        progress(RuntimeProgressEvent("unknown", Stage.INTAKE, 1.0, "secret stderr"))
        progress(RuntimeProgressEvent("timed_out", Stage.INTAKE, 3.25))
        self.assertEqual(output.getvalue(), "INTAKE started\nINTAKE timed out duration=3.2s\n")

    def test_default_plan_is_concise_and_omits_identity_and_full_contract_noise(self):
        output = io.StringIO()
        render_result(plan_document(), mode=OutputMode.HUMAN, stream=output)
        text = output.getvalue()
        for expected in (
            "Workflow", "PLAN", "AWAITING_APPROVAL", "Revision", "Tasks", "2", "PENDING",
            "T1", "Implement version CLI command", "low complexity", "medium risk",
            "T2", "Add automated coverage", "depends on T1",
        ):
            self.assertIn(expected, text)
        for hidden in (
            "workflow-1111", "artifact-2222", "a" * 64,
            "Make the smallest compatible CLI change.", "The package metadata is available.",
            "src/engineering_flow/cli.py", "Print the installed version.", "Version is printed.",
        ):
            self.assertNotIn(hidden, text)
        self.assertIsNone(ANSI.search(text))

    def test_verbose_includes_complete_safe_projection(self):
        output = io.StringIO()
        render_result(plan_document(), mode=OutputMode.VERBOSE, stream=output)
        text = output.getvalue()
        for expected in (
            "Verified projection", "workflow-1111", "artifact-2222", "execution-3333",
            "a" * 64, "Make the smallest compatible CLI change.",
            "The package metadata is available.", "Run the full suite.",
            "src/engineering_flow/cli.py", "Use argparse subcommands.",
            "Print the installed version.", "Version is printed.", "Keep V1 compatible.",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("raw provider", text.casefold())

    def test_json_is_one_plain_parseable_document(self):
        output = Tty()
        document = plan_document()
        render_result(document, mode=OutputMode.JSON, stream=output, environ={"TERM": "xterm-256color"})
        text = output.getvalue()
        self.assertEqual(len(text.splitlines()), 1)
        self.assertEqual(json.loads(text), document)
        self.assertIsNone(ANSI.search(text))

    def test_color_policy_and_narrow_terminal_remain_semantic(self):
        document = plan_document()
        colored = Tty()
        render_result(document, mode=OutputMode.HUMAN, stream=colored,
                      environ={"TERM": "xterm-256color"}, width=24)
        self.assertIsNotNone(ANSI.search(colored.getvalue()))
        self.assertIn("AWAITING_APPROVAL", ANSI.sub("", colored.getvalue()))

        cases = [
            ({"TERM": "xterm-256color"}, True),
            ({"TERM": "xterm-256color", "NO_COLOR": ""}, False),
            ({"TERM": "dumb"}, False),
        ]
        for environment, flag in cases:
            with self.subTest(environment=environment, no_color=flag):
                output = Tty()
                render_result(document, mode=OutputMode.HUMAN, stream=output,
                              no_color=flag, environ=environment, width=20)
                self.assertIsNone(ANSI.search(output.getvalue()))
                self.assertIn("PLAN", output.getvalue())


if __name__ == "__main__":
    unittest.main()
