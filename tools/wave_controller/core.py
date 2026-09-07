"""Small, deterministic mechanics for one bootstrap Wave control record."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .fingerprint import capture

STATES = frozenset({
    "WAVE_AUTHORIZED", "TECHSPEC_REQUIRED", "TECHSPEC_EXECUTION", "AWAITING_TECHSPEC_APPROVAL",
    "TASK_PLAN_REQUIRED", "TASK_PLAN_EXECUTION", "AWAITING_TASK_PLAN_APPROVAL", "TASK_EXECUTION_REQUIRED",
    "TASK_IMPLEMENTATION", "TASK_REVIEW_REQUIRED", "TASK_REVIEW", "TASK_FIX_REQUIRED", "TASK_FIX",
    "TASKS_READY_FOR_WAVE_REVIEW", "WAVE_REVIEW_REQUIRED", "WAVE_REVIEW", "WAVE_REMEDIATION",
    "WAVE_ACCEPTED", "HUMAN_ATTENTION",
})
ROLES = frozenset({"Architect", "Planner", "Developer", "Reviewer", "Fixer", "Wave Reviewer", "Wave Remediator"})
TERMINAL = frozenset({"COMPLETED", "PASS", "FIX_REQUIRED", "BLOCKED", "SPEC_CHANGE_REQUIRED", "INTERRUPTED", "STALE", "INVALID"})
DISPATCH = {
    "TECHSPEC_REQUIRED": ("Architect", "technical-design", "create-techspec", "TECHSPEC_EXECUTION"),
    "TASK_PLAN_REQUIRED": ("Planner", "task-decomposition", "create-tasks", "TASK_PLAN_EXECUTION"),
    "TASK_EXECUTION_REQUIRED": ("Developer", "task-implementation", "execute-task", "TASK_IMPLEMENTATION"),
    "TASK_REVIEW_REQUIRED": ("Reviewer", "task-acceptance-review", "review-task", "TASK_REVIEW"),
    "TASK_FIX_REQUIRED": ("Fixer", "task-remediation", "fix-task", "TASK_FIX"),
    "WAVE_REVIEW_REQUIRED": ("Wave Reviewer", "wave-acceptance-review", "wave-review", "WAVE_REVIEW"),
    "WAVE_REMEDIATION": ("Wave Remediator", "wave-local-remediation", "fix-wave-review", "WAVE_REMEDIATION"),
}
GATES = {"AWAITING_TECHSPEC_APPROVAL": "TECHSPEC_APPROVAL", "AWAITING_TASK_PLAN_APPROVAL": "TASK_PLAN_APPROVAL"}
EXECUTION_ROLES = {"TECHSPEC_EXECUTION": "Architect", "TASK_PLAN_EXECUTION": "Planner", "TASK_IMPLEMENTATION": "Developer", "TASK_REVIEW": "Reviewer", "TASK_FIX": "Fixer", "WAVE_REVIEW": "Wave Reviewer", "WAVE_REMEDIATION": "Wave Remediator"}


class ControllerError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if root.resolve() not in candidate.parents and candidate != root.resolve():
        raise ControllerError("artifact path escapes repository")
    return candidate


class Controller:
    """Sole writer of one Wave's Markdown control record; never dispatches children."""

    def __init__(self, root: str | Path, wave_id: str):
        self.root = Path(root).resolve()
        self.wave_id = wave_id
        self.path = self.root / "docs" / "waves" / wave_id / "bootstrap" / "WAVE-WORKFLOW-STATE.md"

    @staticmethod
    def initial(wave_id: str, wave_name: str, state: str = "WAVE_AUTHORIZED") -> dict[str, Any]:
        return {
            "schema_version": 1, "workflow_id": f"bootstrap-{uuid.uuid4()}", "wave_id": wave_id,
            "wave_name": wave_name, "lifecycle_state": state, "current_task_id": None,
            "attempt": {"task_execution": 0, "task_review": 0, "task_fix": 0, "wave_review": 0},
            "last_completed_transition": None, "next_capability": None, "required_role": None,
            "human_gate": {"status": "NOT_APPLICABLE", "reason": "", "evidence": []},
            "authoritative_refs": [], "checkout_identity": None, "active_operation": None,
            "last_result_envelope": None, "blocker": {"classification": None, "reason": "", "required_human_action": None},
            "updated_at": _now(), "updated_by": "python-wave-controller", "tasks": [],
        }

    def load(self) -> dict[str, Any]:
        try:
            text = self.path.read_text(encoding="utf-8")
            start = text.index("```yaml") + len("```yaml")
            end = text.index("```", start)
            state = json.loads(text[start:end].strip())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ControllerError(f"invalid control record: {exc}") from exc
        self.validate(state)
        return state

    def validate(self, state: dict[str, Any]) -> None:
        required = {"schema_version", "workflow_id", "wave_id", "lifecycle_state", "attempt", "human_gate",
                    "authoritative_refs", "active_operation", "updated_at", "updated_by"}
        if not isinstance(state, dict) or required - state.keys() or state["schema_version"] != 1:
            raise ControllerError("state is missing required schema-v1 fields")
        if state["wave_id"] != self.wave_id or state["lifecycle_state"] not in STATES:
            raise ControllerError("state wave or lifecycle is invalid")
        if state["updated_by"] != "python-wave-controller" or not isinstance(state["attempt"], dict):
            raise ControllerError("state controller metadata is invalid")
        gate = state["human_gate"]
        if not isinstance(gate, dict) or gate.get("status") not in {"OPEN", "SATISFIED", "NOT_APPLICABLE"}:
            raise ControllerError("human gate is invalid")
        active = state["active_operation"]
        if active is not None and (not isinstance(active, dict) or not active.get("id") or not active.get("role")):
            raise ControllerError("active operation is invalid")
        if active is not None and active["role"] in ROLES and state["lifecycle_state"] in EXECUTION_ROLES and active["role"] != EXECUTION_ROLES[state["lifecycle_state"]]:
            raise ControllerError("active operation role does not match lifecycle state")
        self._validate_refs(state.get("authoritative_refs", []))
        if gate["status"] == "SATISFIED":
            if not gate.get("evidence"):
                raise ControllerError("satisfied human gate has no persisted authority")
            self._validate_refs(gate["evidence"])

    def _validate_refs(self, refs: list[dict[str, Any]]) -> None:
        seen: dict[str, str] = {}
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str):
                raise ControllerError("invalid authoritative artifact reference")
            if ref["path"] in seen and seen[ref["path"]] != ref["sha256"]:
                raise ControllerError("conflicting authoritative artifact references")
            seen[ref["path"]] = ref["sha256"]
            artifact = _inside(self.root, ref["path"])
            if not artifact.is_file() or _hash(artifact) != ref["sha256"]:
                raise ControllerError(f"authoritative artifact hash mismatch: {ref['path']}")

    def save(self, state: dict[str, Any], interrupt_before_replace: bool = False) -> None:
        self.validate(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "# Bootstrap Wave Workflow State\n\nTemporary deterministic bootstrap control record.\n\n```yaml\n"
        body += json.dumps(state, sort_keys=True, indent=2) + "\n```\n"
        fd, temporary = tempfile.mkstemp(prefix=".wave-state-", dir=self.path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(body); output.flush(); os.fsync(output.fileno())
            if interrupt_before_replace:
                raise InterruptedError("simulated interruption before atomic replace")
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def _persist(self, state: dict[str, Any], transition: str | None = None) -> None:
        state["updated_at"] = _now(); state["updated_by"] = "python-wave-controller"
        if transition: state["last_completed_transition"] = transition
        self.save(state)

    def _attention(self, state: dict[str, Any], reason: str) -> dict[str, Any]:
        state["lifecycle_state"] = "HUMAN_ATTENTION"; state["active_operation"] = None
        state["blocker"] = {"classification": "HUMAN_ATTENTION", "reason": reason, "required_human_action": reason}
        self._persist(state, "HUMAN_ATTENTION")
        return {"status": "HUMAN_ATTENTION", "wave_id": self.wave_id, "reason": reason}

    def status(self) -> dict[str, Any]:
        state = self.load()
        return {"status": "OK", "wave_id": self.wave_id, "state": state["lifecycle_state"], "active_operation": state["active_operation"]}

    def reconcile(self) -> dict[str, Any]:
        try: state = self.load()
        except ControllerError as exc: return {"status": "HUMAN_ATTENTION", "reason": str(exc)}
        active = state["active_operation"]
        if active and active.get("role") not in ROLES:
            return self._attention(state, "unknown or unresolved active writer")
        envelope = state.get("last_result_envelope")
        if active and envelope and envelope.get("operation_id") == active.get("id"):
            return self.complete_operation(envelope, reconciled=True)
        if active:
            return {"status": "BLOCKED", "wave_id": self.wave_id, "reason": "active operation requires resolved result"}
        return self.next()

    def _task_to_run(self, state: dict[str, Any]) -> str | None:
        passed = {t["id"] for t in state.get("tasks", []) if t.get("status") == "PASS"}
        for task in state.get("tasks", []):
            if task.get("status", "PENDING") == "PENDING" and set(task.get("dependencies", [])) <= passed:
                return task.get("id")
        return None

    def next(self) -> dict[str, Any]:
        try: state = self.load()
        except ControllerError as exc: return {"status": "HUMAN_ATTENTION", "reason": str(exc)}
        if state["active_operation"]:
            if state["active_operation"].get("role") not in ROLES: return {"status": "HUMAN_ATTENTION", "reason": "unknown active writer"}
            return {"status": "BLOCKED", "wave_id": self.wave_id, "reason": "operation is active"}
        lifecycle = state["lifecycle_state"]
        if lifecycle == "WAVE_AUTHORIZED":
            if state["human_gate"]["status"] != "SATISFIED": return {"status": "HUMAN_ACTION", "gate": "WAVE_START_AUTHORIZATION"}
            state["lifecycle_state"] = "TECHSPEC_REQUIRED"; self._persist(state, "WAVE_AUTHORIZED->TECHSPEC_REQUIRED"); lifecycle = "TECHSPEC_REQUIRED"
        if lifecycle in GATES:
            if state["human_gate"]["status"] != "SATISFIED": return {"status": "HUMAN_ACTION", "gate": GATES[lifecycle], "wave_id": self.wave_id}
            target = "TASK_PLAN_REQUIRED" if lifecycle == "AWAITING_TECHSPEC_APPROVAL" else "TASK_EXECUTION_REQUIRED"
            state["lifecycle_state"] = target; self._persist(state, f"{lifecycle}->{target}"); return self.next()
        if lifecycle == "TASK_EXECUTION_REQUIRED":
            task = self._task_to_run(state)
            if task is None:
                if state.get("tasks") and all(t.get("status") == "PASS" for t in state["tasks"]):
                    state["lifecycle_state"] = "TASKS_READY_FOR_WAVE_REVIEW"; self._persist(state, "TASK_EXECUTION_REQUIRED->TASKS_READY_FOR_WAVE_REVIEW"); return self.next()
                return {"status": "HUMAN_ATTENTION", "reason": "no dependency-ready task"}
            state["current_task_id"] = task
            return self._action(state, "Developer", "task-implementation", "execute-task", "TASK_IMPLEMENTATION")
        if lifecycle == "TASKS_READY_FOR_WAVE_REVIEW":
            state["lifecycle_state"] = "WAVE_REVIEW_REQUIRED"; self._persist(state, "TASKS_READY_FOR_WAVE_REVIEW->WAVE_REVIEW_REQUIRED"); return self.next()
        if lifecycle in DISPATCH:
            role, capability, skill, target = DISPATCH[lifecycle]
            return self._action(state, role, capability, skill, target)
        if lifecycle == "WAVE_ACCEPTED": return {"status": "WAVE_ACCEPTED", "wave_id": self.wave_id}
        return {"status": "HUMAN_ATTENTION", "wave_id": self.wave_id, "reason": state.get("blocker", {}).get("reason", "human attention required")}

    def _action(self, state: dict[str, Any], role: str, capability: str, skill: str, target: str) -> dict[str, Any]:
        identity = capture(self.root)
        refs = state.get("authoritative_refs", [])
        output = {"Architect": f"docs/waves/{self.wave_id}/TECHSPEC.md", "Planner": f"tasks/{self.wave_id}/TASKS.md",
                  "Reviewer": f"tasks/{self.wave_id}/reviews/{state.get('current_task_id', 'TASK')}-REVIEW.md",
                  "Wave Reviewer": f"docs/waves/{self.wave_id}/WAVE-REVIEW.md"}.get(role)
        handoff = {"wave_id": self.wave_id, "task_id": state.get("current_task_id"), "required_role": role,
            "required_capability": capability, "skill": skill, "authoritative_inputs": refs,
            "checkout_identity": identity, "required_validation": [], "expected_authoritative_output_path": output,
            "fork_turns": "none", "intended_model": "Terra", "intended_reasoning_tier": "high" if role in {"Architect", "Planner", "Reviewer", "Wave Reviewer"} else "medium"}
        return {"status": "ACTION_REQUIRED", "wave_id": self.wave_id, "state": state["lifecycle_state"], "action": "RUN_CAPABILITY", "role": role, "capability": capability, "handoff": handoff}

    def begin_operation(self, operation_id: str | None = None, child_task_name: str | None = None) -> dict[str, Any]:
        existing = self.load().get("active_operation")
        if existing:
            return {"status": "REJECT", "reason": "known active writer"} if existing.get("role") in ROLES else {"status": "BLOCKED", "reason": "unknown active writer"}
        action = self.next()
        if action["status"] != "ACTION_REQUIRED": return action
        state = self.load()
        op_id = operation_id or str(uuid.uuid4())
        state["checkout_identity"] = action["handoff"]["checkout_identity"]
        state["active_operation"] = {"id": op_id, "role": action["role"], "child_task_name": child_task_name,
            "task_id": state.get("current_task_id"), "input_identity": state["checkout_identity"], "dispatched_at": _now()}
        state["lifecycle_state"] = DISPATCH.get(state["lifecycle_state"], (None, None, None, state["lifecycle_state"]))[3]
        self._persist(state, f"BEGIN:{op_id}")
        action["handoff"]["operation_id"] = op_id
        return {"status": "ACQUIRED", "operation_id": op_id, "handoff": action["handoff"]}

    def _validate_envelope(self, state: dict[str, Any], envelope: dict[str, Any]) -> str | None:
        active = state.get("active_operation")
        needed = {"envelope_version", "operation_id", "scope", "role", "attempt", "input_checkout_identity", "output_checkout_identity", "terminal_status", "authoritative_artifacts", "validation", "review_decision", "recorded_at"}
        if not isinstance(envelope, dict) or needed - envelope.keys() or envelope["envelope_version"] != 1: return "required envelope fields are missing"
        if not active or envelope["operation_id"] != active["id"] or envelope["role"] != active["role"]: return "operation identity does not match active operation"
        if envelope["scope"].get("wave_id") != self.wave_id or envelope["scope"].get("task_id") != active.get("task_id"): return "envelope scope does not match"
        if envelope["terminal_status"] not in TERMINAL or envelope["input_checkout_identity"].get("fingerprint") != active["input_identity"].get("fingerprint"): return "terminal status or input identity is invalid"
        if envelope["output_checkout_identity"].get("fingerprint") != capture(self.root).get("fingerprint"): return "STALE"
        try: self._validate_refs(envelope["authoritative_artifacts"])
        except ControllerError as exc: return str(exc)
        if active["role"] in {"Reviewer", "Wave Reviewer"} and envelope["review_decision"] not in {"PASS", "FIX_REQUIRED", "SPEC_CHANGE_REQUIRED", "BLOCKED"}: return "review decision is invalid"
        if active["role"] in {"Reviewer", "Wave Reviewer"} and envelope["terminal_status"] != envelope["review_decision"]: return "review terminal status does not match decision"
        if active["role"] not in {"Reviewer", "Wave Reviewer"} and envelope["terminal_status"] != "COMPLETED": return "writer terminal status must be COMPLETED"
        return None

    def complete_operation(self, envelope: dict[str, Any], reconciled: bool = False) -> dict[str, Any]:
        state = self.load(); error = self._validate_envelope(state, envelope)
        if error:
            envelope = dict(envelope); envelope["terminal_status"] = "STALE" if error == "STALE" else "INVALID"
            state["last_result_envelope"] = envelope
            return self._attention(state, "stale result" if error == "STALE" else f"invalid result envelope: {error}")
        role, decision = state["active_operation"]["role"], envelope["terminal_status"]
        state["last_result_envelope"] = envelope; state["active_operation"] = None
        if decision in {"BLOCKED", "SPEC_CHANGE_REQUIRED", "INTERRUPTED", "STALE", "INVALID"}:
            return self._attention(state, f"operation ended {decision}")
        if role == "Architect": state["lifecycle_state"] = "AWAITING_TECHSPEC_APPROVAL"; state["human_gate"] = {"status":"OPEN", "reason":"TECHSPEC_APPROVAL", "evidence":[]}
        elif role == "Planner": state["lifecycle_state"] = "AWAITING_TASK_PLAN_APPROVAL"; state["human_gate"] = {"status":"OPEN", "reason":"TASK_PLAN_APPROVAL", "evidence":[]}
        elif role == "Developer": state["lifecycle_state"] = "TASK_REVIEW_REQUIRED"; state["attempt"]["task_execution"] += 1
        elif role == "Fixer": state["lifecycle_state"] = "TASK_REVIEW_REQUIRED"; state["attempt"]["task_fix"] += 1
        elif role == "Reviewer":
            state["attempt"]["task_review"] += 1
            if envelope["review_decision"] == "PASS":
                for task in state.get("tasks", []):
                    if task.get("id") == state.get("current_task_id"): task["status"] = "PASS"
                state["lifecycle_state"] = "TASK_EXECUTION_REQUIRED"
            elif envelope["review_decision"] == "FIX_REQUIRED": state["lifecycle_state"] = "TASK_FIX_REQUIRED"
            else: return self._attention(state, "review requires human attention")
        elif role == "Wave Reviewer":
            state["attempt"]["wave_review"] += 1
            if envelope["review_decision"] == "PASS": state["lifecycle_state"] = "WAVE_ACCEPTED"
            elif envelope["review_decision"] == "FIX_REQUIRED": state["lifecycle_state"] = "WAVE_REMEDIATION"
            else: return self._attention(state, "wave review requires human attention")
        elif role == "Wave Remediator": state["lifecycle_state"] = "WAVE_REVIEW_REQUIRED"
        self._persist(state, f"COMPLETE:{envelope['operation_id']}")
        return {"status": "RECONCILED" if reconciled else "COMPLETED", "wave_id": self.wave_id, "state": state["lifecycle_state"]}
