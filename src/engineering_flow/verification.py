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
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from .domain import (ApprovedV2PlanAuthority, SuccessfulImplementationProducer,
                     ValidationFailure, VerificationOutcome)
from .repository import RepositoryInspector, RepositorySnapshot


MANIFEST_RELATIVE_PATH = ".engineering-flow/verification/manifest-v1.json"


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
