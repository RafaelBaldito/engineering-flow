"""Small ordinary-process host for the bootstrap task execution loop."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .core import Controller
from .fingerprint import capture


@dataclass(frozen=True)
class RolePolicy:
    model: str
    reasoning: str
    sandbox: str = "workspace-write"


# Invocation-scoped bootstrap policy: never inherit Codex user defaults.
ROLE_POLICIES = {
    "Developer": RolePolicy("gpt-5.6-terra", "low"),
    "Reviewer": RolePolicy("gpt-5.6-terra", "medium"),
    "Fixer": RolePolicy("gpt-5.6-terra", "low"),
}


def approve_confirmed_human_gate(controller: Controller, actor: str) -> dict[str, Any]:
    """Adapt an already-confirmed human approval to the Controller handoff.

    The conversational Host calls this only after it has presented one known
    pending gate and received an unambiguous affirmative response.  No prose
    is interpreted here and no approval state is retained outside the control
    record.
    """
    return controller.approve_pending_human_gate(actor)


def report_confirmed_supervised_capability_completion(controller: Controller) -> dict[str, Any]:
    """Adapt an operator's explicit supervised-completion report to Controller state."""
    return controller.report_supervised_capability_completion()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def task_path(handoff: dict[str, Any]) -> str | None:
    task_id = handoff.get("task_id")
    return f"tasks/{handoff['wave_id']}/{task_id}.md" if task_id else None


def build_prompt(handoff: dict[str, Any]) -> str:
    """Only factual bounded handoff; repository Skills retain all workflow logic."""
    role, skill = handoff["required_role"], handoff["skill"]
    facts = [
        f"Role: {role}", f"Use the repository Skill: {skill}.",
        f"Wave: {handoff['wave_id']}", f"Task: {handoff.get('task_id')}",
        f"Task path: {task_path(handoff)}",
        f"Expected review artifact: {handoff.get('expected_authoritative_output_path')}",
        f"TECHSPEC path: docs/waves/{handoff['wave_id']}/TECHSPEC.md",
        "Authoritative input paths: " + ", ".join(ref["path"] for ref in handoff.get("authoritative_inputs", [])),
        f"Checkout fingerprint: {handoff['checkout_identity']['fingerprint']}",
        "Perform exactly this bounded role; do not dispatch another role or Wave Review.",
        'When finished, return exactly JSON: {"terminal_status":"COMPLETED"}.',
    ]
    return "\n".join(fact for fact in facts if not fact.endswith("None"))


def build_command(repo: Path, handoff: dict[str, Any], final_path: Path, schema_path: Path) -> list[str]:
    policy = ROLE_POLICIES[handoff["required_role"]]
    return ["codex", "exec", "--json", "--strict-config", "-m", policy.model,
            "-c", f'model_reasoning_effort="{policy.reasoning}"', "-C", str(repo),
            "-s", policy.sandbox, "--output-last-message", str(final_path),
            "--output-schema", str(schema_path), build_prompt(handoff)]


def _parse_jsonl(stdout: str) -> tuple[str | None, dict[str, Any] | None, str | None]:
    thread_id = None; completed = None
    try:
        for line in stdout.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("event is not an object")
            if event.get("type") == "thread.started": thread_id = event.get("thread_id")
            if event.get("type") == "turn.completed": completed = event
    except (json.JSONDecodeError, ValueError) as exc:
        return thread_id, completed, f"malformed JSONL: {exc}"
    return thread_id, completed, None


def _result(**facts: Any) -> dict[str, Any]:
    return facts


def run_codex(repo: Path, handoff: dict[str, Any], timeout: float = 900.0,
              popen: Callable[..., Any] = subprocess.Popen) -> dict[str, Any]:
    """Run one fresh `codex exec`; this deliberately has no resume path."""
    with tempfile.TemporaryDirectory(prefix="wave-codex-") as directory:
        temp = Path(directory); final_path = temp / "final.json"; schema_path = temp / "schema.json"
        schema_path.write_text(json.dumps({"type": "object", "properties": {"terminal_status": {"type": "string", "const": "COMPLETED"}}, "required": ["terminal_status"], "additionalProperties": False}))
        command = build_command(repo, handoff, final_path, schema_path)
        process = popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, start_new_session=True)
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                stdout, stderr = process.communicate()
        code = process.returncode
        thread_id, terminal, parse_error = _parse_jsonl(stdout or "")
        final_content = final_path.read_text(encoding="utf-8") if final_path.is_file() else None
        final_error = None
        if final_content is None: final_error = "missing final message"
        else:
            try:
                if json.loads(final_content).get("terminal_status") != "COMPLETED": final_error = "malformed final result"
            except (json.JSONDecodeError, AttributeError): final_error = "malformed final result"
        expected = handoff.get("expected_authoritative_output_path") or task_path(handoff)
        artifact_exists = not expected or (repo / expected).is_file()
        failure = ("timeout" if timed_out else "nonzero exit" if code else parse_error or
                   "missing terminal turn.completed event" if terminal is None else final_error or
                   "missing expected artifact" if not artifact_exists else None)
        return _result(ok=failure is None, failure=failure, command=command, exit_code=code,
                       thread_id=thread_id, terminal_event=terminal, usage=(terminal or {}).get("usage"),
                       final_message=final_content, timed_out=timed_out, stdout=stdout or "", stderr=stderr or "")


def _review_decision(path: Path) -> str | None:
    # The authoritative review record, not model prose, supplies the decision.
    import re
    values = re.findall(r"(?m)^\s*(PASS|FIX_REQUIRED|SPEC_CHANGE_REQUIRED|BLOCKED)\s*$", path.read_text(encoding="utf-8"))
    return values[-1] if values else None


def build_envelope(controller: Controller, acquired: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    handoff = acquired["handoff"]; role = handoff["required_role"]; state = controller.load(); active = state["active_operation"]
    artifacts: list[dict[str, Any]] = []; decision = None
    output = handoff.get("expected_authoritative_output_path")
    if role == "Reviewer" and output and (controller.root / output).is_file():
        path = controller.root / output
        artifacts = [{"path": output, "sha256": sha256(path.read_bytes()).hexdigest(), "purpose": "review"}]
        decision = _review_decision(path)
    terminal = decision if role == "Reviewer" and decision else ("COMPLETED" if execution["ok"] else "INTERRUPTED")
    return {"envelope_version": 1, "operation_id": acquired["operation_id"],
            "scope": {"wave_id": controller.wave_id, "task_id": active.get("task_id")}, "role": role,
            "attempt": 0, "child_task_name": "fresh-codex-exec", "thread_id": execution.get("thread_id"),
            "input_checkout_identity": active["input_identity"], "output_checkout_identity": capture(controller.root),
            "terminal_status": terminal, "authoritative_artifacts": artifacts,
            "validation": [{"codex_exit_code": execution["exit_code"], "jsonl_terminal": bool(execution["terminal_event"]), "failure": execution["failure"]}],
            "review_decision": decision, "recorded_at": _now()}


def run_task_loop(controller: Controller, timeout: float = 900.0,
                  runner: Callable[[Path, dict[str, Any], float], dict[str, Any]] = run_codex) -> dict[str, Any]:
    """Dispatch only Developer, Reviewer, and Fixer until the manual boundary."""
    history = []
    while True:
        action = controller.next()
        if action["status"] == "TASKS_READY_FOR_WAVE_REVIEW":
            return {"status": "TASKS_READY_FOR_WAVE_REVIEW", "wave_id": controller.wave_id, "history": history}
        if action.get("status") != "ACTION_REQUIRED" or action.get("role") not in ROLE_POLICIES:
            return {"status": action.get("status", "HUMAN_ATTENTION"), "wave_id": controller.wave_id, "history": history, "action": action}
        acquired = controller.begin_operation()
        if acquired.get("status") != "ACQUIRED":
            return {"status": acquired.get("status", "HUMAN_ATTENTION"), "wave_id": controller.wave_id, "history": history}
        execution = runner(controller.root, acquired["handoff"], timeout)
        envelope = build_envelope(controller, acquired, execution)
        completion = controller.complete_operation(envelope)
        history.append({"role": acquired["handoff"]["required_role"], "thread_id": execution.get("thread_id"), "execution": execution, "completion": completion})
        if not execution["ok"] or completion.get("status") == "HUMAN_ATTENTION":
            return {"status": "HUMAN_ATTENTION", "wave_id": controller.wave_id, "history": history, "reason": execution.get("failure")}
