"""Small, deterministic mechanics for one bootstrap Wave control record."""

from __future__ import annotations

import hashlib
import json
import os
import re
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
APPROVAL_GATES = frozenset({"TECHSPEC_APPROVAL", "TASK_PLAN_APPROVAL"})
EXECUTION_ROLES = {"TECHSPEC_EXECUTION": "Architect", "TASK_PLAN_EXECUTION": "Planner", "TASK_IMPLEMENTATION": "Developer", "TASK_REVIEW": "Reviewer", "TASK_FIX": "Fixer", "WAVE_REVIEW": "Wave Reviewer", "WAVE_REMEDIATION": "Wave Remediator"}
TASK_ID = re.compile(r"TASK-[A-Za-z0-9][A-Za-z0-9_-]*$")


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
            # Append-only bootstrap governance evidence.  Old schema-v1 records
            # without this field are interpreted through their human_gate below.
            "governance_decisions": [],
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
        decisions = state.get("governance_decisions", [])
        if not isinstance(decisions, list) or any(not isinstance(item, dict) for item in decisions):
            raise ControllerError("governance decision history is invalid")

    def _approval_target(self, gate: str) -> str:
        if gate == "TECHSPEC_APPROVAL":
            return f"docs/waves/{self.wave_id}/TECHSPEC.md"
        if gate == "TASK_PLAN_APPROVAL":
            return self._task_plan_path()
        raise ControllerError("approval gate is invalid")

    def _decision_id(self, operation: str, gate: str, actor: str, evidence: list[dict[str, Any]], target: str | None) -> str:
        payload = json.dumps({"operation": operation, "gate": gate, "wave_id": self.wave_id,
                              "actor": actor, "evidence": evidence, "target": target}, sort_keys=True,
                             separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def _active_approval(self, state: dict[str, Any], gate: str) -> dict[str, Any]:
        """Resolve exactly one current, exact-revision approval or fail closed."""
        if gate not in APPROVAL_GATES:
            raise ControllerError("approval gate is invalid")
        target = self._approval_target(gate)
        decisions = state.get("governance_decisions", [])
        # Legacy v1 state is read-compatible; it represents one approval fact.
        if not decisions:
            legacy = state.get("human_gate", {})
            if legacy.get("status") == "SATISFIED" and legacy.get("reason") == gate and legacy.get("decision", "APPROVE") == "APPROVE":
                decisions = [{"id": "legacy-human-gate", "operation": "APPROVE", "gate": gate,
                              "wave_id": self.wave_id, "evidence": legacy.get("evidence", [])}]
        by_id = {item.get("id"): item for item in decisions if item.get("id")}
        candidates = [item for item in decisions if item.get("operation") == "APPROVE"
                      and item.get("gate") == gate and item.get("wave_id") == self.wave_id]
        inactive: set[str] = set()
        for item in decisions:
            if item.get("operation") == "REVOKE" and item.get("gate") == gate and item.get("target") in by_id:
                inactive.add(item["target"])
            if item.get("operation") == "SUPERSEDE" and item.get("gate") == gate and item.get("target") in by_id:
                replacement = by_id.get(item.get("replacement"))
                if replacement and replacement.get("operation") == "APPROVE" and replacement.get("gate") == gate:
                    inactive.add(item["target"])
                else:
                    raise ControllerError("ambiguous supersession lineage")
        active = [item for item in candidates if item.get("id") not in inactive]
        if len(active) != 1:
            raise ControllerError("approval lineage is missing or ambiguous")
        approval = active[0]
        evidence = approval.get("evidence")
        if not isinstance(evidence, list):
            raise ControllerError("approval lineage has invalid evidence")
        self._validate_refs(evidence)
        digest = _hash(_inside(self.root, target)) if _inside(self.root, target).is_file() else None
        matching = [ref for ref in evidence if ref.get("path") == target and ref.get("sha256") == digest]
        if len(matching) != 1:
            raise ControllerError("approval does not bind the current authoritative artifact")
        return approval

    def _require_active_approval(self, state: dict[str, Any], gate: str) -> None:
        self._active_approval(state, gate)

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
        try:
            repaired = self._reconcile_task_statuses(state)
        except ControllerError as exc:
            return self._attention(state, str(exc))
        if repaired:
            self._persist(state, "RECONCILE_TASK_STATUS")
        active = state["active_operation"]
        if active and active.get("role") not in ROLES:
            return self._attention(state, "unknown or unresolved active writer")
        envelope = state.get("last_result_envelope")
        if active and envelope and envelope.get("operation_id") == active.get("id"):
            return self.complete_operation(envelope, reconciled=True)
        if active:
            return {"status": "BLOCKED", "wave_id": self.wave_id, "reason": "active operation requires resolved result"}
        return self.next()

    def _accepted_review_receipt(self, task_id: str, envelope: dict[str, Any]) -> dict[str, Any]:
        """Retain only Controller-validated facts needed to recover a task PASS."""
        return {
            "task_id": task_id, "operation_id": envelope["operation_id"],
            "role": envelope["role"], "review_decision": envelope["review_decision"],
            "authoritative_artifacts": envelope["authoritative_artifacts"],
            "recorded_at": envelope["recorded_at"],
        }

    def _reconcile_task_statuses(self, state: dict[str, Any]) -> bool:
        """Restore only status lost after a Controller-accepted task review PASS.

        A review file by itself is deliberately insufficient: the receipt is
        created solely after ``_validate_envelope`` accepted the matching
        Reviewer PASS against its active lease.
        """
        repaired = False
        for task in state.get("tasks", []):
            receipt = task.get("accepted_review")
            if receipt is None:
                continue
            expected = f"tasks/{self.wave_id}/reviews/{task.get('id')}-REVIEW.md"
            if (not isinstance(receipt, dict) or receipt.get("task_id") != task.get("id")
                    or not isinstance(receipt.get("operation_id"), str)
                    or receipt.get("role") != "Reviewer" or receipt.get("review_decision") != "PASS"
                    or not isinstance(receipt.get("recorded_at"), str)):
                raise ControllerError(f"ambiguous accepted review receipt for {task.get('id')}")
            artifacts = receipt.get("authoritative_artifacts")
            if not isinstance(artifacts, list):
                raise ControllerError(f"ambiguous accepted review receipt for {task.get('id')}")
            self._validate_refs(artifacts)
            if expected not in {ref.get("path") for ref in artifacts}:
                raise ControllerError(f"accepted review receipt lacks required artifact for {task.get('id')}")
            if task.get("status") == "PENDING":
                task["status"] = "PASS"
                repaired = True
            elif task.get("status") != "PASS":
                raise ControllerError(f"ambiguous task status for accepted review: {task.get('id')}")
        return repaired

    def _wave_review_task_evidence(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the factual task-acceptance manifest for a Wave Reviewer.

        TASKS.md is the immutable approved plan.  The Controller receipt and
        task record are the runtime acceptance authority, so a planning-time
        PENDING cell cannot be interpreted as a current task status.
        """
        task_plan = state.get("task_plan")
        if not isinstance(task_plan, dict) or not isinstance(task_plan.get("path"), str):
            raise ControllerError("Wave Review lacks registered approved task plan")
        plan_path = _inside(self.root, task_plan["path"])
        if not plan_path.is_file() or _hash(plan_path) != task_plan.get("sha256"):
            raise ControllerError("registered approved task plan hash mismatch")
        planned_tasks = self._parse_task_plan(plan_path)
        runtime_tasks = state.get("tasks", [])
        if (len(planned_tasks) != len(runtime_tasks)
                or any(plan.get("id") != runtime.get("id")
                       or plan.get("dependencies") != runtime.get("dependencies")
                       for plan, runtime in zip(planned_tasks, runtime_tasks))):
            raise ControllerError("approved task plan and Controller task index disagree")
        evidence = []
        for position, task in enumerate(runtime_tasks, start=1):
            task_id = task["id"]
            receipt = task.get("accepted_review")
            expected = f"tasks/{self.wave_id}/reviews/{task_id}-REVIEW.md"
            if task.get("status") != "PASS":
                raise ControllerError(f"Controller runtime status is not accepted for {task_id}")
            if (not isinstance(receipt, dict) or receipt.get("task_id") != task_id
                    or not isinstance(receipt.get("operation_id"), str)
                    or receipt.get("role") != "Reviewer" or receipt.get("review_decision") != "PASS"
                    or not isinstance(receipt.get("recorded_at"), str)):
                raise ControllerError(f"authoritative task review is missing or inconsistent for {task_id}")
            artifacts = receipt.get("authoritative_artifacts")
            if not isinstance(artifacts, list):
                raise ControllerError(f"authoritative task review is missing or inconsistent for {task_id}")
            self._validate_refs(artifacts)
            artifact = next((ref for ref in artifacts if ref.get("path") == expected), None)
            if artifact is None:
                raise ControllerError(f"authoritative task review has wrong identity for {task_id}")
            evidence.append({
                "task_id": task_id,
                "task_plan_position": position,
                "task_plan_source": {"path": task_plan["path"], "sha256": task_plan["sha256"]},
                "controller_runtime_status": "accepted",
                "authoritative_review_artifact": artifact,
                "authoritative_review_decision": "PASS",
            })
        return evidence

    def _open_gate(self, state: dict[str, Any]) -> str | None:
        if state["lifecycle_state"] == "WAVE_AUTHORIZED":
            return "WAVE_START_AUTHORIZATION"
        return GATES.get(state["lifecycle_state"])

    def _record_decision(self, operation: str, gate: str, actor: str, evidence: list[dict[str, Any]],
                         authority_wave_id: str | None, target: str | None = None) -> dict[str, Any]:
        state = self.load()
        if authority_wave_id != self.wave_id:
            raise ControllerError("authority wave does not match controller wave")
        if not isinstance(actor, str) or not actor.strip():
            raise ControllerError("authority actor is required")
        if operation in {"APPROVE", "AUTHORIZE", "SUPERSEDE"} and (not isinstance(evidence, list) or not evidence):
            raise ControllerError("authority evidence is required")
        evidence = evidence or []
        self._validate_refs(evidence)
        prior = [item for item in state.get("governance_decisions", [])
                 if item.get("operation") == operation and item.get("gate") == gate
                 and item.get("actor") == actor and item.get("evidence") == evidence and item.get("target") == target]
        if prior:
            return {"status": "IDEMPOTENT", "wave_id": self.wave_id, "gate": gate, "decision_id": prior[0]["id"]}
        if operation == "AUTHORIZE":
            if gate != "WAVE_START_AUTHORIZATION" or self._open_gate(state) != gate:
                raise ControllerError("authorization gate is not currently open")
        elif operation == "APPROVE":
            if gate not in APPROVAL_GATES or self._open_gate(state) != gate:
                raise ControllerError("approval gate is not currently open")
            expected = self._approval_target(gate)
            if not any(ref.get("path") == expected for ref in evidence):
                raise ControllerError("approval evidence has wrong authoritative artifact path")
        elif operation in {"REVOKE", "SUPERSEDE"}:
            if gate not in APPROVAL_GATES or not target:
                raise ControllerError("revocation or supersession target is required")
            old = next((item for item in state.get("governance_decisions", []) if item.get("id") == target), None)
            if not old or old.get("operation") != "APPROVE" or old.get("gate") != gate:
                raise ControllerError("governance target is invalid")
            if operation == "SUPERSEDE":
                expected = self._approval_target(gate)
                if not any(ref.get("path") == expected for ref in evidence):
                    raise ControllerError("superseding approval has wrong authoritative artifact path")
        else:
            raise ControllerError("governance operation is unsupported")
        identifier = self._decision_id(operation, gate, actor, evidence, target)
        history = state.setdefault("governance_decisions", [])
        existing = next((item for item in history if item.get("id") == identifier), None)
        if existing:
            return {"status": "IDEMPOTENT", "wave_id": self.wave_id, "gate": gate, "decision_id": identifier}
        record = {"id": identifier, "operation": operation, "gate": gate, "wave_id": self.wave_id,
                  "actor": actor, "evidence": evidence, "target": target, "recorded_at": _now()}
        if operation == "SUPERSEDE":
            replacement_id = self._decision_id("APPROVE", gate, actor, evidence, identifier)
            record["replacement"] = replacement_id
            history.append({"id": replacement_id, "operation": "APPROVE", "gate": gate, "wave_id": self.wave_id,
                            "actor": actor, "evidence": evidence, "supersedes": target, "recorded_at": _now()})
        history.append(record)
        if operation in {"AUTHORIZE", "APPROVE"}:
            state["human_gate"] = {"status": "SATISFIED", "reason": gate, "decision": operation,
                                   "actor": actor, "recorded_at": _now(), "evidence": evidence}
            if gate == "TASK_PLAN_APPROVAL":
                state["lifecycle_state"] = "TASK_EXECUTION_REQUIRED"
        elif operation == "REVOKE":
            state["human_gate"] = {"status": "NOT_APPLICABLE", "reason": "", "evidence": []}
        self._persist(state, f"GOVERNANCE:{operation}:{gate}")
        return {"status": "RECORDED", "wave_id": self.wave_id, "gate": gate, "decision_id": identifier}

    def approve(self, gate: str, actor: str, evidence: list[dict[str, Any]], authority_wave_id: str | None = None) -> dict[str, Any]:
        return self._record_decision("APPROVE", gate, actor, evidence, authority_wave_id)

    def authorize(self, gate: str, actor: str, evidence: list[dict[str, Any]], authority_wave_id: str | None = None) -> dict[str, Any]:
        return self._record_decision("AUTHORIZE", gate, actor, evidence, authority_wave_id)

    def revoke(self, gate: str, actor: str, target: str, authority_wave_id: str | None = None) -> dict[str, Any]:
        return self._record_decision("REVOKE", gate, actor, [], authority_wave_id, target)

    def supersede(self, gate: str, actor: str, evidence: list[dict[str, Any]], target: str,
                  authority_wave_id: str | None = None) -> dict[str, Any]:
        return self._record_decision("SUPERSEDE", gate, actor, evidence, authority_wave_id, target)

    def record_authority(self, gate: str, decision: str, actor: str, evidence: list[dict[str, Any]], authority_wave_id: str | None = None) -> dict[str, Any]:
        """Compatibility shim; typed public operations are the semantic API."""
        if decision == "APPROVE":
            if gate == "WAVE_START_AUTHORIZATION":
                return self.authorize(gate, actor, evidence, authority_wave_id)
            return self.approve(gate, actor, evidence, authority_wave_id)
        if decision == "AUTHORIZE":
            return self.authorize(gate, actor, evidence, authority_wave_id)
        raise ControllerError("authority decision is unsupported; use typed governance operation")

    def _task_plan_path(self) -> str:
        return f"tasks/{self.wave_id}/TASKS.md"

    def _parse_task_plan(self, path: Path) -> list[dict[str, Any]]:
        """Parse only the canonical TASKS.md Execution Order table."""
        lines = path.read_text(encoding="utf-8").splitlines()
        try:
            start = next(index for index, line in enumerate(lines) if line.strip() == "## Execution Order")
        except StopIteration as exc:
            raise ControllerError("TASKS.md has no Execution Order section") from exc
        index = start + 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines) or [part.strip() for part in lines[index].strip().strip("|").split("|")] != ["Task", "Title", "Depends On", "Status"]:
            raise ControllerError("TASKS.md Execution Order header is invalid")
        index += 1
        if index >= len(lines) or not re.fullmatch(r"\s*\|\s*:?-{3,}:?\s*\|\s*:?-{3,}:?\s*\|\s*:?-{3,}:?\s*\|\s*:?-{3,}:?\s*\|\s*", lines[index]):
            raise ControllerError("TASKS.md Execution Order separator is invalid")
        index += 1
        tasks: list[dict[str, Any]] = []
        while index < len(lines) and lines[index].strip().startswith("|"):
            fields = [part.strip() for part in lines[index].strip().strip("|").split("|")]
            if len(fields) != 4:
                raise ControllerError("TASKS.md Execution Order row is malformed")
            task_id, title, dependencies, status = fields
            if not TASK_ID.fullmatch(task_id) or not title or status != "PENDING":
                raise ControllerError("TASKS.md task identifier, title, or initial status is invalid")
            dependency_ids = [] if dependencies == "—" else [item.strip() for item in dependencies.split(",")]
            if (not all(TASK_ID.fullmatch(item) for item in dependency_ids)
                    or len(dependency_ids) != len(set(dependency_ids))):
                raise ControllerError("TASKS.md task dependencies are invalid")
            tasks.append({"id": task_id, "status": "PENDING", "dependencies": dependency_ids})
            index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index < len(lines) and not lines[index].startswith("#"):
            raise ControllerError("TASKS.md Execution Order rows are malformed")
        if not tasks:
            raise ControllerError("TASKS.md Execution Order is empty")
        identifiers = [task["id"] for task in tasks]
        if len(identifiers) != len(set(identifiers)):
            raise ControllerError("TASKS.md has duplicate task identifiers")
        known = set(identifiers)
        if any(task["id"] in task["dependencies"] or not set(task["dependencies"]) <= known for task in tasks):
            raise ControllerError("TASKS.md has unknown or self-referential dependencies")
        return tasks

    def register_tasks(self) -> dict[str, Any]:
        """Explicitly register the exact approved TASKS.md task identity/order."""
        state = self.load()
        if state["lifecycle_state"] != "TASK_EXECUTION_REQUIRED" or state.get("active_operation"):
            raise ControllerError("task registration is not permitted in the current lifecycle state")
        try:
            self._require_active_approval(state, "TASK_PLAN_APPROVAL")
        except ControllerError as exc:
            raise ControllerError(f"approved task plan authority is required before registration: {exc}") from exc
        relative_path = self._task_plan_path()
        plan = _inside(self.root, relative_path)
        if not plan.is_file():
            raise ControllerError("approved TASKS.md is missing")
        digest = _hash(plan)
        tasks = self._parse_task_plan(plan)
        registration = {"path": relative_path, "sha256": digest}
        existing = state.get("task_plan")
        if existing:
            if existing == registration and state.get("tasks") == tasks:
                return {"status": "IDEMPOTENT", "wave_id": self.wave_id, "task_count": len(tasks)}
            raise ControllerError("conflicting task-set registration")
        if state.get("tasks"):
            raise ControllerError("task-set registration already has conflicting persisted tasks")
        state["tasks"] = tasks
        state["task_plan"] = registration
        self._persist(state, "REGISTER_TASKS")
        return {"status": "REGISTERED", "wave_id": self.wave_id, "task_count": len(tasks)}

    def _task_to_run(self, state: dict[str, Any]) -> str | None:
        current = state.get("current_task_id")
        if current:
            for task in state.get("tasks", []):
                if task.get("id") == current and task.get("status", "PENDING") == "PENDING":
                    passed = {t["id"] for t in state.get("tasks", []) if t.get("status") == "PASS"}
                    if set(task.get("dependencies", [])) <= passed:
                        return current
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
            authorizations = [item for item in state.get("governance_decisions", [])
                              if item.get("operation") == "AUTHORIZE" and item.get("gate") == "WAVE_START_AUTHORIZATION"
                              and item.get("wave_id") == self.wave_id]
            legacy = state["human_gate"]
            if not authorizations and not (legacy.get("status") == "SATISFIED" and legacy.get("reason") == "WAVE_START_AUTHORIZATION"):
                return {"status": "HUMAN_ACTION", "gate": "WAVE_START_AUTHORIZATION"}
            if len(authorizations) > 1:
                return self._attention(state, "wave-start authorization is ambiguous")
            state["lifecycle_state"] = "TECHSPEC_REQUIRED"; self._persist(state, "WAVE_AUTHORIZED->TECHSPEC_REQUIRED"); lifecycle = "TECHSPEC_REQUIRED"
        if lifecycle in GATES:
            gate = GATES[lifecycle]
            try:
                self._require_active_approval(state, gate)
            except ControllerError as exc:
                if state["human_gate"].get("status") != "SATISFIED":
                    return {"status": "HUMAN_ACTION", "gate": gate, "wave_id": self.wave_id}
                return self._attention(state, str(exc))
            target = "TASK_PLAN_REQUIRED" if lifecycle == "AWAITING_TECHSPEC_APPROVAL" else "TASK_EXECUTION_REQUIRED"
            state["lifecycle_state"] = target; self._persist(state, f"{lifecycle}->{target}"); return self.next()
        if lifecycle == "TASK_PLAN_REQUIRED":
            try: self._require_active_approval(state, "TECHSPEC_APPROVAL")
            except ControllerError as exc: return self._attention(state, str(exc))
        if lifecycle == "TASK_EXECUTION_REQUIRED":
            try: self._require_active_approval(state, "TASK_PLAN_APPROVAL")
            except ControllerError as exc: return self._attention(state, str(exc))
            task = self._task_to_run(state)
            if task is None:
                if state.get("tasks") and all(t.get("status") == "PASS" for t in state["tasks"]):
                    state["lifecycle_state"] = "TASKS_READY_FOR_WAVE_REVIEW"; self._persist(state, "TASK_EXECUTION_REQUIRED->TASKS_READY_FOR_WAVE_REVIEW"); return self.next()
                return {"status": "HUMAN_ATTENTION", "reason": "no dependency-ready task"}
            if state.get("current_task_id") != task:
                state["current_task_id"] = task
                # Selection is a deterministic workflow fact, not Host memory.
                self._persist(state, f"SELECT_TASK:{task}")
            return self._action(state, "Developer", "task-implementation", "execute-task", "TASK_IMPLEMENTATION")
        if lifecycle == "TASKS_READY_FOR_WAVE_REVIEW":
            # The Codex host owns only the post-task-plan loop.  Wave Review
            # remains a separately invoked, manual lifecycle action.
            return {"status": "TASKS_READY_FOR_WAVE_REVIEW", "wave_id": self.wave_id,
                    "state": lifecycle}
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
        if role in {"Reviewer", "Wave Reviewer"}:
            handoff["allowed_output_paths"] = [output]
            # Review validation must leave the checkout unchanged except for
            # the authoritative review artifact. The Host applies this only
            # to Python validation for these read-mostly roles.
            handoff["validation_environment"] = {"PYTHONDONTWRITEBYTECODE": "1"}
        if role == "Wave Reviewer":
            try:
                handoff["task_acceptance_evidence"] = self._wave_review_task_evidence(state)
            except ControllerError as exc:
                return self._attention(state, str(exc))
        return {"status": "ACTION_REQUIRED", "wave_id": self.wave_id, "state": state["lifecycle_state"], "action": "RUN_CAPABILITY", "role": role, "capability": capability, "handoff": handoff}

    def begin_operation(self, operation_id: str | None = None, child_task_name: str | None = None) -> dict[str, Any]:
        existing = self.load().get("active_operation")
        if existing:
            return {"status": "REJECT", "reason": "known active writer"} if existing.get("role") in ROLES else {"status": "BLOCKED", "reason": "unknown active writer"}
        action = self.next()
        if action["status"] != "ACTION_REQUIRED": return action
        state = self.load()
        # Recheck the proposition after next() and immediately before the
        # writer lease is persisted; a prior handoff is never authority.
        try:
            if action["role"] == "Planner": self._require_active_approval(state, "TECHSPEC_APPROVAL")
            if action["role"] == "Developer": self._require_active_approval(state, "TASK_PLAN_APPROVAL")
        except ControllerError as exc:
            return self._attention(state, str(exc))
        op_id = operation_id or str(uuid.uuid4())
        state["checkout_identity"] = action["handoff"]["checkout_identity"]
        state["active_operation"] = {"id": op_id, "role": action["role"], "child_task_name": child_task_name,
            "task_id": action["handoff"].get("task_id"), "input_identity": state["checkout_identity"], "dispatched_at": _now(),
            "allowed_output_paths": action["handoff"].get("allowed_output_paths", [])}
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
        if active["role"] in {"Reviewer", "Wave Reviewer"}:
            allowed = set(active.get("allowed_output_paths", []))
            if len(allowed) != 1:
                return "review operation has no exact allowed artifact path"
            # The Controller's own control record changes when it obtains the
            # lease.  It is not a child mutation and is excluded exactly.
            ignored = {self.path.relative_to(self.root).as_posix()}
            before = active["input_identity"].get("path_hashes")
            after = envelope["output_checkout_identity"].get("path_hashes")
            if not isinstance(before, dict) or not isinstance(after, dict):
                return "review checkout identity lacks path snapshots"
            changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
            if changed - allowed - ignored:
                return "review operation changed unauthorized paths"
            artifact_paths = {ref.get("path") for ref in envelope["authoritative_artifacts"]}
            if not allowed <= artifact_paths:
                return "required review artifact is missing"
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
                    if task.get("id") == state.get("current_task_id"):
                        task["status"] = "PASS"
                        task["accepted_review"] = self._accepted_review_receipt(task["id"], envelope)
                state["current_task_id"] = None
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
