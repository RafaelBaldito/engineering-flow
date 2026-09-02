"""Safe, bounded adapter for the Codex command-line planning runtime."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from queue import Empty, Queue
from pathlib import Path
from typing import Any

from .domain import FailureClassification, ValidationFailure
from .runtime import (
    AgentRuntime,
    CapabilityReport,
    NormalizedEvent,
    PlanningExecutionRequest,
    PlanningExecutionResult,
    TerminalState,
)
from .sanitization import sanitize_payload, sanitize_text


FINAL_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "artifact_markdown",
        "summary",
        "requires_human_approval",
        "approval_reason",
    ],
    "properties": {
        "artifact_markdown": {"type": "string", "minLength": 1},
        "summary": {"type": "string"},
        "requires_human_approval": {"type": "boolean"},
        "approval_reason": {"type": "string"},
    },
}

_AUTHENTICATION_ERROR = re.compile(
    r"(?i)(authentication|unauthori[sz]ed|invalid\s+(?:api\s*)?key|"
    r"login required|missing credentials|not logged in|\b401\b|credential)"
)
_SUCCESS_EVENTS = frozenset({
    "turn.completed",
    "response.completed",
    "task.completed",
    "completed",
})
_FAILURE_EVENTS = frozenset({
    "error",
    "turn.failed",
    "turn.aborted",
    "response.failed",
    "task.failed",
})


def _minimal_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Keep only process settings needed to find and authenticate the CLI."""

    source = source or os.environ
    allowed = {
        "PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
        "CODEX_HOME", "TEMP", "TMP", "TMPDIR", "SYSTEMROOT", "WINDIR", "PATHEXT",
        "LANG", "LC_ALL", "TERM",
    }
    return {key: str(value) for key, value in source.items() if key in allowed}


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class CodexCliRuntime(AgentRuntime):
    """Execute read-only planning through ``codex exec`` without a shell."""

    provider = "codex-cli"

    def __init__(
        self,
        command: str = "codex",
        *,
        timeout_seconds: float = 1800,
        allow_read_only_planning: bool = True,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        run_factory: Callable[..., Any] = subprocess.run,
        executable_resolver: Callable[[str], str | None] = shutil.which,
        git_runner: Callable[..., Any] = subprocess.run,
        environment: Mapping[str, str] | None = None,
        secret_values: tuple[str, ...] = (),
    ) -> None:
        if not command:
            raise ValueError("Codex executable command is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.allow_read_only_planning = allow_read_only_planning
        self._popen = popen_factory
        self._run = run_factory
        self._resolve_executable = executable_resolver
        self._git_runner = git_runner
        self._environment = dict(environment) if environment is not None else None
        self._secret_values = tuple(secret_values)

    def _resolved_executable(self) -> str | None:
        command_path = Path(self.command).expanduser()
        if command_path.is_absolute() or command_path.parent != Path("."):
            return str(command_path.resolve()) if command_path.is_file() else None
        return self._resolve_executable(self.command)

    @staticmethod
    def _is_git_worktree(repository: Path) -> bool:
        """Perform a read-only structural check before invoking Git."""

        if not repository.is_dir():
            return False
        marker = repository / ".git"
        if marker.is_dir():
            return all(
                (marker / required).is_file()
                for required in ("HEAD", "config")
            ) and (marker / "objects").is_dir() and (marker / "refs").is_dir()
        if not marker.is_file():
            return False
        try:
            content = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if not content.lower().startswith("gitdir:"):
            return False
        gitdir = Path(content.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = (repository / gitdir).resolve()
        if not (gitdir / "HEAD").is_file():
            return False
        if (gitdir / "config").is_file():
            return True
        commondir = gitdir / "commondir"
        if not commondir.is_file():
            return False
        try:
            common = (gitdir / commondir.read_text(encoding="utf-8").strip()).resolve()
        except OSError:
            return False
        return (common / "config").is_file()

    def _verified_git_worktree(self, repository: Path) -> bool:
        if not self._is_git_worktree(repository):
            return False
        try:
            completed = self._git_runner(
                ["git", "-C", str(repository), "rev-parse", "--is-inside-work-tree", "--is-bare-repository"],
                cwd=str(repository),
                env=_minimal_environment(self._environment),
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(self.timeout_seconds, 30),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if getattr(completed, "returncode", 1) != 0:
            return False
        values = _as_text(getattr(completed, "stdout", "")).splitlines()
        return [value.strip().lower() for value in values] == ["true", "false"]

    def _help_result(self, repository: Path) -> tuple[bool, str]:
        try:
            completed = self._run(
                [self.command, "exec", "--help"],
                cwd=str(repository),
                env=_minimal_environment(self._environment),
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(self.timeout_seconds, 30),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, sanitize_text(str(exc), self._secret_values)
        output = _as_text(getattr(completed, "stdout", ""))
        error = _as_text(getattr(completed, "stderr", ""))
        if getattr(completed, "returncode", 1) != 0:
            return False, sanitize_text(error or output or "codex exec capability check failed", self._secret_values)
        help_text = f"{output}\n{error}".lower()
        required = {
            "json_events": "--json" in help_text,
            "output_schema": "--output-schema" in help_text,
            "output_last_message": "--output-last-message" in help_text,
            "read_only_sandbox": "--sandbox" in help_text and "read-only" in help_text,
        }
        missing = [name for name, supported in required.items() if not supported]
        if missing:
            return False, f"codex exec is missing capabilities: {', '.join(missing)}"
        return True, ""

    def verify_planning_capabilities(self, repository: str | Path) -> CapabilityReport:
        repository_path = Path(repository).expanduser().resolve()
        capabilities: dict[str, bool] = {
            "executable": False,
            "git_worktree": False,
            "json_events": False,
            "output_schema": False,
            "output_last_message": False,
            "read_only_sandbox": False,
        }
        if not self.allow_read_only_planning:
            return CapabilityReport(
                self.provider, self.command, str(repository_path), False, capabilities, False,
                FailureClassification.WORKFLOW,
                "read-only planning is disabled by configuration",
            )
        if self._resolved_executable() is None:
            return CapabilityReport(
                self.provider, self.command, str(repository_path), False, capabilities, True,
                FailureClassification.PROVIDER, "configured Codex executable was not found",
            )
        capabilities["executable"] = True
        if not self._verified_git_worktree(repository_path):
            return CapabilityReport(
                self.provider, self.command, str(repository_path), False, capabilities, True,
                FailureClassification.WORKFLOW, "target repository is not a Git worktree",
            )
        capabilities["git_worktree"] = True
        supported, detail = self._help_result(repository_path)
        if not supported:
            return CapabilityReport(
                self.provider, self.command, str(repository_path), False, capabilities, True,
                FailureClassification.PROVIDER, detail,
            )
        capabilities.update(
            json_events=True,
            output_schema=True,
            output_last_message=True,
            read_only_sandbox=True,
        )
        return CapabilityReport(
            self.provider, self.command, str(repository_path), True, capabilities, True,
        )

    @staticmethod
    def _write_schema(path: Path) -> None:
        encoded = json.dumps(FINAL_OUTPUT_SCHEMA, indent=2, sort_keys=True) + "\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.read_text(encoding="utf-8") != encoded:
                    raise ValidationFailure("output schema path already contains different content")
            else:
                path.write_text(encoded, encoding="utf-8", newline="")
        except OSError as exc:
            raise ValidationFailure(f"could not retain output schema: {exc}") from exc

    def _process(self, request: PlanningExecutionRequest) -> Any:
        argv = [
            self.command,
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(Path(request.output_schema_path).expanduser().resolve()),
            "--output-last-message",
            str(Path(request.final_output_path).expanduser().resolve()),
            request.instruction,
        ]
        return self._popen(
            argv,
            cwd=str(Path(request.repository_path).expanduser().resolve()),
            env=_minimal_environment(self._environment),
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def _normalize_line(
        self,
        line: str,
        line_number: int,
        state: dict[str, Any],
        events: list[NormalizedEvent],
    ) -> None:
        if not line.strip():
            return
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            state["malformed"] = True
            events.append(NormalizedEvent(
                "runtime.malformed_output",
                {"line": line_number, "detail": sanitize_text(str(exc), self._secret_values)},
            ))
            return
        if not isinstance(raw, Mapping):
            state["malformed"] = True
            events.append(NormalizedEvent(
                "runtime.malformed_output",
                {"line": line_number, "detail": "JSON event is not an object"},
            ))
            return
        event_type = raw.get("type")
        if not isinstance(event_type, str) or not event_type:
            state["malformed"] = True
            events.append(NormalizedEvent(
                "runtime.malformed_output",
                {"line": line_number, "detail": "JSON event has no type"},
            ))
            return
        safe = sanitize_payload(raw, self._secret_values)
        provider_event_id = raw.get("id") if isinstance(raw.get("id"), str) else None
        timestamp = raw.get("timestamp") if isinstance(raw.get("timestamp"), str) else None
        events.append(NormalizedEvent(event_type, safe, provider_event_id, timestamp))
        if event_type == "thread.started":
            candidate = raw.get("thread_id") or raw.get("threadId") or raw.get("id")
            if isinstance(candidate, str):
                state["provider_session_id"] = candidate
        if event_type in _SUCCESS_EVENTS:
            candidate = raw.get("id")
            if isinstance(candidate, str):
                state["provider_execution_id"] = candidate
            if isinstance(raw.get("usage"), Mapping):
                state["usage"] = dict(sanitize_payload(raw["usage"], self._secret_values))
        if event_type in _FAILURE_EVENTS:
            state["failure_seen"] = True

    def _normalize_lines(self, stdout: str) -> tuple[list[NormalizedEvent], str | None, str | None, bool, bool, dict[str, Any]]:
        events: list[NormalizedEvent] = []
        state: dict[str, Any] = {
            "provider_session_id": None,
            "provider_execution_id": None,
            "malformed": False,
            "failure_seen": False,
            "usage": {},
        }
        for line_number, line in enumerate(stdout.splitlines(), 1):
            self._normalize_line(line, line_number, state, events)
        return (
            events,
            state["provider_session_id"],
            state["provider_execution_id"],
            state["malformed"],
            state["failure_seen"],
            state["usage"],
        )

    def _stream_process(
        self,
        process: Any,
        timeout_seconds: float,
        state: dict[str, Any],
        events: list[NormalizedEvent],
    ) -> tuple[bool, str]:
        """Read JSONL as it arrives while retaining only bounded stderr."""

        stdout_stream = getattr(process, "stdout", None)
        stderr_stream = getattr(process, "stderr", None)
        if stdout_stream is None or stderr_stream is None:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            for line_number, line in enumerate(_as_text(stdout).splitlines(), 1):
                self._normalize_line(line, line_number, state, events)
            return False, _as_text(stderr)[-4000:]

        lines: Queue[str] = Queue()
        stderr_parts: deque[str] = deque()
        stderr_length = 0

        def read_stdout() -> None:
            try:
                for line in iter(stdout_stream.readline, ""):
                    lines.put(line)
            except (OSError, ValueError):
                pass

        def read_stderr() -> None:
            nonlocal stderr_length
            try:
                for line in iter(stderr_stream.readline, ""):
                    if len(line) >= 4000:
                        stderr_parts.clear()
                        stderr_parts.append(line[-4000:])
                        stderr_length = 4000
                        continue
                    stderr_parts.append(line)
                    stderr_length += len(line)
                    while stderr_length > 4000 and stderr_parts:
                        stderr_length -= len(stderr_parts.popleft())
            except (OSError, ValueError):
                pass

        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        deadline = time.monotonic() + timeout_seconds
        line_number = 0
        timed_out = False
        poll = getattr(process, "poll", lambda: 0)
        while stdout_thread.is_alive() or not lines.empty() or poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                try:
                    process.kill()
                except OSError:
                    pass
                break
            try:
                line = lines.get(timeout=min(0.1, remaining))
            except Empty:
                continue
            line_number += 1
            self._normalize_line(line, line_number, state, events)
        while True:
            try:
                line = lines.get_nowait()
            except Empty:
                break
            line_number += 1
            self._normalize_line(line, line_number, state, events)
        stdout_thread.join(timeout=0.2)
        stderr_thread.join(timeout=0.2)
        return timed_out, "".join(stderr_parts)[-4000:]

    def _read_final_payload(self, path: Path, events: list[NormalizedEvent]) -> tuple[dict[str, Any] | None, str | None]:
        raw_payload: Any = None
        if path.is_file():
            try:
                raw_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return None, f"final output is not valid JSON: {sanitize_text(str(exc), self._secret_values)}"
        else:
            # Fixture runtimes and older CLI builds may place the structured
            # response in a JSON event. Never use progress text as content.
            for event in reversed(events):
                candidate = event.payload
                for nested_key in ("final_output", "final_response", "response", "payload"):
                    nested = candidate.get(nested_key)
                    if isinstance(nested, Mapping):
                        candidate = nested
                        break
                if all(key in candidate for key in FINAL_OUTPUT_SCHEMA["required"]):
                    raw_payload = candidate
                    break
        if not isinstance(raw_payload, Mapping):
            return None, "final structured output is missing"
        required = set(FINAL_OUTPUT_SCHEMA["required"])
        if set(raw_payload) != required:
            return None, "final structured output does not match the approved schema"
        if not isinstance(raw_payload["artifact_markdown"], str) or not raw_payload["artifact_markdown"].strip():
            return None, "artifact_markdown must be non-empty Markdown"
        if not isinstance(raw_payload["summary"], str):
            return None, "summary must be a string"
        if type(raw_payload["requires_human_approval"]) is not bool:
            return None, "requires_human_approval must be a boolean"
        if not isinstance(raw_payload["approval_reason"], str):
            return None, "approval_reason must be a string"
        return {key: raw_payload[key] for key in FINAL_OUTPUT_SCHEMA["required"]}, None

    def execute_planning(self, request: PlanningExecutionRequest) -> PlanningExecutionResult:
        logical_session_id = request.logical_session_id or request.execution_id
        report = self.verify_planning_capabilities(request.repository_path)
        if not report.available:
            raise ValidationFailure(
                report.failure_detail or "Codex planning capabilities are unavailable",
                details={"capability_report": report.capabilities},
            )
        schema_path = Path(request.output_schema_path).expanduser().resolve()
        final_output_path = Path(request.final_output_path).expanduser().resolve()
        self._write_schema(schema_path)
        process: Any
        try:
            process = self._process(request)
        except OSError as exc:
            detail = sanitize_text(str(exc), self._secret_values)
            return PlanningExecutionResult(
                self.provider, logical_session_id, None, None, TerminalState.FAILED, None,
                metadata={"detail": detail}, failure_classification=FailureClassification.PROVIDER,
                failure_detail=detail,
            )
        timed_out = False
        stdout_text = ""
        stderr_text = ""
        state: dict[str, Any] = {
            "provider_session_id": None,
            "provider_execution_id": None,
            "malformed": False,
            "failure_seen": False,
            "usage": {},
        }
        events: list[NormalizedEvent] = []
        try:
            timed_out, stderr_text = self._stream_process(
                process, request.timeout_seconds, state, events
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            try:
                process.kill()
            except OSError:
                pass
            try:
                stdout, stderr = process.communicate()
            except OSError:
                stdout, stderr = exc.stdout, exc.stderr
            stdout_text = _as_text(stdout)
            stderr_text = _as_text(stderr)
            for line_number, line in enumerate(stdout_text.splitlines(), 1):
                self._normalize_line(line, line_number, state, events)
        provider_session_id = state["provider_session_id"]
        provider_execution_id = state["provider_execution_id"]
        malformed = state["malformed"]
        failure_seen = state["failure_seen"]
        usage = state["usage"]
        returncode = getattr(process, "returncode", None)
        safe_stderr = sanitize_text(stderr_text[-4000:], self._secret_values)
        if timed_out:
            detail = f"Codex planning exceeded {request.timeout_seconds:g} seconds"
            return PlanningExecutionResult(
                self.provider, logical_session_id, provider_session_id, provider_execution_id,
                TerminalState.TIMED_OUT, None, usage, tuple(events), {"returncode": returncode, "stderr": safe_stderr},
                FailureClassification.AGENT_EXECUTION, detail,
            )
        if returncode not in (0, None):
            diagnostic = safe_stderr or "Codex process exited unsuccessfully"
            event_diagnostics = " ".join(
                sanitize_text(json.dumps(event.payload, sort_keys=True), self._secret_values)
                for event in events
            )
            classification = (
                FailureClassification.AUTHENTICATION
                if _AUTHENTICATION_ERROR.search(f"{diagnostic} {event_diagnostics}")
                else FailureClassification.PROVIDER
            )
            return PlanningExecutionResult(
                self.provider, logical_session_id, provider_session_id, provider_execution_id,
                TerminalState.FAILED, None, usage, tuple(events), {"returncode": returncode, "stderr": diagnostic},
                classification, diagnostic,
            )
        event_diagnostics = " ".join(
            sanitize_text(json.dumps(event.payload, sort_keys=True), self._secret_values)
            for event in events
        )
        if _AUTHENTICATION_ERROR.search(event_diagnostics):
            detail = "Codex authentication failed"
            return PlanningExecutionResult(
                self.provider, logical_session_id, provider_session_id, provider_execution_id,
                TerminalState.FAILED, None, usage, tuple(events), {"stderr": safe_stderr},
                FailureClassification.AUTHENTICATION, detail,
            )
        payload, payload_error = self._read_final_payload(final_output_path, events)
        has_success = any(event.type in _SUCCESS_EVENTS for event in events)
        if malformed or failure_seen or not has_success or payload_error:
            detail = payload_error or ("provider emitted a failure event" if failure_seen else "terminal success event is missing")
            return PlanningExecutionResult(
                self.provider, logical_session_id, provider_session_id, provider_execution_id,
                TerminalState.FAILED, None, usage, tuple(events), {"stderr": safe_stderr},
                FailureClassification.AGENT_EXECUTION, sanitize_text(detail, self._secret_values),
            )
        return PlanningExecutionResult(
            self.provider, logical_session_id, provider_session_id, provider_execution_id,
            TerminalState.SUCCEEDED, payload, usage, tuple(events), {"stderr": safe_stderr},
        )


__all__ = ["CodexCliRuntime", "FINAL_OUTPUT_SCHEMA"]
