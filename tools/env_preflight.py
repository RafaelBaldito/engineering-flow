"""Read-only readiness checks for an Engineering Flow checkout.

This module deliberately runs under a host Python so it can describe a broken
repository virtual environment rather than depending on it to start.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


EXIT_READY = 0
EXIT_USAGE = 2
EXIT_NOT_READY = 20
EXIT_PREFLIGHT_ERROR = 70
TIMEOUT_SECONDS = 2
SCHEMA_VERSION = 1
MAX_DETAIL_LENGTH = 240
MAX_GIT_PATHS = 10

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
SKIP = "SKIP"
ERROR = "ERROR"


@dataclass(frozen=True)
class CheckResult:
    """One stable, renderable preflight fact."""

    id: str
    status: str
    message: str
    detail: str | None = None

    def document(self) -> dict[str, str]:
        result = asdict(self)
        return {key: value for key, value in result.items() if value is not None}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _run_command(args: Sequence[str], *, cwd: Path, timeout: float = TIMEOUT_SECONDS) -> CommandResult:
    """Run a bounded probe without a shell or inherited output streams."""
    try:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=-1,
            stdout=_as_text(exc.stdout),
            stderr=_as_text(exc.stderr),
            timed_out=True,
        )
    except OSError as exc:
        return CommandResult(returncode=-1, stdout="", stderr=str(exc))
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _detail(stderr: str) -> str | None:
    """Return one bounded diagnostic line, suitable for human and JSON output."""
    for line in stderr.splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            return cleaned[:MAX_DETAIL_LENGTH]
    return None


def _parse_python_spec(specification: str) -> list[tuple[str, tuple[int, ...]]]:
    clauses: list[tuple[str, tuple[int, ...]]] = []
    for clause in specification.split(","):
        match = re.fullmatch(r"\s*(>=|<=|>|<)\s*(\d+(?:\.\d+)*)\s*", clause)
        if match is None:
            raise ValueError("requires-python must use simple integer comparison clauses")
        clauses.append((match.group(1), tuple(int(part) for part in match.group(2).split("."))))
    if not clauses:
        raise ValueError("requires-python is empty")
    return clauses


def _version_matches(version: tuple[int, ...], clauses: Sequence[tuple[str, tuple[int, ...]]]) -> bool:
    for operator, required in clauses:
        length = max(len(version), len(required))
        actual_value = version + (0,) * (length - len(version))
        required_value = required + (0,) * (length - len(required))
        if operator == ">=" and not actual_value >= required_value:
            return False
        if operator == ">" and not actual_value > required_value:
            return False
        if operator == "<=" and not actual_value <= required_value:
            return False
        if operator == "<" and not actual_value < required_value:
            return False
    return True


def _skip(check_id: str, blocked_by: str) -> CheckResult:
    return CheckResult(check_id, SKIP, f"blocked_by={blocked_by}")


def _read_metadata(path: Path) -> dict[str, Any]:
    with path.open("rb") as metadata_file:
        document = tomllib.load(metadata_file)
    project = document.get("project")
    scripts = project.get("scripts") if isinstance(project, dict) else None
    if not isinstance(project, dict) or not isinstance(scripts, dict):
        raise ValueError("project metadata is incomplete")
    name = project.get("name")
    version = project.get("version")
    requires_python = project.get("requires-python")
    entrypoint = scripts.get("engineering-flow")
    if name != "engineering-flow" or not isinstance(version, str) or not version:
        raise ValueError("project name or version is not recognized")
    if not isinstance(requires_python, str) or not requires_python:
        raise ValueError("project requires-python is missing")
    if entrypoint != "engineering_flow.cli:main":
        raise ValueError("engineering-flow console entry point is not recognized")
    return {"version": version, "requires_python": requires_python}


class Preflight:
    """Evaluate preflight checks with injectible command and executable probes."""

    def __init__(
        self,
        root: Path,
        *,
        command: Callable[..., CommandResult] = _run_command,
        executable: Callable[[Path], bool] = _executable,
        metadata_reader: Callable[[Path], dict[str, Any]] = _read_metadata,
    ) -> None:
        self.root = root.resolve()
        self.command = command
        self.executable = executable
        self.metadata_reader = metadata_reader

    def run(self) -> tuple[list[CheckResult], dict[str, str], bool]:
        checks: list[CheckResult] = []
        summary: dict[str, str] = {}
        preflight_error = False

        metadata_path = self.root / "pyproject.toml"
        package_init = self.root / "src" / "engineering_flow" / "__init__.py"
        if metadata_path.is_file() and package_init.is_file():
            checks.append(CheckResult("repo.root", PASS, "checkout markers found"))
        else:
            checks.append(CheckResult("repo.root", FAIL, "expected pyproject.toml and src/engineering_flow/__init__.py; run from an intact Engineering Flow checkout"))
            checks.extend([
                _skip("repo.metadata", "repo.root"),
                _skip("git.worktree", "repo.root"),
                _skip("git.baseline", "git.worktree"),
                _skip("venv.path", "repo.root"),
                _skip("python.contract", "venv.path"),
                _skip("package.binding", "python.contract"),
                _skip("cli.entrypoint", "package.binding"),
            ])
            return checks, summary, preflight_error

        try:
            metadata = self.metadata_reader(metadata_path)
            clauses = _parse_python_spec(metadata["requires_python"])
        except (OSError, ValueError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
            checks.append(CheckResult("repo.metadata", ERROR, "unable to read recognized project metadata", _detail(str(exc))))
            preflight_error = True
            clauses = None
        else:
            checks.append(CheckResult("repo.metadata", PASS, "recognized engineering-flow metadata"))

        git_worktree = self._git_worktree()
        checks.append(git_worktree)
        if git_worktree.status == PASS:
            baseline, dirty_count, paths = self._git_baseline()
            checks.append(baseline)
            if baseline.status == WARN and not dirty_count:
                summary["git"] = "unknown"
                summary["git_warning"] = f"WARN git.baseline {baseline.message}"
            else:
                summary["git"] = "dirty" if dirty_count else "clean"
            if dirty_count:
                summary["git_warning"] = self._git_warning(dirty_count, paths)
        else:
            checks.append(_skip("git.baseline", "git.worktree"))

        venv = self.root / ".venv"
        interpreter = venv / "bin" / "python3"
        windows_interpreter = venv / "Scripts" / "python.exe"
        if self.executable(interpreter):
            checks.append(CheckResult("venv.path", PASS, "repository-local Linux/WSL interpreter found"))
        elif windows_interpreter.is_file():
            checks.append(CheckResult("venv.path", FAIL, "found .venv/Scripts/python.exe; do not reuse a Windows venv from Linux/WSL"))
        else:
            checks.append(CheckResult("venv.path", FAIL, "expected executable .venv/bin/python3; create a Linux/WSL Python 3.13 venv for this checkout"))

        python_check: CheckResult
        if clauses is None:
            python_check = _skip("python.contract", "repo.metadata")
        elif checks[-1].status != PASS:
            python_check = _skip("python.contract", "venv.path")
        else:
            python_check, version = self._python_contract(interpreter, clauses, metadata["requires_python"])
            if version:
                summary["python"] = version
        checks.append(python_check)

        if python_check.status != PASS:
            checks.append(_skip("package.binding", "python.contract"))
            checks.append(_skip("cli.entrypoint", "package.binding"))
            return checks, summary, preflight_error

        package_check = self._package_binding(interpreter)
        checks.append(package_check)
        if package_check.status != PASS:
            checks.append(_skip("cli.entrypoint", "package.binding"))
            return checks, summary, preflight_error
        summary["package"] = "editable"

        cli_check = self._cli_entrypoint()
        checks.append(cli_check)
        if cli_check.status == PASS:
            summary["cli"] = "ok"
        return checks, summary, preflight_error

    def _git_worktree(self) -> CheckResult:
        result = self.command(
            ["git", "-C", str(self.root), "rev-parse", "--show-toplevel", "--is-inside-work-tree"],
            cwd=self.root,
        )
        if result.timed_out:
            return CheckResult("git.worktree", FAIL, "Git worktree check timed out; verify this checkout's Git worktree")
        lines = result.stdout.splitlines()
        if result.returncode == 0 and len(lines) >= 2 and lines[1].strip() == "true":
            try:
                reported_root = Path(lines[0].strip()).resolve()
            except OSError:
                reported_root = Path("")
            if reported_root == self.root:
                return CheckResult("git.worktree", PASS, "Git worktree matches checkout root")
        return CheckResult("git.worktree", FAIL, "expected this checkout to be a Git worktree", _detail(result.stderr))

    def _git_baseline(self) -> tuple[CheckResult, int, list[str]]:
        result = self.command(["git", "-C", str(self.root), "status", "--porcelain=v1", "-uno"], cwd=self.root)
        if result.timed_out:
            return CheckResult("git.baseline", WARN, "Git baseline check timed out"), 0, []
        if result.returncode != 0:
            return CheckResult("git.baseline", WARN, "unable to read bounded Git baseline", _detail(result.stderr)), 0, []
        paths = [_porcelain_path(line) for line in result.stdout.splitlines() if line]
        return CheckResult("git.baseline", WARN if paths else PASS, "dirty tracked files" if paths else "clean tracked baseline"), len(paths), paths[:MAX_GIT_PATHS]

    def _python_contract(
        self, interpreter: Path, clauses: Sequence[tuple[str, tuple[int, ...]]], specification: str
    ) -> tuple[CheckResult, str | None]:
        code = "import json, sys; print(json.dumps({'version': list(sys.version_info[:3]), 'prefix': sys.prefix}))"
        result = self.command([str(interpreter), "-c", code], cwd=self.root)
        if result.timed_out:
            return CheckResult("python.contract", FAIL, "repository venv interpreter timed out; recreate .venv with a compatible Python"), None
        try:
            payload = json.loads(result.stdout)
            version_data = payload["version"]
            version = tuple(int(part) for part in version_data)
            prefix = Path(payload["prefix"]).resolve()
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, OSError):
            return CheckResult("python.contract", FAIL, f"unable to inspect repository venv interpreter; recreate .venv with a compatible Python", _detail(result.stderr)), None
        version_text = ".".join(str(part) for part in version)
        if result.returncode != 0 or not _version_matches(version, clauses):
            return CheckResult("python.contract", FAIL, f"found={version_text} required={specification}; recreate .venv with a compatible Python", _detail(result.stderr)), None
        if prefix != (self.root / ".venv").resolve():
            return CheckResult("python.contract", FAIL, "venv interpreter prefix does not resolve to .venv; recreate .venv for this checkout"), None
        return CheckResult("python.contract", PASS, f"Python {version_text} matches project contract"), version_text

    def _package_binding(self, interpreter: Path) -> CheckResult:
        code = """
import importlib
import json
from importlib import metadata
try:
    distribution = metadata.distribution('engineering-flow')
    module = importlib.import_module('engineering_flow')
except Exception as exc:
    print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}))
else:
    print(json.dumps({'distribution': str(distribution.locate_file('')), 'module': module.__file__}))
"""
        result = self.command([str(interpreter), "-c", code], cwd=self.root)
        if result.timed_out:
            return CheckResult("package.binding", FAIL, "package inspection timed out; install this checkout into its venv")
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError, json.JSONDecodeError):
            return CheckResult("package.binding", FAIL, "distribution engineering-flow is not installed in .venv; install this checkout into its venv", _detail(result.stderr))
        module_file = payload.get("module")
        if result.returncode != 0 or not isinstance(module_file, str):
            return CheckResult("package.binding", FAIL, "distribution engineering-flow is not installed in .venv; install this checkout into its venv", _detail(str(payload.get("message", "")) or result.stderr))
        if not _within(Path(module_file), self.root / "src" / "engineering_flow"):
            return CheckResult("package.binding", FAIL, "engineering-flow is bound outside this checkout; install this checkout into its venv")
        return CheckResult("package.binding", PASS, "engineering-flow is bound to checkout source")

    def _cli_entrypoint(self) -> CheckResult:
        cli = self.root / ".venv" / "bin" / "engineering-flow"
        if not self.executable(cli):
            return CheckResult("cli.entrypoint", FAIL, "expected executable .venv/bin/engineering-flow; reinstall this checkout into its venv")
        result = self.command([str(cli), "--help"], cwd=self.root)
        if result.timed_out:
            return CheckResult("cli.entrypoint", FAIL, ".venv/bin/engineering-flow timed out; reinstall this checkout into its venv")
        if result.returncode != 0:
            return CheckResult("cli.entrypoint", FAIL, ".venv/bin/engineering-flow did not run successfully; reinstall this checkout into its venv", _detail(result.stderr))
        return CheckResult("cli.entrypoint", PASS, "console entry point is usable")

    @staticmethod
    def _git_warning(count: int, paths: Sequence[str]) -> str:
        listed = ",".join(paths)
        remainder = f"+{count - len(paths)} more" if count > len(paths) else ""
        suffix = f",{remainder}" if remainder else ""
        return f"WARN git.baseline dirty={count} paths={listed}{suffix}"


def _porcelain_path(line: str) -> str:
    """Extract a bounded display path from porcelain v1 without parsing a diff."""
    path = line[3:].strip() if len(line) > 3 else line.strip()
    return " ".join(path.split())[:MAX_DETAIL_LENGTH]


def _report(root: Path) -> tuple[dict[str, Any], list[CheckResult]]:
    checks, summary, preflight_error = Preflight(root).run()
    failures = [check for check in checks if check.status == FAIL]
    if preflight_error or any(check.status == ERROR for check in checks):
        state, exit_code = "PREFLIGHT_ERROR", EXIT_PREFLIGHT_ERROR
    elif failures:
        state, exit_code = "NOT_READY", EXIT_NOT_READY
    else:
        state, exit_code = "READY", EXIT_READY
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "root": str(root),
        "checks": [check.document() for check in checks],
        "exit_code": exit_code,
    }
    document.update(summary)
    return document, checks


def _render_human(document: dict[str, Any], checks: Sequence[CheckResult]) -> str:
    state = document["state"]
    if state == "READY":
        line = (
            f"READY root={document['root']} python={document.get('python', 'unknown')} "
            f"package={document.get('package', 'unknown')} cli={document.get('cli', 'unknown')} git={document.get('git', 'unknown')}"
        )
        warning = document.get("git_warning")
        return "\n".join([line, warning]) if warning else line
    if state == "NOT_READY":
        failures = [check for check in checks if check.status == FAIL]
        lines = [f"NOT_READY failed={len(failures)}"]
        lines.extend(f"FAIL {check.id} {check.message}" for check in failures)
        lines.extend(f"SKIP {check.id} {check.message}" for check in checks if check.status == SKIP)
        return "\n".join(lines)
    errors = [check for check in checks if check.status == ERROR]
    lines = ["PREFLIGHT_ERROR"]
    lines.extend(f"ERROR {check.id} {check.message}" for check in errors)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(argument not in {"--json"} for argument in arguments) or len(arguments) > 1:
        print("USAGE ./scripts/env-preflight [--json]", file=sys.stderr)
        return EXIT_USAGE
    root = Path(__file__).resolve().parent.parent
    try:
        document, checks = _report(root)
    except Exception:
        document = {
            "schema_version": SCHEMA_VERSION,
            "state": "PREFLIGHT_ERROR",
            "root": str(root),
            "checks": [CheckResult("preflight.internal", ERROR, "unexpected preflight failure").document()],
            "exit_code": EXIT_PREFLIGHT_ERROR,
        }
        checks = [CheckResult("preflight.internal", ERROR, "unexpected preflight failure")]
    if arguments == ["--json"]:
        print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    else:
        print(_render_human(document, checks))
    return int(document["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
