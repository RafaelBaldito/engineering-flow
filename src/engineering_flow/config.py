"""Repository-local configuration for the Engineering Flow control plane."""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .domain import ApprovalPolicy, ValidationFailure


APPLICATION_DIRECTORY = ".engineering-flow"
CONFIG_FILENAME = "config.toml"
DATABASE_FILENAME = "workflows.sqlite3"
INITIAL_CONFIG = """[provider]
name = "codex-cli"
command = "codex"
timeout_seconds = 1800

[approval]
prd = "required"
techspec = "required"
task_plan = "required"

[safety]
allow_read_only_planning = true
"""

_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?key|secret|token|password|passwd|"
    r"authorization|credential|private[_-]?key)\s*(?:=|:)|"
    r"--?(?:api[_-]?key|access[_-]?key|secret|token|password|passwd|"
    r"authorization|credential|private[_-]?key)\b(?:\s|=|$)|"
    r"\bBearer\s+|\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b"
)
_ALLOWED_SECTIONS = frozenset({"provider", "approval", "safety"})
_ALLOWED_PROVIDER_KEYS = frozenset({"name", "command", "timeout_seconds"})
_ALLOWED_APPROVAL_KEYS = frozenset({"prd", "techspec", "task_plan"})
_ALLOWED_SAFETY_KEYS = frozenset({"allow_read_only_planning"})


def _resolved_directory(value: str | Path, label: str) -> Path:
    try:
        path = Path(value).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValidationFailure(f"invalid {label} path") from exc
    if not path.is_dir():
        raise ValidationFailure(f"{label} is not a directory: {path}")
    return path


def application_path(repository: str | Path) -> Path:
    """Return the canonical repository-local application workspace path."""

    canonical_repository = _resolved_directory(repository, "repository")
    application = (canonical_repository / APPLICATION_DIRECTORY).resolve()
    try:
        application.relative_to(canonical_repository)
    except ValueError as exc:
        raise ValidationFailure("application directory escapes the repository") from exc
    return application


def application_owned_path(application: str | Path, filename: str, label: str) -> Path:
    """Return a canonical application-owned file path, rejecting link escapes."""

    try:
        path = (Path(application).expanduser() / filename).resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValidationFailure(f"invalid {label} path") from exc
    try:
        path.relative_to(application)
    except ValueError as exc:
        raise ValidationFailure(f"{label} path escapes the application directory") from exc
    return path


def is_git_worktree(repository: str | Path) -> bool:
    """Return whether *repository* is a real, non-bare Git worktree."""

    try:
        path = Path(repository).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if not path.is_dir():
        return False
    marker = path / ".git"
    if marker.is_dir():
        structural = all((marker / name).is_file() for name in ("HEAD", "config"))
        structural = structural and (marker / "objects").is_dir() and (marker / "refs").is_dir()
    elif marker.is_file():
        try:
            content = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if not content.lower().startswith("gitdir:"):
            return False
        gitdir = Path(content.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = (path / gitdir).resolve()
        if (gitdir / "config").is_file():
            structural = (gitdir / "HEAD").is_file()
        elif (gitdir / "commondir").is_file():
            try:
                common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
            except OSError:
                return False
            structural = (gitdir / "HEAD").is_file() and (common / "config").is_file()
        else:
            structural = False
    else:
        return False
    if not structural:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree", "--is-bare-repository"],
            cwd=str(path), shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and [line.strip().lower() for line in result.stdout.splitlines()] == ["true", "false"]


def _validate_mapping(value: Any, label: str, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationFailure(f"{label} must be a table")
    unknown = set(value) - allowed
    if unknown:
        raise ValidationFailure(f"unknown {label} setting: {sorted(unknown)[0]}")
    missing = allowed - set(value)
    if missing:
        raise ValidationFailure(f"missing {label} setting: {sorted(missing)[0]}")
    return dict(value)


def _reject_credentials(value: Any, path: str = "config") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if _CREDENTIAL_PATTERN.search(key_text):
                raise ValidationFailure(f"credentials are not permitted in {path}.{key_text}")
            _reject_credentials(child, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_credentials(child, f"{path}[{index}]")
    elif isinstance(value, str) and _CREDENTIAL_PATTERN.search(value):
        raise ValidationFailure(f"credential-shaped value is not permitted in {path}")


@dataclass(frozen=True, slots=True)
class FlowConfig:
    """Validated, canonical repository configuration."""

    repository_path: Path
    application_path: Path
    config_path: Path
    database_path: Path
    provider_name: str
    provider_command: str
    timeout_seconds: float
    approval_policies: Mapping[str, ApprovalPolicy]
    allow_read_only_planning: bool

    @property
    def provider(self) -> str:
        return self.provider_name

    @property
    def command(self) -> str:
        return self.provider_command

    @property
    def approvals(self) -> Mapping[str, ApprovalPolicy]:
        return self.approval_policies

    @property
    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": {
                "name": self.provider_name,
                "command": self.provider_command,
                "timeout_seconds": self.timeout_seconds if self.timeout_seconds % 1 else int(self.timeout_seconds),
            },
            "approval": {key: policy.value for key, policy in self.approval_policies.items()},
            "safety": {"allow_read_only_planning": self.allow_read_only_planning},
        }

    @classmethod
    def load(cls, repository_path: str | Path) -> "FlowConfig":
        return load_config(repository_path)


def load_config(repository_path: str | Path) -> FlowConfig:
    repository = _resolved_directory(repository_path, "repository")
    if not is_git_worktree(repository):
        raise ValidationFailure(f"target repository is not a Git worktree: {repository}")
    application = application_path(repository)
    config_path = application_owned_path(application, CONFIG_FILENAME, "configuration")
    database_path = application_owned_path(application, DATABASE_FILENAME, "database")
    if not config_path.is_file():
        raise ValidationFailure(f"configuration file not found: {config_path}")
    try:
        with config_path.open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValidationFailure(f"invalid configuration: {exc}") from exc
    if not isinstance(raw, Mapping) or set(raw) != _ALLOWED_SECTIONS:
        raise ValidationFailure("configuration must contain provider, approval, and safety tables")
    _reject_credentials(raw)
    provider = _validate_mapping(raw["provider"], "provider", _ALLOWED_PROVIDER_KEYS)
    approval = _validate_mapping(raw["approval"], "approval", _ALLOWED_APPROVAL_KEYS)
    safety = _validate_mapping(raw["safety"], "safety", _ALLOWED_SAFETY_KEYS)
    if provider["name"] != "codex-cli":
        raise ValidationFailure("only the codex-cli provider is supported in Wave 1")
    if (
        not isinstance(provider["command"], str)
        or not provider["command"].strip()
        or any(char.isspace() for char in provider["command"])
    ):
        raise ValidationFailure(
            "provider.command must be a single non-empty executable name or path without arguments"
        )
    timeout = provider["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValidationFailure("provider.timeout_seconds must be positive")
    parsed_policies: dict[str, ApprovalPolicy] = {}
    for stage, value in approval.items():
        try:
            parsed_policies[stage] = ApprovalPolicy(value)
        except (TypeError, ValueError) as exc:
            raise ValidationFailure(f"invalid approval policy for {stage}: {value!r}") from exc
    if safety["allow_read_only_planning"] is not True:
        raise ValidationFailure("safety.allow_read_only_planning must be true")
    return FlowConfig(
        repository, application, config_path, database_path,
        "codex-cli", provider["command"].strip(), float(timeout), parsed_policies, True,
    )


Config = FlowConfig


__all__ = [
    "APPLICATION_DIRECTORY", "CONFIG_FILENAME", "DATABASE_FILENAME", "INITIAL_CONFIG",
    "Config", "FlowConfig", "application_owned_path", "application_path", "is_git_worktree", "load_config",
]
