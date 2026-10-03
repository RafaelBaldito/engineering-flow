"""Read-only authority and evidence contracts for one bounded MDS #6 FIX."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping
import uuid

from .domain import (ApprovedV2PlanAuthority, ConflictFailure, ImplementationProfile, Role, Stage,
                     ValidationFailure, WorkKind, WorkflowStatus, select_implementation_profile)
from .process_identity import (HostBootIdentity, ProcessGroupObservation,
                               local_host_boot_identity, observe_exact_process_group)
from .repository import RepositoryInspector, RepositorySnapshot, control_state_fingerprint
from .review import ReviewerResult
from .runtime import AgentRuntime, RuntimeExecutionRequest, TerminalState
from .store import WorkflowStore
from .verification import authority_binding_sha256


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValidationFailure(f"FIX result has duplicate field: {key}")
        value[key] = item
    return value


@dataclass(frozen=True, slots=True)
class SourceReview:
    """The immutable, terminal review evidence that alone may authorize FIX."""

    attempt_id: str
    producer_operation_id: str
    verification_attempt_id: str
    reviewer_result_sha256: str
    authority_sha256: str
    verification_evidence_sha256: str
    repository_fingerprint: str
    protected_control_sha256: str
    task_contract_id: str
    task_contract_sha256: str
    review_cycle: int
    result: ReviewerResult

    @property
    def blocking_finding_ids(self) -> tuple[str, ...]:
        return tuple(finding.id for finding in self.result.findings if finding.severity == "blocking")


@dataclass(frozen=True, slots=True)
class FixPreflight:
    authority: ApprovedV2PlanAuthority
    source_review: SourceReview
    authority_sha256: str
    request_hash: str
    implementation_profile: ImplementationProfile
    max_review_cycles: int


@dataclass(frozen=True, slots=True)
class FixResult:
    """Advisory provider evidence, never verification or review authority."""

    summary: str
    addressed_blocking_finding_ids: tuple[str, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {"summary": self.summary,
                "addressed_blocking_finding_ids": list(self.addressed_blocking_finding_ids)}

    def sha256(self) -> str:
        return _sha256(self.canonical_payload())


def _source_review_from_payload(value: Mapping[str, Any]) -> SourceReview:
    fields = {"attempt_id", "producer_operation_id", "verification_attempt_id", "reviewer_result_sha256",
              "authority_sha256", "verification_evidence_sha256", "repository_fingerprint", "protected_control_sha256",
              "task_contract_id", "task_contract_sha256", "review_cycle", "summary", "findings"}
    if set(value) != fields:
        raise ValidationFailure("FIX source review evidence has an invalid shape")
    hashed = {"reviewer_result_sha256", "authority_sha256", "verification_evidence_sha256",
              "repository_fingerprint", "protected_control_sha256", "task_contract_sha256"}
    for name in fields - {"review_cycle", "summary", "findings"}:
        item = value[name]
        if not isinstance(item, str) or not item:
            raise ValidationFailure("FIX source review evidence has an invalid binding")
        if name in hashed and (len(item) != 64 or any(char not in "0123456789abcdef" for char in item)):
            raise ValidationFailure("FIX source review evidence has an invalid hash")
    if type(value["review_cycle"]) is not int or value["review_cycle"] < 1:
        raise ValidationFailure("FIX source review cycle is invalid")
    raw = {"outcome": "CHANGES_REQUESTED", "summary": value["summary"], "findings": value["findings"]}
    try:
        from .review import parse_reviewer_result
        result = parse_reviewer_result(raw)
    except ValidationFailure as exc:
        raise ValidationFailure("FIX source review findings are invalid") from exc
    if result.sha256() != value["reviewer_result_sha256"]:
        raise ValidationFailure("FIX source reviewer result hash is stale or mismatched")
    return SourceReview(value["attempt_id"], value["producer_operation_id"], value["verification_attempt_id"],
        value["reviewer_result_sha256"], value["authority_sha256"], value["verification_evidence_sha256"],
        value["repository_fingerprint"], value["protected_control_sha256"], value["task_contract_id"], value["task_contract_sha256"],
        value["review_cycle"], result)


class FixPreflightResolver:
    """Resolve one below-limit task-level CHANGES_REQUESTED review without writes."""

    def __init__(self, authority_loader: Callable[[str], ApprovedV2PlanAuthority],
                 source_review_loader: Callable[[str, str, str], Mapping[str, Any]],
                 max_review_cycles: int) -> None:
        if type(max_review_cycles) is not int or max_review_cycles < 1:
            raise ValidationFailure("FIX max_review_cycles must be a positive integer")
        self.authority_loader = authority_loader
        self.source_review_loader = source_review_loader
        self.max_review_cycles = max_review_cycles

    def resolve(self, workflow_id: str, *, task_contract_id: str,
                task_contract_sha256: str) -> FixPreflight:
        authority = self.authority_loader(workflow_id)
        if (authority.workflow.id != workflow_id or authority.workflow.stage is not Stage.TASK_EXECUTION
                or authority.workflow.status is not WorkflowStatus.TASK_CHANGES_REQUESTED):
            raise ValidationFailure("FIX requires exact task-level TASK_CHANGES_REQUESTED authority")
        task = next((item for item in authority.plan.tasks if item.id == task_contract_id), None)
        if task is None or task.payload_sha256() != task_contract_sha256:
            raise ValidationFailure("FIX Task Contract does not match approved authority")
        authority_hash = authority_binding_sha256(authority, task_contract_id=task_contract_id,
            task_contract_sha256=task_contract_sha256)
        source = _source_review_from_payload(dict(self.source_review_loader(
            workflow_id, task_contract_id, task_contract_sha256)))
        if (source.task_contract_id != task_contract_id or source.task_contract_sha256 != task_contract_sha256
                or source.authority_sha256 != authority_hash):
            raise ValidationFailure("FIX source review does not match current authority")
        request_hash = _sha256({"fix_authority_sha256": authority_hash,
            "source_review_attempt_id": source.attempt_id,
            "source_reviewer_result_sha256": source.reviewer_result_sha256,
            "source_verified_producer_operation_id": source.producer_operation_id,
            "source_verification_attempt_id": source.verification_attempt_id,
            "source_verification_evidence_sha256": source.verification_evidence_sha256,
            "source_repository_fingerprint": source.repository_fingerprint,
            "source_protected_control_sha256": source.protected_control_sha256,
            "review_cycle": source.review_cycle, "fix_attempt_ordinal": 1,
            "blocking_finding_ids": list(source.blocking_finding_ids)})
        return FixPreflight(authority, source, authority_hash, request_hash,
            select_implementation_profile(task.complexity, task.risk), self.max_review_cycles)


def parse_fix_result(raw: str | bytes | Mapping[str, Any], *,
                     source_blocking_finding_ids: tuple[str, ...]) -> FixResult:
    """Parse only the bounded advisory claim required of a MDS #6 Fixer."""
    if not source_blocking_finding_ids or len(set(source_blocking_finding_ids)) != len(source_blocking_finding_ids):
        raise ValidationFailure("FIX source blocking findings are invalid")
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw, object_pairs_hook=_strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationFailure("FIX result must be valid UTF-8 JSON") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"summary", "addressed_blocking_finding_ids"}:
        raise ValidationFailure("FIX result must contain exactly summary and addressed_blocking_finding_ids")
    summary, identifiers = raw["summary"], raw["addressed_blocking_finding_ids"]
    if not isinstance(summary, str) or not summary.strip() or not isinstance(identifiers, list):
        raise ValidationFailure("FIX result fields are invalid")
    if any(not isinstance(identifier, str) or not identifier.strip() for identifier in identifiers):
        raise ValidationFailure("FIX addressed finding IDs are invalid")
    if len(set(identifiers)) != len(identifiers):
        raise ValidationFailure("FIX addressed finding IDs must not contain duplicates")
    if tuple(identifiers) != source_blocking_finding_ids:
        raise ValidationFailure("FIX addressed finding IDs must exactly match source blocking findings in order")
    return FixResult(summary, tuple(identifiers))


class FixRecoveryService:
    """Observe one retained FIX owner and stop at a durable human boundary.

    Recovery deliberately has no runtime dependency and no continuation path:
    it cannot dispatch a Fixer, verifier, Reviewer, or successor.
    """

    def __init__(self, store: WorkflowStore, *, identity: HostBootIdentity | None = None,
                 observer: Callable[..., ProcessGroupObservation] = observe_exact_process_group,
                 inspector_factory: Callable[[str | Path], RepositoryInspector] = RepositoryInspector) -> None:
        self.store, self.identity, self.observer, self.inspector_factory = (
            store, identity, observer, inspector_factory)

    @staticmethod
    def _same_structure(before: Mapping[str, Any], after: RepositorySnapshot) -> bool:
        return (before.get("fingerprint") == after.fingerprint and
                all(before.get(field) == getattr(after, field) for field in (
                    "canonical_root", "git_toplevel", "git_dir", "git_common_dir", "head_sha",
                    "branch_name", "detached", "local_git_config_sha256")))

    def recover(self, workflow_id: str) -> str:
        # A durable active attempt, not a lease lookup, establishes that an
        # unresolved FIX owner exists.  Lease topology is reconciled only
        # after that boundary has been found.
        attempts = self.store._connection.execute("SELECT * FROM fix_attempts WHERE workflow_id=? AND status='fixing'",
            (workflow_id,)).fetchall()
        if not attempts:
            retained = self.store._connection.execute("SELECT 1 FROM fix_attempts WHERE workflow_id=? AND status='unknown'",
                (workflow_id,)).fetchone()
            return "already_recovered" if retained is not None else "no_attempt"
        if len(attempts) != 1:
            ids = [row["id"] for row in attempts]
            for attempt in attempts:
                self.store.retain_fix_recovery_unknown(attempt["id"], classification="multiple_active_fix_attempts",
                    detail="FIX recovery found multiple active durable FIX attempts",
                    evidence={"attempt_id": attempt["id"], "active_attempt_ids": ids})
            return "ambiguous_ownership"
        attempt = attempts[0]
        rows = self.store._connection.execute("""SELECT * FROM workspace_operation_leases
            WHERE operation_kind='fix' AND (workflow_id=? OR attempt_id=? OR operation_id=? OR lease_id=?)""",
            (workflow_id, attempt["id"], attempt["operation_id"], attempt["lease_id"])).fetchall()
        exact = [row for row in rows if row["workflow_id"] == workflow_id and row["lease_id"] == attempt["lease_id"]
                 and row["attempt_id"] == attempt["id"] and row["operation_id"] == attempt["operation_id"]]
        if len(rows) != 1 or len(exact) != 1:
            classification = ("missing_expected_fix_lease" if not rows else
                              "multiple_fix_leases" if len(rows) > 1 else "foreign_or_mismatched_fix_lease")
            self.store.retain_fix_recovery_unknown(attempt["id"], classification=classification,
                detail="FIX recovery could not prove exact durable lease ownership",
                evidence={"attempt_id": attempt["id"], "expected_lease_id": attempt["lease_id"],
                          "expected_operation_id": attempt["operation_id"],
                          "candidate_lease_ids": [row["lease_id"] for row in rows],
                          "candidate_attempt_ids": [row["attempt_id"] for row in rows],
                          "candidate_operation_ids": [row["operation_id"] for row in rows]})
            return classification
        lease = exact[0]
        evidence: dict[str, Any] = {key: lease[key] for key in (
            "lease_id", "attempt_id", "operation_id", "owner_instance_id", "owner_pid",
            "owner_host_id", "owner_boot_id", "child_pid", "child_process_start",
            "child_process_group", "child_process_session")}
        try:
            observation = self.observer(host_id=lease["owner_host_id"], boot_id=lease["owner_boot_id"],
                process_pid=lease["child_pid"], process_start=lease["child_process_start"],
                process_group=lease["child_process_group"], process_session=lease["child_process_session"],
                identity=self.identity)
        except Exception:
            observation = ProcessGroupObservation.INSPECTION_FAILURE
        evidence["process_observation"] = observation.value
        if observation is not ProcessGroupObservation.DEAD:
            self.store.recover_fix_attempt(lease["attempt_id"], lease["lease_id"],
                classification=observation.value, detail="FIX ownership is unresolved or still live",
                evidence=evidence, release_lease=False)
            return observation.value
        try:
            baseline = json.loads(attempt["baseline_repository_json"])
            if not isinstance(baseline, Mapping) or not isinstance(baseline.get("control_state_fingerprint"), str):
                raise ValidationFailure("FIX baseline protected-control evidence is unavailable")
            snapshot = self.inspector_factory(lease["canonical_root"]).capture()
            control = control_state_fingerprint(snapshot.canonical_root)
            evidence.update({"repository": snapshot.as_payload(), "control_state_fingerprint": control})
            unchanged = self._same_structure(baseline, snapshot) and control == baseline["control_state_fingerprint"]
        except Exception as exc:
            evidence["inspection_error"] = type(exc).__name__
            unchanged = False
        self.store.recover_fix_attempt(lease["attempt_id"], lease["lease_id"],
            classification="process_dead_unchanged" if unchanged else "protected_state_unknown",
            detail=("FIX process is dead and protected state is unchanged" if unchanged else
                    "FIX process is dead but protected state is changed, unreadable, or corrupt"),
            evidence=evidence, release_lease=unchanged)
        return "process_dead_unchanged" if unchanged else "protected_state_unknown"


class FixContinuationService:
    """Route one explicit V2 remediation continuation through durable boundaries."""

    def __init__(self, store: WorkflowStore, runtime: AgentRuntime, *, max_review_cycles: int) -> None:
        self.store, self.runtime, self.max_review_cycles = store, runtime, max_review_cycles

    def continue_once(self, workflow_id: str) -> str:
        workflow = self.store.get_workflow(workflow_id)
        if workflow.status is WorkflowStatus.FIXING or self.store.has_retained_fix_attempt(workflow_id):
            return FixRecoveryService(self.store).recover(workflow_id)
        if workflow.status is not WorkflowStatus.TASK_CHANGES_REQUESTED:
            return "not_fixable"
        authority = self.store.load_approved_v2_plan_authority(workflow_id)
        states = self.store.list_task_implementation_states(workflow_id, authority.plan_artifact.id)
        requested = [state for state in states if state.status.value == "changes_requested"]
        if len(requested) != 1:
            raise ValidationFailure("FIX requires exactly one changes_requested task state")
        state = requested[0]
        FixAttemptOrchestrator(self.store, self.runtime).run_once(
            workflow_id, task_contract_id=state.task_contract_id,
            task_contract_sha256=state.task_contract_sha256, max_review_cycles=self.max_review_cycles)
        return "dispatched"


class FixAttemptOrchestrator:
    """Dispatch exactly one Developer/FIX request from one durable intent.

    This slice intentionally records just the normal completed-FIX evidence.
    It does not classify failures, recover retained ownership, invoke VERIFY,
    or make any task-success projection.
    """

    def __init__(self, store: WorkflowStore, runtime: AgentRuntime, *, timeout_seconds: float = 1800,
                 before_dispatch: Callable[[], None] | None = None) -> None:
        self.store, self.runtime, self.timeout_seconds, self.before_dispatch = (
            store, runtime, timeout_seconds, before_dispatch)

    @staticmethod
    def _same_structure(before: RepositorySnapshot, after: RepositorySnapshot) -> bool:
        return (before.canonical_root, before.git_toplevel, before.git_dir, before.git_common_dir,
                before.head_sha, before.branch_name, before.detached, before.local_git_config_sha256) == (
                after.canonical_root, after.git_toplevel, after.git_dir, after.git_common_dir,
                after.head_sha, after.branch_name, after.detached, after.local_git_config_sha256)

    def _bounded_inputs(self, preflight: FixPreflight, execution_id: str,
                        inspector: RepositoryInspector) -> tuple[tuple[str, ...], tuple[str, ...], Path, Path]:
        root = Path(tempfile.mkdtemp(prefix="engineering-flow-fix-"))
        task = next(item for item in preflight.authority.plan.tasks
                    if item.id == preflight.source_review.task_contract_id)
        verification = self.store._connection.execute("""SELECT manifest_binding_json,final_inspection_json
            FROM verification_attempts WHERE id=? AND producer_operation_id=? AND status='terminal'
              AND classification='verified'""", (preflight.source_review.verification_attempt_id,
                preflight.source_review.producer_operation_id)).fetchone()
        command_rows = self.store._connection.execute("""SELECT ordinal,command_id,canonical_command_sha256
            FROM verification_command_results WHERE verification_attempt_id=? ORDER BY ordinal,id""",
            (preflight.source_review.verification_attempt_id,)).fetchall()
        if verification is None or not command_rows:
            raise ValidationFailure("FIX source verification evidence is incomplete")
        try:
            manifest = json.loads(verification["manifest_binding_json"])
            final_inspection = json.loads(verification["final_inspection_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValidationFailure("FIX source verification evidence is malformed") from exc
        if not isinstance(manifest, Mapping) or not isinstance(final_inspection, Mapping):
            raise ValidationFailure("FIX source verification evidence is malformed")
        evidence = {
            "task_contract": task.as_payload(),
            "source_review": {"attempt_id": preflight.source_review.attempt_id,
                "reviewer_result_sha256": preflight.source_review.reviewer_result_sha256,
                "producer_operation_id": preflight.source_review.producer_operation_id,
                "verification_attempt_id": preflight.source_review.verification_attempt_id,
                "verification_evidence_sha256": preflight.source_review.verification_evidence_sha256,
                "findings": [finding.as_payload() for finding in preflight.source_review.result.findings]},
            "source_verification": {"manifest": manifest, "final_inspection": final_inspection,
                "commands": [{"ordinal": row["ordinal"], "id": row["command_id"],
                               "canonical_command_sha256": row["canonical_command_sha256"]}
                             for row in command_rows]},
        }
        evidence_path = root / "fix-evidence.json"
        evidence_path.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        diff_path = root / "source-review.diff"
        diff_path.write_bytes(inspector._git("diff", "--binary", "HEAD"))
        feature, plan = preflight.authority.feature_contract_artifact, preflight.authority.plan_artifact
        self.store.read_artifact(feature.id); self.store.read_artifact(plan.id)
        paths = [feature.path, plan.path, str(evidence_path), str(diff_path)]
        hashes = [feature.sha256, plan.sha256, hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                  hashlib.sha256(diff_path.read_bytes()).hexdigest()]
        repository = Path(preflight.authority.workflow.repository_path).resolve()
        for relative in (*task.relevant_files, *task.existing_patterns):
            candidate = (repository / relative).resolve()
            try:
                candidate.relative_to(repository)
            except ValueError as exc:
                raise ValidationFailure("FIX Task Contract input is outside the repository") from exc
            if candidate.is_file():
                paths.append(str(candidate)); hashes.append(hashlib.sha256(candidate.read_bytes()).hexdigest())
        rules = repository / "AGENTS.md"
        if rules.is_file():
            paths.append(str(rules)); hashes.append(hashlib.sha256(rules.read_bytes()).hexdigest())
        return tuple(paths), tuple(hashes), root / "fix-output.schema.json", root / "final-output.json"

    @staticmethod
    def _instruction(preflight: FixPreflight, paths: tuple[str, ...]) -> str:
        return (
            "You are the Developer performing exactly one bounded FIX. Read only the supplied authoritative inputs: "
            + ", ".join(paths)
            + ". Address every blocking source-review finding in its given order. You may modify only the workspace. "
              "Do not modify authority/control artifacts, Git refs or configuration; do not commit, push, open a PR, "
              "verify, review, accept a task, release dependencies, select another task, or retry. "
              "Return only JSON with non-empty summary and addressed_blocking_finding_ids exactly matching the source blocking IDs."
        )

    def _continuity(self, preflight: FixPreflight) -> tuple[str | None, Mapping[str, Any]]:
        row = self.store._connection.execute("""SELECT a.requested_provider,a.actual_provider,a.provider_session_ref,
            e.session_id FROM implementation_attempts a JOIN executions e ON e.id=a.execution_id
            WHERE a.operation_id=?""", (preflight.source_review.producer_operation_id,)).fetchone()
        if row is None or not row["provider_session_ref"]:
            return None, {}
        runtime_provider = getattr(self.runtime, "provider", None)
        if runtime_provider not in {row["requested_provider"], row["actual_provider"]}:
            return None, {}
        # The adapter remains responsible for determining whether its explicitly
        # advertised resume mechanism is safe; it falls back to this bounded bundle.
        bundle = {"task_contract": next(item for item in preflight.authority.plan.tasks
                    if item.id == preflight.source_review.task_contract_id).as_payload(),
                  "review_findings": [item.as_payload() for item in preflight.source_review.result.findings]}
        return row["provider_session_ref"], bundle

    def run_once(self, workflow_id: str, *, task_contract_id: str,
                 task_contract_sha256: str, max_review_cycles: int) -> FixResult | None:
        preflight = FixPreflightResolver(self.store.load_approved_v2_plan_authority,
            self.store.load_fix_source_review_evidence, max_review_cycles).resolve(
                workflow_id, task_contract_id=task_contract_id, task_contract_sha256=task_contract_sha256)
        if preflight.source_review.review_cycle >= max_review_cycles:
            self.store.project_review_cycle_limit(workflow_id,
                task_contract_id=task_contract_id,
                task_contract_sha256=task_contract_sha256,
                source_review_attempt_id=preflight.source_review.attempt_id,
                review_cycle=preflight.source_review.review_cycle,
                max_review_cycles=max_review_cycles)
            return None
        inspector = RepositoryInspector(preflight.authority.workflow.repository_path)
        baseline = inspector.capture()
        if baseline.fingerprint != preflight.source_review.repository_fingerprint:
            raise ValidationFailure("repository drifted from source REVIEW evidence before FIX intent")
        protected_control = control_state_fingerprint(baseline.canonical_root)
        if protected_control != preflight.source_review.protected_control_sha256:
            raise ValidationFailure("protected control state drifted from source REVIEW evidence before FIX intent")
        baseline_payload = {**baseline.as_payload(), "control_state_fingerprint": protected_control}
        identity = local_host_boot_identity()
        intent = self.store.create_fix_intent(workflow_id, repository_key=inspector.repository_key(),
            canonical_root=baseline.canonical_root, task_contract_id=task_contract_id,
            task_contract_sha256=task_contract_sha256, source_review_attempt_id=preflight.source_review.attempt_id,
            source_reviewer_result_sha256=preflight.source_review.reviewer_result_sha256,
            source_producer_operation_id=preflight.source_review.producer_operation_id,
            source_verification_attempt_id=preflight.source_review.verification_attempt_id,
            source_verification_evidence_sha256=preflight.source_review.verification_evidence_sha256,
            authority_sha256=preflight.authority_sha256, request_hash=preflight.request_hash,
            max_review_cycles=max_review_cycles, baseline=baseline_payload, owner_instance_id=str(uuid.uuid4()),
            owner_pid=os.getpid(), owner_host_id=identity.host_id, owner_boot_id=identity.boot_id,
            requested_profile=preflight.implementation_profile.value,
            requested_provider=getattr(self.runtime, "provider", "runtime"))
        if not intent["created"]:
            raise ConflictFailure("active FIX intent requires recovery classification before dispatch")
        if self.before_dispatch:
            self.before_dispatch()
        accepted = inspector.capture()
        accepted_control = control_state_fingerprint(baseline.canonical_root)
        if (accepted.fingerprint != baseline.fingerprint
                or accepted.fingerprint != preflight.source_review.repository_fingerprint
                or accepted_control != protected_control
                or accepted_control != preflight.source_review.protected_control_sha256):
            return None
        paths, hashes, schema_path, final_path = self._bounded_inputs(preflight, intent["execution_id"], inspector)
        resume_id, bundle = self._continuity(preflight)
        session = self.store.get_session(self.store.get_execution(intent["execution_id"]).session_id)
        request = RuntimeExecutionRequest(workflow_id=workflow_id, execution_id=intent["execution_id"],
            logical_session_id=session.logical_session_id, role=Role.DEVELOPER, stage=Stage.TASK_EXECUTION,
            repository_path=preflight.authority.workflow.repository_path, authoritative_input_paths=paths,
            authoritative_input_hashes=hashes, instruction=self._instruction(preflight, paths),
            output_schema_path=str(schema_path), final_output_path=str(final_path), timeout_seconds=self.timeout_seconds,
            required_capabilities=("workspace_write", "json_events", "output_schema"), work_kind=WorkKind.FIX,
            continuity_bundle=bundle, resume_provider_session_id=resume_id,
            provider_started=lambda evidence: self.store.record_fix_provider_started(
                intent["attempt_id"], intent["lease_id"], evidence))
        result = self.runtime.execute(request)  # The sole provider dispatch in this invocation.
        try:
            final = inspector.capture()
            safe = (self._same_structure(baseline, final)
                and control_state_fingerprint(baseline.canonical_root) == protected_control)
        except Exception:
            return None
        if not result.success or result.terminal_state is not TerminalState.SUCCEEDED or not safe:
            return None
        try:
            parsed = parse_fix_result(result.final_payload or {},
                source_blocking_finding_ids=preflight.source_review.blocking_finding_ids)
        except ValidationFailure:
            return None
        if final.fingerprint == baseline.fingerprint:
            return None
        self.store.finish_fix_attempt(intent["attempt_id"], intent["lease_id"], result_payload=parsed.canonical_payload(),
            result_sha256=parsed.sha256(), final=final.as_payload(), provider=result.provider,
            provider_session_id=result.provider_session_id, provider_execution_id=result.provider_execution_id)
        # A completed Fix is advisory provider evidence only.  The same
        # invocation immediately hands its exact producer operation to MDS #4
        # deterministic verification; it never starts a Reviewer.
        try:
            from .verification import DeterministicVerificationOrchestrator, DeterministicVerificationPreflight
            verification = DeterministicVerificationPreflight(
                inspector.root, self.store.load_approved_v2_plan_authority,
                self.store.load_successful_producer).validate(workflow_id,
                    task_contract_id=task_contract_id, task_contract_sha256=task_contract_sha256,
                    producer_operation_id=intent["operation_id"])
            DeterministicVerificationOrchestrator(self.store, inspector.root).run(verification)
        except Exception as exc:
            # A stale/malformed producer, manifest, or authority chain cannot
            # become a retry channel.  Preserve the completed Fix and stop.
            self.store.project_completed_fix_verification_attention(
                intent["attempt_id"], intent["lease_id"], detail=type(exc).__name__)
        return parsed
