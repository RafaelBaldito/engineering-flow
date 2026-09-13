from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.wave_controller.core import Controller
from tools.wave_controller.host import (ROLE_POLICIES, approve_confirmed_human_gate,
                                        build_command, build_prompt,
                                        report_confirmed_supervised_capability_completion,
                                        run_codex, run_task_loop, _stdout_event)


class _Process:
    def __init__(self, stdout, code=0, timeout=False):
        self.stdout, self.returncode, self.timeout, self.pid = stdout, code, timeout, 12345
    def communicate(self, timeout=None):
        if self.timeout:
            self.timeout = False
            raise subprocess.TimeoutExpired("codex", timeout)
        return self.stdout, "diagnostic"


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "host@test.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Host"], cwd=self.root, check=True)
        (self.root / "base").write_text("base\n")
        subprocess.run(["git", "add", "base"], cwd=self.root, check=True); subprocess.run(["git", "commit", "-qm", "base"], cwd=self.root, check=True)
        self.controller = Controller(self.root, "fixture"); self.controller.save(self.controller.initial("fixture", "Fixture"))

    def tearDown(self): self.temp.cleanup()

    def handoff(self, role="Developer"):
        return {"required_role": role, "skill": {"Developer":"execute-task", "Reviewer":"review-task", "Fixer":"fix-task"}[role],
                "wave_id":"fixture", "task_id":"TASK-A", "checkout_identity":{"fingerprint":"abc"},
                "expected_authoritative_output_path": "tasks/fixture/reviews/TASK-A-REVIEW.md" if role == "Reviewer" else None}

    def test_explicit_role_commands_and_fresh_invocations(self):
        dev = build_command(self.root, self.handoff("Developer"), Path("/tmp/final"), Path("/tmp/schema"))
        reviewer = build_command(self.root, self.handoff("Reviewer"), Path("/tmp/final"), Path("/tmp/schema"))
        fixer = build_command(self.root, self.handoff("Fixer"), Path("/tmp/final"), Path("/tmp/schema"))
        self.assertIn("gpt-5.6-terra", dev); self.assertIn('model_reasoning_effort="low"', dev)
        self.assertIn("gpt-5.6-terra", reviewer); self.assertIn('model_reasoning_effort="medium"', reviewer)
        self.assertEqual("codex", dev[0]); self.assertEqual("exec", dev[1]); self.assertNotIn("resume", reviewer)
        self.assertEqual("low", ROLE_POLICIES["Fixer"].reasoning)
        self.assertEqual(str(self.root), dev[dev.index("-C") + 1])
        self.assertIn("Use the repository Skill: review-task.", build_prompt(self.handoff("Reviewer")))
        for role in ("Developer", "Reviewer", "Fixer"):
            prompt = build_prompt(self.handoff(role))
            self.assertIn("TASKS.md and TASK-*.md are immutable", prompt)
            self.assertIn("must never edit task-plan status cells", prompt)

    def test_jsonl_success_and_fail_closed_cases(self):
        task = self.root / "tasks/fixture/TASK-A.md"; task.parent.mkdir(parents=True); task.write_text("task")
        output = '\n'.join([json.dumps({"type":"thread.started", "thread_id":"fresh"}), json.dumps({"type":"turn.completed", "usage":{"output_tokens":1}})])
        def successful(command, **kwargs):
            Path(command[command.index("--output-last-message") + 1]).write_text('{"terminal_status":"COMPLETED"}')
            return _Process(output)
        result = run_codex(self.root, self.handoff(), popen=successful)
        self.assertTrue(result["ok"]); self.assertEqual("fresh", result["thread_id"]); self.assertTrue(result["usage"])
        for name, process, final in (("exit", _Process(output, 1), True), ("terminal", _Process(json.dumps({"type":"thread.started"})), True), ("jsonl", _Process("nope"), True), ("artifact", _Process(output), True)):
            with self.subTest(name=name):
                if name == "artifact": task.unlink()
                def fake(command, **kwargs):
                    if final: Path(command[command.index("--output-last-message") + 1]).write_text('{"terminal_status":"COMPLETED"}')
                    return process
                self.assertFalse(run_codex(self.root, self.handoff(), popen=fake)["ok"])
                if name == "artifact": task.write_text("task")

    @patch("tools.wave_controller.host.os.killpg")
    def test_timeout_is_interrupted(self, killpg):
        def fake(command, **kwargs): return _Process("", timeout=True)
        result = run_codex(self.root, self.handoff(), timeout=.01, popen=fake)
        self.assertFalse(result["ok"]); self.assertTrue(result["timed_out"]); self.assertEqual("timeout", result["failure"])
        self.assertTrue(killpg.called)

    def test_heartbeat_is_safe_and_stdout_events_flush_immediately(self):
        task = self.root / "tasks/fixture/TASK-A.md"; task.parent.mkdir(parents=True); task.write_text("task")
        output = '\n'.join([json.dumps({"type":"thread.started", "thread_id":"fresh"}), json.dumps({"type":"turn.completed"})])
        events = []
        def delayed(command, **_):
            Path(command[command.index("--output-last-message") + 1]).write_text('{"terminal_status":"COMPLETED"}')
            return _Process(output, timeout=True)
        with patch("tools.wave_controller.host.time.monotonic", side_effect=[0, 0, 30, 30, 30, 30]):
            self.assertTrue(run_codex(self.root, self.handoff(), timeout=60, popen=delayed, event_sink=events.append)["ok"])
        self.assertEqual(["heartbeat"], [event["event"] for event in events])
        self.assertNotIn(output, json.dumps(events))
        with patch("builtins.print") as output_print:
            _stdout_event({"event": "task_started"})
        self.assertTrue(output_print.call_args.kwargs["flush"])

    def _ready(self):
        plan = self.root / "tasks/fixture/TASKS.md"; plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("## Execution Order\n| Task | Title | Depends On | Status |\n|---|---|---|---|\n| TASK-A | A | — | PENDING |\n| TASK-B | B | TASK-A | PENDING |\n")
        for task in ("TASK-A", "TASK-B"): (plan.parent / f"{task}.md").write_text(f"# {task}\n")
        ref = {"path":"tasks/fixture/TASKS.md", "sha256":hashlib.sha256(plan.read_bytes()).hexdigest(), "purpose":"approved"}
        state = self.controller.load(); state.update(lifecycle_state="TASK_EXECUTION_REQUIRED", human_gate={"status":"SATISFIED", "reason":"TASK_PLAN_APPROVAL", "evidence":[ref]})
        self.controller.save(state); self.controller.register_tasks()

    def test_loop_fix_cycle_next_task_terminal_and_no_wave_review(self):
        self._ready(); calls=[]; reviews=0
        before = (self.root / "tasks/fixture/TASKS.md").read_bytes()
        def fake(repo, handoff, timeout):
            nonlocal reviews
            calls.append(handoff["required_role"])
            if handoff["required_role"] == "Reviewer":
                reviews += 1; review = repo / handoff["expected_authoritative_output_path"]; review.parent.mkdir(parents=True, exist_ok=True)
                review.write_text("FIX_REQUIRED\n" if reviews == 2 else "PASS\n")
            return {"ok":True, "failure":None, "exit_code":0, "thread_id":f"fresh-{len(calls)}", "terminal_event":{"type":"turn.completed"}, "usage":{}, "final_message":"{}", "timed_out":False, "stdout":"", "stderr":""}
        outcome = run_task_loop(self.controller, runner=fake, event_sink=lambda _: None)
        self.assertEqual("TASKS_READY_FOR_WAVE_REVIEW", outcome["status"])
        self.assertEqual(["Developer", "Reviewer", "Developer", "Reviewer", "Fixer", "Reviewer"], calls)
        self.assertNotIn("Wave Reviewer", calls)
        self.assertEqual("TASKS_READY_FOR_WAVE_REVIEW", self.controller.load()["lifecycle_state"])
        self.assertEqual(before, (self.root / "tasks/fixture/TASKS.md").read_bytes())

    def test_runner_failures_clear_valid_lease_and_emit_only_safe_events(self):
        self._ready(); events = []
        raw = "provider reasoning and stderr secret"
        def failed(*_):
            return {"ok": False, "failure": "nonzero exit", "exit_code": 1, "thread_id": "thread",
                    "terminal_event": None, "timed_out": False, "stdout": raw, "stderr": raw}
        outcome = run_task_loop(self.controller, runner=failed, event_sink=events.append)
        self.assertEqual("HUMAN_ATTENTION", outcome["status"])
        self.assertIsNone(self.controller.load()["active_operation"])
        rendered = json.dumps(events)
        self.assertNotIn(raw, rendered)
        self.assertEqual(["task_started", "role_dispatched", "role_completed", "run_stopped"],
                         [item["event"] for item in events])

    def test_host_exception_clears_valid_lease_and_safe_output_flushes(self):
        self._ready(); events = []
        outcome = run_task_loop(self.controller, runner=lambda *_: (_ for _ in ()).throw(RuntimeError("raw boom")),
                                event_sink=events.append)
        self.assertEqual("HUMAN_ATTENTION", outcome["status"])
        self.assertIsNone(self.controller.load()["active_operation"])
        self.assertEqual("host exception", outcome["reason"])
        self.assertNotIn("raw boom", json.dumps(events))

    def test_authoritative_plan_drift_fails_closed_without_envelope_or_redispatch(self):
        self._ready(); events = []
        def drift(repo, *_):
            plan = repo / "tasks/fixture/TASKS.md"
            plan.write_text(plan.read_text().replace("PENDING", "IMPLEMENTED", 1))
            return {"ok": True, "failure": None, "exit_code": 0, "thread_id": "thread",
                    "terminal_event": {"type": "turn.completed"}, "timed_out": False, "stdout": "", "stderr": ""}
        outcome = run_task_loop(self.controller, runner=drift, event_sink=events.append)
        self.assertEqual("HUMAN_ATTENTION", outcome["status"])
        # The invalid authoritative input leaves the lease for the explicit
        # recovery protocol; it must not invent an interrupted envelope.
        state_text = self.controller.path.read_text()
        self.assertIn("TASK_IMPLEMENTATION", state_text)
        self.assertNotIn('"last_result_envelope": {', state_text)
        self.assertEqual("AUTHORITATIVE_INPUT_INVALID", events[-1]["reason"])

    def test_human_attention_stops_without_runner(self):
        self.controller.save({**self.controller.load(), "lifecycle_state":"HUMAN_ATTENTION"})
        self.assertEqual("HUMAN_ATTENTION", run_task_loop(self.controller, runner=lambda *_: self.fail("run"), event_sink=lambda _: None)["status"])

    def test_confirmed_human_adapter_only_forwards_the_explicit_signal_and_never_runs_tasks(self):
        with patch.object(self.controller, "approve_pending_human_gate", return_value={"status": "RECORDED"}) as approve:
            self.assertEqual("RECORDED", approve_confirmed_human_gate(self.controller, "human@example")["status"])
        approve.assert_called_once_with("human@example")
        self.assertIsNone(self.controller.load()["active_operation"])

    def test_supervised_completion_adapter_only_forwards_explicit_operator_report(self):
        with patch.object(self.controller, "report_supervised_capability_completion", return_value={"status": "COMPLETED"}) as report:
            self.assertEqual("COMPLETED", report_confirmed_supervised_capability_completion(self.controller)["status"])
        report.assert_called_once_with()
        self.assertIsNone(self.controller.load()["active_operation"])
