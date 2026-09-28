"""Pure deterministic verification policy and preflight checks.

This module deliberately does not execute commands, acquire leases, or write
workflow state.  It makes the manifest and its Git binding safe inputs for a
later execution slice.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
import shutil
import signal
import select
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping
import uuid

from .domain import (ApprovedV2PlanAuthority, Stage, SuccessfulImplementationProducer,
                     ValidationFailure, VerificationOutcome, WorkflowStatus)
from .repository import RepositoryInspector, RepositorySnapshot, control_state_fingerprint
from .store import VerificationRecoveryDecision, WorkflowStore
from .process_identity import (HostBootIdentity, ProcessGroupObservation,
    local_host_boot_identity, observe_exact_process_group, owned_process_evidence)


MANIFEST_RELATIVE_PATH = ".engineering-flow/verification/manifest-v1.json"


class VerificationProcessGroupDeathUnknown(RuntimeError):
    """The owned verification process group could not be proven dead."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationFailure(f"verification manifest has duplicate field: {key}")
        result[key] = value
    return result


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class VerificationCommand:
    id: str
    argv: tuple[str, ...]
    timeout_seconds: int

    def as_payload(self) -> dict[str, object]:
        return {"id": self.id, "argv": list(self.argv), "timeout_seconds": self.timeout_seconds}


@dataclass(frozen=True, slots=True)
class VerificationManifest:
    version: int
    commands: tuple[VerificationCommand, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {"version": self.version, "commands": [command.as_payload() for command in self.commands]}

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.canonical_payload())

    def canonical_sha256(self) -> str:
        return _sha256(self.canonical_bytes())


@dataclass(frozen=True, slots=True)
class VerificationManifestBinding:
    path: str
    head_sha: str
    head_blob_sha256: str
    worktree_sha256: str
    canonical_commands_sha256: str
    manifest: VerificationManifest

    def request_hash(self, *, authority_hash: str, producer: SuccessfulImplementationProducer) -> str:
        """Hash the immutable inputs a future VERIFY request must bind."""
        if not authority_hash or not producer.operation_id:
            raise ValidationFailure("verification request binding requires authority and producer operation hashes")
        return _sha256(_canonical_json({"authority_hash": authority_hash,
            "producer_operation_id": producer.operation_id,
            "producer_execution_id": producer.execution_id,
            "producer_implementation_request_hash": producer.implementation_request_hash,
            "producer_final_repository_sha256": producer.final_repository_sha256,
            "producer_final_repository_fingerprint": producer.final_repository_fingerprint,
            "manifest_head_sha": self.head_sha,
            "manifest_blob_sha256": self.head_blob_sha256,
            "manifest_worktree_sha256": self.worktree_sha256,
            "canonical_commands_sha256": self.canonical_commands_sha256}))


@dataclass(frozen=True, slots=True)
class VerificationPreflight:
    authority: ApprovedV2PlanAuthority
    repository: RepositorySnapshot
    manifest_binding: VerificationManifestBinding
    authority_sha256: str
    producer: SuccessfulImplementationProducer
    request_hash: str


class VerificationManifestResolver:
    """Resolve only strict manifest-v1 policy from a tracked Git blob."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.path = self.root / MANIFEST_RELATIVE_PATH

    def _git(self, *args: str) -> bytes:
        try:
            result = subprocess.run(("git", "-C", os.fspath(self.root), *args), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, check=False)
        except OSError as exc:
            raise ValidationFailure(f"Git inspection unavailable: {exc}") from exc
        if result.returncode:
            raise ValidationFailure("verification manifest must be tracked in accepted HEAD")
        return result.stdout

    @staticmethod
    def parse(raw: bytes) -> VerificationManifest:
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_json_object)
        except UnicodeDecodeError as exc:
            raise ValidationFailure("verification manifest must be UTF-8 JSON") from exc
        except json.JSONDecodeError as exc:
            raise ValidationFailure(f"verification manifest JSON is malformed: {exc.msg}") from exc
        if not isinstance(value, dict) or set(value) != {"version", "commands"}:
            raise ValidationFailure("verification manifest-v1 must contain exactly version and commands")
        if value["version"] != 1 or isinstance(value["version"], bool):
            raise ValidationFailure("unsupported verification manifest version")
        commands = value["commands"]
        if not isinstance(commands, list) or not commands:
            raise ValidationFailure("verification manifest commands must be a non-empty array")
        parsed: list[VerificationCommand] = []
        seen: set[str] = set()
        for ordinal, command in enumerate(commands, 1):
            if not isinstance(command, dict) or set(command) != {"id", "argv", "timeout_seconds"}:
                raise ValidationFailure(f"verification command {ordinal} has invalid fields")
            command_id, argv, timeout = command["id"], command["argv"], command["timeout_seconds"]
            if not isinstance(command_id, str) or not command_id or not command_id.strip() or "\x00" in command_id:
                raise ValidationFailure(f"verification command {ordinal} id must be a non-empty text token")
            if command_id in seen:
                raise ValidationFailure(f"duplicate verification command id: {command_id}")
            if (not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item
                    or "\x00" in item for item in argv)):
                raise ValidationFailure(f"verification command {ordinal} argv must be a non-empty text-token array")
            if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
                raise ValidationFailure(f"verification command {ordinal} timeout_seconds must be a positive integer")
            seen.add(command_id)
            parsed.append(VerificationCommand(command_id, tuple(argv), timeout))
        return VerificationManifest(1, tuple(parsed))

    def resolve(self) -> VerificationManifestBinding:
        # ls-files establishes index/HEAD tracking rather than accepting an
        # ignored or merely present worktree file.
        self._git("ls-files", "--error-unmatch", "--", MANIFEST_RELATIVE_PATH)
        head = self._git("rev-parse", "HEAD").strip().decode("ascii", "strict")
        blob = self._git("show", f"HEAD:{MANIFEST_RELATIVE_PATH}")
        try:
            worktree = self.path.read_bytes()
        except OSError as exc:
            raise ValidationFailure("verification manifest is missing from the working tree") from exc
        if blob != worktree:
            raise ValidationFailure("verification manifest working-tree bytes differ from accepted HEAD")
        manifest = self.parse(blob)
        return VerificationManifestBinding(MANIFEST_RELATIVE_PATH, head, _sha256(blob), _sha256(worktree),
            manifest.canonical_sha256(), manifest)

    def validate_unchanged(self, expected: VerificationManifestBinding) -> VerificationManifestBinding:
        current = self.resolve()
        if current != expected:
            raise ValidationFailure("verification manifest binding changed after preflight")
        return current


def authority_binding_sha256(authority: ApprovedV2PlanAuthority, *, task_contract_id: str,
                             task_contract_sha256: str) -> str:
    """Canonical hash of immutable MDS #3 authority selected for verification."""
    task = next((item for item in authority.plan.tasks if item.id == task_contract_id), None)
    if task is None or task.payload_sha256() != task_contract_sha256:
        raise ValidationFailure("selected Task Contract does not match approved Plan authority")
    return _sha256(_canonical_json({"workflow_id": authority.workflow.id,
        "feature_artifact_id": authority.feature_contract_artifact.id,
        "feature_sha256": authority.feature_contract_artifact.sha256,
        "plan_artifact_id": authority.plan_artifact.id, "plan_sha256": authority.plan_artifact.sha256,
        "plan_id": authority.plan.id, "plan_revision": authority.plan.revision,
        "approval_id": authority.approval.id, "task_contract_id": task_contract_id,
        "task_contract_sha256": task_contract_sha256}))


class DeterministicVerificationPreflight:
    """Read-only authority, repository, and manifest gate for future VERIFY."""

    def __init__(self, root: str | Path, authority_loader: Callable[[str], ApprovedV2PlanAuthority],
                 producer_loader: Callable[[str, str, str, str], SuccessfulImplementationProducer]) -> None:
        self.root, self.authority_loader, self.producer_loader = Path(root).resolve(), authority_loader, producer_loader

    def validate(self, workflow_id: str, *, task_contract_id: str, task_contract_sha256: str,
                 producer_operation_id: str) -> VerificationPreflight:
        if not producer_operation_id:
            raise ValidationFailure("verification requires a successful producer operation")
        authority = self.authority_loader(workflow_id)
        if authority.workflow.id != workflow_id:
            raise ValidationFailure("verification authority workflow binding is invalid")
        authority_hash = authority_binding_sha256(authority, task_contract_id=task_contract_id,
            task_contract_sha256=task_contract_sha256)
        producer = self.producer_loader(workflow_id, producer_operation_id, task_contract_id, task_contract_sha256)
        if (producer.workflow_id != workflow_id or producer.operation_id != producer_operation_id
                or producer.task_contract_id != task_contract_id or producer.task_contract_sha256 != task_contract_sha256
                or (producer.feature_artifact_id, producer.feature_sha256) != (authority.feature_contract_artifact.id, authority.feature_contract_artifact.sha256)
                or (producer.plan_artifact_id, producer.plan_sha256, producer.plan_revision, producer.plan_id, producer.approval_id)
                   != (authority.plan_artifact.id, authority.plan_artifact.sha256, authority.plan.revision, authority.plan.id, authority.approval.id)):
            raise ValidationFailure("verification producer evidence does not match current approved authority")
        repository = RepositoryInspector(self.root).capture()
        if repository.fingerprint != producer.final_repository_fingerprint:
            raise ValidationFailure("repository no longer matches the producer's persisted final snapshot")
        binding = VerificationManifestResolver(self.root).resolve()
        return VerificationPreflight(authority, repository, binding, authority_hash, producer,
            binding.request_hash(authority_hash=authority_hash, producer=producer))


def classify_verification_preflight_failure(error: Exception) -> VerificationOutcome:
    """Pre-execution structural failures are blocked, not test failures."""
    return VerificationOutcome.VERIFICATION_BLOCKED if isinstance(error, ValidationFailure) else VerificationOutcome.VERIFICATION_UNKNOWN


@dataclass(frozen=True, slots=True)
class VerificationCommandExecution:
    """Bounded evidence from one argv-only verification child."""

    exit_code: int | None
    timed_out: bool
    stdout: bytes
    stderr: bytes
    output_bytes: int
    output_truncated: bool
    output_sha256: str
    spawn_error: str | None = None


class VerificationCommandRunner:
    """Execute one manifest command in a controlled, non-shell environment."""

    def __init__(self, root: str | Path, *, output_limit_bytes: int = 64 * 1024,
                 path: str | None = None) -> None:
        if type(output_limit_bytes) is not int or output_limit_bytes < 1:
            raise ValidationFailure("verification output limit must be a positive integer")
        self.root = Path(root).resolve()
        self.output_limit_bytes = output_limit_bytes
        # PATH is deliberately a policy input, not a copy of the caller's
        # environment.  The ordinary Linux executable locations are enough
        # for manifests to opt into repository-local tools explicitly.
        self.path = path or "/usr/local/bin:/usr/bin:/bin"

    def _environment(self, runtime: Path) -> dict[str, str]:
        runtime = runtime.resolve()
        if runtime.is_relative_to(self.root):
            raise ValidationFailure("verification runtime must be outside the repository")
        home, tmp, cache = runtime / "home", runtime / "tmp", runtime / "cache"
        for directory in (home, tmp, cache):
            directory.mkdir(parents=True, exist_ok=True)
        return {
            "PATH": self.path, "HOME": str(home), "TMPDIR": str(tmp),
            "XDG_CACHE_HOME": str(cache), "PIP_CACHE_DIR": str(cache / "pip"),
            "PYTHONPYCACHEPREFIX": str(cache / "pycache"), "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8", "TZ": "UTC", "CI": "true", "NO_COLOR": "1",
            "PYTHONUNBUFFERED": "1",
        }

    @staticmethod
    def _live_group_members(process_group: int) -> set[int]:
        """Return non-zombie Linux processes still in precisely this group.

        /proc is used instead of treating the leader's exit as group death.  A
        read failure is deliberately unsafe: callers must retain the durable
        lease for later reconciliation rather than guess about ownership.
        """
        try:
            entries = os.listdir("/proc")
            members: set[int] = set()
            for entry in entries:
                if not entry.isdecimal():
                    continue
                try:
                    raw = Path("/proc", entry, "stat").read_text(encoding="utf-8")
                except FileNotFoundError:
                    # A process may naturally exit between directory listing
                    # and record read; it cannot remain a live group member.
                    continue
                end = raw.rfind(")")
                fields = raw[end + 2:].split()
                if end < 0 or len(fields) < 3:
                    raise OSError("malformed /proc process record")
                if int(fields[2]) == process_group and fields[0] not in {"Z", "X"}:
                    members.add(int(entry))
            return members
        except (OSError, ValueError) as exc:
            raise RuntimeError("cannot establish verification process-group death") from exc

    @classmethod
    def _terminate_group(cls, process_group: int) -> None:
        """TERM, then KILL the still-owned group, and prove it is empty."""
        try:
            if not cls._live_group_members(process_group):
                return
        except RuntimeError as exc:
            raise VerificationProcessGroupDeathUnknown(str(exc)) from exc
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                if not cls._live_group_members(process_group):
                    return
            except RuntimeError as exc:
                raise VerificationProcessGroupDeathUnknown(str(exc)) from exc
            time.sleep(0.02)
        # Do not signal a recycled pgid: it must still have live members whose
        # recorded pgrp is the group we created before sending SIGKILL.
        try:
            remaining = cls._live_group_members(process_group)
        except RuntimeError as exc:
            raise VerificationProcessGroupDeathUnknown(str(exc)) from exc
        if remaining:
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                if not cls._live_group_members(process_group):
                    return
            except RuntimeError as exc:
                raise VerificationProcessGroupDeathUnknown(str(exc)) from exc
            time.sleep(0.02)
        raise VerificationProcessGroupDeathUnknown("verification process group did not terminate")

    def run(self, command: VerificationCommand, *, runtime_directory: str | Path,
            on_started: Callable[[Mapping[str, object]], None] | None = None) -> VerificationCommandExecution:
        """Run argv directly and return only after the owned group is dead."""
        runtime = Path(runtime_directory).resolve()
        env = self._environment(runtime)
        try:
            process = subprocess.Popen(command.argv, cwd=self.root, env=env, shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True)
        except OSError as exc:
            return VerificationCommandExecution(None, False, b"", b"", 0, False,
                _sha256(b""), f"unable to start verification command: {exc}")
        process_group = process.pid  # start_new_session makes this exact pgid.
        if on_started is not None:
            try:
                evidence = owned_process_evidence(process.pid)
                if evidence.get("process_group") != process_group:
                    raise RuntimeError("verification child process group changed before persistence")
                on_started(evidence)
            except Exception:
                try:
                    self._terminate_group(process_group)
                    process.wait(timeout=0.2)
                finally:
                    for pipe in (process.stdout, process.stderr):
                        if pipe is not None:
                            pipe.close()
                raise

        captured: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        totals = {"stdout": 0, "stderr": 0}
        digest = hashlib.sha256()
        lock = threading.Lock()

        draining = threading.Event()

        def drain(name: str, pipe: Any) -> None:
            fd = pipe.fileno()
            while not draining.is_set():
                readable, _, _ = select.select((fd,), (), (), 0.1)
                if not readable:
                    continue
                try:
                    data = os.read(fd, 8192)
                except BlockingIOError:
                    continue
                if not data:
                    return
                with lock:
                    totals[name] += len(data)
                    digest.update(name.encode("ascii") + b"\0" + data)
                    remaining = self.output_limit_bytes - len(captured[name])
                    if remaining > 0:
                        captured[name].extend(data[:remaining])

        threads = [threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
                   threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True)]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            process.wait(timeout=command.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # A zero-exit leader may leave children behind.  Always terminate
            # and prove the complete owned group dead before an inspection or
            # any durable command completion can occur.
            termination_error: Exception | None = None
            try:
                self._terminate_group(process_group)
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("verification leader survived group termination")
            except Exception as exc:
                termination_error = exc
            # Descendants outside the group can retain inherited pipes.  They
            # cannot delay completion: group death is proven above, then the
            # reader loop and descriptors are bounded locally.
            draining.set()
            for thread in threads:
                thread.join(timeout=0.5)
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
            if termination_error is not None:
                raise termination_error
        total = totals["stdout"] + totals["stderr"]
        truncated = any(totals[name] > len(captured[name]) for name in captured)
        return VerificationCommandExecution(process.returncode, timed_out, bytes(captured["stdout"]),
            bytes(captured["stderr"]), total, truncated, digest.hexdigest())


class VerificationRecoveryOutcome(Enum):
    PROCESS_ALIVE_OWNED = "process_alive_owned"
    PROCESS_DEAD_UNCHANGED = "process_dead_unchanged"
    PROCESS_DEAD_CHANGED = "process_dead_changed"
    PID_REUSED = "pid_reused"
    IDENTITY_MISMATCH = "identity_mismatch"
    DIFFERENT_MACHINE = "different_machine"
    DIFFERENT_BOOT = "different_boot"
    INCOMPLETE_IDENTITY = "incomplete_identity"
    INSPECTION_FAILURE = "inspection_failure"
    AMBIGUOUS_OWNERSHIP = "ambiguous_ownership"
    STATE_INCONSISTENT = "state_inconsistent"
    REPOSITORY_INSPECTION_FAILURE = "repository_inspection_failure"


class VerificationRecoveryService:
    """Reconcile one unresolved VERIFY attempt and always stop at recovery."""

    _OBSERVATION_OUTCOMES = {
        ProcessGroupObservation.PID_REUSED: VerificationRecoveryOutcome.PID_REUSED,
        ProcessGroupObservation.IDENTITY_MISMATCH: VerificationRecoveryOutcome.IDENTITY_MISMATCH,
        ProcessGroupObservation.DIFFERENT_MACHINE: VerificationRecoveryOutcome.DIFFERENT_MACHINE,
        ProcessGroupObservation.DIFFERENT_BOOT: VerificationRecoveryOutcome.DIFFERENT_BOOT,
        ProcessGroupObservation.INCOMPLETE_IDENTITY: VerificationRecoveryOutcome.INCOMPLETE_IDENTITY,
        ProcessGroupObservation.INSPECTION_FAILURE: VerificationRecoveryOutcome.INSPECTION_FAILURE,
        ProcessGroupObservation.AMBIGUOUS_OWNERSHIP: VerificationRecoveryOutcome.AMBIGUOUS_OWNERSHIP,
    }

    def __init__(self, store: WorkflowStore, *, identity: HostBootIdentity | None = None,
                 observer: Callable[..., ProcessGroupObservation] = observe_exact_process_group,
                 inspector_factory: Callable[[str | Path], RepositoryInspector] = RepositoryInspector) -> None:
        self.store, self.identity = store, identity
        self.observer, self.inspector_factory = observer, inspector_factory

    @staticmethod
    def _identity_evidence(lease: Mapping[str, Any], command: Mapping[str, Any] | None) -> dict[str, Any]:
        return {
            "pid": None if command is None else command.get("child_pid"),
            "process_start": None if command is None else command.get("child_process_start"),
            "process_group": None if command is None else command.get("child_process_group"),
            "process_session": None if command is None else command.get("child_process_session"),
            "machine_id": None if command is None else command.get("child_host_id"),
            "boot_id": None if command is None else command.get("child_boot_id"),
            "owner_instance_id": lease.get("owner_instance_id"),
            "owner_pid": lease.get("owner_pid"),
            "workflow_id": lease.get("workflow_id"),
            "attempt_id": lease.get("attempt_id"),
            "lease_id": lease.get("lease_id"),
            "operation_id": lease.get("operation_id"),
            "command_result_id": None if command is None else command.get("id"),
        }

    @staticmethod
    def _repository_matches(snapshot: RepositorySnapshot, baseline: Mapping[str, Any]) -> bool:
        return snapshot.fingerprint == baseline.get("fingerprint") and all(
            getattr(snapshot, field) == baseline.get(field) for field in (
                "canonical_root", "git_toplevel", "git_dir", "git_common_dir", "head_sha",
                "branch_name", "detached", "local_git_config_sha256"))

    @staticmethod
    def _persisted_repository_snapshot(value: object, *, baseline: bool = False) -> dict[str, object]:
        """Validate a persisted RepositorySnapshot, including its internal hashes."""
        snapshot_fields = {
            "canonical_root", "git_toplevel", "git_dir", "git_common_dir", "head_sha",
            "branch_name", "detached", "status_sha256", "diff_sha256",
            "untracked_manifest_sha256", "changed_paths", "changed_paths_sha256",
            "local_git_config_sha256", "fingerprint",
        }
        expected_fields = snapshot_fields | ({"control_state_fingerprint"} if baseline else set())
        if not isinstance(value, dict) or set(value) != expected_fields:
            raise ValidationFailure("verification repository inspection evidence has an invalid shape")
        text_fields = {"canonical_root", "git_toplevel", "git_dir", "git_common_dir",
            "head_sha", "branch_name"}
        if any(not isinstance(value[field], str) or not value[field] for field in text_fields):
            raise ValidationFailure("verification repository inspection identity is incomplete")
        if type(value["detached"]) is not bool:
            raise ValidationFailure("verification repository inspection detached state is invalid")
        changed_paths = value["changed_paths"]
        if (not isinstance(changed_paths, list)
                or any(not isinstance(path, str) or not path for path in changed_paths)
                or changed_paths != sorted(set(changed_paths))):
            raise ValidationFailure("verification repository changed-path evidence is invalid")
        sha_fields = {"status_sha256", "diff_sha256", "untracked_manifest_sha256",
            "changed_paths_sha256", "local_git_config_sha256", "fingerprint"}
        if baseline:
            sha_fields.add("control_state_fingerprint")
        if any(not isinstance(value[field], str) or len(value[field]) != 64
                or any(character not in "0123456789abcdef" for character in value[field])
                for field in sha_fields):
            raise ValidationFailure("verification repository inspection hash evidence is invalid")
        changed_paths_hash = hashlib.sha256(
            b"\0".join(os.fsencode(path) for path in changed_paths)).hexdigest()
        if value["changed_paths_sha256"] != changed_paths_hash:
            raise ValidationFailure("verification repository changed-path evidence is inconsistent")
        fingerprint_payload = {field: value[field] for field in snapshot_fields - {"fingerprint"}}
        fingerprint = _sha256(json.dumps(
            fingerprint_payload, sort_keys=True, separators=(",", ":")).encode())
        if value["fingerprint"] != fingerprint:
            raise ValidationFailure("verification repository fingerprint evidence is inconsistent")
        return {field: value[field] for field in snapshot_fields}

    @staticmethod
    def _validate_recovery_lifecycle(attempt: Mapping[str, Any],
                                     workflow: Mapping[str, Any] | None,
                                     task_state: Mapping[str, Any] | None,
                                     operation: Mapping[str, Any] | None,
                                     execution: Mapping[str, Any] | None, *,
                                     live_owned_projection: bool = False) -> None:
        if workflow is None or task_state is None or operation is None or execution is None:
            raise ValidationFailure("verification recovery lifecycle evidence is incomplete")
        if attempt.get("status") == "verifying":
            # A prior exact live-owned projection changes only the workflow
            # presentation to HUMAN_ATTENTION; the attempt remains actively
            # owned and must be recoverable idempotently.
            expected_status = (WorkflowStatus.HUMAN_ATTENTION.value
                if live_owned_projection else WorkflowStatus.VERIFYING.value)
            expected = ("verifying", "pending", "intent")
            if (execution.get("terminal_result") is not None
                    or attempt.get("final_inspection_json") is not None
                    or attempt.get("classification") is not None
                    or attempt.get("finished_at") is not None):
                raise ValidationFailure("verification execution result is inconsistent with active recovery")
        elif attempt.get("status") == "unknown":
            expected_status = WorkflowStatus.HUMAN_ATTENTION.value
            expected = ("implementation_completed", "unknown", "unknown")
            try:
                terminal_result = json.loads(execution["terminal_result"])
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValidationFailure("verification unknown execution result is corrupt") from exc
            if terminal_result != {"classification": "verification_unknown"}:
                raise ValidationFailure("verification unknown execution result is inconsistent")
        else:
            raise ValidationFailure("verification attempt lifecycle is invalid for recovery")
        actual = (task_state.get("status"), operation.get("status"), execution.get("lifecycle"))
        if (workflow.get("stage") != Stage.TASK_EXECUTION.value
                or workflow.get("status") != expected_status or actual != expected):
            raise ValidationFailure("verification recovery lifecycle projections are inconsistent")

    def _retain(self, lease: Mapping[str, Any], evidence: Mapping[str, Any],
                outcome: VerificationRecoveryOutcome, detail: str, *,
                authority: Mapping[str, Any] | None = None) -> VerificationRecoveryOutcome:
        payload = {"recovery_classification": outcome.value, "identity": dict(evidence)}
        if authority is not None:
            payload["authority"] = dict(authority)
        self.store.retain_verification_recovery_unknown(lease["attempt_id"], lease["lease_id"],
            owner_instance_id=lease["owner_instance_id"], final_inspection=payload, detail=detail)
        return outcome

    @staticmethod
    def _authority_evidence(attempt: Mapping[str, Any] | None) -> dict[str, Any]:
        if attempt is None:
            return {}
        return {key: attempt.get(key) for key in (
            "workflow_id", "feature_artifact_id", "feature_sha256",
            "plan_artifact_id", "plan_sha256", "plan_revision", "plan_id",
            "approval_id", "task_contract_id", "task_contract_sha256",
            "producer_operation_id", "execution_id", "operation_id", "lease_id",
            "authority_sha256", "request_hash")}

    @staticmethod
    def _binding_payload(binding: VerificationManifestBinding) -> dict[str, Any]:
        return {"path": binding.path, "head_sha": binding.head_sha,
            "head_blob_sha256": binding.head_blob_sha256,
            "worktree_sha256": binding.worktree_sha256,
            "canonical_commands_sha256": binding.canonical_commands_sha256,
            "commands": [command.as_payload() for command in binding.manifest.commands]}

    def _validate_command_evidence(self, lease: Mapping[str, Any], attempt: Mapping[str, Any],
                                   operation: Mapping[str, Any] | None,
                                   execution: Mapping[str, Any] | None,
                                   workflow: Mapping[str, Any] | None,
                                   task_state: Mapping[str, Any] | None,
                                   commands: list[Mapping[str, Any]],
                                   workflow_id: str, *,
                                   live_owned_projection: bool = False,
                                   ) -> tuple[Mapping[str, Any] | None, Mapping[str, Any]]:
        """Validate the durable command prefix against its tracked manifest."""
        if (attempt.get("workflow_id") != workflow_id
                or lease.get("workflow_id") != workflow_id
                or attempt.get("id") != lease.get("attempt_id")
                or attempt.get("lease_id") != lease.get("lease_id")
                or attempt.get("operation_id") != lease.get("operation_id")
                or attempt.get("status") not in {"verifying", "unknown"}
                or operation is None or operation.get("id") != attempt.get("operation_id")
                or operation.get("workflow_id") != workflow_id
                or operation.get("kind") != "verification"
                or operation.get("related_record_id") != attempt.get("execution_id")
                or execution is None or execution.get("id") != attempt.get("execution_id")
                or execution.get("workflow_id") != workflow_id
                or execution.get("request_hash") != attempt.get("request_hash")):
            raise ValidationFailure("verification attempt, workflow, operation, or execution linkage is inconsistent")
        self._validate_recovery_lifecycle(
            attempt, workflow, task_state, operation, execution,
            live_owned_projection=live_owned_projection)
        try:
            current_identity = self.identity or local_host_boot_identity()
        except Exception as exc:
            raise ValidationFailure("verification recovery host identity is unavailable") from exc
        canonical_root = str(Path(workflow["repository_path"]).resolve())
        if (not isinstance(lease.get("owner_instance_id"), str)
                or not lease.get("owner_instance_id")
                or type(lease.get("owner_pid")) is not int or lease.get("owner_pid") <= 0
                or not isinstance(lease.get("owner_host_id"), str) or not lease.get("owner_host_id")
                or not isinstance(lease.get("owner_boot_id"), str) or not lease.get("owner_boot_id")
                or lease.get("owner_host_id") != current_identity.host_id
                or lease.get("owner_boot_id") != current_identity.boot_id
                or lease.get("canonical_root") != canonical_root):
            raise ValidationFailure("verification persisted owner or host/boot identity is inconsistent")
        try:
            baseline = json.loads(attempt["baseline_repository_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationFailure("verification baseline repository evidence is corrupt") from exc
        baseline_repository = self._persisted_repository_snapshot(baseline, baseline=True)
        expected_control = baseline["control_state_fingerprint"]
        expected_repository_key = hashlib.sha256("\0".join((
            baseline_repository["canonical_root"], baseline_repository["git_dir"],
            baseline_repository["git_common_dir"])).encode()).hexdigest()
        if (baseline_repository["canonical_root"] != canonical_root
                or lease.get("repository_key") != expected_repository_key):
            raise ValidationFailure("verification repository identity/key is inconsistent")
        try:
            persisted_binding = json.loads(attempt["manifest_binding_json"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationFailure("verification manifest binding evidence is corrupt") from exc
        binding = VerificationManifestResolver(lease["canonical_root"]).resolve()
        if persisted_binding != self._binding_payload(binding):
            raise ValidationFailure("verification manifest binding evidence does not match authoritative manifest")
        authority = self.store.load_approved_v2_plan_authority(
            workflow_id, allow_human_attention=True)
        authoritative_hash = authority_binding_sha256(authority,
            task_contract_id=attempt["task_contract_id"],
            task_contract_sha256=attempt["task_contract_sha256"])
        producer = self.store.load_successful_implementation_producer(workflow_id,
            attempt["producer_operation_id"], attempt["task_contract_id"],
            attempt["task_contract_sha256"])
        if ((attempt.get("feature_artifact_id"), attempt.get("feature_sha256"))
                != (authority.feature_contract_artifact.id,
                    authority.feature_contract_artifact.sha256)
                or (attempt.get("plan_artifact_id"), attempt.get("plan_sha256"),
                    attempt.get("plan_revision"), attempt.get("plan_id"),
                    attempt.get("approval_id"))
                != (authority.plan_artifact.id, authority.plan_artifact.sha256,
                    authority.plan.revision, authority.plan.id, authority.approval.id)
                or attempt.get("authority_sha256") != authoritative_hash
                or (producer.feature_artifact_id, producer.feature_sha256,
                    producer.plan_artifact_id, producer.plan_sha256,
                    producer.plan_revision, producer.plan_id, producer.approval_id,
                    producer.task_contract_id, producer.task_contract_sha256)
                != (attempt.get("feature_artifact_id"), attempt.get("feature_sha256"),
                    attempt.get("plan_artifact_id"), attempt.get("plan_sha256"),
                    attempt.get("plan_revision"), attempt.get("plan_id"),
                    attempt.get("approval_id"), attempt.get("task_contract_id"),
                    attempt.get("task_contract_sha256"))
                or dict(producer.final_repository) != baseline_repository
                or attempt.get("request_hash") != binding.request_hash(
                    authority_hash=authoritative_hash, producer=producer)):
            raise ValidationFailure("verification authority binding is stale or inconsistent")
        if (task_state.get("workflow_id") != workflow_id
                or task_state.get("plan_artifact_id") != authority.plan_artifact.id
                or task_state.get("plan_sha256") != authority.plan_artifact.sha256
                or task_state.get("task_contract_id") != attempt.get("task_contract_id")
                or task_state.get("task_contract_sha256") != attempt.get("task_contract_sha256")
                or not isinstance(task_state.get("selected_at"), str)
                or not task_state.get("selected_at")
                or operation.get("idempotency_key") != f"verification:{attempt['id']}"
                or operation.get("status") not in {"pending", "unknown"}
                or execution.get("role") != "developer"
                or execution.get("request_hash") != attempt.get("request_hash")):
            raise ValidationFailure("verification task, operation, or execution authority is inconsistent")
        manifest_commands = binding.manifest.commands
        if not commands or len(commands) > len(manifest_commands):
            raise ValidationFailure("verification command evidence is incomplete or ambiguous")
        unresolved: list[Mapping[str, Any]] = []
        for ordinal, row in enumerate(commands, 1):
            expected = manifest_commands[ordinal - 1]
            try:
                argv = json.loads(row["argv_json"])
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValidationFailure("verification command argv evidence is corrupt") from exc
            if (not isinstance(row.get("id"), str) or not row.get("id")
                    or not isinstance(row.get("intent_at"), str) or not row.get("intent_at")
                    or row.get("verification_attempt_id") != attempt.get("id")
                    or row.get("ordinal") != ordinal
                    or row.get("command_id") != expected.id
                    or argv != list(expected.argv)
                    or row.get("timeout_seconds") != expected.timeout_seconds
                    or row.get("canonical_command_sha256") != DeterministicVerificationOrchestrator._command_hash(expected)):
                raise ValidationFailure("verification command evidence does not match authoritative binding")
            if row.get("result_at") is None:
                unresolved.append(row)
                if ordinal != len(commands):
                    raise ValidationFailure("verification unresolved command evidence is ambiguous")
            else:
                try:
                    inspection = json.loads(row["post_command_inspection_json"])
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise ValidationFailure("verification command result evidence is incomplete") from exc
                classification = row.get("classification")
                if (not isinstance(inspection, dict) or not isinstance(classification, str)
                        or classification not in {"passed", "failed", "timed_out", "output_limited",
                                                  "spawn_blocked", "repository_mutated"}
                        or row.get("timed_out") not in {0, 1}
                        or row.get("output_truncated") not in {0, 1}
                        or (row.get("exit_code") is not None and type(row.get("exit_code")) is not int)
                        or type(row.get("output_bytes")) is not int or row.get("output_bytes") < 0
                        or not isinstance(row.get("output_sha256"), str)
                        or len(row.get("output_sha256")) != 64
                        or any(character not in "0123456789abcdef" for character in row.get("output_sha256"))):
                    raise ValidationFailure("verification command result evidence is incomplete")
                repository = self._persisted_repository_snapshot(inspection.get("repository"))
                control = inspection.get("control_state_fingerprint")
                if (not isinstance(control, str) or len(control) != 64
                        or any(character not in "0123456789abcdef" for character in control)):
                    raise ValidationFailure("verification command control-state evidence is invalid")
                if (repository != baseline_repository or control != expected_control
                        or inspection.get("safe") is not True):
                    raise ValidationFailure("verification command inspection does not match its authoritative baseline")
                if ((classification == "passed" and (row.get("exit_code") != 0
                            or row.get("timed_out") or row.get("output_truncated")))
                        or (classification == "failed" and (row.get("exit_code") in {None, 0}
                            or row.get("timed_out") or row.get("output_truncated")))
                        or (classification == "timed_out" and row.get("timed_out") != 1)
                        or (classification == "output_limited" and
                            (row.get("timed_out") != 0 or row.get("output_truncated") != 1))
                        or (classification == "spawn_blocked" and
                            (row.get("exit_code") is not None or row.get("timed_out")
                             or row.get("output_truncated")))
                        or classification == "repository_mutated"):
                    raise ValidationFailure("verification command result classification is inconsistent")
                # A completed non-spawn result must retain the exact historical
                # process owner even though the active lease child is cleared.
                if classification != "spawn_blocked" and (
                        row.get("child_owner_instance_id") != lease.get("owner_instance_id")
                        or row.get("child_host_id") != lease.get("owner_host_id")
                        or row.get("child_boot_id") != lease.get("owner_boot_id")
                        or type(row.get("child_pid")) is not int
                        or not row.get("child_process_start")
                        or row.get("child_process_group") != row.get("child_pid")
                        or row.get("child_process_session") != row.get("child_pid")):
                    raise ValidationFailure("verification completed-command ownership evidence is incomplete")
        if len(unresolved) > 1:
            raise ValidationFailure("verification has multiple unresolved commands")
        command = unresolved[0] if unresolved else None
        if command is not None:
            if (command.get("child_owner_instance_id") != lease.get("owner_instance_id")
                    or command.get("child_pid") != lease.get("child_pid")
                    or command.get("child_process_start") != lease.get("child_process_start")
                    or command.get("child_process_group") != lease.get("child_process_group")
                    or command.get("child_process_session") != lease.get("child_process_session")
                    or command.get("child_host_id") != lease.get("owner_host_id")
                    or command.get("child_boot_id") != lease.get("owner_boot_id")):
                raise ValidationFailure("verification active command ownership evidence is inconsistent")
        elif any(lease.get(field) is not None for field in (
                "child_pid", "child_process_start", "child_process_group", "child_process_session")):
            raise ValidationFailure("verification completed-command lease still has active child identity")
        return command, commands[-1]

    def reconcile(self, workflow_id: str) -> VerificationRecoveryOutcome | None:
        """Classify persisted ownership; never signal or execute a command."""
        context = self.store.active_verification_recovery_context(workflow_id)
        if context is None:
            return None
        if context.get("ambiguous"):
            leases = context.get("leases", [])
            attempts = context.get("attempts", [])
            evidence = {
                "lease_count": len(leases), "attempt_count": len(attempts),
                "lease_ids": [item.get("lease_id") for item in leases],
                "attempt_ids": [item.get("id") for item in attempts],
            }
            self.store.retain_ambiguous_verification_recovery(workflow_id,
                evidence=evidence,
                detail="verification recovery has no single exact lease/attempt context")
            return VerificationRecoveryOutcome.STATE_INCONSISTENT
        lease, attempt, commands = context["lease"], context["attempt"], context["commands"]
        fallback_command = commands[-1] if commands else None
        evidence = self._identity_evidence(lease, fallback_command)
        authority_evidence = self._authority_evidence(attempt)
        linkage_safe = (attempt is not None and attempt.get("id") == lease.get("attempt_id")
                and attempt.get("lease_id") == lease.get("lease_id")
                and attempt.get("workflow_id") == lease.get("workflow_id")
                and attempt.get("operation_id") == lease.get("operation_id"))
        if not linkage_safe:
            self.store.retain_inconsistent_verification_lease(workflow_id=workflow_id,
                lease_id=lease["lease_id"], attempt_id=lease["attempt_id"],
                operation_id=lease["operation_id"], owner_instance_id=lease["owner_instance_id"],
                evidence=evidence,
                detail="verification attempt, lease, workflow, or operation linkage is inconsistent")
            return VerificationRecoveryOutcome.STATE_INCONSISTENT
        if context.get("command_state") not in {"UNRESOLVED", "PASSING_PREFIX", "COMPLETE_PASS"}:
            return self._retain(lease, evidence, VerificationRecoveryOutcome.STATE_INCONSISTENT,
                "verification recovery command prefix is not a valid passing prefix",
                authority=authority_evidence)
        try:
            command, last_command = self._validate_command_evidence(lease, attempt,
                context["operation"], context["execution"], context["workflow"],
                context["task_state"], commands, workflow_id,
                live_owned_projection=context.get("live_owned_projection") is True)
        except Exception as exc:
            return self._retain(lease, evidence, VerificationRecoveryOutcome.STATE_INCONSISTENT,
                f"verification recovery evidence is unsafe: {exc}",
                authority=authority_evidence)
        evidence = self._identity_evidence(lease, command or last_command)
        was_unknown = attempt.get("status") == "unknown"
        if command is not None:
            observation = self.observer(host_id=command["child_host_id"], boot_id=command["child_boot_id"],
                process_pid=command["child_pid"], process_start=command["child_process_start"],
                process_group=command["child_process_group"], process_session=command["child_process_session"],
                identity=self.identity)
            if observation is ProcessGroupObservation.ALIVE_OWNED:
                if was_unknown:
                    return self._retain(lease, evidence, VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED,
                        "verification process remains alive with exact persisted ownership",
                        authority=authority_evidence)
                self.store.project_live_verification_recovery_attention(
                    attempt["id"], lease["lease_id"], owner_instance_id=lease["owner_instance_id"],
                    command_result_id=command["id"], final_inspection={
                        "recovery_classification": VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED.value,
                        "identity": evidence, "authority": authority_evidence,
                    }, detail="verification process remains alive with exact persisted ownership")
                return VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED
            if observation is not ProcessGroupObservation.DEAD:
                outcome = self._OBSERVATION_OUTCOMES.get(observation,
                    VerificationRecoveryOutcome.AMBIGUOUS_OWNERSHIP)
                return self._retain(lease, evidence, outcome,
                    f"verification ownership is not safely reconcilable: {observation.value}",
                    authority=authority_evidence)
        try:
            baseline = json.loads(attempt["baseline_repository_json"])
            expected_control = baseline.get("control_state_fingerprint")
            if not isinstance(expected_control, str) or not expected_control:
                return self._retain(lease, evidence, VerificationRecoveryOutcome.STATE_INCONSISTENT,
                    "verification recovery baseline lacks control-state evidence",
                    authority=authority_evidence)
            snapshot = self.inspector_factory(lease["canonical_root"]).capture()
            current_control = control_state_fingerprint(lease["canonical_root"])
        except Exception as exc:
            return self._retain(lease, evidence, VerificationRecoveryOutcome.REPOSITORY_INSPECTION_FAILURE,
                f"verification recovery repository inspection failed: {exc}",
                authority=authority_evidence)
        final = {"recovery_classification": VerificationRecoveryOutcome.PROCESS_DEAD_UNCHANGED.value,
            "identity": evidence, "repository": snapshot.as_payload(),
            "control_state_fingerprint": current_control,
            "authority": authority_evidence}
        if not self._repository_matches(snapshot, baseline) or current_control != expected_control:
            final["recovery_classification"] = VerificationRecoveryOutcome.PROCESS_DEAD_CHANGED.value
            self.store.retain_verification_recovery_unknown(lease["attempt_id"], lease["lease_id"],
                owner_instance_id=lease["owner_instance_id"], final_inspection=final,
                detail="verification process is dead and the protected repository changed")
            return VerificationRecoveryOutcome.PROCESS_DEAD_CHANGED
        if was_unknown:
            self.store.retain_verification_recovery_unknown(lease["attempt_id"], lease["lease_id"],
                owner_instance_id=lease["owner_instance_id"], final_inspection=final,
                detail="verification recovery observed a dead process and unchanged repository; UNKNOWN remains sticky")
            return VerificationRecoveryOutcome.PROCESS_DEAD_UNCHANGED
        self.store.finish_interrupted_verification_recovery(VerificationRecoveryDecision(
            workflow_id=workflow_id, process_observation="dead",
            observed_identity=evidence, repository=snapshot.as_payload(),
            control_state_fingerprint=current_control, authority=authority_evidence,
            detail="verification process is dead and the protected repository is unchanged"))
        return VerificationRecoveryOutcome.PROCESS_DEAD_UNCHANGED


class DeterministicVerificationOrchestrator:
    """Run one preflight-bound VERIFY attempt without successor workflow work."""

    def __init__(self, store: WorkflowStore, root: str | Path, *, runner: VerificationCommandRunner | None = None,
                 owner_instance_id: str | None = None) -> None:
        self.store, self.root = store, Path(root).resolve()
        self.runner = runner or VerificationCommandRunner(self.root)
        self.owner_instance_id = owner_instance_id or str(uuid.uuid4())

    @staticmethod
    def _command_hash(command: VerificationCommand) -> str:
        return _sha256(_canonical_json(command.as_payload()))

    @staticmethod
    def _same_repository(before: RepositorySnapshot, after: RepositorySnapshot) -> bool:
        return before.fingerprint == after.fingerprint and (
            before.canonical_root, before.git_toplevel, before.git_dir, before.git_common_dir,
            before.head_sha, before.branch_name, before.detached, before.local_git_config_sha256,
        ) == (
            after.canonical_root, after.git_toplevel, after.git_dir, after.git_common_dir,
            after.head_sha, after.branch_name, after.detached, after.local_git_config_sha256,
        )

    def _authority_is_current(self, preflight: VerificationPreflight) -> bool:
        try:
            authority = self.store.load_approved_v2_plan_authority(preflight.authority.workflow.id,
                allow_human_attention=True)
            if authority_binding_sha256(authority, task_contract_id=preflight.producer.task_contract_id,
                task_contract_sha256=preflight.producer.task_contract_sha256) != preflight.authority_sha256:
                return False
            producer = self.store.load_successful_implementation_producer(preflight.authority.workflow.id,
                preflight.producer.operation_id, preflight.producer.task_contract_id,
                preflight.producer.task_contract_sha256)
            return producer == preflight.producer and VerificationManifestResolver(self.root).validate_unchanged(
                preflight.manifest_binding) == preflight.manifest_binding
        except Exception:
            return False

    def run(self, preflight: VerificationPreflight) -> VerificationOutcome:
        """Persist intent, execute each command serially, and terminally project its outcome."""
        inspector = RepositoryInspector(self.root)
        try:
            host_identity = local_host_boot_identity()
            # Slice 3 deliberately has no recovery authority.  An unfinished
            # attempt (including one with an unresolved command intent) stays
            # wholly intact for Slice 4; it is never execution authorization.
            existing = self.store.find_verification_attempt(preflight.authority.workflow.id,
                preflight.producer.operation_id, preflight.request_hash)
            if existing is not None and (existing["status"] != "terminal"
                    or existing["classification"] != "interrupted_unchanged"):
                return VerificationOutcome.VERIFICATION_BLOCKED
            initial = inspector.capture()
            if not self._same_repository(preflight.repository, initial):
                return VerificationOutcome.VERIFICATION_BLOCKED
            initial_payload = initial.as_payload()
            initial_payload["control_state_fingerprint"] = control_state_fingerprint(self.root)
            intent = self.store.create_verification_intent(preflight.authority.workflow.id,
                repository_key=inspector.repository_key(), canonical_root=initial.canonical_root,
                producer_operation_id=preflight.producer.operation_id,
                task_contract_id=preflight.producer.task_contract_id,
                task_contract_sha256=preflight.producer.task_contract_sha256,
                authority_sha256=preflight.authority_sha256, request_hash=preflight.request_hash,
                manifest_binding={"path": preflight.manifest_binding.path, "head_sha": preflight.manifest_binding.head_sha,
                    "head_blob_sha256": preflight.manifest_binding.head_blob_sha256,
                    "worktree_sha256": preflight.manifest_binding.worktree_sha256,
                    "canonical_commands_sha256": preflight.manifest_binding.canonical_commands_sha256,
                    "commands": [command.as_payload()
                                 for command in preflight.manifest_binding.manifest.commands]},
                baseline=initial_payload, owner_instance_id=self.owner_instance_id, owner_pid=os.getpid(),
                owner_host_id=host_identity.host_id, owner_boot_id=host_identity.boot_id)
        except Exception:
            return VerificationOutcome.VERIFICATION_BLOCKED

        # Store writes are expected control changes.  The protected baseline is
        # therefore taken after lease acquisition and before the first spawn.
        try:
            baseline = inspector.capture()
            baseline_control = control_state_fingerprint(self.root)
        except Exception as exc:
            self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"],
                owner_instance_id=self.owner_instance_id, outcome="verification_unknown", final_inspection={}, detail=str(exc))
            return VerificationOutcome.VERIFICATION_UNKNOWN
        # Do not permit verifier-created HOME, TMPDIR, cache, or runtime bytes
        # onto the protected repository surface.  /tmp is explicit so an
        # ambient TMPDIR cannot redirect us back into the checkout.
        runtime = Path(tempfile.mkdtemp(prefix="engineering-flow-verification-", dir="/tmp")).resolve()
        if runtime.is_relative_to(self.root):
            # This should be impossible with the explicit /tmp, but remains a
            # fail-closed guard for unusual filesystem topology.
            self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"],
                owner_instance_id=self.owner_instance_id, outcome="verification_unknown",
                final_inspection={"runtime_directory": str(runtime)},
                detail="verification runtime directory overlaps the protected repository")
            return VerificationOutcome.VERIFICATION_UNKNOWN
        outcome, detail, final = VerificationOutcome.VERIFIED, None, baseline.as_payload()
        try:
            for ordinal, command in enumerate(preflight.manifest_binding.manifest.commands, 1):
                if not self._authority_is_current(preflight):
                    outcome, detail = VerificationOutcome.VERIFICATION_BLOCKED, "verification authority changed before command"
                    break
                command_id = self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"],
                    owner_instance_id=self.owner_instance_id, ordinal=ordinal, command_id=command.id,
                    canonical_command_sha256=self._command_hash(command), argv=command.argv,
                    timeout_seconds=command.timeout_seconds)
                result = self.runner.run(command, runtime_directory=runtime / str(ordinal),
                    on_started=lambda evidence: self.store.record_verification_command_started(
                        intent["attempt_id"], intent["lease_id"], command_id,
                        owner_instance_id=self.owner_instance_id, child_pid=evidence["pid"],
                        child_process_start=evidence["process_start"], child_process_group=evidence["process_group"],
                        child_process_session=evidence["process_session"],
                        child_host_id=host_identity.host_id, child_boot_id=host_identity.boot_id))
                try:
                    after = inspector.capture()
                    control_ok = control_state_fingerprint(self.root) == baseline_control
                    final = after.as_payload()
                    safe = self._same_repository(baseline, after) and control_ok
                    inspection = {"repository": final, "control_state_fingerprint": control_state_fingerprint(self.root),
                                  "safe": safe}
                except Exception as exc:
                    safe, inspection = False, {"error": str(exc)}
                    final = inspection
                classification = ("spawn_blocked" if result.spawn_error else "timed_out" if result.timed_out
                    else "output_limited" if result.output_truncated else "passed" if result.exit_code == 0 and safe
                    else "repository_mutated" if not safe else "failed")
                self.store.record_verification_command_result(intent["attempt_id"], intent["lease_id"], command_id,
                    owner_instance_id=self.owner_instance_id, exit_code=result.exit_code, timed_out=result.timed_out,
                    output_sha256=result.output_sha256, output_bytes=result.output_bytes,
                    output_truncated=result.output_truncated, post_command_inspection=inspection,
                    classification=classification)
                if not safe:
                    outcome, detail = VerificationOutcome.VERIFICATION_UNKNOWN, "protected repository surface changed"
                    break
                if result.spawn_error:
                    outcome, detail = VerificationOutcome.VERIFICATION_BLOCKED, result.spawn_error
                    break
                if result.timed_out or result.output_truncated or result.exit_code != 0:
                    outcome, detail = VerificationOutcome.VERIFICATION_FAILED, classification
                    break
        except VerificationProcessGroupDeathUnknown as exc:
            recovery = self.store.active_verification_recovery_context(
                preflight.authority.workflow.id)
            retained = final
            if recovery is not None:
                unresolved = [item for item in recovery["commands"] if item.get("result_at") is None]
                command = unresolved[0] if len(unresolved) == 1 else None
                retained = {"repository": final, "identity": VerificationRecoveryService._identity_evidence(
                    recovery["lease"], command)}
            self.store.retain_verification_unknown(intent["attempt_id"], intent["lease_id"],
                owner_instance_id=self.owner_instance_id, final_inspection=retained, detail=str(exc))
            shutil.rmtree(runtime, ignore_errors=True)
            return VerificationOutcome.VERIFICATION_UNKNOWN
        except Exception as exc:
            outcome, detail = VerificationOutcome.VERIFICATION_UNKNOWN, str(exc)
        self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"],
            owner_instance_id=self.owner_instance_id, outcome=outcome.value, final_inspection=final, detail=detail)
        shutil.rmtree(runtime, ignore_errors=True)
        return outcome
