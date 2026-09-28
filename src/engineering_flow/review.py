"""Fail-closed authority checks and one bounded independent REVIEW attempt."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Callable, Mapping

from .domain import (ApprovedV2PlanAuthority, SuccessfulImplementationProducer,
                     Role, Stage, ValidationFailure, WorkKind, WorkflowStatus)
from .repository import RepositoryInspector, RepositorySnapshot, control_state_fingerprint
from .runtime import AgentRuntime, RuntimeExecutionRequest, TerminalState
from .store import WorkflowStore
from .verification import authority_binding_sha256


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationFailure(f"reviewer result has duplicate field: {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class ReviewerFinding:
    id: str
    severity: str
    category: str
    description: str
    path: str | None
    line: int | None
    requirement_reference: str | None

    def as_payload(self) -> dict[str, object]:
        return {"id": self.id, "severity": self.severity, "category": self.category,
                "description": self.description, "path": self.path, "line": self.line,
                "requirement_reference": self.requirement_reference}


@dataclass(frozen=True, slots=True)
class ReviewerResult:
    outcome: str
    summary: str
    findings: tuple[ReviewerFinding, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {"outcome": self.outcome, "summary": self.summary,
                "findings": [finding.as_payload() for finding in self.findings]}

    def sha256(self) -> str:
        return _sha256(self.canonical_payload())


def validate_repository_relative_path(value: object) -> str | None:
    """Accept a portable repository-relative file path, never a traversal."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value or "\\" in value:
        raise ValidationFailure("review finding path must be a safe repository-relative path or null")
    path = PurePosixPath(value)
    if path.is_absolute() or value in {".", ".."} or any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationFailure("review finding path must be a safe repository-relative path or null")
    return value


def parse_reviewer_result(raw: str | bytes | Mapping[str, Any]) -> ReviewerResult:
    """Strictly parse the canonical, provider-supplied reviewer evidence."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw, object_pairs_hook=_strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationFailure("reviewer result must be valid UTF-8 JSON") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"outcome", "summary", "findings"}:
        raise ValidationFailure("reviewer result must contain exactly outcome, summary, and findings")
    outcome, summary, findings = raw["outcome"], raw["summary"], raw["findings"]
    if outcome not in {"REVIEW_PASSED", "CHANGES_REQUESTED"}:
        raise ValidationFailure("reviewer outcome is invalid")
    if not isinstance(summary, str) or not summary.strip():
        raise ValidationFailure("reviewer summary must be non-empty")
    if not isinstance(findings, list):
        raise ValidationFailure("reviewer findings must be an array")
    parsed: list[ReviewerFinding] = []
    identifiers: set[str] = set()
    fields = {"id", "severity", "category", "description", "path", "line", "requirement_reference"}
    for finding in findings:
        if not isinstance(finding, Mapping) or set(finding) != fields:
            raise ValidationFailure("review finding must contain exactly the canonical fields")
        identifier, severity, category, description = (finding["id"], finding["severity"],
            finding["category"], finding["description"])
        if (not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers
                or not isinstance(description, str) or not description.strip()
                or severity not in {"blocking", "advisory"}
                or category not in {"correctness", "requirement", "architecture", "edge_case",
                                   "maintainability", "security", "regression_risk"}):
            raise ValidationFailure("review finding fields are invalid")
        path = validate_repository_relative_path(finding["path"])
        line = finding["line"]
        reference = finding["requirement_reference"]
        if (line is not None and (type(line) is not int or line < 1)) or (line is not None and path is None):
            raise ValidationFailure("review finding line must be a positive integer for a path or null")
        if reference is not None and (not isinstance(reference, str) or not reference.strip()):
            raise ValidationFailure("review finding requirement_reference must be non-empty text or null")
        identifiers.add(identifier)
        parsed.append(ReviewerFinding(identifier, severity, category, description, path, line, reference))
    if (outcome == "REVIEW_PASSED" and parsed) or (outcome == "CHANGES_REQUESTED"
                                                    and not any(item.severity == "blocking" for item in parsed)):
        raise ValidationFailure("reviewer findings do not match the declared outcome")
    return ReviewerResult(outcome, summary, tuple(parsed))


@dataclass(frozen=True, slots=True)
class ReviewPreflight:
    authority: ApprovedV2PlanAuthority
    producer: SuccessfulImplementationProducer
    verification: Mapping[str, Any]
    authority_sha256: str
    request_hash: str


class ReviewPreflightResolver:
    """Resolve exactly one terminal VERIFIED task through read-only loaders."""

    def __init__(self, authority_loader: Callable[[str], ApprovedV2PlanAuthority],
                 producer_loader: Callable[[str, str, str, str], SuccessfulImplementationProducer],
                 verified_evidence_loader: Callable[[str, str, str], Mapping[str, Any]]) -> None:
        self.authority_loader = authority_loader
        self.producer_loader = producer_loader
        self.verified_evidence_loader = verified_evidence_loader

    def resolve(self, workflow_id: str, *, task_contract_id: str,
                task_contract_sha256: str) -> ReviewPreflight:
        authority = self.authority_loader(workflow_id)
        if authority.workflow.id != workflow_id:
            raise ValidationFailure("review authority workflow binding is invalid")
        if (authority.workflow.stage is not Stage.TASK_EXECUTION
                or authority.workflow.status is not WorkflowStatus.TASK_VERIFIED):
            raise ValidationFailure("REVIEW requires exact TASK_VERIFIED authority")
        authority_hash = authority_binding_sha256(authority, task_contract_id=task_contract_id,
            task_contract_sha256=task_contract_sha256)
        evidence = dict(self.verified_evidence_loader(workflow_id, task_contract_id, task_contract_sha256))
        required = {"attempt_id", "producer_operation_id", "verification_request_hash",
                    "verification_authority_sha256", "verification_evidence_sha256",
                    "repository_fingerprint"}
        if set(evidence) != required or any(not isinstance(evidence[key], str) or not evidence[key]
                                              for key in required):
            raise ValidationFailure("verified REVIEW evidence is incomplete")
        if evidence["verification_authority_sha256"] != authority_hash:
            raise ValidationFailure("verified REVIEW evidence is stale or mismatched")
        producer = self.producer_loader(workflow_id, evidence["producer_operation_id"],
            task_contract_id, task_contract_sha256)
        bindings = (producer.workflow_id == workflow_id and producer.task_contract_id == task_contract_id
            and producer.task_contract_sha256 == task_contract_sha256
            and (producer.feature_artifact_id, producer.feature_sha256) ==
                (authority.feature_contract_artifact.id, authority.feature_contract_artifact.sha256)
            and (producer.plan_artifact_id, producer.plan_sha256, producer.plan_revision,
                 producer.plan_id, producer.approval_id) ==
                (authority.plan_artifact.id, authority.plan_artifact.sha256, authority.plan.revision,
                 authority.plan.id, authority.approval.id))
        if not bindings:
            raise ValidationFailure("verified REVIEW producer does not match current authority")
        request_hash = _sha256({"review_authority_sha256": authority_hash,
            "feature_sha256": authority.feature_contract_artifact.sha256,
            "plan_sha256": authority.plan_artifact.sha256, "approval_id": authority.approval.id,
            "task_contract_sha256": task_contract_sha256, "producer_operation_id": producer.operation_id,
            "producer_execution_id": producer.execution_id,
            "producer_request_hash": producer.implementation_request_hash,
            "producer_final_repository_sha256": producer.final_repository_sha256,
            "verification_attempt_id": evidence["attempt_id"],
            "verification_request_hash": evidence["verification_request_hash"],
            "verification_evidence_sha256": evidence["verification_evidence_sha256"],
            "repository_fingerprint": evidence["repository_fingerprint"]})
        return ReviewPreflight(authority, producer, evidence, authority_hash, request_hash)


class ReviewRecoveryService:
    """Dispatch-free reconciliation of one retained REVIEW attempt.

    REVIEW currently persists no safe process-owner identity.  Consequently a
    live/running execution is never guessed to be dead: only already durable
    terminal provider evidence can be classified as a known failure.
    """

    def __init__(self, store: WorkflowStore,
                 inspector_factory: Callable[[str], RepositoryInspector] = RepositoryInspector) -> None:
        self.store, self.inspector_factory = store, inspector_factory

    def recover(self, workflow_id: str) -> str:
        rows = self.store._connection.execute("""SELECT a.*, e.lifecycle AS execution_lifecycle,
            e.terminal_result, e.failure_classification, e.failure_detail
            FROM review_attempts a JOIN executions e ON e.id=a.execution_id
            WHERE a.workflow_id=? ORDER BY a.sequence DESC""", (workflow_id,)).fetchall()
        if not rows:
            return "no_attempt"
        retained = [row for row in rows if row["status"] != "terminal"]
        if not retained:
            return "already_terminal"
        # More than one retained intent is itself corrupt.  Do not choose one
        # as a survivor: retain every attempt at a human boundary.
        if len(retained) != 1:
            for row in retained:
                self.store.recover_review_attempt(row["id"], classification="ambiguous_evidence",
                    detail="review recovery found multiple retained attempts", evidence={
                        "attempt_id": row["id"], "retained_attempt_ids": [item["id"] for item in retained]})
            return "ambiguous_attempt_set"
        attempt = retained[0]
        evidence: dict[str, object] = {"attempt_id": attempt["id"],
            "execution_lifecycle": attempt["execution_lifecycle"]}
        try:
            workflow = self.store.get_workflow(workflow_id)
            snapshot = self.inspector_factory(workflow.repository_path).capture()
            control = control_state_fingerprint(snapshot.canonical_root)
            evidence.update({"repository": snapshot.as_payload(), "control_state_fingerprint": control})
        except Exception as exc:
            return self.store.recover_review_attempt(attempt["id"], classification="ambiguous_evidence",
                detail="review recovery repository/control inspection is unavailable",
                evidence={**evidence, "inspection_error": type(exc).__name__})
        unchanged = (snapshot.fingerprint == attempt["repository_fingerprint"]
            and attempt["protected_control_sha256"] is not None
            and control == attempt["protected_control_sha256"])
        if not unchanged:
            return self.store.recover_review_attempt(attempt["id"], classification="protected_state_drift",
                detail="review recovery observed repository/control drift or missing baseline", evidence=evidence)
        raw_result = attempt["terminal_result"]
        if raw_result:
            try:
                result = json.loads(raw_result)
                parse_reviewer_result(result)
            except (TypeError, json.JSONDecodeError, ValidationFailure):
                return self.store.recover_review_attempt(attempt["id"], classification="malformed_result",
                    detail="review recovery found malformed persisted terminal result", evidence=evidence)
            return self.store.recover_review_attempt(attempt["id"], classification="ambiguous_evidence",
                detail="review recovery projects persisted valid terminal result", evidence=evidence,
                reviewer_result=result)
        if (attempt["execution_lifecycle"] == "failed"
                and attempt["failure_classification"] in {"provider", "provider_runtime_failure"}):
            return self.store.recover_review_attempt(attempt["id"], classification="provider_runtime_failure",
                detail=attempt["failure_detail"] or "persisted reviewer provider failure", evidence=evidence,
                review_failed=True)
        # A running/intended/unknown execution has no persisted exact owner to
        # observe.  Retain it and stop at a human boundary rather than retry.
        return self.store.recover_review_attempt(attempt["id"], classification="ambiguous_evidence",
            detail="review execution ownership or liveness is not safely observable", evidence=evidence)


class ReviewContinuationService:
    """Select the one Slice 5 REVIEW boundary without giving that policy to CLI."""

    def __init__(self, store: WorkflowStore, runtime: AgentRuntime) -> None:
        self.store, self.runtime = store, runtime

    def continue_once(self, workflow_id: str) -> str:
        workflow = self.store.get_workflow(workflow_id)
        # A persisted REVIEWING projection is uncertain even if its retained
        # row is corrupt or missing.  It must never become permission to retry.
        if workflow.status is WorkflowStatus.REVIEWING or self.store.has_retained_review_attempt(workflow_id):
            return ReviewRecoveryService(self.store).recover(workflow_id)
        if workflow.status is not WorkflowStatus.TASK_VERIFIED:
            return "not_reviewable"
        authority = self.store.load_approved_v2_plan_authority(workflow_id)
        states = self.store.list_task_implementation_states(workflow_id, authority.plan_artifact.id)
        verified = [state for state in states if state.status.value == "verified"]
        if len(verified) != 1:
            raise ValidationFailure("REVIEW requires exactly one verified task state")
        state = verified[0]
        ReviewAttemptOrchestrator(self.store, self.runtime).run_once(workflow_id,
            task_contract_id=state.task_contract_id, task_contract_sha256=state.task_contract_sha256)
        return "dispatched"


class ReviewAttemptOrchestrator:
    """Execute precisely one fresh, read-only Reviewer request.

    Failures, interruption, malformed output, and protected-state drift leave
    the durable intent unresolved.  Classifying or recovering that boundary is
    deliberately owned by Slice 5.4, not this execution slice.
    """

    def __init__(self, store: WorkflowStore, runtime: AgentRuntime, *, timeout_seconds: float = 1800,
                 before_dispatch: Callable[[], None] | None = None) -> None:
        self.store = store
        self.runtime = runtime
        self.timeout_seconds = timeout_seconds
        self.before_dispatch = before_dispatch

    def _resolver(self) -> ReviewPreflightResolver:
        return ReviewPreflightResolver(self.store.load_approved_v2_plan_authority,
            self.store.load_successful_implementation_producer, self.store.load_verified_review_evidence)

    @staticmethod
    def _same_snapshot(first: RepositorySnapshot, second: RepositorySnapshot) -> bool:
        return first.fingerprint == second.fingerprint

    def _runtime_root(self, workflow_id: str, execution_id: str) -> Path:
        # REVIEW has no write authority in the inspected worktree.  Its
        # adapter-only schema, output, and generated evidence therefore live
        # outside that worktree rather than creating an ignored exception in
        # the protected repository state.
        del workflow_id, execution_id
        return Path(tempfile.mkdtemp(prefix="engineering-flow-review-"))

    def _bounded_inputs(self, preflight: ReviewPreflight, execution_id: str,
                        inspector: RepositoryInspector) -> tuple[tuple[str, ...], tuple[str, ...], Path, Path]:
        """Materialize only the contract/evidence/diff inputs allowed to REVIEW."""
        root = self._runtime_root(preflight.authority.workflow.id, execution_id)
        root.mkdir(parents=True, exist_ok=True)
        task = next(item for item in preflight.authority.plan.tasks
                    if item.id == preflight.producer.task_contract_id)
        evidence_path = root / "verified-review-evidence.json"
        evidence_path.write_text(json.dumps({
            "task_contract": task.as_payload(),
            "implementation": {"operation_id": preflight.producer.operation_id,
                "execution_id": preflight.producer.execution_id,
                "request_hash": preflight.producer.implementation_request_hash,
                "final_repository_sha256": preflight.producer.final_repository_sha256},
            "verification": dict(preflight.verification),
        }, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        diff_path = root / "repository.diff"
        diff_path.write_bytes(inspector._git("diff", "--binary", "HEAD"))

        # Artifact reads re-check their immutable hashes before their paths are
        # forwarded to the runtime.
        feature = preflight.authority.feature_contract_artifact
        plan = preflight.authority.plan_artifact
        self.store.read_artifact(feature.id)
        self.store.read_artifact(plan.id)
        paths = [feature.path, plan.path, str(evidence_path), str(diff_path)]
        hashes = [feature.sha256, plan.sha256,
                  hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                  hashlib.sha256(diff_path.read_bytes()).hexdigest()]
        repository = Path(preflight.authority.workflow.repository_path).resolve()
        for relative in (*task.relevant_files, *task.existing_patterns):
            candidate = (repository / relative).resolve()
            try:
                candidate.relative_to(repository)
            except ValueError as exc:
                raise ValidationFailure("review Task Contract input is outside the repository") from exc
            if candidate.is_file():
                paths.append(str(candidate))
                hashes.append(hashlib.sha256(candidate.read_bytes()).hexdigest())
        rules = repository / "AGENTS.md"
        if rules.is_file():
            paths.append(str(rules)); hashes.append(hashlib.sha256(rules.read_bytes()).hexdigest())
        return tuple(paths), tuple(hashes), root / "review-output.schema.json", root / "final-output.json"

    @staticmethod
    def _instruction(preflight: ReviewPreflight, paths: tuple[str, ...]) -> str:
        return (
            "You are an independent Reviewer. Read only the supplied bounded REVIEW inputs: "
            + ", ".join(paths)
            + ". Revalidate the exact Task Contract against the verified IMPLEMENT/VERIFY evidence and Git diff. "
              "Do not modify files, run write commands, commit, push, create a PR, accept a task, start FIX, or select another task. "
              "Return only the canonical REVIEW JSON: REVIEW_PASSED with no findings, or CHANGES_REQUESTED with at least one blocking finding."
        )

    def _abnormal(self, attempt_id: str, *, classification: str, detail: str,
                  review_failed: bool, **evidence: object) -> None:
        self.store.finish_review_abnormal_attempt(attempt_id, classification=classification,
            detail=detail, evidence=evidence, review_failed=review_failed)

    def run_once(self, workflow_id: str, *, task_contract_id: str,
                 task_contract_sha256: str) -> ReviewerResult | None:
        """Run one request; only a state-preserving valid result is terminal."""
        preflight = self._resolver().resolve(workflow_id, task_contract_id=task_contract_id,
            task_contract_sha256=task_contract_sha256)
        inspector = RepositoryInspector(preflight.authority.workflow.repository_path)
        pre_dispatch = inspector.capture()
        if pre_dispatch.fingerprint != preflight.verification["repository_fingerprint"]:
            raise ValidationFailure("repository drifted from verified REVIEW evidence before dispatch")

        intent = self.store.create_review_intent(workflow_id,
            task_contract_id=task_contract_id, task_contract_sha256=task_contract_sha256,
            authority_sha256=preflight.authority_sha256,
            verification_evidence_sha256=preflight.verification["verification_evidence_sha256"],
            request_hash=preflight.request_hash,
            repository_fingerprint=preflight.verification["repository_fingerprint"],
            protected_control_sha256=control_state_fingerprint(pre_dispatch.canonical_root))
        if not intent["created"]:
            # A retained prior intent is an explicit 5.4B recovery boundary.
            # This execution entry must never adopt or redispatch it.
            raise ValidationFailure("active REVIEW attempt requires recovery classification before dispatch")
        protected_control = control_state_fingerprint(pre_dispatch.canonical_root)
        if self.before_dispatch:
            self.before_dispatch()
        try:
            accepted = inspector.capture()
            if (not self._same_snapshot(pre_dispatch, accepted)
                    or control_state_fingerprint(pre_dispatch.canonical_root) != protected_control):
                self._abnormal(intent["attempt_id"], classification="protected_state_drift",
                    detail="protected repository/control state drifted before reviewer dispatch", review_failed=False,
                    before=pre_dispatch.as_payload(), after=accepted.as_payload())
                return None
        except BaseException as exc:
            self._abnormal(intent["attempt_id"], classification="ambiguous_evidence",
                detail="could not establish protected repository/control state before reviewer dispatch",
                review_failed=False, error=type(exc).__name__)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return None

        try:
            paths, hashes, schema_path, final_path = self._bounded_inputs(preflight, intent["execution_id"], inspector)
        except BaseException as exc:
            self._abnormal(intent["attempt_id"], classification="ambiguous_evidence",
                detail="review inputs could not be materialized after intent", review_failed=False,
                error=type(exc).__name__)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return None
        reviewer_session = self.store.get_session(self.store.get_execution(intent["execution_id"]).session_id)
        developer_session = self.store.get_session(
            self.store.get_execution(preflight.producer.execution_id).session_id)
        request = RuntimeExecutionRequest(workflow_id=workflow_id, execution_id=intent["execution_id"],
            logical_session_id=reviewer_session.logical_session_id, role=Role.REVIEWER,
            stage=Stage.TASK_EXECUTION, repository_path=preflight.authority.workflow.repository_path,
            authoritative_input_paths=paths, authoritative_input_hashes=hashes,
            instruction=self._instruction(preflight, paths), output_schema_path=str(schema_path),
            final_output_path=str(final_path), timeout_seconds=self.timeout_seconds,
            required_capabilities=("read_only", "json_events", "output_schema"), work_kind=WorkKind.REVIEW,
            continuity_bundle={}, resume_provider_session_id=None,
            developer_logical_session_id=developer_session.logical_session_id)
        try:
            # This is intentionally the sole provider dispatch in an invocation.
            result = self.runtime.execute(request)
        except BaseException as exc:
            try:
                after = inspector.capture()
                drifted = (not self._same_snapshot(pre_dispatch, after)
                    or control_state_fingerprint(pre_dispatch.canonical_root) != protected_control)
            except BaseException as inspection_exc:
                self._abnormal(intent["attempt_id"], classification="ambiguous_evidence",
                    detail="review interruption left protected-state evidence unavailable", review_failed=False,
                    error=type(exc).__name__, inspection_error=type(inspection_exc).__name__)
                raise
            classification = "protected_state_drift" if drifted else "interrupted"
            self._abnormal(intent["attempt_id"], classification=classification,
                detail=("protected repository/control state drifted during interrupted reviewer execution"
                        if drifted else "reviewer execution was interrupted before a normal terminal result"),
                review_failed=False, after=after.as_payload(), error=type(exc).__name__)
            raise
        try:
            post_dispatch = inspector.capture()
            if (not self._same_snapshot(pre_dispatch, post_dispatch)
                    or control_state_fingerprint(pre_dispatch.canonical_root) != protected_control):
                self._abnormal(intent["attempt_id"], classification="protected_state_drift",
                    detail="protected repository/control state drifted during reviewer execution", review_failed=False,
                    before=pre_dispatch.as_payload(), after=post_dispatch.as_payload())
                return None
        except BaseException as exc:
            self._abnormal(intent["attempt_id"], classification="ambiguous_evidence",
                detail="review completion protected-state evidence is unavailable", review_failed=False,
                error=type(exc).__name__)
            return None
        if result.terminal_state is not TerminalState.SUCCEEDED or not result.success:
            known_failure = result.terminal_state in {TerminalState.FAILED, TerminalState.TIMED_OUT}
            self._abnormal(intent["attempt_id"],
                classification="provider_runtime_failure" if known_failure else "interrupted",
                detail=(result.failure_detail or "reviewer runtime did not produce a successful result"),
                review_failed=known_failure, terminal_state=result.terminal_state.value,
                provider=result.provider, failure_classification=(None if result.failure_classification is None
                    else result.failure_classification.value))
            return None
        try:
            parsed = parse_reviewer_result(result.final_payload or {})
        except ValidationFailure as exc:
            self._abnormal(intent["attempt_id"], classification="malformed_result", detail=str(exc),
                review_failed=False, provider=result.provider, terminal_state=result.terminal_state.value)
            return None
        self.store.finish_review_attempt(intent["attempt_id"], reviewer_result=parsed.canonical_payload())
        return parsed
