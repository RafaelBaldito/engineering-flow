"""Focused tests for the standalone environment preflight."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "env_preflight.py"
SPEC = importlib.util.spec_from_file_location("env_preflight_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


class FakeProbes:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git_worktree = True
        self.git_baseline = ""
        self.venv_executable = True
        self.python_payload: object = {"version": [3, 13, 15], "prefix": str(root / ".venv")}
        self.package_payload: object = {
            "distribution": str(root),
            "module": str(root / "src" / "engineering_flow" / "__init__.py"),
        }
        self.cli_returncode = 0

    def executable(self, path: Path) -> bool:
        return self.venv_executable or path.name != "python3"

    def command(self, args: list[str], *, cwd: Path, timeout: float = 2) -> object:
        if args[0] == "git" and "rev-parse" in args:
            if self.git_worktree:
                return preflight.CommandResult(0, f"{self.root}\ntrue\n", "")
            return preflight.CommandResult(128, "", "not a git repository")
        if args[0] == "git":
            return preflight.CommandResult(0, self.git_baseline, "")
        if "-c" in args:
            code = args[-1]
            payload = self.package_payload if "metadata.distribution" in code else self.python_payload
            return preflight.CommandResult(0, json.dumps(payload), "")
        return preflight.CommandResult(self.cli_returncode, "", "CLI failed" if self.cli_returncode else "")


class EnvironmentPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "src" / "engineering_flow").mkdir(parents=True)
        (self.root / "src" / "engineering_flow" / "__init__.py").touch()
        (self.root / ".venv" / "Scripts").mkdir(parents=True)
        (self.root / "pyproject.toml").write_text(
            """[project]
name = "engineering-flow"
version = "0.1.0"
requires-python = ">=3.13,<3.14"

[project.scripts]
engineering-flow = "engineering_flow.cli:main"
""",
            encoding="utf-8",
        )
        self.probes = FakeProbes(self.root)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_preflight(self, *, metadata_reader=preflight._read_metadata) -> list[object]:
        return preflight.Preflight(
            self.root,
            command=self.probes.command,
            executable=self.probes.executable,
            metadata_reader=metadata_reader,
        ).run()[0]

    @staticmethod
    def result(checks: list[object], check_id: str) -> object:
        return next(check for check in checks if check.id == check_id)

    def test_ready_with_dirty_baseline_is_ready_and_warns(self) -> None:
        self.probes.git_baseline = " M src/engineering_flow/cli.py\n"
        checks, summary, error = preflight.Preflight(
            self.root,
            command=self.probes.command,
            executable=self.probes.executable,
        ).run()

        self.assertFalse(error)
        self.assertEqual(self.result(checks, "git.baseline").status, preflight.WARN)
        self.assertEqual(summary["git"], "dirty")
        self.assertEqual(summary["git_warning"], "WARN git.baseline dirty=1 paths=src/engineering_flow/cli.py")

    def test_missing_root_markers_skips_dependent_checks(self) -> None:
        (self.root / "pyproject.toml").unlink()

        checks = self.run_preflight()

        self.assertEqual(self.result(checks, "repo.root").status, preflight.FAIL)
        self.assertEqual(self.result(checks, "repo.metadata").status, preflight.SKIP)
        self.assertEqual(self.result(checks, "cli.entrypoint").status, preflight.SKIP)

    def test_unreadable_or_invalid_metadata_is_preflight_error(self) -> None:
        checks, _, error = preflight.Preflight(
            self.root,
            command=self.probes.command,
            executable=self.probes.executable,
            metadata_reader=lambda _path: (_ for _ in ()).throw(ValueError("bad metadata")),
        ).run()

        self.assertTrue(error)
        self.assertEqual(self.result(checks, "repo.metadata").status, preflight.ERROR)

    def test_non_worktree_skips_baseline_without_blocking_runtime_checks(self) -> None:
        self.probes.git_worktree = False

        checks = self.run_preflight()

        self.assertEqual(self.result(checks, "git.worktree").status, preflight.FAIL)
        self.assertEqual(self.result(checks, "git.baseline").status, preflight.SKIP)
        self.assertEqual(self.result(checks, "cli.entrypoint").status, preflight.PASS)

    def test_windows_venv_is_identified_without_execution(self) -> None:
        self.probes.venv_executable = False
        (self.root / ".venv" / "Scripts" / "python.exe").touch()

        checks = self.run_preflight()

        self.assertEqual(self.result(checks, "venv.path").status, preflight.FAIL)
        self.assertIn("do not reuse a Windows venv", self.result(checks, "venv.path").message)
        self.assertEqual(self.result(checks, "python.contract").status, preflight.SKIP)

    def test_missing_linux_venv_is_a_failure(self) -> None:
        self.probes.venv_executable = False

        checks = self.run_preflight()

        self.assertEqual(self.result(checks, "venv.path").status, preflight.FAIL)
        self.assertIn("expected executable .venv/bin/python3", self.result(checks, "venv.path").message)

    def test_incompatible_python_blocks_package_and_cli(self) -> None:
        self.probes.python_payload = {"version": [3, 12, 3], "prefix": str(self.root / ".venv")}

        checks = self.run_preflight()

        self.assertEqual(self.result(checks, "python.contract").status, preflight.FAIL)
        self.assertEqual(self.result(checks, "package.binding").status, preflight.SKIP)
        self.assertEqual(self.result(checks, "cli.entrypoint").status, preflight.SKIP)

    def test_external_package_binding_blocks_cli(self) -> None:
        self.probes.package_payload = {"distribution": "/elsewhere", "module": "/elsewhere/engineering_flow/__init__.py"}

        checks = self.run_preflight()

        self.assertEqual(self.result(checks, "package.binding").status, preflight.FAIL)
        self.assertEqual(self.result(checks, "cli.entrypoint").status, preflight.SKIP)

    def test_unusable_cli_is_a_failure(self) -> None:
        self.probes.cli_returncode = 1

        checks = self.run_preflight()

        self.assertEqual(self.result(checks, "cli.entrypoint").status, preflight.FAIL)

    def test_requires_python_parser_rejects_unsupported_clause(self) -> None:
        with self.assertRaises(ValueError):
            preflight._parse_python_spec("~=3.13")

    def test_launcher_json_reports_current_checkout(self) -> None:
        launcher = Path(__file__).parents[1] / "scripts" / "env-preflight"
        completed = subprocess.run(
            [str(launcher), "--json"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        document = json.loads(completed.stdout)
        self.assertEqual(document["state"], "READY")
        self.assertEqual(document["root"], str(Path(__file__).parents[1]))
        self.assertEqual(document["exit_code"], 0)
        self.assertTrue(any(check["id"] == "cli.entrypoint" and check["status"] == "PASS" for check in document["checks"]))


if __name__ == "__main__":
    unittest.main()
