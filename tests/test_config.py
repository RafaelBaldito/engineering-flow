import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.cli import INITIAL_CONFIG, main  # noqa: E402
from engineering_flow.config import load_config  # noqa: E402
from engineering_flow.domain import ValidationFailure  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = Path(self.tempdir.name) / "repo"
        self.repository.mkdir()
        subprocess.run(["git", "init", str(self.repository)], check=True, capture_output=True)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_init_writes_normative_config_and_preserves_gitignore(self):
        gitignore = self.repository / ".gitignore"
        gitignore.write_text("build/\n", encoding="utf-8")
        self.assertEqual(main(["init", "--repo", str(self.repository)]), 0)
        self.assertEqual((self.repository / ".engineering-flow" / "config.toml").read_text(encoding="utf-8"), INITIAL_CONFIG)
        self.assertEqual(gitignore.read_text(encoding="utf-8"), "build/\n.engineering-flow/\n")
        config = load_config(self.repository)
        self.assertEqual(config.provider_name, "codex-cli")
        self.assertEqual(config.timeout_seconds, 1800)
        self.assertTrue(config.allow_read_only_planning)
        self.assertEqual(set(config.approval_policies), {"prd", "techspec", "task_plan"})
        self.assertEqual(main(["init", "--repo", str(self.repository)]), 0)

    def test_invalid_configuration_is_rejected(self):
        application = self.repository / ".engineering-flow"
        application.mkdir()
        (application / "config.toml").write_text(
            "[provider]\nname='codex-cli'\ncommand='codex'\ntimeout_seconds=0\n"
            "[approval]\nprd='required'\ntechspec='required'\ntask_plan='required'\n"
            "[safety]\nallow_read_only_planning=true\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValidationFailure):
            load_config(self.repository)

    def test_non_git_repository_is_rejected(self):
        other = Path(self.tempdir.name) / "not-a-repo"
        other.mkdir()
        with self.assertRaises(ValidationFailure):
            load_config(other)

    def test_application_directory_link_cannot_escape_repository(self):
        external = Path(self.tempdir.name) / "external-workspace"
        external.mkdir()
        application = self.repository / ".engineering-flow"
        try:
            application.symlink_to(external, target_is_directory=True)
        except OSError as exc:
            if sys.platform != "win32":
                self.skipTest(f"directory links are unavailable: {exc}")
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(application), str(external)],
                capture_output=True,
                text=True,
                check=False,
            )
            if junction.returncode != 0:
                self.skipTest(f"directory links are unavailable: {junction.stderr.strip() or exc}")

        with self.assertRaisesRegex(ValidationFailure, "application directory escapes the repository"):
            load_config(self.repository)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["init", "--repo", str(self.repository)]), 2)
        self.assertFalse((external / "config.toml").exists())
        self.assertFalse((external / "workflows.sqlite3").exists())
        self.assertFalse((self.repository / ".gitignore").exists())

    def test_database_file_link_cannot_escape_application_workspace(self):
        application = self.repository / ".engineering-flow"
        application.mkdir()
        (application / "config.toml").write_text(INITIAL_CONFIG, encoding="utf-8")
        external_workspace = Path(self.tempdir.name) / "external-workspace"
        external_workspace.mkdir()
        external_database = external_workspace / "workflows.sqlite3"
        database_link = application / "workflows.sqlite3"
        try:
            database_link.symlink_to(external_database)
        except OSError as exc:
            if sys.platform != "win32":
                self.skipTest(f"file links are unavailable: {exc}")
            junction = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(database_link), str(external_workspace)],
                capture_output=True,
                text=True,
                check=False,
            )
            if junction.returncode != 0:
                self.skipTest(f"file links are unavailable: {junction.stderr.strip() or exc}")

        with self.assertRaisesRegex(ValidationFailure, "database path escapes the application directory"):
            load_config(self.repository)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["init", "--repo", str(self.repository)]), 2)
        self.assertFalse(external_database.exists())

    def test_gitignore_link_cannot_escape_repository(self):
        external_gitignore = Path(self.tempdir.name) / "external-gitignore"
        external_gitignore.write_text("external-entry/\n", encoding="utf-8")
        gitignore_link = self.repository / ".gitignore"
        try:
            gitignore_link.symlink_to(external_gitignore)
        except OSError as exc:
            self.skipTest(f"file links are unavailable: {exc}")

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["init", "--repo", str(self.repository)]), 2)
        self.assertEqual(external_gitignore.read_text(encoding="utf-8"), "external-entry/\n")

    def test_credentials_and_write_capable_planning_are_rejected(self):
        application = self.repository / ".engineering-flow"
        application.mkdir()
        (application / "config.toml").write_text(
            "[provider]\nname='codex-cli'\ncommand='codex'\ntimeout_seconds=1800\n"
            "[approval]\nprd='required'\ntechspec='required'\ntask_plan='required'\n"
            "[safety]\nallow_read_only_planning=false\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValidationFailure):
            load_config(self.repository)

    def test_provider_command_cannot_include_credential_argument_or_reach_snapshot(self):
        application = self.repository / ".engineering-flow"
        application.mkdir()
        (application / "config.toml").write_text(
            "[provider]\nname='codex-cli'\ncommand='codex --api-key this-is-a-private-value'\ntimeout_seconds=1800\n"
            "[approval]\nprd='required'\ntechspec='required'\ntask_plan='required'\n"
            "[safety]\nallow_read_only_planning=true\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationFailure, "credential"):
            load_config(self.repository)

        feature = self.repository / "feature.md"
        feature.write_text("feature", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(["run", "--repo", str(self.repository), "--feature-file", str(feature)]), 2
            )
        self.assertFalse((application / "workflows.sqlite3").exists())
        (application / "config.toml").write_text(
            "[provider]\nname='codex-cli'\ncommand='codex'\ntimeout_seconds=1800\n"
            "[approval]\nprd='required'\ntechspec='required'\ntask_plan='required'\n"
            "[safety]\nallow_read_only_planning=true\n[provider.extra]\ntoken='secret'\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValidationFailure):
            load_config(self.repository)


if __name__ == "__main__":
    unittest.main()
