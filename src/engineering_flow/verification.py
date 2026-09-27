"""Pure deterministic verification policy and preflight checks.

This module deliberately does not execute commands, acquire leases, or write
workflow state.  It makes the manifest and its Git binding safe inputs for a
later execution slice.
"""
from __future__ import annotations

from dataclasses import dataclass
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

from .domain import (ApprovedV2PlanAuthority, SuccessfulImplementationProducer,
                     ValidationFailure, VerificationOutcome)
from .repository import RepositoryInspector, RepositorySnapshot, control_state_fingerprint
from .store import WorkflowStore
from .process_identity import local_host_boot_identity, owned_process_evidence


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
            intent = self.store.create_verification_intent(preflight.authority.workflow.id,
                repository_key=inspector.repository_key(), canonical_root=initial.canonical_root,
                producer_operation_id=preflight.producer.operation_id,
                task_contract_id=preflight.producer.task_contract_id,
                task_contract_sha256=preflight.producer.task_contract_sha256,
                authority_sha256=preflight.authority_sha256, request_hash=preflight.request_hash,
                manifest_binding={"path": preflight.manifest_binding.path, "head_sha": preflight.manifest_binding.head_sha,
                    "head_blob_sha256": preflight.manifest_binding.head_blob_sha256,
                    "worktree_sha256": preflight.manifest_binding.worktree_sha256,
                    "canonical_commands_sha256": preflight.manifest_binding.canonical_commands_sha256},
                baseline=initial.as_payload(), owner_instance_id=self.owner_instance_id, owner_pid=os.getpid(),
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
            self.store.retain_verification_unknown(intent["attempt_id"], intent["lease_id"],
                owner_instance_id=self.owner_instance_id, final_inspection=final, detail=str(exc))
            shutil.rmtree(runtime, ignore_errors=True)
            return VerificationOutcome.VERIFICATION_UNKNOWN
        except Exception as exc:
            outcome, detail = VerificationOutcome.VERIFICATION_UNKNOWN, str(exc)
        self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"],
            owner_instance_id=self.owner_instance_id, outcome=outcome.value, final_inspection=final, detail=detail)
        shutil.rmtree(runtime, ignore_errors=True)
        return outcome
